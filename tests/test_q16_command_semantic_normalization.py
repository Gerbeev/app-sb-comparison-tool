from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.domain import REL_RUNS_COMMAND
from stonebranch_graph.normalizers import command_hash, normalize_command_semantic, semantic_command_hash
from stonebranch_graph.workflows import compare_direct


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def matched_edge_keys(result) -> set[str]:
    return {edge["key"] for edge in result.comparison.edges["matched"]}


def test_semantic_command_normalization_matches_variable_masks_and_env_tokens() -> None:
    stonebranch = "python load.py --date ${BUSINESS_DATE} --env P1"
    autosys = "python load.py --date $${business_date} --env 0en0"

    assert command_hash(stonebranch) != command_hash(autosys)
    assert normalize_command_semantic(stonebranch) == "python load.py --date <var:business_date> --env <env>"
    assert normalize_command_semantic(stonebranch) == normalize_command_semantic(autosys)
    assert semantic_command_hash(stonebranch) == semantic_command_hash(autosys)


def test_command_edges_match_by_semantic_hash_but_strict_diff_is_reported(tmp_path: Path) -> None:
    sb_root = tmp_path / "stonebranch"
    jil_root = tmp_path / "jil"
    output = tmp_path / "out"

    write_json(
        sb_root / "tasks" / "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS.json",
        {
            "name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS",
            "command": "python load.py --date ${BUSINESS_DATE} --env P1",
        },
    )
    jil_root.mkdir(parents=True)
    (jil_root / "IB_CT_CVA_1109_EN_DAILY_BOX.jil").write_text(
        "\n".join(
            [
                "insert_job: IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS job_type: c",
                "command: python load.py --date $${business_date} --env 0en0",
            ]
        ),
        encoding="utf-8",
    )

    result = compare_direct(
        stonebranch_path=sb_root,
        jil_path=jil_root,
        output_dir=output,
        config=AnalyzerConfig.default(),
        env="PROD",
    )

    command_edges = [edge for edge in matched_edge_keys(result) if f"->{REL_RUNS_COMMAND}->" in edge]
    assert command_edges
    assert result.summary["missing_edges_in_stonebranch"] == 0
    assert result.summary["missing_edges_in_jil"] == 0
    assert result.summary["command_differences"] == 1
    assert result.summary["command_syntax_diff_only"] == 1
    assert result.summary["command_semantic_mismatches"] == 0
    assert result.summary["command_mismatch_count"] == 0

    [difference] = result.comparison.attributes["command_differences"]
    assert difference["status"] == "command_syntax_diff_only"
    assert difference["strict_match"] is False
    assert difference["semantic_match"] is True
    assert difference["stonebranch_command_hash"] != difference["jil_command_hash"]
    assert difference["stonebranch_semantic_command_hash"] == difference["jil_semantic_command_hash"]

    report = (output / "compare" / "report.md").read_text(encoding="utf-8")
    remediation = (output / "compare" / "remediation-plan.md").read_text(encoding="utf-8")
    assert "Command syntax-only differences: **1**" in report
    assert "Review variable/environment/script-path syntax mapping" in remediation


def test_semantic_command_mismatch_still_counts_as_command_mismatch(tmp_path: Path) -> None:
    sb_root = tmp_path / "stonebranch"
    jil_root = tmp_path / "jil"
    output = tmp_path / "out"

    write_json(
        sb_root / "tasks" / "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS.json",
        {"name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS", "command": "python load.py --mode full"},
    )
    jil_root.mkdir(parents=True)
    (jil_root / "IB_CT_CVA_1109_EN_DAILY_BOX.jil").write_text(
        "\n".join(
            [
                "insert_job: IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS job_type: c",
                "command: python load.py --mode delta",
            ]
        ),
        encoding="utf-8",
    )

    result = compare_direct(
        stonebranch_path=sb_root,
        jil_path=jil_root,
        output_dir=output,
        config=AnalyzerConfig.default(),
        env="PROD",
    )

    assert result.summary["command_syntax_diff_only"] == 0
    assert result.summary["command_semantic_mismatches"] == 1
    assert result.summary["command_mismatch_count"] == 1
    [difference] = result.comparison.attributes["command_differences"]
    assert difference["status"] == "command_semantic_mismatch"
    assert difference["semantic_match"] is False


