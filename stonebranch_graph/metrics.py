from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .core import Graph
from .domain import (
    CALENDAR_RELATIONS,
    CRITICAL_DEPENDENCY_RELATIONS,
    KIND_TASK,
    REL_DEPENDS_ON,
    REL_STARTS,
    RUNTIME_TARGET_RELATIONS,
)
from .graph_utils import GraphTraversalCache


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


@dataclass(frozen=True)
class ComparisonRateMetrics:
    node_match_rate_percent: float
    edge_match_rate_percent: float
    jil_to_stonebranch_node_coverage_percent: float
    stonebranch_to_jil_node_coverage_percent: float
    jil_to_stonebranch_edge_coverage_percent: float
    stonebranch_to_jil_edge_coverage_percent: float


@dataclass(frozen=True)
class ComparisonDifferenceCounts:
    critical_dependency_loss_count: int
    critical_dependency_extra_count: int
    calendar_mismatch_count: int
    agent_machine_mismatch_count: int
    command_mismatch_count: int
    condition_mismatch_count: int


@dataclass(frozen=True)
class ComparisonGraphQuality:
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


@dataclass(frozen=True)
class ReadinessPenaltyBreakdown:
    node_match_gap_penalty: float
    edge_match_gap_penalty: float
    critical_dependency_loss_penalty: float
    critical_dependency_extra_penalty: float
    calendar_mismatch_penalty: float
    agent_machine_mismatch_penalty: float
    command_mismatch_penalty: float
    condition_mismatch_penalty: float
    jil_conditions_not_parsed_penalty: float
    synthetic_nodes_penalty: float
    low_confidence_edges_penalty: float

    @property
    def total_penalty(self) -> float:
        return sum(
            (
                self.node_match_gap_penalty,
                self.edge_match_gap_penalty,
                self.critical_dependency_loss_penalty,
                self.critical_dependency_extra_penalty,
                self.calendar_mismatch_penalty,
                self.agent_machine_mismatch_penalty,
                self.command_mismatch_penalty,
                self.condition_mismatch_penalty,
                self.jil_conditions_not_parsed_penalty,
                self.synthetic_nodes_penalty,
                self.low_confidence_edges_penalty,
            )
        )


