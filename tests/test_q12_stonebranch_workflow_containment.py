from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.compare import compare_graphs, normalize_key
from stonebranch_graph.config import AnalyzerConfig, MappingConfig
from stonebranch_graph.core import make_node_id
from stonebranch_graph.domain import (
    KIND_BOX,
    KIND_TASK,
    KIND_TRIGGER,
    KIND_WORKFLOW,
    REL_CONTAINS,
    REL_STARTS,
    SOURCE_STONEBRANCH,
)
from stonebranch_graph.parsers.autosys_jil import AutosysJilParser
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


def parse_stonebranch(tmp_path: Path):
    return StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(tmp_path)


def edge_exists(graph, source: str, target: str, relation: str) -> bool:
    return any(edge.source == source and edge.target == target and edge.relation == relation for edge in graph.edges.values())


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_stonebranch_workflow_folder_and_task_list_create_contains_edges(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "DAILY_BOX.json", {"name": "DAILY_BOX", "tasks": ["LOAD_CUSTOMERS"]})
    write_json(tmp_path / "tasks" / "LOAD_CUSTOMERS.json", {"name": "LOAD_CUSTOMERS"})

    graph = parse_stonebranch(tmp_path)

    workflow_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_WORKFLOW, "DAILY_BOX")
    task_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, "LOAD_CUSTOMERS")

    assert graph.nodes[workflow_id].kind == KIND_WORKFLOW
    assert edge_exists(graph, workflow_id, task_id, REL_CONTAINS)


def test_stonebranch_nested_workflows_create_workflow_contains_workflow_edges(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "PARENT.json", {"name": "PARENT", "workflows": ["CHILD"]})
    write_json(tmp_path / "workflows" / "CHILD.json", {"name": "CHILD"})

    graph = parse_stonebranch(tmp_path)

    parent_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_WORKFLOW, "PARENT")
    child_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_WORKFLOW, "CHILD")

    assert edge_exists(graph, parent_id, child_id, REL_CONTAINS)


def test_stonebranch_trigger_workflow_name_starts_workflow_not_task(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "DAILY_BOX.json", {"name": "DAILY_BOX"})
    write_json(tmp_path / "triggers" / "TRG_DAILY.json", {"name": "TRG_DAILY", "workflowName": "DAILY_BOX"})

    graph = parse_stonebranch(tmp_path)

    trigger_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TRIGGER, "TRG_DAILY")
    workflow_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_WORKFLOW, "DAILY_BOX")
    wrong_task_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, "DAILY_BOX")

    assert edge_exists(graph, trigger_id, workflow_id, REL_STARTS)
    assert wrong_task_id not in graph.nodes


def test_stonebranch_workflow_and_autosys_box_containment_match_in_compare(tmp_path: Path) -> None:
    sb_root = tmp_path / "stonebranch"
    write_json(
        sb_root / "workflows" / "IB_CT_CVA_1109_P1_DAILY_BOX.json",
        {"name": "IB_CT_CVA_1109_P1_DAILY_BOX", "tasks": ["IB_CT_CVA_1109_P1_LOAD_CUSTOMERS"]},
    )
    write_json(
        sb_root / "tasks" / "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS.json",
        {"name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS"},
    )

    jil_root = tmp_path / "jil"
    jil_root.mkdir()
    (jil_root / "IB_CT_CVA_1109_EN_DAILY_BOX.jil").write_text(
        "\n".join(
            [
                "insert_job: IB_CT_CVA_1109_0en0_DAILY_BOX job_type: b",
                "insert_job: IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS job_type: c",
                "box_name: IB_CT_CVA_1109_0en0_DAILY_BOX",
            ]
        ),
        encoding="utf-8",
    )

    config = AnalyzerConfig.default()
    sb_graph = StonebranchJsonParser(config, env="PROD").parse(sb_root)
    jil_graph = AutosysJilParser(config, env="PROD").parse(jil_root)
    comparison = compare_graphs(sb_graph, jil_graph, MappingConfig.empty(config), config)

    assert normalize_key("PROD:workflow:IB_CT_CVA_1109_P1_DAILY_BOX", MappingConfig.empty(config)) == "PROD:box:daily_box"
    assert comparison.summary["matched_nodes"] == 2
    assert comparison.summary["missing_in_stonebranch"] == 0
    assert comparison.summary["missing_in_jil"] == 0
    assert comparison.summary["matched_edges"] == 1
    assert comparison.edges["matched"][0]["key"] == "PROD:box:daily_box->contains->PROD:task:load_customers"


def test_workflow_kind_is_preserved_in_graph_but_compares_as_box(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "DAILY_BOX.json", {"name": "DAILY_BOX"})

    graph = parse_stonebranch(tmp_path)
    node = next(iter(graph.nodes.values()))

    assert node.kind == KIND_WORKFLOW
    assert node.canonical_key == "PROD:workflow:daily_box"
    assert normalize_key(node.canonical_key, MappingConfig.empty(AnalyzerConfig.default())) == "PROD:box:daily_box"
