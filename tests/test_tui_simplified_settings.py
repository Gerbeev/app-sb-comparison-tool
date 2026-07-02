from pathlib import Path

from stonebranch_graph.tui import TerminalUi
from stonebranch_graph.tui_rendering import (
    SETTINGS_ADVANCED_MENU_ITEMS,
    SETTINGS_MENU_ITEMS,
    SETTINGS_MORE_MENU_ITEMS,
    SETTINGS_STORAGE_MENU_ITEMS,
)


def test_settings_main_screen_is_simplified_to_core_numeric_items_with_zero_back() -> None:
    labels = [item[1] for item in SETTINGS_MENU_ITEMS]

    assert [item[0] for item in SETTINGS_MENU_ITEMS] == ["1", "2", "3", "4", "0"]
    assert labels == [
        "Stonebranch source folder",
        "JIL source folder",
        "Output folder",
        "More settings",
        "Back",
    ]
    assert "Parser and output options" not in labels
    assert "Existing graph.json paths" not in labels
    assert "Reset to defaults" not in labels


def test_nested_settings_menus_use_only_one_to_four() -> None:
    for menu in (SETTINGS_MORE_MENU_ITEMS, SETTINGS_ADVANCED_MENU_ITEMS, SETTINGS_STORAGE_MENU_ITEMS):
        assert [item[0] for item in menu] == ["1", "2", "3", "4"]


def test_output_folder_auto_fills_standard_pack_paths(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "analysis-output"
    output.mkdir()
    ui = TerminalUi()

    monkeypatch.setattr(ui, "clear", lambda: None)
    monkeypatch.setattr(ui, "header", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui, "pause", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui, "pick_folder_setting", lambda *_args, **_kwargs: str(output))

    ui.configure_base_output_folder()

    assert ui.settings.output_path == str(output)
    assert ui.settings.stonebranch_pack_path == str(output / "stonebranch-pack")
    assert ui.settings.jil_pack_path == str(output / "jil-pack")
    assert ui.settings.compare_pack_path == str(output / "compare-pack")


def test_settings_docs_describe_simplified_screen() -> None:
    text = Path("README.md").read_text(encoding="utf-8") + "\n" + Path("docs/TERMINAL_UI.md").read_text(encoding="utf-8")

    assert "1) Stonebranch source folder" in text
    assert "2) JIL source folder" in text
    assert "3) Output folder" in text
    assert "4) More settings" in text
    assert "Settings → Output folder → opens folder picker and auto-fills pack folders" in text
    assert "1) Show current settings" not in text
    assert "10) Reset to defaults" not in text
