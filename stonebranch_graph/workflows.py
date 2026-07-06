from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .alias import AliasTable
from .compare import Comparison, compare_graphs, export_comparison
from .config import AnalyzerConfig, MappingConfig
from .core import Graph, resolve_suffix_patterns
from .exporters import (
    export_csv_rows,
    export_graph_bundle,
    export_reconciliation_keys,
    load_graph_json,
    reconciliation_keys_filename,
    write_text_file,
)
from .domain import SOURCE_AUTOSYS_JIL, SOURCE_STONEBRANCH
from .html_graph import export_skeleton_comparison_html, export_skeleton_html_report
from .keys_compare import (
    KeysComparison,
    compare_keys_files,
    export_keys_comparison_json,
    export_keys_comparison_markdown,
)
from .logging_utils import log_comparison_risks, log_exception, log_graph_warnings, log_info
from .pack import compare_analysis_packs, create_analysis_pack
from .parsers.autosys_jil import AutosysJilParser
from .parsers.stonebranch_json import StonebranchJsonParser
from .schema_profiler import profile_jil, profile_stonebranch
from .skeleton import Skeleton, index_rows
from .skeleton_autosys import build_autosys_skeleton
from .skeleton_compare import (
    SkeletonComparison,
    compare_skeletons,
    export_skeleton_comparison,
    skeleton_metrics,
)
from .skeleton_normalize import erase_plumbing
from .skeleton_stonebranch import build_stonebranch_skeleton


@dataclass(frozen=True)
class GraphWorkflowResult:
    graph: Graph
    output_dir: Path
    summary: dict[str, Any]
    files: list[Path]


@dataclass(frozen=True)
class SkeletonWorkflowResult:
    skeleton: Skeleton
    output_dir: Path
    summary: dict[str, Any]
    files: list[Path]


@dataclass(frozen=True)
class CompareWorkflowResult:
    comparison: Comparison | None
    stonebranch_graph: Graph | None
    jil_graph: Graph | None
    output_dir: Path
    summary: dict[str, Any]
    files: list[Path]


@dataclass(frozen=True)
class CompareSkeletonResult:
    comparison: SkeletonComparison
    stonebranch_skeleton: Skeleton
    jil_skeleton: Skeleton
    output_dir: Path
    summary: dict[str, Any]
    files: list[Path]


@dataclass(frozen=True)
class ProfileWorkflowResult:
    profile_type: str
    output_dir: Path
    summary: dict[str, Any]
    files: list[Path]


@dataclass(frozen=True)
class ReconciliationKeysWorkflowResult:
    stonebranch_graph: Graph
    jil_graph: Graph
    output_dir: Path
    summary: dict[str, Any]
    files: list[Path]


@dataclass(frozen=True)
class KeysCompareWorkflowResult:
    comparison: KeysComparison
    output_dir: Path
    summary: dict[str, Any]
    files: list[Path]


def graph_bundle_files(output_dir: Path, source_system: str | None = None) -> list[Path]:
    files = [
        output_dir / "report.md",
        output_dir / "json" / "graph.json",
        output_dir / "json" / "canonical-graph.json",
        output_dir / "graph.html",
        output_dir / "graph-data.js",
        output_dir / "json" / "graph-data.json",
        output_dir / "cytoscape.min.js",
        output_dir / "json" / "containers.json",
        output_dir / "csv" / "containers.csv",
        output_dir / "json" / "metrics.json",
        output_dir / "csv" / "metrics.csv",
        output_dir / "csv" / "objects.csv",
        output_dir / "csv" / "edges.csv",
    ]
    if source_system:
        files.append(output_dir / "ids" / reconciliation_keys_filename(source_system))
    return files


def skeleton_bundle_files(output_dir: Path) -> list[Path]:
    return [
        output_dir / "skeleton.jsonl",
        output_dir / "skeleton-canonical.jsonl",
        output_dir / "skeleton-index.csv",
        output_dir / "skeleton-graph.html",
        output_dir / "skeleton-graph-data.js",
        output_dir / "skeleton-graph-data.json",
        output_dir / "cytoscape.min.js",
    ]


