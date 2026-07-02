from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.exporters import export_graph_bundle
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def build_graph(tmp_path: Path):
    source = tmp_path / "src"
    write_json(
        source / "workflows" / "daily.json",
        {"name": "IB_CT_CVA_1109_P1_DAILY_BOX", "tasks": ["IB_CT_CVA_1109_P1_LOAD_CUSTOMERS"]},
    )
    write_json(
        source / "tasks" / "load.json",
        {"name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS", "agent": "AGENT_01"},
    )
    return StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(source)


def test_graph_html_is_offline_and_has_no_cdn_dependencies(tmp_path: Path) -> None:
    graph = build_graph(tmp_path)
    out = tmp_path / "out"

    export_graph_bundle(graph, out)

    html = (out / "graph.html").read_text(encoding="utf-8")
    assert "graph-data.js" in html
    assert "cdn.jsdelivr" not in html
    assert "https://" not in html
    assert "cytoscape@" not in html
    assert "dagre@" not in html
    assert "cytoscape.min.js" in html
    assert "window.cytoscape({" in html
    assert (out / "cytoscape.min.js").exists()
    assert (out / "cytoscape.LICENSE").exists()


def test_graph_html_keeps_core_interactions_without_external_runtime(tmp_path: Path) -> None:
    graph = build_graph(tmp_path)
    out = tmp_path / "out"

    export_graph_bundle(graph, out)

    html = (out / "graph.html").read_text(encoding="utf-8")
    for expected in [
        "Search task/job/workflow",
        "Collapse groups",
        "Expand groups",
        "Direction: LR",
        "relationFilter",
        "Wheel to zoom",
        "function selectNode",
        "function visibleEdges",
    ]:
        assert expected in html


def test_documentation_describes_offline_graph_report() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    analysis_packs = Path("docs/ANALYSIS_PACKS.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")

    assert "offline interactive HTML graph" in readme
    assert "offline interactive HTML graph" in analysis_packs
    assert "QA20.6" in changelog
    assert "bundled Cytoscape.js" in changelog
