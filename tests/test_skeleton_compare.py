"""Integration tests for skeleton_compare.py: classification, diagnostics, metrics."""

from __future__ import annotations

from pathlib import Path

from stonebranch_graph.alias import AliasTable
from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.expr import Atom, SUCCESS
from stonebranch_graph.skeleton import KIND_UNIT, Skeleton, SkeletonNode
from stonebranch_graph.skeleton_compare import (
    build_skeleton_risks,
    compare_skeletons,
    skeleton_metrics,
    write_skeleton_report,
)
from stonebranch_graph.skeleton_normalize import erase_plumbing
from stonebranch_graph.skeleton_stonebranch import build_stonebranch_skeleton

from .conftest import build_jil_skeleton, build_sb_skeleton, write_json, write_text


def _alias(data: dict) -> AliasTable:
    return AliasTable._from_data(data)


def test_status_classification_matched_changed_only_in():
    sb = Skeleton()
    sb.add_node(SkeletonNode(id="a", kind=KIND_UNIT, parent=None, trigger=None))
    sb.add_node(SkeletonNode(id="b", kind=KIND_UNIT, parent=None, trigger=Atom("a", SUCCESS)))
    sb.add_node(SkeletonNode(id="only_sb", kind=KIND_UNIT, parent=None, trigger=None))
    sb.validate()

    jil = Skeleton()
    jil.add_node(SkeletonNode(id="a", kind=KIND_UNIT, parent=None, trigger=None))
    jil.add_node(SkeletonNode(id="b", kind=KIND_UNIT, parent=None, trigger=None))  # different trigger
    jil.add_node(SkeletonNode(id="only_jil", kind=KIND_UNIT, parent=None, trigger=None))
    jil.validate()

    comparison = compare_skeletons(sb, jil)
    by_id = {entry.id: entry for entry in comparison.entries}

    assert by_id["a"].status_by_level["strict"] == "matched"
    assert by_id["b"].status_by_level["strict"] == "changed"
    assert "trigger_changed" in by_id["b"].reasons
    assert by_id["only_sb"].status_by_level["topology"] == "only_in_stonebranch"
    assert by_id["only_jil"].status_by_level["topology"] == "only_in_jil"


def test_metrics_score_monotonicity_more_misses_lower_score():
    def build(missing_count: int) -> Skeleton:
        sk = Skeleton()
        sk.add_node(SkeletonNode(id="shared", kind=KIND_UNIT, parent=None, trigger=None))
        for i in range(missing_count):
            sk.add_node(SkeletonNode(id=f"extra{i}", kind=KIND_UNIT, parent=None, trigger=None))
        sk.validate()
        return sk

    jil = Skeleton()
    jil.add_node(SkeletonNode(id="shared", kind=KIND_UNIT, parent=None, trigger=None))
    jil.validate()

    score_0 = skeleton_metrics(compare_skeletons(build(0), jil))["skeleton_readiness_score"]
    score_2 = skeleton_metrics(compare_skeletons(build(2), jil))["skeleton_readiness_score"]
    score_5 = skeleton_metrics(compare_skeletons(build(5), jil))["skeleton_readiness_score"]

    assert score_0 > score_2 > score_5


def test_collision_surfaced_as_risk_and_report(tmp_path: Path, config: AnalyzerConfig):
    jil_dir = tmp_path / "jil"
    write_text(
        jil_dir / "PROD" / "jobs.jil",
        "insert_job: EXTRACT\njob_type: c\ncommand: /app/extract.sh\n\n"
        "insert_job: JOB_A\njob_type: c\ncommand: /app/job_a.sh\n",
    )
    alias = _alias(
        {
            "logical_ids": {
                "autosys": {"EXTRACT": "etl/extract", "JOB_A": "etl/extract"},
            }
        }
    )
    skeleton = build_jil_skeleton(jil_dir / "PROD", config=config, alias=alias)

    assert len(skeleton.collisions) == 1
    collision = skeleton.collisions[0]
    assert {collision["kept_native"], collision["dropped_native"]} == {"EXTRACT", "JOB_A"}
    assert collision["merge_allowed"] is False

    empty_sb = erase_plumbing(build_stonebranch_skeleton(
        __import__("stonebranch_graph.parsers.stonebranch_json", fromlist=["StonebranchRawExport"])
        .StonebranchRawExport(records=[], warnings=[]),
        config=config,
    ))
    comparison = compare_skeletons(empty_sb, skeleton)
    metrics = skeleton_metrics(comparison)
    assert metrics["jil_collisions"] == 1
    risks = build_skeleton_risks(comparison)
    assert any("collision" in risk.lower() for risk in risks)

    report_path = tmp_path / "report.md"
    write_skeleton_report(report_path, comparison, metrics)
    report_text = report_path.read_text(encoding="utf-8")
    assert "EXTRACT" in report_text and "JOB_A" in report_text


