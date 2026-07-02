from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def function_length(module_path: str, function_name: str) -> int:
    source = (ROOT / module_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return (node.end_lineno or node.lineno) - node.lineno + 1
    raise AssertionError(f"Function {function_name} not found in {module_path}")


def function_names(module_path: str) -> set[str]:
    source = (ROOT / module_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def test_cli_main_is_a_thin_parser_and_dispatch_wrapper() -> None:
    assert function_length("stonebranch_graph/cli.py", "main") <= 15
    assert {"build_parser", "run_command", "handle_compare_direct", "handle_build_stonebranch_pack"} <= function_names("stonebranch_graph/cli.py")


def test_compare_graphs_is_split_into_index_payload_and_summary_helpers() -> None:
    assert function_length("stonebranch_graph/compare_engine.py", "compare_graphs") <= 35
    assert {
        "build_side_indexes",
        "compare_matched_attributes",
        "build_node_diff_payloads",
        "build_edge_diff_payloads",
        "build_diagnostics",
        "build_summary",
    } <= function_names("stonebranch_graph/compare_engine.py")


def test_compare_module_is_a_compatibility_facade_after_r2_split() -> None:
    assert function_names("stonebranch_graph/compare.py") == set()


def test_export_report_is_split_into_report_section_helpers() -> None:
    assert function_length("stonebranch_graph/exporters.py", "export_report") <= 25
    assert {
        "append_report_summary",
        "append_quality_metrics",
        "append_capped_graph_note",
        "append_count_table",
        "append_warnings",
        "append_most_connected",
    } <= function_names("stonebranch_graph/exporters.py")
