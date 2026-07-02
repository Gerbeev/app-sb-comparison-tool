from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.compare import compare_graphs, normalize_key
from stonebranch_graph.config import AnalyzerConfig, MappingConfig
from stonebranch_graph.core import enterprise_name_parts, make_canonical_key
from stonebranch_graph.domain import KIND_TASK
from stonebranch_graph.parsers.autosys_jil import AutosysJilParser
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


def test_enterprise_name_parts_strip_business_env_prefix_for_canonical_matching() -> None:
    assert enterprise_name_parts("IB_CT_CVA_1109_P1_REAL_JOB") == {
        "prefix": "IB_CT_CVA",
        "business_code": "1109",
        "env_token": "P1",
        "real_name": "REAL_JOB",
    }
    assert make_canonical_key("PROD", KIND_TASK, "IB_CT_CVA_1109_P1_REAL_JOB") == "PROD:task:real_job"
    assert make_canonical_key("PROD", KIND_TASK, "IB_CT_CVA_1109_EN_REAL_JOB") == "PROD:task:real_job"
    assert make_canonical_key("PROD", KIND_TASK, "IB_CT_CVA_1109_0en0_REAL_JOB") == "PROD:task:real_job"
    assert make_canonical_key("PROD", KIND_TASK, "NORMAL_REAL_JOB") == "PROD:task:normal_real_job"


def test_compare_normalize_key_also_handles_existing_prefixed_canonical_keys() -> None:
    config = AnalyzerConfig.default()
    mapping = MappingConfig.empty(config)

    assert (
        normalize_key("PROD:task:IB_CT_CVA_1109_P1_REAL_JOB", mapping)
        == "PROD:task:real_job"
    )
    assert (
        normalize_key("autosys_jil:PROD:task:IB_CT_CVA_1109_0en0_REAL_JOB", mapping)
        == "PROD:task:real_job"
    )


def test_stonebranch_and_jil_prefixed_env_names_match_by_real_job_name(tmp_path: Path) -> None:
    config = AnalyzerConfig.default()

    sb_root = tmp_path / "stonebranch" / "tasks"
    sb_root.mkdir(parents=True)
    (sb_root / "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS.json").write_text(
        json.dumps({"name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS", "command": "echo load"}),
        encoding="utf-8",
    )

    jil_root = tmp_path / "jil"
    jil_root.mkdir()
    (jil_root / "IB_CT_CVA_1109_EN_MAIN_BOX.jil").write_text(
        "\n".join(
            [
                "insert_job: IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS job_type: c",
                "command: echo load",
            ]
        ),
        encoding="utf-8",
    )

    sb_graph = StonebranchJsonParser(config, env="PROD").parse(tmp_path / "stonebranch")
    jil_graph = AutosysJilParser(config, env="PROD").parse(jil_root)

    sb_node = next(node for node in sb_graph.nodes.values() if node.kind == KIND_TASK)
    jil_node = next(node for node in jil_graph.nodes.values() if node.kind == KIND_TASK)

    assert sb_node.name == "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS"
    assert jil_node.name == "IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS"
    assert sb_node.canonical_key == "PROD:task:load_customers"
    assert jil_node.canonical_key == "PROD:task:load_customers"
    assert sb_node.metadata["enterprise_naming"]["env_token"] == "P1"
    assert jil_node.metadata["enterprise_naming"]["env_token"] == "0en0"

    comparison = compare_graphs(sb_graph, jil_graph, MappingConfig.empty(config), config)
    matched_task_pairs = [
        item for item in comparison.nodes["matched"]
        if item["stonebranch"]["kind"] == KIND_TASK and item["jil"]["kind"] == KIND_TASK
    ]
    assert len(matched_task_pairs) == 1
    assert comparison.summary["missing_in_stonebranch"] == 0
    assert comparison.summary["missing_in_jil"] == 0


def test_jil_box_file_env_name_and_inner_0en0_job_name_do_not_block_real_name_matching(tmp_path: Path) -> None:
    config = AnalyzerConfig.default()

    sb_root = tmp_path / "stonebranch" / "tasks"
    sb_root.mkdir(parents=True)
    (sb_root / "IB_CT_CVA_1109_P1_DAILY_LOAD.json").write_text(
        json.dumps({"name": "IB_CT_CVA_1109_P1_DAILY_LOAD"}),
        encoding="utf-8",
    )

    jil_root = tmp_path / "jil"
    jil_root.mkdir()
    # The file name contains EN, while the object name inside contains 0en0.
    (jil_root / "IB_CT_CVA_1109_EN_DAILY_BOX.jil").write_text(
        "\n".join(
            [
                "insert_job: IB_CT_CVA_1109_0en0_DAILY_LOAD job_type: c",
                "box_name: IB_CT_CVA_1109_0en0_DAILY_BOX",
            ]
        ),
        encoding="utf-8",
    )

    sb_graph = StonebranchJsonParser(config, env="PROD").parse(tmp_path / "stonebranch")
    jil_graph = AutosysJilParser(config, env="PROD").parse(jil_root)
    comparison = compare_graphs(sb_graph, jil_graph, MappingConfig.empty(config), config)

    matched_names = {
        item["stonebranch"]["name"]: item["jil"]["name"]
        for item in comparison.nodes["matched"]
    }
    assert matched_names == {
        "IB_CT_CVA_1109_P1_DAILY_LOAD": "IB_CT_CVA_1109_0en0_DAILY_LOAD"
    }
