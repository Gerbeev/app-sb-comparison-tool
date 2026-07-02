from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.exporters import write_json
from stonebranch_graph.workflows import compare_direct, build_stonebranch_pack


def write_sources(tmp_path: Path) -> tuple[Path, Path]:
    sb_root = tmp_path / "stonebranch"
    jil_root = tmp_path / "jil"
    write_json(
        sb_root / "workflows" / "daily.json",
        {"name": "IB_CT_CVA_1109_P1_DAILY_BOX", "tasks": ["IB_CT_CVA_1109_P1_LOAD_CUSTOMERS"]},
    )
    write_json(
        sb_root / "tasks" / "load.json",
        {
            "name": "IB_CT_CVA_1109_P1_LOAD_CUSTOMERS",
            "command": "/u01/stonebranch/scripts/load_customers.sh --date ${BUSINESS_DATE} --env P1",
        },
    )
    write_json(sb_root / "tasks" / "sb_only.json", {"name": "IB_CT_CVA_1109_P1_STONEBRANCH_ONLY"})
    jil_root.mkdir(parents=True)
    (jil_root / "IB_CT_CVA_1109_EN_DAILY_BOX.jil").write_text(
        "\n".join(
            [
                "insert_job: IB_CT_CVA_1109_0en0_DAILY_BOX job_type: b",
                "insert_job: IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS job_type: c",
                "box_name: IB_CT_CVA_1109_0en0_DAILY_BOX",
                "command: /opt/autosys/bin/load_customers.sh --date $${business_date} --env 0en0",
                "insert_job: IB_CT_CVA_1109_0en0_JIL_ONLY job_type: c",
            ]
        ),
        encoding="utf-8",
    )
    return sb_root, jil_root


def load_graph_data(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    prefix = "window.GRAPH_DATA = "
    assert prefix in text
    return json.loads(text.split(prefix, 1)[1].rsplit(";", 1)[0])


def test_comparison_html_has_large_scale_status_filters(tmp_path: Path) -> None:
    sb_root, jil_root = write_sources(tmp_path)
    output = tmp_path / "compare"

    compare_direct(stonebranch_path=sb_root, jil_path=jil_root, output_dir=output, config=AnalyzerConfig.default(), env="PROD")

    html = (output / "compare" / "compare-graph.html").read_text(encoding="utf-8")
    assert 'id="statusFilter"' in html
    assert 'value="problems"' in html
    assert 'value="critical"' in html
    assert 'value="missing"' in html
    assert 'id="showProblems"' in html
    assert 'id="showCritical"' in html
    assert 'id="showMissing"' in html
    assert "Status counts" in html
    assert "Large graph tips" in html
    assert "statusMatches" in html
    assert "visible_nodes" in html
    assert "cdn.jsdelivr" not in html
    assert "https://" not in html


def test_comparison_graph_data_keeps_status_counts_for_filters(tmp_path: Path) -> None:
    sb_root, jil_root = write_sources(tmp_path)
    output = tmp_path / "compare"

    compare_direct(stonebranch_path=sb_root, jil_path=jil_root, output_dir=output, config=AnalyzerConfig.default(), env="PROD")
    data = load_graph_data(output / "compare" / "compare-graph-data.js")

    statuses = data["metadata"]["statuses"]
    assert statuses["matched"] >= 1
    assert statuses["missing_in_stonebranch"] >= 1
    assert statuses["missing_in_jil"] >= 1
    assert statuses["command_syntax_diff_only"] >= 1


def test_source_html_hides_problem_quick_filters_when_no_comparison_statuses(tmp_path: Path) -> None:
    sb_root, _jil_root = write_sources(tmp_path)
    output = tmp_path / "sb-pack"

    build_stonebranch_pack(input_path=sb_root, output_dir=output, config=AnalyzerConfig.default(), env="PROD")

    html = (output / "graph.html").read_text(encoding="utf-8")
    assert "hasComparisonStatuses" in html
    assert "quickFilters" in html
    assert "No comparison statuses in this source graph" in html
