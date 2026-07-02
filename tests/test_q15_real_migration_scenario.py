from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.domain import (
    REL_CONTAINS,
    REL_DEPENDS_ON_SUCCESS,
    REL_RUNS_COMMAND,
    REL_RUNS_ON,
    REL_USES_CALENDAR,
    REL_WATCHES_FILE,
)
from stonebranch_graph.workflows import compare_direct


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def comparison_edge_keys(result) -> set[str]:
    return {edge["key"] for edge in result.comparison.edges["matched"]}


def comparison_node_keys(result) -> set[str]:
    return {node["key"] for node in result.comparison.nodes["matched"]}


def test_real_migration_fixture_matches_stonebranch_p1_to_autosys_en_0en0(tmp_path: Path) -> None:
    sb_root = tmp_path / "stonebranch"
    jil_root = tmp_path / "autosys"
    output = tmp_path / "compare-output"

    # Stonebranch export shape: files use IB_CT_CVA_1109_P1_<real-name>.
    write_json(
        sb_root / "workflows" / "IB_CT_CVA_1109_P1_DAILY_BOX.json",
        {
            "name": "IB_CT_CVA_1109_P1_DAILY_BOX",
            "tasks": [
                "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS",
                "IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS",
            ],
        },
    )
    write_json(
        sb_root / "tasks" / "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS.json",
        {
            "name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS",
            "agentName": "AGENT_01",
            "calendarName": "BUSINESS_DAYS",
            "command": "/opt/jobs/load_customers.sh",
        },
    )
    write_json(
        sb_root / "tasks" / "IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS.json",
        {
            "name": "IB_CT_CVA_1109_P1_VALIDATE_CUSTOMERS",
            "predecessorTask": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS",
            "agentName": "AGENT_01",
            "calendarName": "BUSINESS_DAYS",
            "command": "/opt/jobs/validate_customers.sh",
        },
    )
    write_json(
        sb_root / "file_watchers" / "IB_CT_CVA_1109_P1_WATCH_INCOMING.json",
        {
            "name": "IB_CT_CVA_1109_P1_WATCH_INCOMING",
            "workflowName": "IB_CT_CVA_1109_P1_DAILY_BOX",
            "watch_file": "/data/incoming/*.csv",
        },
    )
    write_json(sb_root / "agents" / "AGENT_01.json", {"name": "AGENT_01"})
    write_json(sb_root / "calendars" / "BUSINESS_DAYS.json", {"name": "BUSINESS_DAYS"})

    # AutoSys repository shape: file uses EN token, while inner jobs/boxes use 0en0.
    jil_root.mkdir(parents=True)
    (jil_root / "IB_CT_CVA_1109_EN_DAILY_BOX.jil").write_text(
        "\n".join(
            [
                "insert_job: IB_CT_CVA_1109_0en0_DAILY_BOX job_type: b",
                "insert_job: IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS job_type: c",
                "box_name: IB_CT_CVA_1109_0en0_DAILY_BOX",
                "machine: AGENT_01",
                "run_calendar: BUSINESS_DAYS",
                "command: /opt/jobs/load_customers.sh",
                "insert_job: IB_CT_CVA_1109_0en0_VALIDATE_CUSTOMERS job_type: c",
                "box_name: IB_CT_CVA_1109_0en0_DAILY_BOX",
                "machine: AGENT_01",
                "run_calendar: BUSINESS_DAYS",
                "condition: s(IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS)",
                "command: /opt/jobs/validate_customers.sh",
                "insert_job: IB_CT_CVA_1109_0en0_WATCH_INCOMING job_type: f",
                "box_name: IB_CT_CVA_1109_0en0_DAILY_BOX",
                "watch_file: /data/incoming/*.csv",
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

    assert result.summary["missing_in_stonebranch"] == 0
    assert result.summary["missing_in_jil"] == 0
    assert result.summary["missing_edges_in_stonebranch"] == 0
    assert result.summary["missing_edges_in_jil"] == 0
    assert not result.comparison.diagnostics["stonebranch_key_collisions"]
    assert not result.comparison.diagnostics["jil_key_collisions"]

    matched_nodes = comparison_node_keys(result)
    assert "PROD:box:daily_box" in matched_nodes
    assert "PROD:task:load_customers" in matched_nodes
    assert "PROD:task:validate_customers" in matched_nodes
    assert "PROD:file_watcher:watch_incoming" in matched_nodes
    assert "PROD:agent:agent_01" in matched_nodes
    assert "PROD:calendar:business_days" in matched_nodes

    matched_edges = comparison_edge_keys(result)
    assert f"PROD:box:daily_box->{REL_CONTAINS}->PROD:task:load_customers" in matched_edges
    assert f"PROD:box:daily_box->{REL_CONTAINS}->PROD:task:validate_customers" in matched_edges
    assert f"PROD:box:daily_box->{REL_CONTAINS}->PROD:file_watcher:watch_incoming" in matched_edges
    assert f"PROD:task:validate_customers->{REL_DEPENDS_ON_SUCCESS}->PROD:task:load_customers" in matched_edges
    assert f"PROD:task:load_customers->{REL_RUNS_ON}->PROD:agent:agent_01" in matched_edges
    assert f"PROD:task:validate_customers->{REL_USES_CALENDAR}->PROD:calendar:business_days" in matched_edges
    assert any(f"->{REL_RUNS_COMMAND}->PROD:command:" in edge for edge in matched_edges)
    assert f"PROD:file_watcher:watch_incoming->{REL_WATCHES_FILE}->PROD:file:/data/incoming/*.csv" in matched_edges

    report = (output / "compare" / "report.md").read_text(encoding="utf-8")
    edge_diff = (output / "compare" / "edge-diff.csv").read_text(encoding="utf-8")
    log_text = (output / "run.log").read_text(encoding="utf-8")

    assert "IB_CT_CVA_1109_P1" not in edge_diff
    assert "IB_CT_CVA_1109_0en0" not in edge_diff
    assert "Completed direct comparison" in log_text
    assert "Migration metrics" in report