def analysis_pack_files(output_dir: Path, source_system: str | None = None) -> list[Path]:
    files = [
        output_dir / "README.md",
        output_dir / "json" / "pack-manifest.json",
        output_dir / "report.md",
        output_dir / "json" / "graph.json",
        output_dir / "json" / "canonical-graph.json",
        output_dir / "graph.html",
        output_dir / "graph-data.js",
        output_dir / "json" / "graph-data.json",
        output_dir / "cytoscape.min.js",
        output_dir / "json" / "containers.json",
        output_dir / "csv" / "containers.csv",
        output_dir / "json" / "metrics.json",
        output_dir / "csv" / "metrics.csv",
        output_dir / "csv" / "objects.csv",
        output_dir / "csv" / "edges.csv",
        output_dir / "csv" / "object-summary.csv",
        output_dir / "csv" / "relation-summary.csv",
        output_dir / "indexes" / "node-index.json",
        output_dir / "reports" / "README.md",
        output_dir / "reports" / "top-connected.md",
        output_dir / "reports" / "orphans.md",
    ]
    if source_system:
        files.append(output_dir / "ids" / reconciliation_keys_filename(source_system))
    return files


def comparison_files(output_dir: Path) -> list[Path]:
    compare_dir = output_dir / "compare"
    return [
        compare_dir / "report.md",
        compare_dir / "json" / "comparison.json",
        compare_dir / "json" / "metrics.json",
        compare_dir / "csv" / "metrics.csv",
        compare_dir / "csv" / "edge-diff.csv",
        compare_dir / "csv" / "command-diff.csv",
        compare_dir / "compare-graph.html",
        compare_dir / "compare-graph-data.js",
        compare_dir / "json" / "compare-graph-data.json",
        compare_dir / "cytoscape.min.js",
        compare_dir / "csv" / "missing-in-stonebranch.csv",
        compare_dir / "csv" / "missing-in-jil.csv",
        compare_dir / "csv" / "collisions.csv",
        compare_dir / "csv" / "mapping-diagnostics.csv",
        compare_dir / "json" / "diff-index.json",
        compare_dir / "json" / "critical-diff.json",
        compare_dir / "json" / "remediation-summary.json",
        compare_dir / "remediation-plan.md",
        compare_dir / "json" / "reconciliation.json",
    ]


def comparison_pack_files(output_dir: Path) -> list[Path]:
    return [output_dir / "json" / "compare-pack-manifest.json", *comparison_files(output_dir)]


def skeleton_comparison_files(output_dir: Path) -> list[Path]:
    compare_dir = output_dir / "compare-skeleton"
    return [
        output_dir / "stonebranch" / "skeleton.jsonl",
        output_dir / "stonebranch" / "skeleton-canonical.jsonl",
        output_dir / "stonebranch" / "skeleton-index.csv",
        output_dir / "stonebranch" / "skeleton-graph.html",
        output_dir / "stonebranch" / "skeleton-graph-data.js",
        output_dir / "stonebranch" / "skeleton-graph-data.json",
        output_dir / "stonebranch" / "cytoscape.min.js",
        output_dir / "jil" / "skeleton.jsonl",
        output_dir / "jil" / "skeleton-canonical.jsonl",
        output_dir / "jil" / "skeleton-index.csv",
        output_dir / "jil" / "skeleton-graph.html",
        output_dir / "jil" / "skeleton-graph-data.js",
        output_dir / "jil" / "skeleton-graph-data.json",
        output_dir / "jil" / "cytoscape.min.js",
        compare_dir / "skeleton-stonebranch.jsonl",
        compare_dir / "skeleton-jil.jsonl",
        compare_dir / "skeleton-diff.json",
        compare_dir / "skeleton-compare-graph.html",
        compare_dir / "skeleton-compare-graph-data.js",
        compare_dir / "skeleton-compare-graph-data.json",
        compare_dir / "cytoscape.min.js",
        compare_dir / "skeleton-index.csv",
        compare_dir / "report.md",
        compare_dir / "remediation-plan.md",
        compare_dir / "metrics.json",
        compare_dir / "metrics.csv",
    ]


def schema_profile_files(output_dir: Path) -> list[Path]:
    return [output_dir / "schema-profile.md", output_dir / "schema-profile.csv"]


def graph_summary(graph: Graph) -> dict[str, Any]:
    return {"nodes": len(graph.nodes), "edges": len(graph.edges)}


def skeleton_summary(skeleton: Skeleton) -> dict[str, Any]:
    return {
        "nodes": len(skeleton.nodes),
        "externals": len(skeleton.externals),
        "erasures": len(skeleton.erasures),
        "warnings": len(skeleton.warnings),
    }


