from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path
from typing import Any

from .config import AnalyzerConfig, MappingConfig
from .core import Edge, Graph, Node, enterprise_name_parts, comparison_name, normalize_name
from .domain import (
    KIND_BOX,
    KIND_OBJECT,
    KIND_WORKFLOW,
    KNOWN_SOURCE_SYSTEMS,
    PACK_CRITICAL_RELATIONS,
    REL_CONTAINS,
    REL_DEPENDS_ON_SUCCESS,
    REL_SUCCESSOR_OF,
)
from .exporters import export_csv_rows, write_json
from .metrics import compute_comparison_metrics, metric_rows, metrics_to_dict


@dataclass
class Comparison:
    summary: dict[str, Any] = field(default_factory=dict)
    nodes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    edges: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    attributes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    diagnostics: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "nodes": self.nodes,
            "edges": self.edges,
            "attributes": self.attributes,
            "diagnostics": self.diagnostics,
            "risks": self.risks,
        }


def compare_graphs(stonebranch: Graph, jil: Graph, mapping: MappingConfig, config: AnalyzerConfig) -> Comparison:
    mapping_usage: set[str] = set()
    sb = build_side_indexes(stonebranch, mapping, left=True, mapping_usage=mapping_usage)
    jl = build_side_indexes(jil, mapping, left=False, mapping_usage=mapping_usage)

    matched_keys = sb.node_keys & jl.node_keys
    missing_in_sb = sorted(jl.node_keys - sb.node_keys)
    missing_in_jil = sorted(sb.node_keys - jl.node_keys)
    matched_edge_keys = sb.edge_keys & jl.edge_keys
    missing_edges_in_sb = sorted(jl.edge_keys - sb.edge_keys)
    missing_edges_in_jil = sorted(sb.edge_keys - jl.edge_keys)

    attributes = compare_matched_attributes(matched_keys, sb.node_index, jl.node_index)
    nodes = build_node_diff_payloads(matched_keys, missing_in_sb, missing_in_jil, sb.node_index, jl.node_index)
    edges = build_edge_diff_payloads(
        matched_edge_keys,
        missing_edges_in_sb,
        missing_edges_in_jil,
        sb.edge_index,
        jl.edge_index,
        stonebranch,
        jil,
    )
    diagnostics = build_diagnostics(sb, jl, mapping, mapping_usage)
    summary = build_summary(stonebranch, jil, matched_keys, missing_in_sb, missing_in_jil, matched_edge_keys, missing_edges_in_sb, missing_edges_in_jil, attributes, diagnostics)
    summary.update(metrics_to_dict(compute_comparison_metrics(summary, nodes, edges, attributes, stonebranch, jil)))

    comparison = Comparison(summary=summary, nodes=nodes, edges=edges, attributes=attributes, diagnostics=diagnostics)
    comparison.risks = build_risks(comparison)
    return comparison


@dataclass
class SideComparisonIndex:
    node_index: dict[str, Node]
    node_collisions: list[dict[str, Any]]
    node_keys: set[str]
    edge_index: dict[str, Edge]
    edge_collisions: list[dict[str, Any]]
    edge_keys: set[str]


def build_side_indexes(graph: Graph, mapping: MappingConfig, left: bool, mapping_usage: set[str]) -> SideComparisonIndex:
    node_buckets = bucket_nodes(graph, mapping, left=left, mapping_usage=mapping_usage)
    edge_buckets = bucket_edges(graph, mapping, left=left, mapping_usage=mapping_usage)
    node_index = single_item_index(node_buckets)
    edge_index = single_item_index(edge_buckets)
    return SideComparisonIndex(
        node_index=node_index,
        node_collisions=collision_payload(node_buckets),
        node_keys=set(node_index),
        edge_index=edge_index,
        edge_collisions=edge_collision_payload(edge_buckets, graph),
        edge_keys=set(edge_index),
    )


def single_item_index(buckets: dict[str, list[Any]]) -> dict[str, Any]:
    return {key: items[0] for key, items in buckets.items() if len(items) == 1}


