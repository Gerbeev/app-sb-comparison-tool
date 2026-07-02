from __future__ import annotations

from pathlib import Path
from typing import Any

from stonebranch_graph.tui import TerminalUi


def test_profile_jil_last_files_use_schema_profile_outputs(tmp_path: Path) -> None:
    jil_dir = tmp_path / "jil"
    jil_dir.mkdir()
    (jil_dir / "jobs.jil").write_text("insert_job: JOB_A\ncommand: echo ok\n", encoding="utf-8")

    output_root = tmp_path / "out"
    ui = TerminalUi()
    ui.settings.jil_path = str(jil_dir)
    ui.settings.output_path = str(output_root)

    ui.success = lambda *args, **kwargs: None  # type: ignore[method-assign]
    ui.pause = lambda *args, **kwargs: None  # type: ignore[method-assign]
    ui.show_last_files = lambda *args, **kwargs: None  # type: ignore[method-assign]

    ui.profile_jil()

    profile_dir = output_root / "profile-jil"
    expected_files = [profile_dir / "schema-profile.md", profile_dir / "schema-profile.csv"]
    assert ui.last_files == expected_files
    for path in expected_files:
        assert path.exists(), str(path)
