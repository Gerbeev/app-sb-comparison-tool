from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from .core import Edge, Graph, Node


CRITICAL_DEPENDENCY_RELATIONS = {
    "depends_on",
    "depends_on_success",
    "depends_on_done",
    "depends_on_failure",
    "depends_on_terminated",
    "depends_on_notrunning",
    "contains",
}

RUNTIME_TARGET_RELATIONS = {
    "runs_on",
    "runs_on_cluster",
}

CALENDAR_RELATIONS = {
    "uses_calendar",
    "excludes_calendar",
}

SCHEDULE_RELATIONS = {
    "starts",
    "uses_calendar",
    "excludes_calendar",
}

COMMAND_RELATIONS = {
    "runs_command",
    "runs_script",
}


@dataclass(frozen=True)
class GraphMetrics:
    source_system: str
    env: str
    nodes_total: int
    edges_total: int
    task_nodes: int
    synthetic_nodes: int
    low_confidence_edges: int
    orphan_nodes: int
    orphan_tasks: int
    tasks_without_inbound_dependency: int
    tasks_without_outbound_dependency: int
    tasks_without_trigger: int
    condition_nodes: int
    conditions_not_parsed: int
    object_types: dict[str, int]
    relation_types: dict[str, int]


@dataclass(frozen=True)
class ComparisonMetrics:
    node_match_rate_percent: float
    edge_match_rate_percent: float
    jil_to_stonebranch_node_coverage_percent: float
    stonebranch_to_jil_node_coverage_percent: float
    jil_to_stonebranch_edge_coverage_percent: float
    stonebranch_to_jil_edge_coverage_percent: float
    critical_dependency_loss_count: int
    critical_dependency_extra_count: int
    calendar_mismatch_count: int
    agent_machine_mismatch_count: int
    command_mismatch_count: int
    condition_mismatch_count: int
    stonebranch_synthetic_nodes: int
    jil_synthetic_nodes: int
    synthetic_nodes_total: int
    stonebranch_low_confidence_edges: int
    jil_low_confidence_edges: int
    low_confidence_edges_total: int
    stonebranch_orphan_tasks: int
    jil_orphan_tasks: int
    stonebranch_tasks_without_trigger: int
    jil_conditions_not_parsed_count: int
    migration_readiness_score: int
    readiness_grade: str


def compute_graph_metrics(graph: Graph) -> GraphMetrics:
    inbound, outbound = degree_maps(graph)
    object_types = Counter(node.kind for node in graph.nodes.values())
    relation_types = Counter(edge.relation for edge in graph.edges.values())

    task_ids = {node.id for node in graph.nodes.values() if node.kind == "task"}
    synthetic_nodes = sum(1 for node in graph.nodes.values() if bool(node.metadata.get("synthetic")))
    low_confidence_edges = sum(1 for edge in graph.edges.values() if edge.confidence < 0.8)

    orphan_nodes = sum(1 for node_id in graph.nodes if inbound[node_id] == 0 and outbound[node_id] == 0)
    orphan_tasks = sum(1 for node_id in task_ids if inbound[node_id] == 0 and outbound[node_id] == 0)
    tasks_without_inbound_dependency = sum(1 for node_id in task_ids if inbound[node_id] == 0)
    tasks_without_outbound_dependency = sum(1 for node_id in task_ids if outbound[node_id] == 0)

    task_ids_with_trigger = {
        edge.target
        for edge in graph.edges.values()
        if edge.relation == "starts" and edge.target in task_ids
    }
    tasks_without_trigger = max(0, len(task_ids - task_ids_with_trigger))

    condition_nodes = sum(1 for node in graph.nodes.values() if bool(node.metadata.get("has_condition")))
    condition_edge_sources = {
        edge.source
        for edge in graph.edges.values()
        if edge.native_relation.startswith("condition_") or edge.relation.startswith("depends_on_")
    }
    conditions_not_parsed = sum(
        1
        for node in graph.nodes.values()
        if bool(node.metadata.get("has_condition")) and node.id not in condition_edge_sources
    )

    return GraphMetrics(
        source_system=graph.source_system,
        env=graph.env,
        nodes_total=len(graph.nodes),
        edges_total=len(graph.edges),
        task_nodes=len(task_ids),
        synthetic_nodes=synthetic_nodes,
        low_confidence_edges=low_confidence_edges,
        orphan_nodes=orphan_nodes,
        orphan_tasks=orphan_tasks,
        tasks_without_inbound_dependency=tasks_without_inbound_dependency,
        tasks_without_outbound_dependency=tasks_without_outbound_dependency,
        tasks_without_trigger=tasks_without_trigger,
        condition_nodes=condition_nodes,
        conditions_not_parsed=conditions_not_parsed,
        object_types=dict(sorted(object_types.items())),
        relation_types=dict(sorted(relation_types.items())),
    )


