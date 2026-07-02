# Comparing AutoSys and Stonebranch graphs — the plain-language version

*(Companion to [mapping-theory.md](mapping-theory.md), which is the precise spec.
Read this one first.)*

---

## 1. The whole idea in one picture

Strip away the vendor words and both systems are the same three things:

```
┌─ ETL (container) ────────────────────┐      ┌─ REPORTING (container) ─┐
│                                      │      │                         │
│  extract ──success──▶ transform      │      │   build_report          │
│                          │           │      │        ▲                │
│                       success        │      │        │                │
│                          ▼           │      │     success             │
│                        load ─────────┼──────┼────────┘                │
│                                      │      │                         │
└──────────────────────────────────────┘      └─────────────────────────┘

 nodes   = things that run            (jobs / tasks)
 nesting = things that group them     (boxes / workflows)
 arrows  = "waits for" rules          (conditions / connectors)
```

- AutoSys calls the pieces: *job, box, condition*.
- Stonebranch calls them: *task, workflow, connector*.
- Same skeleton. Different words. That's the entire premise of comparing them.

---

## 2. What is a node?

**Rule of thumb: a node is anything with its own lifecycle** — it can run, then succeed or fail.

| Our node kind | AutoSys | Stonebranch | Why it's a node |
|---|---|---|---|
| `unit` | command job, file-watcher, any non-box job | task (any type) | it does the work |
| `container` | box | workflow / sub-workflow | it *also* has a status — a box succeeds, a workflow completes — so it's a node that holds children |

**What is deliberately NOT a node:**

| Construct | System | Why we delete it |
|---|---|---|
| Task Monitor task | Stonebranch | does no work; exists only to say "wait until job X over there finishes". That's a **wire pretending to be a box**. We remove the node and keep its meaning as an ordinary dependency arrow. |
| dummy / "gate" jobs | AutoSys | same story — pure dependency glue |

Deleting these is what makes the two systems comparable: Stonebranch *needs* a helper
node to express a cross-workflow wait; AutoSys just writes a condition. After deletion,
both look identical.

---

## 3. What is an edge?

There are **two completely different kinds of "arrow"**, and keeping them separate is
the single most clarifying decision:

### Kind 1 — "lives inside" (containment)

Not drawn as an arrow at all — drawn as **nesting** (a box around its children).

| AutoSys | Stonebranch |
|---|---|
| `box_name: ETL_BOX` on a job | the task is placed inside a workflow |

### Kind 2 — "waits for" (dependency)

A directed arrow **predecessor → successor**, carrying one label: **the state being waited for**.

| | AutoSys | Stonebranch |
|---|---|---|
| where the arrow comes from | each atom of `condition: success(A) & failure(B)` gives one arrow | each connector drawn between two tasks is one arrow |
| the label | success, failure, done, terminated, notrunning, exit-code | connector condition: Success, Failure, exit-code |
| arrow across groups | a condition can name any job anywhere — just works | done via a Task Monitor → we erase the monitor, keep the arrow |

**How to read one:** `A --success--> B` means "B may start once A has succeeded."

---

## 4. Where AND/OR lives (how to interpret multiple arrows)

Not on the edges — **on the receiving node**. Every node has a *combine rule* that says
how its incoming arrows join together:

| System | Combine rule |
|---|---|
| Stonebranch | fixed: **ALL incoming connectors** must be satisfied (AND) |
| AutoSys | a formula: `s(A) & (d(B) | f(C))` — any AND/OR mix |
| **our graph** | default = AND (covers the vast majority); an explicit formula only where AutoSys really uses OR |

So the mental model for reading any node:

> "**\<node\>** starts when **\<combine rule over its incoming arrows\>** is true,
> provided its **container** has started."

That last clause is why containment stays a separate relation: being inside a box/workflow
already implies "wait for my container to start" in *both* systems — so we never draw
that arrow. Only the *extra* logic becomes edges.

---

## 5. How everyone else does it (graph theory & industry)

This structure has old, well-studied names:

- **DAG** (directed acyclic graph) of precedence constraints — in scheduling literature,
  an *activity-on-vertex network* (PERT/CPM lineage).
- Grouping = a **compound (nested) graph**: a containment *tree* overlaid on the dependency *DAG*.
  Two relations on one node set — exactly our kinds 1 and 2.
- Boolean conditions = an **AND-OR graph** (AI planning term).
- Nodes/edges carrying attributes = a **property graph** (the Neo4j-style model).

And practically every modern scheduler converged on the same shape:

