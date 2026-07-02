from __future__ import annotations

from pathlib import Path

from .comparison_model import Comparison
from .core import Graph
from .exporters import export_csv_rows, write_json
from .metrics import metric_rows, metrics_to_dict
from .compare_csv_exports import write_command_diff_csv, write_diagnostics_csv, write_edge_diff_csv, write_missing_csvs
from .compare_indexes import write_critical_diff, write_diff_index
from .compare_overlay import write_overlay_mermaid
from .compare_remediation import write_remediation_plan
from .compare_report import append_collision_section, append_command_normalization_section, write_report


def export_comparison(comparison: Comparison, output_dir: Path, stonebranch: Graph, jil: Graph) -> None:
    compare_dir = output_dir / "compare"
    compare_dir.mkdir(parents=True, exist_ok=True)
    write_report(compare_dir / "report.md", comparison)
    write_json(compare_dir / "comparison.json", comparison.to_dict())
    metrics = comparison.summary
    write_json(compare_dir / "metrics.json", metrics)
    export_csv_rows(compare_dir / "metrics.csv", ["metric", "value"], metric_rows(metrics))
    write_missing_csvs(compare_dir, comparison)
    write_edge_diff_csv(compare_dir, comparison)
    write_command_diff_csv(compare_dir, comparison)
    write_diagnostics_csv(compare_dir, comparison)
    write_diff_index(compare_dir, comparison)
    write_critical_diff(compare_dir, comparison)
    write_remediation_plan(compare_dir, comparison)
    write_overlay_mermaid(compare_dir / "overlay-graph.mmd", comparison, stonebranch, jil)
