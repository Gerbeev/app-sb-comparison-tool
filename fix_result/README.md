# fix_result — conformance & migration-validity backlog

Generated 2026-07-02 from a static review of `stonebranch_graph/` against
`docs/concept/mapping-theory.md`, `docs/concept/mapping-explained.md`,
`docs/concept/skeleton-example.json`, and `docs/IMPLEMENTATION_PLAN.md`.

Scope of the review: does the implemented skeleton pipeline (a) match the documented
concept, and (b) build AutoSys- and Stonebranch-specific graphs correctly enough that a
migration from AutoSys → Stonebranch can be reconciled by comparing the two skeletons?

Each file below is a self-contained task for an agentic coding session. Files carry exact
module/function anchors, the concept rule they enforce, the change, and an acceptance test.
Do them in priority order; tasks are independent unless a "Depends on" line says otherwise.

## Correctness / conformance (do first — these change comparison results)

| # | Task | Severity | Concept rule |
|---|------|----------|--------------|
| 01 | [DONE-folding is asymmetric: JIL side never folds `success+failure`→`DONE`](task-01-done-fold-asymmetry.md) | HIGH | N5 |
| 02 | [Alias/id collisions silently drop nodes (`keep-first`)](task-02-alias-id-collision.md) | HIGH | N1 |
| 03 | [Unknown UC connector conditions & exit codes silently coerced to `SUCCESS`](task-03-uc-edge-condition-fidelity.md) | HIGH | §4, N5 |
| 04 | [Stonebranch alias-marked plumbing is ignored (only type-based erasure)](task-04-sb-alias-plumbing.md) | MEDIUM | N3 |
| 05 | [External-reference id formats differ between the two builders](task-05-external-ref-id-format.md) | MEDIUM | §3, §7 |
| 06 | [Task Monitor target resolution picks an instance arbitrarily](task-06-monitor-target-ambiguity.md) | MEDIUM | §4, N6 |
| 09 | [Minor spec gaps: topology projection + broken doc paths](task-09-minor-spec-conformance.md) | LOW | §5, §7 |

## Confidence / verification (do these to trust the result)

| # | Task | Severity |
|---|------|----------|
| 07 | [No test suite exists — add golden, monitor-erasure, and benchmark tests](task-07-test-suite-and-goldens.md) | HIGH |
| 08 | [Alias coverage diagnostics are not surfaced in the skeleton report](task-08-alias-coverage-diagnostics.md) | MEDIUM |

## Performance (separate track — must not reduce graph-report fidelity)

| # | Task | Severity |
|---|------|----------|
| 10 | [Browser viewer is slow at thousands of nodes after the user opens it](task-10-perf-viewer-runtime.md) | HIGH (UX) |
| 11 | [Skeleton comparison re-serializes and re-hashes the graph several times](task-11-perf-compare-pipeline.md) | MEDIUM |

See `../READINESS_ASSESSMENT.md` for the overall go/no-go judgement.
