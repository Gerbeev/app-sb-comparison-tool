from __future__ import annotations

import csv
import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.domain import KIND_TASK, KIND_WORKFLOW, REL_CONTAINS
from stonebranch_graph.exporters import build_container_view, export_graph_bundle
from stonebranch_graph.pack import create_analysis_pack
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_stonebranch_workflow_container_view_groups_tasks(tmp_path: Path) -> None:
    write_json(
        tmp_path / "workflows" / "IB_CT_CVA_1109_P1_DAILY_BOX.json",
        {
            "name": "IB_CT_CVA_1109_P1_DAILY_BOX",
            "tasks": ["IB_CT_CVA_1109_P1_LOAD_CUSTOMERS", "IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS"],
        },
    )
    write_json(tmp_path / "tasks" / "load.json", {"name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS"})
    write_json(tmp_path / "tasks" / "validate.json", {"name": "IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS"})

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(tmp_path)
    view = build_container_view(graph)

    assert view["summary"] == {"containers": 1, "contained_children": 2, "ungrouped_tasks": 0}
    container = view["containers"][0]
    assert container["kind"] == KIND_WORKFLOW
    assert container["group_key"] == "PROD:box:daily_box"
    assert container["task_count"] == 2
    assert [child["group_key"] for child in container["children"]] == [
        "PROD:task:load_customers",
        "PROD:task:validate_customers",
    ]

    assert any(edge.relation == REL_CONTAINS for edge in graph.edges.values())
    assert all(node.kind != "dependency" for node in graph.nodes.values())


def test_task_level_workflow_name_appears_as_group_membership(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "box.json", {"name": "IB_CT_CVA_1109_P1_DAILY_BOX"})
    write_json(
        tmp_path / "tasks" / "load.json",
        {"name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS", "workflowName": "IB_CT_CVA_1109_P1_DAILY_BOX"},
    )

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(tmp_path)
    container = build_container_view(graph)["containers"][0]

    assert container["group_key"] == "PROD:box:daily_box"
    assert container["children"][0]["group_key"] == "PROD:task:load_customers"


def test_export_graph_bundle_writes_container_files(tmp_path: Path) -> None:
    source = tmp_path / "src"
    write_json(source / "workflows" / "daily.json", {"name": "DAILY_BOX", "tasks": ["LOAD_CUSTOMERS"]})
    write_json(source / "tasks" / "load.json", {"name": "LOAD_CUSTOMERS"})
    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(source)

    out = tmp_path / "out"
    export_graph_bundle(graph, out)

    containers = json.loads((out / "containers.json").read_text(encoding="utf-8"))
    assert containers["containers"][0]["name"] == "DAILY_BOX"

    rows = list(csv.DictReader((out / "containers.csv").open(encoding="utf-8")))
    assert rows[0]["container_key"] == "PROD:box:daily_box"
    assert rows[0]["child_keys"] == "PROD:task:load_customers"


def test_analysis_pack_manifest_mentions_container_group_files(tmp_path: Path) -> None:
    source = tmp_path / "src"
    write_json(source / "workflows" / "daily.json", {"name": "DAILY_BOX", "tasks": ["LOAD_CUSTOMERS"]})
    write_json(source / "tasks" / "load.json", {"name": "LOAD_CUSTOMERS"})
    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(source)

    out = tmp_path / "pack"
    create_analysis_pack(
        graph=graph,
        output_dir=out,
        pack_type="stonebranch",
        source_path=source,
        env="PROD",
        include_raw_values=False,
    )

    manifest = json.loads((out / "pack-manifest.json").read_text(encoding="utf-8"))
    assert "containers.json" in manifest["important_files"]
    assert "containers.csv" in manifest["important_files"]
    assert (out / "containers.json").exists()
    assert (out / "containers.csv").exists()
