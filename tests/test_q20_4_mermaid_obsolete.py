from __future__ import annotations

import inspect
import json
from pathlib import Path

from stonebranch_graph import compare, exporters, pack
from stonebranch_graph.compare import compare_graphs, export_comparison
from stonebranch_graph.config import AnalyzerConfig, MappingConfig
from stonebranch_graph.core import Graph, Node
from stonebranch_graph.exporters import export_graph_bundle
from stonebranch_graph.pack import create_analysis_pack
from stonebranch_graph.workflows import analysis_pack_files, comparison_files, graph_bundle_files


def _graph(source_system: str) -> Graph:
    graph = Graph(source_system=source_system, env="PROD")
    graph.add_node(
        Node(
            id=f"{source_system}:PROD:task:JOB_A",
            canonical_key="PROD:task:job_a",
            source_system=source_system,
            env="PROD",
            kind="task",
            name="JOB_A",
        )
    )
    return graph


def test_graph_bundle_does_not_emit_mermaid(tmp_path: Path) -> None:
    export_graph_bundle(_graph("stonebranch"), tmp_path)

    assert not (tmp_path / "dependency-graph.mmd").exists()
    assert (tmp_path / "dependency-graph.dot").exists()
    assert (tmp_path / "canonical-graph.json").exists()
    assert (tmp_path / "containers.json").exists()
    assert tmp_path / "dependency-graph.mmd" not in graph_bundle_files(tmp_path)


def test_analysis_pack_writes_mermaid_decommission_readme_not_mmd_views(tmp_path: Path) -> None:
    create_analysis_pack(
        graph=_graph("stonebranch"),
        output_dir=tmp_path,
        pack_type="stonebranch-analysis-pack",
        source_path=tmp_path / "source",
        env="PROD",
        include_raw_values=False,
    )

    assert (tmp_path / "graphs" / "README.md").exists()
    graphs_readme = (tmp_path / "graphs" / "README.md").read_text(encoding="utf-8")
    assert "Mermaid `.mmd` graph exports have been fully decommissioned" in graphs_readme
    assert not list((tmp_path / "graphs").glob("*.mmd"))
    manifest = json.loads((tmp_path / "pack-manifest.json").read_text(encoding="utf-8"))
    assert "graphs/README.md" in manifest["important_files"]
    assert all(not item.endswith(".mmd") for item in manifest["important_files"])
    assert tmp_path / "graphs" / "README.md" in analysis_pack_files(tmp_path)


def test_comparison_export_does_not_emit_overlay_mermaid(tmp_path: Path) -> None:
    sb = _graph("stonebranch")
    jil = _graph("autosys_jil")
    comparison = compare_graphs(sb, jil, MappingConfig.empty(AnalyzerConfig.default()), AnalyzerConfig.default())

    export_comparison(comparison, tmp_path, sb, jil)

    assert not (tmp_path / "compare" / "overlay-graph.mmd").exists()
    assert tmp_path / "compare" / "overlay-graph.mmd" not in comparison_files(tmp_path)


def test_mermaid_generation_hooks_are_removed() -> None:
    assert "include_legacy_mermaid" not in inspect.signature(export_graph_bundle).parameters
    assert "include_legacy_mermaid" not in inspect.signature(export_comparison).parameters
    assert not hasattr(exporters, "export_mermaid")
    assert not hasattr(pack, "write_mermaid")
    assert not hasattr(compare, "write_overlay_mermaid")
