from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import (
    Edge,
    Graph,
    Node,
    make_canonical_key,
    make_edge_id,
    make_node_id,
    redacted_preview,
    stable_hash,
    enterprise_name_parts,
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
    KIND_OBJECT,
    KIND_SCRIPT,
    KIND_TASK,
    KIND_TRIGGER,
    KIND_VARIABLE,
    KIND_WORKFLOW,
    REL_DEPENDS_ON,
    REL_DEPENDS_ON_DONE,
    REL_DEPENDS_ON_FAILURE,
    REL_DEPENDS_ON_NOTRUNNING,
    REL_DEPENDS_ON_SUCCESS,
    REL_DEPENDS_ON_TERMINATED,
    REL_REFERENCES,
    REL_CONTAINS,
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
from stonebranch_graph.normalizers import command_evidence, command_hash, command_normalization_diagnostics, semantic_command_hash
from stonebranch_graph.utils import discover_source_files, first_string, is_secret_key, normalized_kind, read_json_text, safe_metadata


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
        files = self._load_json_files(input_path)
        graph = Graph(source_system=SOURCE_STONEBRANCH, env=self.env)
        records: list[tuple[Path, str, str, str, str, dict[str, Any]]] = []
        dependency_records: list[tuple[Path, str, str, dict[str, Any]]] = []

        for path, relative_path, data in files:
            kind = self._kind_from_path(path)
            if not kind:
                if self._is_dependency_definition_path(path):
                    for item_relative_path, item in self._iter_object_dicts(data, relative_path, graph):
                        env = self._env_from_path(path) if self.env_aware else self.env
                        dependency_records.append((path, item_relative_path, env, item))
                    continue
                self._append_warning_once(
                    graph,
                    f"Skipped Stonebranch JSON file outside a configured object-kind folder: {relative_path}.",
                )
                continue
            for item_relative_path, item in self._iter_object_dicts(data, relative_path, graph):
                env = self._env_from_path(path) if self.env_aware else self.env
                name = self._detect_object_name(item, kind, path)
                native_kind = self._native_kind(item) or kind
                node = self._make_node(
                    env=env,
                    kind=kind,
                    name=name,
                    native_kind=native_kind,
                    source_file=item_relative_path,
                    metadata=self._object_metadata(item, name),
                    attributes=item,
                )
                existing = graph.nodes.get(node.id)
                if existing and existing.source_file != item_relative_path:
                    self._append_warning_once(
                        graph,
                        f"Duplicate Stonebranch object id {node.id!r}: keeping first definition from "
                        f"{existing.source_file!r}, merging duplicate from {item_relative_path!r}.",
                    )
                graph.add_node(node)
                records.append((path, item_relative_path, env, kind, name, item))

        if not records and not dependency_records:
            self._append_warning_once(graph, f"No Stonebranch objects were parsed from {input_path}.")

        registry = self._build_registry(graph)

        for path, relative_path, env, data in dependency_records:
            edge = self._dependency_definition_edge(graph, registry, env, relative_path, data)
            if edge:
                graph.add_edge(edge)
            else:
                self._append_warning_once(
                    graph,
                    f"Skipped Stonebranch dependency definition without a clear dependent/prerequisite pair: {relative_path}.",
                )

        for path, relative_path, env, source_kind, source_name, data in records:
            source_id = make_node_id(SOURCE_STONEBRANCH, env, source_kind, source_name)
            for ref_value, native_relation, relation, evidence_path, evidence_key, evidence_value in self._find_references(data, source_kind):
                target_kind = self._kind_from_relation(native_relation, relation)
                target_id = self._resolve_or_create_ref_node(
                    graph=graph,
                    registry=registry,
                    env=env,
                    target_kind=target_kind,
                    target_name=ref_value,
                    native_relation=native_relation,
                    source_file=relative_path,
                )
                edge_source, edge_target, edge_relation, edge_native_relation = self._directed_relation(
                    source_id,
                    target_id,
                    relation,
                    native_relation,
                )
                edge = Edge(
                    id=make_edge_id(edge_source, edge_target, edge_relation, edge_native_relation),
                    source=edge_source,
                    target=edge_target,
                    relation=edge_relation,
                    source_system=SOURCE_STONEBRANCH,
                    native_relation=edge_native_relation,
                    evidence_file=relative_path,
                    evidence_path=evidence_path,
                    evidence_key=evidence_key,
                    evidence_value=redacted_preview(evidence_value, self.config.max_evidence_value_len),
                    confidence=0.95 if native_relation != "deep_scan_reference" else 0.55,
                )
                graph.add_edge(edge)

        self._add_warnings(graph)
        return graph

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

    def _iter_object_dicts(self, data: Any, relative_path: str, graph: Graph) -> list[tuple[str, dict[str, Any]]]:
        if isinstance(data, dict):
            return [(relative_path, data)]
        if isinstance(data, list):
            objects: list[tuple[str, dict[str, Any]]] = []
            for idx, item in enumerate(data):
                if isinstance(item, dict):
                    objects.append((f"{relative_path}#[{idx}]", item))
                else:
                    self._append_warning_once(
                        graph,
                        f"Skipped non-object item in Stonebranch JSON array at {relative_path}#[{idx}].",
                    )
            if not objects:
                self._append_warning_once(graph, f"Skipped Stonebranch JSON array with no object items: {relative_path}.")
            return objects
        self._append_warning_once(graph, f"Skipped unsupported Stonebranch JSON root in {relative_path}: {type(data).__name__}.")
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
        metadata = {"json_keys": sorted(str(k) for k in data.keys())}
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
        found: list[str] = []
        for match in VAR_TOKEN_RE.finditer(value):
            token = next((group for group in match.groups() if group), None)
            if token:
                found.append(token.strip())
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

    def _add_warnings(self, graph: Graph) -> None:
        synthetic = sum(1 for n in graph.nodes.values() if n.metadata.get("synthetic"))
        if synthetic:
            self._append_warning_once(graph, f"Created {synthetic} synthetic nodes for unresolved references.")
