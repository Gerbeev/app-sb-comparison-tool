from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any

from .compare import compare_graphs, export_comparison
from .config import AnalyzerConfig, MappingConfig
from .exporters import export_graph_bundle, load_graph_json
from .pack import compare_analysis_packs, create_analysis_pack
from .parsers.autosys_jil import AutosysJilParser
from .parsers.stonebranch_json import StonebranchJsonParser
from .schema_profiler import profile_jil, profile_stonebranch


SETTINGS_FILE = Path(".stonebranch-tool-settings.json")


PALETTE = {
    "reset": "0",
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
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
    (
        "1",
        "Build Stonebranch analysis pack",
        "Create a full Stonebranch pack: graph.json, indexes, graph views, metrics, and source-side reports.",
        "PACK",
    ),
    (
        "2",
        "Build JIL analysis pack",
        "Create a full JIL pack: graph.json, indexes, graph views, metrics, and source-side reports.",
        "PACK",
    ),
    (
        "3",
        "Compare analysis packs",
        "Compare Stonebranch/JIL pack folders and produce detailed gaps, critical diffs, and remediation checklist.",
        "MAIN",
    ),
    (
        "4",
        "Settings",
        "Open detailed configuration: paths, pack folders, mapping, environment, parser options, validation, save/load.",
        "SETUP",
    ),
    (
        "5",
        "Other tools",
        "Direct compare, compare graph.json files, schema profiles, and last output file list.",
        "OTHER",
    ),
    (
        "0",
        "Exit",
        "Save settings and close the terminal UI.",
        "EXIT",
    ),
]


OTHER_MENU_ITEMS = [
    (
        "1",
        "Run direct compare: Stonebranch ↔ JIL",
        "Parse both repositories and compare immediately. Good for quick checks; packs are better for iterative analysis.",
        "GRAPH",
    ),
    (
        "2",
        "Compare existing graph.json files",
        "Compare previously generated Stonebranch/JIL graph.json files without reparsing repositories.",
        "GRAPH",
    ),
    (
        "3",
        "Profile Stonebranch schema",
        "Generate a safe structure profile of Stonebranch JSON keys and types without values.",
        "PROFILE",
    ),
    (
        "4",
        "Profile JIL schema",
        "Generate a safe structure profile of JIL job blocks and attributes.",
        "PROFILE",
    ),
    (
        "5",
        "Show last output files",
        "Print the most important files from the last run: manifests, reports, graph.json, metrics, diffs.",
        "SETUP",
    ),
    (
        "0",
        "Back",
        "Return to the main menu.",
        "EXIT",
    ),
]


SETTINGS_MENU_ITEMS = [
    (
        "1",
        "Show current settings",
        "Display all configured paths/options and mark existing/missing paths.",
    ),
    (
        "2",
        "Source repository paths",
        "Set Stonebranch repository folder and JIL folder.",
    ),
    (
        "3",
        "Analysis pack folders",
        "Set output folders for Stonebranch pack, JIL pack, and comparison pack.",
    ),
    (
        "4",
        "Environment and mapping",
        "Set environment name and optional mapping.json path.",
    ),
    (
        "5",
        "Parser and output options",
        "Toggle include raw values, deep scan, and env-aware Stonebranch layout.",
    ),
    (
        "6",
        "Existing graph.json paths",
        "Set Stonebranch/JIL graph.json paths for compare-existing-JSON mode.",
    ),
    (
        "7",
        "Validate paths",
        "Check source paths, graph.json paths, pack folders, and mapping file.",
    ),
    (
        "8",
        "Save settings",
        f"Write settings to {SETTINGS_FILE}.",
    ),
    (
        "9",
        "Load settings",
        f"Reload settings from {SETTINGS_FILE}.",
    ),
    (
        "R",
        "Reset to defaults",
        "Reset settings in memory. Use Save settings afterwards to persist.",
    ),
    (
        "0",
        "Back",
        "Return to the main menu.",
    ),
]


@dataclass
class TuiSettings:
    stonebranch_path: str = ""
    jil_path: str = ""
    stonebranch_graph_json: str = ""
    jil_graph_json: str = ""
    output_path: str = "out"
    stonebranch_pack_path: str = "out/stonebranch-pack"
    jil_pack_path: str = "out/jil-pack"
    compare_pack_path: str = "out/compare-pack"
    env: str = "PROD"
    mapping_path: str = ""
    include_raw_values: bool = False
    deep_scan: bool = False
    env_aware: bool = False


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
    if not codes:
        return text
    return f"\033[{';'.join(codes)}m{text}\033[0m"


