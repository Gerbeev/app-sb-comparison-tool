from __future__ import annotations

from pathlib import Path

import pytest

from stonebranch_graph import tui_prompts


def test_folder_setting_opens_system_picker_without_menu_or_manual_input(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    selected = tmp_path / "selected-source"
    selected.mkdir()

    def fail_menu(*args: object, **kwargs: object) -> str:
        raise AssertionError("folder settings must not show a numbered manual-input menu")

    def fail_ask(*args: object, **kwargs: object) -> str:
        raise AssertionError("folder settings must not ask for manual path input")

    monkeypatch.setattr(tui_prompts, "menu_choice", fail_menu)
    monkeypatch.setattr(tui_prompts, "ask", fail_ask)
    monkeypatch.setattr(tui_prompts, "pick_directory", lambda title, start: selected)

    value = tui_prompts.pick_folder_setting(
        "Stonebranch repo",
        "",
        tmp_path,
        allow_empty=False,
    )

    assert value == str(selected)


def test_folder_setting_cancel_keeps_current_without_manual_prompt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    current = tmp_path / "current-source"
    current.mkdir()
    warnings: list[str] = []

    def fail_ask(*args: object, **kwargs: object) -> str:
        raise AssertionError("cancelled folder picker must not fall back to manual path input")

    monkeypatch.setattr(tui_prompts, "ask", fail_ask)
    monkeypatch.setattr(tui_prompts, "pick_directory", lambda title, start: None)

    value = tui_prompts.pick_folder_setting(
        "Stonebranch repo",
        str(current),
        tmp_path,
        allow_empty=False,
        warn=warnings.append,
    )

    assert value == str(current)
    assert warnings == ["Folder selection cancelled or the system picker is unavailable. Current value kept."]