def compare_matched_attributes(matched_keys: set[str], sb_nodes: dict[str, Node], jil_nodes: dict[str, Node]) -> dict[str, list[dict[str, Any]]]:
    changed: list[dict[str, Any]] = []
    command_diff: list[dict[str, Any]] = []
    condition_diff: list[dict[str, Any]] = []

    for key in sorted(matched_keys):
        sb_node = sb_nodes[key]
        jil_node = jil_nodes[key]
        if comparable_hash(sb_node) and comparable_hash(jil_node) and sb_node.attributes_hash != jil_node.attributes_hash:
            changed.append(node_pair_payload(sb_node, jil_node, comparison_key=key))
        command_item = command_difference_payload(key, sb_node, jil_node)
        if command_item:
            command_diff.append(command_item)
        condition_item = condition_difference_payload(key, sb_node, jil_node)
        if condition_item:
            condition_diff.append(condition_item)

    return {
        "changed": changed,
        "command_differences": command_diff,
        "condition_differences": condition_diff,
    }


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


def list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


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


def condition_difference_payload(key: str, sb_node: Node, jil_node: Node) -> dict[str, Any] | None:
    sb_condition = sb_node.metadata.get("condition_hash") or sb_node.metadata.get("condition_raw")
    jil_condition = jil_node.metadata.get("condition_hash") or jil_node.metadata.get("condition_raw")
    if not sb_condition or not jil_condition or sb_condition == jil_condition:
        return None
    return {"key": key, "stonebranch_condition": sb_condition, "jil_condition": jil_condition}


def count_command_differences_by_status(attributes: dict[str, list[dict[str, Any]]], status: str) -> int:
    return sum(1 for item in attributes.get("command_differences", []) if item.get("status") == status)


def build_node_diff_payloads(
    matched_keys: set[str],
    missing_in_sb: list[str],
    missing_in_jil: list[str],
    sb_nodes: dict[str, Node],
    jil_nodes: dict[str, Node],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "matched": [node_pair_payload(sb_nodes[key], jil_nodes[key], comparison_key=key) for key in sorted(matched_keys)],
        "missing_in_stonebranch": [node_payload_with_key(jil_nodes[key], key) for key in missing_in_sb],
        "missing_in_jil": [node_payload_with_key(sb_nodes[key], key) for key in missing_in_jil],
    }


def build_edge_diff_payloads(
    matched_edge_keys: set[str],
    missing_edges_in_sb: list[str],
    missing_edges_in_jil: list[str],
    sb_edges: dict[str, Edge],
    jil_edges: dict[str, Edge],
    stonebranch: Graph,
    jil: Graph,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "matched": [
            edge_pair_payload(sb_edges[key], jil_edges[key], stonebranch, jil, comparison_key=key)
            for key in sorted(matched_edge_keys)
        ],
        "missing_in_stonebranch": [edge_payload(jil_edges[key], jil, comparison_key=key) for key in missing_edges_in_sb],
        "missing_in_jil": [edge_payload(sb_edges[key], stonebranch, comparison_key=key) for key in missing_edges_in_jil],
    }


def build_diagnostics(sb: SideComparisonIndex, jl: SideComparisonIndex, mapping: MappingConfig, mapping_usage: set[str]) -> dict[str, list[dict[str, Any]]]:
    return {
        "stonebranch_key_collisions": sb.node_collisions,
        "jil_key_collisions": jl.node_collisions,
        "stonebranch_edge_collisions": sb.edge_collisions,
        "jil_edge_collisions": jl.edge_collisions,
        "unused_mappings": unused_mapping_payload(mapping, mapping_usage),
    }


def build_summary(
    stonebranch: Graph,
    jil: Graph,
    matched_keys: set[str],
    missing_in_sb: list[str],
    missing_in_jil: list[str],
    matched_edge_keys: set[str],
    missing_edges_in_sb: list[str],
    missing_edges_in_jil: list[str],
    attributes: dict[str, list[dict[str, Any]]],
    diagnostics: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "stonebranch_nodes": len(stonebranch.nodes),
        "jil_nodes": len(jil.nodes),
        "matched_nodes": len(matched_keys),
        "missing_in_stonebranch": len(missing_in_sb),
        "missing_in_jil": len(missing_in_jil),
        "stonebranch_edges": len(stonebranch.edges),
        "jil_edges": len(jil.edges),
        "matched_edges": len(matched_edge_keys),
        "missing_edges_in_stonebranch": len(missing_edges_in_sb),
        "missing_edges_in_jil": len(missing_edges_in_jil),
        "changed_attributes": len(attributes.get("changed", [])),
        "command_differences": len(attributes.get("command_differences", [])),
        "command_syntax_diff_only": count_command_differences_by_status(attributes, "command_syntax_diff_only"),
        "command_semantic_mismatches": count_command_differences_by_status(attributes, "command_semantic_mismatch"),
        "condition_differences": len(attributes.get("condition_differences", [])),
        "stonebranch_key_collision_count": len(diagnostics.get("stonebranch_key_collisions", [])),
        "jil_key_collision_count": len(diagnostics.get("jil_key_collisions", [])),
        "stonebranch_edge_collision_count": len(diagnostics.get("stonebranch_edge_collisions", [])),
        "jil_edge_collision_count": len(diagnostics.get("jil_edge_collisions", [])),
        "unused_mapping_count": len(diagnostics.get("unused_mappings", [])),
    }


