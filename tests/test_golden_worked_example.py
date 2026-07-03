"""Golden worked-example tests (IMPLEMENTATION_PLAN.md Definition of Done #1 & #2).

The scenario mirrors docs/concept/mapping-explained.md section 8: an ETL box/workflow
(extract -> transform -> load), a REPORTING box/workflow that depends on the whole ETL
box (build_report <- ETL success), and an ARCHIVE box/workflow that depends on one job
inside ETL (copy_files <- load success). The Stonebranch side expresses both
box-level and single-job cross-workflow dependencies with Task Monitors; the AutoSys
side expresses the same logic with plain `condition: s(...)` references to a box name
and a job name. Both must normalize to byte-identical canonical skeletons.
"""

from __future__ import annotations

import json

from stonebranch_graph.skeleton import STRICTNESS_LEVELS

from .conftest import GOLDEN_DIR


def test_golden_byte_identical_at_all_levels(golden_sb_skeleton, golden_jil_skeleton):
    for level in STRICTNESS_LEVELS:
        sb_text = golden_sb_skeleton.to_canonical_jsonl(level)
        jil_text = golden_jil_skeleton.to_canonical_jsonl(level)
        assert sb_text == jil_text, f"canonical skeletons differ at level={level!r}"


def test_golden_topology_matches_expected_node_set(golden_sb_skeleton, golden_jil_skeleton):
    expected_ids = {
        "archive",
        "archive/copy_files",
        "etl",
        "etl/extract",
        "etl/load",
        "etl/transform",
        "reporting",
        "reporting/build_report",
        "reporting/publish",
    }
    assert set(golden_sb_skeleton.nodes) == expected_ids
    assert set(golden_jil_skeleton.nodes) == expected_ids


def test_golden_no_task_monitor_node_survives(golden_sb_skeleton):
    for node in golden_sb_skeleton.nodes.values():
        assert node.meta.get("plumbing") != "task_monitor"
        assert "MON_" not in node.id.upper()


def test_golden_monitor_condition_appears_in_successor_trigger(golden_sb_skeleton):
    build_report = golden_sb_skeleton.nodes["reporting/build_report"]
    copy_files = golden_sb_skeleton.nodes["archive/copy_files"]
    assert build_report.trigger is not None
    assert copy_files.trigger is not None

    from stonebranch_graph import expr

    assert expr.render(build_report.trigger) == "etl:SUCCESS"
    assert expr.render(copy_files.trigger) == "etl/load:SUCCESS"


def test_golden_matches_shipped_concept_skeleton_example(golden_jil_skeleton):
    """Guard the concept's own golden file: docs/concept/skeleton-example.json."""

    doc_path = GOLDEN_DIR.parent.parent.parent / "docs" / "concept" / "skeleton-example.json"
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    doc_nodes = {
        (n["id"], n["kind"], n["parent"], n["trigger"]) for n in doc["nodes"]
    }

    built_nodes = set()
    for line in golden_jil_skeleton.to_canonical_jsonl("strict").splitlines():
        record = json.loads(line)
        built_nodes.add((record["id"], record["kind"], record["parent"], record.get("trigger")))

    assert built_nodes == doc_nodes


def test_golden_comparison_reports_zero_differences_at_all_levels(
    golden_sb_skeleton, golden_jil_skeleton, golden_alias
):
    from stonebranch_graph.skeleton_compare import compare_skeletons

    comparison = compare_skeletons(golden_sb_skeleton, golden_jil_skeleton, alias=golden_alias)
    for level, summary in comparison.summary_by_level.items():
        assert summary["changed"] == 0, f"unexpected changes at {level}"
        assert summary["only_in_stonebranch"] == 0, f"unexpected only_in_stonebranch at {level}"
        assert summary["only_in_jil"] == 0, f"unexpected only_in_jil at {level}"
        assert summary["match_rate_percent"] == 100.0
    assert comparison.risks == []
