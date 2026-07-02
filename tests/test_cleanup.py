from __future__ import annotations

from pathlib import Path


def test_obsolete_files_removed() -> None:
    root = Path(__file__).resolve().parents[1]

    obsolete = [
        "run_compare_example.cmd",
        "run_compare_your_repo.cmd",
        "docs/HARDENING_v0.3.3.md",
        "stonebranch_graph/parsers/base.py",
    ]

    for relative in obsolete:
        assert not (root / relative).exists(), relative
