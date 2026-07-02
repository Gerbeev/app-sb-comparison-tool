from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .artifacts import analysis_pack_files, comparison_files, comparison_pack_files, graph_bundle_files, schema_profile_files
from .compare import Comparison, compare_graphs, export_comparison
from .config import AnalyzerConfig, MappingConfig
from .core import Graph
from .exporters import export_graph_bundle, load_graph_json
from .logging_utils import log_comparison_risks, log_exception, log_graph_warnings, log_info
from .pack import compare_analysis_packs, create_analysis_pack
from .parsers.autosys_jil import AutosysJilParser
from .parsers.stonebranch_json import StonebranchJsonParser
from .schema_profiler import profile_jil, profile_stonebranch


@dataclass(frozen=True)
class GraphWorkflowResult:
    graph: Graph
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
class ProfileWorkflowResult:
    profile_type: str
    output_dir: Path
    summary: dict[str, Any]
    files: list[Path]



def graph_summary(graph: Graph) -> dict[str, Any]:
    return {"nodes": len(graph.nodes), "edges": len(graph.edges)}


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
