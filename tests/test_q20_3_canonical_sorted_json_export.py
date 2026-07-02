from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.domain import REL_CONTAINS, REL_DEPENDS_ON_SUCCESS
from stonebranch_graph.exporters import build_canonical_graph_view, export_graph_bundle
from stonebranch_graph.pack import create_analysis_pack
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def build_workflow_graph(tmp_path: Path):
    source = tmp_path / "src"
    write_json(
        source / "workflows" / "daily.json",
        {
            "name": "IB_CT_CVA_1109_P1_DAILY_BOX",
            "tasks": ["IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS", "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS"],
        },
    )
    write_json(source / "tasks" / "load.json", {"name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS"})
    write_json(source / "tasks" / "validate.json", {"name": "IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS"})
    write_json(
        source / "dependencies" / "validate_after_load.json",
        {
            "name": "VALIDATE_AFTER_LOAD",
            "successorTask": "IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS",
            "predecessorTask": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS",
        },
    )
    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(source)
    return source, graph


def test_canonical_graph_view_uses_group_keys_and_dependency_edges(tmp_path: Path) -> None:
    _source, graph = build_workflow_graph(tmp_path)

    view = build_canonical_graph_view(graph)

    assert view["schema_version"] == "1.0"
    assert view["summary"]["containers"] == 1
    assert view["containers"][0]["group_key"] == "PROD:box:daily_box"
    assert [child["group_key"] for child in view["containers"][0]["children"]] == [
        "PROD:task:load_customers",
        "PROD:task:validate_customers",
    ]

    assert any(
        edge["source"] == "PROD:task:validate_customers"
        and edge["relation"] == REL_DEPENDS_ON_SUCCESS
        and edge["target"] == "PROD:task:load_customers"
        for edge in view["edges"]
    )
    assert any(
        edge["source"] == "PROD:box:daily_box"
        and edge["relation"] == REL_CONTAINS
        and edge["target"] == "PROD:task:load_customers"
        for edge in view["edges"]
    )
    assert all(node["kind"] != "workflow" for node in view["nodes"] if node["key"] == "PROD:box:daily_box")
    assert all("dependency" not in node["kind"] for node in view["nodes"])


def test_export_graph_bundle_writes_sorted_canonical_graph_json(tmp_path: Path) -> None:
    _source, graph = build_workflow_graph(tmp_path)
    out = tmp_path / "out"

    export_graph_bundle(graph, out)

    canonical_path = out / "canonical-graph.json"
    assert canonical_path.exists()
    text = canonical_path.read_text(encoding="utf-8")
    payload = json.loads(text)

    assert text.endswith("\n")
    assert payload["nodes"] == sorted(
        payload["nodes"],
        key=lambda item: (item["key"], item["original_kind"], item["name"], item["source_file"]),
    )
    assert payload["edges"] == sorted(
        payload["edges"],
        key=lambda item: (
            item["source"],
            item["relation"],
            item["target"],
            item["native_relation"],
            item["evidence_file"],
            item["evidence_key"],
        ),
    )


def test_canonical_graph_json_is_deterministic_for_file_order_noise(tmp_path: Path) -> None:
    first_source, first_graph = build_workflow_graph(tmp_path / "first")
    # Same logical graph, different file names and order of workflow task references.
    second_source = tmp_path / "second" / "src"
    write_json(
        second_source / "tasks" / "z_validate.json",
        {"name": "IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS"},
    )
    write_json(second_source / "tasks" / "a_load.json", {"name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS"})
    write_json(
        second_source / "workflows" / "z_daily.json",
        {
            "name": "IB_CT_CVA_1109_P1_DAILY_BOX",
            "tasks": ["IB_CT_CVA_1109_P1_LOAD_CUSTOMERS", "IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS"],
        },
    )
    write_json(
        second_source / "dependencies" / "z_dep.json",
        {
            "successorTask": "IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS",
            "predecessorTask": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS",
        },
    )
    second_graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(second_source)

    first_view = build_canonical_graph_view(first_graph)
    second_view = build_canonical_graph_view(second_graph)

    first_edges = {(edge["source"], edge["relation"], edge["target"]) for edge in first_view["edges"]}
    second_edges = {(edge["source"], edge["relation"], edge["target"]) for edge in second_view["edges"]}
    assert first_edges == second_edges
    assert [node["key"] for node in first_view["nodes"]] == [node["key"] for node in second_view["nodes"]]
    assert [child["group_key"] for child in first_view["containers"][0]["children"]] == [
        child["group_key"] for child in second_view["containers"][0]["children"]
    ]


def test_analysis_pack_manifest_mentions_canonical_graph_json(tmp_path: Path) -> None:
    source, graph = build_workflow_graph(tmp_path)
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
    assert "canonical-graph.json" in manifest["important_files"]
    assert (out / "canonical-graph.json").exists()
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "canonical-graph.json" in readme
    assert "diff tools" in readme