| System | Node | Edge | OR-logic | Grouping |
|---|---|---|---|---|
| Make / Bazel | target | "needs" (success) | no | — |
| dbt | model | `ref()` (success) | no | folders (cosmetic) |
| GitHub Actions / GitLab CI | job | `needs:` | no (`if:` hacks) | stages |
| **Airflow** | task | up/downstream | **`trigger_rule` on the node** | TaskGroups |
| Control-M | job | condition | yes | folders / SMART tables |
| AutoSys | job | condition atoms | yes — full boolean | boxes (nested) |
| Stonebranch | task | connector | no (workarounds) | workflows (nested) |

The convergent pattern — which we adopt verbatim — is **Airflow's**:

> *Edges say WHO you wait for. A small rule on the node says HOW the arrows combine.*

AutoSys is the most expressive dialect of this idea; Stonebranch is the most restricted.
Our common format uses the expressive rule, and Stonebranch maps into it as the simple case.

---

## 6. Why "same logic" ends up as the same file

Five plain rules (rigorous versions in [mapping-theory.md](mapping-theory.md) §5):

1. **One shared name per job** — a small alias table (`ACME_LOAD` ↔ `acme-load` → `etl/load`).
   Comparing then needs no graph mathematics at all: same id ⇒ compare the two records.
2. **Helpers erased** — task monitors and gate jobs vanish; their meaning folds into arrows.
3. **Formulas tidied** — flatten, dedupe, sort. `B & A` and `A & B` become the same text.
4. **Reused sub-workflows copied out per use** — you compare what actually runs.
5. **Only logic in the file** — schedules, owners, machines are kept aside as metadata and
   never enter the comparison.

Then each node becomes **one sorted line** in a file:

```
etl/load : AND(etl/extract:SUCCESS, OR(ref/dim_fallback:FAILURE, ref/dim_load:DONE))
```

Two systems, same logic → **byte-identical lines** → comparing graphs is just `diff`.

---

## 7. The short honest list of what can't match

| | Why |
|---|---|
| AutoSys lookback (`success(J, 04.00)`) | Stonebranch has no time-windowed dependency |
| AutoSys `notrunning` / `terminated` | no Stonebranch connector equivalent |
| Stonebranch skip-propagation on conditional paths | runtime behavior, not definition — out of scope |
| AutoSys `box_success` override | Stonebranch can't express custom workflow completion — a real difference, and it *should* show in the diff |

---

## 8. Worked example — full skeleton file

Live file: [`data/skeleton-example.json`](../data/skeleton-example.json). The scenario:

```
┌─ ETL ─────────────┐          ┌─ REPORTING ──────────────┐
│  extract          │          │  build_report            │
│    │ success      │ ETL:     │    ▲     │ success       │
│    ▼              ●─SUCCESS──┼────┘     ▼               │
│  transform        │ (whole   │  publish                 │
│    │ success      │  box)    └──────────────────────────┘
│    ▼              │
│  load ────────────┼─── load:SUCCESS ──┐  (one job)
└───────────────────┘                   │
                              ┌─ ARCHIVE ▼───────┐
                              │  copy_files      │
                              └──────────────────┘
```

The entire skeleton — one node per line, sorted by id (canonical order):

```jsonc
{"id":"archive",                "kind":"container", "parent":null,        "trigger":null}
{"id":"archive/copy_files",     "kind":"unit",      "parent":"archive",   "trigger":"etl/load:SUCCESS"}
{"id":"etl",                    "kind":"container", "parent":null,        "trigger":null}
{"id":"etl/extract",            "kind":"unit",      "parent":"etl",       "trigger":null, "meta":{...}}
{"id":"etl/load",               "kind":"unit",      "parent":"etl",       "trigger":"etl/transform:SUCCESS"}
{"id":"etl/transform",          "kind":"unit",      "parent":"etl",       "trigger":"etl/extract:SUCCESS"}
{"id":"reporting",              "kind":"container", "parent":null,        "trigger":null}
{"id":"reporting/build_report", "kind":"unit",      "parent":"reporting", "trigger":"etl:SUCCESS"}
{"id":"reporting/publish",      "kind":"unit",      "parent":"reporting", "trigger":"reporting/build_report:SUCCESS"}
```

Fields, in fixed order: `id` (containment path), `kind` (`unit` | `container`), `parent`
(containment), `trigger` (when may I start), optional `meta` (never compared).

The two lines worth staring at:

- **Dependency on a box** — `build_report` has `trigger:"etl:SUCCESS"`. The nodeRef is simply a
  *container's id*; nothing special in the format. The meaning is special: `etl`'s SUCCESS is
  **derived from its children**, so this fires only when the whole box completes. Visually: the
  arrow starts on the box **border** — the border *is* the node.
- **Dependency on one job** — `copy_files` has `trigger:"etl/load:SUCCESS"`. Fires as soon as
  `load` finishes, regardless of the rest of ETL.

