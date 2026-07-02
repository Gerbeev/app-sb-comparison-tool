# Implementation Plan — Canonical Skeleton Graph & Comparison

Target concept: `docs/mapping-theory.md` (spec) + `docs/mapping-explained.md` (rationale) +
`docs/skeleton-example.json` (golden example). Goal: AutoSys JIL and Stonebranch UC exports that
describe the same scheduling logic normalize to **byte-identical canonical skeleton files**, so
comparison becomes keyed line diff instead of graph matching.

---

## 1. Current state (as analyzed 2026-07-02)

Package `stonebranch_graph/` (v0.5.5, Python 3.11, zero runtime deps):

- `core.py` — flat `Node`/`Edge`/`Graph` model; ids `source:env:kind:name`; `canonical_key`
  `env:kind:normalized_name`; enterprise-name normalization (`enterprise_name_parts`).
- `domain.py` — 16 node kinds, 22 edge relations, comparison scope sets.
- `parsers/autosys_jil.py` — JIL block parser; conditions extracted with a **flat regex**
  (`CONDITION_RE`), each atom becomes an independent `depends_on_*` edge; AND/OR structure,
  lookback windows, and `job^INSTANCE` refs are lost or mangled.
- `parsers/stonebranch_json.py` — folder-driven object parser; workflow `workflowVertices`/
  `workflowEdges` → `contains` + `depends_on_*` edges; key-based reference walker;
  **no Task Monitor awareness** (a Task Monitor task is parsed as a normal `task` node).
- `compare.py` — node/edge key-set comparison with category scoping (job-like / infrastructure /
  system-specific / artifact), command semantic-hash comparison, metrics, report.md,
  remediation plan. `condition_differences` is effectively dead (SB side never sets a
  condition hash).
- `exporters.py` / `html_graph.py` — graph.json, canonical-graph.json (sorted diff view),
  containers view, Cytoscape HTML viewer (compound nodes, `depends_on` lists), comparison HTML.
- `workflows.py` / `cli.py` / `tui*.py` — orchestration, CLI subcommands, terminal UI.
- No `tests/` directory (pyproject is configured for pytest but nothing exists).

## 2. Gap analysis vs the documented concept

| # | Docs rule | Current implementation | Gap |
|---|---|---|---|
| G1 | §2.2 trigger = boolean expression tree per node | flat `depends_on_*` edges; `s(A) & (d(B) \| f(C))` → 3 unrelated edges | **Structural.** Need expression model + JIL boolean parser |
| G2 | §2.1 two node kinds (`unit`/`container`) + N7 meta split | 16 kinds compared via `COMPARISON_KIND_MAP`; schedule/runtime data mixed into edge diff | Need skeleton projection; keep rich kinds only in the exploration graph / meta layer |
| G3 | §4+N3 **Task Monitor = dependency, not node** | Task Monitors become ordinary task nodes with no special handling | **Critical correctness gap.** Erasure by substitution, fixpoint |
| G4 | N3 dummy/gate/Sleep plumbing erasure | none | Same mechanism as G3, driven by type + alias table |
| G5 | N1 logical-id alias table per system | `mapping.json` maps SB key→JIL key at compare time only | New alias format: `nativeName → logicalId` per system + plumbing markers |
| G6 | N4 canonical boolean form (flatten, dedupe, sort; no DNF) | n/a | part of expression core |
| G7 | N5 DONE folding (Success+Failure connectors from same predecessor → `DONE`; never expand `done`) | `_workflow_edge_relation` maps a single edge whose condition mentions both to `depends_on_done`, but parallel-edge folding does not exist | implement in SB skeleton builder |
| G8 | N6 sub-workflow instance expansion, path-qualified ids | name-keyed nodes; reused definitions collapse into one node | implement in SB skeleton builder |
| G9 | §3 lookback qualifier, `ext:` cross-instance refs | `success(J,04.00)` body split on comma, window dropped; `J^PRD` kept as literal name | expression atoms carry `qualifier`; `ext:NS/name` stubs |
| G10 | §2.3 completion override (`box_success`/`box_failure`) | attribute kept in raw attrs, never modeled | container `completion` expression (strict level) |
| G11 | §5 comparison = canonical line diff, 3 strictness levels, per-node hash | key-set comparison of nodes and edges | new skeleton comparison engine; legacy engine kept during transition |
| G12 | §10 viewer reads `trigger`, permanent container-target edges, predicate labels | viewer consumes `depends_on` success-lists; container edges only as collapse trick | viewer update; `depends_on` remains the degenerate-case fallback |
| G13 | performance at thousands of objects | `_resolve_ref_node`/`_resolve_dependency_node` do **O(N) scans per unresolved reference** (O(N²) total); several places rebuild traversal caches | indexing + perf pass with benchmark |

## 3. Design decisions

**Adopt** (from docs, verbatim): unit/container kinds; containment as `parent`; trigger
expressions attached to nodes; predicates `SUCCESS|FAILURE|DONE|TERMINATED|NOT_RUNNING|EXIT(op,n)`;
N1–N7 normalization; JSONL canonical serialization sorted by id; three comparison levels
(topology / logic / strict); Task Monitor & gate-job erasure by substitution; instance expansion;
`ext:` external stubs; no DNF minimization; `done` never expanded, UC success+failure folded up.

