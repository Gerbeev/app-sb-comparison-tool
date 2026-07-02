from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.exporters import write_json
from stonebranch_graph.workflows import (
    build_jil_pack,
    build_stonebranch_pack,
    compare_direct,
    compare_packs,
    comparison_files,
    comparison_pack_files,
)


def _write_minimal_sources(tmp_path: Path) -> tuple[Path, Path]:
    sb_root = tmp_path / "stonebranch"
    jil_root = tmp_path / "jil"
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
    return sb_root, jil_root


def test_q17_comparison_file_contract_is_complete_unique_and_existing(tmp_path: Path) -> None:
    sb_root, jil_root = _write_minimal_sources(tmp_path)
    output = tmp_path / "compare-direct"

    result = compare_direct(
        stonebranch_path=sb_root,
        jil_path=jil_root,
        output_dir=output,
        config=AnalyzerConfig.default(),
        env="PROD",
    )

    expected = comparison_files(output)
    assert result.files == expected
    assert len(result.files) == len(set(result.files))
    assert all(path.exists() for path in result.files)
    assert output / "compare" / "command-diff.csv" in result.files
    assert output / "compare" / "remediation-summary.json" in result.files
    assert output / "compare" / "metrics.csv" in result.files
    assert output / "compare" / "collisions.csv" in result.files
    assert output / "compare" / "mapping-diagnostics.csv" in result.files


def test_q17_compare_pack_manifest_lists_current_comparison_artifacts(tmp_path: Path) -> None:
    sb_root, jil_root = _write_minimal_sources(tmp_path)
    sb_pack = tmp_path / "sb-pack"
    jil_pack = tmp_path / "jil-pack"
    output = tmp_path / "compare-pack"

    build_stonebranch_pack(sb_root, sb_pack, AnalyzerConfig.default(), env="PROD")
    build_jil_pack(jil_root, jil_pack, AnalyzerConfig.default(), env="PROD")
    result = compare_packs(
        stonebranch_pack=sb_pack,
        jil_pack=jil_pack,
        output_dir=output,
        config=AnalyzerConfig.default(),
    )

    assert result.files == comparison_pack_files(output)
    assert len(result.files) == len(set(result.files))
    assert all(path.exists() for path in result.files)

    manifest = json.loads((output / "compare-pack-manifest.json").read_text(encoding="utf-8"))
    expected_manifest_files = [str(path.relative_to(output)) for path in comparison_files(output)]
    assert manifest["important_files"] == expected_manifest_files


def test_q17_windows_launcher_uses_plain_python() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "run_terminal_ui.cmd").read_text(encoding="utf-8")

    assert "python -m stonebranch_graph.cli tui" in launcher
    assert "py -3" not in launcher


def test_q17_changelog_records_final_qa_baseline() -> None:
    root = Path(__file__).resolve().parents[1]
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "### QA17" in changelog
    assert "final QA regression pass" in changelog
