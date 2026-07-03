from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import (
    Edge,
    Graph,
    Node,
    enterprise_name_parts,
    make_canonical_key,
    make_edge_id,
    make_node_id,
    redacted_preview,
    stable_hash,
)
from stonebranch_graph.domain import (
    KIND_AGENT,
    KIND_AGENT_CLUSTER,
    KIND_CALENDAR,
    KIND_COMMAND,
    KIND_CONNECTION,
    KIND_CREDENTIAL,
    KIND_EMAIL_TEMPLATE,
    KIND_FILE,
    KIND_FILE_WATCHER,
    KIND_OBJECT,
    KIND_SCRIPT,
    KIND_TASK,
    KIND_TRIGGER,
    KIND_VARIABLE,
    KIND_WORKFLOW,
    REL_CONTAINS,
    REL_DEPENDS_ON,
    REL_DEPENDS_ON_DONE,
    REL_DEPENDS_ON_FAILURE,
    REL_DEPENDS_ON_NOTRUNNING,
    REL_DEPENDS_ON_SUCCESS,
    REL_DEPENDS_ON_TERMINATED,
    REL_REFERENCES,
    REL_RUNS_COMMAND,
    REL_RUNS_ON,
    REL_RUNS_ON_CLUSTER,
    REL_RUNS_SCRIPT,
    REL_STARTS,
    REL_SUCCESSOR_OF,
    REL_USES_CALENDAR,
    REL_USES_CONNECTION,
    REL_USES_CREDENTIAL,
    REL_USES_EMAIL_TEMPLATE,
    REL_USES_VARIABLE,
    REL_WATCHES_FILE,
    SOURCE_STONEBRANCH,
)
from stonebranch_graph.normalizers import (
    command_evidence,
    command_hash,
    command_normalization_diagnostics,
    command_variable_names,
    normalize_command_variable_name,
    semantic_command_hash,
)
from stonebranch_graph.utils import (
    discover_source_files,
    first_string,
    is_secret_key,
    normalized_kind,
    read_json_text,
    safe_metadata,
)

VAR_TOKEN_RE = re.compile(
    r"""
    (?:
        \$\{(?P<brace>[A-Za-z0-9_.:/\- ]+)\} |
        \{\{(?P<mustache>[A-Za-z0-9_.:/\- ]+)\}\} |
        %(?P<percent>[A-Za-z0-9_.:/\- ]+)% |
        @\((?P<at>[A-Za-z0-9_.:/\- ]+)\)
    )
    """,
    re.VERBOSE,
)

# Variable usage is compared against AutoSys, where variables can only appear
# inside command text. Extracting tokens from every JSON string creates
# variable objects and uses_variable edges that AutoSys can never express, so
# extraction is limited to command-like fields.
COMMAND_LIKE_KEYS = {"command", "script"}

# Stonebranch stores intra-workflow dependencies as a vertex/edge graph inside
# the workflow definition. These subtrees are parsed structurally and must be
# skipped by the generic key-based reference walker.
WORKFLOW_VERTEX_KEYS = ("workflowVertices", "workflow_vertices", "vertices")
WORKFLOW_EDGE_KEYS = ("workflowEdges", "workflow_edges", "edges")
WORKFLOW_STRUCTURE_KEY_NAMES = {key.lower() for key in (*WORKFLOW_VERTEX_KEYS, *WORKFLOW_EDGE_KEYS)}

# Native Stonebranch type values that mean "this object is a workflow" even
# when the export stores it in the tasks folder.
WORKFLOW_NATIVE_TYPES = {"taskworkflow", "workflow"}
JOB_LIKE_TARGET_KINDS = {KIND_TASK, KIND_WORKFLOW, KIND_FILE_WATCHER}


@dataclass(frozen=True)
class RawRecord:
    kind: str
    native_type: str
    name: str
    env: str
    source_file: str
    data: dict[str, Any]


@dataclass(frozen=True)
class _RawDependencyRecord:
    env: str
    source_file: str
    data: dict[str, Any]


@dataclass(frozen=True)
class StonebranchRawExport:
    records: list[RawRecord]
    warnings: list[str]


TARGET_KIND_BY_NATIVE_RELATION = {
    "starts_task": KIND_TASK,
    "starts_workflow": KIND_WORKFLOW,
    "contains_task": KIND_TASK,
    "contains_workflow": KIND_WORKFLOW,
    "references_workflow": KIND_WORKFLOW,
    "references_task": KIND_TASK,
    "references_job": KIND_TASK,
    "references_predecessor": KIND_TASK,
    "references_successor": KIND_TASK,
    "references_calendar": KIND_CALENDAR,
    "references_credential": KIND_CREDENTIAL,
    "references_connection": KIND_CONNECTION,
    "references_agent": KIND_AGENT,
    "references_agent_cluster": KIND_AGENT_CLUSTER,
    "references_agentcluster": KIND_AGENT_CLUSTER,
    "references_email_template": KIND_EMAIL_TEMPLATE,
    "references_emailtemplate": KIND_EMAIL_TEMPLATE,
    "references_script": KIND_SCRIPT,
    "references_variable": KIND_VARIABLE,
    "references_trigger": KIND_TRIGGER,
    "references_command": KIND_COMMAND,
    "watch_file": KIND_FILE,
    "contained_by_workflow": KIND_WORKFLOW,
    "variable_token": KIND_VARIABLE,
}

