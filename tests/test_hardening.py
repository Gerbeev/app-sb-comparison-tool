from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.workflows import compare_direct, profile_jil_schema, profile_stonebranch_schema


def test_compare_outputs_hardening_files(tmp_path: Path) -> None:
    root = Path.cwd()
    out = tmp_path / "out"
    compare_direct(
        stonebranch_path=root / "examples" / "stonebranch" / "PROD",
        jil_path=root / "examples" / "jil" / "PROD",
        env="PROD",
        output_dir=out,
        config=AnalyzerConfig.default(),
    )
    assert (out / "compare" / "collisions.csv").exists()
    assert (out / "compare" / "mapping-diagnostics.csv").exists()
    comparison = json.loads((out / "compare" / "comparison.json").read_text(encoding="utf-8"))
    assert "diagnostics" in comparison


def test_safe_profiles(tmp_path: Path) -> None:
    root = Path.cwd()
    sb_out = tmp_path / "profile-sb"
    jil_out = tmp_path / "profile-jil"
    profile_stonebranch_schema(root / "examples" / "stonebranch" / "PROD", sb_out, AnalyzerConfig.default())
    profile_jil_schema(root / "examples" / "jil" / "PROD", jil_out)
    assert (sb_out / "schema-profile.md").exists()
    assert (jil_out / "schema-profile.md").exists()