def test_semantic_command_normalization_matches_different_script_base_paths() -> None:
    stonebranch = "/u01/stonebranch/scripts/load_customers.sh --date ${BUSINESS_DATE} --env P1"
    autosys = "/opt/autosys/jobs/bin/load_customers.sh --date $${business_date} --env 0en0"

    assert command_hash(stonebranch) != command_hash(autosys)
    assert normalize_command_semantic(stonebranch) == (
        "<script_path>/load_customers.sh --date <var:business_date> --env <env>"
    )
    assert normalize_command_semantic(stonebranch) == normalize_command_semantic(autosys)
    assert semantic_command_hash(stonebranch) == semantic_command_hash(autosys)


def test_script_path_normalization_is_conservative_for_data_files_and_script_names() -> None:
    data_a = "python load.py --input /autosys/data/customers.csv"
    data_b = "python load.py --input /stonebranch/data/customers.csv"
    script_a = "/opt/autosys/scripts/load_customers.sh --x 1"
    script_b = "/opt/autosys/scripts/validate_customers.sh --x 1"

    assert normalize_command_semantic(data_a) != normalize_command_semantic(data_b)
    assert semantic_command_hash(data_a) != semantic_command_hash(data_b)
    assert semantic_command_hash(script_a) != semantic_command_hash(script_b)


def test_command_edges_match_by_script_basename_but_strict_diff_is_reported(tmp_path: Path) -> None:
    sb_root = tmp_path / "stonebranch"
    jil_root = tmp_path / "jil"
    output = tmp_path / "out"

    write_json(
        sb_root / "tasks" / "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS.json",
        {
            "name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS",
            "command": "/u01/stonebranch/scripts/load_customers.sh --date ${BUSINESS_DATE} --env P1",
        },
    )
    jil_root.mkdir(parents=True)
    (jil_root / "IB_CT_CVA_1109_EN_DAILY_BOX.jil").write_text(
        "\n".join(
            [
                "insert_job: IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS job_type: c",
                "command: /opt/autosys/bin/load_customers.sh --date $${business_date} --env 0en0",
            ]
        ),
        encoding="utf-8",
    )

    result = compare_direct(
        stonebranch_path=sb_root,
        jil_path=jil_root,
        output_dir=output,
        config=AnalyzerConfig.default(),
        env="PROD",
    )

    command_edges = [edge for edge in matched_edge_keys(result) if f"->{REL_RUNS_COMMAND}->" in edge]
    assert command_edges
    assert result.summary["command_syntax_diff_only"] == 1
    assert result.summary["command_semantic_mismatches"] == 0
    assert result.summary["command_mismatch_count"] == 0
    [difference] = result.comparison.attributes["command_differences"]
    assert difference["status"] == "command_syntax_diff_only"
    assert difference["reason"] == "Command differs only by variable syntax, environment token, script path."

    remediation = (output / "compare" / "remediation-plan.md").read_text(encoding="utf-8")
    assert "Review variable/environment/script-path syntax mapping" in remediation


def test_different_script_basenames_remain_semantic_command_mismatch(tmp_path: Path) -> None:
    sb_root = tmp_path / "stonebranch"
    jil_root = tmp_path / "jil"
    output = tmp_path / "out"

    write_json(
        sb_root / "tasks" / "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS.json",
        {"name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS", "command": "/u01/scripts/load_customers.sh --mode full"},
    )
    jil_root.mkdir(parents=True)
    (jil_root / "IB_CT_CVA_1109_EN_DAILY_BOX.jil").write_text(
        "\n".join(
            [
                "insert_job: IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS job_type: c",
                "command: /opt/autosys/bin/validate_customers.sh --mode full",
            ]
        ),
        encoding="utf-8",
    )

    result = compare_direct(
        stonebranch_path=sb_root,
        jil_path=jil_root,
        output_dir=output,
        config=AnalyzerConfig.default(),
        env="PROD",
    )

    assert result.summary["command_syntax_diff_only"] == 0
    assert result.summary["command_semantic_mismatches"] == 1
    assert result.summary["command_mismatch_count"] == 1
