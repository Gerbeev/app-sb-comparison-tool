# Mapping AutoSys and Stonebranch to one comparable graph skeleton (theory)

> **New here? Read [mapping-explained.md](mapping-explained.md) first** — the plain-language
> version with pictures (what's a node, what's an edge, how other systems do it).
> This file is the precise spec.

Goal: define a **canonical dependency graph** ("skeleton") such that an AutoSys JIL export and a
Stonebranch Universal Controller (UC) export, when both describe the *same scheduling logic*,
normalize to **byte-identical** canonical files — so comparison is a plain `diff`, not graph math.

Design rule that follows from the goal: *never compare source syntax; compare normalized logic.*
Everything below is about which logic to keep, which to erase, and which canonical form to force.

---

## 1. The core asymmetry you must design around

| | AutoSys | Stonebranch UC |
|---|---|---|
| Dependency carrier | **Condition expression on the job** — `condition: success(A) & (done(B) \| failure(C))`; arbitrary boolean over any job anywhere | **Connector (edge) inside a workflow** — predecessor → successor with a condition (success / failure / exit code); a task with several incoming connectors waits for **all** of them (AND) |
| OR logic | native (`\|`) | not native — approximated with duplicate tasks / conditional paths + skip propagation |
| Scope of a dependency | global (any job, any box, other instance via `job^INSTANCE`) | local to the workflow; **cross-workflow = Task Monitor task** (a real node that waits on an external task status) |
| Grouping | box (nestable); jobs may also live outside any box | workflow (nestable via sub-workflow); every task runs inside some workflow instance |

Conclusion: the canonical skeleton must carry dependencies as **trigger expressions attached to
nodes** (the AutoSys-shaped, more expressive model). UC's edges compile *into* that form losslessly
(AND of per-edge atoms); the reverse is not generally possible. Plain edges remain recoverable as
the degenerate case "AND of SUCCESS atoms" — which is exactly the `depends_on` list our current
viewers consume.

---

## 2. Canonical skeleton model

### 2.1 Node kinds (only two)

| Kind | Meaning | AutoSys source | UC source |
|---|---|---|---|
| `container` | grouping with a lifecycle (starts, completes from children) | box | workflow / sub-workflow usage |
| `unit` | atomic executable | command, file watcher, FTP, … job types | task (all task types) |

Job/task *type* (command vs file-watcher vs script) is metadata, **not** part of the skeleton:
two systems implementing the same step differently should still match.

### 2.2 Two relations, kept separate

1. **Containment** — a forest: every node has `parent: <containerId> | null`.
   AutoSys `box_name` → parent. UC workflow membership → parent. Nested box ≈ sub-workflow.
2. **Trigger** — per node, one boolean expression over **atoms**:

```
atom      := ( nodeRef, predicate )
predicate := SUCCESS | FAILURE | DONE | TERMINATED | NOT_RUNNING | EXIT(op, int)
expr      := atom | AND(expr...) | OR(expr...) | NOT(expr)      # n-ary, flattened
```

Canonical state vocabulary mapping:

| Canonical | AutoSys | UC |
|---|---|---|
| SUCCESS | `success(j)` / `s(j)` | connector condition Success |
| FAILURE | `failure(j)` / `f(j)` | connector condition Failure |
| DONE | `done(j)` / `d(j)` | connector Success **or** Failure (a "finished" path) |
| TERMINATED | `terminated(j)` / `t(j)` | *(no direct analog — see §6)* |
| NOT_RUNNING | `notrunning(j)` / `n(j)` | *(no direct analog — see §6)* |
| EXIT(op,n) | `exitcode(j) op n` | connector exit-code condition |

### 2.3 What is deliberately implicit (identical in both systems, so never materialized)

- "My container has started" — an AutoSys job in a box needs the box RUNNING; a UC task needs its
  workflow instance launched. Same semantics ⇒ keep it implied by containment, don't emit atoms.
- Container completion — default rule "container completes from its children" is implied.
  Only **non-default** completion logic (AutoSys `box_success`/`box_failure` overrides) becomes an
  explicit `completion` expression attribute on the container. UC has no user-defined workflow
  success expression, so a UC workflow always has the default — if the AutoSys side uses an
  override, that's a *real* logic difference and **should** show in the diff.

---

## 3. AutoSys → skeleton

