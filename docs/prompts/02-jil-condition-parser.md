# Prompt 02 — Full boolean JIL condition parser + raw-record API

## Objective

Replace the flat regex extraction of AutoSys `condition:` strings with a real boolean parser
producing `expr.Expr` trees, and expose the parsed raw JIL records so the skeleton builder
(prompt 03) can consume them without re-parsing files. Legacy edge output of
`AutosysJilParser.parse()` must remain behaviorally unchanged (edges are now *derived from
atoms* instead of the old regex).

## Context — read ONLY these

1. `stonebranch_graph/expr.py` (created by prompt 01) — public API only.
2. `stonebranch_graph/parsers/autosys_jil.py` — full file.
3. `docs/mapping-theory.md` §3 (AutoSys → skeleton table) and §6 rows about lookback /
   `notrunning` / `terminated`.
4. `examples/jil/PROD/sample.jil` — smoke-test input.

## Requirements

### A. Condition grammar (new function in `autosys_jil.py` or a small helper module `stonebranch_graph/jil_condition.py` — prefer the separate module)

Implement `parse_jil_condition(text: str) -> Expr` supporting real AutoSys JIL syntax:

1. Atoms: `s(NAME)`, `success(NAME)`, `f/failure`, `d/done`, `t/terminated`, `n/notrunning`
   — case-insensitive; map to predicates `SUCCESS/FAILURE/DONE/TERMINATED/NOT_RUNNING`.
2. Lookback: `s(NAME, 12.00)` / `s(NAME,04.00)` → qualifier normalized to `HH:MM`
   (`04.00` → `"04:00"`; integer form `s(J,24)` → `"24:00"`). Keep the atom, keep the window.
3. Cross-instance: `s(JOB^PRD)` → `node_ref = "ext:PRD/" + logical_leaf(JOB)"` using
   `skeleton.logical_leaf`; same for all predicates.
4. Exit codes: `exitcode(NAME) <op> <int>` where `<op>` ∈ `= == != < <= > >=` → predicate
   `EXIT`, qualifier `"<op><int>"` normalized (`==` → `=`). Global-variable conditions
   (`v(NAME) = X` / `value(...)`) are **not dependency logic** (mapping-theory §3 treats them
   like date_conditions): drop the atom from its AND/OR context with a warning naming the job
   and variable; same for any unknown function name. Never crash on them.
5. Operators: `&`/`AND`, `|`/`OR`, parentheses, optional `!`/`NOT` prefix on a term.
   Whitespace-insensitive. Names may contain `. - _ # $` and digits; quoted names allowed.
6. Output is passed through `expr.canonicalize` before returning.
7. Errors: raise `JilConditionError(message, position)`; callers catch it and fall back.

### B. Wire into `AutosysJilParser`

1. In `_add_condition_edges`: call the new parser. On success, derive the legacy
   `depends_on_*` edges by iterating `expr.atoms(...)` — the relation mapping is the existing
   event→REL table; for `ext:` atoms keep creating the synthetic node exactly as today
   (name = original `JOB^INSTANCE` text) so legacy output stays stable. On
   `JilConditionError`, fall back to the current `CONDITION_RE` path and append a warning
   `"JIL condition parsed in legacy mode for job X: <reason>"`.
2. Store on the job node metadata: `condition_expr` = `expr.render(parsed)` (always — this is
   not gated by `include_raw_values`; a rendered logic string is not a secret, unlike raw
   command text) and keep the existing `condition_hash`.
3. Do **not** change node ids, edge ids, or existing metadata keys — downstream compare and
   exporters depend on them.

### C. Raw-record API

1. Add `AutosysJilParser.parse_raw(input_path: Path) -> list[JilJob]` — runs the existing
   file loading + `_parse_file` and returns the `JilJob` records (plus populate
   `self._job_counts_by_source_file` so `_inferred_box_name_for_job` works). Refactor
   `parse()` to use it internally. `JilJob` gains no new fields.
2. Make `JilJob` importable from the module top level (it already is — just don't break it).

### D. Tests — `tests/test_jil_condition.py`

- `s(A) & (d(B) | f(C))` → render `AND(a:SUCCESS, OR(b:DONE, c:FAILURE))` (note: refs here are
  raw normalized leaves; containment-path prefixing happens later in prompt 03 — atoms at this
  stage hold `logical_leaf(name)`).
- Lookback and `^INSTANCE` and exitcode forms per A.2–A.4.
- Operator precedence: `a & b | c` == `OR(AND(a,b), c)` (AutoSys `&` binds tighter than `|`).
- Legacy-fallback: malformed input produces a warning and the same edges as before.
- `parse()` on `examples/jil/PROD/sample.jil` yields the same node and edge id sets as the
  current code (capture with a quick before/after run, assert counts + a few known edges:
  `JOB_B depends_on_success JOB_A`, `JOB_C depends_on_done JOB_B`, `BOX_MAIN contains JOB_C`).

## Out of scope

Skeleton building (prompt 03), Stonebranch side, compare, viewer, performance work beyond not
introducing new O(N²) loops.

## Acceptance criteria

1. New tests pass; `ruff check` clean on changed files.
2. `python -m stonebranch_graph.cli build-jil examples/jil -o /tmp/jil-out` completes
   (`input` is positional; see `add_source_output` in `cli.py`); `graph.json` node/edge
   counts unchanged vs current main.
3. Every job with a `condition` attribute has `condition_expr` in its node metadata.

## Cost guidance

Read only the listed context. The tokenizer+parser is ~150 lines — write it in one pass with
tests alongside; iterate on test failures rather than re-reading source files. Do not run the
Stonebranch parser or comparison at all.
