# Graph Skeleton & Semantic Core — Implementation Plan

Companion to `GRAPH_SKELETON_AND_SEMANTIC_CORE_PROPOSAL.md`. Each item below has a matching agent prompt in `prompts/graph-skeleton/NN-*.md`, sized to be executed independently by an agentic AI (Claude Sonnet 4.6) with minimal token spend.

Execution order matters: items 1–4 are the dependency chain; 5–8 build on them; 9–10 close the loop. Items 2, 5, 6 can run in parallel once 1 is merged.

---

## Item 1 — Domain vocabulary extension

**Files:** `stonebranch_graph/domain.py`, `stonebranch_graph/core.py`

Add `REL_PRODUCES_FILE = "produces_file"` and `REL_DATA_DEPENDS_ON = "data_depends_on"`. Add `DATA_FLOW_RELATIONS = {REL_WATCHES_FILE, REL_PRODUCES_FILE, REL_DATA_DEPENDS_ON}` and `DERIVED_EDGE_RELATIONS = {REL_DATA_DEPENDS_ON}`. Extend `Edge` with `derived: bool = False` and `inference: str = ""` (defaults keep every existing `graph.json` loadable via `Edge(**edge_data)` — verify `from_dict` round-trip). Exclude the two new relations from `COMPARABLE_EDGE_RELATIONS`; add them to `ARTIFACT_EDGE_RELATIONS` or a new exclusion set consumed by `compare.py`.

**Acceptance:** old `graph.json` files load unchanged; new fields serialize via `asdict`; no comparison output changes on existing fixtures.

## Item 2 — File identity canonicalization

**Files:** new `stonebranch_graph/file_identity.py` (+ small hook in both parsers)

`canonical_file_key(raw_path, variables: dict) -> FileIdentity(key, pattern, unresolved_vars)`. Rules: strip quotes, unify `\\`→`/`, case-fold when path looks Windows-style, substitute `$VAR`/`${VAR}`/`%VAR%` when the variable is known, collapse date/sequence stamps (`_20260701`, `.001`) into `{date}`/`{seq}` placeholder producing a stable stem-pattern. Both parsers use it when creating `KIND_FILE` nodes so watcher paths and (later) producer paths unify to one node; keep the raw string in node metadata.

**Acceptance:** unit tests covering Windows/Unix paths, quoted paths, `%DATE%` stamps, unknown variables; same canonical key ⇒ same node id in a parsed sample.

## Item 3 — Producer inference engine

**Files:** new `stonebranch_graph/producers.py`, config hook in `config.py`, CLI flag in `cli.py`

Post-parse pass over a `Graph`: collect watched file nodes; scan each job's normalized command tokens (reuse `normalizers.py` tokenization) for T2 lexical path matches and T3 basename/stem matches against canonical file keys; load optional `producers.json` (T1) mapping job-name-or-command-regex → produced paths. Emit `produces_file` edges with `confidence` 1.0/0.8/0.5, `derived=False`, `inference` set to the tier name, evidence pointing at the matched command token or mapping entry. Highest tier wins per (job, file).

**Acceptance:** fixture where job A's command writes `out.csv` redirect and watcher B watches it ⇒ one T2 edge; `producers.json` entry overrides to T1; no edges invented for non-watched paths.

## Item 4 — Data-flow contraction + skeleton builder

**Files:** new `stonebranch_graph/skeleton.py`

`build_skeleton(graph, *, traversal=None) -> SkeletonView`:
1. Restrict to `JOB_LIKE_KINDS` + `DEPENDENCY_RELATIONS`; carry the containment forest separately.
2. For each file node compute `P(f)`, `W(f)`; emit derived `data_depends_on` edges (`derived=True`, `inference="contraction"`, confidence = product), with the `|P|×|W| > 25` cap-and-warn guard.
3. Tarjan SCC → warnings + `scc_id` per node; all further analysis on the condensation.
4. Optional transitive reduction (flag, default off in data, on in skeleton *view*); longest-path layering → `layer` per node.

Pure stdlib; no new dependencies. Deterministic output ordering.

**Acceptance:** unit tests for contraction pair-expansion, cap behavior, SCC detection on a synthetic cycle, layering on a diamond DAG; runs on `examples/` without warnings.

## Item 5 — Semantic-core metrics

**Files:** `stonebranch_graph/metrics.py` (extend), consumed by skeleton view

