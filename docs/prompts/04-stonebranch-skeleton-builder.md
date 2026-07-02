# Prompt 04 — Stonebranch → skeleton builder

## Objective

Create `stonebranch_graph/skeleton_stonebranch.py` plus a raw-record API on
`StonebranchJsonParser`: transform UC export JSON into a `Skeleton` per
`docs/mapping-theory.md` §4 and rules N5 (DONE folding), N6 (instance expansion), N7.
Task Monitors are **detected and recorded here but erased in prompt 05** — they must never
become skeleton nodes in the final output; in this step they are emitted as marked plumbing
nodes carrying their monitored condition, ready for substitution.

## Context — read ONLY these

1. `docs/mapping-theory.md` §4, §5 (N5, N6), §2.2–2.3.
2. `docs/mapping-explained.md` §2 (the "what is deliberately NOT a node" table) and §8 table
   (how Task Monitor rows land in the skeleton).
3. `stonebranch_graph/expr.py`, `stonebranch_graph/skeleton.py` — public APIs.
4. `stonebranch_graph/parsers/stonebranch_json.py` — full file (you will add a raw API and
   reuse: `_kind_from_path`, `WORKFLOW_VERTEX_KEYS`, `WORKFLOW_EDGE_KEYS`,
   `WORKFLOW_NATIVE_TYPES`, `_normalized_type_token`, `_workflow_task_name`,
   `_workflow_edge_relation` field lists, `_structure_value`).
5. `stonebranch_graph/config.py` — `STONEBRANCH_FOLDER_KIND_MAP`, `STONEBRANCH_TYPE_KEYS`.

## Requirements

### A. Raw-record API on the existing parser

Add `StonebranchJsonParser.parse_raw(input_path) -> StonebranchRawExport` where
`StonebranchRawExport` (dataclass in the parser module) holds:
`records: list[RawRecord]` with `RawRecord(kind, native_type, name, env, source_file, data)`
(kind from folder map + `_effective_kind` promotion, `data` = the raw dict), and
`warnings: list[str]`. Refactor `parse()` to consume `parse_raw()` internally; legacy graph
output must not change (verify via the acceptance run).

### B. Builder — `build_stonebranch_skeleton(raw: StonebranchRawExport, *, alias: AliasTable | None = None, config: AnalyzerConfig) -> Skeleton`

Use the same `AliasTable` protocol as prompt 03; system string `"stonebranch"`.

1. **Node kinds.** Workflow records (folder `workflows/` or native type in
   `WORKFLOW_NATIVE_TYPES`) → `KIND_CONTAINER`. Every task record of any native type →
   `KIND_UNIT`, with two special classes detected by normalized native type token:
   - `taskmonitor` (match tokens `{"taskmonitor", "taskmonitortask"}`) → unit with
     `meta["plumbing"] = "task_monitor"` and `meta["monitor"]` (see B.5);
   - sleep/dummy (tokens `{"sleep", "sleeptask", "timer"}`) → unit with
     `meta["plumbing"] = "sleep"`.
   Objects that are not workflows or tasks (agents, calendars, credentials, variables,
   triggers, scripts, email templates, connections) are **not skeleton nodes at all** (§4:
   triggers/resources are metadata) — skip them entirely.
2. **Containment & instance expansion (N6).** Workflows contain tasks via
   `workflowVertices`. Build a definition registry first (task/workflow definitions by name),
   then **expand instances**: for each top-level workflow (not used as a sub-workflow of
   another) walk its vertex tree; when a vertex names another workflow definition, inline it
   as a nested container with a path-qualified id (`parentwf/childwf`, then
   `parentwf/childwf/task`). The same definition used in N parents produces N instances. Guard
   against recursion (workflow containing itself directly or transitively): stop, warn, keep
   the first occurrence.
   Tasks that belong to no workflow become root units. Task definitions referenced by several
   workflows are likewise expanded per instance (same task in two workflows = two skeleton
   nodes with different path ids — comparison is about instantiated logic).
