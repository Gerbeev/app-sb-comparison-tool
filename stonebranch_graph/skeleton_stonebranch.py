"""Stonebranch raw-record to Skeleton builder.

Exit-code qualifier grammar (task 03)
--------------------------------------
UC workflow-edge exit-code conditions are normalized to the same qualifier
grammar the JIL side emits (``jil_condition._exitcode_expr``), so a strict-level
comparison of an ``EXIT`` predicate is byte-identical for the same numeric
condition on both sides:

- A bare integer (``4``) or an explicit equality (``==4`` / ``=4``) normalizes
  to ``"=4"``.
- Comparison operators (``>=N``, ``<=N``, ``>N``, ``<N``, ``!=N``) normalize to
  the same operator with ``==`` collapsed to ``=``, matching
  ``jil_condition._exitcode_expr``.
- A comma list (``1,2,3``) normalizes to a sorted, deduped list of equalities
  joined by commas (``"=1,=2,=3"``). JIL has no multi-value exit-code literal,
  so this form only round-trips within the Stonebranch side, but it is
  deterministic and documented rather than silently dropped.
- A range (``1-4``) normalizes to ``"1-4"`` with bounds sorted ascending. JIL
  has no range literal either; the qualifier is preserved verbatim at strict
  level so the condition is visible instead of silently degraded.

Any exit-code value that does not match one of the shapes above is treated as
an **unmapped condition** (see :func:`_edge_predicate`): it is *not* silently
coerced to ``SUCCESS`` without a trace. The edge still uses ``SUCCESS`` for
graph connectivity, but the raw text is recorded on the dependent node's
``meta["unmapped_conditions"]`` and surfaced by ``skeleton_compare`` as a risk
and a dedicated report section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from stonebranch_graph import expr
from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.domain import (
    KIND_FILE_WATCHER,
    KIND_TASK,
    KIND_WORKFLOW,
    REL_DEPENDS_ON_DONE,
    REL_DEPENDS_ON_FAILURE,
    REL_DEPENDS_ON_TERMINATED,
)
from stonebranch_graph.normalizers import command_hash, semantic_command_hash
from stonebranch_graph.parsers.stonebranch_json import (
    WORKFLOW_EDGE_KEYS,
    WORKFLOW_NATIVE_TYPES,
    WORKFLOW_VERTEX_KEYS,
    RawRecord,
    StonebranchJsonParser,
    StonebranchRawExport,
)
from stonebranch_graph.skeleton import (
    EXT_PREFIX,
    KIND_CONTAINER,
    KIND_UNIT,
    Skeleton,
    SkeletonNode,
    child_id,
    external_id,
    logical_leaf,
)

from .alias import AliasTable

TASK_MONITOR_TYPE_TOKENS = {"taskmonitor", "taskmonitortask"}
SLEEP_TYPE_TOKENS = {"sleep", "sleeptask", "timer"}
TASK_MONITOR_TARGET_KEYS = (
    "taskMonitoredName",
    "taskName",
    "taskMonName",
    "monitoredTask",
)
# UC export field variance (IMPLEMENTATION_PLAN.md §5): any of these keys may
# carry the workflow the monitored task instance lives in, used to disambiguate
# a monitor target when the monitored task name is reused across sub-workflow
# instances (N6, task 06).
TASK_MONITOR_WORKFLOW_KEYS = (
    "taskMonitoredWorkflow",
    "taskMonitoredWorkflowName",
    "monitoredWorkflow",
    "monitoredWorkflowName",
    "taskMonWorkflow",
    "workflowName",
)
TASK_MONITOR_STATUS_KEYS = (
    "statuses",
    "status",
    "taskMonStatus",
    "monitorStatus",
)
COMMAND_KEYS = ("command", "Command", "script", "Script")

SOURCE_ENDPOINT_KEYS = (
    "sourceId",
    "source_id",
    "sourceVertex",
    "source_vertex",
    "source",
    "from",
    "fromVertex",
)
TARGET_ENDPOINT_KEYS = (
    "targetId",
    "target_id",
    "targetVertex",
    "target_vertex",
    "target",
    "to",
    "toVertex",
)
EDGE_CONDITION_KEYS = ("condition", "Condition", "conditionType", "condition_type", "status")
EXIT_CODE_KEYS = ("exitCodes", "exit_codes", "exitCode", "exit_code", "value")


@dataclass(frozen=True)
class _Definition:
    native_name: str
    record: RawRecord


@dataclass
class _NodeSpec:
    id: str
    kind: str
    parent: str | None
    native_name: str
    record: RawRecord | None
    trigger_pairs: list[tuple[str, str, str]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def build_stonebranch_skeleton(
    raw: StonebranchRawExport,
    *,
    alias: AliasTable | None = None,
    config: AnalyzerConfig,
) -> Skeleton:
    """Build a canonical skeleton from raw Universal Controller export records."""

    return _StonebranchSkeletonBuilder(raw=raw, alias=alias, config=config).build()


class _StonebranchSkeletonBuilder:
    def __init__(
        self,
        *,
        raw: StonebranchRawExport,
        alias: AliasTable | None,
        config: AnalyzerConfig,
    ) -> None:
        self.raw = raw
        self.alias = alias
        self.parser = StonebranchJsonParser(config=config)
        self.skeleton = Skeleton(warnings=list(raw.warnings))
        self.workflow_defs: dict[str, _Definition] = {}
        self.task_defs: dict[str, _Definition] = {}
        self.workflow_order: list[str] = []
        self.task_order: list[str] = []
        self.referenced_workflow_names: set[str] = set()
        self.referenced_task_names: set[str] = set()
        self.specs: dict[str, _NodeSpec] = {}

    def build(self) -> Skeleton:
        self._register_definitions()
        self._index_workflow_references()
        self._expand_top_level_workflows()
        self._add_root_tasks()
        self._emit_nodes()
        self.skeleton.validate()
        return self.skeleton

    def _register_definitions(self) -> None:
        for record in self.raw.records:
            if _is_workflow_record(record):
                self._register_definition(
                    record, self.workflow_defs, self.workflow_order, "workflow"
                )
            elif _is_task_record(record):
                self._register_definition(record, self.task_defs, self.task_order, "task")

    def _register_definition(
        self,
        record: RawRecord,
        registry: dict[str, _Definition],
        order: list[str],
        label: str,
    ) -> None:
        key = _name_key(record.name)
        if key in registry:
            self.skeleton.warnings.append(
                f"Duplicate Stonebranch {label} definition {record.name!r}: keeping first."
            )
            return
        registry[key] = _Definition(native_name=record.name, record=record)
        order.append(key)

    def _index_workflow_references(self) -> None:
        for workflow_key in self.workflow_order:
            definition = self.workflow_defs[workflow_key]
            for vertex in self._workflow_vertices(definition.record.data):
                name = self.parser._workflow_task_name(vertex)
                if not name:
                    continue
                key = _name_key(name)
                if key in self.workflow_defs and key != workflow_key:
                    self.referenced_workflow_names.add(key)
                elif key in self.task_defs:
                    self.referenced_task_names.add(key)

    def _expand_top_level_workflows(self) -> None:
        top_level = [
            key for key in self.workflow_order if key not in self.referenced_workflow_names
        ]
        if not top_level and self.workflow_order:
            top_level = list(self.workflow_order)
        for key in top_level:
            self._expand_workflow(self.workflow_defs[key], parent_id=None, stack={})

    def _add_root_tasks(self) -> None:
        for key in self.task_order:
            if key not in self.referenced_task_names:
                self._add_task_instance(self.task_defs[key], parent_id=None)

    def _expand_workflow(
        self,
        definition: _Definition,
        *,
        parent_id: str | None,
        stack: dict[str, str],
    ) -> str:
        key = _name_key(definition.native_name)
        if key in stack:
            self.skeleton.warnings.append(
                "Recursive Stonebranch workflow reference stopped: "
                + " -> ".join((*stack.keys(), key))
            )
            return stack[key]

        node_id = self._node_id(definition.native_name, parent_id)
        self._ensure_spec(
            node_id=node_id,
            kind=KIND_CONTAINER,
            parent_id=parent_id,
            native_name=definition.native_name,
            record=definition.record,
        )

        next_stack = {**stack, key: node_id}
        vertex_ids: dict[str, str] = {}
        vertex_names: dict[str, str] = {}
        for vertex in self._workflow_vertices(definition.record.data):
            child_name = self.parser._workflow_task_name(vertex)
            if not child_name:
                continue
            child_key = _name_key(child_name)
            if child_key in self.workflow_defs:
                child_node_id = self._expand_workflow(
                    self.workflow_defs[child_key],
                    parent_id=node_id,
                    stack=next_stack,
                )
            elif child_key in self.task_defs:
                child_node_id = self._add_task_instance(
                    self.task_defs[child_key], parent_id=node_id
                )
            else:
                child_node_id = self._add_synthetic_task(child_name, parent_id=node_id)

            vertex_id = self._vertex_id(vertex)
            if vertex_id:
                vertex_ids[vertex_id] = child_node_id
            vertex_names.setdefault(child_key, child_node_id)

        for edge in self._workflow_edges(definition.record.data):
            source_id = self._edge_endpoint(edge, vertex_ids, vertex_names, SOURCE_ENDPOINT_KEYS)
            target_id = self._edge_endpoint(edge, vertex_ids, vertex_names, TARGET_ENDPOINT_KEYS)
            if not source_id or not target_id or source_id == target_id:
                self.skeleton.warnings.append(
                    "Skipped Stonebranch workflow edge without resolvable endpoints in "
                    f"{definition.record.source_file}."
                )
                continue
            predicate, qualifier, unmapped = self._edge_predicate(edge)
            if unmapped:
                self.skeleton.warnings.append(
                    f"Unknown Stonebranch workflow edge condition {unmapped!r} in "
                    f"{definition.record.source_file}; using SUCCESS."
                )
                self.specs[target_id].meta.setdefault("unmapped_conditions", []).append(
                    {
                        "raw": unmapped,
                        "source_id": source_id,
                        "source_file": definition.record.source_file,
                    }
                )
            self.specs[target_id].trigger_pairs.append((source_id, predicate, qualifier))

        return node_id

    def _add_task_instance(self, definition: _Definition, *, parent_id: str | None) -> str:
        node_id = self._node_id(definition.native_name, parent_id)
        self._ensure_spec(
            node_id=node_id,
            kind=KIND_UNIT,
            parent_id=parent_id,
            native_name=definition.native_name,
            record=definition.record,
        )
        return node_id

    def _add_synthetic_task(self, native_name: str, *, parent_id: str | None) -> str:
        node_id = self._node_id(native_name, parent_id)
        self._ensure_spec(
            node_id=node_id,
            kind=KIND_UNIT,
            parent_id=parent_id,
            native_name=native_name,
            record=None,
        )
        self.specs[node_id].meta["synthetic"] = True
        self.skeleton.warnings.append(
            f"Stonebranch workflow vertex {native_name!r} has no matching task or workflow "
            "definition; created synthetic unit."
        )
        return node_id

    def _ensure_spec(
        self,
        *,
        node_id: str,
        kind: str,
        parent_id: str | None,
        native_name: str,
        record: RawRecord | None,
    ) -> _NodeSpec:
        if node_id in self.specs:
            return self.specs[node_id]
        spec = _NodeSpec(
            id=node_id,
            kind=kind,
            parent=parent_id,
            native_name=native_name,
            record=record,
            meta=self._base_meta(native_name, record, kind),
        )
        self.specs[node_id] = spec
        return spec

    def _base_meta(
        self, native_name: str, record: RawRecord | None, kind: str
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {"src": "stonebranch", "native": native_name}
        if record is None:
            return meta
        meta["type"] = record.native_type
        meta["source_file"] = record.source_file
        token = _type_token(record)
        if token in TASK_MONITOR_TYPE_TOKENS:
            meta["plumbing"] = "task_monitor"
        elif token in SLEEP_TYPE_TOKENS:
            meta["plumbing"] = "sleep"
        elif (
            kind != KIND_CONTAINER
            and self.alias is not None
            and self.alias.is_plumbing("stonebranch", native_name)
        ):
            # N3 (mapping-theory.md §5): the alias `plumbing` list marks
            # dummy/gate tasks by name on both systems, not just Stonebranch
            # objects that happen to be typed Task Monitor/Sleep. Containers
            # (workflows) are never erased regardless of this marker; see
            # skeleton_normalize._demote_marked_containers.
            meta["plumbing"] = "alias"
        command = _first_command(record.data)
        if command:
            meta["command_hash"] = command_hash(command)
            meta["semantic_command_hash"] = semantic_command_hash(command)
        return meta

    def _node_id(self, native_name: str, parent_id: str | None) -> str:
        logical = _alias_logical_id(self.alias, native_name)
        if logical is not None and "/" in logical.strip("/"):
            return logical.strip("/")
        leaf = logical.strip("/").rsplit("/", 1)[-1] if logical else logical_leaf(native_name)
        return child_id(parent_id, leaf)

    def _workflow_vertices(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            item
            for item in self.parser._first_list(data, WORKFLOW_VERTEX_KEYS)
            if isinstance(item, dict)
        ]

    def _workflow_edges(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            item
            for item in self.parser._first_list(data, WORKFLOW_EDGE_KEYS)
            if isinstance(item, dict)
        ]

    def _vertex_id(self, vertex: dict[str, Any]) -> str:
        return self.parser._structure_value(
            vertex.get("vertexId")
            if "vertexId" in vertex
            else vertex.get("vertex_id", vertex.get("id"))
        )

    def _edge_endpoint(
        self,
        edge: dict[str, Any],
        vertex_ids: dict[str, str],
        vertex_names: dict[str, str],
        keys: tuple[str, ...],
    ) -> str | None:
        ref: Any = None
        for key in keys:
            if key in edge and edge[key] is not None:
                ref = edge[key]
                break
        if ref is None:
            return None

        task_name = ""
        vertex_id = ""
        if isinstance(ref, dict):
            for key in ("taskName", "task_name", "task", "name"):
                candidate = self.parser._structure_value(ref.get(key))
                if candidate:
                    task_name = candidate
                    break
            vertex_id = self.parser._structure_value({"value": ref.get("value", ref.get("id"))})
        else:
            token = self.parser._structure_value(ref)
            if token in vertex_ids or token.isdigit():
                vertex_id = token
            else:
                task_name = token

        if vertex_id and vertex_id in vertex_ids:
            return vertex_ids[vertex_id]
        if task_name:
            return vertex_names.get(_name_key(task_name))
        return None

    def _edge_predicate(self, edge: dict[str, Any]) -> tuple[str, str, str | None]:
        """Return ``(predicate, qualifier, unmapped_raw)`` for a workflow edge.

        ``unmapped_raw`` is ``None`` when the condition was recognized. When it
        is not ``None``, the edge still uses ``SUCCESS`` for graph connectivity
        (so topology stays connected), but the caller must record the raw text
        as an unmapped condition rather than treat it as a silent, indistinguishable
        success dependency (task 03).
        """

        exit_qualifier, exit_unparsed = self._exit_qualifier(edge)
        if exit_qualifier:
            return expr.EXIT, exit_qualifier, None
        if exit_unparsed:
            return expr.SUCCESS, "", exit_unparsed

        relation = self.parser._workflow_edge_relation(edge)
        if relation == REL_DEPENDS_ON_DONE:
            return expr.DONE, "", None
        if relation == REL_DEPENDS_ON_FAILURE:
            return expr.FAILURE, "", None
        if relation == REL_DEPENDS_ON_TERMINATED:
            return expr.TERMINATED, "", None
        raw = self._edge_condition_text(edge)
        if raw and not _mentions_known_status(raw):
            return expr.SUCCESS, "", raw
        return expr.SUCCESS, "", None

    def _edge_condition_text(self, edge: dict[str, Any]) -> str:
        return " ".join(
            value for key in EDGE_CONDITION_KEYS if (value := _string_value(edge.get(key)))
        )

    def _exit_qualifier(self, edge: dict[str, Any]) -> tuple[str, str]:
        """Return ``(qualifier, unparsed_raw)`` for an edge's exit-code fields.

        Only one of the two return values is non-empty: a value that parses
        under the grammar documented in the module docstring returns
        ``(qualifier, "")``; a present-but-unrecognized exit-code value returns
        ``("", raw_text)`` so the caller can flag it instead of silently
        defaulting to ``SUCCESS``.
        """

        condition_text = self._edge_condition_text(edge).lower()
        for key in EXIT_CODE_KEYS:
            if key == "value" and "exit" not in condition_text:
                continue
            raw = _string_value(edge.get(key))
            if not raw:
                continue
            parsed = _parse_exit_codes_value(raw)
            if parsed:
                return parsed, ""
            return "", raw
        return "", ""

    def _emit_nodes(self) -> None:
        instance_index = self._instance_index()
        for node_id in sorted(self.specs):
            spec = self.specs[node_id]
            meta = dict(spec.meta)
            if meta.get("plumbing") == "task_monitor" and spec.record is not None:
                meta["monitor"] = self._monitor_payload(spec, instance_index, meta)
            self.skeleton.add_node(
                SkeletonNode(
                    id=spec.id,
                    kind=spec.kind,
                    parent=spec.parent,
                    trigger=_trigger_expression(spec.trigger_pairs),
                    completion=None,
                    meta=meta,
                ),
                merge_allowed=bool(self.alias and self.alias.is_merge_allowed("stonebranch", spec.id)),
            )

    def _instance_index(self) -> dict[str, list[str]]:
        index: dict[str, list[str]] = {}
        for spec in self.specs.values():
            index.setdefault(_name_key(spec.native_name), []).append(spec.id)
        for ids in index.values():
            ids.sort()
        return index

    def _monitor_payload(
        self,
        spec: _NodeSpec,
        instance_index: dict[str, list[str]],
        meta: dict[str, Any],
    ) -> dict[str, str | bool]:
        assert spec.record is not None
        target_name = _first_structure_value(
            spec.record.data,
            TASK_MONITOR_TARGET_KEYS,
            self.parser,
        )
        predicate = self._monitor_predicate(spec)
        if not target_name:
            self.skeleton.warnings.append(
                f"Stonebranch task monitor {spec.native_name!r} has no monitored task name."
            )
            target = external_id(None, "unknown")
            self.skeleton.externals.add(target)
            self.skeleton.ambiguous_externals.add(target)
            return {"target": target, "predicate": predicate, "external": True}

        candidates = instance_index.get(_name_key(target_name), [])
        if not candidates:
            target = self._external_target_id(target_name)
            self.skeleton.externals.add(target)
            return {"target": target, "predicate": predicate, "external": True}

        # N6: the same task name can exist as several path-qualified instances
        # (sub-workflows are inlined per use). Prefer an exact path match via a
        # workflow-scoping hint from the export, then same-parent, then a
        # documented deterministic fallback (task 06). Any fallback beyond an
        # unambiguous single candidate is recorded as a first-class risk signal
        # rather than a buried warning, because a wrong pick silently mis-wires
        # a real dependency.
        workflow_hint = _first_structure_value(
            spec.record.data, TASK_MONITOR_WORKFLOW_KEYS, self.parser
        )
        if workflow_hint:
            hinted = self._match_by_workflow_hint(candidates, workflow_hint)
            if hinted is not None:
                return {"target": hinted, "predicate": predicate, "external": False}

        same_parent = [
            candidate for candidate in candidates if self.specs[candidate].parent == spec.parent
        ]
        pool = same_parent or candidates
        if len(pool) == 1:
            return {"target": pool[0], "predicate": predicate, "external": False}

        chosen = pool[0]
        meta["ambiguous_monitor_target"] = {"name": target_name, "candidates": list(pool)}
        self.skeleton.warnings.append(
            f"Ambiguous Stonebranch task monitor target {target_name!r} near "
            f"{spec.id!r}; using {chosen!r} (deterministic fallback: sorted id order; "
            "no workflow hint disambiguated it)."
        )
        return {"target": chosen, "predicate": predicate, "external": False}

    def _match_by_workflow_hint(self, candidates: list[str], workflow_hint: str) -> str | None:
        """Return the single candidate whose ancestor chain names ``workflow_hint``.

        Returns ``None`` when zero or more than one candidate matches, so the
        caller falls back to same-parent/global resolution instead of guessing.
        """

        hint_key = _name_key(workflow_hint)
        matches: list[str] = []
        for candidate in candidates:
            ancestor_id = self.specs[candidate].parent
            while ancestor_id is not None:
                ancestor = self.specs.get(ancestor_id)
                if ancestor is None:
                    break
                if _name_key(ancestor.native_name) == hint_key:
                    matches.append(candidate)
                    break
                ancestor_id = ancestor.parent
        if len(matches) == 1:
            return matches[0]
        return None

    def _external_target_id(self, target_name: str) -> str:
        """Return the canonical external id for a monitor target not in this graph.

        Prefers an alias entry that explicitly maps the native name to an
        ``ext:<ns>/<leaf>`` id (task 05: unify the external grammar and let the
        alias table state cross-instance identity). Without such an alias, the
        namespace cannot be known, so the id degenerates to a bare
        ``ext:<leaf>`` and is flagged as namespace-ambiguous rather than
        silently assumed to match (or not match) the AutoSys side.
        """

        logical = _alias_logical_id(self.alias, target_name)
        if logical:
            stripped = logical.strip("/")
            if stripped.startswith(EXT_PREFIX) and "/" in stripped[len(EXT_PREFIX) :]:
                return stripped

        target = external_id(None, logical_leaf(target_name))
        self.skeleton.ambiguous_externals.add(target)
        self.skeleton.warnings.append(
            f"Stonebranch task monitor external target {target_name!r} has no "
            "alias-configured namespace (expected an 'ext:<ns>/<leaf>' alias entry); "
            f"external id {target!r} is namespace-ambiguous."
        )
        return target

    def _monitor_predicate(self, spec: _NodeSpec) -> str:
        assert spec.record is not None
        status = _first_structure_value(
            spec.record.data,
            TASK_MONITOR_STATUS_KEYS,
            self.parser,
        )
        predicate = _status_predicate(status)
        if predicate is None:
            if status:
                self.skeleton.warnings.append(
                    f"Unknown Stonebranch task monitor status {status!r} on "
                    f"{spec.native_name!r}; using SUCCESS."
                )
            return expr.SUCCESS
        return predicate


_EXIT_OP_RE = re.compile(r"(>=|<=|!=|==|=|>|<)\s*([+-]?\d+)\Z")
_EXIT_RANGE_RE = re.compile(r"(\d+)\s*-\s*(\d+)\Z")
_EXIT_INT_RE = re.compile(r"[+-]?\d+\Z")


def _parse_exit_codes_value(raw: str) -> str:
    """Parse a UC exit-code field value into the documented qualifier grammar.

    Returns ``""`` when ``raw`` does not match any recognized shape, so the
    caller can flag it as an unmapped condition instead of guessing.
    """

    text = raw.strip()
    if not text:
        return ""

    match = _EXIT_OP_RE.match(text)
    if match:
        op, number = match.groups()
        op = "=" if op == "==" else op
        return f"{op}{int(number)}"

    match = _EXIT_RANGE_RE.match(text)
    if match:
        low, high = sorted((int(match.group(1)), int(match.group(2))))
        return f"{low}-{high}"

    if "," in text:
        parts = [part.strip() for part in text.split(",") if part.strip()]
        if parts and all(_EXIT_INT_RE.match(part) for part in parts):
            numbers = sorted({int(part) for part in parts})
            return ",".join(f"={number}" for number in numbers)
        return ""

    if _EXIT_INT_RE.match(text):
        return f"={int(text)}"

    return ""


def _trigger_expression(pairs: list[tuple[str, str, str]]) -> expr.Expr | None:
    atoms = expr.fold_done(pairs)
    if not atoms:
        return None
    if len(atoms) == 1:
        return atoms[0]
    return expr.canonicalize(expr.And(atoms))


def _is_workflow_record(record: RawRecord) -> bool:
    return record.kind == KIND_WORKFLOW or _type_token(record) in WORKFLOW_NATIVE_TYPES


def _is_task_record(record: RawRecord) -> bool:
    return record.kind in {KIND_TASK, KIND_FILE_WATCHER}


def _type_token(record: RawRecord) -> str:
    return StonebranchJsonParser._normalized_type_token(record.native_type)


def _name_key(name: str) -> str:
    return str(name).strip().lower()


def _alias_logical_id(alias: AliasTable | None, native_name: str) -> str | None:
    if alias is None:
        return None
    logical = alias.logical_id("stonebranch", native_name)
    return logical or None


def _first_command(data: dict[str, Any]) -> str:
    for key in COMMAND_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _first_structure_value(
    data: dict[str, Any],
    keys: tuple[str, ...],
    parser: StonebranchJsonParser,
) -> str:
    for key in keys:
        value = _string_value(data.get(key), parser=parser)
        if value:
            return value
    return ""


def _string_value(value: Any, parser: StonebranchJsonParser | None = None) -> str:
    if isinstance(value, list):
        values = [_string_value(item, parser=parser) for item in value]
        return ",".join(item for item in values if item)
    if parser is not None:
        return parser._structure_value(value)
    if isinstance(value, dict):
        for key in ("value", "name", "taskName", "task_name", "id", "sysId", "sys_id"):
            nested = value.get(key)
            if isinstance(nested, (str, int)) and str(nested).strip():
                return str(nested).strip()
        return ""
    if isinstance(value, (str, int)):
        return str(value).strip()
    return ""


def _status_predicate(status: str) -> str | None:
    raw = status.lower()
    has_success = "success" in raw
    has_failure = "failure" in raw or "fail" in raw
    if "finished" in raw or "done" in raw or (has_success and has_failure):
        return expr.DONE
    if "cancelled" in raw or "canceled" in raw or "terminated" in raw:
        return expr.TERMINATED
    if has_failure:
        return expr.FAILURE
    if has_success:
        return expr.SUCCESS
    return None


def _mentions_known_status(status: str) -> bool:
    return _status_predicate(status) is not None or "exit" in status.lower()