def export_skeleton_bundle(skeleton: Skeleton, output_dir: Path) -> None:
    write_text_file(output_dir / "skeleton.jsonl", skeleton.to_jsonl())
    write_text_file(output_dir / "skeleton-canonical.jsonl", skeleton.to_canonical_jsonl("strict"))
    export_csv_rows(
        output_dir / "skeleton-index.csv",
        ["id", "kind", "parent", "topology_hash", "logic_hash", "strict_hash"],
        index_rows(skeleton),
    )
    export_skeleton_html_report(skeleton, output_dir)


def build_stonebranch_graph(
    input_path: Path,
    output_dir: Path,
    config: AnalyzerConfig,
    *,
    env: str = "default",
    env_aware: bool = False,
    deep_scan: bool = False,
    include_raw_values: bool = False,
) -> GraphWorkflowResult:
    log_info(output_dir, f"Starting Stonebranch graph build: input={input_path} env={env}")
    try:
        runtime_config = config.with_runtime_flags(include_raw_values=include_raw_values)
        graph = StonebranchJsonParser(
            runtime_config,
            env=env,
            env_aware=env_aware,
            deep_scan=deep_scan,
        ).parse(input_path)
        export_graph_bundle(graph, output_dir, config=runtime_config)
        log_graph_warnings(output_dir, graph.warnings, source="stonebranch")
        log_info(output_dir, f"Completed Stonebranch graph build: nodes={len(graph.nodes)} edges={len(graph.edges)}")
        return GraphWorkflowResult(
            graph=graph,
            output_dir=output_dir,
            summary=graph_summary(graph),
            files=graph_bundle_files(output_dir, source_system=graph.source_system),
        )
    except Exception as exc:
        log_exception(output_dir, "Stonebranch graph build", exc)
        raise


def build_jil_graph(
    input_path: Path,
    output_dir: Path,
    config: AnalyzerConfig,
    *,
    env: str = "default",
    include_raw_values: bool = False,
) -> GraphWorkflowResult:
    log_info(output_dir, f"Starting JIL graph build: input={input_path} env={env}")
    try:
        runtime_config = config.with_runtime_flags(include_raw_values=include_raw_values)
        graph = AutosysJilParser(runtime_config, env=env).parse(input_path)
        export_graph_bundle(graph, output_dir, config=runtime_config)
        log_graph_warnings(output_dir, graph.warnings, source="jil")
        log_info(output_dir, f"Completed JIL graph build: nodes={len(graph.nodes)} edges={len(graph.edges)}")
        return GraphWorkflowResult(
            graph=graph,
            output_dir=output_dir,
            summary=graph_summary(graph),
            files=graph_bundle_files(output_dir, source_system=graph.source_system),
        )
    except Exception as exc:
        log_exception(output_dir, "JIL graph build", exc)
        raise


def reconciliation_keys_files(output_dir: Path, stonebranch_source: str, jil_source: str) -> list[Path]:
    return [
        output_dir / "ids" / reconciliation_keys_filename(stonebranch_source),
        output_dir / "ids" / reconciliation_keys_filename(jil_source),
    ]


