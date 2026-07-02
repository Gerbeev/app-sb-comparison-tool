from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import Node, enterprise_name_parts, make_canonical_key, make_node_id, stable_hash
from stonebranch_graph.domain import (
    KIND_AGENT,
    KIND_AGENT_CLUSTER,
    KIND_CALENDAR,
    KIND_CONNECTION,
    KIND_CREDENTIAL,
    KIND_EMAIL_TEMPLATE,
    KIND_SCRIPT,
    KIND_TASK,
    KIND_TRIGGER,
    KIND_VARIABLE,
    KIND_WORKFLOW,
    SOURCE_STONEBRANCH,
)
from stonebranch_graph.normalizers import command_hash, command_normalization_diagnostics, semantic_command_hash
from stonebranch_graph.utils import discover_source_files, first_string, normalized_kind, read_json_text, safe_metadata


def load_stonebranch_json_files(input_path: Path, config: AnalyzerConfig) -> list[tuple[Path, str, Any]]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    root = input_path.parent if input_path.is_file() else input_path
    files = discover_source_files(
        input_path,
        extensions={".json"},
        ignored_filenames=config.ignored_filenames,
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


def iter_object_dicts(data: Any, relative_path: str) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    if isinstance(data, dict):
        return [(relative_path, data)], []
    if isinstance(data, list):
        objects: list[tuple[str, dict[str, Any]]] = []
        warnings: list[str] = []
        for idx, item in enumerate(data):
            if isinstance(item, dict):
                objects.append((f"{relative_path}#[{idx}]", item))
            else:
                warnings.append(f"Skipped non-object item in Stonebranch JSON array at {relative_path}#[{idx}].")
        if not objects:
            warnings.append(f"Skipped Stonebranch JSON array with no object items: {relative_path}.")
        return objects, warnings
    return [], [f"Skipped unsupported Stonebranch JSON root in {relative_path}: {type(data).__name__}."]


def kind_from_path(path: Path, config: AnalyzerConfig) -> str | None:
    mapping = config.folder_kind_map or {}
    for part in reversed(path.parts[:-1]):
        kind = mapping.get(part.lower())
        if kind:
            return normalized_kind(kind, config.kind_aliases)
    return None


def env_from_path(path: Path, config: AnalyzerConfig, default_env: str) -> str:
    mapping = config.folder_kind_map or {}
    parts = list(path.parts)
    for idx, part in enumerate(parts):
        if part.lower() in mapping and idx > 0:
            parent = parts[idx - 1]
            if parent.lower() not in mapping:
                return parent
    return default_env


def native_kind(data: dict[str, Any], config: AnalyzerConfig) -> str | None:
    for key in config.stonebranch_type_keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def detect_object_name(data: dict[str, Any], kind: str, path: Path) -> str:
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


def object_metadata(data: dict[str, Any], name: str = "") -> dict[str, Any]:
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


def make_stonebranch_node(
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
