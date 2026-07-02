from __future__ import annotations

from pathlib import Path

import pytest

from stonebranch_graph import tui_actions
from stonebranch_graph.tui import TerminalUi


def _no_pause(*args: object, **kwargs: object) -> None:
    return None


def test_action_with_missing_settings_does_not_run_workflow_or_prompt_for_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    ui = TerminalUi()
    ui.settings.output_path = str(tmp_path / "out")
    ui.settings.stonebranch_path = ""

    monkeypatch.setattr(ui, "pause", _no_pause)
    monkeypatch.setattr(ui, "menu_choice", lambda label, valid: "2")
    monkeypatch.setattr(ui, "settings_menu", lambda: (_ for _ in ()).throw(AssertionError("settings menu should not open when user chooses Back")))
    monkeypatch.setattr(
        tui_actions,
        "build_stonebranch_pack",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("workflow must not run with missing settings")),
    )

    ui.build_stonebranch_pack()

    output = capsys.readouterr().out
    assert "This action uses saved Settings only" in output
    assert "Stonebranch source folder" in output
    assert "  1) Open Settings" in output
    assert "  2) Back" in output


def test_action_revalidates_after_settings_and_stops_if_still_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    ui = TerminalUi()
    ui.settings.output_path = str(tmp_path / "out")
    ui.settings.jil_path = ""
    opened_settings: list[bool] = []

    monkeypatch.setattr(ui, "pause", _no_pause)
    monkeypatch.setattr(ui, "menu_choice", lambda label, valid: "1")
    monkeypatch.setattr(ui, "settings_menu", lambda: opened_settings.append(True))
    monkeypatch.setattr(
        tui_actions,
        "build_jil_pack",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("workflow must not run until settings are valid")),
    )

    ui.build_jil_pack()

    output = capsys.readouterr().out
    assert opened_settings == [True]
    assert output.count("This action uses saved Settings only") == 2
    assert "Required settings are still missing" in output


def test_action_uses_saved_settings_when_valid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "stonebranch"
    source.mkdir()
    out = tmp_path / "out" / "stonebranch-pack"

    ui = TerminalUi()
    ui.settings.stonebranch_path = str(source)
    ui.settings.stonebranch_pack_path = str(out)

    called: list[tuple[str, str]] = []

    class Result:
        summary = {"nodes": 1}
        files = []

    monkeypatch.setattr(ui, "pause", _no_pause)
    monkeypatch.setattr(ui, "show_last_files", lambda pause=True: None)
    monkeypatch.setattr(
        tui_actions,
        "build_stonebranch_pack",
        lambda settings, config: called.append((settings.stonebranch_path, settings.stonebranch_pack_path)) or Result(),
    )

    ui.build_stonebranch_pack()

    assert called == [(str(source), str(out))]
    assert ui.last_summary == {"nodes": 1}


def test_build_and_compare_actions_do_not_call_path_pickers_or_text_prompts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ui = TerminalUi()
    ui.settings.output_path = str(tmp_path / "out")
    monkeypatch.setattr(ui, "menu_choice", lambda label, valid: "2")
    monkeypatch.setattr(ui, "pause", _no_pause)
    monkeypatch.setattr(ui, "pick_folder_setting", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("actions must not pick folders directly")))
    monkeypatch.setattr(ui, "pick_file_setting", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("actions must not pick files directly")))
    monkeypatch.setattr(ui, "ask", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("actions must not ask for paths directly")))

    ui.build_stonebranch_pack()
    ui.build_jil_pack()
    ui.compare_packs()
    ui.run_compare()
    ui.compare_json()
    ui.profile_stonebranch()
    ui.profile_jil()