def bucket_nodes(graph: Graph, mapping: MappingConfig, left: bool, mapping_usage: set[str]) -> dict[str, list[Node]]:
    buckets: dict[str, list[Node]] = {}
    for node in graph.nodes.values():
        key = comparison_node_key(node, mapping, left, mapping_usage)
        buckets.setdefault(key, []).append(node)
    return buckets


def bucket_edges(graph: Graph, mapping: MappingConfig, left: bool, mapping_usage: set[str]) -> dict[str, list[Edge]]:
    buckets: dict[str, list[Edge]] = {}
    for edge in graph.edges.values():
        key = comparison_edge_key(edge, graph, mapping, left, mapping_usage)
        buckets.setdefault(key, []).append(edge)
    return buckets


def comparison_node_key(node: Node, mapping: MappingConfig, left: bool, mapping_usage: set[str] | None = None) -> str:
    if left:
        mapped = lookup_mapping(node, mapping)
        if mapped:
            if mapping_usage is not None:
                mapping_usage.add(mapped[0])
            return normalize_key(mapped[1], mapping)
    return normalize_key(node.canonical_key, mapping)


def lookup_mapping(node: Node, mapping: MappingConfig) -> tuple[str, str] | None:
    candidates = [
        node.id,
        node.canonical_key,
        normalize_key(node.canonical_key, mapping),
        node.name,
        normalize_name(node.name),
    ]
    for candidate in candidates:
        if candidate in mapping.node_mappings:
            return candidate, mapping.node_mappings[candidate]
    return None


def normalize_key(key: str, mapping: MappingConfig) -> str:
    key = str(key)
    parts = key.split(":", 3)
    # Accept source_system:env:kind:name IDs and env:kind:name canonical keys.
    if len(parts) == 4 and parts[0] in KNOWN_SOURCE_SYSTEMS:
        _, env, kind, name = parts
    elif len(parts) == 3:
        env, kind, name = parts
    else:
        env, kind, name = "default", KIND_OBJECT, key
    kind = comparison_kind(mapping.kind_aliases.get(kind, kind))
    name = normalize_name(comparison_name(name))
    for rule in mapping.name_rewrites:
        pattern = rule.get("from", "")
        repl = rule.get("to", "")
        if pattern:
            name = re.sub(pattern, repl, name)
    return f"{env}:{kind}:{name}"




def comparison_kind(kind: str) -> str:
    """Return kind used for cross-system comparison keys.

    AutoSys boxes and Stonebranch workflows represent the same containment
    concept in migration analysis, so compare them as box-like containers while
    preserving the original node kind in graph.json and reports.
    """
    if kind == KIND_WORKFLOW:
        return KIND_BOX
    return kind

def comparison_edge_key(edge: Edge, graph: Graph, mapping: MappingConfig, left: bool, mapping_usage: set[str] | None = None) -> str:
    components = comparison_edge_components(edge, graph)
    if components is None:
        return f"broken:{edge.id}"
    source, relation, target = components
    return f"{comparison_node_key(source, mapping, left, mapping_usage)}->{relation}->{comparison_node_key(target, mapping, left, mapping_usage)}"