def build_reconciliation_keys(
    *,
    stonebranch_path: Path,
    jil_path: Path,
    output_dir: Path,
    config: AnalyzerConfig,
    env: str = "default",
    env_aware: bool = False,
    deep_scan: bool = False,
    include_raw_values: bool = False,
    keep_task_monitor_suffix: bool = True,
) -> ReconciliationKeysWorkflowResult:
    """Build only the two reconciliation key-list files (no full graph bundle).

    A lightweight sibling of `compare_direct` for the common "just give me
    the two diff-ready files" workflow: parses both sides and writes
    `ids/stonebranch.keys.json` / `ids/autosys.keys.json` under `output_dir`,
    skipping graph.html/containers/metrics/etc. `keep_task_monitor_suffix`
    lets a reviewer keep Task Monitor (`-tm` / `-taskmonitor`) objects as
    their own separate entries instead of folding them onto their twin --
    useful when they're needed to understand the full picture during a
    reconciliation pass. Defaults to True so object names are exported in
    full (including `-tm`) unless a caller explicitly opts into folding twins
    together by passing `keep_task_monitor_suffix=False`.
    """
    log_info(output_dir, f"Starting reconciliation keys only: stonebranch={stonebranch_path} jil={jil_path} env={env}")
    try:
        runtime_config = config.with_runtime_flags(include_raw_values=include_raw_values)
        output_dir.mkdir(parents=True, exist_ok=True)
        sb_graph = StonebranchJsonParser(runtime_config, env=env, env_aware=env_aware, deep_scan=deep_scan).parse(stonebranch_path)
        jil_graph = AutosysJilParser(runtime_config, env=env).parse(jil_path)
        patterns = resolve_suffix_patterns(runtime_config.suffix_strips, keep_task_monitor_suffix=keep_task_monitor_suffix)

        ids_dir = output_dir / "ids"
        sb_path = ids_dir / reconciliation_keys_filename(sb_graph.source_system)
        jil_out_path = ids_dir / reconciliation_keys_filename(jil_graph.source_system)
        sb_ids = export_reconciliation_keys(sb_graph, sb_path, patterns=patterns)
        jil_ids = export_reconciliation_keys(jil_graph, jil_out_path, patterns=patterns)

        log_graph_warnings(output_dir, sb_graph.warnings, source="stonebranch")
        log_graph_warnings(output_dir, jil_graph.warnings, source="jil")
        summary = {
            "stonebranch_nodes": len(sb_graph.nodes),
            "jil_nodes": len(jil_graph.nodes),
            "stonebranch_keys": len(sb_ids),
            "jil_keys": len(jil_ids),
            "keep_task_monitor_suffix": keep_task_monitor_suffix,
        }
        log_info(output_dir, f"Completed reconciliation keys only: stonebranch_keys={len(sb_ids)} jil_keys={len(jil_ids)}")
        return ReconciliationKeysWorkflowResult(
            stonebranch_graph=sb_graph,
            jil_graph=jil_graph,
            output_dir=output_dir,
            summary=summary,
            files=[sb_path, jil_out_path],
        )
    except Exception as exc:
        log_exception(output_dir, "Reconciliation keys only build", exc)
        raise


def keys_compare_default_paths(reconciliation_keys_dir: Path) -> tuple[Path, Path]:
    """Return the conventional `ids/stonebranch.keys.json` / `ids/autosys.keys.json`

    paths under a reconciliation-keys output folder (the folder produced by
    `build_reconciliation_keys`).
    """
    ids_dir = reconciliation_keys_dir / "ids"
    return (
        ids_dir / reconciliation_keys_filename(SOURCE_STONEBRANCH),
        ids_dir / reconciliation_keys_filename(SOURCE_AUTOSYS_JIL),
    )


def keys_compare_files(output_dir: Path) -> list[Path]:
    return [output_dir / "keys-report.md", output_dir / "json" / "keys-comparison.json"]


def compare_reconciliation_keys(
    *,
    stonebranch_keys_path: Path,
    jil_keys_path: Path,
    output_dir: Path,
) -> KeysCompareWorkflowResult:
    """Diff two already-exported `*.keys.json` files and write a Markdown +

    JSON report: overall match statistics plus a breakdown by object type
    (kind), and the full lists of objects present on only one side. A
    lightweight sibling of `build_reconciliation_keys` for the "I already
    have the two key lists, now show me the differences" step -- no
    repository parsing involved, just a set diff over the two flat arrays.
    """
    log_info(output_dir, f"Starting reconciliation keys comparison: stonebranch={stonebranch_keys_path} jil={jil_keys_path}")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        comparison = compare_keys_files(stonebranch_keys_path, jil_keys_path)
        report_path = output_dir / "keys-report.md"
        json_path = output_dir / "json" / "keys-comparison.json"
        export_keys_comparison_markdown(comparison, report_path)
        export_keys_comparison_json(comparison, json_path)
        summary = comparison.summary
        log_info(
            output_dir,
            "Completed reconciliation keys comparison: "
            f"matched={summary['matched_total']} "
            f"only_in_stonebranch={summary['only_in_stonebranch_total']} "
            f"only_in_jil={summary['only_in_jil_total']}",
        )
        return KeysCompareWorkflowResult(
            comparison=comparison,
            output_dir=output_dir,
            summary=summary,
            files=[report_path, json_path],
        )
    except Exception as exc:
        log_exception(output_dir, "Reconciliation keys comparison", exc)
        raise


