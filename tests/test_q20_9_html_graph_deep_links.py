from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.exporters import write_json
from stonebranch_graph.workflows import build_stonebranch_pack, compare_direct


def load_graph_data(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    prefix = "window.GRAPH_DATA = "
    assert prefix in text
    return json.loads(text.split(prefix, 1)[1].rsplit(";", 1)[0])


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
            "calendar": "BUSINESS_DAYS",
        },
    )
    jil_root.mkdir(parents=True)
    (jil_root / "IB_CT_CVA_1109_EN_DAILY_BOX.jil").write_text(
        "\n".join(
            [
                "insert_job: IB_CT_CVA_1109_0en0_DAILY_BOX job_type: b",
                "insert_job: IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS job_type: c",
                "box_name: IB_CT_CVA_1109_0en0_DAILY_BOX",
                "command: /opt/autosys/bin/load_customers.sh --date $${business_date} --env 0en0",
            ]
        ),
        encoding="utf-8",
    )
    return sb_root, jil_root


def test_html_graph_data_includes_node_and_edge_evidence_for_side_panel(tmp_path: Path) -> None:
    sb_root, _jil_root = write_sources(tmp_path)
    output = tmp_path / "sb-pack"

    build_stonebranch_pack(input_path=sb_root, output_dir=output, config=AnalyzerConfig.default(), env="PROD")
    data = load_graph_data(output / "graph-data.js")

    job = next(item for item in data["jobs"] if item["id"].endswith(":load_customers"))
    assert job["graph_id"].startswith("stonebranch:PROD:task:")
    assert job["canonical_key"].endswith(":load_customers")
    assert job["source_file"].endswith("tasks/load.json")

    edge = next(item for item in data["edges"] if item["relation"] == "runs_command")
    assert edge["evidence_file"].endswith("tasks/load.json")
    assert edge["evidence_key"] == "command"
    assert edge["evidence_path"] == "$.command"
    assert "graph_edge_id" in edge


def test_html_side_panel_has_copy_buttons_hash_deep_links_and_edge_details(tmp_path: Path) -> None:
    sb_root, jil_root = write_sources(tmp_path)
    output = tmp_path / "compare"

    compare_direct(stonebranch_path=sb_root, jil_path=jil_root, output_dir=output, config=AnalyzerConfig.default(), env="PROD")
    html = (output / "compare" / "compare-graph.html").read_text(encoding="utf-8")

    assert "copyButton" in html
    assert "data-copy" in html
    assert "Copy edge" in html
    assert "Copy graph ID" in html
    assert "Copy graph edge ID" in html
    assert "showEdge(edgeId)" in html
    assert "selectEdge(edgeId)" in html
    assert "openHashTarget" in html
    assert "window.location.hash" in html
    assert "evidence_file" in html
    assert "evidence_path" in html
    assert "evidence_value" in html
    assert "data-edge" in html
    assert "data-node" in html
    assert "cdn.jsdelivr" not in html
    assert "https://" not in html
