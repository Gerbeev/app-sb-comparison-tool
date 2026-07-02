# Prompt 07 — Skeleton comparison engine and redesigned report

## Objective

Create `stonebranch_graph/skeleton_compare.py`: compare two skeletons (Stonebranch vs
AutoSys) as **keyed record comparison over canonical lines** with the three strictness levels
from `docs/mapping-theory.md` §5, and redesign the comparison report around it. The current
edge-set comparison in `compare.py` was written without these documents; it stays available
as the legacy engine but the skeleton diff becomes the primary product. Valuable existing
pieces (command semantic-hash diff, infrastructure matching) are retained as a separate
**meta layer** section, excluded from skeleton identity exactly as N7 prescribes.

## Context — read ONLY these

1. `docs/mapping-theory.md` §5 (three levels, canonical serialization paragraph), §6
   (honest mismatch table — these must be *reported*, not silently matched).
2. `docs/mapping-explained.md` §6, §9.
3. `stonebranch_graph/skeleton.py`, `stonebranch_graph/expr.py` — hashes, projections,
   `index_rows`.
4. `stonebranch_graph/compare.py` — only: `Comparison` dataclass, `export_comparison`,
   `write_report`, `build_risks`, `command_difference_payload` (you will reuse the command
   diff by matching meta of paired skeleton nodes).
5. `stonebranch_graph/workflows.py` — `compare_direct` (you add a sibling, not modify it).

## Requirements

### A. Data flow

`compare_skeletons(sb: Skeleton, jil: Skeleton) -> SkeletonComparison`

Node pairing is by skeleton id — nothing else. No fuzzy matching: N1 already moved that
problem to the alias table. Classification per id, computed once per level
(`topology`, `logic`, `strict`) using the per-node hashes from `skeleton.node_hash`:

- `matched` — id in both, hash equal at this level;
- `changed` — id in both, hash differs at this level; payload carries both canonical lines
  plus a field-level reason list: `kind_changed`, `parent_changed`, `trigger_changed`,
  `completion_changed` (strict only), `qualifier_only` (logic-equal but strict-differs);
- `only_in_stonebranch` / `only_in_jil` — with the node's canonical line.

`externals` sets are compared as plain id sets (informational).

### B. Outputs (written by `export_skeleton_comparison(comparison, output_dir, ...)`)

Into `output_dir/compare-skeleton/`:

1. `skeleton-stonebranch.jsonl`, `skeleton-jil.jsonl` — strict canonical serializations
   (these two files are the diffable artifacts; a reviewer can `git diff` them directly —
   state this in the report header).
2. `skeleton-diff.json` — full machine-readable result: per-level summaries + per-node
   entries `{id, status_by_level, reasons, sb_line, jil_line}` sorted by id.
3. `skeleton-index.csv` — `id, side(s), topology_hash_sb, topology_hash_jil, logic_*, strict_*,
   status_topology, status_logic, status_strict` (the O(1) "which nodes changed" table).
4. `report.md` — new structure:
   - header: what the three levels mean (2 lines each);
   - summary table: per level — matched / changed / only-SB / only-JIL counts + match rate;
   - **Plumbing erasure** section: erasure counts per side (from `Skeleton.erasures`),
     kept-with-warning nodes — this is where Task Monitor handling is made visible;
   - **Changed nodes** table (logic level, cap 200 rows): id, reasons, `sb_trigger`,
     `jil_trigger` rendered side by side;
   - **Qualifier-only differences** (strict vs logic delta — the §6 lookback/completion
     cases): explicitly labeled "expected UC gaps: lookback windows, notrunning/terminated,
     box_success overrides" per the honest-mismatch table;
   - **Only in X** tables (cap 200);
   - **Meta layer** section: command diffs for paired ids (strict + semantic hash from node
     meta, reusing the reason vocabulary of `command_difference_payload`), external-ref set
     diff, per-side warnings;
   - **Risks**: reuse the style of `build_risks` with skeleton-specific rules (any
     `only_in_*` at topology level; `trigger_changed` count; kept-plumbing warnings; cycle
     warnings).
5. `remediation-plan.md` — checklist grouped by: create missing objects, rewire triggers
   (show expected trigger line), review qualifier gaps.

### C. Metrics

`skeleton_metrics(comparison) -> dict` — per level match rates, counts, plus
`skeleton_readiness_score` (reuse the penalty-weight idea from `metrics.py` but simpler:
start 100, weighted penalties for topology misses > logic changes > strict-only diffs).
Emit into `compare-skeleton/metrics.json` + `metrics.csv` (reuse `export_csv_rows`,
`metric_rows`).

### D. Orchestration

Add to `workflows.py`:

```
compare_skeleton_direct(*, stonebranch_path, jil_path, output_dir, config,
                        alias_path=None, env="default", env_aware=False) -> CompareSkeletonResult
```

Pipeline: `parse_raw` both sides → builders (prompts 03/04) → `erase_plumbing` both →
`compare_skeletons` → `export_skeleton_comparison`. Also export each side's skeleton next to
the legacy bundles. Reuse logging_utils patterns. Do **not** remove or modify
`compare_direct`; CLI wiring is prompt 10.

### E. Tests — `tests/test_skeleton_compare.py`

1. Identical skeletons → 100% matched at all levels, empty diff files sections.
2. Same topology, one predicate differs → topology matched, logic changed with
   `trigger_changed`.
3. Lookback qualifier present on JIL side only → logic matched, strict changed,
   `qualifier_only` reason.
4. Added/removed node; parent moved (`parent_changed`); unit↔container (`kind_changed`).
5. End-to-end: the prompt-05 equivalence fixtures compared → zero differences; then perturb
   one UC connector condition and assert exactly one `changed` node at logic level.

## Out of scope

Viewer/HTML (prompt 08 consumes `skeleton-diff.json`), CLI/TUI (prompt 10), deleting the
legacy engine.

## Acceptance criteria

1. All tests pass; previous suites pass; `ruff check` clean.
2. `skeleton-*.jsonl` outputs are byte-stable across two runs (no timestamps, no dict-order
   leakage).
3. report.md renders correctly (verify by reading the generated file once in a test run).

## Cost guidance

~350 lines + tests. Classification is hash comparison over dicts — resist any temptation to
diff expressions structurally beyond the reason labels. Cap all report tables. Do not touch
`compare.py` logic; only import from it.
