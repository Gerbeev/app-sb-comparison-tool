# Task 05 — External-reference id formats differ between the two builders (MEDIUM)

## Problem
Concept §3 / §7: cross-instance / cross-namespace references use `ext:<ns>/<name>` (e.g.
`ext:PRD/feed`). External stubs are listed in `Skeleton.externals` and compared in
`skeleton_compare._external_diff`.

The two builders emit **different id shapes** for externals, so the same external dependency will
not match across systems:

- AutoSys: `jil_condition._node_ref` maps `J^PRD` → `ext:PRD/<leaf>` (namespace kept). ✔ matches
  the concept.
- Stonebranch: `skeleton_stonebranch._monitor_payload` builds an external target as
  `EXT_PREFIX + logical_leaf(target_name)` → `ext:<leaf>` (**no namespace segment**).

So a UC Task Monitor watching an external task `feed` becomes `ext:feed`, while the AutoSys side
of the same migration produces `ext:PRD/feed`. `_external_diff` then reports both as
`only_in_*` — a false mismatch on exactly the cross-workflow dependencies that N3 was designed to
make comparable.

## Fix
1. **Unify the grammar.** Decide a single canonical external id form `ext:<ns>/<leaf>` where `<ns>`
   is optional but, when absent, both sides must agree. Two workable options — pick one and apply
   to *both* builders:
   - (a) Always require a namespace. Give the UC monitor an `ext:` namespace derived from the
     monitored object's owning workflow/business unit, configurable via the alias table.
   - (b) Allow a bare `ext:<leaf>` and make the AutoSys side drop the namespace at
     comparison time — **not recommended**, loses real signal.
   Prefer (a).
2. **Alias support for externals.** Extend `alias.py` so an alias value may resolve a native name
   to an `ext:...` id on either side, letting the maintainer state "UC's `feed` == AutoSys's
   `feed^PRD` == `ext:PRD/feed`." Apply in `_monitor_payload` (SB) and in
   `jil_condition._node_ref` / `skeleton_autosys._rewrite_condition_refs` (JIL).
3. **Normalize in one place.** Add `skeleton.external_id(ns, leaf)` helper used by both builders so
   the format can never drift again.

## Acceptance (task 07 fixtures)
- UC Task Monitor on external `feed` (namespace `PRD` via alias) and AutoSys `success(feed^PRD)`
  both yield external id `ext:PRD/feed`; `_external_diff["matched"]` contains it and neither
  `only_in_*` list does.
- With no alias/namespace configured, the report explicitly flags the external as
  namespace-ambiguous rather than silently mismatching.
