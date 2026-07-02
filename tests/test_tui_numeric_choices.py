from __future__ import annotations

from pathlib import Path

import pytest

from stonebranch_graph import tui_prompts


def test_file_setting_shows_numbered_options_on_separate_lines(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    choices: list[tuple[str, set[str]]] = []

    def choose_keep_current(label: str, valid: set[str]) -> str:
        choices.append((label, valid))
        return "2"

    monkeypatch.setattr(tui_prompts, "menu_choice", choose_keep_current)

    value = tui_prompts.pick_file_setting(
        "Mapping JSON optional",
        str(tmp_path / "mapping.json"),
        tmp_path,
        allow_empty=True,
    )

    output = capsys.readouterr().out
    assert value == str(tmp_path / "mapping.json")
    assert choices == [("Choose number", {"1", "2", "3", "4"})]
    assert "  1) Open file picker\n" in output
    assert "  2) Keep current\n" in output
    assert "  3) Manual input fallback\n" in output
    assert "  4) Empty\n" in output
    assert "B =" not in output
    assert "C =" not in output
    assert "M =" not in output
    assert "E =" not in output


def test_yes_no_key_uses_numbered_options(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    keys = iter(["1"])
    monkeypatch.setattr(tui_prompts, "get_key", lambda: next(keys))

    assert tui_prompts.yes_no_key("Include raw values?", False) is True

    output = capsys.readouterr().out
    assert "  1) Yes\n" in output
    assert "  2) No\n" in output
    assert "Y/N" not in output