def test_collision_on_merge_allow_list_downgrades_to_info(tmp_path: Path, config: AnalyzerConfig):
    jil_dir = tmp_path / "jil"
    write_text(
        jil_dir / "PROD" / "jobs.jil",
        "insert_job: EXTRACT\njob_type: c\ncommand: /app/extract.sh\n\n"
        "insert_job: JOB_A\njob_type: c\ncommand: /app/job_a.sh\n",
    )
    alias = _alias(
        {
            "logical_ids": {
                "autosys": {"EXTRACT": "etl/extract", "JOB_A": "etl/extract"},
            },
            "merge": {"autosys": ["etl/extract"]},
        }
    )
    skeleton = build_jil_skeleton(jil_dir / "PROD", config=config, alias=alias)
    assert len(skeleton.collisions) == 1
    assert skeleton.collisions[0]["merge_allowed"] is True

    metrics_no_collision = skeleton_metrics(
        compare_skeletons(
            erase_plumbing(build_stonebranch_skeleton(
                __import__(
                    "stonebranch_graph.parsers.stonebranch_json", fromlist=["StonebranchRawExport"]
                ).StonebranchRawExport(records=[], warnings=[]),
                config=config,
            )),
            skeleton,
        )
    )
    assert metrics_no_collision["jil_collisions"] == 0
    assert metrics_no_collision["jil_collisions_allowed"] == 1


def test_unmapped_stonebranch_condition_surfaced(tmp_path: Path, config: AnalyzerConfig):
    root = tmp_path / "sb"
    write_json(root / "tasks" / "upstream.json", {"name": "upstream", "type": "Universal Task"})
    write_json(root / "tasks" / "downstream.json", {"name": "downstream", "type": "Universal Task"})
    write_json(
        root / "workflows" / "WF.json",
        {
            "name": "WF",
            "type": "taskWorkflow",
            "workflowVertices": [
                {"id": "1", "taskName": "upstream"},
                {"id": "2", "taskName": "downstream"},
            ],
            "workflowEdges": [
                {"sourceId": "1", "targetId": "2", "condition": "SomeCustomVendorStatus"},
            ],
        },
    )
    skeleton = build_sb_skeleton(root, config=config)

    downstream_id = "wf/downstream"
    assert downstream_id in skeleton.nodes
    unmapped = skeleton.nodes[downstream_id].meta.get("unmapped_conditions")
    assert unmapped and unmapped[0]["raw"] == "SomeCustomVendorStatus"

    empty_jil = erase_plumbing(
        build_stonebranch_skeleton(
            __import__(
                "stonebranch_graph.parsers.stonebranch_json", fromlist=["StonebranchRawExport"]
            ).StonebranchRawExport(records=[], warnings=[]),
            config=config,
        )
    )
    comparison = compare_skeletons(skeleton, empty_jil)
    metrics = skeleton_metrics(comparison)
    assert metrics["sb_unmapped_conditions"] == 1
    risks = build_skeleton_risks(comparison)
    assert any("unrecognized" in risk.lower() or "unmapped" in risk.lower() for risk in risks)

    # The edge still uses SUCCESS for connectivity -- it is not a silent drop.
    from stonebranch_graph import expr

    assert expr.render(skeleton.nodes[downstream_id].trigger) == "wf/upstream:SUCCESS"


def test_external_namespace_unified_via_alias(tmp_path: Path, config: AnalyzerConfig):
    jil_dir = tmp_path / "jil"
    write_text(
        jil_dir / "PROD" / "job.jil",
        "insert_job: CONSUMER\njob_type: c\ncondition: s(feed^PRD)\ncommand: /app/consumer.sh\n",
    )
    alias = _alias({"logical_ids": {"stonebranch": {"feed": "ext:PRD/feed"}}})
    jil_skeleton = build_jil_skeleton(jil_dir / "PROD", config=config, alias=alias)
    assert "ext:PRD/feed" in jil_skeleton.externals

    sb_root = tmp_path / "sb"
    write_json(sb_root / "tasks" / "consumer.json", {"name": "consumer", "type": "Universal Task"})
    write_json(
        sb_root / "tasks" / "MON_FEED.json",
        {"name": "MON_FEED", "type": "Task Monitor", "taskMonitoredName": "feed", "statuses": "Success"},
    )
    write_json(
        sb_root / "workflows" / "WF.json",
        {
            "name": "WF",
            "type": "taskWorkflow",
            "workflowVertices": [
                {"id": "1", "taskName": "MON_FEED"},
                {"id": "2", "taskName": "consumer"},
            ],
            "workflowEdges": [{"sourceId": "1", "targetId": "2", "condition": "Success"}],
        },
    )
    sb_skeleton = build_sb_skeleton(sb_root, config=config, alias=alias)
    assert "ext:PRD/feed" in sb_skeleton.externals
    assert not sb_skeleton.ambiguous_externals

    comparison = compare_skeletons(sb_skeleton, jil_skeleton, alias=alias)
    assert "ext:PRD/feed" in comparison.externals["matched"]
    assert "ext:PRD/feed" not in comparison.externals["only_in_stonebranch"]
    assert "ext:PRD/feed" not in comparison.externals["only_in_jil"]


