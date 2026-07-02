from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_real_repository_dry_run_checklist_exists_and_covers_required_outputs() -> None:
    doc = ROOT / "docs" / "REAL_REPOSITORY_DRY_RUN.md"
    text = doc.read_text()

    required = [
        "run.log",
        "report.md",
        "metrics.json",
        "critical-diff.json",
        "edge-diff.csv",
        "command-diff.csv",
        "collisions.csv",
        "remediation-plan.md",
        "graph.json",
    ]
    for item in required:
        assert item in text


def test_real_repository_dry_run_checklist_documents_review_order() -> None:
    text = (ROOT / "docs" / "REAL_REPOSITORY_DRY_RUN.md").read_text()

    assert "1) collisions.csv" in text
    assert "2) edge-diff.csv" in text
    assert "3) command-diff.csv" in text
    assert "command_syntax_diff_only" in text
    assert "command_semantic_mismatch" in text
    assert "missing_in_stonebranch = exists in JIL" in text
    assert "missing_in_jil         = exists in Stonebranch" in text


def test_real_repository_dry_run_checklist_uses_python_cli_commands() -> None:
    text = (ROOT / "docs" / "REAL_REPOSITORY_DRY_RUN.md").read_text()

    assert "python -m stonebranch_graph.cli build-stonebranch-pack" in text
    assert "python -m stonebranch_graph.cli build-jil-pack" in text
    assert "python -m stonebranch_graph.cli compare-packs" in text
    assert "py -3" not in text


def test_readme_links_real_repository_dry_run_checklist() -> None:
    text = (ROOT / "README.md").read_text()

    assert "## Real repository dry run" in text
    assert "docs/REAL_REPOSITORY_DRY_RUN.md" in text


def test_changelog_mentions_qa18_dry_run_checklist() -> None:
    text = (ROOT / "CHANGELOG.md").read_text()

    assert "### QA18" in text
    assert "REAL_REPOSITORY_DRY_RUN.md" in text
