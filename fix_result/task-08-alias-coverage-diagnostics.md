# Task 08 — Alias coverage diagnostics are not surfaced in the skeleton report (MEDIUM)

## Problem
N1 makes the alias table the anchor of the whole comparison. Its correctness therefore determines
the trustworthiness of every "matched"/"missing" verdict. `alias.py` already tracks the data needed
to audit coverage:
- `AliasUsage.logical_hits / logical_misses / plumbing_hits / plumbing_misses`
- `AliasTable.unused_entries()`

But nothing surfaces it in the skeleton pipeline. `skeleton_compare.py` never reads alias usage,
and the workflow only appends `alias.warnings` to `skeleton.warnings`. A maintainer cannot see:
- which native names had **no** alias entry (so they were matched by normalized leaf, which may be
  a coincidence), or
- which alias entries were configured but **never used** (typos, stale names).

For a real migration this is the difference between "89% matched, and here is exactly why the other
11% is unmapped" and an opaque percentage.

## Fix
1. Thread alias usage into the comparison. `compare_skeleton_direct` (in `workflows.py`) already
   holds the `AliasTable`; pass an alias-coverage summary into `SkeletonComparison.meta`:
   ```python
   meta["alias_coverage"] = {
     "unused_entries": alias.unused_entries(),
     "logical_misses": sorted(alias.usage.logical_misses),
     "hit_count": len(alias.usage.logical_hits),
   }
   ```
   (Use one shared `AliasTable` instance for both builders so usage accumulates across sides.)
2. In `skeleton_compare.write_skeleton_report`, add an "## Alias coverage" section: count of
   aliased vs leaf-matched nodes, list unused entries and misses (capped, like other sections).
3. In `skeleton_metrics`, expose `alias_unused` / `alias_miss` counts. Do **not** hard-penalize the
   score for misses (unmapped is legitimate signal per N1), but add a `build_skeleton_risks` line
   when unused entries exist (they usually mean a typo that is silently weakening matching).

## Acceptance (task 07 fixtures)
- An alias file with one entry whose native name matches nothing → report "Alias coverage" lists it
  under unused entries and a risk is raised.
- A native object with no alias entry → counted under leaf-matched, listed under misses.
