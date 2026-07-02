from __future__ import annotations

from pathlib import Path


def paths_for(output_dir: Path, relative_paths: tuple[str, ...]) -> list[Path]:
    """Return concrete artifact paths rooted at an output directory."""
    return [output_dir / relative_path for relative_path in relative_paths]


GRAPH_BUNDLE_FILE_NAMES = (
    "report.md",
    "graph.json",
    "metrics.json",
    "metrics.csv",
    "objects.csv",
    "edges.csv",
    "dependency-graph.mmd",
    "dependency-graph.dot",
)

ANALYSIS_PACK_FILE_NAMES = (
    "README.md",
    "pack-manifest.json",
    *GRAPH_BUNDLE_FILE_NAMES,
    "indexes/node-index.json",
    "indexes/edge-index.json",
    "indexes/adjacency.json",
    "indexes/reverse-adjacency.json",
    "graphs/full.mmd",
    "graphs/tasks-only.mmd",
    "graphs/triggers-to-tasks.mmd",
    "graphs/dependencies-only.mmd",
    "graphs/runtime.mmd",
    "graphs/calendars.mmd",
    "graphs/variables.mmd",
    "reports/top-connected.md",
    "reports/orphans.md",
    "reports/relation-summary.csv",
    "reports/object-summary.csv",
)

COMPARISON_FILE_NAMES = (
    "compare/report.md",
    "compare/comparison.json",
    "compare/metrics.json",
    "compare/metrics.csv",
    "compare/edge-diff.csv",
    "compare/command-diff.csv",
    "compare/missing-in-stonebranch.csv",
    "compare/missing-in-jil.csv",
    "compare/collisions.csv",
    "compare/mapping-diagnostics.csv",
    "compare/diff-index.json",
    "compare/critical-diff.json",
    "compare/remediation-summary.json",
    "compare/remediation-plan.md",
    "compare/overlay-graph.mmd",
)

COMPARISON_PACK_FILE_NAMES = (
    "compare-pack-manifest.json",
    *COMPARISON_FILE_NAMES,
)

TRIAGE_OUTPUT_FILE_NAMES = (
    "triage-report.md",
    "triage-findings.csv",
    "triage-summary.json",
    "triage-fix-plan.md",
    "triage-fix-plan.csv",
)

SCHEMA_PROFILE_FILE_NAMES = (
    "schema-profile.md",
    "schema-profile.csv",
)


def graph_bundle_files(output_dir: Path) -> list[Path]:
    return paths_for(output_dir, GRAPH_BUNDLE_FILE_NAMES)


def analysis_pack_files(output_dir: Path) -> list[Path]:
    return paths_for(output_dir, ANALYSIS_PACK_FILE_NAMES)


def comparison_files(output_dir: Path) -> list[Path]:
    return paths_for(output_dir, COMPARISON_FILE_NAMES)


def comparison_pack_files(output_dir: Path) -> list[Path]:
    return paths_for(output_dir, COMPARISON_PACK_FILE_NAMES)


def triage_output_files(output_dir: Path) -> list[Path]:
    return paths_for(output_dir, TRIAGE_OUTPUT_FILE_NAMES)


def schema_profile_files(output_dir: Path) -> list[Path]:
    return paths_for(output_dir, SCHEMA_PROFILE_FILE_NAMES)
