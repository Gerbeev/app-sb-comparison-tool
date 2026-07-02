from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import make_node_id
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_trigger_task_name_starts_task_not_trigger(tmp_path: Path) -> None:
    root = tmp_path / "stonebranch"
    write_json(root / "tasks" / "TASK_A.json", {"name": "TASK_A", "type": "task"})
    write_json(
        root / "triggers" / "TRIGGER_A.json",
        {"name": "TRIGGER_A", "type": "trigger", "taskName": "TASK_A"},
    )

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(root)

    trigger_id = make_node_id("stonebranch", "PROD", "trigger", "TRIGGER_A")
    task_id = make_node_id("stonebranch", "PROD", "task", "TASK_A")

    assert graph.nodes[task_id].kind == "task"
    assert graph.nodes[task_id].metadata.get("synthetic") is not True
    assert any(
        edge.source == trigger_id
        and edge.target == task_id
        and edge.relation == "starts"
        and edge.native_relation == "starts_task"
        for edge in graph.edges.values()
    )
    assert not any(node.kind == "trigger" and node.name == "TASK_A" for node in graph.nodes.values())


def test_trigger_task_name_unresolved_reference_creates_synthetic_task(tmp_path: Path) -> None:
    root = tmp_path / "stonebranch"
    write_json(
        root / "triggers" / "TRIGGER_A.json",
        {"name": "TRIGGER_A", "type": "trigger", "taskName": "MISSING_TASK"},
    )

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(root)

    task_id = make_node_id("stonebranch", "PROD", "task", "MISSING_TASK")

    assert graph.nodes[task_id].kind == "task"
    assert graph.nodes[task_id].metadata.get("synthetic") is True
    assert not any(node.kind == "trigger" and node.name == "MISSING_TASK" for node in graph.nodes.values())
