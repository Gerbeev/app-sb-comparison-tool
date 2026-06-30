from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_cmd(cwd: Path, args: list[str]) -> None:
    result = subprocess.run([sys.executable, "-m", "stonebranch_graph.cli", *args], cwd=cwd, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_compare_outputs_hardening_files(tmp_path: Path) -> None:
    root = Path.cwd()
    out = tmp_path / "out"
    run_cmd(root, [
        "compare",
        "--stonebranch", "examples/stonebranch/PROD",
        "--jil", "examples/jil/PROD",
        "--env", "PROD",
        "-o", str(out),
    ])
    assert (out / "compare" / "collisions.csv").exists()
    assert (out / "compare" / "mapping-diagnostics.csv").exists()
    comparison = json.loads((out / "compare" / "comparison.json").read_text(encoding="utf-8"))
    assert "diagnostics" in comparison


def test_safe_profiles(tmp_path: Path) -> None:
    root = Path.cwd()
    sb_out = tmp_path / "profile-sb"
    jil_out = tmp_path / "profile-jil"
    run_cmd(root, ["profile-stonebranch", "examples/stonebranch/PROD", "-o", str(sb_out)])
    run_cmd(root, ["profile-jil", "examples/jil/PROD", "-o", str(jil_out)])
    assert (sb_out / "schema-profile.md").exists()
    assert (jil_out / "schema-profile.md").exists()
