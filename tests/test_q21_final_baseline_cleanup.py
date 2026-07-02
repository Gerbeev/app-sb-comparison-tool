from __future__ import annotations

from pathlib import Path

import pytest

from stonebranch_graph import __version__
from stonebranch_graph.cli import build_parser, main
from stonebranch_graph.triage import TRIAGE_OUTPUT_FILES
from stonebranch_graph.workflows import comparison_files

ROOT = Path(__file__).resolve().parents[1]


def test_q21_cli_version_option_reports_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert f"stonebranch-graph {__version__}" in capsys.readouterr().out


def test_q21_cli_help_lists_current_primary_commands() -> None:
    help_text = build_parser().format_help()

    for command in [
        "build-stonebranch-pack",
        "build-jil-pack",
        "compare-packs",
        "compare-json",
        "triage",
        "tui",
    ]:
        assert command in help_text
    assert "--version" in help_text


def test_q21_baseline_document_contains_current_output_contracts() -> None:
    baseline = (ROOT / "docs" / "QA_BASELINE.md").read_text(encoding="utf-8")
    comparison_relpaths = [str(path.relative_to(Path("baseline-output"))) for path in comparison_files(Path("baseline-output"))]

    for relpath in comparison_relpaths:
        assert relpath in baseline
    for triage_file in TRIAGE_OUTPUT_FILES:
        assert f"compare/{triage_file}" in baseline
    assert "compare-pack-manifest.json" in baseline
    assert "python -m stonebranch_graph.cli triage" in baseline
    assert "py -3" not in baseline


def test_q21_readme_comparison_contract_is_synced() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for relpath in [str(path.relative_to(Path("baseline-output"))) for path in comparison_files(Path("baseline-output"))]:
        assert relpath in readme
    for triage_file in TRIAGE_OUTPUT_FILES:
        assert f"triage-{triage_file.split('-', 1)[1]}" in readme
    assert "remediation-summary.json" in readme
    assert "overlay-graph.mmd" in readme
    assert "docs/QA_BASELINE.md" in readme


def test_q21_changelog_records_final_baseline_cleanup() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "### QA21" in changelog
    assert "docs/QA_BASELINE.md" in changelog
    assert "--version" in changelog


def test_q21_repository_root_has_no_runtime_state() -> None:
    assert not (ROOT / "out").exists()
    assert not (ROOT / ".stonebranch-tool-settings.json").exists()
