from __future__ import annotations

from typing import Any

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import Graph, Node, comparison_name, enterprise_name_parts, make_canonical_key, make_node_id, stable_hash
from stonebranch_graph.domain import KIND_BOX, KIND_FILE_WATCHER, KIND_TASK, SOURCE_AUTOSYS_JIL
from stonebranch_graph.normalizers import command_hash, command_normalization_diagnostics, normalize_command, semantic_command_hash, condition_hash
from stonebranch_graph.parsers.autosys_model import JilJob
from stonebranch_graph.utils import normalized_kind, safe_metadata


def jil_job_kind(attrs: dict[str, str], config: AnalyzerConfig) -> str:
    raw = attrs.get("job_type", "c").lower()
    mapping = {
        "b": KIND_BOX,
        "box": KIND_BOX,
        "c": KIND_TASK,
        "cmd": KIND_TASK,
        "command": KIND_TASK,
        "f": KIND_FILE_WATCHER,
        "fw": KIND_FILE_WATCHER,
        "file_watcher": KIND_FILE_WATCHER,
    }
    return normalized_kind(mapping.get(raw, raw), config.kind_aliases)


def inferred_box_name_for_job(job: JilJob, job_counts_by_source_file: dict[str, int]) -> str:
    from pathlib import Path

    if job_counts_by_source_file.get(job.source_file, 0) < 2:
        return ""
    stem = Path(job.source_file).stem
    if enterprise_name_parts(stem):
        return stem
    return ""


def is_self_box_reference(job: JilJob, box_name: str, config: AnalyzerConfig) -> bool:
    if jil_job_kind(job.attributes, config) != KIND_BOX:
        return False
    return comparison_name(job.name).lower() == comparison_name(box_name).lower()


def jil_job_metadata(
    job: JilJob,
    config: AnalyzerConfig,
    job_counts_by_source_file: dict[str, int],
) -> dict[str, Any]:
    command = job.attributes.get("command", "")
    condition = job.attributes.get("condition", "")
    metadata = {
        "action": job.action,
        "start_line": job.start_line,
        "command_hash": command_hash(command) if command else "",
        "semantic_command_hash": semantic_command_hash(command) if command else "",
        "command_normalization": command_normalization_diagnostics(command) if command else {},
        "condition_hash": condition_hash(condition) if condition else "",
        "has_condition": bool(condition),
    }
    naming = enterprise_name_parts(job.name)
    if naming:
        metadata["enterprise_naming"] = naming
    inferred_box_name = inferred_box_name_for_job(job, job_counts_by_source_file)
    if inferred_box_name:
        metadata["source_file_box_name"] = inferred_box_name
        inferred_naming = enterprise_name_parts(inferred_box_name)
        if inferred_naming:
            metadata["source_file_box_naming"] = inferred_naming
    if command and config.include_raw_values:
        metadata["command_raw"] = normalize_command(command)
    if condition and config.include_raw_values:
        metadata["condition_raw"] = condition
    return metadata


def make_jil_node(
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
        id=make_node_id(SOURCE_AUTOSYS_JIL, env, kind, name),
        canonical_key=make_canonical_key(env, kind, name),
        source_system=SOURCE_AUTOSYS_JIL,
        env=env,
        kind=kind,
        name=name,
        native_kind=native_kind,
        source_file=source_file,
        attributes_hash=stable_hash(safe_attrs, 16) if safe_attrs else "",
        metadata=metadata,
    )


def ensure_jil_ref_node(
    graph: Graph,
    env: str,
    kind: str,
    name: str,
    native_kind: str,
    source_file: str,
    metadata: dict[str, Any] | None = None,
) -> Node:
    node_id = make_node_id(SOURCE_AUTOSYS_JIL, env, kind, name)
    existing = graph.nodes.get(node_id)
    if existing:
        return existing
    node = make_jil_node(
        env=env,
        kind=kind,
        name=name,
        native_kind=native_kind,
        source_file=source_file,
        metadata={"synthetic": True, **(metadata or {})},
        attributes=None,
    )
    return graph.add_node(node)
