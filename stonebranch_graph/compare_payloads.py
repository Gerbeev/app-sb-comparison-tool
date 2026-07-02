from __future__ import annotations

from typing import Any

from .core import Edge, Graph, Node
from .compare_keys import edge_key_parts

def list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def command_normalization_payload(node: Node) -> dict[str, Any]:
    payload = node.metadata.get("command_normalization")
    if not isinstance(payload, dict):
        return {}
    return {
        "normalization_reasons": list_of_strings(payload.get("normalization_reasons")),
        "variable_names": list_of_strings(payload.get("variable_names")),
        "env_tokens": list_of_strings(payload.get("env_tokens")),
        "script_basenames": list_of_strings(payload.get("script_basenames")),
        "semantic_preview": str(payload.get("semantic_preview", "")),
        "semantic_preview_truncated": bool(payload.get("semantic_preview_truncated", False)),
    }


def combined_command_normalization_diagnostics(left: dict[str, Any], right: dict[str, Any]) -> dict[str, list[str]]:
    reason_set = set(list_of_strings(left.get("normalization_reasons"))) | set(list_of_strings(right.get("normalization_reasons")))
    reason_order = ["variable_syntax", "environment_token", "script_path", "case_whitespace_or_quoting"]
    ordered_reasons = [reason for reason in reason_order if reason in reason_set]
    ordered_reasons.extend(sorted(reason_set - set(reason_order)))
    return {
        "normalization_reasons": ordered_reasons,
        "variable_names": sorted(set(list_of_strings(left.get("variable_names"))) | set(list_of_strings(right.get("variable_names")))),
        "env_tokens": sorted(set(list_of_strings(left.get("env_tokens"))) | set(list_of_strings(right.get("env_tokens")))),
        "script_basenames": sorted(set(list_of_strings(left.get("script_basenames"))) | set(list_of_strings(right.get("script_basenames")))),
    }


def command_difference_reason(semantic_match: bool, reasons: list[str]) -> str:
    if not semantic_match:
        return "Command differs after semantic normalization."
    labels = {
        "variable_syntax": "variable syntax",
        "environment_token": "environment token",
        "script_path": "script path",
        "case_whitespace_or_quoting": "case, whitespace, or quoting",
    }
    reason_text = ", ".join(labels.get(reason, reason) for reason in reasons) or "semantic command normalization"
    return f"Command differs only by {reason_text}."


def command_difference_payload(key: str, sb_node: Node, jil_node: Node) -> dict[str, Any] | None:
    sb_command = sb_node.metadata.get("command_hash")
    jil_command = jil_node.metadata.get("command_hash")
    if not sb_command or not jil_command or sb_command == jil_command:
        return None

    sb_semantic = sb_node.metadata.get("semantic_command_hash")
    jil_semantic = jil_node.metadata.get("semantic_command_hash")
    semantic_match = bool(sb_semantic and jil_semantic and sb_semantic == jil_semantic)
    status = "command_syntax_diff_only" if semantic_match else "command_semantic_mismatch"
    sb_diagnostics = command_normalization_payload(sb_node)
    jil_diagnostics = command_normalization_payload(jil_node)
    combined = combined_command_normalization_diagnostics(sb_diagnostics, jil_diagnostics)
    return {
        "key": key,
        "status": status,
        "strict_match": False,
        "semantic_match": semantic_match,
        "stonebranch": sb_node.name,
        "jil": jil_node.name,
        "stonebranch_command_hash": sb_command,
        "jil_command_hash": jil_command,
        "stonebranch_semantic_command_hash": sb_semantic or "",
        "jil_semantic_command_hash": jil_semantic or "",
        "normalization_reasons": combined["normalization_reasons"],
        "variable_names": combined["variable_names"],
        "env_tokens": combined["env_tokens"],
        "script_basenames": combined["script_basenames"],
        "stonebranch_command_normalization": sb_diagnostics,
        "jil_command_normalization": jil_diagnostics,
        "reason": command_difference_reason(semantic_match, combined["normalization_reasons"]),
    }


def condition_difference_payload(key: str, sb_node: Node, jil_node: Node) -> dict[str, Any] | None:
    sb_condition = sb_node.metadata.get("condition_hash") or sb_node.metadata.get("condition_raw")
    jil_condition = jil_node.metadata.get("condition_hash") or jil_node.metadata.get("condition_raw")
    if not sb_condition or not jil_condition or sb_condition == jil_condition:
        return None
    return {"key": key, "stonebranch_condition": sb_condition, "jil_condition": jil_condition}


def count_command_differences_by_status(attributes: dict[str, list[dict[str, Any]]], status: str) -> int:
    return sum(1 for item in attributes.get("command_differences", []) if item.get("status") == status)


def comparable_hash(node: Node) -> bool:
    return bool(node.attributes_hash)


def node_payload(node: Node | None) -> dict[str, Any]:
    if node is None:
        return {}
    return {
        "id": node.id,
        "canonical_key": node.canonical_key,
        "source_system": node.source_system,
        "env": node.env,
        "kind": node.kind,
        "native_kind": node.native_kind,
        "name": node.name,
        "source_file": node.source_file,
        "attributes_hash": node.attributes_hash,
    }


def node_payload_with_key(node: Node | None, comparison_key: str) -> dict[str, Any]:
    payload = node_payload(node)
    if payload:
        payload["comparison_key"] = comparison_key
    return payload


def node_pair_payload(left: Node, right: Node, comparison_key: str | None = None) -> dict[str, Any]:
    key = comparison_key or left.canonical_key
    return {"key": key, "stonebranch": node_payload(left), "jil": node_payload(right)}


def edge_payload(edge: Edge, graph: Graph, comparison_key: str | None = None) -> dict[str, Any]:
    source = graph.nodes.get(edge.source)
    target = graph.nodes.get(edge.target)
    payload = {
        "id": edge.id,
        "relation": edge.relation,
        "native_relation": edge.native_relation,
        "source": node_payload(source) if source else {"id": edge.source},
        "target": node_payload(target) if target else {"id": edge.target},
        "evidence_file": edge.evidence_file,
        "evidence_key": edge.evidence_key,
        "evidence_value": edge.evidence_value,
        "confidence": edge.confidence,
    }
    parts = edge_key_parts(comparison_key)
    if parts:
        source_key, relation, target_key = parts
        payload["comparison_key"] = comparison_key
        payload["source_key"] = source_key
        payload["relation_key"] = relation
        payload["target_key"] = target_key
    return payload


def edge_pair_payload(
    left: Edge,
    right: Edge,
    left_graph: Graph,
    right_graph: Graph,
    comparison_key: str | None = None,
) -> dict[str, Any]:
    return {
        "key": comparison_key or "",
        "stonebranch": edge_payload(left, left_graph, comparison_key=comparison_key),
        "jil": edge_payload(right, right_graph, comparison_key=comparison_key),
    }
