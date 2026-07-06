# Reconciliation Export Improvement Plan

## Goal

Make the JSON reconciliation export between **AutoSys (JIL)** and **Stonebranch**
produce a clean, apples-to-apples object diff. Today a Notepad++ diff of the two
exports shows a huge, misleading difference because the files carry per-system
noise (internal IDs, content hashes, `-tm` task-monitor suffixes, `source_file`
paths, `attributes_hash`, `metadata`). After this change, the same logical object
must serialize identically on both sides, so a diff shows **only** the objects
that are genuinely missing or extra after migration.

## Root cause (verified in code)

The tool already has most of the machinery, so this is a *finishing* job, not a
rewrite. Two concrete gaps:

1. **Canonical key does not strip migration noise.**
   `make_canonical_key` (`core.py`) → `env:kind:normalize_name(comparison_name(name))`.
   `comparison_name` only strips the enterprise business-code/env token
   (e.g. `IB_CT_CVA_1109_P1_REAL_JOB` → `REAL_JOB`). It does **not** strip the
   Stonebranch `-tm` / task-monitor suffix or trailing content hashes, so a
   Stonebranch object and its AutoSys twin get different keys and are reported
   as missing on both sides.

2. **The diff-friendly view still contains per-system fields.**
   `build_canonical_graph_view` (`exporters.py`) emits `source_file`,
   `attributes_hash`, `metadata`, and `source_system` per node. Even when two
   objects match, these fields differ, so a raw text diff explodes.

Everything else needed already exists and will be reused:
- Set-based reconciliation: `compare_graphs` (`compare.py`) already computes
  `missing_in_sb`, `missing_in_jil`, `matched_keys` from canonical keys.
- Key normalization hook: `normalize_key` (`compare.py`) already applies
  `kind_aliases`, `comparison_kind`, `env_map`, and a config-driven
  `name_rewrites` regex list (`MappingConfig.name_rewrites`).
- Deterministic serialization: `write_canonical_json` already sorts keys and
  writes stable output.

## Design decision: what "one format" means

Reconcile on a **lightweight canonical ID**, not on the raw object body:

```
canonical_id = "<kind>:<name>"
```

where:
- `kind` is collapsed to the shared migration concept (`workflow`→`box`,
  `file_watcher`→`task`, `agent_cluster`→`agent`) — reuse `comparison_kind`.
- `name` is `normalize_name(comparison_name(name))` with migration-noise
  suffixes stripped (`-tm`, `_tm`, task-monitor markers, trailing
  `-<hex-hash>`), driven by a **config list** so new patterns need no code
  change.
- `env` is included only when `env_aware` is on (it already normalizes via
  `env_map`); otherwise omit it so single-env exports don't diff on the label.

Original `Node.name` / `Node.id` / `metadata` stay untouched in `graph.json` —
this only affects the reconciliation view, so the graph report is unaffected.

## Deliverables

1. **`autosys.keys.json` + `stonebranch.keys.json`** (the core ask) — generated
   **together with each graph**, at build time, one file per system, written
   next to that system's `graph.html` / `graph.json`. Each file is a flat,
   ascending-sorted **JSON array of ID strings and nothing else** — one ID per
   object, no `kind` wrapper objects, no `metadata`, no `source_file`, no
   `attributes_hash`, no hashes. Example:

   ```json
   [
     "box:real_archive",
     "task:real_extract",
     "task:real_load"
   ]
   ```

   Same object ⇒ byte-identical line on both sides ⇒ a Notepad++ diff shows only
   genuine adds/drops, with zero migration junk carried along.

2. **`reconciliation.json`** (secondary, no diff tool needed) — one file emitted
   by the compare step, three sorted arrays: `only_in_autosys`,
   `only_in_stonebranch`, `matched`. Directly answers "what's missing / extra
   after migration."

The two key files are the primary artifact and are produced during normal graph
generation; `reconciliation.json` is a convenience computed from them (or from
`compare_graphs`) so you don't have to diff manually.

## Work breakdown (ordered for cheap agentic execution)

### Step 0 — Evidence snapshot (cheap, do first)
Run the existing compare on `examples/` and on one real export pair, then grep
the current canonical view for `-tm` and hash-suffixed names. Capture 3–5 real
example names that fail to match. This pins the exact suffix patterns before
touching code and gives regression fixtures.
*Cost note:* read-only; reuses bundled offline examples, no rebuild.

