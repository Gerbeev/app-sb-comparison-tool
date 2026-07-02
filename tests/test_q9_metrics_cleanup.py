from __future__ import annotations

import ast
from pathlib import Path

from stonebranch_graph.core import Edge, Graph, Node, make_canonical_key, make_edge_id, make_node_id
from stonebranch_graph.domain import (
    KIND_TASK,
    REL_DEPENDS_ON_SUCCESS,
    REL_RUNS_ON,
    REL_USES_CALENDAR,
    SOURCE_AUTOSYS_JIL,
    SOURCE_STONEBRANCH,
)
from stonebranch_graph.metrics import (
    compute_comparison_difference_counts,
    compute_comparison_graph_quality,
    compute_comparison_metrics,
    compute_comparison_rate_metrics,
    compute_readiness_penalties,
    compute_readiness_score,
)

ROOT = Path(__file__).resolve().parents[1]


def function_length(module_path: str, function_name: str) -> int:
    source = (ROOT / module_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return (node.end_lineno or node.lineno) - node.lineno + 1
    raise AssertionError(f"Function {function_name} not found in {module_path}")


def function_names(module_path: str) -> set[str]:
    source = (ROOT / module_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def task(source_system: str, name: str, *, metadata: dict | None = None) -> Node:
    return Node(
        id=make_node_id(source_system, "PROD", KIND_TASK, name),
        canonical_key=make_canonical_key("PROD", KIND_TASK, name),
        source_system=source_system,
        env="PROD",
        kind=KIND_TASK,
        native_kind=KIND_TASK,
        name=name,
        metadata=metadata or {},
    )


def edge(source: Node, target: Node, relation: str, *, confidence: float = 1.0) -> Edge:
    return Edge(
        id=make_edge_id(source.id, target.id, relation, relation),
        source=source.id,
        target=target.id,
        relation=relation,
        source_system=source.source_system,
        native_relation=relation,
        confidence=confidence,
    )


def test_comparison_rate_metrics_are_split_and_directional() -> None:
    rates = compute_comparison_rate_metrics(
        {
            "matched_nodes": 4,
            "stonebranch_nodes": 8,
            "jil_nodes": 10,
            "matched_edges": 2,
            "stonebranch_edges": 5,
            "jil_edges": 8,
        }
    )

    assert rates.node_match_rate_percent == 44.44
    assert rates.edge_match_rate_percent == 30.77
    assert rates.jil_to_stonebranch_node_coverage_percent == 40.0
    assert rates.stonebranch_to_jil_node_coverage_percent == 50.0
    assert rates.jil_to_stonebranch_edge_coverage_percent == 25.0
    assert rates.stonebranch_to_jil_edge_coverage_percent == 40.0


def test_difference_counts_are_split_by_critical_calendar_runtime_and_attribute_groups() -> None:
    differences = compute_comparison_difference_counts(
        {
            "missing_in_stonebranch": [
                {"relation": REL_DEPENDS_ON_SUCCESS},
                {"relation": REL_USES_CALENDAR},
                {"relation": REL_USES_CALENDAR},
            ],
            "missing_in_jil": [
                {"relation": REL_RUNS_ON},
                {"relation": REL_USES_CALENDAR},
            ],
        },
        {
            "command_differences": [{"key": "PROD:task:a"}],
            "condition_differences": [{"key": "PROD:task:b"}, {"key": "PROD:task:c"}],
        },
    )

    assert differences.critical_dependency_loss_count == 1
    assert differences.critical_dependency_extra_count == 0
    assert differences.calendar_mismatch_count == 2
    assert differences.agent_machine_mismatch_count == 1
    assert differences.command_mismatch_count == 1
    assert differences.condition_mismatch_count == 2


def test_graph_quality_metrics_are_split_from_comparison_summary_math() -> None:
    sb = Graph(source_system=SOURCE_STONEBRANCH, env="PROD")
    jil = Graph(source_system=SOURCE_AUTOSYS_JIL, env="PROD")
    sb_a = task(SOURCE_STONEBRANCH, "SB_A", metadata={"synthetic": True})
    sb_b = task(SOURCE_STONEBRANCH, "SB_B")
    jil_a = task(SOURCE_AUTOSYS_JIL, "JIL_A", metadata={"has_condition": True})
    jil_b = task(SOURCE_AUTOSYS_JIL, "JIL_B")
    for node in (sb_a, sb_b):
        sb.add_node(node)
    for node in (jil_a, jil_b):
        jil.add_node(node)
    sb.add_edge(edge(sb_a, sb_b, REL_DEPENDS_ON_SUCCESS, confidence=0.5))

    quality = compute_comparison_graph_quality(sb, jil)

    assert quality.stonebranch_synthetic_nodes == 1
    assert quality.jil_synthetic_nodes == 0
    assert quality.synthetic_nodes_total == 1
    assert quality.stonebranch_low_confidence_edges == 1
    assert quality.low_confidence_edges_total == 1
    assert quality.jil_conditions_not_parsed_count == 1


def test_readiness_penalty_breakdown_matches_public_score_formula() -> None:
    penalties = compute_readiness_penalties(
        node_match_rate=90.0,
        edge_match_rate=80.0,
        critical_dependency_loss_count=1,
        critical_dependency_extra_count=2,
        calendar_mismatch_count=1,
        agent_machine_mismatch_count=1,
        command_mismatch_count=1,
        condition_mismatch_count=1,
        jil_conditions_not_parsed_count=1,
        synthetic_nodes_total=2,
        low_confidence_edges_total=4,
    )
    score = compute_readiness_score(
        node_match_rate=90.0,
        edge_match_rate=80.0,
        critical_dependency_loss_count=1,
        critical_dependency_extra_count=2,
        calendar_mismatch_count=1,
        agent_machine_mismatch_count=1,
        command_mismatch_count=1,
        condition_mismatch_count=1,
        jil_conditions_not_parsed_count=1,
        synthetic_nodes_total=2,
        low_confidence_edges_total=4,
    )

    assert penalties.node_match_gap_penalty == 2.0
    assert penalties.edge_match_gap_penalty == 7.0
    assert penalties.critical_dependency_loss_penalty == 4.0
    assert penalties.critical_dependency_extra_penalty == 4.0
    assert penalties.calendar_mismatch_penalty == 2.0
    assert penalties.agent_machine_mismatch_penalty == 2.5
    assert penalties.command_mismatch_penalty == 3.0
    assert penalties.condition_mismatch_penalty == 3.0
    assert penalties.jil_conditions_not_parsed_penalty == 5.0
    assert penalties.synthetic_nodes_penalty == 1.0
    assert penalties.low_confidence_edges_penalty == 3.0
    assert penalties.total_penalty == 36.5
    assert score == 64


def test_compute_comparison_metrics_is_composed_from_small_helpers() -> None:
    sb = Graph(source_system=SOURCE_STONEBRANCH, env="PROD")
    jil = Graph(source_system=SOURCE_AUTOSYS_JIL, env="PROD")
    sb.add_node(task(SOURCE_STONEBRANCH, "A"))
    jil.add_node(task(SOURCE_AUTOSYS_JIL, "A"))

    metrics = compute_comparison_metrics(
        {"matched_nodes": 1, "stonebranch_nodes": 1, "jil_nodes": 1, "matched_edges": 0, "stonebranch_edges": 0, "jil_edges": 0},
        {},
        {"missing_in_stonebranch": [], "missing_in_jil": []},
        {"command_differences": [], "condition_differences": []},
        sb,
        jil,
    )

    assert metrics.node_match_rate_percent == 100.0
    assert metrics.edge_match_rate_percent == 100.0
    assert metrics.migration_readiness_score == 100
    assert metrics.readiness_grade == "excellent"


def test_metrics_module_keeps_comparison_and_readiness_functions_small() -> None:
    assert function_length("stonebranch_graph/metrics.py", "compute_comparison_metrics") <= 35
    assert function_length("stonebranch_graph/metrics.py", "compute_readiness_score") <= 30
    assert {
        "compute_comparison_rate_metrics",
        "compute_comparison_difference_counts",
        "compute_comparison_graph_quality",
        "build_comparison_metrics",
        "compute_readiness_penalties",
        "match_gap_penalty",
        "clamp_score",
    } <= function_names("stonebranch_graph/metrics.py")
