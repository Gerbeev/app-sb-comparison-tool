from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

from . import __version__
from .tui_settings import SETTINGS_FILE, TuiSettings


PALETTE = {
    "bold": "1",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "gray": "90",
    "bright_red": "91",
    "bright_green": "92",
    "bright_yellow": "93",
    "bright_blue": "94",
    "bright_magenta": "95",
    "bright_cyan": "96",
    "bright_white": "97",
}


MAIN_MENU_ITEMS = [
    ("1", "Build Stonebranch analysis pack", "Create a full Stonebranch pack: graph.json, indexes, graph views, metrics, and source-side reports.", "PACK"),
    ("2", "Build JIL analysis pack", "Create a full JIL pack: graph.json, indexes, graph views, metrics, and source-side reports.", "PACK"),
    ("3", "Compare analysis packs", "Compare Stonebranch/JIL pack folders and produce detailed gaps, critical diffs, and remediation checklist.", "MAIN"),
    ("4", "Settings", "Open simple setup first, with advanced mapping, parser options, and save/load in More settings.", "SETUP"),
    ("5", "Other tools", "Direct compare, compare graph.json files, schema profiles, and last output file list.", "OTHER"),
    ("0", "Exit", "Save settings and close the terminal UI.", "EXIT"),
]


OTHER_MENU_ITEMS = [
    ("1", "Run direct compare: Stonebranch ↔ JIL", "Parse both repositories and compare immediately. Good for quick checks; packs are better for iterative analysis.", "GRAPH"),
    ("2", "Compare existing graph.json files", "Compare previously generated Stonebranch/JIL graph.json files without reparsing repositories.", "GRAPH"),
    ("3", "Profile Stonebranch schema", "Generate a safe structure profile of Stonebranch JSON keys and types without values.", "PROFILE"),
    ("4", "Profile JIL schema", "Generate a safe structure profile of JIL job blocks and attributes.", "PROFILE"),
    ("5", "Show last output files", "Print the most important files from the last run: manifests, reports, graph.json, metrics, diffs.", "SETUP"),
    ("0", "Back", "Return to the main menu.", "EXIT"),
]

OTHER_MENU_ITEMS = [
    ("1", "Build Stonebranch skeleton", "Create canonical Stonebranch skeleton JSONL, index CSV, and offline graph view.", "GRAPH"),
    ("2", "Build JIL skeleton", "Create canonical JIL skeleton JSONL, index CSV, and offline graph view.", "GRAPH"),
    ("3", "Compare skeletons", "Compare Stonebranch and JIL canonical skeletons by topology, logic, and strict levels.", "MAIN"),
    ("4", "Run legacy direct compare", "Parse both repositories and compare with the legacy graph engine.", "GRAPH"),
    ("5", "Compare existing graph.json files", "Compare previously generated Stonebranch/JIL graph.json files without reparsing repositories.", "GRAPH"),
    ("6", "Profile Stonebranch schema", "Generate a safe structure profile of Stonebranch JSON keys and types without values.", "PROFILE"),
    ("7", "Profile JIL schema", "Generate a safe structure profile of JIL job blocks and attributes.", "PROFILE"),
    ("8", "Show last output files", "Print the most important files from the last run: manifests, reports, graph.json, metrics, diffs.", "SETUP"),
    ("0", "Back", "Return to the main menu.", "EXIT"),
]


SETTINGS_MENU_ITEMS = [
    ("1", "Stonebranch source folder", "Select the Stonebranch export folder with the system folder picker."),
    ("2", "JIL source folder", "Select the AutoSys JIL folder with the system folder picker."),
    ("3", "Output folder", "Select one base output folder; analysis pack folders are auto-filled."),
    ("4", "More settings", "Environment, advanced options, save/load/reset, and detailed view."),
    ("0", "Back", "Return to the main menu."),
]


SETTINGS_MORE_MENU_ITEMS = [
    ("1", "Environment", "Set the environment name used in generated graphs and reports."),
    ("2", "Advanced settings", "Mapping file, parser flags, custom pack folders, and graph.json paths."),
    ("3", "Save / load / reset", f"Persist or reload settings from {SETTINGS_FILE}."),
    ("4", "Back", "Return to the main Settings screen."),
]


SETTINGS_ADVANCED_MENU_ITEMS = [
    ("1", "Mapping file", "Select an optional mapping.json file with the system file picker."),
    ("2", "Parser and output options", "Toggle include raw values, deep scan, and env-aware Stonebranch layout."),
    ("3", "Custom output and graph.json paths", "Override pack output folders or set graph.json files for advanced compare mode."),
    ("4", "Back", "Return to More settings."),
]


SETTINGS_STORAGE_MENU_ITEMS = [
    ("1", "Save settings", f"Write settings to {SETTINGS_FILE}."),
    ("2", "Load settings", f"Reload settings from {SETTINGS_FILE}."),
    ("3", "Reset to defaults", "Reset settings in memory. Use Save settings afterwards to persist."),
    ("4", "Back", "Return to More settings."),
]