def comparison_edge_components(edge: Edge, graph: Graph) -> tuple[Node, str, Node] | None:
    source = graph.nodes.get(edge.source)
    target = graph.nodes.get(edge.target)
    if not source or not target:
        return None

    relation = edge.relation
    if relation == REL_SUCCESSOR_OF:
        # Legacy Stonebranch exports represented successorTask as current -> successor.
        # For comparison, normalize to dependent -> prerequisite like AutoSys condition edges.
        return target, REL_DEPENDS_ON_SUCCESS, source

    if relation == REL_CONTAINS and source.kind not in {KIND_BOX, KIND_WORKFLOW} and target.kind in {KIND_BOX, KIND_WORKFLOW}:
        # Legacy task.workflowName edges could be written as task -> contains -> workflow.
        # A containment relation should always point container -> child.
        return target, relation, source

    return source, relation, target


def collision_payload(buckets: dict[str, list[Node]]) -> list[dict[str, Any]]:
    return [node_collision_payload(k, v) for k, v in sorted(buckets.items()) if len(v) > 1]


def node_collision_payload(key: str, nodes: list[Node]) -> dict[str, Any]:
    parts = [node_enterprise_parts(node) for node in nodes]
    populated_parts = [item for item in parts if item]
    reason = "normalized_key_collision"
    if populated_parts and len({item.get("real_name", "") for item in populated_parts}) == 1:
        reason = "enterprise_name_collision"
    return {
        "key": key,
        "reason": reason,
        "count": len(nodes),
        "names": sorted({node.name for node in nodes}),
        "business_codes": sorted({item.get("business_code", "") for item in populated_parts if item.get("business_code")}),
        "env_tokens": sorted({item.get("env_token", "") for item in populated_parts if item.get("env_token")}),
        "real_names": sorted({item.get("real_name", "") for item in populated_parts if item.get("real_name")}),
        "nodes": [collision_node_payload(n) for n in nodes],
    }


def node_enterprise_parts(node: Node) -> dict[str, str]:
    metadata_parts = node.metadata.get("enterprise_naming")
    if isinstance(metadata_parts, dict) and metadata_parts.get("real_name"):
        return {str(key): str(value) for key, value in metadata_parts.items()}
    return enterprise_name_parts(node.name)


def collision_node_payload(node: Node) -> dict[str, Any]:
    payload = node_payload(node)
    parts = node_enterprise_parts(node)
    if parts:
        payload["enterprise_naming"] = parts
    return payload


def edge_collision_payload(buckets: dict[str, list[Edge]], graph: Graph) -> list[dict[str, Any]]:
    return [{"key": k, "edges": [edge_payload(e, graph) for e in v]} for k, v in sorted(buckets.items()) if len(v) > 1]


def unused_mapping_payload(mapping: MappingConfig, used: set[str]) -> list[dict[str, str]]:
    return [{"stonebranch": k, "jil": v} for k, v in sorted(mapping.node_mappings.items()) if k not in used]


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


def edge_key_parts(comparison_key: str | None) -> tuple[str, str, str] | None:
    if not comparison_key or "->" not in comparison_key:
        return None
    parts = comparison_key.split("->", 2)
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


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


def build_risks(comparison: Comparison) -> list[str]:
    risks: list[str] = []
    s = comparison.summary
    if s.get("missing_edges_in_stonebranch", 0):
        risks.append("JIL dependencies exist that were not found in Stonebranch. Possible lost migration dependencies.")
    if s.get("missing_edges_in_jil", 0):
        risks.append("Stonebranch dependencies exist that were not found in JIL. Possible new/extra orchestration behavior.")
    if s.get("missing_in_stonebranch", 0):
        risks.append("JIL objects exist without Stonebranch matches.")
    if s.get("missing_in_jil", 0):
        risks.append("Stonebranch objects exist without JIL matches.")
    if s.get("command_semantic_mismatches", 0):
        risks.append("Matched objects have semantically different command hashes.")
    if s.get("command_syntax_diff_only", 0):
        risks.append("Matched objects have command syntax differences only after variable/environment/script-path normalization.")
    if s.get("condition_differences", 0):
        risks.append("Matched objects have different condition hashes.")
    if s.get("critical_dependency_loss_count", 0):
        risks.append("Critical JIL dependency edges are missing in Stonebranch.")
    if s.get("calendar_mismatch_count", 0):
        risks.append("Calendar relation mismatches detected.")
    if s.get("agent_machine_mismatch_count", 0):
        risks.append("Agent/machine runtime target mismatches detected.")
    if s.get("jil_conditions_not_parsed_count", 0):
        risks.append("Some JIL conditions were detected but no condition dependencies were parsed.")
    if s.get("stonebranch_key_collision_count", 0) or s.get("jil_key_collision_count", 0):
        risks.append("Normalized node key collisions detected, including possible enterprise-name collisions. Some matches were excluded to avoid false positives.")
    if s.get("unused_mapping_count", 0):
        risks.append("Some manual mapping rules were not used. Check mapping-diagnostics.csv.")
    if s.get("migration_readiness_score", 100) < 70:
        risks.append("Migration readiness score is below 70. Manual review is required before production use.")
    return risks


