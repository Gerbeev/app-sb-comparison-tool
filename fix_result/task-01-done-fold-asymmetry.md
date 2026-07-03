# Task 01 — DONE-folding is asymmetric between the two builders (HIGH)

## Problem
Concept rule **N5** (`mapping-theory.md` §5): *"`done` stays `DONE` … but the UC pattern
'connector on Success and parallel connector on Failure from the same predecessor' is folded up
to `DONE`. Always desugar toward the coarser shared vocabulary so both sides land on the same
token."*

The Stonebranch builder folds `SUCCESS`+`FAILURE` on the same predecessor into `DONE`:
`skeleton_stonebranch.py::_trigger_expression` calls `expr.fold_done(pairs)`.

The AutoSys builder does **not**. `skeleton_autosys.py` parses `condition:` via
`jil_condition.parse_jil_condition_details` and canonicalizes, but never calls `fold_done`.
Therefore a JIL condition `s(A) & f(A)` canonicalizes to `AND(A:FAILURE, A:SUCCESS)`, while the
equivalent UC parallel connectors canonicalize to `A:DONE`.

**Consequence:** identical migration logic produces different canonical bytes → false
`trigger_changed` diffs on every job that waits on both the success and failure of the same
predecessor. This defeats the core "same logic ⇒ same file" guarantee for a common idiom.

## Root cause
`fold_done` is applied per-builder instead of inside the shared canonical form. `expr.canonicalize`
(in `expr.py`) flattens/sorts/dedupes but never folds `SUCCESS`+`FAILURE`→`DONE`.

## Fix
Make the fold part of the **shared** canonicalizer so both sides land on the same token.

1. In `stonebranch_graph/expr.py`, extend `_canonical_nary` (the `And` path only) so that, after
   flattening and dedupe, any pair of sibling atoms `Atom(ref, SUCCESS, q)` **and**
   `Atom(ref, FAILURE, q)` with the **same** `node_ref` and `qualifier` is replaced by a single
   `Atom(ref, DONE, q)`. Only apply inside `And` (never `Or` — `s(A) | f(A)` is not "done").
   Re-sort after folding. Keep the existing `fold_done` function working (it can delegate to a
   shared helper) so `skeleton_stonebranch.py` behavior is unchanged.
2. Because `canonicalize` is `@lru_cache`d on immutable trees, no perf regression; just ensure the
   fold is deterministic (sort atoms before folding).
3. Leave `Or` and mixed nestings alone — no DNF (N4 forbids aggressive minimization).

## Edge cases to preserve
- `AND(A:SUCCESS, A:FAILURE, B:SUCCESS)` → `AND(A:DONE, B:SUCCESS)`.
- Qualifier must match: `AND(A:SUCCESS[04:00], A:FAILURE)` must **not** fold (different qualifier).
- `EXIT` atoms never participate.
- Folding must run after n-ary flatten so `AND(AND(A:SUCCESS), A:FAILURE)` also folds.

## Acceptance
Add to the new test suite (task 07):
- `expr.render(expr.parse("AND(A:FAILURE, A:SUCCESS)")) == "A:DONE"`.
- A JIL fixture job with `condition: s(A) & f(A)` and a UC fixture with parallel Success+Failure
  connectors from `A` produce the **same** strict canonical line for that node.
- Existing `fold_done` unit behavior unchanged.
