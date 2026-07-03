from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .alias import AliasTable
from .compare import Comparison, compare_graphs, export_comparison
from .config import AnalyzerConfig, MappingConfig
from .core import Graph
from .exporters import export_csv_rows, export_graph_bundle, load_graph_json, write_text_file
from .html_graph import export_skeleton_comparison_html, export_skeleton_html_report
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


def graph_bundle_files(output_dir: Path) -> list[Path]:
    return [
        output_dir / "report.md",
        output_dir / "graph.json",
        output_dir / "canonical-graph.json",
        output_dir / "graph.html",
        output_dir / "graph-data.js",
        output_dir / "cytoscape.min.js",
        output_dir / "cytoscape.LICENSE",
        output_dir / "containers.json",
        output_dir / "containers.csv",
        output_dir / "metrics.json",
        output_dir / "objects.csv",
        output_dir / "edges.csv",
        output_dir / "dependency-graph.dot",
    ]


def skeleton_bundle_files(output_dir: Path) -> list[Path]:
    return [
        output_dir / "skeleton.jsonl",
        output_dir / "skeleton-canonical.jsonl",
        output_dir / "skeleton-index.csv",
        output_dir / "skeleton-graph.html",
        output_dir / "skeleton-graph-data.js",
        output_dir / "cytoscape.min.js",
        output_dir / "cytoscape.LICENSE",
    ]


def analysis_pack_files(output_dir: Path) -> list[Path]:
    return [
        output_dir / "README.md",
        output_dir / "pack-manifest.json",
        output_dir / "report.md",
        output_dir / "graph.json",
        output_dir / "canonical-graph.json",
        output_dir / "graph.html",
        output_dir / "graph-data.js",
        output_dir / "cytoscape.min.js",
        output_dir / "cytoscape.LICENSE",
        output_dir / "containers.json",
        output_dir / "containers.csv",
        output_dir / "metrics.json",
        output_dir / "indexes" / "node-index.json",
        output_dir / "graphs" / "README.md",
        output_dir / "reports" / "top-connected.md",
    ]


def comparison_files(output_dir: Path) -> list[Path]:
    compare_dir = output_dir / "compare"
    return [
        compare_dir / "report.md",
        compare_dir / "comparison.json",
        compare_dir / "metrics.json",
        compare_dir / "metrics.csv",
        compare_dir / "edge-diff.csv",
        compare_dir / "command-diff.csv",
        compare_dir / "compare-graph.html",
        compare_dir / "compare-graph-data.js",
        compare_dir / "cytoscape.min.js",
        compare_dir / "cytoscape.LICENSE",
        compare_dir / "missing-in-stonebranch.csv",
        compare_dir / "missing-in-jil.csv",
        compare_dir / "collisions.csv",
        compare_dir / "mapping-diagnostics.csv",
        compare_dir / "diff-index.json",
        compare_dir / "critical-diff.json",
        compare_dir / "remediation-summary.json",
        compare_dir / "remediation-plan.md",
    ]


def comparison_pack_files(output_dir: Path) -> list[Path]:
    return [output_dir / "compare-pack-manifest.json", *comparison_files(output_dir)]


def skeleton_comparison_files(output_dir: Path) -> list[Path]:
    compare_dir = output_dir / "compare-skeleton"
    return [
        output_dir / "stonebranch" / "skeleton.jsonl",
        output_dir / "stonebranch" / "skeleton-canonical.jsonl",
        output_dir / "stonebranch" / "skeleton-index.csv",
        output_dir / "stonebranch" / "skeleton-graph.html",
        output_dir / "stonebranch" / "skeleton-graph-data.js",
        output_dir / "stonebranch" / "cytoscape.min.js",
        output_dir / "stonebranch" / "cytoscape.LICENSE",
        output_dir / "jil" / "skeleton.jsonl",
        output_dir / "jil" / "skeleton-canonical.jsonl",
        output_dir / "jil" / "skeleton-index.csv",
        output_dir / "jil" / "skeleton-graph.html",
        output_dir / "jil" / "skeleton-graph-data.js",
        output_dir / "jil" / "cytoscape.min.js",
        output_dir / "jil" / "cytoscape.LICENSE",
        compare_dir / "skeleton-stonebranch.jsonl",
        compare_dir / "skeleton-jil.jsonl",
        compare_dir / "skeleton-diff.json",
        compare_dir / "skeleton-compare-graph.html",
        compare_dir / "skeleton-compare-graph-data.js",
        compare_dir / "cytoscape.min.js",
        compare_dir / "cytoscape.LICENSE",
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
        export_graph_bundle(graph, output_dir)
        log_graph_warnings(output_dir, graph.warnings, source="stonebranch")
        log_info(output_dir, f"Completed Stonebranch graph build: nodes={len(graph.nodes)} edges={len(graph.edges)}")
        return GraphWorkflowResult(
            graph=graph,
            output_dir=output_dir,
            summary=graph_summary(graph),
            files=graph_bundle_files(output_dir),
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
        export_graph_bundle(graph, output_dir)
        log_graph_warnings(output_dir, graph.warnings, source="jil")
        log_info(output_dir, f"Completed JIL graph build: nodes={len(graph.nodes)} edges={len(graph.edges)}")
        return GraphWorkflowResult(
            graph=graph,
            output_dir=output_dir,
            summary=graph_summary(graph),
            files=graph_bundle_files(output_dir),
        )
    except Exception as exc:
        log_exception(output_dir, "JIL graph build", exc)
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
        )
        log_graph_warnings(output_dir, graph.warnings, source="stonebranch")
        log_info(output_dir, f"Completed Stonebranch analysis pack build: nodes={len(graph.nodes)} edges={len(graph.edges)}")
        return GraphWorkflowResult(
            graph=graph,
            output_dir=output_dir,
            summary=graph_summary(graph),
            files=analysis_pack_files(output_dir),
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
        )
        log_graph_warnings(output_dir, graph.warnings, source="jil")
        log_info(output_dir, f"Completed JIL analysis pack build: nodes={len(graph.nodes)} edges={len(graph.edges)}")
        return GraphWorkflowResult(
            graph=graph,
            output_dir=output_dir,
            summary=graph_summary(graph),
            files=analysis_pack_files(output_dir),
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
        export_graph_bundle(sb_graph, output_dir / "stonebranch")
        export_graph_bundle(jil_graph, output_dir / "jil")
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

        comparison = compare_skeletons(sb_skeleton, jil_skeleton)
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
        metrics_path = output_dir / "compare" / "metrics.json"
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
