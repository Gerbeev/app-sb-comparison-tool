from __future__ import annotations

import pytest

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import Edge, Graph, Node, make_edge_id
from stonebranch_graph.domain import KIND_TASK, REL_DEPENDS_ON_SUCCESS, SOURCE_AUTOSYS_JIL, SOURCE_STONEBRANCH
from stonebranch_graph.logging_utils import append_log
from stonebranch_graph.workflows import analysis_pack_files, build_jil_pack, compare_graph_json
from stonebranch_graph.exporters import write_json


def test_workflow_run_log_records_parser_warnings(tmp_path):
    source = tmp_path / "jil"
    source.mkdir()
    (source / "bad.jil").write_text("this is not valid jil\n", encoding="utf-8")
    output = tmp_path / "jil-pack"

    result = build_jil_pack(source, output, AnalyzerConfig.default(), env="PROD")

    log_path = output / "run.log"
    assert result.files == analysis_pack_files(output)
    text = log_path.read_text(encoding="utf-8")
    assert "[INFO] Starting JIL analysis pack build" in text
    assert "[WARNING] jil: Ignored unparsed JIL line" in text
    assert "[INFO] Completed JIL analysis pack build" in text


def test_workflow_run_log_records_errors_before_reraising(tmp_path):
    output = tmp_path / "jil-pack"

    with pytest.raises(FileNotFoundError):
        build_jil_pack(tmp_path / "missing", output, AnalyzerConfig.default(), env="PROD")

    text = (output / "run.log").read_text(encoding="utf-8")
    assert "[ERROR] JIL analysis pack build failed:" in text
    assert "Input path does not exist" in text


def test_compare_run_log_records_graph_warnings_and_comparison_risks(tmp_path):
    sb = Graph(source_system=SOURCE_STONEBRANCH, env="PROD")
    jil = Graph(source_system=SOURCE_AUTOSYS_JIL, env="PROD")
    sb_node = Node(
        id="stonebranch:PROD:task:JOB_A",
        canonical_key="PROD:task:JOB_A",
        source_system=SOURCE_STONEBRANCH,
        env="PROD",
        kind=KIND_TASK,
        name="JOB_A",
    )
    jil_node = Node(
        id="autosys_jil:PROD:task:JOB_A",
        canonical_key="PROD:task:JOB_A",
        source_system=SOURCE_AUTOSYS_JIL,
        env="PROD",
        kind=KIND_TASK,
        name="JOB_A",
    )
    jil_target = Node(
        id="autosys_jil:PROD:task:JOB_B",
        canonical_key="PROD:task:JOB_B",
        source_system=SOURCE_AUTOSYS_JIL,
        env="PROD",
        kind=KIND_TASK,
        name="JOB_B",
    )
    sb.add_node(sb_node)
    jil.add_node(jil_node)
    jil.add_node(jil_target)
    edge = Edge(
        id=make_edge_id(jil_node.id, jil_target.id, REL_DEPENDS_ON_SUCCESS, "condition_success"),
        source=jil_node.id,
        target=jil_target.id,
        relation=REL_DEPENDS_ON_SUCCESS,
        source_system=SOURCE_AUTOSYS_JIL,
    )
    jil.add_edge(edge)
    sb.warnings.append("Stonebranch warning example")
    jil.warnings.append("JIL warning example")

    sb_path = tmp_path / "sb.json"
    jil_path = tmp_path / "jil.json"
    write_json(sb_path, sb.to_dict())
    write_json(jil_path, jil.to_dict())
    output = tmp_path / "compare-out"

    result = compare_graph_json(
        stonebranch_graph_path=sb_path,
        jil_graph_path=jil_path,
        output_dir=output,
        config=AnalyzerConfig.default(),
    )

    assert output / "run.log" not in result.files
    text = (output / "run.log").read_text(encoding="utf-8")
    assert "[WARNING] stonebranch graph.json: Stonebranch warning example" in text
    assert "[WARNING] jil graph.json: JIL warning example" in text
    assert "[WARNING] comparison risk:" in text
    assert "Critical JIL dependency edges are missing in Stonebranch." in text


def test_append_log_is_best_effort_and_single_line(tmp_path):
    append_log(tmp_path / "out", "warning", "line one\nline two")
    text = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert "[WARNING] line one line two" in text
