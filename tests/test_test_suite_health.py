from __future__ import annotations

from pathlib import Path


def test_only_cli_smoke_tests_spawn_processes() -> None:
    tests_root = Path(__file__).resolve().parent
    offenders: list[str] = []
    for path in sorted(tests_root.glob("test_*.py")) + sorted(tests_root.glob("smoke_test.py")):
        text = path.read_text(encoding="utf-8")
        if ("sub" + "process") in text and path.name != "smoke_test.py":
            offenders.append(path.name)

    assert offenders == []


def test_q7_documents_direct_workflow_test_policy() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "Prefer direct workflow calls in tests" in readme
    assert "Q7" in changelog
    assert ("sub" + "process") in changelog
