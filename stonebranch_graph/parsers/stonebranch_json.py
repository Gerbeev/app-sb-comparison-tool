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
)
from stonebranch_graph.utils import first_string, is_secret_key, normalized_kind, safe_metadata


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
        graph = Graph(source_system="stonebranch", env=self.env)
        records: list[tuple[Path, str, str, str, dict[str, Any]]] = []

        for path, relative_path, data in files:
            if not isinstance(data, dict):
                continue

            kind = self._kind_from_path(path)
            if not kind:
                continue

            env = self._env_from_path(path) if self.env_aware else self.env
            name = self._detect_object_name(data, kind, path)
            native_kind = self._native_kind(data) or kind
            node = self._make_node(
                env=env,
                kind=kind,
                name=name,
                native_kind=native_kind,
                source_file=relative_path,
                metadata=self._object_metadata(data),
                attributes=data,
            )
            graph.add_node(node)
            records.append((path, relative_path, env, name, data))

        registry = self._build_registry(graph)

        for path, relative_path, env, source_name, data in records:
            source_kind = self._kind_from_path(path)
            if not source_kind:
                continue
            source_id = make_node_id("stonebranch", env, source_kind, source_name)

            for ref in self._find_references(data):
                ref_value, native_relation, relation, evidence_path, evidence_key = ref
                relation = self._normalized_relation_for_source(native_relation, source_kind, evidence_key)
                target_kind = self._kind_from_relation(native_relation, relation)
                target_name = self._target_name_for_relation(ref_value, native_relation, relation)
                target_id = self._resolve_or_create_ref_node(
                    graph=graph,
                    registry=registry,
                    env=env,
                    target_kind=target_kind,
                    target_name=target_name,
                    native_relation=native_relation,
                    source_file=relative_path,
                )
                if not target_id:
                    continue

                edge = Edge(
                    id=make_edge_id(source_id, target_id, relation, native_relation),
                    source=source_id,
                    target=target_id,
                    relation=relation,
                    source_system="stonebranch",
                    native_relation=native_relation,
                    evidence_file=relative_path,
                    evidence_path=evidence_path,
                    evidence_key=evidence_key,
                    evidence_value=redacted_preview(ref_value, self.config.max_evidence_value_len),
                    confidence=0.95 if native_relation != "deep_scan_reference" else 0.55,
                )
                graph.add_edge(edge)

        self._add_warnings(graph)
        return graph

    def _load_json_files(self, input_path: Path) -> list[tuple[Path, str, dict[str, Any]]]:
        if not input_path.exists():
            raise FileNotFoundError(f"Input path does not exist: {input_path}")

        root = input_path.parent if input_path.is_file() else input_path
        if input_path.is_file():
            files = [input_path]
        else:
            ignored = set(self.config.ignored_filenames)
            files = sorted(
                p
                for p in input_path.rglob("*.json")
                if p.name not in ignored and not p.name.startswith(".") and "__pycache__" not in p.parts
            )

        loaded = []
        for file in files:
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                data = json.loads(file.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {file}: {exc}") from exc
            relative = str(file.relative_to(root)) if file.is_relative_to(root) else str(file)
            loaded.append((file, relative, data))
        return loaded

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
            "task": ("name", "Name", "title", "Title", "taskName", "TaskName"),
            "trigger": ("name", "Name", "title", "Title", "triggerName", "TriggerName"),
            "variable": ("name", "Name", "title", "Title", "variableName", "VariableName"),
            "calendar": ("name", "Name", "title", "Title", "calendarName", "CalendarName"),
            "credential": ("name", "Name", "title", "Title", "credentialName", "CredentialName"),
            "connection": ("name", "Name", "title", "Title", "connectionName", "ConnectionName"),
            "agent": ("name", "Name", "title", "Title", "agentName", "AgentName"),
            "agent_cluster": ("name", "Name", "title", "Title", "agentClusterName", "AgentClusterName"),
            "script": ("name", "Name", "title", "Title", "scriptName", "ScriptName"),
            "email_template": ("name", "Name", "title", "Title", "emailTemplateName", "EmailTemplateName"),
        }
        value = first_string(data, kind_specific_keys.get(kind, ("name", "Name", "title", "Title")))
        return value or path.stem

    def _object_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        command = data.get("command") or data.get("Command") or data.get("script") or data.get("Script")
        metadata = {"json_keys": sorted(str(k) for k in data.keys())}
        if isinstance(command, str) and command.strip():
            metadata["command_hash"] = stable_hash(" ".join(command.split()), 16)
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
        attributes_hash = stable_hash(safe_attrs, 16) if safe_attrs else ""
        return Node(
            id=make_node_id("stonebranch", env, kind, name),
            canonical_key=make_canonical_key(env, kind, name),
            source_system="stonebranch",
            env=env,
            kind=kind,
            name=name,
            native_kind=native_kind,
            source_file=source_file,
            attributes_hash=attributes_hash,
            metadata=metadata,
        )

    def _build_registry(self, graph: Graph) -> dict[tuple[str, str], str]:
        registry: dict[tuple[str, str], str] = {}
        for node in graph.nodes.values():
            registry[(node.env, node.name.lower())] = node.id
            registry[(node.env, node.canonical_key.lower())] = node.id
        return registry

    def _find_references(self, data: dict[str, Any]) -> list[tuple[str, str, str, str, str]]:
        refs: list[tuple[str, str, str, str, str]] = []

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
            native = self._native_relation_from_key(key)
            if native:
                refs.append((cleaned, native, self._normalized_relation(native), path, key))

            for token in self._extract_variable_tokens(cleaned):
                refs.append((token, "variable_token", "uses_variable", path, key))

            if self.deep_scan and not native and self._likely_reference(cleaned):
                refs.append((cleaned, "deep_scan_reference", "references", path, key))

        walk(data, "$", "")
        return refs

    def _native_relation_from_key(self, key: str) -> str | None:
        lower = key.lower().replace("-", "_")
        compact = lower.replace("_", "")

        exact_map = {
            "taskname": "references_task",
            "tasks": "references_task",
            "workflowname": "references_workflow",
            "workflows": "references_workflow",
            "jobname": "references_job",
            "jobs": "references_job",
            "variablename": "references_variable",
            "variables": "references_variable",
            "calendarname": "references_calendar",
            "calendar": "references_calendar",
            "calendars": "references_calendar",
            "credentialname": "references_credential",
            "credential": "references_credential",
            "credentials": "references_credential",
            "connectionname": "references_connection",
            "connection": "references_connection",
            "connections": "references_connection",
            "agentname": "references_agent",
            "agent": "references_agent",
            "agents": "references_agent",
            "agentclustername": "references_agent_cluster",
            "agentcluster": "references_agent_cluster",
            "scriptname": "references_script",
            "script": "references_script",
            "emailtemplatename": "references_email_template",
            "emailtemplate": "references_email_template",
            "triggername": "references_trigger",
            "trigger": "references_trigger",
            "command": "references_command",
            "cmd": "references_command",
        }
        if compact in exact_map:
            return exact_map[compact]

        if "predecessor" in compact:
            return "references_predecessor"
        if "successor" in compact:
            return "references_successor"
        if compact.endswith("task") or compact.endswith("taskname"):
            return "references_task"
        if compact.endswith("calendar") or compact.endswith("calendarname"):
            return "references_calendar"
        if compact.endswith("agent") or compact.endswith("agentname"):
            return "references_agent"
        return None

    def _normalized_relation(self, native_relation: str) -> str:
        aliases = self.config.relation_aliases or {}
        return aliases.get(native_relation, native_relation)

    def _normalized_relation_for_source(self, native_relation: str, source_kind: str, evidence_key: str) -> str:
        if native_relation == "variable_token":
            return "uses_variable"
        if source_kind == "trigger" and native_relation in {"references_task", "references_workflow", "references_job"}:
            return "starts"
        return self._normalized_relation(native_relation)

    def _target_name_for_relation(self, value: str, native_relation: str, relation: str) -> str:
        if relation == "runs_command" or native_relation == "references_command":
            return stable_hash(" ".join(value.split()), 16)
        return value

    def _extract_variable_tokens(self, value: str) -> list[str]:
        found: list[str] = []
        for match in VAR_TOKEN_RE.finditer(value):
            token = next((group for group in match.groups() if group), None)
            if token:
                found.append(token.strip())
        return found

    def _likely_reference(self, value: str) -> bool:
        if len(value) > 220 or "\n" in value:
            return False
        if " " in value and not any(sep in value for sep in ("_", "-", "/", ":")):
            return False
        return True

    def _kind_from_relation(self, native_relation: str, relation: str) -> str:
        text = (native_relation + " " + relation).lower()
        if "calendar" in text:
            return "calendar"
        if "credential" in text:
            return "credential"
        if "connection" in text:
            return "connection"
        if "agent_cluster" in text or "agentcluster" in text:
            return "agent_cluster"
        if "agent" in text:
            return "agent"
        if "email_template" in text or "emailtemplate" in text:
            return "email_template"
        if "command" in text:
            return "command"
        if "script" in text:
            return "script"
        if "variable" in text:
            return "variable"
        if "trigger" in text:
            return "trigger"
        if "task" in text or "job" in text or "predecessor" in text or "successor" in text:
            return "task"
        return "object"

    def _resolve_or_create_ref_node(
        self,
        graph: Graph,
        registry: dict[tuple[str, str], str],
        env: str,
        target_kind: str,
        target_name: str,
        native_relation: str,
        source_file: str,
    ) -> str:
        key = (env, target_name.lower())
        if key in registry:
            return registry[key]

        node = self._make_node(
            env=env,
            kind=target_kind,
            name=target_name,
            native_kind=f"referenced:{native_relation}",
            source_file=source_file,
            metadata={"synthetic": True, "reason": "referenced_without_object_file"},
            attributes=None,
        )
        graph.add_node(node)
        registry[(env, target_name.lower())] = node.id
        return node.id

    def _add_warnings(self, graph: Graph) -> None:
        synthetic = sum(1 for n in graph.nodes.values() if n.metadata.get("synthetic"))
        if synthetic:
            graph.warnings.append(f"Created {synthetic} synthetic nodes for unresolved references.")
