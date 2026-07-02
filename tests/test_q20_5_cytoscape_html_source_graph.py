from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.domain import REL_CONTAINS, REL_DEPENDS_ON_SUCCESS
from stonebranch_graph.exporters import export_graph_bundle
from stonebranch_graph.html_graph import build_cytoscape_graph_data
from stonebranch_graph.pack import create_analysis_pack
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser
from stonebranch_graph.workflows import analysis_pack_files, graph_bundle_files


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def build_graph(tmp_path: Path):
    source = tmp_path / "src"
    write_json(
        source / "workflows" / "daily.json",
        {
            "name": "IB_CT_CVA_1109_P1_DAILY_BOX",
            "tasks": ["IB_CT_CVA_1109_P1_LOAD_CUSTOMERS", "IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS"],
        },
    )
    write_json(
        source / "tasks" / "load.json",
        {"name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS", "agent": "AGENT_01", "calendar": "BUSINESS_DAYS"},
    )
    write_json(source / "tasks" / "validate.json", {"name": "IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS"})
    write_json(
        source / "dependencies" / "validate_after_load.json",
        {
            "successorTask": "IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS",
            "predecessorTask": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS",
        },
    )
    return source, StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(source)


def test_cytoscape_graph_data_models_groups_jobs_and_dependency_edges(tmp_path: Path) -> None:
    _source, graph = build_graph(tmp_path)

    data = build_cytoscape_graph_data(graph)

    assert data["schema_version"] == "1.0"
    assert data["metadata"]["groups"] == 1
    assert data["groups"][0]["id"] == "PROD:box:daily_box"
    jobs_by_id = {job["id"]: job for job in data["jobs"]}
    assert jobs_by_id["PROD:task:load_customers"]["group"] == "PROD:box:daily_box"
    assert jobs_by_id["PROD:task:validate_customers"]["depends_on"] == ["PROD:task:load_customers"]
    assert any(
        edge["relation"] == REL_CONTAINS
        and edge["source"] == "PROD:box:daily_box"
        and edge["target"] == "PROD:task:load_customers"
        for edge in data["edges"]
    )
    assert any(
        edge["relation"] == REL_DEPENDS_ON_SUCCESS
        and edge["category"] == "dependencies"
        and edge["source"] == "PROD:task:validate_customers"
        and edge["target"] == "PROD:task:load_customers"
        for edge in data["edges"]
    )


def test_export_graph_bundle_writes_cytoscape_html_and_data(tmp_path: Path) -> None:
    _source, graph = build_graph(tmp_path)
    out = tmp_path / "out"

    export_graph_bundle(graph, out)

    html = (out / "graph.html").read_text(encoding="utf-8")
    data_js = (out / "graph-data.js").read_text(encoding="utf-8")
    assert "cytoscape.min.js" in html
    assert "window.cytoscape" in html
    assert "window.cytoscape({" in html
    assert "graph-data.js" in html
    assert "cdn.jsdelivr" not in html
    assert "https://" not in html
    assert "window.GRAPH_DATA" in data_js
    assert "PROD:box:daily_box" in data_js
    assert (out / "cytoscape.min.js").exists()
    assert (out / "cytoscape.LICENSE").exists()
    assert out / "graph.html" in graph_bundle_files(out)
    assert out / "graph-data.js" in graph_bundle_files(out)
    assert out / "cytoscape.min.js" in graph_bundle_files(out)


def test_analysis_pack_manifest_and_readme_include_cytoscape_report(tmp_path: Path) -> None:
    source, graph = build_graph(tmp_path)
    out = tmp_path / "pack"

    create_analysis_pack(
        graph=graph,
        output_dir=out,
        pack_type="stonebranch-analysis-pack",
        source_path=source,
        env="PROD",
        include_raw_values=False,
    )

    manifest = json.loads((out / "pack-manifest.json").read_text(encoding="utf-8"))
    assert "graph.html" in manifest["important_files"]
    assert "graph-data.js" in manifest["important_files"]
    assert (out / "graph.html").exists()
    assert (out / "graph-data.js").exists()
    assert out / "graph.html" in analysis_pack_files(out)
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "offline interactive" in readme


def test_graphs_readme_points_to_graph_html_not_planned_replacement(tmp_path: Path) -> None:
    source, graph = build_graph(tmp_path)
    out = tmp_path / "pack"
    create_analysis_pack(
        graph=graph,
        output_dir=out,
        pack_type="stonebranch-analysis-pack",
        source_path=source,
        env="PROD",
        include_raw_values=False,
    )

    readme = (out / "graphs" / "README.md").read_text(encoding="utf-8")
    assert "graph.html" in readme
    assert "planned replacement" not in readme