def compute_graph_metrics(graph: Graph, *, traversal: GraphTraversalCache | None = None) -> GraphMetrics:
    traversal = traversal or GraphTraversalCache.build(graph)
    inbound = traversal.inbound
    outbound = traversal.outbound
    object_types = traversal.kind_counts
    relation_types = traversal.relation_counts

    task_ids = {node.id for node in traversal.sorted_nodes if node.kind == KIND_TASK}
    synthetic_nodes = sum(1 for node in traversal.sorted_nodes if bool(node.metadata.get("synthetic")))
    low_confidence_edges = sum(1 for edge in traversal.sorted_edges if edge.confidence < 0.8)

    orphan_nodes = sum(1 for node_id in graph.nodes if inbound[node_id] == 0 and outbound[node_id] == 0)
    orphan_tasks = sum(1 for node_id in task_ids if inbound[node_id] == 0 and outbound[node_id] == 0)
    tasks_without_inbound_dependency = sum(1 for node_id in task_ids if inbound[node_id] == 0)
    tasks_without_outbound_dependency = sum(1 for node_id in task_ids if outbound[node_id] == 0)

    task_ids_with_trigger = {
        edge.target
        for edge in traversal.sorted_edges
        if edge.relation == REL_STARTS and edge.target in task_ids
    }
    tasks_without_trigger = max(0, len(task_ids - task_ids_with_trigger))

    condition_nodes = sum(1 for node in traversal.sorted_nodes if bool(node.metadata.get("has_condition")))
    condition_edge_sources = {
        edge.source
        for edge in traversal.sorted_edges
        if edge.native_relation.startswith("condition_") or edge.relation.startswith(f"{REL_DEPENDS_ON}_")
    }
    conditions_not_parsed = sum(
        1
        for node in traversal.sorted_nodes
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
    del comparison_nodes  # Node counts are already represented in the normalized summary payload.

    rates = compute_comparison_rate_metrics(summary)
    differences = compute_comparison_difference_counts(comparison_edges, comparison_attributes)
    quality = compute_comparison_graph_quality(stonebranch, jil)
    readiness_score = compute_readiness_score(
        node_match_rate=rates.node_match_rate_percent,
        edge_match_rate=rates.edge_match_rate_percent,
        critical_dependency_loss_count=differences.critical_dependency_loss_count,
        critical_dependency_extra_count=differences.critical_dependency_extra_count,
        calendar_mismatch_count=differences.calendar_mismatch_count,
        agent_machine_mismatch_count=differences.agent_machine_mismatch_count,
        command_mismatch_count=differences.command_mismatch_count,
        condition_mismatch_count=differences.condition_mismatch_count,
        jil_conditions_not_parsed_count=quality.jil_conditions_not_parsed_count,
        synthetic_nodes_total=quality.synthetic_nodes_total,
        low_confidence_edges_total=quality.low_confidence_edges_total,
    )

    return build_comparison_metrics(
        rates=rates,
        differences=differences,
        quality=quality,
        readiness_score=readiness_score,
    )


def compute_comparison_rate_metrics(summary: dict[str, int]) -> ComparisonRateMetrics:
    matched_nodes = summary.get("matched_nodes", 0)
    matched_edges = summary.get("matched_edges", 0)
    stonebranch_nodes = summary.get("stonebranch_nodes", 0)
    jil_nodes = summary.get("jil_nodes", 0)
    stonebranch_edges = summary.get("stonebranch_edges", 0)
    jil_edges = summary.get("jil_edges", 0)

    return ComparisonRateMetrics(
        node_match_rate_percent=percent(matched_nodes * 2, stonebranch_nodes + jil_nodes),
        edge_match_rate_percent=percent(matched_edges * 2, stonebranch_edges + jil_edges),
        jil_to_stonebranch_node_coverage_percent=percent(matched_nodes, jil_nodes),
        stonebranch_to_jil_node_coverage_percent=percent(matched_nodes, stonebranch_nodes),
        jil_to_stonebranch_edge_coverage_percent=percent(matched_edges, jil_edges),
        stonebranch_to_jil_edge_coverage_percent=percent(matched_edges, stonebranch_edges),
    )


def compute_comparison_difference_counts(
    comparison_edges: dict[str, list[dict[str, Any]]],
    comparison_attributes: dict[str, list[dict[str, Any]]],
) -> ComparisonDifferenceCounts:
    missing_in_sb_edges = comparison_edges.get("missing_in_stonebranch", [])
    missing_in_jil_edges = comparison_edges.get("missing_in_jil", [])

    return ComparisonDifferenceCounts(
        critical_dependency_loss_count=count_edges_by_relations(missing_in_sb_edges, CRITICAL_DEPENDENCY_RELATIONS),
        critical_dependency_extra_count=count_edges_by_relations(missing_in_jil_edges, CRITICAL_DEPENDENCY_RELATIONS),
        calendar_mismatch_count=relation_diff_count(missing_in_sb_edges, missing_in_jil_edges, CALENDAR_RELATIONS),
        agent_machine_mismatch_count=relation_diff_count(
            missing_in_sb_edges,
            missing_in_jil_edges,
            RUNTIME_TARGET_RELATIONS,
        ),
        command_mismatch_count=sum(
            1
            for item in comparison_attributes.get("command_differences", [])
            if item.get("status", "command_semantic_mismatch") == "command_semantic_mismatch"
        ),
        condition_mismatch_count=len(comparison_attributes.get("condition_differences", [])),
    )


def compute_comparison_graph_quality(stonebranch: Graph, jil: Graph) -> ComparisonGraphQuality:
    sb_graph_metrics = compute_graph_metrics(stonebranch)
    jil_graph_metrics = compute_graph_metrics(jil)

    return ComparisonGraphQuality(
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
    )


def build_comparison_metrics(
    *,
    rates: ComparisonRateMetrics,
    differences: ComparisonDifferenceCounts,
    quality: ComparisonGraphQuality,
    readiness_score: int,
) -> ComparisonMetrics:
    return ComparisonMetrics(
        node_match_rate_percent=rates.node_match_rate_percent,
        edge_match_rate_percent=rates.edge_match_rate_percent,
        jil_to_stonebranch_node_coverage_percent=rates.jil_to_stonebranch_node_coverage_percent,
        stonebranch_to_jil_node_coverage_percent=rates.stonebranch_to_jil_node_coverage_percent,
        jil_to_stonebranch_edge_coverage_percent=rates.jil_to_stonebranch_edge_coverage_percent,
        stonebranch_to_jil_edge_coverage_percent=rates.stonebranch_to_jil_edge_coverage_percent,
        critical_dependency_loss_count=differences.critical_dependency_loss_count,
        critical_dependency_extra_count=differences.critical_dependency_extra_count,
        calendar_mismatch_count=differences.calendar_mismatch_count,
        agent_machine_mismatch_count=differences.agent_machine_mismatch_count,
        command_mismatch_count=differences.command_mismatch_count,
        condition_mismatch_count=differences.condition_mismatch_count,
        stonebranch_synthetic_nodes=quality.stonebranch_synthetic_nodes,
        jil_synthetic_nodes=quality.jil_synthetic_nodes,
        synthetic_nodes_total=quality.synthetic_nodes_total,
        stonebranch_low_confidence_edges=quality.stonebranch_low_confidence_edges,
        jil_low_confidence_edges=quality.jil_low_confidence_edges,
        low_confidence_edges_total=quality.low_confidence_edges_total,
        stonebranch_orphan_tasks=quality.stonebranch_orphan_tasks,
        jil_orphan_tasks=quality.jil_orphan_tasks,
        stonebranch_tasks_without_trigger=quality.stonebranch_tasks_without_trigger,
        jil_conditions_not_parsed_count=quality.jil_conditions_not_parsed_count,
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
    condition_mismatch_count: int,
    jil_conditions_not_parsed_count: int,
    synthetic_nodes_total: int,
    low_confidence_edges_total: int,
) -> int:
    penalties = compute_readiness_penalties(
        node_match_rate=node_match_rate,
        edge_match_rate=edge_match_rate,
        critical_dependency_loss_count=critical_dependency_loss_count,
        critical_dependency_extra_count=critical_dependency_extra_count,
        calendar_mismatch_count=calendar_mismatch_count,
        agent_machine_mismatch_count=agent_machine_mismatch_count,
        command_mismatch_count=command_mismatch_count,
        condition_mismatch_count=condition_mismatch_count,
        jil_conditions_not_parsed_count=jil_conditions_not_parsed_count,
        synthetic_nodes_total=synthetic_nodes_total,
        low_confidence_edges_total=low_confidence_edges_total,
    )
    return clamp_score(round(100.0 - penalties.total_penalty))


def compute_readiness_penalties(
    *,
    node_match_rate: float,
    edge_match_rate: float,
    critical_dependency_loss_count: int,
    critical_dependency_extra_count: int,
    calendar_mismatch_count: int,
    agent_machine_mismatch_count: int,
    command_mismatch_count: int,
    condition_mismatch_count: int,
    jil_conditions_not_parsed_count: int,
    synthetic_nodes_total: int,
    low_confidence_edges_total: int,
) -> ReadinessPenaltyBreakdown:
    return ReadinessPenaltyBreakdown(
        node_match_gap_penalty=match_gap_penalty(node_match_rate, weight=0.20),
        edge_match_gap_penalty=match_gap_penalty(edge_match_rate, weight=0.35),
        critical_dependency_loss_penalty=critical_dependency_loss_count * 4.0,
        critical_dependency_extra_penalty=critical_dependency_extra_count * 2.0,
        calendar_mismatch_penalty=calendar_mismatch_count * 2.0,
        agent_machine_mismatch_penalty=agent_machine_mismatch_count * 2.5,
        command_mismatch_penalty=command_mismatch_count * 3.0,
        condition_mismatch_penalty=condition_mismatch_count * 3.0,
        jil_conditions_not_parsed_penalty=jil_conditions_not_parsed_count * 5.0,
        synthetic_nodes_penalty=synthetic_nodes_total * 0.5,
        low_confidence_edges_penalty=low_confidence_edges_total * 0.75,
    )


def match_gap_penalty(match_rate: float, *, weight: float) -> float:
    return max(0.0, 100.0 - match_rate) * weight


def clamp_score(score: int) -> int:
    return max(0, min(100, score))


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
