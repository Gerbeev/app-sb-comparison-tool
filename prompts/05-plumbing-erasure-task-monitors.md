# Prompt 05 — Plumbing erasure (N3): Task Monitors, sleep tasks, gate jobs

## Objective

Create `stonebranch_graph/skeleton_normalize.py` implementing normalization rule **N3** from
`docs/mapping-theory.md` §5: nodes that carry no business action, only dependency glue, are
removed **by substitution** — every successor inherits the erased node's own trigger or
monitored condition — repeated until fixpoint. This is the single most important correctness
rule of the whole migration comparison: **a Stonebranch Task Monitor is a dependency, not a
node.** After erasure, a UC cross-workflow monitor pattern must be structurally identical to
an AutoSys cross-box condition.

## Context — read ONLY these

1. `docs/mapping-theory.md` §4 (Task Monitor row), §5 N3, §8 worked example.
2. `docs/mapping-explained.md` §2 ("What is deliberately NOT a node") and §8 (the two
   Task-Monitor rows of the mapping table).
3. `stonebranch_graph/expr.py`, `stonebranch_graph/skeleton.py` — public APIs.
4. `stonebranch_graph/skeleton_stonebranch.py` — the `meta["plumbing"]` / `meta["monitor"]`
   contracts from prompt 04.
5. `stonebranch_graph/skeleton_autosys.py` — the `meta["plumbing"]` hook from prompt 03.

## Requirements

### A. Public API

`erase_plumbing(skeleton: Skeleton) -> Skeleton` — pure function, returns a new Skeleton;
input untouched. Applies to both systems' skeletons (UC monitors/sleeps, AutoSys gate jobs
marked via alias table).

### B. Semantics

1. **Which nodes are erased:** any node with `meta["plumbing"]` set (values today:
   `"task_monitor"`, `"sleep"`, `true` for alias-marked gate jobs). Containers are never
   erased even if marked (warn instead).
2. **Replacement expression** for an erased node E:
   - Task Monitor: the atom `(meta.monitor.target, meta.monitor.predicate)` — AND-combined
     with E's own trigger if E also had incoming connectors (a monitor placed mid-workflow
     waits for both);
   - sleep/gate: E's own trigger; if E has no trigger, the replacement is "nothing"
     (dependency on E simply disappears — a pure delay/no-op gate contributes no logic).
3. **Substitution:** for every other node whose trigger (or completion) contains an atom
   referencing E:
   - if the atom's predicate is `SUCCESS` or `DONE`: replace the atom in place with E's
     replacement expression (wrapping preserved — inside `AND`/`OR` the replacement is
     spliced as a subtree, then re-canonicalized);
   - if the predicate is `FAILURE`/`TERMINATED`/`NOT_RUNNING`/`EXIT`: the wait is on the
     *plumbing node's own state*, which has no meaning after erasure — substitute for
     monitors with the monitored condition's negation-free best effort: monitor FAILURE ≈
     target NOT reached; there is no sound mapping, so **keep the node instead**: demote to
     a real unit, drop `meta["plumbing"]`, append warning
     `"kept plumbing node <id>: depended on with predicate <P>"`. Correctness over cleverness.
4. **Fixpoint:** repeat until no plumbing nodes remain (monitor watching a monitor, gate
   chained to gate). Guard: max `len(nodes)` iterations; on cycle (E's replacement transitively
   references E), keep the cycle members as real units + warning.
5. **Containment cleanup:** erased node's children (shouldn't exist for units — assert) n/a;
   erased node is removed from `nodes`; its `parent` link disappears. `ext:` targets
   referenced by surviving triggers are registered via `Skeleton.validate()`.
6. **Determinism:** iterate nodes in sorted-id order; resulting skeleton canonical JSONL must
   be stable across runs.
7. Record erasure evidence: surviving successor nodes get nothing added to meta (meta is not
   compared and must stay small), but the Skeleton `warnings`/an `erasures: list[dict]`
   attribute (id, kind of plumbing, replaced_in: [ids]) is populated for diagnostics; the
   compare report (prompt 07) will surface counts.

### C. The docs' equivalence test (the point of it all)

Combined golden test `tests/test_plumbing_erasure.py::test_worked_example_equivalence`:

- AutoSys side: build the §8 skeleton via `build_autosys_skeleton` (fixtures from prompt 03
  test 1).
- Stonebranch side: same logic expressed the UC way — workflows ETL/REPORTING/ARCHIVE;
  `build_report` fed by a Task Monitor watching workflow `ETL` (status Success);
  `copy_files` fed by a Task Monitor watching task `load`.
- After `erase_plumbing` on the SB skeleton: `to_canonical_jsonl("strict")` of both sides is
  **byte-identical** and equals the 9 lines of `docs/skeleton-example.json`.

Additional tests: monitor-of-monitor chain (fixpoint), monitor depended on with FAILURE
(node kept + warning), sleep task in the middle of a chain (A→sleep→B ⇒ B waits on A),
gate node with no trigger (dependency vanishes), cycle guard.

## Out of scope

Alias loading (prompt 06 wires `is_plumbing` markers), comparison engine, viewer, CLI.

## Acceptance criteria

1. The equivalence golden test passes byte-for-byte.
2. No `plumbing`-marked unit survives in output unless a keep-warning was emitted.
3. All prior test files still pass; `ruff check` clean.

## Cost guidance

~150 lines + tests. The only subtle part is splicing a replacement subtree into a parent
expression — implement as a recursive `substitute(expr, ref_id, replacement) -> Expr | None`
in `expr.py` if cleaner (allowed: small additive change there). Don't re-read builder
internals; rely on their tested contracts.
