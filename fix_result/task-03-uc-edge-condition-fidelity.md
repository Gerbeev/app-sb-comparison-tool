# Task 03 — Unknown UC connector conditions & exit codes are silently coerced to SUCCESS (HIGH)

## Problem
For Stonebranch, the dependency carrier is the workflow connector and its condition
(Success / Failure / exit-code) — `mapping-theory.md` §1, §4. Fidelity of that condition is the
whole basis for a valid migration comparison. Two places lose fidelity by defaulting to `SUCCESS`:

1. `skeleton_stonebranch.py::_edge_predicate` — when the relation is not recognized as
   done/failure/terminated and the raw condition text does not mention a known status, it appends
   a warning and returns `expr.SUCCESS`. An unrecognized conditional-path or custom connector
   therefore becomes a plain success dependency, hiding a real logic difference.
2. `skeleton_stonebranch.py::_exit_qualifier` / `EXIT_CODE_KEYS` — exit-code extraction is
   heuristic: it only reads a `value` key when the condition text contains the substring `exit`,
   and otherwise scans a fixed key list. UC exports vary (`exitCodes`, ranges like `1-4`, operators
   `>=`). Missed exit conditions silently degrade to `SUCCESS` as well.

`IMPLEMENTATION_PLAN.md` §5 explicitly warns: *"unknown shapes must degrade to warnings, never
silent drops."* A warning buried in a list is effectively a silent drop for reconciliation,
because the node still reports as matched.

## Fix
1. **Introduce an explicit `UNKNOWN` sentinel predicate path.** When `_edge_predicate` cannot map
   a condition, do **not** substitute `SUCCESS`. Instead:
   - keep the edge with predicate `SUCCESS` for graph connectivity **but**
   - record the raw condition on the target spec (e.g. `spec.meta["unmapped_conditions"]`), and
   - have `skeleton_compare.build_skeleton_risks` raise a risk and `write_skeleton_report` list
     every node with an unmapped connector condition (id, raw text, source file).
2. **Harden exit-code parsing.** Replace the `"exit" in condition_text` gate with a real matcher:
   accept keys `exitCodes/exit_codes/exitCode/exit_code`, values that are ints, comma lists,
   ranges (`1-4`), and operator forms (`>=N`, `!=N`). Normalize to the same qualifier grammar the
   JIL side emits (`jil_condition._exitcode_expr` produces `"=N"`, `">=N"`, etc.) so exit-code
   comparisons are apples-to-apples. Document the grammar in a module docstring.
3. **Symmetry check with JIL.** Confirm the normalized exit qualifier string is byte-identical for
   the same numeric condition on both sides (`exitcode(J)=4` vs UC exit code `4`). Add a test.

## Acceptance (task 07 fixtures)
- A UC workflow edge with an unrecognized condition string → node appears in a new report section
  and a risk is raised; it is **not** counted as a clean match.
- UC exit code `4` and JIL `exitcode(J) == 4` produce the same strict trigger line for the
  successor.
- UC exit range `1-4` round-trips to a documented qualifier and is preserved at strict level.
