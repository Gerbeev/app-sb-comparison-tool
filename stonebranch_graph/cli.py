from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import AnalyzerConfig
from .logging_utils import log_error
from .triage import create_triage_report
from .tui import run_tui
from .workflows import (
    build_jil_graph,
    build_jil_pack,
    build_jil_skeleton_workflow,
    build_reconciliation_keys,
    build_stonebranch_graph,
    build_stonebranch_pack,
    build_stonebranch_skeleton_workflow,
    compare_direct,
    compare_graph_json,
    compare_packs,
    compare_skeleton_direct,
    profile_jil_schema,
    profile_stonebranch_schema,
)


def cli_output_dir(args: argparse.Namespace) -> Path | None:
    output = getattr(args, "output", None)
    if output is not None:
        return output
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stonebranch-graph",
        description="Build and compare dependency graphs from Stonebranch JSON exports and AutoSys JIL files.",
    )
    parser.add_argument("--config", type=Path, default=None, help="Optional analyzer config JSON.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_build_stonebranch_parser(subparsers)
    add_build_jil_parser(subparsers)
    add_build_skeleton_parsers(subparsers)
    add_compare_parser(subparsers)
    add_compare_skeleton_parser(subparsers)
    add_reconciliation_keys_parser(subparsers)
    add_profile_parsers(subparsers)
    add_pack_parsers(subparsers)
    add_existing_graph_compare_parser(subparsers)
    add_triage_parser(subparsers)
    subparsers.add_parser("tui", help="Start terminal UI.")
    subparsers.add_parser("ui", help="Alias for terminal UI.")
    return parser


def add_source_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)


def add_env_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--env", default="default")
    parser.add_argument("--include-raw-values", action="store_true")


def add_stonebranch_options(parser: argparse.ArgumentParser) -> None:
    add_env_options(parser)
    parser.add_argument("--env-aware", action="store_true")
    parser.add_argument("--deep-scan", action="store_true")


def add_skeleton_alias_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--alias", type=Path, default=None)


def add_build_stonebranch_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("build-stonebranch", help="Build graph from Stonebranch folder JSON export.")
    add_source_output(parser)
    add_stonebranch_options(parser)


def add_build_jil_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("build-jil", help="Build graph from AutoSys JIL files.")
    add_source_output(parser)
    add_env_options(parser)


def add_build_skeleton_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    stonebranch = subparsers.add_parser(
        "build-skeleton-stonebranch",
        help="Build a canonical skeleton from Stonebranch JSON exports.",
    )
    add_source_output(stonebranch)
    stonebranch.add_argument("--env", default="default")
    stonebranch.add_argument("--env-aware", action="store_true")
    add_skeleton_alias_option(stonebranch)

    jil = subparsers.add_parser(
        "build-skeleton-jil",
        help="Build a canonical skeleton from AutoSys JIL files.",
    )
    add_source_output(jil)
    jil.add_argument("--env", default="default")
    add_skeleton_alias_option(jil)