### Step 1 — Suffix-stripping normalizer (small, pure, tested)
Add `strip_migration_suffixes(name: str, patterns: list[str]) -> str` next to
`comparison_name` in `core.py`. Default pattern list (config-overridable):
`-tm` / `_tm` / `-taskmonitor` (case-insensitive, end-anchored) and a trailing
`[-_][0-9a-f]{8,}` hash. Pure function, unit-tested in isolation.
*Cost note:* one function, one focused test file; no wiring yet.

### Step 2 — Feed it into the canonical key path
Apply the normalizer inside `normalize_key` (`compare.py`) and
`make_canonical_key` (`core.py`) so both the reconciliation keys and the
diff-view keys benefit. Source the pattern list from `AnalyzerConfig` /
`MappingConfig` (new optional `suffix_strips` field, defaulting to Step 1's
list). Reuse the existing `name_rewrites` mechanism where possible instead of
adding a parallel path.
*Cost note:* config-driven ⇒ future suffix variants are a settings edit, not a
code change or another agent run.

### Step 3 — Lightweight key-list exporter, emitted at graph-build time
Add `export_reconciliation_keys(graph, path)` in `exporters.py`: project each
in-scope node (`JOB_LIKE_KINDS` + referenced `INFRASTRUCTURE_KINDS`, excluding
`ARTIFACT_NODE_KINDS` and `SYSTEM_SPECIFIC_KINDS`) to its canonical ID string,
dedupe, sort ascending, write as a **plain JSON array of strings** via
`write_canonical_json`. The output contains the ID and nothing else — no object
wrappers, no metadata.

Call it from the **graph-generation path**, not only the compare path: wherever
each system's graph JSON is written today (the `export_graph_data_json` /
`export_canonical_graph_json` calls in `html_graph.py` / `exporters.py`), also
emit `<system>.keys.json` next to it. This is the key change from the previous
draft — the reconciliation file is a first-class output of building a graph, so
it never picks up compare-time or per-system junk.
*Cost note:* reuses existing scope sets from `domain.py` and the existing write
path; no new scoping logic and no separate command to run.

### Step 4 — Single reconciliation report
Add `export_reconciliation_report(comparison, path)` that serializes the already
computed `missing_in_sb` / `missing_in_jil` / `matched_keys` from `compare_graphs`
into the `only_in_autosys` / `only_in_stonebranch` / `matched` shape. No new
comparison math — just a serializer over existing results.

### Step 5 — Wire into CLI + TUI + settings
`<system>.keys.json` rides along automatically wherever a graph is built
(`build-stonebranch`, `build-autosys`, and their TUI actions) — no new command.
`reconciliation.json` is emitted from the existing `compare` path (`cli.py` +
TUI compare action). Respect `env_aware` and `mapping_path` settings already in
`.stonebranch-tool-settings.json`.

### Step 6 — Verification (required before hand-off)
- Unit tests for `strip_migration_suffixes` (each pattern + no-op cases).
- Golden test: build both example graphs, export keys, assert `only_in_*` is
  empty for objects that are known twins, and assert `autosys.keys.json` vs
  `stonebranch.keys.json` diff contains **only** the intentionally divergent
  fixtures.
- Byte-level check: same logical object ⇒ identical line in both key files.
- Run offline (no network), consistent with the project's zero-dependency design.
*Cost note:* one agent pass runs Steps 1–6 tests together on bundled examples.

## Out of scope
- No change to `graph.json`, the HTML graph report, or node/edge internal IDs.
- No attribute-level (command/condition/hash) diffing changes — this plan is
  object-presence reconciliation only. Attribute drift stays in the existing
  `attributes` comparison.

## Open questions for review
1. **Primary artifact:** keep the two-file Notepad++ diff as the main workflow,
   or move to the single `reconciliation.json` and treat the key files as
   secondary? (Plan delivers both; this only sets emphasis/docs.)
2. **`-tm` semantics:** confirm `-tm` = Stonebranch Task Monitor and should be
   folded onto the AutoSys twin. If a task monitor is a *distinct* object with
   no AutoSys counterpart, it should instead be classed under
   `SYSTEM_SPECIFIC_KINDS` (informational), not stripped.
3. **Env in the key:** include `env` in the canonical ID always, or only when
   `env_aware` is enabled? (Plan: only when `env_aware`.)
4. **Hash suffix width:** confirm the trailing-hash pattern (length/charset) from
   the Step 0 evidence so we don't over-strip legitimate names ending in digits.