TARGET_KIND_BY_RELATION = {
    REL_STARTS: KIND_TASK,
    REL_DEPENDS_ON: KIND_TASK,
    REL_DEPENDS_ON_DONE: KIND_TASK,
    REL_DEPENDS_ON_FAILURE: KIND_TASK,
    REL_DEPENDS_ON_NOTRUNNING: KIND_TASK,
    REL_DEPENDS_ON_SUCCESS: KIND_TASK,
    REL_DEPENDS_ON_TERMINATED: KIND_TASK,
    REL_SUCCESSOR_OF: KIND_TASK,
    REL_USES_CALENDAR: KIND_CALENDAR,
    REL_USES_CREDENTIAL: KIND_CREDENTIAL,
    REL_USES_CONNECTION: KIND_CONNECTION,
    REL_RUNS_ON: KIND_AGENT,
    REL_RUNS_ON_CLUSTER: KIND_AGENT_CLUSTER,
    REL_USES_EMAIL_TEMPLATE: KIND_EMAIL_TEMPLATE,
    REL_RUNS_SCRIPT: KIND_SCRIPT,
    REL_USES_VARIABLE: KIND_VARIABLE,
    REL_RUNS_COMMAND: KIND_COMMAND,
    REL_WATCHES_FILE: KIND_FILE,
}


