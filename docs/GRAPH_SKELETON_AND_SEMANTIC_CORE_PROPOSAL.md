# Graph Skeleton and Semantic Core — Design Proposal

Status: proposal • Scope: `stonebranch_graph` Cytoscape graph generation for AutoSys (JIL) and Stonebranch objects • Reference system: AutoSys (migration source)

---

## 1. Purpose

The tool already builds a rich normalized graph from JIL files and Stonebranch JSON exports and renders it with Cytoscape. What is missing is a principled separation between:

1. **The skeleton** — the minimal execution-dependency graph that answers *"what runs after what, and what blocks what"*. This is the graph a migration engineer must trust.
2. **The semantic core** — the enriched context around the skeleton: resources, schedules, commands, files, agents, plus computed importance (which nodes are hubs, bridges, or fragile points).

This document defines what should be a node, an edge, and a group; gives the mathematical model behind skeleton extraction; and resolves the file-watcher problem (a watched file may be produced by another job through an opaque command, e.g. a .NET application).

---

## 2. Formal model

The persisted graph is a **directed, typed, attributed multigraph**:

```
G = (V, E, τ, ρ, κ, σ)
```

- `V` — vertices (objects). `τ: V → K` assigns each vertex a *kind* from the closed vocabulary in `domain.py` (`task`, `box`, `workflow`, `file_watcher`, `file`, `command`, `agent`, `calendar`, `variable`, …).
- `E ⊆ V × V × R` — directed edges. `ρ: E → R` assigns a *relation* (`depends_on_success`, `contains`, `watches_file`, `runs_on`, …). Multiple edges between the same vertex pair are allowed if relations differ (multigraph).
- `κ: E → [0,1]` — confidence. `1.0` for facts read verbatim from configuration; `< 1.0` for parsed/inferred facts (the JIL condition parser already uses `0.95`).
- `σ` — provenance: every edge carries `evidence_file / evidence_path / evidence_key / evidence_value`. This already exists and must be preserved for all new edge types: **no edge without evidence**.

Two orthogonal partitions of the vocabulary drive everything below:

| Layer | Kinds | Role |
|---|---|---|
| **Executable** | `task`, `box`, `workflow`, `file_watcher` | Things the scheduler runs (JOB_LIKE_KINDS) |
| **Data** | `file` | Passive artifacts jobs wait on / produce |
| **Infrastructure** | `agent`, `agent_cluster`, `calendar`, `variable` | Referenced, never scheduled |
| **Artifact** | `command` | Hash-named helper nodes, compared at attribute level |
| **System-specific** | `trigger`, `credential`, `connection`, `email_template`, `script` | Stonebranch-only |

| Edge class | Relations | Skeleton? |
|---|---|---|
| **Control flow** | `depends_on*`, `successor_of` | yes |
| **Containment** | `contains` | yes (as hierarchy, not as flow) |
| **Data flow** | `watches_file`, **`produces_file` (new)**, **`data_depends_on` (new, derived)** | derived form only |
| **Resource** | `runs_on`, `runs_on_cluster`, `uses_variable`, `uses_credential`, `uses_connection` | no |
| **Schedule** | `starts`, `uses_calendar`, `excludes_calendar` | no |
| **Artifact/speculative** | `runs_command`, `runs_script`, `references` | no |

### 2.1 What is a node

A vertex is created for anything that has **identity and lifecycle independent of a single referencing object**. This is the test to apply to every modeling question:

- A **job/box/workflow** is a node — obvious.
- A **file watched by a watcher is a node**, not an attribute of the watcher, because (a) several watchers can watch the same file or pattern, (b) several jobs can produce the same file, (c) the same physical file appears on both the AutoSys side (`watch_file:`) and the Stonebranch side (File Monitor task), so cross-system matching needs file identity that is independent of any one watcher. The current parser already does this (`KIND_FILE` + `REL_WATCHES_FILE`) — keep it.
- A **command is an artifact node** keyed by semantic hash (current behavior) — it deduplicates identical commands but is never diffed as a graph object. Keep it.
- A **machine/agent, calendar, variable** are reference nodes (possibly `synthetic: true` when only referenced, never defined). Keep it.

### 2.2 What is an edge

