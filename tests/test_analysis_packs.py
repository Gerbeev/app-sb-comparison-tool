from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.workflows import build_jil_pack, build_stonebranch_pack, compare_packs


def test_analysis_pack_workflow(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]

    sb_pack = tmp_path / "stonebranch-pack"
    jil_pack = tmp_path / "jil-pack"
    compare_pack = tmp_path / "compare-pack"
    config = AnalyzerConfig.default()

    build_stonebranch_pack(
        root / "examples" / "stonebranch" / "PROD",
        sb_pack,
        config,
        env="PROD",
        include_raw_values=True,
    )
    build_jil_pack(
        root / "examples" / "jil" / "PROD",
        jil_pack,
        config,
        env="PROD",
        include_raw_values=True,
    )
    compare_packs(
        stonebranch_pack=sb_pack,
        jil_pack=jil_pack,
        output_dir=compare_pack,
        config=config,
    )

    required = [
        sb_pack / "pack-manifest.json",
        sb_pack / "graph.json",
        sb_pack / "indexes" / "node-index.json",
        sb_pack / "indexes" / "adjacency.json",
        sb_pack / "graphs" / "dependencies-only.mmd",
        sb_pack / "reports" / "top-connected.md",
        jil_pack / "pack-manifest.json",
        jil_pack / "graph.json",
        jil_pack / "indexes" / "node-index.json",
        compare_pack / "compare-pack-manifest.json",
        compare_pack / "compare" / "comparison.json",
        compare_pack / "compare" / "metrics.json",
        compare_pack / "compare" / "critical-diff.json",
        compare_pack / "compare" / "diff-index.json",
        compare_pack / "compare" / "remediation-plan.md",
    ]

    for path in required:
        assert path.exists(), str(path)

    sb_manifest = json.loads((sb_pack / "pack-manifest.json").read_text(encoding="utf-8"))
    jil_manifest = json.loads((jil_pack / "pack-manifest.json").read_text(encoding="utf-8"))
    compare_manifest = json.loads((compare_pack / "compare-pack-manifest.json").read_text(encoding="utf-8"))

    assert sb_manifest["pack_type"] == "stonebranch-analysis-pack"
    assert jil_manifest["pack_type"] == "jil-analysis-pack"
    assert compare_manifest["pack_type"] == "comparison-analysis-pack"

    metrics = json.loads((compare_pack / "compare" / "metrics.json").read_text(encoding="utf-8"))
    assert "migration_readiness_score" in metrics
    assert "matched_nodes" in metrics
