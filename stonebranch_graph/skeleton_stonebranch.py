"""Stonebranch raw-record to Skeleton builder."""

from __future__ import annotations

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
            predicate, qualifier = self._edge_predicate(edge, definition.record.source_file)
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
            meta=self._base_meta(native_name, record),
        )
        self.specs[node_id] = spec
        return spec

    def _base_meta(self, native_name: str, record: RawRecord | None) -> dict[str, Any]:
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

    def _edge_predicate(self, edge: dict[str, Any], source_file: str) -> tuple[str, str]:
        qualifier = self._exit_qualifier(edge)
        if qualifier:
            return expr.EXIT, qualifier

        relation = self.parser._workflow_edge_relation(edge)
        if relation == REL_DEPENDS_ON_DONE:
            return expr.DONE, ""
        if relation == REL_DEPENDS_ON_FAILURE:
            return expr.FAILURE, ""
        if relation == REL_DEPENDS_ON_TERMINATED:
            return expr.TERMINATED, ""
        raw = self._edge_condition_text(edge)
        if raw and not _mentions_known_status(raw):
            self.skeleton.warnings.append(
                f"Unknown Stonebranch workflow edge condition {raw!r} in {source_file}; "
                "using SUCCESS."
            )
        return expr.SUCCESS, ""

    def _edge_condition_text(self, edge: dict[str, Any]) -> str:
        return " ".join(
            value for key in EDGE_CONDITION_KEYS if (value := _string_value(edge.get(key)))
        )

    def _exit_qualifier(self, edge: dict[str, Any]) -> str:
        condition_text = self._edge_condition_text(edge).lower()
        for key in EXIT_CODE_KEYS:
            if key == "value" and "exit" not in condition_text:
                continue
            value = _string_value(edge.get(key))
            if value:
                return value
        return ""

    def _emit_nodes(self) -> None:
        instance_index = self._instance_index()
        for node_id in sorted(self.specs):
            spec = self.specs[node_id]
            meta = dict(spec.meta)
            if meta.get("plumbing") == "task_monitor" and spec.record is not None:
                meta["monitor"] = self._monitor_payload(spec, instance_index)
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
            target = EXT_PREFIX + "unknown"
            self.skeleton.externals.add(target)
            return {"target": target, "predicate": predicate, "external": True}

        candidates = instance_index.get(_name_key(target_name), [])
        if not candidates:
            target = EXT_PREFIX + logical_leaf(target_name)
            self.skeleton.externals.add(target)
            return {"target": target, "predicate": predicate, "external": True}

        same_parent = [
            candidate for candidate in candidates if self.specs[candidate].parent == spec.parent
        ]
        if same_parent:
            if len(same_parent) > 1:
                self.skeleton.warnings.append(
                    f"Ambiguous Stonebranch task monitor target {target_name!r} near "
                    f"{spec.id!r}; using {same_parent[0]!r}."
                )
            return {"target": same_parent[0], "predicate": predicate, "external": False}
        if len(candidates) > 1:
            self.skeleton.warnings.append(
                f"Ambiguous Stonebranch task monitor target {target_name!r}; using "
                f"{candidates[0]!r}."
            )
        return {"target": candidates[0], "predicate": predicate, "external": False}

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