3. **Triggers from connectors.** For each workflow instance, map `workflowEdges`:
   an edge predecessor→successor with condition c contributes atom
   `(predecessor_instance_id, PREDICATE(c))` to the **successor's** trigger. Multiple incoming
   connectors → `And(...)` (§4: documented UC AND semantics). Condition mapping: Success →
   SUCCESS, Failure → FAILURE, single edge whose condition names both → DONE (existing
   `_workflow_edge_relation` logic), exit-code conditions (look for keys like `exitCodes`,
   `exit_code`, `value`) → EXIT with qualifier; unknown condition text → SUCCESS + warning.
4. **N5 folding.** After collecting a node's atoms, apply `expr.fold_done` so parallel
   Success+Failure connectors from the same predecessor collapse to one DONE atom, then
   `canonicalize`.
5. **Task Monitor payload.** For a task-monitor record, extract into `meta["monitor"]`:
   `{"target": <monitored task/workflow name>, "predicate": <mapped status>, "external": bool}`.
   Field names vary by UC version — use a configurable key list (module constant), trying:
   task name keys `("taskMonitoredName", "taskName", "taskMonName", "monitoredTask")` and
   status keys `("statuses", "status", "taskMonStatus", "monitorStatus")`. Status mapping:
   Success→SUCCESS, Failure→FAILURE, Finished/Success,Failure→DONE, Cancelled→TERMINATED,
   anything else→SUCCESS + warning. If the monitored name resolves to a node in this skeleton,
   `target` is its instance id (prefer an instance in the same workflow, else the unique
   instance, else warn + first); if it resolves to nothing, `target` = `ext:` +
   `logical_leaf(name)` and `external=true`. **Do not** create dependency atoms from the
   monitor here — prompt 05 substitutes them.
6. **Ids & aliases.** Leaf = `alias.logical_id("stonebranch", native_name)`'s last segment or
   `logical_leaf(native_name)`; ids are containment paths via `skeleton.child_id`. Full-path
   alias values win verbatim (same rule as prompt 03 B.2).
7. **Meta (N7).** `meta = {"src": "stonebranch", "native": <name>}` + `type`, `source_file`,
   command hashes when a command/script field exists (reuse `normalizers`). UC triggers,
   virtual resources, run criteria, credentials, agents, calendars: excluded from skeleton
   and from meta.

### C. Tests — `tests/test_skeleton_stonebranch.py`

In-code JSON dict fixtures (no files):

1. Workflow ETL with vertices extract/transform/load and Success connectors → triggers
   matching `docs/skeleton-example.json` lines for `etl/*`.
2. Parallel Success+Failure connectors from same predecessor → single DONE atom (N5).
3. Sub-workflow reused by two parents → two inlined instances with distinct path ids (N6);
   recursion guard test.
4. Task Monitor record → node has `meta["plumbing"]=="task_monitor"` and a correct
   `meta["monitor"]` payload for: internal target, cross-workflow target, unresolved target
   (`ext:`), and a "Success,Failure" status → DONE.
5. Agents/calendars/triggers records produce no skeleton nodes.

## Out of scope

Erasure/fixpoint (prompt 05), alias loading (06), comparison (07), viewer, legacy parser
behavior changes beyond adding `parse_raw`.

## Acceptance criteria

1. New tests pass; prompt 01 tests still pass; `ruff check` clean.
2. `build-stonebranch` CLI run on `examples/stonebranch` produces identical `graph.json` to
   current main (raw API refactor is behavior-neutral).
3. No skeleton output path can emit an agent/calendar/trigger/credential node.

## Cost guidance

This is the largest builder (~300 lines) — write it in at most two passes. Reuse the parser's
existing key-list constants instead of inventing new ones. Test with in-memory dicts; do not
create fixture files. Do not run the comparison pipeline.