Also note `etl/extract` has `trigger:null` yet doesn't start at will — its unwritten condition is
"my container started". `parent` already says that, so we never write it (rule from §4).

Richer triggers use the same one-line form, e.g.
`"AND(etl/extract:SUCCESS, OR(ref/dim_load:DONE, ref/dim_fallback:FAILURE))"`.

Where each system's syntax lands:

| Skeleton line | AutoSys JIL | Stonebranch |
|---|---|---|
| `etl` container | `insert_job: ETL  job_type: BOX` | workflow "ETL" |
| `parent:"etl"` on extract | `box_name: ETL` | task placed inside the workflow |
| `transform ← extract:SUCCESS` | `condition: s(EXTRACT)` | connector extract →(Success)→ transform |
| **`build_report ← etl:SUCCESS`** | `condition: s(ETL)` — a box name in a condition | Task Monitor watching workflow "ETL", connector to build_report; the monitor node is **erased** (§2), leaving this line |
| `copy_files ← etl/load:SUCCESS` | `condition: s(LOAD)` | Task Monitor watching task "load" → same erasure |

Both systems produce these identical nine lines — that is the whole comparison trick. The sources
are wildly asymmetric (AutoSys: one token in a condition string; Stonebranch: an entire helper
task) but the *logic* is the same, so the skeleton is the same.

---

## 9. The skeleton is a file; pictures are renders of it

```
skeleton file ──▶ viewer renders it ──▶ boxes & arrows on screen
      │
      └────────▶ diff two skeletons ──▶ the comparison
```

Don't choose between "format" and "picture" — they're layers. Comparison always happens on the
file (sorted lines diff; pictures don't). Visualization is for humans exploring one graph — and
a future **diff view** can render the union of two skeletons with colors: green = only in B,
red = only in A, amber = same node, different trigger.

---

## 10. Can the existing viewers draw this? (verified live)

**Cytoscape — yes, natively.** The two kinds map 1:1 onto features already used by
`cytoscape/index.html`:

| Skeleton | Cytoscape |
|---|---|
| `unit` | ordinary (leaf) node |
| `container`, expanded | **compound node** (node with `parent` children; draws as a box, auto-sizes) |
| `container`, collapsed | leaf "chip" node (view-model swap) |
| per-kind styling | style selectors on `node[kind="..."]` |

The critical capability — an **edge whose target is a container** — was verified in the running
viewer: an edge `box:staging → training` (target = the compound itself) is accepted, renders with
the arrowhead on the compound's **border**, and carries a predicate label (`SUCCESS (whole box)`).
No workarounds needed.

What the viewer still lacks is only semantic wiring, not rendering ability: read `trigger`
instead of `depends_on`, keep container-target edges permanent (today edges point at boxes only
as a collapse-display trick), and show predicate labels on non-success edges.

Layout note: dagre doesn't understand compounds, but the viewer computes positions itself
(hierarchical two-pass, `preset`) — and a box-level dependency is genuinely useful input for the
outer box-arrangement pass.

**React Flow — yes, with one asymmetry:** `parentId` sub-flows give the same nesting, but edges
attach to *handles*, so an edge ending on a group's border is clumsier than in Cytoscape. On this
specific requirement Cytoscape is the more natural fit.

---

## 11. Design choices — Q&A from discussion

**Q: Different node types for box/job?**
Two *kinds*, not two types: one node table, identical fields (`id, kind, parent, trigger, meta`),
a single `kind` enum. A container has a trigger too (AutoSys boxes have `condition:`; UC
sub-workflow tasks have incoming connectors). The only structural difference: containers may be
parents.

**Q: Why are containers nodes at all (not just visual grouping)?**
Because **you can depend on them**: `condition: success(ETL_BOX)` is legal AutoSys; a UC
sub-workflow is inserted *as a task* with its own status. Arrows point at them ⇒ they must be
nodes. Both vendors already model it this way (a box literally *is* a job, `job_type: BOX`).
Contrast: Airflow TaskGroups are grouping-only — possible for Airflow because groups have no
status; ours do.

**Q: Why not more kinds (box vs workflow, command vs file-watcher)?**
Decision rule: *does it change dependency or containment semantics?* Container passes (children,
derived status, gating). Box-vs-workflow fails — mapping them to the same kind is the whole
thesis. Job subtypes fail — same logic implemented as different task types should still match;
type goes to `meta`.

**Q: Why not rewrite `success(BOX)` into conditions on its children?**
Because `success(BOX) ≠ AND(success(children))` in general (AutoSys `box_success` overrides,
ON_ICE members), and the rewrite would explode edges and produce diff noise whenever box
membership changes. Keep the arrow on the container — it preserves the author's intent and keeps
diffs stable.
