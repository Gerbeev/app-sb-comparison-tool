from __future__ import annotations

import csv
import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.normalizers import command_normalization_diagnostics
from stonebranch_graph.workflows import compare_direct


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_command_normalization_diagnostics_explain_variables_env_and_script_path() -> None:
    diagnostics = command_normalization_diagnostics(
        "/u01/stonebranch/scripts/load_customers.sh --date ${BUSINESS_DATE} --env P1"
    )

    assert diagnostics["normalization_reasons"] == ["variable_syntax", "environment_token", "script_path"]
    assert diagnostics["variable_names"] == ["business_date"]
    assert diagnostics["env_tokens"] == ["p1"]
    assert diagnostics["script_basenames"] == ["load_customers.sh"]
    assert diagnostics["semantic_preview"] == (
        "<script_path>/load_customers.sh --date <var:business_date> --env <env>"
    )
    assert diagnostics["semantic_preview_truncated"] is False


def test_command_syntax_diff_payload_and_reports_include_normalization_reasons(tmp_path: Path) -> None:
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

    [difference] = result.comparison.attributes["command_differences"]
    assert difference["status"] == "command_syntax_diff_only"
    assert difference["normalization_reasons"] == ["variable_syntax", "environment_token", "script_path"]
    assert difference["variable_names"] == ["business_date"]
    assert difference["env_tokens"] == ["0en0", "p1"]
    assert difference["script_basenames"] == ["load_customers.sh"]
    assert difference["stonebranch_command_normalization"]["semantic_preview"] == (
        "<script_path>/load_customers.sh --date <var:business_date> --env <env>"
    )
    assert difference["jil_command_normalization"]["semantic_preview"] == (
        "<script_path>/load_customers.sh --date <var:business_date> --env <env>"
    )
    assert difference["reason"] == "Command differs only by variable syntax, environment token, script path."

    comparison_json = json.loads((output / "compare" / "comparison.json").read_text(encoding="utf-8"))
    [json_difference] = comparison_json["attributes"]["command_differences"]
    assert json_difference["normalization_reasons"] == ["variable_syntax", "environment_token", "script_path"]

    command_rows = list(csv.DictReader((output / "compare" / "command-diff.csv").open(encoding="utf-8")))
    assert len(command_rows) == 1
    [command_row] = command_rows
    assert command_row["status"] == "command_syntax_diff_only"
    assert command_row["key"] == "PROD:task:load_customers"
    assert command_row["strict_match"] == "false"
    assert command_row["semantic_match"] == "true"
    assert command_row["normalization_reasons"] == "variable_syntax;environment_token;script_path"
    assert command_row["variable_names"] == "business_date"
    assert command_row["env_tokens"] == "0en0;p1"
    assert command_row["script_basenames"] == "load_customers.sh"
    assert command_row["stonebranch_semantic_preview"] == (
        "<script_path>/load_customers.sh --date <var:business_date> --env <env>"
    )
    assert command_row["jil_semantic_preview"] == command_row["stonebranch_semantic_preview"]

    report = (output / "compare" / "report.md").read_text(encoding="utf-8")
    remediation = (output / "compare" / "remediation-plan.md").read_text(encoding="utf-8")
    assert "## Command normalization diagnostics" in report
    assert "variable_syntax, environment_token, script_path" in report
    assert "business_date" in report
    assert "load_customers.sh" in report
    assert "Reasons: variable_syntax, environment_token, script_path." in remediation
