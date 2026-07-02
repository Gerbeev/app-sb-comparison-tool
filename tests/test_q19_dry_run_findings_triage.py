from __future__ import annotations

import csv
import json
from pathlib import Path

from stonebranch_graph.exporters import write_json
from stonebranch_graph.triage import create_triage_report, resolve_compare_dir
from stonebranch_graph.cli import main


def _write_comparison_fixture(compare_pack: Path) -> Path:
    compare_dir = compare_pack / "compare"
    compare_dir.mkdir(parents=True)
    write_json(
        compare_dir / "comparison.json",
        {
            "summary": {"migration_readiness_score": 61, "readiness_grade": "high_risk"},
            "nodes": {
                "missing_in_stonebranch": [
                    {
                        "id": "jil:PROD:task:JOB_B",
                        "canonical_key": "PROD:task:job_b",
                        "source_system": "autosys_jil",
                        "env": "PROD",
                        "kind": "task",
                        "native_kind": "c",
                        "name": "IB_CT_CVA_1109_0en0_JOB_B",
                        "source_file": "box.jil",
                    }
                ],
                "missing_in_jil": [],
            },
            "edges": {
                "missing_in_stonebranch": [
                    {
                        "key": "PROD:task:job_b->depends_on_success->PROD:task:job_a",
                        "relation": "depends_on_success",
                        "source": {"name": "JOB_B"},
                        "target": {"name": "JOB_A"},
                        "evidence_file": "box.jil",
                        "evidence_key": "condition_success",
                    }
                ],
                "missing_in_jil": [],
            },
            "attributes": {
                "command_differences": [
                    {
                        "key": "PROD:task:job_a",
                        "status": "command_syntax_diff_only",
                        "stonebranch": "IB_CT_CVA_1109_P1_JOB_A",
                        "jil": "IB_CT_CVA_1109_0en0_JOB_A",
                        "reason": "Command differs only by variable syntax, environment token, script path.",
                        "normalization_reasons": ["variable_syntax", "environment_token", "script_path"],
                        "variable_names": ["business_date"],
                        "env_tokens": ["p1", "0en0"],
                        "script_basenames": ["job_a.sh"],
                    },
                    {
                        "key": "PROD:task:job_c",
                        "status": "command_semantic_mismatch",
                        "stonebranch": "JOB_C",
                        "jil": "JOB_C",
                        "reason": "Command differs after semantic normalization.",
                    },
                ],
                "condition_differences": [{"key": "PROD:task:job_b"}],
            },
            "diagnostics": {
                "stonebranch_key_collisions": [
                    {
                        "key": "PROD:task:load_customers",
                        "reason": "enterprise_name_collision",
                        "names": ["IB_CT_CVA_1109_P1_LOAD_CUSTOMERS", "IB_CT_CVA_2200_P1_LOAD_CUSTOMERS"],
                        "business_codes": ["1109", "2200"],
                        "env_tokens": ["P1"],
                    }
                ],
                "jil_key_collisions": [],
                "stonebranch_edge_collisions": [],
                "jil_edge_collisions": [],
                "unused_mappings": [{"from": "old", "to": "new"}],
            },
            "risks": [],
        },
    )
    write_json(compare_dir / "metrics.json", {"migration_readiness_score": 61, "readiness_grade": "high_risk"})
    (compare_pack / "run.log").write_text(
        "2026-07-01T00:00:00+00:00 [WARNING] jil: Condition did not produce dependency references.\n",
        encoding="utf-8",
    )
    return compare_dir


def test_q19_triage_report_classifies_dry_run_findings(tmp_path: Path) -> None:
    compare_pack = tmp_path / "compare-pack"
    _write_comparison_fixture(compare_pack)

    result = create_triage_report(compare_pack)

    assert result.output_dir == compare_pack / "compare"
    assert all(path.exists() for path in result.files)
    assert result.summary["finding_count"] >= 8
    assert result.summary["by_category"]["enterprise_naming_collision"] == 1
    assert result.summary["by_category"]["critical_edge_gap"] == 1
    assert result.summary["by_category"]["command_syntax_mapping"] == 1
    assert result.summary["by_category"]["command_semantic_mismatch"] == 1
    assert result.summary["by_category"]["parser_or_comparison_warning"] == 1

    report = (compare_pack / "compare" / "triage-report.md").read_text(encoding="utf-8")
    assert "Dry-run findings triage" in report
    assert "Review collisions.csv" in report
    assert "critical_edge_gap" in report

    rows = list(csv.DictReader((compare_pack / "compare" / "triage-findings.csv").open(encoding="utf-8")))
    categories = {row["category"] for row in rows}
    assert "enterprise_naming_collision" in categories
    assert "critical_edge_gap" in categories
    assert "command_syntax_mapping" in categories
    assert "command_semantic_mismatch" in categories
    assert "condition_mismatch" in categories
    assert "mapping_rule_issue" in categories
    assert "parser_or_comparison_warning" in categories
    assert "readiness_score" in categories


def test_q19_triage_can_write_to_custom_output_dir(tmp_path: Path) -> None:
    compare_pack = tmp_path / "compare-pack"
    _write_comparison_fixture(compare_pack)
    output = tmp_path / "triage"

    result = create_triage_report(compare_pack / "compare", output)

    assert result.compare_dir == compare_pack / "compare"
    assert result.output_dir == output
    assert (output / "triage-report.md").exists()
    assert (output / "triage-findings.csv").exists()
    assert (output / "triage-summary.json").exists()


def test_q19_cli_triage_command_generates_outputs(tmp_path: Path) -> None:
    compare_pack = tmp_path / "compare-pack"
    _write_comparison_fixture(compare_pack)
    output = tmp_path / "triage-out"

    exit_code = main(["triage", str(compare_pack), "-o", str(output)])

    assert exit_code == 0
    summary = json.loads((output / "triage-summary.json").read_text(encoding="utf-8"))
    assert summary["by_category"]["enterprise_naming_collision"] == 1


def test_q19_resolve_compare_dir_rejects_non_comparison_folder(tmp_path: Path) -> None:
    try:
        resolve_compare_dir(tmp_path / "empty")
    except FileNotFoundError as exc:
        assert "comparison.json" in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError")


def test_q19_docs_and_cli_parser_mention_triage() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    dry_run = (root / "docs" / "REAL_REPOSITORY_DRY_RUN.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "python -m stonebranch_graph.cli triage" in readme
    assert "python -m stonebranch_graph.cli triage" in dry_run
    assert "triage-findings.csv" in dry_run
    assert "enterprise_naming_collision" in dry_run
    assert "### QA19" in changelog
    assert "triage" in readme
