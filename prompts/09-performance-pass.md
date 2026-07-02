# Prompt 09 — Performance pass for thousands of objects

## Objective

Make the full pipeline (parse → build skeleton → normalize → compare → export) comfortably
handle 5,000–20,000 objects. Fix the known O(N²) hot paths, add a benchmark script with a
synthetic generator, and set regression guardrails. No behavior changes — every output must
stay byte-identical (the skeleton golden tests are the safety net).

## Context — read ONLY these

1. `stonebranch_graph/parsers/autosys_jil.py` — `_resolve_ref_node`,
   `_resolve_dependency_node` (the two known O(N)-scan-per-reference offenders),
   `_ensure_ref_node`.
2. `stonebranch_graph/parsers/stonebranch_json.py` — `_build_registry` (the good pattern to
   replicate), `_resolve_or_create_ref_node`.
3. `stonebranch_graph/graph_utils.py` — `GraphTraversalCache`.
4. `stonebranch_graph/skeleton_normalize.py`, `skeleton_compare.py`, `expr.py` — scan for
   accidental quadratic loops (substitution scanning all nodes per erased node is expected;
   make it index-driven).
5. `stonebranch_graph/exporters.py` + `html_graph.py` — only to check traversal-cache reuse
   and payload sizes; do not restructure exports.

## Requirements

### A. JIL parser indexing (the certain win)

1. Build once, after node creation: `by_exact_id: dict[str, Node]` and
   `by_canonical_key: dict[tuple[kind, canonical_key], list[Node]]` +
   `by_key_any_jobkind: dict[canonical_key, list[Node]]`.
2. Rewrite `_resolve_ref_node` and `_resolve_dependency_node` to use these indexes; keep
   ambiguity warnings and synthetic-fallback semantics **identical** (same warning strings).
   Newly created synthetic nodes must be registered in the indexes.
3. Result: O(1) per reference. Assert no remaining `for node in graph.nodes.values()` inside
   per-job/per-reference loops in either parser (grep in the acceptance step).

### B. Skeleton pipeline

1. `erase_plumbing`: precompute a reverse index `ref → [node ids whose trigger references ref]`
   once per fixpoint round (or maintain incrementally); never rescan all triggers per erased
   node.
2. `expr.canonicalize`/`render`: memoize rendered strings on the (frozen) dataclass via a
   module-level `functools.lru_cache` keyed on the expr object, or compute-and-carry — pick
   one; rendering happens ≥3× per node (three level views + serialization).
3. `skeleton_compare`: hashes computed once per node per level (verify — `index_rows` should
   be the single source), dict joins O(N).
4. `Skeleton.validate` containment-cycle check must be linear (visited-set walk), not
   per-node ancestor walks.

### C. Exports & viewer payloads

1. Confirm every `export_*` in a bundle run receives the shared `GraphTraversalCache`
   (pattern exists in `export_graph_bundle`; check the comparison HTML path builds it at most
   once per graph).
2. Skeleton HTML view-model: for graphs above a threshold (module constant, default 4,000
   nodes), emit `trigger` strings only for nodes whose trigger is not a pure success-AND
   (the `depends_on` array already covers those) — measured payload reduction with no
   information loss. Document the constant.
3. `dependency-graph.dot` cap already exists; add the same cap logic to the skeleton diff
   HTML edge overlays if implemented in prompt 08.

### D. Benchmark — `tools/bench_skeleton.py`

1. Synthetic generator: parameters `--workflows W --tasks-per-wf T --monitors M --cross-deps X
   --seed S`; emits an in-memory UC raw export and a JIL job list of matching shape
   (~W·T nodes each side, deterministic).
2. Phases timed separately (parse-equivalent build, skeleton build, erasure, compare,
   serialize); prints a table; `--profile` flag wraps `cProfile` and prints top-20 cumulative.
3. Targets (document in script header, assert nothing — it's a tool, not a test):
   10k nodes/side end-to-end **< 10 s** on a typical laptop; erasure of 1k monitors in a 10k
   graph **< 2 s**; peak additional memory sane (skeleton line strings dominate — fine).
4. One *fast* regression test `tests/test_perf_smoke.py`: 2k nodes/side full pipeline under
   a generous wall-clock bound (e.g. 20 s) so CI catches quadratic regressions without being
   flaky.

## Out of scope

Algorithmic changes to comparison semantics, multiprocessing/threading, external deps
(stdlib only), JS runtime optimization inside cytoscape.

## Acceptance criteria

1. All existing test suites pass unchanged (byte-identical goldens).
2. `python tools/bench_skeleton.py --workflows 100 --tasks-per-wf 100 --monitors 500` meets
   the documented targets; paste the timing table into the final summary.
3. `grep -n "graph.nodes.values()" stonebranch_graph/parsers/autosys_jil.py` shows no hits
   inside reference-resolution paths.
4. `ruff check` clean on all touched files.

## Cost guidance

Profile first (one bench run with `--profile`), optimize only what the profile shows, re-run
bench. Do not micro-optimize code the profile doesn't implicate. Avoid touching test files
except the new smoke test.