On the skeleton condensation: degree (reuse `GraphTraversalCache`), Brandes betweenness, k-core index, articulation points, descendant-reach size; combined criticality score (weights configurable in `config.py`, defaults 0.4/0.3/0.2/0.1 per proposal §3.4). Store per-node results into the skeleton view payload (not into `graph.json` nodes).

**Acceptance:** hand-checkable tests on a 7-node fixture (star, chain, clique) asserting rankings, not absolute values; O(V·E) implementation documented.

## Item 6 — Condition boolean structure (OR-groups)

**Files:** `stonebranch_graph/parsers/autosys_jil.py`

Extend `_parse_condition_refs` to track top-level boolean structure: classify condition as `and` / `or` / `mixed`; assign `or_group` index to atoms inside a disjunction. Store `condition_logic` in node metadata and `or_group` in edge evidence metadata (new `Edge` usage from Item 1 not required — use `evidence_key` suffix or metadata piggyback chosen in implementation). Do not attempt full boolean-tree modeling.

**Acceptance:** tests for `s(a) & s(b)`, `s(a) | s(b)`, `s(a) & (s(b) | s(c))` producing correct logic labels and groups; existing condition tests unchanged.

## Item 7 — Cytoscape view-model extension

**Files:** `stonebranch_graph/html_graph.py` (data side: `build_cytoscape_graph_data`, `relation_category`)

Add relation categories: `data_flow` (`produces_file`, `data_depends_on`) — `watches_file` stays in `files`. Include file nodes in the payload as a new `files` array (id, canonical key, watchers, producers, classification internal/external/ambiguous). Add `skeleton` section: per-job `layer`, `scc_id`, `criticality`, plus derived-edge list. Bump `HTML_GRAPH_SCHEMA_VERSION` to `1.1`. Keep payload deterministic and sorted.

**Acceptance:** payload snapshot test; schema version bumped; graph.html still loads old payloads gracefully or fails with a clear message (choose: hard version check).

## Item 8 — HTML/UI: skeleton mode, derived edges, watcher tracing

**Files:** `stonebranch_graph/html_graph.py` (embedded `CYTOSCAPE_HTML` JS/CSS)

UI work on the offline report: (a) Full/Skeleton mode toggle — skeleton uses layered breadthfirst-style layout from `layer` values; (b) dashed styling + confidence-based opacity for `derived` edges, tooltip shows `inference`; (c) `data_flow` entry in the relation filter; (d) click on `file_watcher` highlights file → producers → downstream corridor; (e) watcher classification badges; (f) criticality-driven node sizing + "Top core" quick filter; (g) SCC red-boundary overlay. Reuse existing filter/selection plumbing; no new JS libraries.

**Acceptance:** manual check-list rendered on `examples/` output; all existing controls still work; report stays fully offline.

## Item 9 — Comparison integration & triage

**Files:** `stonebranch_graph/compare.py`, `stonebranch_graph/triage.py`, `stonebranch_graph/domain.py` (sets from Item 1)

Ensure derived/inferred relations never enter node/edge match rates. Add informational comparison section: watcher classification counts per side, internal-fed watchers whose producer exists in JIL but whose derived link has no Stonebranch counterpart (i.e. migration may replace watcher with a direct workflow edge — surfaced as an *opportunity*, not a mismatch). Triage: rank existing mismatch lists by criticality score when a skeleton view is available.

**Acceptance:** comparison snapshot on existing fixtures unchanged except the new informational section; triage ordering test.

## Item 10 — Fixtures, tests, docs

**Files:** `examples/jil/PROD/` (extend), new `tests/`, `README`/docs section

Add a realistic JIL fixture: box with producer job (`command: run.exe > /data/out/report_%DATE%.csv`), file watcher on the same path pattern, downstream job with `condition: s(FW) & s(OTHER)`, one external-fed watcher. Mirror minimal Stonebranch JSON fixture. Wire `pytest` (none exists today), consolidate tests from items 2–6, add an end-to-end test: parse → infer producers → skeleton → cytoscape payload asserts the derived edge and watcher classifications. Document `producers.json` format and skeleton mode in README.

**Acceptance:** `pytest` green from clean checkout; end-to-end test covers the full pipeline; docs explain the T1 mapping workflow for opaque .NET producers.

---

## Sequencing summary

```
1 → 2 → 3 → 4 → 5 → 7 → 8
      └────────↘
1 → 6 ──────────→ 9 → 10
```

Minimal demo path (first visible result): 1 → 2 → 3 → 4 → 7 → 8 on the `examples/` fixtures.