An edge is a **directed, evidenced statement** `source —relation→ target`. Direction convention (already established, keep it consistent): *the dependent points at what it needs* (`job —depends_on_success→ predecessor`, `job —runs_on→ agent`, `watcher —watches_file→ file`), except containment which points *down* (`box —contains→ job`) and triggering which points *forward* (`trigger —starts→ task`).

Two new mandatory edge attributes:

- `derived: bool` — `true` for edges *computed* by the tool rather than read from configuration. Derived edges are analytical overlays: they are rendered differently, can be toggled off, and are **excluded from cross-system comparison** (they are not migration facts).
- `inference: str` — for derived/inferred edges, the rule that produced them (`"explicit_mapping"`, `"lexical_path_match"`, `"basename_heuristic"`, `"contraction"`), so a reviewer can audit every inferred line on the screen.

### 2.3 What is a group

Groups are **compound nodes derived from the containment forest**. The `contains` relation restricted to executable kinds forms a forest F (boxes nest boxes; workflows nest sub-workflows). Cytoscape compound nodes mirror F exactly — this is already implemented via `build_container_view`. Rules to keep it well-defined:

1. A node has at most one containment parent. If parsing produces two `contains` parents, keep the highest-confidence one and emit a warning (forest invariant).
2. Groups are *never* invented from visual clustering; they only mirror scheduler semantics (box/workflow membership). Visual-only clustering (by application prefix from `enterprise_naming`, by agent, by calendar) should be a separate, optional *coloring/legend* dimension, not compound nesting — mixing the two makes collapse semantics ambiguous.
3. When a group is collapsed, cross-boundary edges are **lifted** to the group: formally, the visible graph is the quotient graph `G/π` where π is the partition induced by collapsed containers, with parallel lifted edges merged per relation-category and labeled with multiplicity (e.g. "deps ×14"). Never silently drop cross-boundary edges — lifted-edge multiplicity is exactly what shows inter-box coupling, the most important migration signal.

---

## 3. The skeleton

### 3.1 Definition

The skeleton `S` is computed from `G` in four steps:

**Step 1 — restrict.** Take the induced subgraph on executable vertices `V_J = τ⁻¹({task, box, workflow, file_watcher})` with control-flow edges plus containment:

```
S₀ = (V_J, { e ∈ E : ρ(e) ∈ DEPENDENCY_RELATIONS } )    + containment forest F as hierarchy
```

**Step 2 — close data flow (file contraction).** For every file vertex `f`, let `P(f) = { p : p —produces_file→ f }` and `W(f) = { w : w —watches_file→ f }`. Add a derived edge for every pair:

```
w —data_depends_on→ p        for (p, w) ∈ P(f) × W(f)
κ(w→p) = κ(w→f) · κ(p→f)     (confidence composition)
```

This is edge composition `data_depends_on = watches_file ∘ produces_file⁻¹`, equivalently the projection of the bipartite job–file graph onto jobs. The file vertex is *not deleted* — it stays in the full view; the derived edge is what enters the skeleton. Guard against blowup: if `|P(f)| × |W(f)|` exceeds a cap (default 25), emit a warning and keep the file node as an explicit junction instead of expanding pairs.

**Step 3 — condense.** The skeleton should be a DAG (schedulers reject dependency cycles, but parsing artifacts, cross-box conditions lifted to containers, and inferred data edges can create cycles). Run Tarjan SCC; every non-trivial SCC becomes a warning and is rendered as a highlighted cluster. Analysis (layering, reduction) runs on the condensation `S/SCC`, which is a DAG by construction.

**Step 4 — reduce and layer (display only).** On the condensation:

- **Transitive reduction** removes edges implied by longer paths (`a→b, b→c, a→c` ⇒ drop `a→c`). Do it per relation class and only as a *view option* — the redundant edge is still a configuration fact the migration must reproduce, so the full edge set stays in `graph.json`. For DAGs the reduction is unique.
- **Longest-path layering** assigns `layer(v) = max over predecessors + 1`, producing the "execution waves" used for a left-to-right hierarchical layout. This makes the skeleton readable at thousands of nodes where force-directed layouts fail, and layer count = critical-path length is itself a useful migration metric.

### 3.2 Why file watchers must not be plain dependency edges

It is tempting to model `FW watches F` + `F produced by J` directly as `FW depends_on J`. Do not do this at the fact level, for three reasons:

