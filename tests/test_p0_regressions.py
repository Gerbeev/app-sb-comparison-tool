from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stonebranch_graph.compare import compare_graphs
from stonebranch_graph.config import AnalyzerConfig, MappingConfig
from stonebranch_graph.core import Graph, Node, make_canonical_key, make_node_id
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser
from stonebranch_graph.tui import TerminalUi


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _node(source_system: str, name: str, attributes_hash: str) -> Node:
    return Node(
        id=make_node_id(source_system, "PROD", "task", name),
        canonical_key=make_canonical_key("PROD", "task", name),
        source_system=source_system,
        env="PROD",
        kind="task",
        name=name,
        native_kind="task",
        attributes_hash=attributes_hash,
    )


def test_p0_trigger_task_name_resolves_to_task(tmp_path: Path) -> None:
    root = tmp_path / "stonebranch"
    _write_json(root / "tasks" / "TASK_A.json", {"name": "TASK_A", "type": "task"})
    _write_json(
        root / "triggers" / "TRIGGER_A.json",
        {"name": "TRIGGER_A", "type": "trigger", "taskName": "TASK_A"},
    )

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(root)

    trigger_id = make_node_id("stonebranch", "PROD", "trigger", "TRIGGER_A")
    task_id = make_node_id("stonebranch", "PROD", "task", "TASK_A")
    assert graph.nodes[task_id].kind == "task"
    assert any(
        edge.source == trigger_id and edge.target == task_id and edge.relation == "starts"
        for edge in graph.edges.values()
    )


def test_p0_attribute_hash_changes_are_reported() -> None:
    config = AnalyzerConfig.default()
    mapping = MappingConfig.empty(config)

    stonebranch = Graph(source_system="stonebranch", env="PROD")
    stonebranch.add_node(_node("stonebranch", "JOB_A", "stonebranch-hash"))

    jil = Graph(source_system="autosys_jil", env="PROD")
    jil.add_node(_node("autosys_jil", "JOB_A", "jil-hash"))

    comparison = compare_graphs(stonebranch, jil, mapping, config)

    assert comparison.summary["changed_attributes"] == 1
    assert comparison.attributes["changed"][0]["stonebranch"]["attributes_hash"] == "stonebranch-hash"
    assert comparison.attributes["changed"][0]["jil"]["attributes_hash"] == "jil-hash"


def test_p0_tui_jil_profile_exposes_real_output_files(tmp_path: Path) -> None:
    jil_dir = tmp_path / "jil"
    jil_dir.mkdir()
    (jil_dir / "jobs.jil").write_text("insert_job: JOB_A\ncommand: echo ok\n", encoding="utf-8")

    output_root = tmp_path / "out"
    ui = TerminalUi()
    ui.settings.jil_path = str(jil_dir)
    ui.settings.output_path = str(output_root)
    ui.success = lambda *args, **kwargs: None  # type: ignore[method-assign]
    ui.pause = lambda *args, **kwargs: None  # type: ignore[method-assign]
    ui.show_last_files = lambda *args, **kwargs: None  # type: ignore[method-assign]

    ui.profile_jil()

    profile_dir = output_root / "profile-jil"
    assert ui.last_files == [profile_dir / "schema-profile.md", profile_dir / "schema-profile.csv"]
    assert all(path.exists() for path in ui.last_files)


def test_p0_docs_match_current_picker_controls() -> None:
    root = Path(__file__).resolve().parents[1]
    docs_text = "\n".join(
        [
            (root / "README.md").read_text(encoding="utf-8"),
            (root / "docs" / "TERMINAL_UI.md").read_text(encoding="utf-8"),
        ]
    )

    for obsolete_fragment in [
        "1-9 open folder/file",
        "1-9  open directory or select file",
        "U go up",
        "U    go up",
        "N/P next/previous page",
        "Path settings use a terminal browser",
        "Folder/file browser",
        "B = open file picker",
        "C = keep current",
        "M = manual input fallback",
        "E = empty",
    ]:
        assert obsolete_fragment not in docs_text

    for current_fragment in [
        "Folder path settings open",
        "opens folder picker",
        "Cancel keeps the current value",
        "1) Open file picker",
        "2) Keep current",
        "3) Manual input fallback",
        "4) Empty",
    ]:
        assert current_fragment in docs_text
