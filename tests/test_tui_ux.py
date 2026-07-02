from __future__ import annotations

from pathlib import Path


def test_tui_menu_mentions_one_key_and_system_pickers(monkeypatch, capsys) -> None:
    monkeypatch.setenv("STONEBRANCH_FORCE_COLOR", "1")
    from stonebranch_graph.tui import TerminalUi

    TerminalUi().print_main_menu()
    output = capsys.readouterr().out
    assert "number" in output
    assert "system pickers" in output
    assert "Build Stonebranch analysis pack" in output


def test_native_dialog_module_imports() -> None:
    from stonebranch_graph.native_dialogs import pick_directory, pick_file

    assert callable(pick_directory)
    assert callable(pick_file)


def test_tui_uses_simple_picker_methods() -> None:
    from stonebranch_graph.tui import TerminalUi

    ui = TerminalUi()
    assert callable(ui.pick_folder_setting)
    assert callable(ui.pick_file_setting)
    assert callable(ui.menu_choice)


def test_docs_describe_current_native_picker_not_removed_terminal_browser() -> None:
    root = Path(__file__).resolve().parents[1]
    docs_text = "\n".join(
        [
            (root / "README.md").read_text(encoding="utf-8"),
            (root / "docs" / "TERMINAL_UI.md").read_text(encoding="utf-8"),
        ]
    )

    obsolete_fragments = [
        "1-9 open folder/file",
        "1-9  open directory or select file",
        "U go up",
        "U    go up",
        "N/P next/previous page",
        "Path settings use a terminal browser",
        "Folder/file browser",
    ]
    for fragment in obsolete_fragments:
        assert fragment not in docs_text

    assert "Folder path settings open" in docs_text
    assert "opens folder picker" in docs_text
    assert "Cancel keeps the current value" in docs_text
    for obsolete_picker_fragment in [
        "B = open file picker",
        "C = keep current",
        "M = manual input fallback",
        "E = empty",
    ]:
        assert obsolete_picker_fragment not in docs_text

    assert "1) Open file picker" in docs_text
    assert "2) Keep current" in docs_text
    assert "3) Manual input fallback" in docs_text
    assert "4) Empty" in docs_text
