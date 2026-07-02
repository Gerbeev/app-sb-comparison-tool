from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.exporters import write_json
from stonebranch_graph.workflows import compare_direct, comparison_files


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
    write_json(
        sb_root / "tasks" / "sb_only.json",
        {"name": "IB_CT_CVA_1109_P1_STONEBRANCH_ONLY"},
    )
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


def load_data(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    prefix = "window.GRAPH_DATA = "
    assert prefix in text
    return json.loads(text.split(prefix, 1)[1].rsplit(";", 1)[0])


def test_comparison_html_graph_files_are_generated_and_offline(tmp_path: Path) -> None:
    sb_root, jil_root = write_sources(tmp_path)
    output = tmp_path / "compare"

    result = compare_direct(stonebranch_path=sb_root, jil_path=jil_root, output_dir=output, config=AnalyzerConfig.default(), env="PROD")

    assert output / "compare" / "compare-graph.html" in result.files
    assert output / "compare" / "compare-graph-data.js" in result.files
    assert output / "compare" / "cytoscape.min.js" in result.files
    assert output / "compare" / "cytoscape.LICENSE" in result.files
    assert comparison_files(output) == result.files
    html = (output / "compare" / "compare-graph.html").read_text(encoding="utf-8")
    assert "compare-graph-data.js" in html
    assert "cytoscape.min.js" in html
    assert "window.cytoscape({" in html
    assert "cdn.jsdelivr" not in html
    assert "https://" not in html
    assert "Comparison graph" in html
    assert (output / "compare" / "cytoscape.min.js").exists()


def test_comparison_graph_data_contains_visual_statuses(tmp_path: Path) -> None:
    sb_root, jil_root = write_sources(tmp_path)
    output = tmp_path / "compare"

    compare_direct(stonebranch_path=sb_root, jil_path=jil_root, output_dir=output, config=AnalyzerConfig.default(), env="PROD")
    data = load_data(output / "compare" / "compare-graph-data.js")

    assert data["metadata"]["report_type"] == "comparison"
    assert data["metadata"]["statuses"]["matched"] >= 1
    assert data["metadata"]["statuses"]["missing_in_stonebranch"] >= 1
    assert data["metadata"]["statuses"]["missing_in_jil"] >= 1
    assert data["metadata"]["statuses"]["command_syntax_diff_only"] >= 1
    jobs_by_id = {item["id"]: item for item in data["jobs"]}
    assert jobs_by_id["PROD:task:load_customers"]["status"] == "command_syntax_diff_only"
    assert jobs_by_id["PROD:task:jil_only"]["status"] == "missing_in_stonebranch"
    assert jobs_by_id["PROD:task:stonebranch_only"]["status"] == "missing_in_jil"


def test_comparison_pack_manifest_and_docs_include_html_graph() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")

    assert "compare/compare-graph.html" in readme
    assert "QA20.7" in changelog
    assert "comparison HTML graph" in changelog