| JIL construct | Mapping |
|---|---|
| `insert_job: X job_type: BOX` | `container` node |
| box inside box (`box_name` on a box) | nested container (parent) |
| any non-box job | `unit`, parent = its `box_name` (or null) |
| `condition:` | parse to expression tree → atoms per §2.2 → canonicalize per §5 |
| condition on a **box** (`success(BOX_B)`) | atom whose `nodeRef` is the container — allowed as-is; box status *is* a first-class status in AutoSys |
| lookback `success(J, 04.00)` | atom qualifier `window: "04:00"` — kept, but see §6 (no UC analog) |
| cross-instance `success(J^PRD)` | `nodeRef` = `ext:PRD/J` — external-namespace node reference; the node itself may be absent from this graph (declared as a stub) |
| `date_conditions`, calendars, `start_times` | **not dependency logic** → metadata, excluded from the skeleton and from comparison |
| machine, owner, priority, alarms | metadata, excluded |
| dummy/"gate" boxes or 0-command jobs used purely to AND/OR fan-ins | plumbing — erased by N3 (§5) |

## 4. Stonebranch → skeleton

| UC construct | Mapping |
|---|---|
| Workflow | `container` |
| Workflow inserted into a Workflow (sub-workflow) | nested container. If the same workflow *definition* is reused in several parents, each usage is **inlined as a separate instance** with a path-qualified id (`parentWf/childWf/task`) — comparison is about instantiated logic, not shared definitions. This also covers "inherited" workflows: expand to what actually runs. |
| Task (any type) | `unit` |
| Connector predecessor→successor with condition c | contributes atom `(predecessor, c)` to the **successor's** trigger |
| Multiple incoming connectors | `AND(atoms...)` — documented UC behavior: a task runs when it is no longer waiting on **any** predecessor |
| Conditional branches (Success path / Failure path) | each path contributes its atom; the *skip* of the untaken branch is runtime behavior, not definition logic — not modeled (see §6) |
| **Task Monitor** task waiting on an external task/workflow status | **plumbing — erased.** The monitor node is deleted; every successor of the monitor gets the monitor's external condition substituted into its trigger: `ext:<...>/<task>` with the monitored status predicate. This is *the* UC idiom for cross-workflow dependency, and after erasure it becomes structurally identical to an AutoSys cross-box condition — which is exactly what "match if the logic is the same" requires. |
| Virtual resources / mutual exclusivity | **not precedence** (it's runtime arbitration, order-free) → excluded from skeleton; optionally a separate `resources` layer never included in the comparison hash |
| Triggers (time/cron) | like AutoSys calendars: metadata, excluded |

---

## 5. Normalization rules (what makes "same logic ⇒ same bytes" true)

- **N1 — Identity aliasing.** Node names differ across systems (`ACME_LOAD_ORDERS` vs
  `acme-load-orders`). Comparison is anchored on a **logical-id alias table** (per system:
  `nativeName → logicalId`), maintained by you. This converts graph comparison from isomorphism
  (hard, ambiguous) into keyed record comparison (trivial, exact). Unmapped names surface as
  additions/removals — which is signal, not noise.
- **N2 — Implicit containment start** (§2.3): never emit "container started" atoms; if a source
  condition literally restates it (AutoSys job depending on its own box's RUNNING), drop it as
  redundant.
- **N3 — Plumbing erasure.** Nodes that carry no business action, only dependency glue
  (UC Task Monitors, UC Sleep/dummy tasks, AutoSys gate jobs marked as such in the alias table),
  are removed by **substitution**: successor triggers inherit the erased node's own trigger /
  monitored condition. Repeat until fixpoint.
- **N4 — Boolean canonical form.** Parse → n-ary flatten (`AND(AND(a,b),c) → AND(a,b,c)`) →
  eliminate duplicates → **sort atoms** (by nodeRef, then predicate, then qualifier) → sort
  branches → *no* aggressive minimization beyond that (don't convert to full DNF: it can explode
  and both systems' authors think in the same shapes anyway; flatten+sort is enough for
  same-logic-same-bytes, and a semantic-equivalence checker can be layered later if needed).
- **N5 — Predicate desugaring is one-way and consistent.** `done` stays `DONE` (do **not** expand
  to `OR(SUCCESS,FAILURE,TERMINATED)`) — but the UC pattern "connector on Success **and** parallel
  connector on Failure from the same predecessor" is *folded up* to `DONE`. Always desugar toward
  the **coarser** shared vocabulary so both sides land on the same token.
- **N6 — Instance expansion** (§4): inline reused sub-workflows; ids are containment paths.
- **N7 — Skeleton vs meta.** The skeleton = `{kind, parent, trigger, completion?}` per node.
  Everything else (`owner, machine, command, schedule, type…`) lives under `meta` and is excluded
  from the canonical serialization used for comparison.

**Canonical serialization** — reuse the repo's existing convention (it was built for this):
one node per line, sorted by id, fixed key order, triggers rendered as a canonical string, e.g.
`AND(ext:PRD/feed:SUCCESS, OR(stage_a:DONE, stage_b:FAILURE))`. Equality = file equality;
comparison = `diff`/`git diff`; a per-node hash column gives O(1) "which nodes changed".

Three comparison strictness levels (report all three):
1. **Topology** — node set + containment + atom *nodeRefs* only (are the same things wired?).
2. **Logic** (default) — level 1 + full trigger expressions with predicates.
3. **Strict** — level 2 + qualifiers (lookback windows, exit-code ranges, completion overrides).

---

## 6. Honest mismatch table (where "same logic" is undefinable)

| Feature | Problem | Recommended handling |
|---|---|---|
| AutoSys lookback `success(J, 04.00)` | UC has no time-windowed dependency | keep qualifier; matches only at level ≤ 2; strict diff flags it |
| AutoSys `notrunning`, `terminated` | no UC connector equivalent (UC would use a Task Monitor with those statuses — which N3 maps back correctly if used) | if unmatched, it's a real logic gap — let it diff |
| UC skip-propagation (untaken conditional path skips downstream tasks) | AutoSys jobs don't "skip"; unmet conditions just never fire | definitional graphs are unaffected; document that *runtime* trace comparison is out of scope |
| AutoSys ON_ICE/ON_NOEXEC folding into `success`/`done` | operational states leaking into semantics | ignore — state *evaluation* detail, not definition logic |
| AutoSys `box_success` override | UC can't express custom workflow completion | container gets explicit `completion` expr → strict diff flags, correctly |
| UC Run Criteria (run/skip by variable, day, etc.) | closer to AutoSys date_conditions than to dependencies | metadata, excluded (both sides consistently) |

---

## 7. Skeleton schema (extends the existing `graph-data.json` shape)

> Runnable example: [`skeleton-example.json`](skeleton-example.json), walked through
> in [mapping-explained.md §8](mapping-explained.md).

```jsonc
{
  "nodes": [
    // one line each, sorted by id — same diff-friendly discipline as today
    {"id":"etl/load_orders","kind":"unit","parent":"etl",
     "trigger":"AND(etl/extract_orders:SUCCESS, OR(ref/dim_load:DONE, ref/dim_stub:SUCCESS))",
     "meta":{"src":"autosys","native":"ACME_LOAD_ORDERS"}},
    {"id":"etl","kind":"container","parent":null,"trigger":null}
  ],
  "externals": [ {"id":"ext:PRD/feed"} ]        // referenced-but-not-owned stubs
}
```

Backward compatibility: today's `depends_on:[a,b]` ≡ `trigger:"AND(a:SUCCESS, b:SUCCESS)"` —
so both existing viewers keep working on any skeleton whose triggers are pure success-ANDs, and
richer triggers degrade gracefully to edges-with-annotations for display.

### Worked example — same logic, two systems, one skeleton

AutoSys:
```
insert_job: LOAD  box_name: ETL
condition: s(EXTRACT) & (d(DIM_LOAD) | f(DIM_FALLBACK))
```
UC: workflow `ETL` with connectors `EXTRACT --Success--> LOAD`, plus a Task-Monitor pattern
providing the `DIM_LOAD finished OR DIM_FALLBACK failed` gate feeding `LOAD`.

Both normalize (N1 aliases: `EXTRACT→etl/extract`, etc.; N3 erases the monitor; N4 sorts) to:
```
etl/load : AND(etl/extract:SUCCESS, OR(ref/dim_fallback:FAILURE, ref/dim_load:DONE))
```
Identical line ⇒ identical logic. Any deviation shows as a one-line diff on the node that differs.

---

## 8. Pipeline (when we implement)

```
JIL export ──parse──▶ raw model ─┐
                                 ├─▶ normalize (N1–N7) ─▶ skeleton.json ─▶ diff / hash / viewer
UC export  ──parse──▶ raw model ─┘        ▲
                                   alias table (per system)
```

Sources: [AutoSys condition attribute (Broadcom)](https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/autosys-workload-automation/12-0-01/reference/ae-job-information-language/jil-job-definitions/condition-attribute-define-starting-conditions-for-a-job.html) ·
[AutoSys dependencies guide (UMN, r11.3)](https://it.umn.edu/sites/itumn.umn.edu/files/AutoSys%20r11.3%20Understanding%20Job%20Scheduling%20Dependencies%20V3.pdf) ·
[UC Creating & Maintaining Workflows](https://docs.stonebranch.com/uac/uc/creating-and-maintaining-workflows) ·
[UC Workflows PDF (7.9)](https://docs.stonebranch.com/attachments/uac-7-9-x-pdfs-universal-controller-7-9-x-workflows.pdf) ·
[UC task predecessor satisfy/clear semantics](https://stonebranchdocs.atlassian.net/wiki/spaces/UC75/pages/206392829/Manually+Running+and+Controlling+Tasks)
