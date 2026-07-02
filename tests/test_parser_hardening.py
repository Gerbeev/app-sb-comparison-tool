from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import make_node_id
from stonebranch_graph.normalizers import condition_hash
from stonebranch_graph.parsers.autosys_jil import AutosysJilParser
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_stonebranch_parser_warns_on_duplicate_and_ambiguous_references(tmp_path: Path) -> None:
    root = tmp_path / "stonebranch"
    write_json(root / "tasks" / "DUP_A.json", {"name": "DUP", "type": "task"})
    write_json(root / "tasks" / "DUP_B.json", {"name": "DUP", "type": "task"})
    write_json(root / "tasks" / "SHARED_TASK.json", {"name": "SHARED", "type": "task"})
    write_json(root / "calendars" / "SHARED_CAL.json", {"name": "SHARED", "type": "calendar"})
    write_json(root / "tasks" / "SOURCE.json", {"name": "SOURCE", "type": "task", "note": "SHARED"})

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD", deep_scan=True).parse(root)

    assert any("Duplicate Stonebranch object id" in warning for warning in graph.warnings)
    assert any("Ambiguous Stonebranch reference 'SHARED'" in warning for warning in graph.warnings)

    synthetic_id = make_node_id("stonebranch", "PROD", "object", "SHARED")
    assert graph.nodes[synthetic_id].metadata["synthetic"] is True


def test_jil_parser_safe_condition_metadata_and_hardening_warnings(tmp_path: Path) -> None:
    jil = tmp_path / "jobs.jil"
    jil.write_text(
        "machine: outside_job\n"
        "insert_job: JOB_A\n"
        "job_type: c\n"
        "condition: custom(EXPR)\n"
        "insert_job: JOB_A\n"
        "job_type: c\n"
        "condition: s(JOB_B)\n",
        encoding="utf-8",
    )

    graph = AutosysJilParser(AnalyzerConfig.default(), env="PROD").parse(jil)

    job_id = make_node_id("autosys_jil", "PROD", "task", "JOB_A")
    metadata = graph.nodes[job_id].metadata
    assert metadata["has_condition"] is True
    assert metadata["condition_hash"]
    assert "condition_raw" not in metadata

    assert any("Ignored JIL attribute outside job block" in warning for warning in graph.warnings)
    assert any("Duplicate JIL job id" in warning for warning in graph.warnings)
    assert any("Could not extract JIL condition dependencies" in warning for warning in graph.warnings)

    condition_edges = [edge for edge in graph.edges.values() if edge.native_relation == "condition_success"]
    assert len(condition_edges) == 1
    assert condition_edges[0].evidence_value == condition_hash("s(JOB_B)")


def test_jil_parser_reads_legacy_windows_encoded_files(tmp_path: Path) -> None:
    jil = tmp_path / "legacy.jil"
    jil.write_bytes("insert_job: JOB_CP1252\njob_type: c\ncommand: echo café\n".encode("cp1252"))

    graph = AutosysJilParser(AnalyzerConfig.default(), env="PROD").parse(jil)

    assert make_node_id("autosys_jil", "PROD", "task", "JOB_CP1252") in graph.nodes
