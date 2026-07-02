from __future__ import annotations

from stonebranch_graph.tui import TerminalUi
from stonebranch_graph.tui_rendering import SETTINGS_MENU_ITEMS


def test_settings_menu_has_zero_back_option() -> None:
    assert ("0", "Back", "Return to the main menu.") in SETTINGS_MENU_ITEMS


def test_settings_menu_accepts_zero_back(monkeypatch) -> None:
    ui = TerminalUi()
    ui.clear = lambda: None
    ui.header = lambda title="": None
    ui.print_settings_compact = lambda: None
    ui.print_settings_menu = lambda items: None

    def fake_menu_choice(label: str, valid: set[str]) -> str:
        assert "0" in valid
        return "0"

    ui.menu_choice = fake_menu_choice  # type: ignore[method-assign]
    ui.settings_menu()


def test_cancelled_folder_selection_does_not_report_success(monkeypatch) -> None:
    ui = TerminalUi()
    ui.clear = lambda: None
    ui.header = lambda title="": None
    ui.pause = lambda message="": None
    ui.pick_folder_setting = lambda label, current, default_start, allow_empty=True: current  # type: ignore[method-assign]

    messages: list[tuple[str, str]] = []
    ui.success = lambda message: messages.append(("success", message))  # type: ignore[method-assign]
    ui.warn = lambda message: messages.append(("warn", message))  # type: ignore[method-assign]

    ui.configure_stonebranch_source_folder()

    assert ("warn", "Stonebranch source folder was not changed.") in messages
    assert not [message for level, message in messages if level == "success"]