def test_external_without_namespace_flagged_ambiguous(tmp_path: Path, config: AnalyzerConfig):
    sb_root = tmp_path / "sb"
    write_json(sb_root / "tasks" / "consumer.json", {"name": "consumer", "type": "Universal Task"})
    write_json(
        sb_root / "tasks" / "MON_FEED.json",
        {"name": "MON_FEED", "type": "Task Monitor", "taskMonitoredName": "feed", "statuses": "Success"},
    )
    write_json(
        sb_root / "workflows" / "WF.json",
        {
            "name": "WF",
            "type": "taskWorkflow",
            "workflowVertices": [
                {"id": "1", "taskName": "MON_FEED"},
                {"id": "2", "taskName": "consumer"},
            ],
            "workflowEdges": [{"sourceId": "1", "targetId": "2", "condition": "Success"}],
        },
    )
    sb_skeleton = build_sb_skeleton(sb_root, config=config, alias=None)
    assert sb_skeleton.ambiguous_externals == {"ext:feed"}

    comparison = compare_skeletons(sb_skeleton, Skeleton())
    risks = build_skeleton_risks(comparison)
    assert any("namespace" in risk.lower() for risk in risks)
    metrics = skeleton_metrics(comparison)
    assert metrics["sb_ambiguous_externals"] == 1


def _sb_root_for_ambiguous_monitor(tmp_path: Path) -> Path:
    root = tmp_path / "sb"
    write_json(root / "tasks" / "load.json", {"name": "load", "type": "Universal Task"})
    write_json(root / "tasks" / "consumer.json", {"name": "consumer", "type": "Universal Task"})
    write_json(
        root / "tasks" / "MON_LOAD.json",
        {"name": "MON_LOAD", "type": "Task Monitor", "taskMonitoredName": "load", "statuses": "Success"},
    )
    write_json(
        root / "workflows" / "WF_SHARED.json",
        {
            "name": "WF_SHARED",
            "type": "taskWorkflow",
            "workflowVertices": [{"id": "1", "taskName": "load"}],
            "workflowEdges": [],
        },
    )
    write_json(
        root / "workflows" / "WF_A.json",
        {
            "name": "WF_A",
            "type": "taskWorkflow",
            "workflowVertices": [{"id": "1", "taskName": "WF_SHARED"}],
            "workflowEdges": [],
        },
    )
    write_json(
        root / "workflows" / "WF_B.json",
        {
            "name": "WF_B",
            "type": "taskWorkflow",
            "workflowVertices": [{"id": "1", "taskName": "WF_SHARED"}],
            "workflowEdges": [],
        },
    )
    return root


def test_ambiguous_monitor_target_no_hint(tmp_path: Path, config: AnalyzerConfig):
    root = _sb_root_for_ambiguous_monitor(tmp_path)
    write_json(
        root / "workflows" / "WF_MON.json",
        {
            "name": "WF_MON",
            "type": "taskWorkflow",
            "workflowVertices": [
                {"id": "1", "taskName": "MON_LOAD"},
                {"id": "2", "taskName": "consumer"},
            ],
            "workflowEdges": [{"sourceId": "1", "targetId": "2", "condition": "Success"}],
        },
    )
    skeleton = build_sb_skeleton(root, config=config)
    ambiguous = [e for e in skeleton.erasures if e.get("ambiguous_monitor_target")]
    assert len(ambiguous) == 1
    assert ambiguous[0]["ambiguous_monitor_target"]["name"] == "load"
    assert set(ambiguous[0]["ambiguous_monitor_target"]["candidates"]) == {
        "wf_a/wf_shared/load",
        "wf_b/wf_shared/load",
    }

    comparison = compare_skeletons(skeleton, Skeleton())
    risks = build_skeleton_risks(comparison)
    assert any("ambiguous" in risk.lower() for risk in risks)


