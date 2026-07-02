from __future__ import annotations

import csv
import json
from pathlib import Path

from stonebranch_graph.compare import compare_graphs, export_comparison
from stonebranch_graph.config import AnalyzerConfig, MappingConfig
from stonebranch_graph.core import Graph, Node, make_node_id, make_canonical_key
from stonebranch_graph.domain import KIND_TASK, SOURCE_AUTOSYS_JIL, SOURCE_STONEBRANCH


def _node(source: str, name: str, source_file: str) -> Node:
    return Node(
        id=make_node_id(source, "PROD", KIND_TASK, name),
        canonical_key=make_canonical_key("PROD", KIND_TASK, name),
        source_system=source,
        env="PROD",
        kind=KIND_TASK,
        name=name,
        source_file=source_file,
    )


def test_enterprise_name_collisions_are_excluded_from_automatic_matching() -> None:
    config = AnalyzerConfig.default()
    mapping = MappingConfig.empty(config)
    sb = Graph(source_system=SOURCE_STONEBRANCH, env="PROD")
    jl = Graph(source_system=SOURCE_AUTOSYS_JIL, env="PROD")

    # Two different business systems produce the same comparison key after
    # stripping business/env prefixes. This must be diagnosed, not matched.
    sb.add_node(_node(SOURCE_STONEBRANCH, "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS", "tasks/a.json"))
    sb.add_node(_node(SOURCE_STONEBRANCH, "IB_CT_CVA_2200_P1_LOAD_CUSTOMERS", "tasks/b.json"))
    jl.add_node(_node(SOURCE_AUTOSYS_JIL, "IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS", "jobs.jil"))

    comparison = compare_graphs(sb, jl, mapping, config)

    assert comparison.summary["matched_nodes"] == 0
    assert comparison.summary["stonebranch_key_collision_count"] == 1
    assert comparison.summary["missing_in_stonebranch"] == 1
    assert comparison.summary["missing_in_jil"] == 0
    assert any("enterprise-name collisions" in risk for risk in comparison.risks)

    collision = comparison.diagnostics["stonebranch_key_collisions"][0]
    assert collision["key"] == "PROD:task:load_customers"
    assert collision["reason"] == "enterprise_name_collision"
    assert collision["business_codes"] == ["1109", "2200"]
    assert collision["env_tokens"] == ["P1"]
    assert collision["real_names"] == ["LOAD_CUSTOMERS"]
    assert collision["names"] == [
        "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS",
        "IB_CT_CVA_2200_P1_LOAD_CUSTOMERS",
    ]
    assert all("enterprise_naming" in node for node in collision["nodes"])


def test_collision_csv_and_report_explain_enterprise_collision(tmp_path: Path) -> None:
    config = AnalyzerConfig.default()
    mapping = MappingConfig.empty(config)
    sb = Graph(source_system=SOURCE_STONEBRANCH, env="PROD")
    jl = Graph(source_system=SOURCE_AUTOSYS_JIL, env="PROD")

    sb.add_node(_node(SOURCE_STONEBRANCH, "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS", "tasks/a.json"))
    sb.add_node(_node(SOURCE_STONEBRANCH, "IB_CT_CVA_2200_P1_LOAD_CUSTOMERS", "tasks/b.json"))
    jl.add_node(_node(SOURCE_AUTOSYS_JIL, "IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS", "jobs.jil"))

    comparison = compare_graphs(sb, jl, mapping, config)
    export_comparison(comparison, tmp_path, sb, jl)

    rows = list(csv.DictReader((tmp_path / "compare" / "collisions.csv").open(encoding="utf-8")))
    assert rows == [
        {
            "section": "stonebranch_key_collisions",
            "key": "PROD:task:load_customers",
            "reason": "enterprise_name_collision",
            "count": "2",
            "names": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS;IB_CT_CVA_2200_P1_LOAD_CUSTOMERS",
            "business_codes": "1109;2200",
            "env_tokens": "P1",
            "real_names": "LOAD_CUSTOMERS",
            "objects": "stonebranch:PROD:task:IB_CT_CVA_1109_P1_LOAD_CUSTOMERS;stonebranch:PROD:task:IB_CT_CVA_2200_P1_LOAD_CUSTOMERS",
            "source_files": "tasks/a.json;tasks/b.json",
        }
    ]

    report = (tmp_path / "compare" / "report.md").read_text(encoding="utf-8")
    assert "## Normalized key collisions" in report
    assert "enterprise_name_collision" in report
    assert "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS" in report
    assert "IB_CT_CVA_2200_P1_LOAD_CUSTOMERS" in report

    comparison_json = json.loads((tmp_path / "compare" / "comparison.json").read_text(encoding="utf-8"))
    collision = comparison_json["diagnostics"]["stonebranch_key_collisions"][0]
    assert collision["reason"] == "enterprise_name_collision"
    assert collision["business_codes"] == ["1109", "2200"]
