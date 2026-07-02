from __future__ import annotations

import ast
from pathlib import Path

from stonebranch_graph import compare
from stonebranch_graph.compare_engine import compare_graphs
from stonebranch_graph.compare_export import export_comparison
from stonebranch_graph.compare_keys import normalize_key

ROOT = Path(__file__).resolve().parents[1]


R2_MODULES = [
    "comparison_model.py",
    "compare_engine.py",
    "compare_keys.py",
    "compare_payloads.py",
    "compare_diagnostics.py",
    "compare_export.py",
    "compare_report.py",
    "compare_csv_exports.py",
    "compare_indexes.py",
    "compare_remediation.py",
    "compare_overlay.py",
]


def module_functions(relative_path: str) -> set[str]:
    tree = ast.parse((ROOT / "stonebranch_graph" / relative_path).read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def test_compare_public_facade_preserves_core_imports() -> None:
    assert compare.compare_graphs is compare_graphs
    assert compare.export_comparison is export_comparison
    assert compare.normalize_key is normalize_key


def test_compare_module_is_split_into_focused_modules() -> None:
    for module_name in R2_MODULES:
        assert (ROOT / "stonebranch_graph" / module_name).exists()

    assert {"compare_graphs", "build_side_indexes", "build_summary"} <= module_functions("compare_engine.py")
    assert {"comparison_node_key", "comparison_edge_key", "normalize_key"} <= module_functions("compare_keys.py")
    assert {"command_difference_payload", "node_payload", "edge_payload"} <= module_functions("compare_payloads.py")
    assert {"collision_payload", "edge_collision_payload"} <= module_functions("compare_diagnostics.py")
    assert {"write_report", "append_collision_section"} <= module_functions("compare_report.py")
    assert {"write_edge_diff_csv", "write_command_diff_csv"} <= module_functions("compare_csv_exports.py")
    assert {"write_remediation_plan"} <= module_functions("compare_remediation.py")
    assert {"write_overlay_mermaid"} <= module_functions("compare_overlay.py")


def test_compare_facade_contains_no_business_logic_functions() -> None:
    assert module_functions("compare.py") == set()