def compute_comparison_metrics(
    summary: dict[str, int],
    comparison_nodes: dict[str, list[dict[str, Any]]],
    comparison_edges: dict[str, list[dict[str, Any]]],
    comparison_attributes: dict[str, list[dict[str, Any]]],
    stonebranch: Graph,
    jil: Graph,
) -> ComparisonMetrics:
    sb_graph_metrics = compute_graph_metrics(stonebranch)
    jil_graph_metrics = compute_graph_metrics(jil)

    missing_in_sb_edges = comparison_edges.get("missing_in_stonebranch", [])
    missing_in_jil_edges = comparison_edges.get("missing_in_jil", [])

    critical_loss = count_edges_by_relations(missing_in_sb_edges, CRITICAL_DEPENDENCY_RELATIONS)
    critical_extra = count_edges_by_relations(missing_in_jil_edges, CRITICAL_DEPENDENCY_RELATIONS)

    calendar_mismatch = relation_diff_count(missing_in_sb_edges, missing_in_jil_edges, CALENDAR_RELATIONS)
    agent_machine_mismatch = relation_diff_count(missing_in_sb_edges, missing_in_jil_edges, RUNTIME_TARGET_RELATIONS)

    node_match_rate = percent(
        summary.get("matched_nodes", 0) * 2,
        summary.get("stonebranch_nodes", 0) + summary.get("jil_nodes", 0),
    )
    edge_match_rate = percent(
        summary.get("matched_edges", 0) * 2,
        summary.get("stonebranch_edges", 0) + summary.get("jil_edges", 0),
    )

    jil_to_sb_node_coverage = percent(
        summary.get("matched_nodes", 0),
        summary.get("jil_nodes", 0),
    )
    sb_to_jil_node_coverage = percent(
        summary.get("matched_nodes", 0),
        summary.get("stonebranch_nodes", 0),
    )
    jil_to_sb_edge_coverage = percent(
        summary.get("matched_edges", 0),
        summary.get("jil_edges", 0),
    )
    sb_to_jil_edge_coverage = percent(
        summary.get("matched_edges", 0),
        summary.get("stonebranch_edges", 0),
    )

    command_mismatch = len(comparison_attributes.get("command_differences", []))
    condition_mismatch = len(comparison_attributes.get("condition_differences", []))

    readiness_score = compute_readiness_score(
        node_match_rate=node_match_rate,
        edge_match_rate=edge_match_rate,
        critical_dependency_loss_count=critical_loss,
        critical_dependency_extra_count=critical_extra,
        calendar_mismatch_count=calendar_mismatch,
        agent_machine_mismatch_count=agent_machine_mismatch,
        command_mismatch_count=command_mismatch,
        jil_conditions_not_parsed_count=jil_graph_metrics.conditions_not_parsed,
        synthetic_nodes_total=sb_graph_metrics.synthetic_nodes + jil_graph_metrics.synthetic_nodes,
        low_confidence_edges_total=sb_graph_metrics.low_confidence_edges + jil_graph_metrics.low_confidence_edges,
    )

    return ComparisonMetrics(
        node_match_rate_percent=node_match_rate,
        edge_match_rate_percent=edge_match_rate,
        jil_to_stonebranch_node_coverage_percent=jil_to_sb_node_coverage,
        stonebranch_to_jil_node_coverage_percent=sb_to_jil_node_coverage,
        jil_to_stonebranch_edge_coverage_percent=jil_to_sb_edge_coverage,
        stonebranch_to_jil_edge_coverage_percent=sb_to_jil_edge_coverage,
        critical_dependency_loss_count=critical_loss,
        critical_dependency_extra_count=critical_extra,
        calendar_mismatch_count=calendar_mismatch,
        agent_machine_mismatch_count=agent_machine_mismatch,
        command_mismatch_count=command_mismatch,
        condition_mismatch_count=condition_mismatch,
        stonebranch_synthetic_nodes=sb_graph_metrics.synthetic_nodes,
        jil_synthetic_nodes=jil_graph_metrics.synthetic_nodes,
        synthetic_nodes_total=sb_graph_metrics.synthetic_nodes + jil_graph_metrics.synthetic_nodes,
        stonebranch_low_confidence_edges=sb_graph_metrics.low_confidence_edges,
        jil_low_confidence_edges=jil_graph_metrics.low_confidence_edges,
        low_confidence_edges_total=sb_graph_metrics.low_confidence_edges + jil_graph_metrics.low_confidence_edges,
        stonebranch_orphan_tasks=sb_graph_metrics.orphan_tasks,
        jil_orphan_tasks=jil_graph_metrics.orphan_tasks,
        stonebranch_tasks_without_trigger=sb_graph_metrics.tasks_without_trigger,
        jil_conditions_not_parsed_count=jil_graph_metrics.conditions_not_parsed,
        migration_readiness_score=readiness_score,
        readiness_grade=readiness_grade(readiness_score),
    )


