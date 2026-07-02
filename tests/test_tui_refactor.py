from __future__ import annotations

import ast
from pathlib import Path


def _module_source(module_path: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / module_path).read_text(encoding="utf-8")


def test_tui_refactor_modules_importable() -> None:
    from stonebranch_graph import tui_actions, tui_prompts, tui_rendering, tui_settings

    assert callable(tui_settings.load_tui_settings)
    assert callable(tui_rendering.print_settings_compact)
    assert callable(tui_prompts.pick_folder_setting)
    assert callable(tui_actions.build_stonebranch_pack)


def test_tui_entrypoint_no_longer_imports_workflows_or_native_dialogs_directly() -> None:
    tree = ast.parse(_module_source("stonebranch_graph/tui.py"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported_from_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    modules = imported_modules | imported_from_modules | imported_from_names

    assert "workflows" not in modules
    assert "native_dialogs" not in modules
    assert "tui_actions" in modules
    assert "tui_prompts" in modules
    assert "tui_rendering" in modules
    assert "tui_settings" in modules