def enable_windows_ansi() -> None:
    if os.name == "nt":
        os.system("")


def print_menu_with_descriptions() -> None:
    enable_windows_ansi()
    print()
    print(color_text("╔" + "═" * 86 + "╗", "bright_blue"))
    print(color_text("║ Stonebranch Dependency Tool · Terminal UI · Pack workflow".ljust(87) + "║", "bright_green", "bold"))
    print(color_text("╚" + "═" * 86 + "╝", "bright_blue"))
    print(color_text("Recommended flow: build Stonebranch pack → build JIL pack → compare packs.", "gray"))
    print()
    for number, title, description, tag in MAIN_MENU_ITEMS:
        print_menu_item(number, title, description, tag)
    print(color_text("─" * 88, "bright_blue"))


def print_menu_item(number: str, title: str, description: str, tag: str) -> None:
    number_style, title_style, tag_style = style_for_tag(tag)
    print(f" {color_text(number.rjust(2), *number_style)}) {color_text(title, *title_style)}  {color_text(tag, *tag_style)}")
    print(f"     {color_text(description, 'gray')}")
    print()


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
            self.print_settings_compact()
            self.print_main_menu()
            choice = input(self.color("Select: ", "bright_white", "bold")).strip().upper()
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
                else:
                    self.pause("Unknown option.")
            except KeyboardInterrupt:
                print()
                self.pause("Cancelled.")
            except Exception as exc:
                self.error(str(exc))
                details = input("Show traceback? [y/N]: ").strip().lower()
                if details == "y":
                    traceback.print_exc()
                self.pause()

    def print_main_menu(self) -> None:
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
            choice = input(self.color("Select: ", "bright_white", "bold")).strip().upper()
            try:
                if choice == "1":
                    self.run_compare()
                elif choice == "2":
                    self.compare_json()
                elif choice == "3":
                    self.profile_stonebranch()
                elif choice == "4":
                    self.profile_jil()
                elif choice == "5":
                    self.show_last_files()
                elif choice == "0":
                    return
                else:
                    self.pause("Unknown option.")
            except KeyboardInterrupt:
                print()
                self.pause("Cancelled.")
            except Exception as exc:
                self.error(str(exc))
                details = input("Show traceback? [y/N]: ").strip().lower()
                if details == "y":
                    traceback.print_exc()
                self.pause()

    def settings_menu(self) -> None:
        while True:
            self.clear()
            self.header("Settings")
            self.print_settings_compact()
            print()
            for number, title, description in SETTINGS_MENU_ITEMS:
                print(f" {self.color(number.rjust(2), 'bright_yellow', 'bold')}) {self.color(title, 'bright_yellow', 'bold')}")
                print(f"     {self.color(description, 'gray')}")
                print()
            choice = input(self.color("Select: ", "bright_white", "bold")).strip().upper()

            if choice == "1":
                self.clear()
                self.header("Current settings")
                self.print_settings_detailed()
                self.pause()
            elif choice == "2":
                self.configure_source_paths()
            elif choice == "3":
                self.configure_pack_paths()
            elif choice == "4":
                self.configure_env_mapping()
            elif choice == "5":
                self.configure_parser_options()
            elif choice == "6":
                self.configure_graph_json_paths()
            elif choice == "7":
                self.validate_paths()
                self.pause()
            elif choice == "8":
                self.save_settings()
                self.pause()
            elif choice == "9":
                self.settings = self.load_settings()
                self.success("Settings loaded.")
                self.pause()
            elif choice == "R":
                if self.ask_bool("Reset settings to defaults", False):
                    self.settings = TuiSettings()
                    self.success("Settings reset in memory.")
                    self.pause()
            elif choice == "0":
                return
            else:
                self.pause("Unknown option.")

    def configure_source_paths(self) -> None:
        self.clear()
        self.header("Source repository paths")
        s = self.settings
        print(self.color("Set paths to original source folders.", "gray"))
        print()
        s.stonebranch_path = self.ask_path("Stonebranch PROD/DEV folder", s.stonebranch_path, must_exist=False)
        s.jil_path = self.ask_path("JIL folder", s.jil_path, must_exist=False)
        self.success("Source paths updated.")
        self.pause()

    def configure_pack_paths(self) -> None:
        self.clear()
        self.header("Analysis pack folders")
        s = self.settings
        print(self.color("These are generated folders. They do not have to exist yet.", "gray"))
        print()
        s.stonebranch_pack_path = self.ask("Stonebranch pack output", s.stonebranch_pack_path)
        s.jil_pack_path = self.ask("JIL pack output", s.jil_pack_path)
        s.compare_pack_path = self.ask("Compare pack output", s.compare_pack_path)
        self.success("Pack output folders updated.")
        self.pause()

    def configure_env_mapping(self) -> None:
        self.clear()
        self.header("Environment and mapping")
        s = self.settings
        s.env = self.ask("Environment name", s.env or "PROD")
        s.mapping_path = self.ask_path("Mapping JSON optional", s.mapping_path, must_exist=False)
        self.success("Environment/mapping settings updated.")
        self.pause()

    def configure_parser_options(self) -> None:
        self.clear()
        self.header("Parser and output options")
        s = self.settings
        print(self.color("Include raw values is useful for local debugging when repos do not contain sensitive values.", "gray"))
        print(self.color("Deep scan may find more Stonebranch links but can add false positives.", "gray"))
        print()
        s.include_raw_values = self.ask_bool("Include raw command/script values", s.include_raw_values)
        s.deep_scan = self.ask_bool("Deep scan Stonebranch strings", s.deep_scan)
        s.env_aware = self.ask_bool("Env-aware Stonebranch folder layout", s.env_aware)
        self.success("Parser/output options updated.")
        self.pause()

    def configure_graph_json_paths(self) -> None:
        self.clear()
        self.header("Existing graph.json paths")
        s = self.settings
        print(self.color("Only needed for Other tools → Compare existing graph.json files.", "gray"))
        print()
        s.stonebranch_graph_json = self.ask_path("Stonebranch graph.json", s.stonebranch_graph_json, must_exist=False)
        s.jil_graph_json = self.ask_path("JIL graph.json", s.jil_graph_json, must_exist=False)
        self.success("graph.json paths updated.")
        self.pause()

    def validate_paths(self) -> None:
        self.clear()
        self.header("Validate paths")
        s = self.settings
        checks = [
            ("Stonebranch source", s.stonebranch_path, True),
            ("JIL source", s.jil_path, True),
            ("Stonebranch pack", s.stonebranch_pack_path, False),
            ("JIL pack", s.jil_pack_path, False),
            ("Compare pack", s.compare_pack_path, False),
            ("Stonebranch graph.json", s.stonebranch_graph_json, True),
            ("JIL graph.json", s.jil_graph_json, True),
            ("Mapping JSON", s.mapping_path, True),
        ]
        for label, value, must_exist_when_set in checks:
            self.print_path_status(label, value, must_exist_when_set)

    def build_stonebranch_pack(self) -> None:
        s = self.ensure_settings_for("build-stonebranch-pack")
        runtime_config = self.runtime_config()
        self.status("Parsing Stonebranch and creating analysis pack...")
        graph = StonebranchJsonParser(
            config=runtime_config,
            env=s.env,
            env_aware=s.env_aware,
            deep_scan=s.deep_scan,
        ).parse(Path(s.stonebranch_path))
        out = Path(s.stonebranch_pack_path)
        create_analysis_pack(
            graph=graph,
            output_dir=out,
            pack_type="stonebranch-analysis-pack",
            source_path=Path(s.stonebranch_path),
            env=s.env,
            include_raw_values=s.include_raw_values,
            deep_scan=s.deep_scan,
            env_aware=s.env_aware,
        )
        self.last_summary = {"nodes": len(graph.nodes), "edges": len(graph.edges)}
        self.last_files = [
            out / "README.md",
            out / "pack-manifest.json",
            out / "report.md",
            out / "graph.json",
            out / "metrics.json",
            out / "indexes" / "node-index.json",
            out / "indexes" / "adjacency.json",
            out / "graphs" / "dependencies-only.mmd",
            out / "reports" / "top-connected.md",
            out / "reports" / "orphans.md",
        ]
        self.success(f"Stonebranch analysis pack created: {out.resolve()}")
        self.print_summary(self.last_summary)
        self.show_last_files(pause=False)
        self.pause()

    def build_jil_pack(self) -> None:
        s = self.ensure_settings_for("build-jil-pack")
        runtime_config = self.runtime_config()
        self.status("Parsing JIL and creating analysis pack...")
        graph = AutosysJilParser(config=runtime_config, env=s.env).parse(Path(s.jil_path))
        out = Path(s.jil_pack_path)
        create_analysis_pack(
            graph=graph,
            output_dir=out,
            pack_type="jil-analysis-pack",
            source_path=Path(s.jil_path),
            env=s.env,
            include_raw_values=s.include_raw_values,
        )
        self.last_summary = {"nodes": len(graph.nodes), "edges": len(graph.edges)}
        self.last_files = [
            out / "README.md",
            out / "pack-manifest.json",
            out / "report.md",
            out / "graph.json",
            out / "metrics.json",
            out / "indexes" / "node-index.json",
            out / "indexes" / "adjacency.json",
            out / "graphs" / "dependencies-only.mmd",
            out / "reports" / "top-connected.md",
            out / "reports" / "orphans.md",
        ]
        self.success(f"JIL analysis pack created: {out.resolve()}")
        self.print_summary(self.last_summary)
        self.show_last_files(pause=False)
        self.pause()

    def compare_packs(self) -> None:
        s = self.ensure_settings_for("compare-packs")
        out = Path(s.compare_pack_path)
        mapping = optional_path(s.mapping_path)
        self.status("Comparing analysis packs...")
        compare_analysis_packs(
            stonebranch_pack=Path(s.stonebranch_pack_path),
            jil_pack=Path(s.jil_pack_path),
            output_dir=out,
            config=self.config,
            mapping_path=mapping,
        )
        metrics_path = out / "compare" / "metrics.json"
        self.last_summary = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
        self.last_files = [
            out / "compare-pack-manifest.json",
            out / "compare" / "report.md",
            out / "compare" / "comparison.json",
            out / "compare" / "metrics.json",
            out / "compare" / "edge-diff.csv",
            out / "compare" / "critical-diff.json",
            out / "compare" / "diff-index.json",
            out / "compare" / "remediation-plan.md",
        ]
        self.success(f"Comparison analysis pack created: {out.resolve()}")
        self.print_compare_summary(self.last_summary)
        self.show_last_files(pause=False)
        self.pause()

    def run_compare(self) -> None:
        s = self.ensure_settings_for("direct-compare")
        output = Path(s.output_path)
        config = self.runtime_config()
        mapping = MappingConfig.from_file(optional_path(s.mapping_path), config)

        self.status("Parsing Stonebranch...")
        sb_graph = StonebranchJsonParser(
            config,
            env=s.env,
            env_aware=s.env_aware,
            deep_scan=s.deep_scan,
        ).parse(Path(s.stonebranch_path))

        self.status("Parsing JIL...")
        jil_graph = AutosysJilParser(config, env=s.env).parse(Path(s.jil_path))

        self.status("Writing graph outputs...")
        export_graph_bundle(sb_graph, output / "stonebranch")
        export_graph_bundle(jil_graph, output / "jil")

        self.status("Comparing graphs...")
        comparison = compare_graphs(sb_graph, jil_graph, mapping, config)
        export_comparison(comparison, output, sb_graph, jil_graph)

        self.last_summary = comparison.summary
        self.last_files = [
            output / "compare" / "report.md",
            output / "compare" / "comparison.json",
            output / "compare" / "metrics.json",
            output / "compare" / "edge-diff.csv",
            output / "stonebranch" / "graph.json",
            output / "jil" / "graph.json",
        ]
        self.success("Direct compare completed.")
        self.print_compare_summary(comparison.summary)
        self.show_last_files(pause=False)
        self.pause()

    def compare_json(self) -> None:
        s = self.ensure_settings_for("compare-json")
        output = Path(s.output_path)
        config = self.runtime_config()
        mapping = MappingConfig.from_file(optional_path(s.mapping_path), config)
        sb_graph = load_graph_json(Path(s.stonebranch_graph_json))
        jil_graph = load_graph_json(Path(s.jil_graph_json))
        comparison = compare_graphs(sb_graph, jil_graph, mapping, config)
        export_comparison(comparison, output, sb_graph, jil_graph)
        self.last_summary = comparison.summary
        self.last_files = [
            output / "compare" / "report.md",
            output / "compare" / "comparison.json",
            output / "compare" / "metrics.json",
            output / "compare" / "edge-diff.csv",
        ]
        self.success("Compare existing graph.json completed.")
        self.print_compare_summary(comparison.summary)
        self.show_last_files(pause=False)
        self.pause()

    def profile_stonebranch(self) -> None:
        s = self.ensure_settings_for("profile-stonebranch")
        output = Path(s.output_path) / "profile-stonebranch"
        profile_stonebranch(Path(s.stonebranch_path), output, self.runtime_config())
        self.last_summary = {"profile": "stonebranch"}
        self.last_files = [output / "schema-profile.md"]
        self.success("Stonebranch schema profile completed.")
        self.show_last_files(pause=False)
        self.pause()

    def profile_jil(self) -> None:
        s = self.ensure_settings_for("profile-jil")
        output = Path(s.output_path) / "profile-jil"
        profile_jil(Path(s.jil_path), output)
        self.last_summary = {"profile": "jil"}
        self.last_files = [output / "jil-profile.md"]
        self.success("JIL schema profile completed.")
        self.show_last_files(pause=False)
        self.pause()

    def ensure_settings_for(self, mode: str) -> TuiSettings:
        s = self.settings
        missing: list[str] = []

        if mode in {"build-stonebranch-pack", "direct-compare", "profile-stonebranch"}:
            if not path_exists(s.stonebranch_path):
                missing.append("Stonebranch source path")

        if mode in {"build-jil-pack", "direct-compare", "profile-jil"}:
            if not path_exists(s.jil_path):
                missing.append("JIL source path")

        if mode == "compare-packs":
            if not path_exists(s.stonebranch_pack_path):
                missing.append("Stonebranch analysis pack path")
            elif not (Path(s.stonebranch_pack_path) / "graph.json").exists():
                missing.append("Stonebranch pack graph.json")
            if not path_exists(s.jil_pack_path):
                missing.append("JIL analysis pack path")
            elif not (Path(s.jil_pack_path) / "graph.json").exists():
                missing.append("JIL pack graph.json")

        if mode == "compare-json":
            if not path_exists(s.stonebranch_graph_json):
                missing.append("Stonebranch graph.json")
            if not path_exists(s.jil_graph_json):
                missing.append("JIL graph.json")

        if missing:
            self.warn("Missing required settings: " + ", ".join(missing))
            self.pause("Open Settings to fix these values. Press Enter...")
            self.settings_menu()

        return self.settings

    def runtime_config(self) -> AnalyzerConfig:
        return self.config.with_runtime_flags(include_raw_values=self.settings.include_raw_values)

    def print_settings_compact(self) -> None:
        s = self.settings
        print(self.color("Current settings", "bright_cyan", "bold"))
        print(f"  {self.color('Env:', 'gray')} {self.color(s.env, 'bright_white')}  "
              f"{self.color('Raw:', 'gray')} {self.flag_text(s.include_raw_values)}  "
              f"{self.color('Deep:', 'gray')} {self.flag_text(s.deep_scan)}  "
              f"{self.color('Env-aware:', 'gray')} {self.flag_text(s.env_aware)}")
        print(f"  {self.color('SB pack:', 'gray')} {self.color(s.stonebranch_pack_path, 'bright_white')}")
        print(f"  {self.color('JIL pack:', 'gray')} {self.color(s.jil_pack_path, 'bright_white')}")
        print(f"  {self.color('Compare pack:', 'gray')} {self.color(s.compare_pack_path, 'bright_white')}")

    def print_settings_detailed(self) -> None:
        s = self.settings
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
            self.print_path_status(label, value, must_exist)

        print()
        print(f"  {self.color('Environment:', 'gray')} {self.color(s.env, 'bright_white')}")
        print(f"  {self.color('Include raw values:', 'gray')} {self.flag_text(s.include_raw_values)}")
        print(f"  {self.color('Deep scan:', 'gray')} {self.flag_text(s.deep_scan)}")
        print(f"  {self.color('Env-aware Stonebranch:', 'gray')} {self.flag_text(s.env_aware)}")

    def print_path_status(self, label: str, value: str, must_exist_when_set: bool) -> None:
        if not value:
            print(f"  {self.color(label + ':', 'gray'):<28} {self.color('-', 'gray')}")
            return

        exists = Path(value).exists()
        if exists:
            status = self.color("OK", "bright_green", "bold")
        elif must_exist_when_set:
            status = self.color("missing", "bright_red", "bold")
        else:
            status = self.color("will create", "bright_yellow", "bold")

        print(f"  {self.color(label + ':', 'gray'):<28} {self.color(value, 'bright_white')} [{status}]")

    def print_summary(self, summary: dict[str, Any]) -> None:
        print()
        print(self.color("Summary", "bright_cyan", "bold"))
        for key, value in summary.items():
            print(f"  {key}: {value}")

    def print_compare_summary(self, summary: dict[str, Any]) -> None:
        print()
        print(self.color("Summary", "bright_cyan", "bold"))
        keys = [
            "migration_readiness_score",
            "readiness_grade",
            "matched_nodes",
            "matched_edges",
            "node_match_rate_percent",
            "edge_match_rate_percent",
            "critical_dependency_loss_count",
            "missing_in_stonebranch",
            "missing_in_jil",
        ]
        for key in keys:
            if key in summary:
                print(f"  {key}: {summary[key]}")

    def show_last_files(self, pause: bool = True) -> None:
        print()
        print(self.color("Output files", "bright_cyan", "bold"))
        if not self.last_files:
            print("  No output files yet.")
        for path in self.last_files:
            exists = path.exists()
            marker = self.color("OK", "bright_green", "bold") if exists else self.color("missing", "bright_red", "bold")
            path_text = self.color(str(path), "bright_white" if exists else "gray")
            print(f"  [{marker}] {path_text}")
        if pause:
            self.pause()

    def ask(self, label: str, current: str = "") -> str:
        suffix = f" [{current}]" if current else ""
        value = input(f"{label}{suffix}: ").strip()
        return value or current

    def ask_path(self, label: str, current: str = "", must_exist: bool = False) -> str:
        while True:
            value = self.ask(label, current)
            if not value or not must_exist or Path(value).exists():
                return value
            self.warn(f"Path does not exist: {value}")

    def ask_bool(self, label: str, current: bool) -> bool:
        default = "Y/n" if current else "y/N"
        value = input(f"{label} [{default}]: ").strip().lower()
        if not value:
            return current
        return value in {"y", "yes", "1", "true", "да", "д"}

    def flag_text(self, enabled: bool) -> str:
        return self.color("yes", "bright_green", "bold") if enabled else self.color("no", "gray")

    def load_settings(self) -> TuiSettings:
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                allowed_keys = set(asdict(TuiSettings()).keys())
                return TuiSettings(**{key: value for key, value in data.items() if key in allowed_keys})
            except Exception:
                return TuiSettings()
        return TuiSettings()

    def save_settings(self, silent: bool = False) -> None:
        SETTINGS_FILE.write_text(json.dumps(asdict(self.settings), indent=2, ensure_ascii=False), encoding="utf-8")
        if not silent:
            self.success(f"Settings saved to {SETTINGS_FILE}")

    def header(self, title: str = "Stonebranch Dependency Tool") -> None:
        print(self.color("╔" + "═" * 70 + "╗", "bright_blue"))
        line = f" {title} · Terminal UI · v0.5.1"
        print(self.color("║" + line.ljust(70) + "║", "bright_green", "bold"))
        print(self.color("╚" + "═" * 70 + "╝", "bright_blue"))

    def clear(self) -> None:
        if os.environ.get("TERM") and sys.stdout.isatty():
            os.system("cls" if os.name == "nt" else "clear")

    def pause(self, message: str = "Press Enter to continue...") -> None:
        input(f"\n{message}")

    def status(self, message: str) -> None:
        print(self.color(f"▶ {message}", "bright_cyan", "bold"))

    def success(self, message: str) -> None:
        print(self.color(f"✓ {message}", "bright_green", "bold"))

    def warn(self, message: str) -> None:
        print(self.color(f"⚠ {message}", "bright_yellow", "bold"))

    def error(self, message: str) -> None:
        print(self.color(f"✗ {message}", "bright_red", "bold"))

    def color(self, text: str, *styles: str) -> str:
        return color_text(text, *styles)


def optional_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.exists() else None


def path_exists(value: str) -> bool:
    return bool(value) and Path(value).exists()


def run_tui() -> int:
    enable_windows_ansi()
    return TerminalUi().run()


if __name__ == "__main__":
    raise SystemExit(run_tui())
