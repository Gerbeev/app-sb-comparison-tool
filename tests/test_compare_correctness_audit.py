from __future__ import annotations

import csv
import json
from pathlib import Path

from stonebranch_graph.compare import compare_graphs, export_comparison
from stonebranch_graph.config import AnalyzerConfig, MappingConfig
from stonebranch_graph.core import Edge, Graph, Node, make_canonical_key, make_edge_id, make_node_id
from stonebranch_graph.domain import (
    KIND_SCRIPT,
    KIND_TASK,
    REL_DEPENDS_ON_SUCCESS,
    REL_RUNS_SCRIPT,
    SOURCE_AUTOSYS_JIL,
    SOURCE_STONEBRANCH,
)
from stonebranch_graph.exporters import write_json
from stonebranch_graph.workflows import compare_graph_json, comparison_files


def _node(source: str, name: str, *, kind: str = KIND_TASK, canonical_key: str | None = None, metadata: dict | None = None) -> Node:
    return Node(
        id=make_node_id(source, "PROD", kind, name),
        canonical_key=canonical_key or make_canonical_key("PROD", kind, name),
        source_system=source,
        env="PROD",
        kind=kind,
        name=name,
        native_kind=kind,
        source_file=f"{name}.src",
        metadata=metadata or {},
    )


def _edge(source_node: Node, target_node: Node, relation: str, source_system: str) -> Edge:
    return Edge(
        id=make_edge_id(source_node.id, target_node.id, relation, relation),
        source=source_node.id,
        target=target_node.id,
        relation=relation,
        source_system=source_system,
        native_relation=relation,
        evidence_file="evidence.src",
        evidence_key="condition",
        evidence_value="hash",
    )


def _compare(sb: Graph, jil: Graph):
    config = AnalyzerConfig.default()
    return compare_graphs(sb, jil, MappingConfig.empty(config), config)


def test_matched_node_payload_uses_normalized_comparison_key_for_enterprise_names() -> None:
    sb = Graph(source_system=SOURCE_STONEBRANCH, env="PROD")
    jil = Graph(source_system=SOURCE_AUTOSYS_JIL, env="PROD")
    sb.add_node(
        _node(
            SOURCE_STONEBRANCH,
            "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS",
            canonical_key="PROD:task:ib_ct_cva_1109_p1_load_customers",
        )
    )
    jil.add_node(
        _node(
            SOURCE_AUTOSYS_JIL,
            "IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS",
            canonical_key="PROD:task:ib_ct_cva_1109_0en0_load_customers",
        )
    )

    comparison = _compare(sb, jil)

    assert comparison.summary["matched_nodes"] == 1
    assert comparison.nodes["matched"][0]["key"] == "PROD:task:load_customers"


def test_edge_diff_csv_uses_normalized_comparison_keys(tmp_path: Path) -> None:
    sb = Graph(source_system=SOURCE_STONEBRANCH, env="PROD")
    jil = Graph(source_system=SOURCE_AUTOSYS_JIL, env="PROD")

    sb_a = _node(SOURCE_STONEBRANCH, "IB_CT_CVA_1109_P1_JOB_A")
    sb_b = _node(SOURCE_STONEBRANCH, "IB_CT_CVA_1109_P1_JOB_B")
    jil_a = _node(SOURCE_AUTOSYS_JIL, "IB_CT_CVA_1109_0en0_JOB_A")
    jil_b = _node(SOURCE_AUTOSYS_JIL, "IB_CT_CVA_1109_0en0_JOB_B")
    for node in (sb_a, sb_b):
        sb.add_node(node)
    for node in (jil_a, jil_b):
        jil.add_node(node)
    jil.add_edge(_edge(jil_a, jil_b, REL_DEPENDS_ON_SUCCESS, SOURCE_AUTOSYS_JIL))

    comparison = _compare(sb, jil)
    export_comparison(comparison, tmp_path, sb, jil)

    rows = list(csv.DictReader((tmp_path / "compare" / "edge-diff.csv").open(encoding="utf-8")))
    assert rows == [
        {
            "side": "missing_in_stonebranch",
            "relation": REL_DEPENDS_ON_SUCCESS,
            "source": "PROD:task:job_a",
            "target": "PROD:task:job_b",
            "evidence_file": "evidence.src",
            "evidence_key": "condition",
            "evidence_value": "hash",
        }
    ]


def test_condition_difference_reduces_readiness_score_and_raises_risk() -> None:
    sb = Graph(source_system=SOURCE_STONEBRANCH, env="PROD")
    jil = Graph(source_system=SOURCE_AUTOSYS_JIL, env="PROD")
    sb.add_node(_node(SOURCE_STONEBRANCH, "JOB_A", metadata={"condition_hash": "sb-condition"}))
    jil.add_node(_node(SOURCE_AUTOSYS_JIL, "JOB_A", metadata={"condition_hash": "jil-condition"}))

    comparison = _compare(sb, jil)

    assert comparison.summary["condition_differences"] == 1
    assert comparison.summary["condition_mismatch_count"] == 1
    assert comparison.summary["migration_readiness_score"] == 97
    assert "Matched objects have different condition hashes." in comparison.risks


def test_export_comparison_writes_complete_diff_artifacts(tmp_path: Path) -> None:
    sb = Graph(source_system=SOURCE_STONEBRANCH, env="PROD")
    jil = Graph(source_system=SOURCE_AUTOSYS_JIL, env="PROD")
    script = _node(SOURCE_AUTOSYS_JIL, "SCRIPT_A", kind=KIND_SCRIPT)
    task = _node(SOURCE_AUTOSYS_JIL, "JOB_A")
    jil.add_node(task)
    jil.add_node(script)
    jil.add_edge(_edge(task, script, REL_RUNS_SCRIPT, SOURCE_AUTOSYS_JIL))

    comparison = _compare(sb, jil)
    export_comparison(comparison, tmp_path, sb, jil)

    compare_dir = tmp_path / "compare"
    assert (compare_dir / "diff-index.json").exists()
    assert (compare_dir / "critical-diff.json").exists()
    assert (compare_dir / "remediation-plan.md").exists()
    critical = json.loads((compare_dir / "critical-diff.json").read_text(encoding="utf-8"))
    assert critical["missing_critical_edges_in_stonebranch"][0]["relation"] == REL_RUNS_SCRIPT


def test_compare_graph_json_contract_returns_complete_comparison_files(tmp_path: Path) -> None:
    sb = Graph(source_system=SOURCE_STONEBRANCH, env="PROD")
    jil = Graph(source_system=SOURCE_AUTOSYS_JIL, env="PROD")
    sb.add_node(_node(SOURCE_STONEBRANCH, "JOB_A"))
    jil.add_node(_node(SOURCE_AUTOSYS_JIL, "JOB_A"))
    sb_path = tmp_path / "sb.json"
    jil_path = tmp_path / "jil.json"
    output = tmp_path / "out"
    write_json(sb_path, sb.to_dict())
    write_json(jil_path, jil.to_dict())

    result = compare_graph_json(
        stonebranch_graph_path=sb_path,
        jil_graph_path=jil_path,
        output_dir=output,
        config=AnalyzerConfig.default(),
    )

    assert result.files == comparison_files(output)
    assert all(path.exists() for path in result.files)
    assert output / "compare" / "critical-diff.json" in result.files
    assert output / "compare" / "remediation-plan.md" in result.files