1. **Epistemic status differs.** `condition: s(JOB_A)` is a configuration fact; "J produces F" is an *inference* (JIL has no `produces:` attribute — the command may call a .NET binary whose outputs are invisible to the parser). Mixing facts and inferences in one relation destroys the trustworthiness of the comparison and of the graph itself.
2. **The file is the cross-system join point.** In Stonebranch the watcher becomes a File Monitor task/trigger referencing the same path. Matching AutoSys watcher ↔ Stonebranch monitor goes *through file identity*, which requires the file node.
3. **External producers exist.** Many watched files come from MFT/upstream feeds outside the graph. `P(f) = ∅` is a meaningful, reportable state ("external-fed watcher") — impossible to express if the watcher-file structure is collapsed away.

Hence the two-relation design: keep `watches_file` (fact, κ=1.0), add `produces_file` (inferred, κ<1.0 unless explicitly mapped), and let the skeleton *derive* `data_depends_on` transparently with `derived: true, inference: "contraction"`.

### 3.3 Producer inference (how `produces_file` edges are found)

Tiered engine, highest tier wins per (job, file) pair; every edge records its tier in `inference` and a tier-specific confidence:

| Tier | Rule | Confidence |
|---|---|---|
| T1 `explicit_mapping` | User-maintained `producers.json`: `{ "job_or_command_pattern": ["path", …] }`. This is the escape hatch for opaque .NET applications whose output paths live in app config — the migration team encodes tribal knowledge once, the graph shows it forever. | 1.00 |
| T2 `lexical_path_match` | The canonical form of a watched path appears as a token inside another job's normalized command string (output redirect `> path`, `-o path`, path-shaped argument). Only paths that are *watched by someone* are searched — this bounds the scan to `O(jobs × watched_files)` on pre-tokenized commands. | 0.80 |
| T3 `basename_heuristic` | Basename (or glob-stem) of the watched file matches a path-shaped token in a command, directories differ or contain unresolved variables/`%DATE%` tokens. | 0.50 |

File identity is the precondition for all tiers: a canonicalization function maps raw path strings to a canonical key (case-fold on Windows-style paths, unify separators, strip quotes, substitute known variables from the `variable` nodes when resolvable, and reduce date-stamped names to a stem + pattern, e.g. `report_20260701.csv → report_{date}.csv`). Two raw strings with equal canonical keys are the same file node.

Watchers are then classifiable — a high-value migration report in itself:

- **Internal-fed** (`P(f) ≠ ∅`): candidate for replacing the watcher with a direct workflow edge in Stonebranch (simpler, no polling). The derived edge shows exactly which producer to wire.
- **External-fed** (`P(f) = ∅`): must remain a File Monitor task/trigger in Stonebranch. No action, but confirmed intentional.
- **Ambiguous** (multiple producers, or only T3 matches): needs human review; surfaced in triage.

### 3.4 Semantic core (importance scoring)

On the skeleton condensation, compute per node and store into `metadata` (extending `metrics.py`):

- **Degree** (in/out, already cached in `GraphTraversalCache`) — local fan-in/fan-out.
- **Betweenness centrality** (Brandes, exact is fine at this scale; sample if > ~20k nodes) — identifies *bridge jobs* through which many dependency paths pass; breaking one during migration breaks many chains.
- **k-core index** — the densely interlocked heart of the schedule; the max-k core *is* the semantic core in the strict sense and should be extractable as a one-click view.
- **Articulation points** on the undirected skeleton — single points of failure in connectivity.
- **Criticality score** = weighted normalized combination (default `0.4·betweenness + 0.3·reach + 0.2·degree + 0.1·core`), where *reach* is the size of the descendant set (how much of the schedule transitively waits on this node).

The Cytoscape view uses the score for node sizing and a "top-N core" filter; the comparison report uses it to rank mismatches (a mismatch on a criticality-0.9 node outranks fifty leaf mismatches).

---

## 4. System-architecture fit

### 4.1 AutoSys (reference side)

| JIL construct | Graph representation |
|---|---|
| `insert_job / job_type: c` | `task` node |
| `job_type: b` (box) | `box` node; members via `contains` (from `box_name:`) |
| `job_type: f` (file watcher) | `file_watcher` node + `watches_file → file` |
| `condition: s(X) & d(Y)…` | `depends_on_success/done/failure/terminated/notrunning` edges, κ=0.95; OR-branches flagged (see below) |
| `machine:` | `runs_on → agent` |
| `calendar / run_calendar / exclude_calendar` | `uses_calendar` / `excludes_calendar` |
| `command:` | `runs_command → command(hash)` + `uses_variable` per `$VAR` |
| box-level conditions | conditions on a box gate all members: when lifting to the skeleton, a member inherits the box's incoming dependency edges *implicitly* — model as edge lifting at render time, never materialize per-member copies |

