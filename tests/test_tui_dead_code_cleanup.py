from __future__ import annotations

import ast
from pathlib import Path


def _tree() -> ast.Module:
    root = Path(__file__).resolve().parents[1]
    return ast.parse((root / "stonebranch_graph" / "tui.py").read_text(encoding="utf-8"))


def _method_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "TerminalUi":
            names.update(child.name for child in node.body if isinstance(child, ast.FunctionDef))
    return names


def test_obsolete_pre_p15_tui_methods_are_removed() -> None:
    methods = _method_names(_tree())
    for name in {
        "configure_source_paths",
        "configure_env_mapping",
        "validate_paths",
        "runtime_config",
        "print_path_status",
        "flag_text",
        "status",
    }:
        assert name not in methods


def test_obsolete_standalone_menu_renderer_is_removed() -> None:
    root = Path(__file__).resolve().parents[1]
    rendering_source = (root / "stonebranch_graph" / "tui_rendering.py").read_text(encoding="utf-8")
    tui_source = (root / "stonebranch_graph" / "tui.py").read_text(encoding="utf-8")

    assert "def print_menu_with_descriptions" not in rendering_source
    assert "print_menu_with_descriptions" not in tui_source


def test_settings_description_no_longer_mentions_removed_validation_screen() -> None:
    root = Path(__file__).resolve().parents[1]
    rendering_source = (root / "stonebranch_graph" / "tui_rendering.py").read_text(encoding="utf-8")

    assert "parser options, validation, save/load" not in rendering_source
    assert "Open simple setup first" in rendering_source