def build_stonebranch_skeleton_workflow(
    input_path: Path,
    output_dir: Path,
    config: AnalyzerConfig,
    *,
    alias_path: Path | None = None,
    env: str = "default",
    env_aware: bool = False,
) -> SkeletonWorkflowResult:
    log_info(output_dir, f"Starting Stonebranch skeleton build: input={input_path} env={env}")
    try:
        alias = AliasTable.from_file(alias_path)
        raw = StonebranchJsonParser(config, env=env, env_aware=env_aware).parse_raw(input_path)
        skeleton = erase_plumbing(build_stonebranch_skeleton(raw, alias=alias, config=config))
        skeleton.warnings.extend(alias.warnings)
        export_skeleton_bundle(skeleton, output_dir)
        log_graph_warnings(output_dir, skeleton.warnings, source="stonebranch skeleton")
        log_info(
            output_dir,
            f"Completed Stonebranch skeleton build: nodes={len(skeleton.nodes)} "
            f"erasures={len(skeleton.erasures)}",
        )
        return SkeletonWorkflowResult(
            skeleton=skeleton,
            output_dir=output_dir,
            summary=skeleton_summary(skeleton),
            files=skeleton_bundle_files(output_dir),
        )
    except Exception as exc:
        log_exception(output_dir, "Stonebranch skeleton build", exc)
        raise


def build_jil_skeleton_workflow(
    input_path: Path,
    output_dir: Path,
    config: AnalyzerConfig,
    *,
    alias_path: Path | None = None,
    env: str = "default",
) -> SkeletonWorkflowResult:
    log_info(output_dir, f"Starting JIL skeleton build: input={input_path} env={env}")
    try:
        alias = AliasTable.from_file(alias_path)
        raw = AutosysJilParser(config, env=env).parse_raw(input_path)
        skeleton = erase_plumbing(build_autosys_skeleton(raw, alias=alias))
        skeleton.warnings.extend(alias.warnings)
        export_skeleton_bundle(skeleton, output_dir)
        log_graph_warnings(output_dir, skeleton.warnings, source="jil skeleton")
        log_info(
            output_dir,
            f"Completed JIL skeleton build: nodes={len(skeleton.nodes)} "
            f"erasures={len(skeleton.erasures)}",
        )
        return SkeletonWorkflowResult(
            skeleton=skeleton,
            output_dir=output_dir,
            summary=skeleton_summary(skeleton),
            files=skeleton_bundle_files(output_dir),
        )
    except Exception as exc:
        log_exception(output_dir, "JIL skeleton build", exc)
        raise


def build_stonebranch_pack(
    input_path: Path,
    output_dir: Path,
    config: AnalyzerConfig,
    *,
    env: str = "default",
    env_aware: bool = False,
    deep_scan: bool = False,
    include_raw_values: bool = False,
) -> GraphWorkflowResult:
    log_info(output_dir, f"Starting Stonebranch analysis pack build: input={input_path} env={env}")
    try:
        runtime_config = config.with_runtime_flags(include_raw_values=include_raw_values)
        graph = StonebranchJsonParser(
            config=runtime_config,
            env=env,
            env_aware=env_aware,
            deep_scan=deep_scan,
        ).parse(input_path)
        create_analysis_pack(
            graph=graph,
            output_dir=output_dir,
            pack_type="stonebranch-analysis-pack",
            source_path=input_path,
            env=env,
            include_raw_values=include_raw_values,
            deep_scan=deep_scan,
            env_aware=env_aware,
            config=runtime_config,
        )
        log_graph_warnings(output_dir, graph.warnings, source="stonebranch")
        log_info(output_dir, f"Completed Stonebranch analysis pack build: nodes={len(graph.nodes)} edges={len(graph.edges)}")
        return GraphWorkflowResult(
            graph=graph,
            output_dir=output_dir,
            summary=graph_summary(graph),
            files=analysis_pack_files(output_dir, source_system=graph.source_system),
        )
    except Exception as exc:
        log_exception(output_dir, "Stonebranch analysis pack build", exc)
        raise


def build_jil_pack(
    input_path: Path,
    output_dir: Path,
    config: AnalyzerConfig,
    *,
    env: str = "default",
    include_raw_values: bool = False,
) -> GraphWorkflowResult:
    log_info(output_dir, f"Starting JIL analysis pack build: input={input_path} env={env}")
    try:
        runtime_config = config.with_runtime_flags(include_raw_values=include_raw_values)
        graph = AutosysJilParser(config=runtime_config, env=env).parse(input_path)
        create_analysis_pack(
            graph=graph,
            output_dir=output_dir,
            pack_type="jil-analysis-pack",
            source_path=input_path,
            env=env,
            include_raw_values=include_raw_values,
            config=runtime_config,
        )
        log_graph_warnings(output_dir, graph.warnings, source="jil")
        log_info(output_dir, f"Completed JIL analysis pack build: nodes={len(graph.nodes)} edges={len(graph.edges)}")
        return GraphWorkflowResult(
            graph=graph,
            output_dir=output_dir,
            summary=graph_summary(graph),
            files=analysis_pack_files(output_dir, source_system=graph.source_system),
        )
    except Exception as exc:
        log_exception(output_dir, "JIL analysis pack build", exc)
        raise


