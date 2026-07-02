# Agent prompt — Item 9: Comparison integration & triage ranking

You are implementing Item 9 of `GRAPH_SKELETON_IMPLEMENTATION_PLAN.md`. Items 1–5 merged. Goal: keep derived/inferred edges out of migration match rates; add an informational watcher section; rank triage by criticality.

## Token budget rules
`compare.py` is ~1200 lines — do NOT read it whole. Grep for `COMPARABLE_EDGE_RELATIONS`, `ARTIFACT_EDGE_RELATIONS`, `watches_file`, and read only the matched functions. Same for `triage.py`: grep for the mismatch-list assembly function and read only it. Read `domain.py` constants block. Minimal diff.

## Task
1. **Exclusion audit**: verify (and fix if needed) that `produces_file` / `data_depends_on` edges can never enter edge diff or edge match rate — they are in `ARTIFACT_EDGE_RELATIONS` per Item 1; confirm every edge-diff code path filters through the domain sets rather than ad-hoc relation lists. Add a defensive filter `if edge.derived: skip` at the edge-diff entry point.
2. **Informational section** in the comparison payload (follow the existing shape for informational counts): per side — watcher counts by classification (`internal/external/ambiguous`, computed like Item 7 from produces/watches edges), plus a list `watcher_simplification_opportunities`: JIL file watchers classified `internal` whose producer job also exists (matched) in Stonebranch — meaning the watcher could become a direct workflow edge. Not a mismatch; a labeled opportunity list `{watcher_key, file_key, producer_key, confidence}`.
3. **Triage ranking**: where triage assembles ordered mismatch lists, if a skeleton criticality map is available (compute once via `build_skeleton` + `score_skeleton` on the JIL graph, guarded by try/except → fall back to current order), sort each list by `criticality` desc, then existing order. Add `criticality` field to triage items when available.

## Acceptance
Existing comparison fixtures/snapshots must produce identical match rates (run whatever comparison the CLI offers on `examples/` before and after; diff the summary numbers). New tests: `tests/test_compare_watchers.py` — synthetic pair of graphs where JIL has internal-fed watcher matched in SB ⇒ one opportunity entry; derived edge injected into a graph ⇒ zero effect on edge match rate. Pytest green. Report: before/after match-rate diff (must be empty) + test summary.
