from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .compare import compare_graphs, export_comparison
from .config import AnalyzerConfig, MappingConfig
from .exporters import export_graph_bundle, load_graph_json
from .parsers.autosys_jil import AutosysJilParser
from .parsers.stonebranch_json import StonebranchJsonParser


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stonebranch-graph",
        description="Build and compare dependency graphs from Stonebranch JSON exports and AutoSys JIL files.",
    )
    parser.add_argument("--config", type=Path, default=None, help="Optional analyzer config JSON.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sb = subparsers.add_parser("build-stonebranch", help="Build graph from Stonebranch folder JSON export.")
    sb.add_argument("input", type=Path)
    sb.add_argument("-o", "--output", type=Path, required=True)
    sb.add_argument("--env", default="default")
    sb.add_argument("--env-aware", action="store_true")
    sb.add_argument("--deep-scan", action="store_true")

    jil = subparsers.add_parser("build-jil", help="Build graph from AutoSys JIL files.")
    jil.add_argument("input", type=Path)
    jil.add_argument("-o", "--output", type=Path, required=True)
    jil.add_argument("--env", default="default")

    cmp_cmd = subparsers.add_parser("compare", help="Build and compare Stonebranch JSON graph against AutoSys JIL graph.")
    cmp_cmd.add_argument("--stonebranch", type=Path, required=True)
    cmp_cmd.add_argument("--jil", type=Path, required=True)
    cmp_cmd.add_argument("-o", "--output", type=Path, required=True)
    cmp_cmd.add_argument("--env", default="default")
    cmp_cmd.add_argument("--env-aware", action="store_true")
    cmp_cmd.add_argument("--deep-scan", action="store_true")
    cmp_cmd.add_argument("--mapping", type=Path, default=None)

    cmp_json = subparsers.add_parser("compare-json", help="Compare two existing graph.json files.")
    cmp_json.add_argument("--stonebranch-graph", type=Path, required=True)
    cmp_json.add_argument("--jil-graph", type=Path, required=True)
    cmp_json.add_argument("-o", "--output", type=Path, required=True)
    cmp_json.add_argument("--mapping", type=Path, default=None)

    args = parser.parse_args(argv)
    config = AnalyzerConfig.from_file(args.config)

    try:
        if args.command == "build-stonebranch":
            graph = StonebranchJsonParser(
                config=config,
                env=args.env,
                env_aware=args.env_aware,
                deep_scan=args.deep_scan,
            ).parse(args.input)
            export_graph_bundle(graph, args.output)
            print(f"OK: Stonebranch graph: nodes={len(graph.nodes)} edges={len(graph.edges)}")
            print(f"OK: output={args.output.resolve()}")
            return 0

        if args.command == "build-jil":
            graph = AutosysJilParser(config=config, env=args.env).parse(args.input)
            export_graph_bundle(graph, args.output)
            print(f"OK: JIL graph: nodes={len(graph.nodes)} edges={len(graph.edges)}")
            print(f"OK: output={args.output.resolve()}")
            return 0

        if args.command == "compare":
            sb_graph = StonebranchJsonParser(
                config=config,
                env=args.env,
                env_aware=args.env_aware,
                deep_scan=args.deep_scan,
            ).parse(args.stonebranch)
            jil_graph = AutosysJilParser(config=config, env=args.env).parse(args.jil)
            export_graph_bundle(sb_graph, args.output / "stonebranch")
            export_graph_bundle(jil_graph, args.output / "jil")

            mapping = MappingConfig.from_file(args.mapping, config)
            comparison = compare_graphs(sb_graph, jil_graph, mapping, config)
            export_comparison(comparison, args.output, sb_graph, jil_graph)

            print(f"OK: Stonebranch nodes={len(sb_graph.nodes)} edges={len(sb_graph.edges)}")
            print(f"OK: JIL nodes={len(jil_graph.nodes)} edges={len(jil_graph.edges)}")
            print(f"OK: matched nodes={comparison.summary['matched_nodes']} matched edges={comparison.summary['matched_edges']}")
            print(f"OK: output={args.output.resolve()}")
            return 0

        if args.command == "compare-json":
            sb_graph = load_graph_json(args.stonebranch_graph)
            jil_graph = load_graph_json(args.jil_graph)
            mapping = MappingConfig.from_file(args.mapping, config)
            comparison = compare_graphs(sb_graph, jil_graph, mapping, config)
            export_comparison(comparison, args.output, sb_graph, jil_graph)
            print(f"OK: matched nodes={comparison.summary['matched_nodes']} matched edges={comparison.summary['matched_edges']}")
            print(f"OK: output={args.output.resolve()}")
            return 0

        raise ValueError(f"Unknown command: {args.command}")

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
