# Prompt 03 — AutoSys → skeleton builder

## Objective

Create `stonebranch_graph/skeleton_autosys.py`: transform raw JIL records (`JilJob` list from
`AutosysJilParser.parse_raw`, prompt 02) into a `Skeleton` per `docs/mapping-theory.md` §3 and
rules N2, N7, plus the completion-override rule from §2.3.

## Context — read ONLY these

1. `docs/mapping-theory.md` §2.3, §3, §5 (N1–N7 list; N1/N3 are applied later — here you only
   prepare hooks), §7.
2. `stonebranch_graph/expr.py`, `stonebranch_graph/skeleton.py` — public APIs.
3. `stonebranch_graph/jil_condition.py` (or wherever prompt 02 put `parse_jil_condition`).
4. `stonebranch_graph/parsers/autosys_jil.py` — only `JilJob`, `parse_raw`, `_job_kind`
   mapping table (reproduce the job_type mapping; do not import private methods).

## Requirements

### A. Public API

`build_autosys_skeleton(jobs: list[JilJob], *, alias: AliasTable | None = None) -> Skeleton`

`AliasTable` does not exist yet (prompt 06); define a minimal protocol here:
`alias.logical_id(system: str, native_name: str) -> str | None` and
`alias.is_plumbing(system: str, native_name: str) -> bool`. When `alias` is None or returns
None, fall back to derived ids. System string: `"autosys"`.

### B. Mapping rules (§3 table, implement all rows)

1. `job_type: b/box` → `KIND_CONTAINER`; every other job type (`c`, `cmd`, `f`, `fw`, custom)
   → `KIND_UNIT`. Native job type goes to `meta["type"]`; it is **not** part of the skeleton
   identity (two kinds only — docs §2.1).
2. Containment: resolve `box_name` chains to build the containment forest first (two passes:
   pass 1 registers all jobs by native name; pass 2 computes each node's id as the
   containment path `child_id(parent_id, leaf)` where `leaf` = alias logical id's last segment
   or `logical_leaf(native_name)`). Boxes nested in boxes → nested containers. Jobs without a
   box → root nodes (`parent=None`). A `box_name` referencing an undefined box: create a
   synthetic container with `meta["synthetic"]=true` + warning.
   If an alias returns a **full path** logical id, use it verbatim as the node id (it wins
   over the derived containment path); still set `parent` from actual containment.
3. Trigger: `parse_jil_condition` on the `condition` attribute. Then rewrite each atom's
   `node_ref` from a native leaf to the referenced node's **skeleton id** via the pass-1 name
   registry (conditions name jobs by native name, anywhere in the forest). Unresolvable refs
   → keep `logical_leaf(name)` as-is and let `Skeleton.validate()` register them as externals.
   `ext:` refs from `^INSTANCE` pass through untouched.
4. **N2**: drop any atom that references the node's own ancestor container (a job restating
   "my box is running/started" — and an ancestor SUCCESS ref is a deadlock restatement, also
   noise) — remove the atom from its AND context with a warning; if it was the whole trigger,
   trigger becomes `None`. Only drop ancestor refs, never arbitrary containers.
5. Conditions **on a box** and conditions **referencing a box** are legal as-is (atom node_ref
   = container id) — no rewriting to children (explicitly forbidden, mapping-explained §11).
6. Completion override (§2.3): if a box job has a `box_success` attribute, parse it with
   `parse_jil_condition` and store it as the container's `completion` expression. If only
   `box_failure` is present, store `completion = Not(parsed(box_failure))`. If both are
   present, use `box_success` and add a warning (rare, ambiguous). UC has no analog, so any
   non-null `completion` will surface at strict level — add a code comment citing §6
   ("strict diff flags it, correctly").
7. Metadata (N7): `meta = {"src": "autosys", "native": <original job name>}` plus `type`,
   `source_file`, and the existing hashes if cheap (`command_hash`, `semantic_command_hash`
   — compute via `normalizers` only when a `command` attribute exists). `date_conditions`,
   `start_times`, calendars, `machine`, `owner`, `priority`, alarms: **excluded from the
   skeleton entirely** — do not even copy them into meta (the exploration graph already has
   them; skeleton meta stays small for thousands of nodes).
8. Plumbing hook: if `alias.is_plumbing("autosys", name)` is true for a job, still build the
   node but set `meta["plumbing"] = true`. Erasure itself happens in prompt 05.
9. Duplicate job names (JIL update_job of same name is already merged upstream; true
   duplicates): keep first, warning — mirror parser behavior.

### C. Tests — `tests/test_skeleton_autosys.py`

Build fixtures in-code (list[JilJob]); no files needed:

1. The mapping-theory §8-style scenario: boxes ETL(extract→transform→load), REPORTING
   (build_report←s(ETL), publish←s(build_report)), ARCHIVE(copy_files←s(LOAD)). Assert the
   canonical JSONL equals the 9 lines of `docs/skeleton-example.json` (ids, parents,
   triggers) — this is the golden test for the whole AutoSys side.
2. N2: job inside BOX whose condition includes an atom referencing BOX itself →
   the ancestor atom is dropped (with warning), the rest of the expression survives.
3. Nested boxes → nested path ids (`a/b/c`).
4. `^PRD` external ref appears in `externals` and in the trigger as `ext:prd/...`.
5. box_success override → `completion` set; strict view includes it, logic view of the
   *trigger* unaffected.

## Out of scope

Stonebranch side, N3 erasure, alias file loading, comparison, CLI.

## Acceptance criteria

1. Golden test (C.1) byte-identical output.
2. All new tests + prompt 01/02 test files still pass.
3. `ruff check` clean on new files.

## Cost guidance

Two-pass algorithm, single module ~200 lines. Do not modify the parser beyond what prompt 02
already provides. If C.1 output mismatches, diff the two strings in the test output instead of
re-reading docs.