class StonebranchJsonParser:
    def __init__(
        self,
        config: AnalyzerConfig,
        env: str = "default",
        env_aware: bool = False,
        deep_scan: bool = False,
    ) -> None:
        self.config = config
        self.env = env
        self.env_aware = env_aware
        self.deep_scan = deep_scan

    def parse(self, input_path: Path) -> Graph:
        raw, dependency_records = self._parse_raw_with_dependencies(input_path)
        graph = Graph(source_system=SOURCE_STONEBRANCH, env=self.env)
        for warning in raw.warnings:
            self._append_warning_once(graph, warning)

        for record in raw.records:
            node = self._make_node(
                env=record.env,
                kind=record.kind,
                name=record.name,
                native_kind=record.native_type,
                source_file=record.source_file,
                metadata=self._object_metadata(record.data, record.name),
                attributes=record.data,
            )
            existing = graph.nodes.get(node.id)
            if existing and existing.source_file != record.source_file:
                self._append_warning_once(
                    graph,
                    f"Duplicate Stonebranch object id {node.id!r}: keeping first definition from "
                    f"{existing.source_file!r}, merging duplicate from {record.source_file!r}.",
                )
            graph.add_node(node)

        registry = self._build_registry(graph)

        for record in dependency_records:
            edge = self._dependency_definition_edge(
                graph, registry, record.env, record.source_file, record.data
            )
            if edge:
                graph.add_edge(edge)
            else:
                self._append_warning_once(
                    graph,
                    "Skipped Stonebranch dependency definition without a clear dependent/"
                    f"prerequisite pair: {record.source_file}.",
                )

        for record in raw.records:
            source_id = make_node_id(SOURCE_STONEBRANCH, record.env, record.kind, record.name)
            if record.kind == KIND_WORKFLOW:
                self._add_workflow_structure_edges(
                    graph, registry, record.env, record.source_file, source_id, record.data
                )
            for (
                ref_value,
                native_relation,
                relation,
                evidence_path,
                evidence_key,
                evidence_value,
            ) in self._find_references(record.data, record.kind):
                target_kind = self._kind_from_relation(native_relation, relation)
                target_id = self._resolve_or_create_ref_node(
                    graph=graph,
                    registry=registry,
                    env=record.env,
                    target_kind=target_kind,
                    target_name=ref_value,
                    native_relation=native_relation,
                    source_file=record.source_file,
                )
                (
                    edge_source,
                    edge_target,
                    edge_relation,
                    edge_native_relation,
                ) = self._directed_relation(source_id, target_id, relation, native_relation)
                edge = Edge(
                    id=make_edge_id(edge_source, edge_target, edge_relation, edge_native_relation),
                    source=edge_source,
                    target=edge_target,
                    relation=edge_relation,
                    source_system=SOURCE_STONEBRANCH,
                    native_relation=edge_native_relation,
                    evidence_file=record.source_file,
                    evidence_path=evidence_path,
                    evidence_key=evidence_key,
                    evidence_value=redacted_preview(
                        evidence_value, self.config.max_evidence_value_len
                    ),
                    confidence=0.95 if native_relation != "deep_scan_reference" else 0.55,
                )
                graph.add_edge(edge)

        self._add_warnings(graph)
        return graph

    def parse_raw(self, input_path: Path) -> StonebranchRawExport:
        raw, _dependency_records = self._parse_raw_with_dependencies(input_path)
        return raw

    def _parse_raw_with_dependencies(
        self, input_path: Path
    ) -> tuple[StonebranchRawExport, list[_RawDependencyRecord]]:
        files = self._load_json_files(input_path)
        records: list[RawRecord] = []
        dependency_records: list[_RawDependencyRecord] = []
        warnings: list[str] = []

        for path, relative_path, data in files:
            kind = self._kind_from_path(path)
            if not kind:
                if self._is_dependency_definition_path(path):
                    for item_relative_path, item in self._iter_object_dicts(
                        data, relative_path, warnings
                    ):
                        env = self._env_from_path(path) if self.env_aware else self.env
                        dependency_records.append(
                            _RawDependencyRecord(env=env, source_file=item_relative_path, data=item)
                        )
                    continue
                self._append_warning_once_raw(
                    warnings,
                    "Skipped Stonebranch JSON file outside a configured object-kind folder: "
                    f"{relative_path}.",
                )
                continue
            for item_relative_path, item in self._iter_object_dicts(
                data, relative_path, warnings
            ):
                env = self._env_from_path(path) if self.env_aware else self.env
                native_kind = self._native_kind(item) or kind
                item_kind = self._effective_kind(kind, native_kind)
                name = self._detect_object_name(item, item_kind, path)
                records.append(
                    RawRecord(
                        kind=item_kind,
                        native_type=native_kind,
                        name=name,
                        env=env,
                        source_file=item_relative_path,
                        data=item,
                    )
                )

        if not records and not dependency_records:
            self._append_warning_once_raw(
                warnings, f"No Stonebranch objects were parsed from {input_path}."
            )

        return StonebranchRawExport(records=records, warnings=warnings), dependency_records

    def _load_json_files(self, input_path: Path) -> list[tuple[Path, str, Any]]:
        if not input_path.exists():
            raise FileNotFoundError(f"Input path does not exist: {input_path}")
        root = input_path.parent if input_path.is_file() else input_path
        files = discover_source_files(
            input_path,
            extensions={".json"},
            ignored_filenames=self.config.ignored_filenames,
        )
        if not files:
            raise FileNotFoundError(f"No Stonebranch JSON files found under: {input_path}")
        loaded: list[tuple[Path, str, Any]] = []
        for file in files:
            try:
                data = json.loads(read_json_text(file))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {file}: {exc}") from exc
            relative = str(file.relative_to(root)) if file.is_relative_to(root) else str(file)
            loaded.append((file, relative, data))
        return loaded

    def _iter_object_dicts(
        self, data: Any, relative_path: str, warnings: list[str]
    ) -> list[tuple[str, dict[str, Any]]]:
        if isinstance(data, dict):
            return [(relative_path, data)]
        if isinstance(data, list):
            objects: list[tuple[str, dict[str, Any]]] = []
            for idx, item in enumerate(data):
                if isinstance(item, dict):
                    objects.append((f"{relative_path}#[{idx}]", item))
                else:
                    self._append_warning_once_raw(
                        warnings,
                        "Skipped non-object item in Stonebranch JSON array at "
                        f"{relative_path}#[{idx}].",
                    )
            if not objects:
                self._append_warning_once_raw(
                    warnings,
                    f"Skipped Stonebranch JSON array with no object items: {relative_path}.",
                )
            return objects
        self._append_warning_once_raw(
            warnings,
            f"Skipped unsupported Stonebranch JSON root in {relative_path}: {type(data).__name__}.",
        )
        return []


    def _is_dependency_definition_path(self, path: Path) -> bool:
        return any(part.lower() in {"dependencies", "dependency", "predecessors", "successors"} for part in path.parts[:-1])

    def _dependency_definition_edge(
        self,
        graph: Graph,
        registry: dict[str, dict],
        env: str,
        relative_path: str,
        data: dict[str, Any],
    ) -> Edge | None:
        dependent = self._dependency_dependent_name(data)
        prerequisite = self._dependency_prerequisite_name(data)
        if not dependent or not prerequisite:
            return None

        source_id = self._resolve_or_create_ref_node(
            graph=graph,
            registry=registry,
            env=env,
            target_kind=KIND_TASK,
            target_name=dependent,
            native_relation="dependency_dependent_task",
            source_file=relative_path,
        )
        target_id = self._resolve_or_create_ref_node(
            graph=graph,
            registry=registry,
            env=env,
            target_kind=KIND_TASK,
            target_name=prerequisite,
            native_relation="dependency_prerequisite_task",
            source_file=relative_path,
        )
        relation = self._dependency_relation_from_definition(data)
        evidence_key = self._dependency_evidence_key(data)
        evidence_value = f"{dependent} -> {relation} -> {prerequisite}"
        return Edge(
            id=make_edge_id(source_id, target_id, relation, "stonebranch_dependency_definition"),
            source=source_id,
            target=target_id,
            relation=relation,
            source_system=SOURCE_STONEBRANCH,
            native_relation="stonebranch_dependency_definition",
            evidence_file=relative_path,
            evidence_path="$",
            evidence_key=evidence_key,
            evidence_value=redacted_preview(evidence_value, self.config.max_evidence_value_len),
            confidence=0.97,
        )

    def _dependency_dependent_name(self, data: dict[str, Any]) -> str:
        return self._first_dependency_string(
            data,
            (
                "successorTaskName",
                "successorTask",
                "successorName",
                "successor",
                "dependentTaskName",
                "dependentTask",
                "dependentName",
                "dependent",
                "taskName",
                "task",
                "jobName",
                "job",
                "toTask",
                "targetTask",
                "childTask",
            ),
        )

    def _dependency_prerequisite_name(self, data: dict[str, Any]) -> str:
        return self._first_dependency_string(
            data,
            (
                "predecessorTaskName",
                "predecessorTask",
                "predecessorName",
                "predecessor",
                "prerequisiteTaskName",
                "prerequisiteTask",
                "prerequisiteName",
                "prerequisite",
                "dependencyTaskName",
                "dependencyTask",
                "dependsOnTaskName",
                "dependsOnTask",
                "dependsOn",
                "fromTask",
                "sourceTask",
                "parentTask",
            ),
        )

    def _first_dependency_string(self, data: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().strip('"').strip("'")
        return ""

    def _dependency_relation_from_definition(self, data: dict[str, Any]) -> str:
        raw = " ".join(
            str(data.get(key, ""))
            for key in (
                "dependencyType",
                "dependency_type",
                "conditionType",
                "condition_type",
                "status",
                "event",
                "relation",
            )
        ).lower()
        if "failure" in raw or raw in {"f", "fail"}:
            return REL_DEPENDS_ON_FAILURE
        if "terminated" in raw or "terminate" in raw or raw == "t":
            return REL_DEPENDS_ON_TERMINATED
        if "notrunning" in raw or "not_running" in raw or "not running" in raw:
            return REL_DEPENDS_ON_NOTRUNNING
        if "done" in raw or raw == "d":
            return REL_DEPENDS_ON_DONE
        if "success" in raw or raw in {"s", "ok"}:
            return REL_DEPENDS_ON_SUCCESS
        return REL_DEPENDS_ON_SUCCESS

    def _dependency_evidence_key(self, data: dict[str, Any]) -> str:
        name = first_string(data, ("name", "Name", "dependencyName", "dependency_name", "id", "Id"))
        if name:
            return f"dependency:{name}"
        return "dependency_definition"

    def _kind_from_path(self, path: Path) -> str | None:
        mapping = self.config.folder_kind_map or {}
        for part in reversed(path.parts[:-1]):
            kind = mapping.get(part.lower())
            if kind:
                return normalized_kind(kind, self.config.kind_aliases)
        return None

    def _env_from_path(self, path: Path) -> str:
        mapping = self.config.folder_kind_map or {}
        parts = list(path.parts)
        for idx, part in enumerate(parts):
            if part.lower() in mapping and idx > 0:
                parent = parts[idx - 1]
                if parent.lower() not in mapping:
                    return parent
        return self.env

    def _native_kind(self, data: dict[str, Any]) -> str | None:
        for key in self.config.stonebranch_type_keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _effective_kind(self, kind: str, native_kind: str) -> str:
        """Promote objects whose native Stonebranch type marks them as
        workflows even when the export stores them in a generic tasks folder.

        Universal Controller exports frequently place every task type,
        including type=taskWorkflow, under one tasks directory. Treating those
        records as plain tasks breaks matching against AutoSys boxes and drops
        their vertex/edge dependency structure.
        """
        if kind == KIND_TASK and self._normalized_type_token(native_kind) in WORKFLOW_NATIVE_TYPES:
            return KIND_WORKFLOW
        return kind

    @staticmethod
    def _normalized_type_token(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value).lower())

    # --- Workflow vertex/edge structure --------------------------------------

    def _add_workflow_structure_edges(
        self,
        graph: Graph,
        registry: dict[str, dict],
        env: str,
        relative_path: str,
        workflow_id: str,
        data: dict[str, Any],
    ) -> None:
        """Parse Stonebranch workflow vertices/edges into containment and
        dependency edges.

        In Stonebranch, dependencies between tasks inside a workflow are stored
        as a graph: workflowVertices map vertex ids to task names and
        workflowEdges connect vertices with a condition (Success/Failure/...).
        These are the AutoSys condition dependencies' counterpart and must be
        compared as depends_on_* edges, not counted as opaque extra edges.
        """
        vertices = self._first_list(data, WORKFLOW_VERTEX_KEYS)
        edges = self._first_list(data, WORKFLOW_EDGE_KEYS)

        vertex_tasks: dict[str, str] = {}
        for index, item in enumerate(vertices):
            if not isinstance(item, dict):
                continue
            task_name = self._workflow_task_name(item)
            if not task_name:
                continue
            node_id = self._resolve_or_create_ref_node(
                graph=graph,
                registry=registry,
                env=env,
                target_kind=KIND_TASK,
                target_name=task_name,
                native_relation="workflow_vertex",
                source_file=relative_path,
            )
            vertex_id = self._structure_value(
                item.get("vertexId") if "vertexId" in item else item.get("vertex_id", item.get("id"))
            )
            if vertex_id:
                vertex_tasks[vertex_id] = node_id
            graph.add_edge(
                Edge(
                    id=make_edge_id(workflow_id, node_id, REL_CONTAINS, "workflow_vertex"),
                    source=workflow_id,
                    target=node_id,
                    relation=REL_CONTAINS,
                    source_system=SOURCE_STONEBRANCH,
                    native_relation="workflow_vertex",
                    evidence_file=relative_path,
                    evidence_path=f"$.workflowVertices[{index}]",
                    evidence_key="task",
                    evidence_value=redacted_preview(task_name, self.config.max_evidence_value_len),
                    confidence=0.97,
                )
            )

        for index, item in enumerate(edges):
            if not isinstance(item, dict):
                continue
            source_task = self._workflow_edge_endpoint(
                graph, registry, env, relative_path, item, vertex_tasks,
                ("sourceId", "source_id", "sourceVertex", "source_vertex", "source", "from", "fromVertex"),
            )
            target_task = self._workflow_edge_endpoint(
                graph, registry, env, relative_path, item, vertex_tasks,
                ("targetId", "target_id", "targetVertex", "target_vertex", "target", "to", "toVertex"),
            )
            if not source_task or not target_task or source_task == target_task:
                if item:
                    self._append_warning_once(
                        graph,
                        f"Skipped Stonebranch workflow edge without resolvable endpoints in {relative_path}.",
                    )
                continue
            relation = self._workflow_edge_relation(item)
            source_name = graph.nodes[source_task].name if source_task in graph.nodes else source_task
            target_name = graph.nodes[target_task].name if target_task in graph.nodes else target_task
            # Stonebranch edge direction source -> target means the target runs
            # after the source. Normalize to dependent -> prerequisite like
            # AutoSys condition edges.
            graph.add_edge(
                Edge(
                    id=make_edge_id(target_task, source_task, relation, "workflow_edge"),
                    source=target_task,
                    target=source_task,
                    relation=relation,
                    source_system=SOURCE_STONEBRANCH,
                    native_relation="workflow_edge",
                    evidence_file=relative_path,
                    evidence_path=f"$.workflowEdges[{index}]",
                    evidence_key="workflow_edge",
                    evidence_value=redacted_preview(
                        f"{target_name} -> {relation} -> {source_name}",
                        self.config.max_evidence_value_len,
                    ),
                    confidence=0.97,
                )
            )

    def _first_list(self, data: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
        return []

    def _workflow_task_name(self, item: dict[str, Any]) -> str:
        for key in ("task", "taskName", "task_name", "name"):
            if key not in item:
                continue
            value = self._structure_value(item[key])
            if value:
                return value
        return ""

    def _structure_value(self, value: Any) -> str:
        if isinstance(value, dict):
            for key in ("value", "name", "taskName", "task_name", "id", "sysId", "sys_id"):
                nested = value.get(key)
                if isinstance(nested, (str, int)) and str(nested).strip():
                    return str(nested).strip()
            return ""
        if isinstance(value, (str, int)):
            return str(value).strip()
        return ""

    def _workflow_edge_endpoint(
        self,
        graph: Graph,
        registry: dict[str, dict],
        env: str,
        relative_path: str,
        item: dict[str, Any],
        vertex_tasks: dict[str, str],
        keys: tuple[str, ...],
    ) -> str | None:
        ref: Any = None
        for key in keys:
            if key in item and item[key] is not None:
                ref = item[key]
                break
        if ref is None:
            return None

        task_name = ""
        vertex_id = ""
        if isinstance(ref, dict):
            for key in ("taskName", "task_name", "task", "name"):
                candidate = self._structure_value(ref.get(key))
                if candidate:
                    task_name = candidate
                    break
            vertex_id = self._structure_value({"value": ref.get("value", ref.get("id"))})
        else:
            token = self._structure_value(ref)
            if token in vertex_tasks or token.isdigit():
                vertex_id = token
            else:
                task_name = token

        if vertex_id and vertex_id in vertex_tasks:
            return vertex_tasks[vertex_id]
        if task_name:
            return self._resolve_or_create_ref_node(
                graph=graph,
                registry=registry,
                env=env,
                target_kind=KIND_TASK,
                target_name=task_name,
                native_relation="workflow_edge_task",
                source_file=relative_path,
            )
        return None

    def _workflow_edge_relation(self, item: dict[str, Any]) -> str:
        raw = " ".join(
            self._structure_value(item.get(key))
            for key in ("condition", "Condition", "conditionType", "condition_type", "status")
        ).lower()
        has_success = "success" in raw
        has_failure = "failure" in raw or "fail" in raw
        if has_success and has_failure:
            return REL_DEPENDS_ON_DONE
        if has_failure:
            return REL_DEPENDS_ON_FAILURE
        return REL_DEPENDS_ON_SUCCESS

    def _detect_object_name(self, data: dict[str, Any], kind: str, path: Path) -> str:
        kind_specific_keys = {
            KIND_TASK: ("name", "Name", "title", "Title", "taskName", "TaskName"),
            KIND_TRIGGER: ("name", "Name", "title", "Title", "triggerName", "TriggerName"),
            KIND_VARIABLE: ("name", "Name", "title", "Title", "variableName", "VariableName"),
            KIND_CALENDAR: ("name", "Name", "title", "Title", "calendarName", "CalendarName"),
            KIND_CREDENTIAL: ("name", "Name", "title", "Title", "credentialName", "CredentialName"),
            KIND_CONNECTION: ("name", "Name", "title", "Title", "connectionName", "ConnectionName"),
            KIND_AGENT: ("name", "Name", "title", "Title", "agentName", "AgentName"),
            KIND_AGENT_CLUSTER: ("name", "Name", "title", "Title", "agentClusterName", "AgentClusterName"),
            KIND_SCRIPT: ("name", "Name", "title", "Title", "scriptName", "ScriptName"),
            KIND_EMAIL_TEMPLATE: ("name", "Name", "title", "Title", "emailTemplateName", "EmailTemplateName"),
            KIND_WORKFLOW: ("name", "Name", "title", "Title", "workflowName", "WorkflowName"),
        }
        return first_string(data, kind_specific_keys.get(kind, ("name", "Name", "title", "Title"))) or path.stem

    def _object_metadata(self, data: dict[str, Any], name: str = "") -> dict[str, Any]:
        metadata = {"json_keys": sorted(str(k) for k in data)}
        naming = enterprise_name_parts(name)
        if naming:
            metadata["enterprise_naming"] = naming
        command = data.get("command") or data.get("Command") or data.get("script") or data.get("Script")
        if isinstance(command, str) and command.strip():
            metadata["command_hash"] = command_hash(command)
            metadata["semantic_command_hash"] = semantic_command_hash(command)
            metadata["command_normalization"] = command_normalization_diagnostics(command)
        return metadata

    def _make_node(
        self,
        env: str,
        kind: str,
        name: str,
        native_kind: str,
        source_file: str,
        metadata: dict[str, Any],
        attributes: dict[str, Any] | None = None,
    ) -> Node:
        safe_attrs = safe_metadata(attributes or {})
        return Node(
            id=make_node_id(SOURCE_STONEBRANCH, env, kind, name),
            canonical_key=make_canonical_key(env, kind, name),
            source_system=SOURCE_STONEBRANCH,
            env=env,
            kind=kind,
            name=name,
            native_kind=native_kind,
            source_file=source_file,
            attributes_hash=stable_hash(safe_attrs, 16) if safe_attrs else "",
            metadata=metadata,
        )

    def _build_registry(self, graph: Graph) -> dict[str, dict]:
        by_kind: dict[tuple[str, str, str], str] = {}
        by_name: dict[tuple[str, str], set[str]] = {}
        for node in graph.nodes.values():
            name_key = node.name.lower()
            by_kind[(node.env, node.kind, name_key)] = node.id
            by_name.setdefault((node.env, name_key), set()).add(node.id)
        return {"by_kind": by_kind, "by_name": by_name}

    def _find_references(self, data: dict[str, Any], source_kind: str) -> list[tuple[str, str, str, str, str, str]]:
        refs: list[tuple[str, str, str, str, str, str]] = []

        def walk(value: Any, path: str, key: str) -> None:
            if isinstance(value, dict):
                for child_key, child in value.items():
                    child_key_str = str(child_key)
                    if source_kind == KIND_WORKFLOW and child_key_str.lower() in WORKFLOW_STRUCTURE_KEY_NAMES:
                        # Workflow vertices/edges are parsed structurally into
                        # containment and dependency edges; walking them here
                        # would create duplicate or mis-typed references.
                        continue
                    walk(child, f"{path}.{child_key_str}", child_key_str)
                return
            if isinstance(value, list):
                for idx, child in enumerate(value):
                    walk(child, f"{path}[{idx}]", key)
                return
            if not isinstance(value, str) or not value.strip() or is_secret_key(key):
                return
            cleaned = value.strip()
            native = self._native_relation_from_key(key, source_kind)
            if native:
                relation = self._normalized_relation(native)
                if relation == REL_RUNS_COMMAND:
                    command_id = semantic_command_hash(cleaned)
                    evidence = command_evidence(cleaned, include_raw_values=self.config.include_raw_values)
                    refs.append((command_id, native, relation, path, key, evidence))
                else:
                    refs.append((cleaned, native, relation, path, key, cleaned))
            if key.lower() in COMMAND_LIKE_KEYS:
                # Variable usage is only comparable with AutoSys inside command
                # text, and the token names are normalized identically on both
                # sides so the same variable produces the same comparison key.
                for token in self._extract_variable_tokens(cleaned):
                    refs.append((token, "variable_token", REL_USES_VARIABLE, path, key, token))
            if self.deep_scan and not native and self._likely_reference(cleaned):
                refs.append((cleaned, "deep_scan_reference", REL_REFERENCES, path, key, cleaned))

        walk(data, "$", "")
        return refs

    def _native_relation_from_key(self, key: str, source_kind: str) -> str | None:
        lower = key.lower().replace("-", "_")
        if source_kind == KIND_TRIGGER:
            if lower in {"taskname", "task_name"}:
                return "starts_task"
            if lower in {"workflowname", "workflow_name"}:
                return "starts_workflow"
        if source_kind == KIND_WORKFLOW:
            workflow_keys = {"workflowname", "workflow_name", "workflow", "workflows", "subworkflowname", "sub_workflow_name"}
            task_keys = {
                "taskname",
                "task_name",
                "tasknames",
                "task_names",
                "task",
                "tasks",
                "jobname",
                "job_name",
                "jobnames",
                "job_names",
                "job",
                "jobs",
                "workflowtaskname",
                "workflow_task_name",
                "workflowtasks",
                "workflow_tasks",
            }
            if lower in workflow_keys:
                return "contains_workflow"
            if lower in task_keys or lower.endswith("taskname") or lower.endswith("task_name"):
                return "contains_task"
        exact = {
            "predecessortask": "references_predecessor",
            "predecessor_task": "references_predecessor",
            "successortask": "references_successor",
            "successor_task": "references_successor",
            "agentclustername": "references_agent_cluster",
            "agent_cluster_name": "references_agent_cluster",
            "emailtemplatename": "references_email_template",
            "email_template_name": "references_email_template",
            "calendarname": "references_calendar",
            "calendar_name": "references_calendar",
            "credentialname": "references_credential",
            "credential_name": "references_credential",
            "connectionname": "references_connection",
            "connection_name": "references_connection",
            "agentname": "references_agent",
            "agent_name": "references_agent",
            "scriptname": "references_script",
            "script_name": "references_script",
            "variablename": "references_variable",
            "variable_name": "references_variable",
            "command": "references_command",
            "watch_file": "watch_file",
            "watchfilename": "watch_file",
            "watch_file_name": "watch_file",
        }
        if lower in exact:
            return exact[lower]
        if lower in {"workflowname", "workflow_name"}:
            return "contained_by_workflow"
        if lower.endswith("taskname") or lower.endswith("task_name"):
            return "references_task"
        return None

    def _normalized_relation(self, native_relation: str) -> str:
        return (self.config.relation_aliases or {}).get(native_relation, native_relation)


    def _directed_relation(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        native_relation: str,
    ) -> tuple[str, str, str, str]:
        if native_relation == "references_successor":
            # Stonebranch successor fields mean: target/successor runs after the current task.
            # Normalize to the same direction used by AutoSys conditions: dependent -> prerequisite.
            return target_id, source_id, REL_DEPENDS_ON_SUCCESS, "successor_depends_on_success"
        if native_relation == "contained_by_workflow":
            # A task-level workflowName means the workflow contains the current task.
            return target_id, source_id, REL_CONTAINS, native_relation
        return source_id, target_id, relation, native_relation

    def _extract_variable_tokens(self, value: str) -> list[str]:
        """Extract variable names from command-like text.

        Uses the shared cross-scheduler normalizer (same as the JIL parser) so
        ${VAR}, $VAR, %%VAR, %VAR%, and #VAR# produce identical names on both
        sides, plus Stonebranch-specific {{var}} and @(var) wrappers.
        """
        found: list[str] = []
        for name in command_variable_names(value):
            if name not in found:
                found.append(name)
        for match in VAR_TOKEN_RE.finditer(value):
            token = next((group for group in match.groups() if group), None)
            normalized = normalize_command_variable_name(token or "")
            if normalized and normalized not in found:
                found.append(normalized)
        return found

    def _likely_reference(self, value: str) -> bool:
        return len(value) <= 220 and "\n" not in value and not (" " in value and not any(sep in value for sep in ("_", "-", "/", ":")))

    def _kind_from_relation(self, native_relation: str, relation: str) -> str:
        native_key = native_relation.lower()
        relation_key = relation.lower()
        if native_key in TARGET_KIND_BY_NATIVE_RELATION:
            return TARGET_KIND_BY_NATIVE_RELATION[native_key]
        if relation_key in TARGET_KIND_BY_RELATION:
            return TARGET_KIND_BY_RELATION[relation_key]

        text = (native_relation + " " + relation).lower()
        if "calendar" in text:
            return KIND_CALENDAR
        if "credential" in text:
            return KIND_CREDENTIAL
        if "connection" in text:
            return KIND_CONNECTION
        if "agent_cluster" in text or "agentcluster" in text:
            return KIND_AGENT_CLUSTER
        if "agent" in text:
            return KIND_AGENT
        if "email_template" in text or "emailtemplate" in text:
            return KIND_EMAIL_TEMPLATE
        if "script" in text:
            return KIND_SCRIPT
        if "variable" in text:
            return KIND_VARIABLE
        if "command" in text:
            return KIND_COMMAND
        if "task" in text or "job" in text or "predecessor" in text or "successor" in text:
            return KIND_TASK
        if "trigger" in text:
            return KIND_TRIGGER
        return KIND_OBJECT

    def _lookup_registry(self, registry: dict[str, dict], env: str, kind: str, name: str) -> str | None:
        name_key = name.lower()
        return registry["by_kind"].get((env, kind, name_key))

    def _same_name_matches(
        self,
        registry: dict[str, dict],
        env: str,
        name: str,
    ) -> set[str]:
        return set(registry["by_name"].get((env, name.lower()), set()))

    def _resolve_or_create_ref_node(
        self,
        graph: Graph,
        registry: dict[str, dict],
        env: str,
        target_kind: str,
        target_name: str,
        native_relation: str,
        source_file: str,
    ) -> str:
        existing = self._lookup_registry(registry, env, target_kind, target_name)
        if existing:
            return existing

        same_name_matches = self._same_name_matches(registry, env, target_name)

        if target_kind in JOB_LIKE_TARGET_KINDS:
            # A dependency/containment/trigger reference to a job-like object
            # may point at a task, a workflow, or a file monitor: AutoSys jobs,
            # boxes, and file watchers all migrate into these. Link to the one
            # defined object with that name instead of fabricating a synthetic
            # node of the wrong kind.
            job_like_matches = [
                node_id
                for node_id in sorted(same_name_matches)
                if graph.nodes[node_id].kind in JOB_LIKE_TARGET_KINDS
            ]
            if len(job_like_matches) == 1:
                return job_like_matches[0]

        if len(same_name_matches) == 1:
            matched_node = graph.nodes[next(iter(same_name_matches))]
            self._append_warning_once(
                graph,
                f"Stonebranch reference {target_name!r} in {source_file!r} via {native_relation!r} "
                f"expected {target_kind!r}, but only found {matched_node.kind!r}; "
                f"created synthetic {target_kind!r} node instead of linking to the wrong kind.",
            )
        elif len(same_name_matches) > 1:
            self._append_warning_once(
                graph,
                f"Ambiguous Stonebranch reference {target_name!r} in {source_file!r} via {native_relation!r}: "
                f"matched {len(same_name_matches)} objects by name, created synthetic {target_kind!r} node.",
            )

        metadata = {"synthetic": True, "reason": "referenced_without_object_file"}
        if target_kind == KIND_COMMAND:
            # Command nodes are hash-named helper artifacts; commands are
            # compared at attribute level, never as objects.
            metadata["artifact"] = True
            metadata["semantic_command_hash"] = target_name
        node = self._make_node(
            env=env,
            kind=target_kind,
            name=target_name,
            native_kind=f"referenced:{native_relation}",
            source_file=source_file,
            metadata=metadata,
            attributes=None,
        )
        graph.add_node(node)
        registry["by_kind"][(env, target_kind, target_name.lower())] = node.id
        registry["by_name"].setdefault((env, target_name.lower()), set()).add(node.id)
        return node.id

    def _append_warning_once(self, graph: Graph, warning: str) -> None:
        if warning not in graph.warnings:
            graph.warnings.append(warning)

    def _append_warning_once_raw(self, warnings: list[str], warning: str) -> None:
        if warning not in warnings:
            warnings.append(warning)

    def _add_warnings(self, graph: Graph) -> None:
        synthetic = sum(1 for n in graph.nodes.values() if n.metadata.get("synthetic"))
        if synthetic:
            self._append_warning_once(graph, f"Created {synthetic} synthetic nodes for unresolved references.")