def add_compare_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("compare", help="Build and compare Stonebranch JSON graph against AutoSys JIL graph.")
    parser.add_argument("--stonebranch", type=Path, required=True)
    parser.add_argument("--jil", type=Path, required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--env", default="default")
    parser.add_argument("--env-aware", action="store_true")
    parser.add_argument("--deep-scan", action="store_true")
    parser.add_argument("--mapping", type=Path, default=None)
    parser.add_argument("--alias", type=Path, default=None)
    parser.add_argument("--include-raw-values", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--skeleton", dest="skeleton", action="store_true", default=True)
    mode.add_argument("--legacy", dest="skeleton", action="store_false")


def add_compare_skeleton_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "compare-skeleton",
        help="Build and compare Stonebranch and JIL canonical skeletons.",
    )
    parser.add_argument("--stonebranch", type=Path, required=True)
    parser.add_argument("--jil", type=Path, required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--env", default="default")
    parser.add_argument("--env-aware", action="store_true")
    add_skeleton_alias_option(parser)


def add_reconciliation_keys_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "reconciliation-keys",
        help="Build only ids/stonebranch.keys.json and ids/autosys.keys.json for a plain-text/Notepad++ diff.",
    )
    parser.add_argument("--stonebranch", type=Path, required=True)
    parser.add_argument("--jil", type=Path, required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--env", default="default")
    parser.add_argument("--env-aware", action="store_true")
    parser.add_argument("--deep-scan", action="store_true")
    parser.add_argument("--include-raw-values", action="store_true")
    parser.add_argument(
        "--keep-task-monitor-suffix",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Do not fold -tm/-taskmonitor-suffixed objects onto their twin; "
            "keep them as their own separate entries, with the full name "
            "(including -tm), in the key lists. Enabled by default; pass "
            "--no-keep-task-monitor-suffix to fold -tm twins together instead."
        ),
    )


def add_profile_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    stonebranch = subparsers.add_parser("profile-stonebranch", help="Write Stonebranch JSON schema profile without values.")
    add_source_output(stonebranch)
    jil = subparsers.add_parser("profile-jil", help="Write AutoSys JIL schema profile without values.")
    add_source_output(jil)


def add_pack_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    stonebranch = subparsers.add_parser("build-stonebranch-pack", help="Build a full Stonebranch analysis pack folder.")
    add_source_output(stonebranch)
    add_stonebranch_options(stonebranch)

    jil = subparsers.add_parser("build-jil-pack", help="Build a full JIL analysis pack folder.")
    add_source_output(jil)
    add_env_options(jil)

    compare = subparsers.add_parser("compare-packs", help="Compare Stonebranch and JIL analysis pack folders.")
    compare.add_argument("--stonebranch-pack", type=Path, required=True)
    compare.add_argument("--jil-pack", type=Path, required=True)
    compare.add_argument("-o", "--output", type=Path, required=True)
    compare.add_argument("--mapping", type=Path, default=None)


def add_existing_graph_compare_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("compare-json", help="Compare two existing graph.json files.")
    parser.add_argument("--stonebranch-graph", type=Path, required=True)
    parser.add_argument("--jil-graph", type=Path, required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, default=None)


def add_triage_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("triage", help="Create a dry-run triage report from comparison outputs.")
    parser.add_argument("compare_output", type=Path, help="Comparison pack folder or compare/ folder containing json/comparison.json.")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Optional output folder. Defaults to the compare/ folder.")


def run_command(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    handlers = {
        "build-stonebranch": handle_build_stonebranch,
        "build-jil": handle_build_jil,
        "build-skeleton-stonebranch": handle_build_skeleton_stonebranch,
        "build-skeleton-jil": handle_build_skeleton_jil,
        "compare": handle_compare_direct,
        "compare-skeleton": handle_compare_skeleton,
        "reconciliation-keys": handle_reconciliation_keys,
        "profile-stonebranch": handle_profile_stonebranch,
        "profile-jil": handle_profile_jil,
        "build-stonebranch-pack": handle_build_stonebranch_pack,
        "build-jil-pack": handle_build_jil_pack,
        "compare-packs": handle_compare_packs,
        "compare-json": handle_compare_json,
        "triage": handle_triage,
        "tui": handle_tui,
        "ui": handle_tui,
    }
    handler = handlers.get(args.command)
    if handler is None:
        raise ValueError(f"Unknown command: {args.command}")
    return handler(args, config)


def handle_build_stonebranch(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    result = build_stonebranch_graph(
        args.input,
        args.output,
        config,
        env=args.env,
        env_aware=args.env_aware,
        deep_scan=args.deep_scan,
        include_raw_values=args.include_raw_values,
    )
    print(f"OK: Stonebranch graph: nodes={len(result.graph.nodes)} edges={len(result.graph.edges)}")
    print(f"OK: output={args.output.resolve()}")
    return 0


def handle_build_jil(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    result = build_jil_graph(args.input, args.output, config, env=args.env, include_raw_values=args.include_raw_values)
    print(f"OK: JIL graph: nodes={len(result.graph.nodes)} edges={len(result.graph.edges)}")
    print(f"OK: output={args.output.resolve()}")
    return 0


def handle_build_skeleton_stonebranch(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    result = build_stonebranch_skeleton_workflow(
        args.input,
        args.output,
        config,
        alias_path=args.alias,
        env=args.env,
        env_aware=args.env_aware,
    )
    print(
        "OK: Stonebranch skeleton: "
        f"nodes={len(result.skeleton.nodes)} erasures={len(result.skeleton.erasures)}"
    )
    print(f"OK: output={args.output.resolve()}")
    return 0


def handle_build_skeleton_jil(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    result = build_jil_skeleton_workflow(
        args.input,
        args.output,
        config,
        alias_path=args.alias,
        env=args.env,
    )
    print(
        f"OK: JIL skeleton: nodes={len(result.skeleton.nodes)} "
        f"erasures={len(result.skeleton.erasures)}"
    )
    print(f"OK: output={args.output.resolve()}")
    return 0


def handle_compare_direct(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    if args.skeleton:
        print("INFO: compare defaults to the skeleton pipeline. Use --legacy for the old graph comparison.")
        return handle_compare_skeleton(args, config)

    result = compare_direct(
        stonebranch_path=args.stonebranch,
        jil_path=args.jil,
        output_dir=args.output,
        config=config,
        env=args.env,
        env_aware=args.env_aware,
        deep_scan=args.deep_scan,
        mapping_path=args.mapping,
        include_raw_values=args.include_raw_values,
    )
    sb_graph = result.stonebranch_graph
    jil_graph = result.jil_graph
    assert sb_graph is not None and jil_graph is not None
    print(f"OK: Stonebranch nodes={len(sb_graph.nodes)} edges={len(sb_graph.edges)}")
    print(f"OK: JIL nodes={len(jil_graph.nodes)} edges={len(jil_graph.edges)}")
    print(f"OK: matched nodes={result.summary['matched_nodes']} matched edges={result.summary['matched_edges']}")
    print(f"OK: output={args.output.resolve()}")
    return 0


def handle_compare_skeleton(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    result = compare_skeleton_direct(
        stonebranch_path=args.stonebranch,
        jil_path=args.jil,
        output_dir=args.output,
        config=config,
        alias_path=args.alias,
        env=args.env,
        env_aware=args.env_aware,
    )
    topology = result.comparison.summary_by_level["topology"]
    logic = result.comparison.summary_by_level["logic"]
    strict = result.comparison.summary_by_level["strict"]
    print(
        "OK: skeleton topology: "
        f"matched={topology['matched']} changed={topology['changed']} "
        f"only_sb={topology['only_in_stonebranch']} only_jil={topology['only_in_jil']}"
    )
    print(
        "OK: skeleton logic/strict changed: "
        f"logic={logic['changed']} strict={strict['changed']}"
    )
    print(f"OK: output={args.output.resolve()}")
    return 0


def handle_reconciliation_keys(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    result = build_reconciliation_keys(
        stonebranch_path=args.stonebranch,
        jil_path=args.jil,
        output_dir=args.output,
        config=config,
        env=args.env,
        env_aware=args.env_aware,
        deep_scan=args.deep_scan,
        include_raw_values=args.include_raw_values,
        keep_task_monitor_suffix=args.keep_task_monitor_suffix,
    )
    print(f"OK: stonebranch keys={result.summary['stonebranch_keys']} jil keys={result.summary['jil_keys']}")
    if args.keep_task_monitor_suffix:
        print("OK: -tm/-taskmonitor objects kept as separate entries (not folded onto twin)")
    else:
        print("OK: -tm/-taskmonitor objects folded onto their twin (--no-keep-task-monitor-suffix)")
    print(f"OK: output={args.output.resolve()}")
    return 0


def handle_profile_stonebranch(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    profile_stonebranch_schema(args.input, args.output, config)
    print(f"OK: Stonebranch schema profile written to {args.output.resolve()}")
    return 0


def handle_profile_jil(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    profile_jil_schema(args.input, args.output)
    print(f"OK: JIL schema profile written to {args.output.resolve()}")
    return 0


def handle_build_stonebranch_pack(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    result = build_stonebranch_pack(
        args.input,
        args.output,
        config,
        env=args.env,
        env_aware=args.env_aware,
        deep_scan=args.deep_scan,
        include_raw_values=args.include_raw_values,
    )
    print(f"OK: Stonebranch analysis pack: nodes={len(result.graph.nodes)} edges={len(result.graph.edges)}")
    print(f"OK: output={args.output.resolve()}")
    return 0


def handle_build_jil_pack(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    result = build_jil_pack(args.input, args.output, config, env=args.env, include_raw_values=args.include_raw_values)
    print(f"OK: JIL analysis pack: nodes={len(result.graph.nodes)} edges={len(result.graph.edges)}")
    print(f"OK: output={args.output.resolve()}")
    return 0


def handle_compare_packs(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    compare_packs(
        stonebranch_pack=args.stonebranch_pack,
        jil_pack=args.jil_pack,
        output_dir=args.output,
        config=config,
        mapping_path=args.mapping,
    )
    print(f"OK: comparison pack output={args.output.resolve()}")
    return 0


def handle_compare_json(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    result = compare_graph_json(
        stonebranch_graph_path=args.stonebranch_graph,
        jil_graph_path=args.jil_graph,
        output_dir=args.output,
        config=config,
        mapping_path=args.mapping,
    )
    print(f"OK: matched nodes={result.summary['matched_nodes']} matched edges={result.summary['matched_edges']}")
    print(f"OK: output={args.output.resolve()}")
    return 0


def handle_triage(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    result = create_triage_report(args.compare_output, args.output)
    print(f"OK: triage findings={result.summary['finding_count']} high_priority={result.summary['high_priority_count']}")
    print(f"OK: output={result.output_dir.resolve()}")
    return 0


def handle_tui(args: argparse.Namespace, config: AnalyzerConfig) -> int:
    return run_tui()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = AnalyzerConfig.from_file(args.config)
    try:
        return run_command(args, config)
    except Exception as exc:
        output_dir = cli_output_dir(args)
        if output_dir is not None:
            log_error(output_dir, f"CLI {args.command} failed: {exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
