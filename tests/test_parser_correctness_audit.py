from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import make_node_id
from stonebranch_graph.domain import (
    KIND_CALENDAR,
    KIND_TASK,
    REL_STARTS,
    REL_USES_CALENDAR,
    SOURCE_STONEBRANCH,
)
from stonebranch_graph.parsers.autosys_jil import AutosysJilParser
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_stonebranch_typed_reference_does_not_bind_unique_wrong_kind_name(tmp_path: Path) -> None:
    root = tmp_path / "stonebranch"
    _write_json(root / "calendars" / "JOB_A.json", {"name": "JOB_A", "type": "calendar"})
    _write_json(root / "triggers" / "TRG_JOB_A.json", {"name": "TRG_JOB_A", "taskName": "JOB_A"})

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(root)

    trigger_id = make_node_id(SOURCE_STONEBRANCH, "PROD", "trigger", "TRG_JOB_A")
    calendar_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_CALENDAR, "JOB_A")
    synthetic_task_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, "JOB_A")

    assert graph.nodes[calendar_id].kind == KIND_CALENDAR
    assert graph.nodes[synthetic_task_id].kind == KIND_TASK
    assert graph.nodes[synthetic_task_id].metadata["synthetic"] is True
    assert any(
        edge.source == trigger_id
        and edge.target == synthetic_task_id
        and edge.relation == REL_STARTS
        for edge in graph.edges.values()
    )
    assert not any(
        edge.source == trigger_id and edge.target == calendar_id and edge.relation == REL_STARTS
        for edge in graph.edges.values()
    )
    assert any("expected 'task', but only found 'calendar'" in warning for warning in graph.warnings)


def test_jil_calendar_lists_preserve_quoted_names_with_spaces(tmp_path: Path) -> None:
    jil = tmp_path / "jobs.jil"
    jil.write_text(
        "insert_job: JOB_A\n"
        "job_type: c\n"
        "calendar: \"Business Days\", HOLIDAYS WEEKEND\n",
        encoding="utf-8",
    )

    graph = AutosysJilParser(AnalyzerConfig.default(), env="PROD").parse(jil)

    calendar_names = {node.name for node in graph.nodes.values() if node.kind == KIND_CALENDAR}
    assert "Business Days" in calendar_names
    assert "Business" not in calendar_names
    assert "Days" not in calendar_names
    assert {"HOLIDAYS", "WEEKEND"}.issubset(calendar_names)

    job_id = make_node_id("autosys_jil", "PROD", KIND_TASK, "JOB_A")
    calendar_edges = [edge for edge in graph.edges.values() if edge.source == job_id and edge.relation == REL_USES_CALENDAR]
    assert len(calendar_edges) == 3