def compute_readiness_score(
    *,
    node_match_rate: float,
    edge_match_rate: float,
    critical_dependency_loss_count: int,
    critical_dependency_extra_count: int,
    calendar_mismatch_count: int,
    agent_machine_mismatch_count: int,
    command_mismatch_count: int,
    jil_conditions_not_parsed_count: int,
    synthetic_nodes_total: int,
    low_confidence_edges_total: int,
) -> int:
    score = 100.0

    score -= max(0.0, 100.0 - node_match_rate) * 0.20
    score -= max(0.0, 100.0 - edge_match_rate) * 0.35

    score -= critical_dependency_loss_count * 4.0
    score -= critical_dependency_extra_count * 2.0
    score -= calendar_mismatch_count * 2.0
    score -= agent_machine_mismatch_count * 2.5
    score -= command_mismatch_count * 3.0
    score -= jil_conditions_not_parsed_count * 5.0
    score -= synthetic_nodes_total * 0.5
    score -= low_confidence_edges_total * 0.75

    return max(0, min(100, round(score)))


def readiness_grade(score: int) -> str:
    if score >= 95:
        return "excellent"
    if score >= 85:
        return "good"
    if score >= 70:
        return "review_required"
    if score >= 50:
        return "high_risk"
    return "unsafe"


def degree_maps(graph: Graph) -> tuple[dict[str, int], dict[str, int]]:
    inbound = {node_id: 0 for node_id in graph.nodes}
    outbound = {node_id: 0 for node_id in graph.nodes}

    for edge in graph.edges.values():
        if edge.source in outbound:
            outbound[edge.source] += 1
        if edge.target in inbound:
            inbound[edge.target] += 1

    return inbound, outbound


def count_edges_by_relations(items: list[dict[str, Any]], relations: set[str]) -> int:
    return sum(1 for item in items if item.get("relation") in relations)


def relation_diff_count(
    missing_in_sb_edges: list[dict[str, Any]],
    missing_in_jil_edges: list[dict[str, Any]],
    relations: set[str],
) -> int:
    left = count_edges_by_relations(missing_in_sb_edges, relations)
    right = count_edges_by_relations(missing_in_jil_edges, relations)
    return max(left, right)


def percent(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 100.0
    return round((float(numerator) / float(denominator)) * 100.0, 2)


def metrics_to_dict(metrics: GraphMetrics | ComparisonMetrics) -> dict[str, Any]:
    return asdict(metrics)


def metric_rows(metrics: dict[str, Any], prefix: str = "") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, value in metrics.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            rows.extend(metric_rows(value, full_key))
        else:
            rows.append({"metric": full_key, "value": str(value)})
    return rows
