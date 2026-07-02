from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import make_node_id
from stonebranch_graph.domain import (
    KIND_AGENT,
    KIND_CALENDAR,
    KIND_COMMAND,
    KIND_TASK,
    KIND_VARIABLE,
    REL_DEPENDS_ON_DONE,
    REL_DEPENDS_ON_FAILURE,
    REL_DEPENDS_ON_NOTRUNNING,
    REL_DEPENDS_ON_SUCCESS,
    REL_DEPENDS_ON_TERMINATED,
    REL_RUNS_COMMAND,
    REL_RUNS_ON,
    REL_USES_CALENDAR,
    REL_USES_VARIABLE,
    SOURCE_AUTOSYS_JIL,
    SOURCE_STONEBRANCH,
)
from stonebranch_graph.normalizers import condition_hash
from stonebranch_graph.parsers.autosys_jil import AutosysJilParser
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_stonebranch_parser_contract_for_env_runtime_calendar_variable_and_command_edges(tmp_path: Path) -> None:
    export_root = tmp_path / "export"
    prod = export_root / "PROD"
    _write_json(
        prod / "tasks" / "JOB_A.json",
        {
            "name": "JOB_A",
            "agentName": "AGENT_1",
            "calendarName": "CAL_MAIN",
            "command": "echo {{GLOBAL_VAR}} --token should-not-be-raw",
        },
    )
    _write_json(prod / "agents" / "AGENT_1.json", {"agentName": "AGENT_1"})
    _write_json(prod / "calendars" / "CAL_MAIN.json", {"calendarName": "CAL_MAIN"})
    _write_json(prod / "variables" / "GLOBAL_VAR.json", {"variableName": "GLOBAL_VAR", "value": "x"})

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="DEFAULT", env_aware=True).parse(export_root)

    job_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, "JOB_A")
    assert graph.nodes[job_id].env == "PROD"
    outgoing = [edge for edge in graph.edges.values() if edge.source == job_id]
    targets = {(edge.relation, graph.nodes[edge.target].kind, graph.nodes[edge.target].name) for edge in outgoing}

    assert (REL_RUNS_ON, KIND_AGENT, "AGENT_1") in targets
    assert (REL_USES_CALENDAR, KIND_CALENDAR, "CAL_MAIN") in targets
    assert (REL_USES_VARIABLE, KIND_VARIABLE, "GLOBAL_VAR") in targets
    assert any(edge.relation == REL_RUNS_COMMAND and graph.nodes[edge.target].kind == KIND_COMMAND for edge in outgoing)
    assert all("should-not-be-raw" not in edge.evidence_value for edge in outgoing)


def test_jil_parser_contract_for_condition_event_variants_and_safe_evidence(tmp_path: Path) -> None:
    jil = tmp_path / "jobs.jil"
    raw_condition = "s(PARENT) & d(DONE_JOB) | f(FAIL_JOB) & t(TERM_JOB) & n(NOT_JOB)"
    jil.write_text(
        "\n".join(
            [
                "insert_job: CHILD",
                "job_type: c",
                f"condition: {raw_condition}",
            ]
        ),
        encoding="utf-8",
    )

    graph = AutosysJilParser(AnalyzerConfig.default()).parse(jil)

    child_id = make_node_id(SOURCE_AUTOSYS_JIL, "default", KIND_TASK, "CHILD")
    child = graph.nodes[child_id]
    assert child.metadata["condition_hash"] == condition_hash(raw_condition)
    assert "condition_raw" not in child.metadata

    outgoing = [edge for edge in graph.edges.values() if edge.source == child_id]
    relations = {edge.relation for edge in outgoing}
    assert {
        REL_DEPENDS_ON_SUCCESS,
        REL_DEPENDS_ON_DONE,
        REL_DEPENDS_ON_FAILURE,
        REL_DEPENDS_ON_TERMINATED,
        REL_DEPENDS_ON_NOTRUNNING,
    }.issubset(relations)
    assert all(edge.evidence_value == condition_hash(raw_condition) for edge in outgoing)
    assert all(raw_condition not in edge.evidence_value for edge in outgoing)


def test_jil_parser_contract_for_raw_condition_only_when_explicitly_enabled(tmp_path: Path) -> None:
    jil = tmp_path / "jobs.jil"
    raw_condition = "s(PARENT)"
    jil.write_text(f"insert_job: CHILD\njob_type: c\ncondition: {raw_condition}\n", encoding="utf-8")

    raw_config = AnalyzerConfig.default().with_runtime_flags(include_raw_values=True)
    graph = AutosysJilParser(raw_config).parse(jil)

    child_id = make_node_id(SOURCE_AUTOSYS_JIL, "default", KIND_TASK, "CHILD")
    assert graph.nodes[child_id].metadata["condition_raw"] == raw_condition
    condition_edges = [edge for edge in graph.edges.values() if edge.source == child_id]
    assert condition_edges
    assert all(edge.evidence_value == raw_condition for edge in condition_edges)
