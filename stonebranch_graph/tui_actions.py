from __future__ import annotations

from pathlib import Path

from .config import AnalyzerConfig
from .tui_settings import TuiSettings, optional_path
from .workflows import (
    CompareSkeletonResult,
    CompareWorkflowResult,
    GraphWorkflowResult,
    KeysCompareWorkflowResult,
    ProfileWorkflowResult,
    ReconciliationKeysWorkflowResult,
    SkeletonWorkflowResult,
    keys_compare_default_paths,
    profile_jil_schema,
    profile_stonebranch_schema,
)
from .workflows import (
    build_jil_pack as run_build_jil_pack,
)
from .workflows import (
    build_reconciliation_keys as run_build_reconciliation_keys,
)
from .workflows import (
    build_jil_skeleton_workflow as run_build_jil_skeleton,
)
from .workflows import (
    build_stonebranch_pack as run_build_stonebranch_pack,
)
from .workflows import (
    build_stonebranch_skeleton_workflow as run_build_stonebranch_skeleton,
)
from .workflows import (
    compare_direct as run_compare_direct,
)
from .workflows import (
    compare_graph_json as run_compare_graph_json,
)
from .workflows import (
    compare_packs as run_compare_packs,
)
from .workflows import (
    compare_reconciliation_keys as run_compare_reconciliation_keys,
)
from .workflows import (
    compare_skeleton_direct as run_compare_skeleton_direct,
)


def runtime_config(settings: TuiSettings, config: AnalyzerConfig) -> AnalyzerConfig:
    return config.with_runtime_flags(include_raw_values=settings.include_raw_values)


def build_stonebranch_pack(settings: TuiSettings, config: AnalyzerConfig) -> GraphWorkflowResult:
    return run_build_stonebranch_pack(
        Path(settings.stonebranch_path),
        Path(settings.stonebranch_pack_path),
        runtime_config(settings, config),
        env=settings.env,
        env_aware=settings.env_aware,
        deep_scan=settings.deep_scan,
        include_raw_values=settings.include_raw_values,
    )


def build_jil_pack(settings: TuiSettings, config: AnalyzerConfig) -> GraphWorkflowResult:
    return run_build_jil_pack(
        Path(settings.jil_path),
        Path(settings.jil_pack_path),
        runtime_config(settings, config),
        env=settings.env,
        include_raw_values=settings.include_raw_values,
    )


def build_stonebranch_skeleton(settings: TuiSettings, config: AnalyzerConfig) -> SkeletonWorkflowResult:
    return run_build_stonebranch_skeleton(
        Path(settings.stonebranch_path),
        Path(settings.output_path) / "stonebranch-skeleton",
        runtime_config(settings, config),
        alias_path=optional_path(settings.mapping_path),
        env=settings.env,
        env_aware=settings.env_aware,
    )


def build_jil_skeleton(settings: TuiSettings, config: AnalyzerConfig) -> SkeletonWorkflowResult:
    return run_build_jil_skeleton(
        Path(settings.jil_path),
        Path(settings.output_path) / "jil-skeleton",
        runtime_config(settings, config),
        alias_path=optional_path(settings.mapping_path),
        env=settings.env,
    )


def compare_packs(settings: TuiSettings, config: AnalyzerConfig) -> CompareWorkflowResult:
    return run_compare_packs(
        stonebranch_pack=Path(settings.stonebranch_pack_path),
        jil_pack=Path(settings.jil_pack_path),
        output_dir=Path(settings.compare_pack_path),
        config=config,
        mapping_path=optional_path(settings.mapping_path),
    )


def compare_skeleton(settings: TuiSettings, config: AnalyzerConfig) -> CompareSkeletonResult:
    return run_compare_skeleton_direct(
        stonebranch_path=Path(settings.stonebranch_path),
        jil_path=Path(settings.jil_path),
        output_dir=Path(settings.output_path) / "compare-skeleton",
        config=runtime_config(settings, config),
        alias_path=optional_path(settings.mapping_path),
        env=settings.env,
        env_aware=settings.env_aware,
    )


def compare_direct(settings: TuiSettings, config: AnalyzerConfig) -> CompareWorkflowResult:
    return run_compare_direct(
        stonebranch_path=Path(settings.stonebranch_path),
        jil_path=Path(settings.jil_path),
        output_dir=Path(settings.output_path),
        config=runtime_config(settings, config),
        env=settings.env,
        env_aware=settings.env_aware,
        deep_scan=settings.deep_scan,
        mapping_path=optional_path(settings.mapping_path),
        include_raw_values=settings.include_raw_values,
    )


def reconciliation_keys(settings: TuiSettings, config: AnalyzerConfig) -> ReconciliationKeysWorkflowResult:
    return run_build_reconciliation_keys(
        stonebranch_path=Path(settings.stonebranch_path),
        jil_path=Path(settings.jil_path),
        output_dir=Path(settings.reconciliation_keys_path),
        config=runtime_config(settings, config),
        env=settings.env,
        env_aware=settings.env_aware,
        deep_scan=settings.deep_scan,
        include_raw_values=settings.include_raw_values,
        keep_task_monitor_suffix=settings.keep_task_monitor_suffix,
    )


def reconciliation_keys_ready(settings: TuiSettings) -> bool:
    sb_keys_path, jil_keys_path = keys_compare_default_paths(Path(settings.reconciliation_keys_path))
    return sb_keys_path.exists() and jil_keys_path.exists()


def compare_reconciliation_keys(settings: TuiSettings) -> KeysCompareWorkflowResult:
    sb_keys_path, jil_keys_path = keys_compare_default_paths(Path(settings.reconciliation_keys_path))
    return run_compare_reconciliation_keys(
        stonebranch_keys_path=sb_keys_path,
        jil_keys_path=jil_keys_path,
        output_dir=Path(settings.reconciliation_keys_path) / "report",
    )


def compare_graph_json(settings: TuiSettings, config: AnalyzerConfig) -> CompareWorkflowResult:
    return run_compare_graph_json(
        stonebranch_graph_path=Path(settings.stonebranch_graph_json),
        jil_graph_path=Path(settings.jil_graph_json),
        output_dir=Path(settings.output_path),
        config=runtime_config(settings, config),
        mapping_path=optional_path(settings.mapping_path),
    )


def profile_stonebranch(settings: TuiSettings, config: AnalyzerConfig) -> ProfileWorkflowResult:
    return profile_stonebranch_schema(
        Path(settings.stonebranch_path),
        Path(settings.output_path) / "profile-stonebranch",
        runtime_config(settings, config),
    )


def profile_jil(settings: TuiSettings) -> ProfileWorkflowResult:
    return profile_jil_schema(Path(settings.jil_path), Path(settings.output_path) / "profile-jil")