def export_comparison(
    comparison: Comparison,
    output_dir: Path,
    stonebranch: Graph,
    jil: Graph,
) -> None:
    compare_dir = output_dir / "compare"
    compare_dir.mkdir(parents=True, exist_ok=True)
    write_json(compare_dir / "comparison.json", comparison.to_dict())
    write_json(compare_dir / "metrics.json", comparison.summary)
    export_csv_rows(compare_dir / "metrics.csv", ["metric", "value"], metric_rows(comparison.summary))
    write_report(compare_dir / "report.md", comparison)
    write_missing_csvs(compare_dir, comparison)
    write_edge_diff_csv(compare_dir, comparison)
    write_command_diff_csv(compare_dir, comparison)
    write_diagnostics_csv(compare_dir, comparison)
    write_diff_index(compare_dir, comparison)
    write_critical_diff(compare_dir, comparison)
    write_remediation_plan(compare_dir, comparison)
    from .html_graph import export_comparison_html_report
    export_comparison_html_report(comparison, stonebranch, jil, output_dir)


def write_report(path: Path, comparison: Comparison) -> None:
    s = comparison.summary
    lines = [
        "# Stonebranch vs JIL comparison report", "", "## Summary", "",
        f"- Stonebranch nodes: **{s.get('stonebranch_nodes', 0)}**",
        f"- JIL nodes: **{s.get('jil_nodes', 0)}**",
        f"- Matched nodes: **{s.get('matched_nodes', 0)}**",
        f"- Missing in Stonebranch: **{s.get('missing_in_stonebranch', 0)}**",
        f"- Missing in JIL: **{s.get('missing_in_jil', 0)}**",
        f"- Stonebranch edges: **{s.get('stonebranch_edges', 0)}**",
        f"- JIL edges: **{s.get('jil_edges', 0)}**",
        f"- Matched edges: **{s.get('matched_edges', 0)}**",
        f"- Missing edges in Stonebranch: **{s.get('missing_edges_in_stonebranch', 0)}**",
        f"- Missing edges in JIL: **{s.get('missing_edges_in_jil', 0)}**", "", "## Migration metrics", "",
        f"- Migration readiness score: **{s.get('migration_readiness_score', 0)}/100** (`{s.get('readiness_grade', 'unknown')}`)",
        f"- Node match rate: **{s.get('node_match_rate_percent', 0)}%**",
        f"- Edge match rate: **{s.get('edge_match_rate_percent', 0)}%**",
        f"- Critical dependency loss count: **{s.get('critical_dependency_loss_count', 0)}**",
        f"- Calendar mismatch count: **{s.get('calendar_mismatch_count', 0)}**",
        f"- Agent/machine mismatch count: **{s.get('agent_machine_mismatch_count', 0)}**",
        f"- Command mismatch count: **{s.get('command_mismatch_count', 0)}**",
        f"- Command syntax-only differences: **{s.get('command_syntax_diff_only', 0)}**",
        f"- Node key collisions: **{s.get('stonebranch_key_collision_count', 0) + s.get('jil_key_collision_count', 0)}**",
        f"- Unused mappings: **{s.get('unused_mapping_count', 0)}**", "", "## Critical risks", "",
    ]
    if comparison.risks:
        lines += [f"- {risk}" for risk in comparison.risks]
    else:
        lines.append("- No critical graph risks detected by the current rules.")
    append_collision_section(lines, comparison)
    append_command_normalization_section(lines, comparison)
    lines += ["", "## Missing objects in Stonebranch", "", "| Kind | Object | JIL source |", "|---|---|---|"]
    for item in comparison.nodes.get("missing_in_stonebranch", [])[:200]:
        lines.append(f"| {item['kind']} | `{item['name']}` | `{item['source_file']}` |")
    lines += ["", "## Missing objects in JIL", "", "| Kind | Object | Stonebranch source |", "|---|---|---|"]
    for item in comparison.nodes.get("missing_in_jil", [])[:200]:
        lines.append(f"| {item['kind']} | `{item['name']}` | `{item['source_file']}` |")
    lines += ["", "## Missing dependencies in Stonebranch", "", "| Relation | Source | Target | Evidence |", "|---|---|---|---|"]
    for item in comparison.edges.get("missing_in_stonebranch", [])[:200]:
        lines.append(f"| {item['relation']} | `{item['source'].get('name', item['source'].get('id'))}` | `{item['target'].get('name', item['target'].get('id'))}` | `{item['evidence_file']}` |")
    lines += ["", "## Missing dependencies in JIL", "", "| Relation | Source | Target | Evidence |", "|---|---|---|---|"]
    for item in comparison.edges.get("missing_in_jil", [])[:200]:
        lines.append(f"| {item['relation']} | `{item['source'].get('name', item['source'].get('id'))}` | `{item['target'].get('name', item['target'].get('id'))}` | `{item['evidence_file']}` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_command_normalization_section(lines: list[str], comparison: Comparison) -> None:
    items = comparison.attributes.get("command_differences", [])
    if not items:
        return
    lines += [
        "",
        "## Command normalization diagnostics",
        "",
        "| Status | Object | Reasons | Variables | Env tokens | Scripts |",
        "|---|---|---|---|---|---|",
    ]
    for item in items[:100]:
        reasons = ", ".join(item.get("normalization_reasons", [])) or "n/a"
        variables = ", ".join(item.get("variable_names", [])) or "n/a"
        env_tokens = ", ".join(item.get("env_tokens", [])) or "n/a"
        scripts = ", ".join(item.get("script_basenames", [])) or "n/a"
        lines.append(
            f"| `{item.get('status', '')}` | `{item.get('stonebranch', '')}` / `{item.get('jil', '')}` "
            f"| {reasons} | {variables} | {env_tokens} | {scripts} |"
        )


def append_collision_section(lines: list[str], comparison: Comparison) -> None:
    collisions: list[tuple[str, dict[str, Any]]] = []
    for section in ("stonebranch_key_collisions", "jil_key_collisions"):
        for item in comparison.diagnostics.get(section, []):
            collisions.append((section, item))
    if not collisions:
        return
    lines += ["", "## Normalized key collisions", "", "| Side | Key | Reason | Objects |", "|---|---|---|---|"]
    for section, item in collisions[:100]:
        side = "Stonebranch" if section.startswith("stonebranch") else "JIL"
        names = ", ".join(f"`{name}`" for name in item.get("names", []))
        lines.append(f"| {side} | `{item.get('key', '')}` | `{item.get('reason', 'normalized_key_collision')}` | {names} |")


def write_missing_csvs(compare_dir: Path, comparison: Comparison) -> None:
    node_fields = ["id", "canonical_key", "source_system", "env", "kind", "native_kind", "name", "source_file"]
    export_csv_rows(compare_dir / "missing-in-stonebranch.csv", node_fields, comparison.nodes.get("missing_in_stonebranch", []))
    export_csv_rows(compare_dir / "missing-in-jil.csv", node_fields, comparison.nodes.get("missing_in_jil", []))


def write_edge_diff_csv(compare_dir: Path, comparison: Comparison) -> None:
    rows = []
    for side in ("missing_in_stonebranch", "missing_in_jil"):
        for item in comparison.edges.get(side, []):
            rows.append({
                "side": side,
                "relation": item["relation"],
                "source": item.get("source_key") or item["source"].get("canonical_key", item["source"].get("id")),
                "target": item.get("target_key") or item["target"].get("canonical_key", item["target"].get("id")),
                "evidence_file": item.get("evidence_file", ""),
                "evidence_key": item.get("evidence_key", ""),
                "evidence_value": item.get("evidence_value", ""),
            })
    export_csv_rows(compare_dir / "edge-diff.csv", ["side", "relation", "source", "target", "evidence_file", "evidence_key", "evidence_value"], rows)


def write_command_diff_csv(compare_dir: Path, comparison: Comparison) -> None:
    fields = [
        "status",
        "key",
        "stonebranch",
        "jil",
        "strict_match",
        "semantic_match",
        "normalization_reasons",
        "variable_names",
        "env_tokens",
        "script_basenames",
        "stonebranch_command_hash",
        "jil_command_hash",
        "stonebranch_semantic_command_hash",
        "jil_semantic_command_hash",
        "stonebranch_semantic_preview",
        "jil_semantic_preview",
        "semantic_preview_truncated",
        "reason",
    ]
    rows = []
    for item in comparison.attributes.get("command_differences", []):
        sb_norm = item.get("stonebranch_command_normalization", {})
        jil_norm = item.get("jil_command_normalization", {})
        if not isinstance(sb_norm, dict):
            sb_norm = {}
        if not isinstance(jil_norm, dict):
            jil_norm = {}
        rows.append({
            "status": item.get("status", ""),
            "key": item.get("key", ""),
            "stonebranch": item.get("stonebranch", ""),
            "jil": item.get("jil", ""),
            "strict_match": str(bool(item.get("strict_match", False))).lower(),
            "semantic_match": str(bool(item.get("semantic_match", False))).lower(),
            "normalization_reasons": ";".join(item.get("normalization_reasons", [])),
            "variable_names": ";".join(item.get("variable_names", [])),
            "env_tokens": ";".join(item.get("env_tokens", [])),
            "script_basenames": ";".join(item.get("script_basenames", [])),
            "stonebranch_command_hash": item.get("stonebranch_command_hash", ""),
            "jil_command_hash": item.get("jil_command_hash", ""),
            "stonebranch_semantic_command_hash": item.get("stonebranch_semantic_command_hash", ""),
            "jil_semantic_command_hash": item.get("jil_semantic_command_hash", ""),
            "stonebranch_semantic_preview": sb_norm.get("semantic_preview", ""),
            "jil_semantic_preview": jil_norm.get("semantic_preview", ""),
            "semantic_preview_truncated": str(bool(sb_norm.get("semantic_preview_truncated") or jil_norm.get("semantic_preview_truncated"))).lower(),
            "reason": item.get("reason", ""),
        })
    export_csv_rows(compare_dir / "command-diff.csv", fields, rows)


def write_diagnostics_csv(compare_dir: Path, comparison: Comparison) -> None:
    collision_rows = []
    for section in ("stonebranch_key_collisions", "jil_key_collisions"):
        for item in comparison.diagnostics.get(section, []):
            collision_rows.append({
                "section": section,
                "key": item["key"],
                "reason": item.get("reason", "normalized_key_collision"),
                "count": item.get("count", len(item.get("nodes", []))),
                "names": ";".join(item.get("names", [])),
                "business_codes": ";".join(item.get("business_codes", [])),
                "env_tokens": ";".join(item.get("env_tokens", [])),
                "real_names": ";".join(item.get("real_names", [])),
                "objects": ";".join(n.get("id", "") for n in item.get("nodes", [])),
                "source_files": ";".join(sorted({n.get("source_file", "") for n in item.get("nodes", []) if n.get("source_file")})),
            })
    export_csv_rows(
        compare_dir / "collisions.csv",
        [
            "section",
            "key",
            "reason",
            "count",
            "names",
            "business_codes",
            "env_tokens",
            "real_names",
            "objects",
            "source_files",
        ],
        collision_rows,
    )
    export_csv_rows(compare_dir / "mapping-diagnostics.csv", ["stonebranch", "jil"], comparison.diagnostics.get("unused_mappings", []))


def write_diff_index(compare_dir: Path, comparison: Comparison) -> None:
    diff_index = {
        "missing_in_stonebranch": comparison.nodes.get("missing_in_stonebranch", []),
        "missing_in_jil": comparison.nodes.get("missing_in_jil", []),
        "missing_edges_in_stonebranch": comparison.edges.get("missing_in_stonebranch", []),
        "missing_edges_in_jil": comparison.edges.get("missing_in_jil", []),
        "command_differences": comparison.attributes.get("command_differences", []),
        "condition_differences": comparison.attributes.get("condition_differences", []),
    }
    write_json(compare_dir / "diff-index.json", diff_index)


def write_critical_diff(compare_dir: Path, comparison: Comparison) -> None:
    critical = {
        "missing_critical_edges_in_stonebranch": [
            edge for edge in comparison.edges.get("missing_in_stonebranch", [])
            if edge.get("relation") in PACK_CRITICAL_RELATIONS
        ],
        "missing_critical_edges_in_jil": [
            edge for edge in comparison.edges.get("missing_in_jil", [])
            if edge.get("relation") in PACK_CRITICAL_RELATIONS
        ],
        "missing_objects_in_stonebranch": comparison.nodes.get("missing_in_stonebranch", []),
        "missing_objects_in_jil": comparison.nodes.get("missing_in_jil", []),
        "command_differences": comparison.attributes.get("command_differences", []),
        "condition_differences": comparison.attributes.get("condition_differences", []),
    }
    write_json(compare_dir / "critical-diff.json", critical)


def write_remediation_plan(compare_dir: Path, comparison: Comparison) -> None:
    lines = [
        "# Remediation plan",
        "",
        "Use this file as a working checklist for closing migration gaps.",
        "",
        "## 1. Missing objects in Stonebranch",
        "",
    ]
    for item in comparison.nodes.get("missing_in_stonebranch", [])[:500]:
        lines.append(f"- [ ] Create or map `{item.get('kind')}` `{item.get('name')}` from JIL source `{item.get('source_file')}`.")

    lines.extend(["", "## 2. Missing objects in JIL", ""])
    for item in comparison.nodes.get("missing_in_jil", [])[:500]:
        lines.append(f"- [ ] Review Stonebranch-only `{item.get('kind')}` `{item.get('name')}` from `{item.get('source_file')}`.")

    lines.extend(["", "## 3. Missing dependencies in Stonebranch", ""])
    for edge in comparison.edges.get("missing_in_stonebranch", [])[:500]:
        source = edge.get("source", {})
        target = edge.get("target", {})
        lines.append(
            f"- [ ] Add/check `{edge.get('relation')}` from `{source.get('name', source.get('id'))}` "
            f"to `{target.get('name', target.get('id'))}`. Evidence: `{edge.get('evidence_file')}`."
        )

    lines.extend(["", "## 4. Missing dependencies in JIL / extra Stonebranch behavior", ""])
    for edge in comparison.edges.get("missing_in_jil", [])[:500]:
        source = edge.get("source", {})
        target = edge.get("target", {})
        lines.append(
            f"- [ ] Review Stonebranch `{edge.get('relation')}` from `{source.get('name', source.get('id'))}` "
            f"to `{target.get('name', target.get('id'))}`. Evidence: `{edge.get('evidence_file')}`."
        )

    lines.extend(["", "## 5. Command differences", ""])
    for item in comparison.attributes.get("command_differences", [])[:500]:
        status = item.get("status", "command_semantic_mismatch")
        if status == "command_syntax_diff_only":
            reasons = ", ".join(item.get("normalization_reasons", [])) or "command syntax"
            lines.append(
                f"- [ ] Review variable/environment/script-path syntax mapping for `{item.get('stonebranch')}` / `{item.get('jil')}`. Reasons: {reasons}."
            )
        else:
            lines.append(f"- [ ] Compare semantic command behavior for `{item.get('stonebranch')}` / `{item.get('jil')}`.")

    lines.extend(["", "## 6. Condition differences", ""])
    for item in comparison.attributes.get("condition_differences", [])[:500]:
        lines.append(f"- [ ] Compare condition for `{item.get('key')}`.")

    write_json(compare_dir / "remediation-summary.json", {
        "missing_in_stonebranch": len(comparison.nodes.get("missing_in_stonebranch", [])),
        "missing_in_jil": len(comparison.nodes.get("missing_in_jil", [])),
        "missing_edges_in_stonebranch": len(comparison.edges.get("missing_in_stonebranch", [])),
        "missing_edges_in_jil": len(comparison.edges.get("missing_in_jil", [])),
        "command_differences": len(comparison.attributes.get("command_differences", [])),
        "command_syntax_diff_only": count_command_differences_by_status(comparison.attributes, "command_syntax_diff_only"),
        "command_semantic_mismatches": count_command_differences_by_status(comparison.attributes, "command_semantic_mismatch"),
        "condition_differences": len(comparison.attributes.get("condition_differences", [])),
    })
    (compare_dir / "remediation-plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

