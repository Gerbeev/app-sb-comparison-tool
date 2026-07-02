from __future__ import annotations

import re
from pathlib import Path

from stonebranch_graph import tui_prompts
from stonebranch_graph.tui import TerminalUi
from stonebranch_graph.tui_rendering import next_recommended_action
from stonebranch_graph.tui_settings import TuiSettings


ROOT = Path(__file__).resolve().parents[1]


def test_tui_prompt_options_use_parentheses_not_dot(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(tui_prompts, "menu_choice", lambda label, valid: "2")

    tui_prompts.pick_file_setting("Mapping JSON optional", str(tmp_path / "mapping.json"), tmp_path, allow_empty=True)

    output = capsys.readouterr().out
    assert "  1) Open file picker\n" in output
    assert "  2) Keep current\n" in output
    assert "  3) Manual input fallback\n" in output
    assert "  4) Empty\n" in output
    assert not re.search(r"^\s+[1-4]\. ", output, flags=re.MULTILINE)


def test_yes_no_prompt_uses_parentheses_not_letters(monkeypatch, capsys) -> None:
    keys = iter(["2"])
    monkeypatch.setattr(tui_prompts, "get_key", lambda: next(keys))

    assert tui_prompts.yes_no_key("Include raw values?", True) is False

    output = capsys.readouterr().out
    assert "  1) Yes\n" in output
    assert "  2) No\n" in output
    assert "Y/N" not in output
    assert not re.search(r"^\s+[1-2]\. ", output, flags=re.MULTILINE)


def test_missing_settings_menu_uses_parentheses(monkeypatch, capsys, tmp_path) -> None:
    ui = TerminalUi()
    ui.settings.output_path = str(tmp_path / "out")
    ui.settings.stonebranch_path = ""
    monkeypatch.setattr(ui, "menu_choice", lambda label, valid: "2")
    monkeypatch.setattr(ui, "pause", lambda *args, **kwargs: None)

    ui.build_stonebranch_pack()

    output = capsys.readouterr().out
    assert "  1) Open Settings" in output
    assert "  2) Back" in output
    assert "  1. Open Settings" not in output
    assert "  2. Back" not in output


def test_dashboard_recommendations_use_menu_number_format(tmp_path) -> None:
    sb_source = tmp_path / "sb-source"
    jil_source = tmp_path / "jil-source"
    out_dir = tmp_path / "out"
    sb_source.mkdir()
    jil_source.mkdir()
    out_dir.mkdir()
    settings = TuiSettings(
        stonebranch_path=str(sb_source),
        jil_path=str(jil_source),
        output_path=str(out_dir),
        stonebranch_pack_path=str(out_dir / "stonebranch-pack"),
        jil_pack_path=str(out_dir / "jil-pack"),
        compare_pack_path=str(out_dir / "compare-pack"),
    )

    assert next_recommended_action(settings).startswith("1) Build Stonebranch")


def test_tui_docs_use_numeric_parentheses_and_keep_zero_back_exit() -> None:
    docs_text = "\n".join(
        [
            (ROOT / "README.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "TERMINAL_UI.md").read_text(encoding="utf-8"),
        ]
    )
    assert "1) Open file picker" in docs_text
    assert "2) Keep current" in docs_text
    assert "3) Manual input fallback" in docs_text
    assert "4) Empty" in docs_text
    assert "0) Back" in docs_text
    assert "0) Exit" in docs_text
    for bad in ["1. Open file picker", "2. Keep current", "3. Manual input fallback", "4. Empty", "B =", "C =", "M =", "E =", "Y/N"]:
        assert bad not in docs_text