**Keep** (existing value):
- Both parsers' raw extraction and the rich exploration `Graph` (graph.json, containers, packs,
  schema profiler, TUI) — the skeleton is an *additional* pipeline stage, not a rewrite of parsing.
- Command strict/semantic hash comparison, infrastructure (agent/calendar/variable) matching,
  enterprise-name normalization — these become the **meta layer** report, excluded from the
  skeleton hash exactly as N7 prescribes.
- `canonical-graph.json` discipline (sorted, deterministic) — the skeleton serializer follows it.
- Cytoscape viewer architecture (compound nodes verified to support container-target edges).

**Replace / deprecate**:
- Edge-set dependency comparison → skeleton line comparison (legacy engine callable via
  `--legacy-compare` until parity is confirmed, then removed).
- Regex-flat JIL condition extraction → boolean parser (legacy edges still derived from atoms).
- `condition_differences` payload → canonical trigger diff.

**New modules** (flat, matching repo style):

```
stonebranch_graph/expr.py                 # expression model, parser, canonicalizer (N4, N5)
stonebranch_graph/skeleton.py             # SkeletonNode, ids, serialization, hashes, projections
stonebranch_graph/skeleton_autosys.py     # raw JIL records -> skeleton (§3, N2, G10)
stonebranch_graph/skeleton_stonebranch.py # raw UC records -> skeleton (§4, N5, N6)
stonebranch_graph/skeleton_normalize.py   # N1 alias application + N3 plumbing erasure fixpoint
stonebranch_graph/skeleton_compare.py     # 3-level diff, hashes, reports
```

## 4. Phases

| Phase | Prompt file | Depends on | Deliverable |
|---|---|---|---|
| 1 | `01-expression-core-and-skeleton-model.md` | — | `expr.py`, `skeleton.py`, unit tests |
| 2 | `02-jil-condition-parser.md` | 1 | boolean condition parsing in `autosys_jil.py`, raw-record API |
| 3 | `03-autosys-skeleton-builder.md` | 1, 2 | `skeleton_autosys.py` |
| 4 | `04-stonebranch-skeleton-builder.md` | 1 | `skeleton_stonebranch.py` + raw-record API in SB parser |
| 5 | `05-plumbing-erasure-task-monitors.md` | 3, 4 | N3 fixpoint in `skeleton_normalize.py` |
| 6 | `06-alias-table.md` | 5 | N1 alias config + application + diagnostics |
| 7 | `07-skeleton-comparison-engine.md` | 6 | `skeleton_compare.py`, new report, meta layer retained |
| 8 | `08-viewer-trigger-support.md` | 7 | skeleton view-model + HTML viewer + diff view |
| 9 | `09-performance-pass.md` | 7 (viewer parts: 8) | O(N²) fixes, benchmark script, targets met |
| 10 | `10-integration-cli-tests-docs.md` | 7 (8, 9 recommended) | CLI/TUI wiring, golden tests, docs, examples |

Sequencing: 1 → {2, 4 in parallel} → 3 → 5 → 6 → 7 → {8, 9 in parallel} → 10.
Each prompt is self-contained: a fresh agent session per prompt needs no other context.

## 5. Risks / notes

- **UC export field variance.** Task Monitor / vertex / edge JSON key names differ between UC
  versions. Builders use configurable key lists (pattern already used for
  `WORKFLOW_VERTEX_KEYS`); unknown shapes must degrade to warnings, never silent drops.
- **Erasure cycles.** Monitor→monitor chains need cycle detection in the N3 fixpoint (bounded
  iterations + warning), or a malformed export can loop.
- **Id stability.** Instance expansion (N6) changes ids when workflow nesting changes; that is
  by design (compare what runs), documented in the report.
- **Doc path bug.** Docs reference `data/skeleton-example.json`; the file lives at
  `docs/skeleton-example.json` (fix in phase 10).
- **examples/** has no workflow, no Task Monitor, no sub-workflow fixtures — phase 10 adds them;
  phases 4–5 add minimal fixtures under `tests/fixtures/` earlier.

## 6. Definition of done

1. The §8 worked example from `mapping-explained.md`, expressed as JIL fixtures on one side and
   UC JSON fixtures (with a Task Monitor) on the other, produces **byte-identical** canonical
   skeleton files, and `compare-skeleton` reports zero differences at all three levels.
2. A Task Monitor never appears as a node in any skeleton output; its condition appears inside
   its successors' triggers.
3. Legacy commands (`build-stonebranch`, `build-jil`, `compare`, packs, TUI) still work.
4. Benchmark: 10k-node synthetic set parses + normalizes + compares in seconds, not minutes;
   no O(N²) hot paths remain in parsers or normalization.
5. Viewer renders triggers (predicate labels, container-target edges) and the comparison view
   colors added/removed/changed nodes from skeleton diff statuses.