COMPARE_SUMMARY_KEYS = [
    "migration_readiness_score",
    "readiness_grade",
    "matched_nodes",
    "matched_edges",
    "node_match_rate_percent",
    "edge_match_rate_percent",
    "critical_dependency_loss_count",
]


def supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("STONEBRANCH_FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


def color_text(text: str, *styles: str) -> str:
    if not supports_color():
        return text
    codes = [PALETTE[style] for style in styles if style in PALETTE]
    return f"\033[{';'.join(codes)}m{text}\033[0m" if codes else text


def enable_windows_ansi() -> None:
    if os.name == "nt":
        os.system("")


def clear_screen() -> None:
    if os.environ.get("TERM") and sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")


def style_for_tag(tag: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if tag == "MAIN":
        return ("bright_green", "bold"), ("bright_white", "bold"), ("bright_green", "bold")
    if tag == "PACK":
        return ("bright_cyan", "bold"), ("bright_cyan",), ("cyan",)
    if tag == "PROFILE":
        return ("bright_magenta", "bold"), ("bright_magenta",), ("magenta",)
    if tag == "SETUP":
        return ("bright_yellow", "bold"), ("bright_yellow",), ("yellow",)
    if tag == "GRAPH":
        return ("bright_cyan", "bold"), ("bright_cyan",), ("cyan",)
    if tag == "OTHER":
        return ("bright_blue", "bold"), ("bright_blue",), ("blue",)
    return ("gray",), ("gray",), ("gray",)


def print_menu_item(number: str, title: str, description: str, tag: str) -> None:
    number_style, title_style, tag_style = style_for_tag(tag)
    print(f" {color_text(number.rjust(2), *number_style)}) {color_text(title, *title_style)}  {color_text(tag, *tag_style)}")
    print(f"     {color_text(description, 'gray')}")
    print()


def print_header(title: str = "Stonebranch Dependency Tool") -> None:
    print(color_text("╔" + "═" * 70 + "╗", "bright_blue"))
    line = f" {title} · Terminal UI · v{__version__}"
    print(color_text("║" + line.ljust(70) + "║", "bright_green", "bold"))
    print(color_text("╚" + "═" * 70 + "╝", "bright_blue"))


def flag_text(enabled: bool) -> str:
    return color_text("yes", "bright_green", "bold") if enabled else color_text("no", "gray")


def _status_text(label: str, status: str) -> str:
    style_by_status = {
        "OK": ("bright_green", "bold"),
        "READY": ("bright_green", "bold"),
        "MISSING": ("bright_red", "bold"),
        "NOT BUILT": ("bright_yellow", "bold"),
        "INCOMPLETE": ("bright_yellow", "bold"),
        "WILL CREATE": ("bright_yellow", "bold"),
        "OPTIONAL": ("gray",),
    }
    styles = style_by_status.get(status, ("gray",))
    return f"{color_text(label + ':', 'gray'):<24} {color_text(status, *styles)}"


def _path_display(value: str) -> str:
    return color_text(value if value else "not selected", "bright_white" if value else "gray")


def _required_folder_status(value: str) -> str:
    return "OK" if value and Path(value).is_dir() else "MISSING"


def _output_folder_status(value: str) -> str:
    if not value:
        return "MISSING"
    return "OK" if Path(value).is_dir() else "WILL CREATE"


def _pack_status(path_value: str) -> str:
    if not path_value:
        return "MISSING"
    path = Path(path_value)
    if (path / "graph.json").exists():
        return "READY"
    return "INCOMPLETE" if path.exists() else "NOT BUILT"


def _comparison_status(path_value: str) -> str:
    if not path_value:
        return "MISSING"
    path = Path(path_value)
    if (path / "compare" / "report.md").exists() or (path / "compare" / "comparison.json").exists():
        return "READY"
    return "INCOMPLETE" if path.exists() else "NOT BUILT"


def next_recommended_action(settings: TuiSettings) -> str:
    if _required_folder_status(settings.stonebranch_path) != "OK" or _required_folder_status(settings.jil_path) != "OK":
        return "4) Settings — select missing source folders."
    if _output_folder_status(settings.output_path) == "MISSING":
        return "4) Settings — select an output folder."
    if _pack_status(settings.stonebranch_pack_path) != "READY":
        return "1) Build Stonebranch analysis pack."
    if _pack_status(settings.jil_pack_path) != "READY":
        return "2) Build JIL analysis pack."
    if _comparison_status(settings.compare_pack_path) != "READY":
        return "3) Compare analysis packs."
    return "Review generated reports or rerun comparison after source changes."


def print_main_dashboard(settings: TuiSettings) -> None:
    s = settings
    print(color_text("Project dashboard", "bright_cyan", "bold"))
    print(
        f"  {color_text('Environment:', 'gray')} {color_text(s.env, 'bright_white')}  "
        f"{color_text('Raw:', 'gray')} {flag_text(s.include_raw_values)}  "
        f"{color_text('Deep:', 'gray')} {flag_text(s.deep_scan)}  "
        f"{color_text('Env-aware:', 'gray')} {flag_text(s.env_aware)}"
    )
    print()
    print(color_text("Selected folders", "bright_blue", "bold"))
    print(f"  {_status_text('Stonebranch repo', _required_folder_status(s.stonebranch_path))}  {_path_display(s.stonebranch_path)}")
    print(f"  {_status_text('JIL repo', _required_folder_status(s.jil_path))}  {_path_display(s.jil_path)}")
    print(f"  {_status_text('Output folder', _output_folder_status(s.output_path))}  {_path_display(s.output_path)}")
    print()
    print(color_text("Analysis outputs", "bright_blue", "bold"))
    print(f"  {_status_text('Stonebranch pack', _pack_status(s.stonebranch_pack_path))}  {_path_display(s.stonebranch_pack_path)}")
    print(f"  {_status_text('JIL pack', _pack_status(s.jil_pack_path))}  {_path_display(s.jil_pack_path)}")
    print(f"  {_status_text('Comparison pack', _comparison_status(s.compare_pack_path))}  {_path_display(s.compare_pack_path)}")
    print()
    print(color_text("Next recommended action", "bright_blue", "bold"))
    print(f"  {color_text(next_recommended_action(s), 'bright_yellow', 'bold')}")


def print_settings_compact(settings: TuiSettings) -> None:
    s = settings
    print(color_text("Current settings", "bright_cyan", "bold"))
    print(
        f"  {color_text('Env:', 'gray')} {color_text(s.env, 'bright_white')}  "
        f"{color_text('Raw:', 'gray')} {flag_text(s.include_raw_values)}  "
        f"{color_text('Deep:', 'gray')} {flag_text(s.deep_scan)}  "
        f"{color_text('Env-aware:', 'gray')} {flag_text(s.env_aware)}"
    )
    print(f"  {color_text('SB pack:', 'gray')} {color_text(s.stonebranch_pack_path, 'bright_white')}")
    print(f"  {color_text('JIL pack:', 'gray')} {color_text(s.jil_pack_path, 'bright_white')}")
    print(f"  {color_text('Compare pack:', 'gray')} {color_text(s.compare_pack_path, 'bright_white')}")


def print_path_status(label: str, value: str, must_exist_when_set: bool) -> None:
    if not value:
        print(f"  {color_text(label + ':', 'gray'):<28} {color_text('-', 'gray')}")
        return
    exists = Path(value).exists()
    if exists:
        status = color_text("OK", "bright_green", "bold")
    else:
        status = color_text(
            "missing" if must_exist_when_set else "will create",
            "bright_red" if must_exist_when_set else "bright_yellow",
            "bold",
        )
    print(f"  {color_text(label + ':', 'gray'):<28} {color_text(value, 'bright_white')} [{status}]")


def print_settings_detailed(settings: TuiSettings) -> None:
    s = settings
    rows = [
        ("Stonebranch source", s.stonebranch_path, True),
        ("JIL source", s.jil_path, True),
        ("Stonebranch pack", s.stonebranch_pack_path, False),
        ("JIL pack", s.jil_pack_path, False),
        ("Compare pack", s.compare_pack_path, False),
        ("Stonebranch graph.json", s.stonebranch_graph_json, True),
        ("JIL graph.json", s.jil_graph_json, True),
        ("Output folder", s.output_path, False),
        ("Mapping JSON", s.mapping_path, True),
    ]
    for label, value, must_exist in rows:
        print_path_status(label, value, must_exist)
    print()
    print(f"  {color_text('Environment:', 'gray')} {color_text(s.env, 'bright_white')}")
    print(f"  {color_text('Include raw values:', 'gray')} {flag_text(s.include_raw_values)}")
    print(f"  {color_text('Deep scan:', 'gray')} {flag_text(s.deep_scan)}")
    print(f"  {color_text('Env-aware Stonebranch:', 'gray')} {flag_text(s.env_aware)}")


def print_summary(summary: dict[str, Any]) -> None:
    print()
    print(color_text("Summary", "bright_cyan", "bold"))
    for key, value in summary.items():
        print(f"  {key}: {value}")


def print_compare_summary(summary: dict[str, Any]) -> None:
    print()
    print(color_text("Summary", "bright_cyan", "bold"))
    for key in COMPARE_SUMMARY_KEYS:
        if key in summary:
            print(f"  {key}: {summary[key]}")


def print_last_files(last_files: list[Path]) -> None:
    print()
    print(color_text("Output files", "bright_cyan", "bold"))
    if not last_files:
        print("  No output files yet.")
    for path in last_files:
        marker = color_text("OK", "bright_green", "bold") if path.exists() else color_text("missing", "bright_red", "bold")
        print(f"  [{marker}] {color_text(str(path), 'bright_white' if path.exists() else 'gray')}")
