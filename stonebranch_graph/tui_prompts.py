from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

from .native_dialogs import pick_directory, pick_file
from .tui_rendering import color_text

WarnFn = Callable[[str], None]


def get_key() -> str:
    if not sys.stdin.isatty():
        return input().strip()[:1]

    if os.name == "nt":
        import msvcrt

        return msvcrt.getwch()

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def menu_choice(label: str, valid: set[str]) -> str:
    valid_upper = {item.upper() for item in valid}
    while True:
        print(f"{color_text(label + ': ', 'bright_white', 'bold')}", end="", flush=True)
        key = get_key().upper()
        if key in valid_upper:
            print(key)
            return key
        print(color_text(f"\nInvalid key: {key or '<empty>'}", "bright_red"))


def yes_no_key(label: str, current: bool) -> bool:
    default_choice = "1" if current else "2"
    print()
    print(color_text(label, "bright_cyan", "bold"))
    print("  1) Yes")
    print("  2) No")
    print(f"Choose number [{default_choice}]: ", end="", flush=True)
    while True:
        key = get_key().strip()
        if key == "1":
            print("1")
            return True
        if key == "2":
            print("2")
            return False
        if key in {"\r", "\n", ""}:
            print(default_choice)
            return current
        print(color_text(f"\nInvalid option: {key or '<empty>'}. Choose 1 or 2.", "bright_red"))
        print(f"Choose number [{default_choice}]: ", end="", flush=True)


def ask(label: str, current: str = "") -> str:
    suffix = f" [{current}]" if current else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or current


def pick_folder_setting(
    label: str,
    current: str,
    default_start: Path,
    *,
    allow_empty: bool = True,
    warn: WarnFn | None = None,
) -> str:
    print()
    print(color_text(label, "bright_cyan", "bold"))
    if current:
        print(f"  Current: {color_text(current, 'bright_white')}")

    gui_available = os.environ.get("SB_TOOL_NO_NATIVE_DIALOG") != "1"
    selected: Path | None = None
    if gui_available:
        print("  Opening system folder picker...")
        selected = pick_directory(label, Path(current) if current else default_start)

    if selected:
        print(f"  Selected: {color_text(str(selected), 'bright_white')}")
        return str(selected)

    message = "Folder selection cancelled or the system picker is unavailable. Falling back to manual path input."
    if warn:
        warn(message)
    else:
        print(color_text(f"⚠ {message}", "bright_yellow", "bold"))

    return _manual_path_input(label, current, allow_empty=allow_empty, want_dir=True)


def _manual_path_input(
    label: str,
    current: str,
    *,
    allow_empty: bool,
    want_dir: bool,
) -> str:
    suffix = f" [{current}]" if current else (" [empty]" if allow_empty else "")
    while True:
        value = input(f"  Enter path for '{label}'{suffix}: ").strip()
        if not value:
            if current:
                return current
            if allow_empty:
                return ""
            print(color_text("  Path cannot be empty.", "bright_red"))
            continue

        p = Path(value)
        if want_dir and not p.is_dir():
            print(color_text(f"  Not a valid directory: {value}", "bright_red"))
            continue
        if not want_dir and not p.is_file():
            print(color_text(f"  Not a valid file: {value}", "bright_red"))
            continue
        return str(p)


def pick_file_setting(
    label: str,
    current: str,
    default_start: Path,
    *,
    allow_empty: bool = False,
    warn: WarnFn | None = None,
) -> str:
    print()
    print(color_text(label, "bright_cyan", "bold"))
    if current:
        print(f"  Current: {color_text(current, 'bright_white')}")
    print("  1) Open file picker")
    print("  2) Keep current")
    print("  3) Manual input fallback")
    if allow_empty:
        print("  4) Empty")
    valid = {"1", "2", "3"} | ({"4"} if allow_empty else set())
    choice = menu_choice("Choose number", valid)

    if choice == "2":
        return current
    if choice == "4":
        return ""
    if choice == "3":
        return _manual_path_input(label, current, allow_empty=allow_empty, want_dir=False)

    if os.environ.get("SB_TOOL_NO_NATIVE_DIALOG") == "1":
        message = "Native file picker disabled (SB_TOOL_NO_NATIVE_DIALOG=1). Falling back to manual path input."
        if warn:
            warn(message)
        else:
            print(color_text(f"⚠ {message}", "bright_yellow", "bold"))
        return _manual_path_input(label, current, allow_empty=allow_empty, want_dir=False)

    print("  Opening system file picker...")
    selected = pick_file(label, Path(current).parent if current else default_start)
    if selected:
        return str(selected)

    message = "System file picker is unavailable. Falling back to manual path input."
    if warn:
        warn(message)
    else:
        print(color_text(f"⚠ {message}", "bright_yellow", "bold"))
    return _manual_path_input(label, current, allow_empty=allow_empty, want_dir=False)