def compare_direct(
    *,
    stonebranch_path: Path,
    jil_path: Path,
    output_dir: Path,
    config: AnalyzerConfig,
    env: str = "default",
    env_aware: bool = False,
    deep_scan: bool = False,
    mapping_path: Path | None = None,
    include_raw_values: bool = False,
) -> CompareWorkflowResult:
    log_info(output_dir, f"Starting direct comparison: stonebranch={stonebranch_path} jil={jil_path} env={env}")
    try:
        runtime_config = config.with_runtime_flags(include_raw_values=include_raw_values)
        mapping = MappingConfig.from_file(mapping_path, runtime_config)
        sb_graph = StonebranchJsonParser(runtime_config, env=env, env_aware=env_aware, deep_scan=deep_scan).parse(stonebranch_path)
        jil_graph = AutosysJilParser(runtime_config, env=env).parse(jil_path)
        export_graph_bundle(sb_graph, output_dir / "stonebranch", config=runtime_config)
        export_graph_bundle(jil_graph, output_dir / "jil", config=runtime_config)
        comparison = compare_graphs(sb_graph, jil_graph, mapping, runtime_config)
        export_comparison(comparison, output_dir, sb_graph, jil_graph)
        log_graph_warnings(output_dir, sb_graph.warnings, source="stonebranch")
        log_graph_warnings(output_dir, jil_graph.warnings, source="jil")
        log_comparison_risks(output_dir, comparison.risks)
        log_info(output_dir, f"Completed direct comparison: matched_nodes={comparison.summary['matched_nodes']} matched_edges={comparison.summary['matched_edges']}")
        return CompareWorkflowResult(
            comparison=comparison,
            stonebranch_graph=sb_graph,
            jil_graph=jil_graph,
            output_dir=output_dir,
            summary=comparison.summary,
            files=comparison_files(output_dir),
        )
    except Exception as exc:
        log_exception(output_dir, "Direct comparison", exc)
        raise


def compare_skeleton_direct(
    *,
    stonebranch_path: Path,
    jil_path: Path,
    output_dir: Path,
    config: AnalyzerConfig,
    alias_path: Path | None = None,
    env: str = "default",
    env_aware: bool = False,
) -> CompareSkeletonResult:
    log_info(
        output_dir,
        "Starting direct skeleton comparison: "
        f"stonebranch={stonebranch_path} jil={jil_path} env={env}",
    )
    try:
        alias = AliasTable.from_file(alias_path)
        sb_parser = StonebranchJsonParser(config, env=env, env_aware=env_aware)
        jil_parser = AutosysJilParser(config, env=env)
        sb_raw = sb_parser.parse_raw(stonebranch_path)
        jil_raw = jil_parser.parse_raw(jil_path)

        sb_skeleton = erase_plumbing(
            build_stonebranch_skeleton(sb_raw, alias=alias, config=config)
        )
        jil_skeleton = erase_plumbing(build_autosys_skeleton(jil_raw, alias=alias))
        sb_skeleton.warnings.extend(alias.warnings)
        jil_skeleton.warnings.extend(alias.warnings)

        export_skeleton_bundle(sb_skeleton, output_dir / "stonebranch")
        export_skeleton_bundle(jil_skeleton, output_dir / "jil")

        comparison = compare_skeletons(sb_skeleton, jil_skeleton, alias=alias)
        export_skeleton_comparison(comparison, output_dir)
        export_skeleton_comparison_html(
            comparison,
            sb_skeleton,
            jil_skeleton,
            output_dir / "compare-skeleton",
        )
        summary = skeleton_metrics(comparison)

        log_graph_warnings(output_dir, sb_skeleton.warnings, source="stonebranch skeleton")
        log_graph_warnings(output_dir, jil_skeleton.warnings, source="jil skeleton")
        log_comparison_risks(output_dir, comparison.risks)
        log_info(
            output_dir,
            "Completed direct skeleton comparison: "
            f"topology_matched={comparison.summary_by_level['topology']['matched']} "
            f"logic_changed={comparison.summary_by_level['logic']['changed']}",
        )
        return CompareSkeletonResult(
            comparison=comparison,
            stonebranch_skeleton=sb_skeleton,
            jil_skeleton=jil_skeleton,
            output_dir=output_dir,
            summary=summary,
            files=skeleton_comparison_files(output_dir),
        )
    except Exception as exc:
        log_exception(output_dir, "Direct skeleton comparison", exc)
        raise