def test_ambiguous_monitor_target_resolved_by_workflow_hint(tmp_path: Path, config: AnalyzerConfig):
    root = _sb_root_for_ambiguous_monitor(tmp_path)
    write_json(
        root / "tasks" / "MON_LOAD.json",
        {
            "name": "MON_LOAD",
            "type": "Task Monitor",
            "taskMonitoredName": "load",
            "taskMonitoredWorkflow": "WF_B",
            "statuses": "Success",
        },
    )
    write_json(
        root / "workflows" / "WF_MON.json",
        {
            "name": "WF_MON",
            "type": "taskWorkflow",
            "workflowVertices": [
                {"id": "1", "taskName": "MON_LOAD"},
                {"id": "2", "taskName": "consumer"},
            ],
            "workflowEdges": [{"sourceId": "1", "targetId": "2", "condition": "Success"}],
        },
    )
    skeleton = build_sb_skeleton(root, config=config)
    ambiguous = [e for e in skeleton.erasures if e.get("ambiguous_monitor_target")]
    assert ambiguous == []

    from stonebranch_graph import expr

    consumer = skeleton.nodes["wf_mon/consumer"]
    assert expr.render(consumer.trigger) == "wf_b/wf_shared/load:SUCCESS"


def test_alias_marked_plumbing_erased_on_stonebranch_side(tmp_path: Path, config: AnalyzerConfig):
    root = tmp_path / "sb"
    write_json(root / "tasks" / "upstream.json", {"name": "upstream", "type": "Universal Task"})
    write_json(root / "tasks" / "gate_fanin.json", {"name": "GATE_FANIN", "type": "Universal Task"})
    write_json(root / "tasks" / "downstream.json", {"name": "downstream", "type": "Universal Task"})
    write_json(
        root / "workflows" / "WF.json",
        {
            "name": "WF",
            "type": "taskWorkflow",
            "workflowVertices": [
                {"id": "1", "taskName": "upstream"},
                {"id": "2", "taskName": "GATE_FANIN"},
                {"id": "3", "taskName": "downstream"},
            ],
            "workflowEdges": [
                {"sourceId": "1", "targetId": "2", "condition": "Success"},
                {"sourceId": "2", "targetId": "3", "condition": "Success"},
            ],
        },
    )
    alias = _alias({"plumbing": {"stonebranch": ["GATE_FANIN"]}})
    skeleton = build_sb_skeleton(root, config=config, alias=alias)

    assert "wf/gate_fanin" not in skeleton.nodes
    from stonebranch_graph import expr

    assert expr.render(skeleton.nodes["wf/downstream"].trigger) == "wf/upstream:SUCCESS"


def test_alias_coverage_reports_unused_and_misses(tmp_path: Path, config: AnalyzerConfig):
    jil_dir = tmp_path / "jil"
    write_text(
        jil_dir / "PROD" / "job.jil",
        "insert_job: KNOWN\njob_type: c\ncommand: /app/known.sh\n\n"
        "insert_job: UNMAPPED\njob_type: c\ncommand: /app/unmapped.sh\n",
    )
    alias = _alias(
        {
            "logical_ids": {
                "autosys": {
                    "KNOWN": "known",
                    "TYPO_NAME_NEVER_USED": "typo",
                }
            }
        }
    )
    skeleton = build_jil_skeleton(jil_dir / "PROD", config=config, alias=alias)
    empty_sb = erase_plumbing(
        build_stonebranch_skeleton(
            __import__(
                "stonebranch_graph.parsers.stonebranch_json", fromlist=["StonebranchRawExport"]
            ).StonebranchRawExport(records=[], warnings=[]),
            config=config,
        )
    )
    comparison = compare_skeletons(empty_sb, skeleton, alias=alias)
    coverage = comparison.meta["alias_coverage"]
    assert coverage["unused_count"] == 1
    assert coverage["miss_count"] == 1  # UNMAPPED has no alias entry

    metrics = skeleton_metrics(comparison)
    assert metrics["alias_unused"] == 1
    assert metrics["alias_miss"] == 1
    risks = build_skeleton_risks(comparison)
    assert any("never used" in risk.lower() for risk in risks)

    report_path = tmp_path / "report.md"
    write_skeleton_report(report_path, comparison, metrics)
    report_text = report_path.read_text(encoding="utf-8")
    assert "Alias coverage" in report_text
