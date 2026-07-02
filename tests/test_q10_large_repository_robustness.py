from __future__ import annotations

import json
from pathlib import Path

import pytest

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.domain import KIND_TASK, SOURCE_STONEBRANCH
from stonebranch_graph.parsers.autosys_jil import AutosysJilParser
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser
from stonebranch_graph.utils import discover_source_files
from stonebranch_graph.workflows import build_stonebranch_pack


def test_discover_source_files_skips_generated_and_hidden_trees(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "tasks").mkdir(parents=True)
    (root / "tasks" / "JOB_A.json").write_text("{}", encoding="utf-8")
    (root / ".git" / "tasks").mkdir(parents=True)
    (root / ".git" / "tasks" / "SHOULD_NOT_SCAN.json").write_text("{}", encoding="utf-8")
    (root / "out" / "tasks").mkdir(parents=True)
    (root / "out" / "tasks" / "generated.json").write_text("{}", encoding="utf-8")
    (root / "__pycache__").mkdir(parents=True)
    (root / "__pycache__" / "cache.json").write_text("{}", encoding="utf-8")

    files = discover_source_files(root, extensions={".json"})

    assert [file.relative_to(root).as_posix() for file in files] == ["tasks/JOB_A.json"]


def test_stonebranch_parser_supports_top_level_json_arrays(tmp_path: Path) -> None:
    root = tmp_path / "stonebranch"
    tasks = root / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "batch.json").write_text(
        json.dumps([
            {"name": "JOB_A", "agentName": "machine01"},
            {"name": "JOB_B", "predecessorTask": "JOB_A"},
            "not-an-object",
        ]),
        encoding="utf-8",
    )

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(root)

    assert {node.name for node in graph.nodes.values() if node.source_system == SOURCE_STONEBRANCH} >= {"JOB_A", "JOB_B"}
    assert any("batch.json#[2]" in warning for warning in graph.warnings)
    assert any(node.kind == KIND_TASK and node.name == "JOB_A" for node in graph.nodes.values())


def test_stonebranch_empty_json_folder_fails_fast(tmp_path: Path) -> None:
    root = tmp_path / "stonebranch"
    (root / "tasks").mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="No Stonebranch JSON files found"):
        StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(root)


def test_stonebranch_parser_reads_legacy_encoded_json(tmp_path: Path) -> None:
    root = tmp_path / "stonebranch"
    tasks = root / "tasks"
    tasks.mkdir(parents=True)
    payload = json.dumps({"name": "JOB_Á", "agentName": "MACHINE_Á"}, ensure_ascii=False)
    (tasks / "legacy.json").write_text(payload, encoding="cp1252")

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(root)

    assert any(node.name == "JOB_Á" for node in graph.nodes.values())


def test_jil_parser_skips_generated_hidden_trees_and_warns_when_no_active_jobs(tmp_path: Path) -> None:
    root = tmp_path / "autosys"
    root.mkdir()
    (root / "BOX.jil").write_text("delete_job: OLD_JOB\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "ignored.jil").write_text("insert_job: HIDDEN job_type: c\n", encoding="utf-8")
    (root / "out").mkdir()
    (root / "out" / "generated.jil").write_text("insert_job: GENERATED job_type: c\n", encoding="utf-8")

    graph = AutosysJilParser(AnalyzerConfig.default(), env="PROD").parse(root)

    assert graph.nodes == {}
    assert any("delete_job records" in warning for warning in graph.warnings)
    assert any("No active JIL insert_job/update_job records" in warning for warning in graph.warnings)


def test_large_repo_warnings_are_written_to_run_log(tmp_path: Path) -> None:
    root = tmp_path / "stonebranch"
    tasks = root / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "array.json").write_text(json.dumps(["bad-array-item"]), encoding="utf-8")
    output = tmp_path / "pack"

    result = build_stonebranch_pack(root, output, AnalyzerConfig.default(), env="PROD")

    assert result.summary == {"nodes": 0, "edges": 0}
    log_text = (output / "run.log").read_text(encoding="utf-8")
    assert "Skipped non-object item in Stonebranch JSON array" in log_text
    assert "No Stonebranch objects were parsed" in log_text