One known gap worth fixing while implementing this proposal: the condition parser extracts atoms but discards the boolean structure (`&` vs `|`). An OR-group of dependencies is semantically different from AND (Stonebranch models OR via separate triggers or virtual resources). Minimum viable fix: store `condition_logic: "and" | "or" | "mixed"` on the dependent node's metadata and set edge metadata `or_group: <n>` for atoms inside a disjunction, so the renderer can bracket them and the migration report can flag `mixed` conditions for manual review.

### 4.2 Stonebranch (target side)

| Stonebranch construct | Graph representation |
|---|---|
| Workflow | `workflow` node; vertices via `contains`; workflow edges → `depends_on_*` between member tasks |
| Task (all universal task types) | `task` node |
| File Monitor task | `file_watcher` node + `watches_file → file` (same shape as AutoSys — this symmetry is the whole point) |
| Trigger (cron, file monitor trigger) | `trigger —starts→ task/workflow` (system-specific layer) |
| Agent / cluster, credential, connection, script, email template | respective infrastructure/system-specific nodes |

Because both sides normalize to the same shapes, the migration check reduces to comparing two graphs restricted to `COMPARABLE_EDGE_RELATIONS` — which is exactly the existing `compare.py` contract. The new relations slot in as: `produces_file` and `data_depends_on` are **excluded** from comparison (derived/inferred, not configuration); `watches_file` remains comparable (already is).

### 4.3 Migration equivalence, mathematically

The comparison is a partial graph homomorphism check: find mapping `h: V_jil → V_sb` (via `canonical_key` on comparison names) such that for every skeleton edge `(u,v)` in JIL there is an edge `(h(u), h(v))` with an equivalent relation in Stonebranch. Reported classes: node mismatches (`h` undefined / not injective), edge mismatches (relation preserved / dropped / added), attribute mismatches (command hashes). The skeleton restriction is what makes this tractable and meaningful — resource and schedule layers are compared as per-node attribute sets, not as edges.

---

## 5. Rendering (Cytoscape)

- **Two modes**: *Full graph* (current behavior + file/data layer) and *Skeleton* (executable nodes only, control-flow + derived data edges, hierarchical layered layout from §3.1 step 4). Skeleton is the default for large graphs.
- **Derived edges** (`data_depends_on`): dashed line, distinct color, opacity ∝ confidence, tooltip shows inference tier + evidence. Toggleable as their own relation category `data_flow`.
- **File nodes**: small square glyph; hidden in skeleton mode (represented by the derived edge), visible in full mode between producer and watcher.
- **File-watcher tracing**: clicking a `file_watcher` highlights the watched file, all inferred producers, and the downstream jobs gated by the watcher — the full data-flow corridor.
- **Watcher classification badges**: internal-fed / external-fed / ambiguous (§3.3).
- **Criticality**: node size or halo ∝ criticality score; "show top-N core" quick filter next to the existing Problems/Critical/Missing filters.
- **SCC warning overlay**: any non-trivial SCC rendered with a red boundary; list in the warnings panel.

---

## 6. Summary of design decisions

1. Files stay first-class nodes; watchers stay first-class executable nodes. (Already true — confirmed correct.)
2. New fact-level inferred relation `produces_file` (tiered inference T1/T2/T3 with explicit-mapping escape hatch for opaque .NET producers, confidence + provenance on every edge).
3. New derived relation `data_depends_on` = contraction of producer→file←watcher paths; `derived: true`; enters the skeleton; excluded from cross-system comparison.
4. Skeleton = induced executable subgraph + data-flow closure + SCC condensation + (display-only) transitive reduction and longest-path layering.
5. Semantic core = k-core / betweenness / reach-based criticality scoring on the skeleton, driving node sizing, top-N filters, and mismatch ranking.
6. Groups mirror the containment forest only; collapse semantics = quotient graph with lifted, multiplicity-labeled edges.
7. Condition boolean structure (AND/OR) captured at least as metadata to keep OR-dependencies honest.
