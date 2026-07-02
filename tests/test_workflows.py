from __future__ import annotations

from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.workflows import (
    analysis_pack_files,
    build_jil_graph,
    build_stonebranch_pack,
    compare_direct,
    graph_bundle_files,
    profile_jil_schema,
)


def test_workflow_build_jil_graph_returns_summary_and_files(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "jil-graph"

    result = build_jil_graph(
        root / "examples" / "jil" / "PROD",
        output,
        AnalyzerConfig.default(),
        env="PROD",
    )

    assert result.summary == {"nodes": len(result.graph.nodes), "edges": len(result.graph.edges)}
    assert result.files == graph_bundle_files(output)
    assert (output / "graph.json").exists()
    assert (output / "metrics.json").exists()


def test_workflow_build_stonebranch_pack_returns_standard_pack_files(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "stonebranch-pack"

    result = build_stonebranch_pack(
        root / "examples" / "stonebranch" / "PROD",
        output,
        AnalyzerConfig.default(),
        env="PROD",
    )

    assert result.summary["nodes"] == len(result.graph.nodes)
    assert result.summary["edges"] == len(result.graph.edges)
    assert result.files == analysis_pack_files(output)
    assert all(path.exists() for path in result.files[:5])


def test_workflow_compare_direct_centralizes_parse_export_compare(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "compare"

    result = compare_direct(
        stonebranch_path=root / "examples" / "stonebranch" / "PROD",
        jil_path=root / "examples" / "jil" / "PROD",
        output_dir=output,
        config=AnalyzerConfig.default(),
        env="PROD",
    )

    assert result.comparison is not None
    assert result.stonebranch_graph is not None
    assert result.jil_graph is not None
    assert result.summary["matched_nodes"] >= 6
    assert result.summary["matched_edges"] >= 6
    assert (output / "stonebranch" / "graph.json").exists()
    assert (output / "jil" / "graph.json").exists()
    assert all(path.exists() for path in result.files)


def test_workflow_profile_jil_returns_real_schema_profile_outputs(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "profile-jil"

    result = profile_jil_schema(root / "examples" / "jil" / "PROD", output)

    assert result.summary == {"profile": "jil"}
    assert result.files == [output / "schema-profile.md", output / "schema-profile.csv"]
    assert all(path.exists() for path in result.files)
