from __future__ import annotations

import inspect

from stonebranch_graph import triage
from stonebranch_graph.triage import TriageFinding, fix_guidance_for, with_fix_guidance


def test_triage_fix_guidance_is_rule_driven() -> None:
    assert "enterprise_naming_collision" in triage.TRIAGE_FIX_RULES
    assert triage.TRIAGE_FIX_RULES["command_semantic_mismatch"].suggested_fix_type == "real_command_migration_gap"
    assert fix_guidance_for("unknown_category") == triage.DEFAULT_FIX_GUIDANCE


def test_with_fix_guidance_uses_rule_table_without_overwriting_explicit_fields() -> None:
    enriched = with_fix_guidance(TriageFinding(severity="high", category="critical_edge_gap", status="missing"))
    assert enriched.suggested_fix_type == "relation_parser_or_real_gap_triage"
    assert enriched.owner == "migration_engineer"
    assert "edge evidence" in enriched.next_action

    explicit = with_fix_guidance(
        TriageFinding(
            severity="high",
            category="critical_edge_gap",
            status="missing",
            suggested_fix_type="custom_fix",
            owner="custom_owner",
            next_action="custom action",
        )
    )
    assert explicit.suggested_fix_type == "custom_fix"
    assert explicit.owner == "custom_owner"
    assert explicit.next_action == "custom action"


def test_triage_sort_and_review_order_are_tables() -> None:
    assert triage.TRIAGE_CATEGORY_ORDER["enterprise_naming_collision"] < triage.TRIAGE_CATEGORY_ORDER["critical_edge_gap"]
    messages = triage.next_review_order(
        [
            TriageFinding(severity="high", category="command_semantic_mismatch", status="x"),
            TriageFinding(severity="high", category="enterprise_naming_collision", status="x"),
        ]
    )
    assert messages[0].startswith("Review collisions.csv")
    assert any("command-diff.csv" in message for message in messages)


def test_fix_guidance_function_no_long_inline_category_dictionary() -> None:
    source = inspect.getsource(triage.fix_guidance_for)
    assert "TRIAGE_FIX_RULES.get" in source
    assert "enterprise_naming_collision" not in source
    assert len(source.splitlines()) <= 3
