from __future__ import annotations

import csv
import json
from pathlib import Path

from stonebranch_graph.exporters import write_json
from stonebranch_graph.triage import create_triage_report


def _write_q20_compare_fixture(compare_pack: Path) -> Path:
    compare_dir = compare_pack / "compare"
    compare_dir.mkdir(parents=True)
    write_json(
        compare_dir / "comparison.json",
        {
            "summary": {"migration_readiness_score": 54, "readiness_grade": "high_risk"},
            "nodes": {
                "missing_in_stonebranch": [
                    {
                        "canonical_key": "PROD:task:job_missing",
                        "kind": "task",
                        "name": "IB_CT_CVA_1109_0en0_JOB_MISSING",
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
                        "normalization_reasons": ["variable_syntax", "environment_token"],
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
                "unused_mappings": [{"from": "old", "to": "new"}],
            },
        },
    )
    write_json(compare_dir / "metrics.json", {"migration_readiness_score": 54, "readiness_grade": "high_risk"})
    (compare_pack / "run.log").write_text(
        "2026-07-01T00:00:00+00:00 [WARNING] stonebranch: Skipped unsupported object shape.\n",
        encoding="utf-8",
    )
    return compare_dir


def test_q20_triage_findings_include_fix_guidance_columns(tmp_path: Path) -> None:
    compare_pack = tmp_path / "compare-pack"
    _write_q20_compare_fixture(compare_pack)

    result = create_triage_report(compare_pack)

    assert (compare_pack / "compare" / "triage-fix-plan.md").exists()
    assert (compare_pack / "compare" / "triage-fix-plan.csv").exists()
    assert all(path.exists() for path in result.files)
    summary = json.loads((compare_pack / "compare" / "triage-summary.json").read_text(encoding="utf-8"))
    assert summary["by_suggested_fix_type"]["manual_mapping_or_naming_rule"] == 1
    assert summary["by_suggested_fix_type"]["command_normalization_rule_candidate"] == 1
    assert summary["by_suggested_fix_type"]["real_command_migration_gap"] == 1

    rows = list(csv.DictReader((compare_pack / "compare" / "triage-findings.csv").open(encoding="utf-8")))
    assert {"suggested_fix_type", "owner", "next_action"}.issubset(rows[0].keys())
    by_category = {row["category"]: row for row in rows}
    assert by_category["enterprise_naming_collision"]["suggested_fix_type"] == "manual_mapping_or_naming_rule"
    assert by_category["critical_edge_gap"]["suggested_fix_type"] == "relation_parser_or_real_gap_triage"
    assert by_category["command_syntax_mapping"]["suggested_fix_type"] == "command_normalization_rule_candidate"
    assert by_category["command_semantic_mismatch"]["suggested_fix_type"] == "real_command_migration_gap"


def test_q20_fix_plan_groups_findings_into_prioritized_backlog(tmp_path: Path) -> None:
    compare_pack = tmp_path / "compare-pack"
    _write_q20_compare_fixture(compare_pack)

    create_triage_report(compare_pack)

    rows = list(csv.DictReader((compare_pack / "compare" / "triage-fix-plan.csv").open(encoding="utf-8")))
    assert rows[0]["suggested_fix_type"] == "manual_mapping_or_naming_rule"
    assert rows[0]["owner"] == "migration_analyst"
    assert any(row["suggested_fix_type"] == "parser_rule_candidate" for row in rows)
    assert any(row["suggested_fix_type"] == "condition_parser_or_logic_gap" for row in rows)
    assert all(row["recommended_action"] for row in rows)

    plan = (compare_pack / "compare" / "triage-fix-plan.md").read_text(encoding="utf-8")
    assert "Dry-run fix plan" in plan
    assert "manual_mapping_or_naming_rule" in plan
    assert "relation_parser_or_real_gap_triage" in plan
    assert "triage-fix-plan.csv" in plan


def test_q20_docs_describe_post_dry_run_fix_plan_outputs() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    dry_run = (root / "docs" / "REAL_REPOSITORY_DRY_RUN.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "triage-fix-plan.md" in readme
    assert "triage-fix-plan.csv" in readme
    assert "suggested_fix_type" in dry_run
    assert "manual_mapping_or_naming_rule" in dry_run
    assert "### QA20" in changelog
