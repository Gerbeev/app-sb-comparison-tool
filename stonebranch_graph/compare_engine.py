from __future__ import annotations

from typing import Any

from .config import AnalyzerConfig, MappingConfig
from .core import Edge, Graph, Node
from .domain import REL_CONTAINS
from .metrics import compute_comparison_metrics, metrics_to_dict
from .comparison_model import Comparison, SideComparisonIndex
from .compare_keys import comparison_edge_key, comparison_node_key
from .compare_diagnostics import collision_payload, edge_collision_payload, unused_mapping_payload
from .compare_payloads import (
    command_difference_payload,
    comparable_hash,
    condition_difference_payload,
    count_command_differences_by_status,
    edge_pair_payload,
    edge_payload,
    node_pair_payload,
    node_payload,
    node_payload_with_key,
)

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
