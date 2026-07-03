from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

from . import tui_actions
from .config import AnalyzerConfig
from .logging_utils import log_error, log_warning
from .tui_prompts import ask, menu_choice, pick_file_setting, pick_folder_setting, yes_no_key
from .tui_rendering import (
    MAIN_MENU_ITEMS,
    OTHER_MENU_ITEMS,
    SETTINGS_ADVANCED_MENU_ITEMS,
    SETTINGS_MENU_ITEMS,
    SETTINGS_MORE_MENU_ITEMS,
    SETTINGS_STORAGE_MENU_ITEMS,
    clear_screen,
    color_text,
    enable_windows_ansi,
    print_compare_summary,
    print_header,
    print_last_files,
    print_main_dashboard,
    print_menu_item,
    print_settings_compact,
    print_settings_detailed,
    print_summary,
)
from .tui_settings import (
    SETTINGS_FILE,
    TuiSettings,
    load_tui_settings,
    path_exists,
    save_tui_settings,
)


class TerminalUi:
    def __init__(self) -> None:
        self.config = AnalyzerConfig.default()
        self.settings = self.load_settings()
        self.last_files: list[Path] = []
        self.last_summary: dict[str, Any] = {}

    def run(self) -> int:
        enable_windows_ansi()
        while True:
            self.clear()
            self.header()
            self.print_main_dashboard()
            self.print_main_menu()
            choice = self.menu_choice("Select", {item[0] for item in MAIN_MENU_ITEMS})
            try:
                if choice == "1":
                    self.build_stonebranch_pack()
                elif choice == "2":
                    self.build_jil_pack()
                elif choice == "3":
                    self.compare_packs()
                elif choice == "4":
                    self.settings_menu()
                elif choice == "5":
                    self.other_menu()
                elif choice == "0":
                    self.save_settings(silent=True)
                    return 0
            except KeyboardInterrupt:
                print()
                self.pause("Cancelled.")
            except Exception as exc:
                self.error(str(exc))
                if self.yes_no_key("Show traceback?", False):
                    traceback.print_exc()
                self.pause()

    def print_main_menu(self) -> None:
        print()
        print(self.color("Choose menu items by number. Folder settings open system pickers directly.", "bright_yellow"))
        print()
        for number, title, description, tag in MAIN_MENU_ITEMS:
            print_menu_item(number, title, description, tag)
        print(self.color("─" * 72, "bright_blue"))

    def other_menu(self) -> None:
        while True:
            self.clear()
            self.header("Other tools")
            print(self.color("Secondary tools. Main workflow stays pack-based.", "gray"))
            print()
            for number, title, description, tag in OTHER_MENU_ITEMS:
                print_menu_item(number, title, description, tag)
            choice = self.menu_choice("Select", {item[0] for item in OTHER_MENU_ITEMS})
            try:
                if choice == "1":
                    self.build_stonebranch_skeleton()
                elif choice == "2":
                    self.build_jil_skeleton()
                elif choice == "3":
                    self.compare_skeleton()
                elif choice == "4":
                    self.run_compare()
                elif choice == "5":
                    self.compare_json()
                elif choice == "6":
                    self.profile_stonebranch()
                elif choice == "7":
                    self.profile_jil()
                elif choice == "8":
                    self.show_last_files()
                elif choice == "0":
                    return
            except Exception as exc:
                self.error(str(exc))
                self.pause()

    def settings_menu(self) -> None:
        while True:
            self.clear()
            self.header("Settings")
            self.print_settings_compact()
            print()
            print(self.color("Basic setup. Choose folders with system pickers; no manual folder path entry.", "gray"))
            print()
            self.print_settings_menu(SETTINGS_MENU_ITEMS)
            choice = self.menu_choice("Select", {item[0] for item in SETTINGS_MENU_ITEMS})

            if choice == "1":
                self.configure_stonebranch_source_folder()
            elif choice == "2":
                self.configure_jil_source_folder()
            elif choice == "3":
                self.configure_base_output_folder()
            elif choice == "4":
                self.settings_more_menu()
            elif choice == "0":
                return

    def print_settings_menu(self, items: list[tuple[str, str, str]]) -> None:
        for number, title, description in items:
            print(f" {self.color(number.rjust(2), 'bright_yellow', 'bold')}) {self.color(title, 'bright_yellow', 'bold')}")
            print(f"     {self.color(description, 'gray')}")
            print()

    def settings_more_menu(self) -> None:
        while True:
            self.clear()
            self.header("More settings")
            self.print_settings_compact()
            print()
            self.print_settings_menu(SETTINGS_MORE_MENU_ITEMS)
            choice = self.menu_choice("Select", {item[0] for item in SETTINGS_MORE_MENU_ITEMS})

            if choice == "1":
                self.configure_environment()
            elif choice == "2":
                self.settings_advanced_menu()
            elif choice == "3":
                self.settings_storage_menu()
            elif choice == "4":
                return

    def settings_advanced_menu(self) -> None:
        while True:
            self.clear()
            self.header("Advanced settings")
            print(self.color("Advanced options are optional. Most users only need the first Settings screen.", "gray"))
            print()
            self.print_settings_menu(SETTINGS_ADVANCED_MENU_ITEMS)
            choice = self.menu_choice("Select", {item[0] for item in SETTINGS_ADVANCED_MENU_ITEMS})

            if choice == "1":
                self.configure_mapping_file()
            elif choice == "2":
                self.configure_parser_options()
            elif choice == "3":
                self.configure_custom_paths_menu()
            elif choice == "4":
                return

    def settings_storage_menu(self) -> None:
        while True:
            self.clear()
            self.header("Save / load / reset")
            self.print_settings_compact()
            print()
            self.print_settings_menu(SETTINGS_STORAGE_MENU_ITEMS)
            choice = self.menu_choice("Select", {item[0] for item in SETTINGS_STORAGE_MENU_ITEMS})

            if choice == "1":
                self.save_settings()
                self.pause()
            elif choice == "2":
                self.settings = self.load_settings()
                self.success("Settings loaded.")
                self.pause()
            elif choice == "3":
                if self.yes_no_key("Reset settings to defaults?", False):
                    self.settings = TuiSettings()
                    self.success("Settings reset in memory.")
                    self.pause()
            elif choice == "4":
                return

    def configure_stonebranch_source_folder(self) -> None:
        self.clear()
        self.header("Stonebranch source folder")
        s = self.settings
        previous = s.stonebranch_path
        s.stonebranch_path = self.pick_folder_setting("Stonebranch source folder", previous, Path.cwd(), allow_empty=False)
        if s.stonebranch_path != previous and s.stonebranch_path:
            self.success("Stonebranch source folder updated.")
        else:
            self.warn("Stonebranch source folder was not changed.")
        self.pause()

    def configure_jil_source_folder(self) -> None:
        self.clear()
        self.header("JIL source folder")
        s = self.settings
        previous = s.jil_path
        s.jil_path = self.pick_folder_setting("JIL source folder", previous, Path.cwd(), allow_empty=False)
        if s.jil_path != previous and s.jil_path:
            self.success("JIL source folder updated.")
        else:
            self.warn("JIL source folder was not changed.")
        self.pause()

    def configure_base_output_folder(self) -> None:
        self.clear()
        self.header("Output folder")
        s = self.settings
        previous = s.output_path
        base_dir = self.pick_folder_setting("Base output folder", previous, Path.cwd(), allow_empty=False)
        if base_dir and base_dir != previous:
            s.output_path = base_dir
            s.stonebranch_pack_path = str(Path(base_dir) / "stonebranch-pack")
            s.jil_pack_path = str(Path(base_dir) / "jil-pack")
            s.compare_pack_path = str(Path(base_dir) / "compare-pack")
            self.success("Output folder updated and pack folders auto-filled.")
            self.print_settings_compact()
        else:
            self.warn("Output folder was not changed.")
        self.pause()

    def configure_environment(self) -> None:
        self.clear()
        self.header("Environment")
        s = self.settings
        s.env = self.ask("Environment name", s.env or "PROD")
        self.success("Environment updated.")
        self.pause()

    def configure_mapping_file(self) -> None:
        self.clear()
        self.header("Mapping file")
        s = self.settings
        s.mapping_path = self.pick_file_setting("Mapping JSON optional", s.mapping_path, Path.cwd(), allow_empty=True)
        self.success("Mapping setting updated.")
        self.pause()

    def configure_custom_paths_menu(self) -> None:
        while True:
            self.clear()
            self.header("Custom output and graph.json paths")
            print(self.color("Only needed for advanced workflows. The main output folder auto-fills pack paths.", "gray"))
            print()
            print("  1) Custom analysis pack folders")
            print("  2) Existing graph.json paths")
            print("  3) Show current settings")
            print("  4) Back")
            choice = self.menu_choice("Select", {"1", "2", "3", "4"})

            if choice == "1":
                self.configure_pack_paths()
            elif choice == "2":
                self.configure_graph_json_paths()
            elif choice == "3":
                self.clear()
                self.header("Current settings")
                self.print_settings_detailed()
                self.pause()
            elif choice == "4":
                return

    def configure_pack_paths(self) -> None:
        self.clear()
        self.header("Custom analysis pack folders")
        s = self.settings
        print(self.color("Advanced override. Use Settings → Output folder for the normal workflow.", "gray"))
        print()
        s.stonebranch_pack_path = self.pick_folder_setting("Stonebranch pack output", s.stonebranch_pack_path, Path(s.output_path), allow_empty=False)
        s.jil_pack_path = self.pick_folder_setting("JIL pack output", s.jil_pack_path, Path(s.output_path), allow_empty=False)
        s.compare_pack_path = self.pick_folder_setting("Compare pack output", s.compare_pack_path, Path(s.output_path), allow_empty=False)
        self.success("Custom pack output folders updated.")
        self.pause()

    def configure_parser_options(self) -> None:
        self.clear()
        self.header("Parser and output options")
        s = self.settings
        s.include_raw_values = self.yes_no_key("Include raw command/script values?", s.include_raw_values)
        s.deep_scan = self.yes_no_key("Deep scan Stonebranch strings?", s.deep_scan)
        s.env_aware = self.yes_no_key("Env-aware Stonebranch folder layout?", s.env_aware)
        self.success("Parser/output options updated.")
        self.pause()

    def configure_graph_json_paths(self) -> None:
        self.clear()
        self.header("Existing graph.json paths")
        s = self.settings
        print(self.color("Only needed for Other tools → Compare existing graph.json files.", "gray"))
        print()
        s.stonebranch_graph_json = self.pick_file_setting("Stonebranch graph.json", s.stonebranch_graph_json, Path.cwd(), allow_empty=False)
        s.jil_graph_json = self.pick_file_setting("JIL graph.json", s.jil_graph_json, Path.cwd(), allow_empty=False)
        self.success("graph.json paths updated.")
        self.pause()

    def build_stonebranch_pack(self) -> None:
        s = self.ensure_settings_for("build-stonebranch-pack")
        if s is None:
            return
        out = Path(s.stonebranch_pack_path)
        result = tui_actions.build_stonebranch_pack(s, self.config)
        self.last_summary = result.summary
        self.last_files = result.files
        self.success(f"Stonebranch analysis pack created: {out.resolve()}")
        self.print_summary(self.last_summary)
        self.show_last_files(pause=False)
        self.pause()

    def build_jil_pack(self) -> None:
        s = self.ensure_settings_for("build-jil-pack")
        if s is None:
            return
        out = Path(s.jil_pack_path)
        result = tui_actions.build_jil_pack(s, self.config)
        self.last_summary = result.summary
        self.last_files = result.files
        self.success(f"JIL analysis pack created: {out.resolve()}")
        self.print_summary(self.last_summary)
        self.show_last_files(pause=False)
        self.pause()

    def compare_packs(self) -> None:
        s = self.ensure_settings_for("compare-packs")
        if s is None:
            return
        out = Path(s.compare_pack_path)
        result = tui_actions.compare_packs(s, self.config)
        self.last_summary = result.summary
        self.last_files = result.files
        self.success(f"Comparison analysis pack created: {out.resolve()}")
        self.print_compare_summary(self.last_summary)
        self.show_last_files(pause=False)
        self.pause()

    def build_stonebranch_skeleton(self) -> None:
        s = self.ensure_settings_for("build-skeleton-stonebranch")
        if s is None:
            return
        result = tui_actions.build_stonebranch_skeleton(s, self.config)
        self.last_summary = result.summary
        self.last_files = result.files
        self.success("Stonebranch skeleton created.")
        self.print_summary(self.last_summary)
        self.show_last_files(pause=False)
        self.pause()

    def build_jil_skeleton(self) -> None:
        s = self.ensure_settings_for("build-skeleton-jil")
        if s is None:
            return
        result = tui_actions.build_jil_skeleton(s, self.config)
        self.last_summary = result.summary
        self.last_files = result.files
        self.success("JIL skeleton created.")
        self.print_summary(self.last_summary)
        self.show_last_files(pause=False)
        self.pause()

    def compare_skeleton(self) -> None:
        s = self.ensure_settings_for("compare-skeleton")
        if s is None:
            return
        result = tui_actions.compare_skeleton(s, self.config)
        self.last_summary = result.summary
        self.last_files = result.files
        self.success("Skeleton compare completed.")
        self.print_summary(self.last_summary)
        self.show_last_files(pause=False)
        self.pause()

    def run_compare(self) -> None:
        s = self.ensure_settings_for("direct-compare")
        if s is None:
            return
        result = tui_actions.compare_direct(s, self.config)
        self.last_summary = result.summary
        self.last_files = result.files
        self.success("Direct compare completed.")
        self.print_compare_summary(self.last_summary)
        self.show_last_files(pause=False)
        self.pause()

    def compare_json(self) -> None:
        s = self.ensure_settings_for("compare-json")
        if s is None:
            return
        result = tui_actions.compare_graph_json(s, self.config)
        self.last_summary = result.summary
        self.last_files = result.files
        self.success("Compare existing graph.json completed.")
        self.print_compare_summary(self.last_summary)
        self.show_last_files(pause=False)
        self.pause()

    def profile_stonebranch(self) -> None:
        s = self.ensure_settings_for("profile-stonebranch")
        if s is None:
            return
        result = tui_actions.profile_stonebranch(s, self.config)
        self.last_summary = result.summary
        self.last_files = result.files
        self.success("Stonebranch schema profile completed.")
        self.show_last_files(pause=False)
        self.pause()

    def profile_jil(self) -> None:
        s = self.ensure_settings_for("profile-jil")
        if s is None:
            return
        result = tui_actions.profile_jil(s)
        self.last_summary = result.summary
        self.last_files = result.files
        self.success("JIL schema profile completed.")
        self.show_last_files(pause=False)
        self.pause()

    def missing_settings_for(self, mode: str) -> list[str]:
        s = self.settings
        missing: list[str] = []

        if mode in {
            "build-stonebranch-pack",
            "build-skeleton-stonebranch",
            "compare-skeleton",
            "direct-compare",
            "profile-stonebranch",
        } and not path_exists(s.stonebranch_path):
            missing.append("Stonebranch source folder")
        if mode in {
            "build-jil-pack",
            "build-skeleton-jil",
            "compare-skeleton",
            "direct-compare",
            "profile-jil",
        } and not path_exists(s.jil_path):
            missing.append("JIL source folder")
        if mode == "compare-packs":
            if not (path_exists(s.stonebranch_pack_path) and (Path(s.stonebranch_pack_path) / "graph.json").exists()):
                missing.append("Stonebranch analysis pack folder with graph.json")
            if not (path_exists(s.jil_pack_path) and (Path(s.jil_pack_path) / "graph.json").exists()):
                missing.append("JIL analysis pack folder with graph.json")
        if mode == "compare-json":
            if not path_exists(s.stonebranch_graph_json):
                missing.append("Stonebranch graph.json file")
            if not path_exists(s.jil_graph_json):
                missing.append("JIL graph.json file")

        return missing

    def ensure_settings_for(self, mode: str) -> TuiSettings | None:
        missing = self.missing_settings_for(mode)
        if not missing:
            return self.settings

        self.show_missing_settings(missing)
        print("  1) Open Settings")
        print("  2) Back")
        choice = self.menu_choice("Choose number", {"1", "2"})

        if choice == "2":
            return None

        self.settings_menu()
        missing = self.missing_settings_for(mode)
        if missing:
            self.show_missing_settings(missing)
            self.warn("Required settings are still missing.")
            self.pause("Press Enter to return...")
            return None

        return self.settings

    def show_missing_settings(self, missing: list[str]) -> None:
        self.warn("This action uses saved Settings only. Required values are missing:")
        for index, item in enumerate(missing, start=1):
            print(f"  {index}) {item}")
        print()
        print("Open Settings to select folders/files with pickers, then run this action again.")

    def print_main_dashboard(self) -> None:
        print_main_dashboard(self.settings)

    def print_settings_compact(self) -> None:
        print_settings_compact(self.settings)

    def print_settings_detailed(self) -> None:
        print_settings_detailed(self.settings)

    def print_summary(self, summary: dict[str, Any]) -> None:
        print_summary(summary)

    def print_compare_summary(self, summary: dict[str, Any]) -> None:
        print_compare_summary(summary)

    def show_last_files(self, pause: bool = True) -> None:
        print_last_files(self.last_files)
        if pause:
            self.pause()

    def menu_choice(self, label: str, valid: set[str]) -> str:
        return menu_choice(label, valid)

    def yes_no_key(self, label: str, current: bool) -> bool:
        return yes_no_key(label, current)

    def ask(self, label: str, current: str = "") -> str:
        return ask(label, current)

    def pick_folder_setting(self, label: str, current: str, default_start: Path, allow_empty: bool = True) -> str:
        return pick_folder_setting(label, current, default_start, allow_empty=allow_empty, warn=self.warn)

    def pick_file_setting(self, label: str, current: str, default_start: Path, allow_empty: bool = False) -> str:
        return pick_file_setting(label, current, default_start, allow_empty=allow_empty, warn=self.warn)

    def load_settings(self) -> TuiSettings:
        return load_tui_settings()

    def save_settings(self, silent: bool = False) -> None:
        save_tui_settings(self.settings)
        if not silent:
            self.success(f"Settings saved to {SETTINGS_FILE}")

    def header(self, title: str = "Stonebranch Dependency Tool") -> None:
        print_header(title)

    def clear(self) -> None:
        clear_screen()

    def pause(self, message: str = "Press Enter to continue...") -> None:
        input(f"\n{message}")

    def success(self, message: str) -> None:
        print(self.color(f"✓ {message}", "bright_green", "bold"))

    def warn(self, message: str) -> None:
        print(self.color(f"⚠ {message}", "bright_yellow", "bold"))
        log_warning(Path(self.settings.output_path), f"TUI: {message}")

    def error(self, message: str) -> None:
        print(self.color(f"✗ {message}", "bright_red", "bold"))
        log_error(Path(self.settings.output_path), f"TUI: {message}")

    def color(self, text: str, *styles: str) -> str:
        return color_text(text, *styles)


def run_tui() -> int:
    enable_windows_ansi()
    return TerminalUi().run()


if __name__ == "__main__":
    raise SystemExit(run_tui())
