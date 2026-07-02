from __future__ import annotations

from pathlib import Path
import tomllib

import stonebranch_graph

ROOT = Path(__file__).resolve().parents[1]


def load_pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_release_version_is_consistent_across_package_metadata() -> None:
    pyproject = load_pyproject()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert pyproject["project"]["version"] == "0.5.5"
    assert stonebranch_graph.__version__ == "0.5.5"
    assert readme.startswith("# Stonebranch Dependency Tool v0.5.5")


def test_pep517_build_system_and_package_discovery_are_configured() -> None:
    pyproject = load_pyproject()

    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert "setuptools>=68" in pyproject["build-system"]["requires"]
    assert pyproject["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "stonebranch_graph*"
    ]


def test_project_metadata_points_to_readme_and_license() -> None:
    pyproject = load_pyproject()
    project = pyproject["project"]

    assert project["readme"] == "README.md"
    assert project["license"] == {"text": "MIT"}
    assert (ROOT / "README.md").exists()
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_changelog_documents_current_release_and_deferred_privacy_mode() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert changelog.startswith("# Changelog\n")
    assert "## v0.5.5 - 2026-07-01" in changelog
    assert "Stonebranch trigger `taskName`" in changelog
    assert "workflow/TUI refactoring" in changelog or "workflow" in changelog
    assert "privacy-mode/safe-sharing" in changelog


def test_release_archive_excludes_local_runtime_state() -> None:
    root = Path(__file__).resolve().parents[1]

    assert not (root / ".stonebranch-tool-settings.json").exists()
    assert not (root / "out").exists()


def test_windows_terminal_launcher_uses_python_command() -> None:
    launcher = (ROOT / "run_terminal_ui.cmd").read_text(encoding="utf-8").lower()

    assert "python -m stonebranch_graph.cli tui" in launcher
    assert "py -3" not in launcher
