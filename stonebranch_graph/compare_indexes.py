from __future__ import annotations

from pathlib import Path

from .comparison_model import Comparison
from .domain import PACK_CRITICAL_RELATIONS
from .exporters import write_json

def write_diff_index(compare_dir: Path, comparison: Comparison) -> None:
    diff_index = {
        "missing_in_stonebranch": comparison.nodes.get("missing_in_stonebranch", []),
        "missing_in_jil": comparison.nodes.get("missing_in_jil", []),
        "missing_edges_in_stonebranch": comparison.edges.get("missing_in_stonebranch", []),
        "missing_edges_in_jil": comparison.edges.get("missing_in_jil", []),
        "command_differences": comparison.attributes.get("command_differences", []),
        "condition_differences": comparison.attributes.get("condition_differences", []),
    }
    write_json(compare_dir / "diff-index.json", diff_index)


def write_critical_diff(compare_dir: Path, comparison: Comparison) -> None:
    critical = {
        "missing_critical_edges_in_stonebranch": [
            edge for edge in comparison.edges.get("missing_in_stonebranch", [])
            if edge.get("relation") in PACK_CRITICAL_RELATIONS
        ],
        "missing_critical_edges_in_jil": [
            edge for edge in comparison.edges.get("missing_in_jil", [])
            if edge.get("relation") in PACK_CRITICAL_RELATIONS
        ],
        "missing_objects_in_stonebranch": comparison.nodes.get("missing_in_stonebranch", []),
        "missing_objects_in_jil": comparison.nodes.get("missing_in_jil", []),
        "command_differences": comparison.attributes.get("command_differences", []),
        "condition_differences": comparison.attributes.get("condition_differences", []),
    }
    write_json(compare_dir / "critical-diff.json", critical)
