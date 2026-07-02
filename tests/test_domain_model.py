from __future__ import annotations

from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import make_node_id
from stonebranch_graph.domain import (
    KIND_AGENT,
    KIND_BOX,
    KIND_CALENDAR,
    KIND_TASK,
    KIND_TRIGGER,
    REL_CONTAINS,
    REL_DEPENDS_ON_SUCCESS,
    REL_RUNS_ON,
    REL_STARTS,
    REL_USES_CALENDAR,
    SOURCE_AUTOSYS_JIL,
    SOURCE_STONEBRANCH,
)
from stonebranch_graph.parsers.autosys_jil import AutosysJilParser
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


def test_domain_constants_preserve_public_graph_values() -> None:
    assert SOURCE_STONEBRANCH == "stonebranch"
    assert SOURCE_AUTOSYS_JIL == "autosys_jil"
    assert KIND_TASK == "task"
    assert KIND_TRIGGER == "trigger"
    assert REL_STARTS == "starts"
    assert REL_DEPENDS_ON_SUCCESS == "depends_on_success"


def test_config_defaults_are_backed_by_domain_constants() -> None:
    config = AnalyzerConfig.default()
    assert config.folder_kind_map["tasks"] == KIND_TASK
    assert config.folder_kind_map["triggers"] == KIND_TRIGGER
    assert config.relation_aliases["starts_task"] == REL_STARTS
    assert config.relation_aliases["condition_success"] == REL_DEPENDS_ON_SUCCESS
    assert config.relation_aliases["machine"] == REL_RUNS_ON


def test_parsers_emit_domain_source_kind_and_relation_values(tmp_path: Path) -> None:
    sb_root = tmp_path / "sb"
    (sb_root / "tasks").mkdir(parents=True)
    (sb_root / "triggers").mkdir(parents=True)
    (sb_root / "tasks" / "TASK_A.json").write_text('{"name":"TASK_A","type":"task"}', encoding="utf-8")
    (sb_root / "triggers" / "TRIGGER_A.json").write_text(
        '{"name":"TRIGGER_A","type":"trigger","taskName":"TASK_A"}',
        encoding="utf-8",
    )

    sb_graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(sb_root)
    task_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, "TASK_A")
    trigger_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TRIGGER, "TRIGGER_A")
    assert sb_graph.source_system == SOURCE_STONEBRANCH
    assert sb_graph.nodes[task_id].kind == KIND_TASK
    assert any(edge.source == trigger_id and edge.target == task_id and edge.relation == REL_STARTS for edge in sb_graph.edges.values())

    jil_file = tmp_path / "jobs.jil"
    jil_file.write_text(
        "\n".join([
            "insert_job: BOX_A",
            "job_type: b",
            "insert_job: JOB_A",
            "job_type: c",
            "box_name: BOX_A",
            "machine: AGENT_A",
            "calendar: CAL_A",
            "condition: s(JOB_B)",
        ]),
        encoding="utf-8",
    )
    jil_graph = AutosysJilParser(AnalyzerConfig.default(), env="PROD").parse(jil_file)
    assert jil_graph.source_system == SOURCE_AUTOSYS_JIL
    assert any(node.kind == KIND_BOX and node.name == "BOX_A" for node in jil_graph.nodes.values())
    assert {REL_CONTAINS, REL_RUNS_ON, REL_USES_CALENDAR, REL_DEPENDS_ON_SUCCESS}.issubset(
        {edge.relation for edge in jil_graph.edges.values()}
    )


def test_domain_module_is_single_source_for_core_literals() -> None:
    domain_text = Path("stonebranch_graph/domain.py").read_text(encoding="utf-8")
    stonebranch_parser = Path("stonebranch_graph/parsers/stonebranch_json.py").read_text(encoding="utf-8")
    jil_parser = Path("stonebranch_graph/parsers/autosys_jil.py").read_text(encoding="utf-8")

    assert 'SOURCE_STONEBRANCH = "stonebranch"' in domain_text
    assert 'SOURCE_AUTOSYS_JIL = "autosys_jil"' in domain_text
    assert 'source_system="stonebranch"' not in stonebranch_parser
    assert 'source_system="autosys_jil"' not in jil_parser
    assert 'Graph(source_system="stonebranch"' not in stonebranch_parser
    assert 'Graph(source_system="autosys_jil"' not in jil_parser
