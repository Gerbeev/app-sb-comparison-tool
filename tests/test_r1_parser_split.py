from __future__ import annotations

import inspect
import importlib
from pathlib import Path

from stonebranch_graph.parsers.autosys_jil import AutosysJilParser
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


AUTOSYS_SPLIT_MODULES = [
    "stonebranch_graph.parsers.autosys_model",
    "stonebranch_graph.parsers.autosys_lexer",
    "stonebranch_graph.parsers.autosys_conditions",
    "stonebranch_graph.parsers.autosys_nodes",
]

STONEBRANCH_SPLIT_MODULES = [
    "stonebranch_graph.parsers.stonebranch_discovery",
    "stonebranch_graph.parsers.stonebranch_relations",
    "stonebranch_graph.parsers.stonebranch_registry",
]


def test_parser_public_imports_are_preserved() -> None:
    assert AutosysJilParser.__name__ == "AutosysJilParser"
    assert StonebranchJsonParser.__name__ == "StonebranchJsonParser"


def test_autosys_parser_logic_is_split_into_focused_modules() -> None:
    for module_name in AUTOSYS_SPLIT_MODULES:
        importlib.import_module(module_name)

    from stonebranch_graph.parsers.autosys_lexer import parse_jil_file
    from stonebranch_graph.parsers.autosys_conditions import parse_condition_refs
    from stonebranch_graph.parsers.autosys_nodes import make_jil_node

    assert callable(parse_jil_file)
    assert callable(parse_condition_refs)
    assert callable(make_jil_node)


def test_stonebranch_parser_logic_is_split_into_focused_modules() -> None:
    for module_name in STONEBRANCH_SPLIT_MODULES:
        importlib.import_module(module_name)

    from stonebranch_graph.parsers.stonebranch_discovery import load_stonebranch_json_files
    from stonebranch_graph.parsers.stonebranch_relations import find_stonebranch_references
    from stonebranch_graph.parsers.stonebranch_registry import resolve_or_create_ref_node

    assert callable(load_stonebranch_json_files)
    assert callable(find_stonebranch_references)
    assert callable(resolve_or_create_ref_node)


def test_parser_entrypoint_files_are_smaller_facades() -> None:
    autosys_lines = Path(inspect.getsourcefile(AutosysJilParser) or "").read_text(encoding="utf-8").splitlines()
    stonebranch_lines = Path(inspect.getsourcefile(StonebranchJsonParser) or "").read_text(encoding="utf-8").splitlines()

    assert len(autosys_lines) < 380
    assert len(stonebranch_lines) < 220


def test_parser_helpers_do_not_reintroduce_large_monoliths() -> None:
    for module_name in AUTOSYS_SPLIT_MODULES + STONEBRANCH_SPLIT_MODULES:
        module = importlib.import_module(module_name)
        module_path = Path(module.__file__ or "")
        line_count = len(module_path.read_text(encoding="utf-8").splitlines())
        assert line_count < 280, f"{module_name} grew into a parser monolith"
