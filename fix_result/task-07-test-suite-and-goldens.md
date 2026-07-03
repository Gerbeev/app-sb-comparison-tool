# Task 07 — No test suite exists; add golden, monitor-erasure, and benchmark tests (HIGH)

## Problem
`pyproject.toml` configures pytest (`testpaths = ["tests"]`) but there is **no `tests/`
directory**. None of the `IMPLEMENTATION_PLAN.md` §6 "Definition of Done" items are verified:
1. the §8 worked example produces byte-identical skeletons at all three levels,
2. a Task Monitor never appears as a node,
3. legacy commands still work,
4. 10k-node benchmark runs in seconds,
5. the viewer renders triggers.

Without these, every other fix in this backlog is unguarded against regression, and there is no
evidence the byte-identical guarantee actually holds on real inputs. This is the single biggest
blocker to trusting the tool for a production migration reconciliation.

## Fix — create `tests/` with at least these modules

### `tests/test_expr.py`
- Canonical flatten/dedupe/sort round-trips (`parse`→`render` idempotent).
- N4: `AND(AND(a:SUCCESS,b:SUCCESS),c:SUCCESS)` → sorted flat AND.
- N5 fold (after task 01): `AND(A:FAILURE, A:SUCCESS)` → `A:DONE`; qualifier mismatch does not fold.
- `substitute`, `success_and_only`, `topology_view/logic_view/strict_view` projections.

### `tests/test_golden_worked_example.py`  (Definition of Done #1 & #2)
- Ship fixtures under `tests/fixtures/`: the §8 scenario as **JIL on one side** and **UC JSON with
  a Task Monitor on the other**, plus an alias file.
- Assert `build → erase_plumbing → to_canonical_jsonl(level)` is **byte-identical** between the two
  systems at `topology`, `logic`, and `strict`.
- Assert no node whose id/native is the Task Monitor survives in either skeleton, and that the
  monitor's condition appears in its successor's trigger.
- Assert the shipped `docs/concept/skeleton-example.json` equals the AutoSys skeleton for the
  matching fixture (guards the concept's golden file).

### `tests/test_normalize_plumbing.py`
- Monitor erased by substitution; Sleep/dummy erased; alias-marked SB gate erased (task 04).
- Unsafe predicate (successor depends on monitor via FAILURE) keeps the node + emits the warning.
- Monitor→monitor cycle is broken with a warning (bounded iterations), not an infinite loop.

### `tests/test_skeleton_compare.py`
- Matched / changed / only_in_* classification per level.
- Collisions surfaced (task 02), unmapped UC conditions surfaced (task 03), external match (task 05).
- `skeleton_metrics` score monotonicity: more topology misses ⇒ lower score.

### `tests/test_benchmark.py`  (Definition of Done #4)
- Generate a synthetic 10k-unit / nested-container set, run parse → build → erase → compare,
  assert wall-clock under a generous CI bound (e.g. < 20 s) and assert no accidental O(N²)
  (scale from 1k→10k and check near-linear growth, e.g. ratio < 15×).

### `tests/test_cli_smoke.py`  (Definition of Done #3 + guards the encoding/packaging issue)
- Invoke `python -m stonebranch_graph.cli compare-skeleton` and the legacy `compare` on the
  bundled `examples/`; assert exit 0 and that expected artifacts are written. This smoke test also
  catches file-encoding / packaging breakage before shipping.

## Acceptance
`pytest -q` is green; the golden test fails loudly if any future change breaks byte-identity;
CI runs the benchmark.