def compare_graph_json(
    *,
    stonebranch_graph_path: Path,
    jil_graph_path: Path,
    output_dir: Path,
    config: AnalyzerConfig,
    mapping_path: Path | None = None,
) -> CompareWorkflowResult:
    log_info(output_dir, f"Starting graph.json comparison: stonebranch_graph={stonebranch_graph_path} jil_graph={jil_graph_path}")
    try:
        sb_graph = load_graph_json(stonebranch_graph_path)
        jil_graph = load_graph_json(jil_graph_path)
        mapping = MappingConfig.from_file(mapping_path, config)
        comparison = compare_graphs(sb_graph, jil_graph, mapping, config)
        export_comparison(comparison, output_dir, sb_graph, jil_graph)
        log_graph_warnings(output_dir, sb_graph.warnings, source="stonebranch graph.json")
        log_graph_warnings(output_dir, jil_graph.warnings, source="jil graph.json")
        log_comparison_risks(output_dir, comparison.risks)
        log_info(output_dir, f"Completed graph.json comparison: matched_nodes={comparison.summary['matched_nodes']} matched_edges={comparison.summary['matched_edges']}")
        return CompareWorkflowResult(
            comparison=comparison,
            stonebranch_graph=sb_graph,
            jil_graph=jil_graph,
            output_dir=output_dir,
            summary=comparison.summary,
            files=comparison_files(output_dir),
        )
    except Exception as exc:
        log_exception(output_dir, "Graph.json comparison", exc)
        raise

def compare_packs(
    *,
    stonebranch_pack: Path,
    jil_pack: Path,
    output_dir: Path,
    config: AnalyzerConfig,
    mapping_path: Path | None = None,
) -> CompareWorkflowResult:
    log_info(output_dir, f"Starting analysis pack comparison: stonebranch_pack={stonebranch_pack} jil_pack={jil_pack}")
    try:
        compare_analysis_packs(
            stonebranch_pack=stonebranch_pack,
            jil_pack=jil_pack,
            output_dir=output_dir,
            config=config,
            mapping_path=mapping_path,
        )
        metrics_path = output_dir / "compare" / "json" / "metrics.json"
        summary = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
        log_info(output_dir, "Completed analysis pack comparison")
        return CompareWorkflowResult(
            comparison=None,
            stonebranch_graph=None,
            jil_graph=None,
            output_dir=output_dir,
            summary=summary,
            files=comparison_pack_files(output_dir),
        )
    except Exception as exc:
        log_exception(output_dir, "Analysis pack comparison", exc)
        raise

def profile_stonebranch_schema(
    input_path: Path,
    output_dir: Path,
    config: AnalyzerConfig,
) -> ProfileWorkflowResult:
    log_info(output_dir, f"Starting Stonebranch schema profile: input={input_path}")
    try:
        profile_stonebranch(input_path, output_dir, config)
        log_info(output_dir, "Completed Stonebranch schema profile")
        return ProfileWorkflowResult(
            profile_type="stonebranch",
            output_dir=output_dir,
            summary={"profile": "stonebranch"},
            files=schema_profile_files(output_dir),
        )
    except Exception as exc:
        log_exception(output_dir, "Stonebranch schema profile", exc)
        raise


def profile_jil_schema(input_path: Path, output_dir: Path) -> ProfileWorkflowResult:
    log_info(output_dir, f"Starting JIL schema profile: input={input_path}")
    try:
        profile_jil(input_path, output_dir)
        log_info(output_dir, "Completed JIL schema profile")
        return ProfileWorkflowResult(
            profile_type="jil",
            output_dir=output_dir,
            summary={"profile": "jil"},
            files=schema_profile_files(output_dir),
        )
    except Exception as exc:
        log_exception(output_dir, "JIL schema profile", exc)
        raise
