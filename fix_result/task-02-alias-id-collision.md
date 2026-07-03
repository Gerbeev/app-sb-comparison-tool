# Task 02 — Alias/id collisions silently drop nodes (HIGH)

## Problem
Concept rule **N1** anchors comparison on a per-system `nativeName → logicalId` alias table and
says *"Unmapped names surface as additions/removals — which is signal, not noise."* The same
principle must hold for **collisions**: two distinct native objects that map to the **same**
skeleton id are a data/alias error and must be surfaced, not hidden.

Today they are hidden. `skeleton.py::Skeleton.add_node`:

```python
if node.id in self.nodes:
    self.warnings.append(f"Duplicate skeleton node id ignored: {node.id}")
    return self.nodes[node.id]
```

The second object is dropped; only a free-text warning remains. Nothing in
`skeleton_compare.py` promotes this to a risk or a report row.

This is reachable with the shipped example. `examples/alias.json` maps AutoSys
`JOB_A → etl/extract` and also `EXTRACT → etl/extract` (leaf `extract` under box `ETL`). With both
`etl_example.jil` (EXTRACT) and `sample.jil` (JOB_A) loaded, both resolve to id `etl/extract` and
one is silently discarded — even though they have different commands
(`/app/extract.sh` vs `/app/job_a.sh`). At migration scale (thousands of jobs, hand-maintained
alias), silent merges become **missed diffs**: the reconciliation reports "match" for a node that
actually lost a definition.

## Fix
1. **Record collisions as structured data**, not just warnings. In `skeleton.py`, add
   `Skeleton.collisions: list[dict]` and, in `add_node`, when `node.id` already exists, append
   `{"id": node.id, "kept_native": <existing meta.native>, "dropped_native": <new meta.native>,
   "kept_src": ..., "dropped_src": ...}` in addition to the warning.
2. **Surface in the comparison.** In `skeleton_compare.py`:
   - Add the counts to `skeleton_metrics` (e.g. `sb_collisions`, `jil_collisions`) and **penalize
     the readiness score** (each collision is a correctness risk, weight ≈ a topology miss).
   - In `build_skeleton_risks`, add a risk line when either side has collisions.
   - In `write_skeleton_report`, add a "## Id collisions" section listing each collision with
     both native names and source files.
3. **Distinguish intentional merges.** If two natives are *deliberately* the same logical node
   (legitimate N1 aliasing), the alias file should say so. Add an optional
   `"merge": { "<system>": ["logicalId", ...] }` allow-list in the alias schema
   (`alias.py`); collisions on allow-listed ids are downgraded from risk to info.

## Acceptance (task 07 fixtures)
- Two AutoSys jobs aliased to the same id, different commands, not on the merge allow-list →
  `metrics["jil_collisions"] == 1`, a risk is emitted, and the report lists both native names.
- The same pair on the allow-list → no risk, downgraded to info, score unaffected.
