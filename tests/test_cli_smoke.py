"""CLI smoke tests (IMPLEMENTATION_PLAN.md Definition of Done #3).

Invokes the CLI entry point end-to-end on the golden fixtures for both the
current default (`compare-skeleton`, and plain `compare` which now delegates
to the skeleton pipeline) and the legacy graph-based `compare --legacy` path,
asserting a clean exit code and that every documented output artifact is
actually written. This is the cheapest way to catch packaging/encoding
regressions (e.g. a signature change that breaks a call site only exercised
end-to-end) that unit tests around individual functions would miss.
"""

from __future__ import annotations

from pathlib import Path

from stonebranch_graph.cli import main
from stonebranch_graph.workflows import comparison_files, skeleton_comparison_files

from conftest import GOLDEN_DIR


def _run_cli(argv: list[str]) -> int:
    return main(argv)


def test_compare_skeleton_smoke(tmp_path: Path):
    out_dir = tmp_path / "out-skeleton"
    exit_code = _run_cli(
        [
            "compare-skeleton",
            "--stonebranch",
            str(GOLDEN_DIR / "stonebranch" / "PROD"),
            "--jil",
            str(GOLDEN_DIR / "jil" / "PROD"),
            "-o",
            str(out_dir),
            "--alias",
            str(GOLDEN_DIR / "alias.json"),
        ]
    )
    assert exit_code == 0

    missing = [str(path) for path in skeleton_comparison_files(out_dir) if not path.exists()]
    assert not missing, f"missing expected artifacts: {missing}"


def test_compare_default_delegates_to_skeleton_pipeline(tmp_path: Path):
    out_dir = tmp_path / "out-default"
    exit_code = _run_cli(
        [
            "compare",
            "--stonebranch",
            str(GOLDEN_DIR / "stonebranch" / "PROD"),
            "--jil",
            str(GOLDEN_DIR / "jil" / "PROD"),
            "-o",
            str(out_dir),
            "--alias",
            str(GOLDEN_DIR / "alias.json"),
        ]
    )
    assert exit_code == 0

    missing = [str(path) for path in skeleton_comparison_files(out_dir) if not path.exists()]
    assert not missing, f"missing expected artifacts: {missing}"


def test_compare_legacy_graph_pipeline_smoke(tmp_path: Path):
    out_dir = tmp_path / "out-legacy"
    exit_code = _run_cli(
        [
            "compare",
            "--legacy",
            "--stonebranch",
            str(GOLDEN_DIR / "stonebranch" / "PROD"),
            "--jil",
            str(GOLDEN_DIR / "jil" / "PROD"),
            "-o",
            str(out_dir),
        ]
    )
    assert exit_code == 0

    missing = [str(path) for path in comparison_files(out_dir) if not path.exists()]
    assert not missing, f"missing expected artifacts: {missing}"
