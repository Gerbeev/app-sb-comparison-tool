# Agent prompt — Item 6: JIL condition boolean structure (OR-groups)

You are implementing Item 6 of `GRAPH_SKELETON_IMPLEMENTATION_PLAN.md`. Goal: stop flattening `condition:` boolean logic — record AND/OR structure as metadata so OR-dependencies are honest in the graph and flagged for migration review.

## Token budget rules
Read ONLY: `stonebranch_graph/parsers/autosys_jil.py` methods `_parse_condition_refs`, `_add_condition_edges`, `_job_metadata`, and the `CONDITION_RE` constant. Do not read other modules (constants you need are already imported in that file). Minimal diff, keep the existing public behavior (same edges, same relations).

## Task
1. Extend condition parsing to classify top-level logic, tolerant of parentheses:
   - only `&`/none → `"and"`; only `|` → `"or"`; both → `"mixed"`; unparsable → `"unknown"`.
   - Assign `or_group` indexes: atoms joined by `|` inside the same parenthesized group (or at top level) share a group index; pure-AND atoms have none. A simple single-pass scanner over the condition string tracking paren depth and last connective is sufficient — do NOT build a full AST.
2. `_parse_condition_refs` returns `(event, job_name, or_group: int | None)`; `_add_condition_edges` passes structure through:
   - node metadata: `condition_logic: <str>`, `condition_or_group_count: <int>`.
   - edge: append `|or_group=<n>` to `native_relation` (e.g. `condition_success|or_group=1`) so no Edge schema change is needed and edge ids stay stable for pure-AND conditions.
3. Emit one graph warning per `mixed`/`unknown` job: `"Job X has non-trivial condition logic (<logic>); review manually for Stonebranch migration."`

## Acceptance
`tests/test_condition_logic.py` driving the parser on inline JIL text: `s(a) & s(b)` ⇒ and, no groups; `s(a) | s(b)` ⇒ or, both group 0; `s(a) & (s(b) | s(c))` ⇒ mixed, b,c share group, a none; edge count unchanged vs today. Pytest green. Report: test summary + one sample edge `native_relation`.
