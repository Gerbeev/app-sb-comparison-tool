# Task 11 — Skeleton comparison re-serializes and re-hashes the graph several times (MEDIUM)

> Performance track. Must not change comparison output — this is a pure refactor for speed.

## Where the cost is
`skeleton_compare.py` walks the full node set several independent times per comparison:

1. `_canonical_maps(skeleton)` calls `skeleton.to_canonical_jsonl(level)` for **each** of the three
   levels, then `json.loads` **every line again** to rebuild records — i.e. render + serialize +
   parse, 3×, for both skeletons.
2. `_row_index(skeleton)` → `index_rows(skeleton)` recomputes per-node hashes for all three levels
   (`node_hash` → `_node_record` → `render`) — a 4th full pass.
3. `_index_rows(comparison)` calls `index_rows(...)` **again** for both sides (5th/6th pass).
4. `_meta_layer` loops the intersection building `Node` adapters and command-diff payloads.

`render`/`_render`/`_render_projection` are `@lru_cache`d, so repeated identical expressions are
cheap, but record-dict construction, `json.dumps`, and `json.loads` are not cached and run on every
pass. For 10k nodes this is several MB of JSON churned repeatedly. It is likely "seconds," not
"minutes," but it is easy to cut by ~3–5×.

## Fix (behavior-preserving)
1. **Build once, reuse.** Compute, per skeleton, a single structure keyed by node id holding:
   the three canonical records (topology/logic/strict dicts), their serialized lines, and their
   three hashes. Derive `_status_at_level`, `_reasons`, `_index_rows`, and `_canonical_maps`
   consumers from that one structure instead of re-serializing/re-parsing.
2. Have `index_rows` and `_canonical_maps` share the same per-node record builder (compute the
   record dict once, then both `json.dumps` it for the line and `stable_hash` it for the index).
3. Keep outputs byte-for-byte identical — assert equality against the current implementation in a
   test before deleting the old paths.

## Notes / guardrails
- Parsers are already O(1)-indexed (`_build_registry` by (env,kind,name); AutoSys
  `by_exact_id`/`by_canonical_key`), and `erase_plumbing` uses an incremental `_ReferenceIndex`, so
  the build/normalize stages are not the bottleneck — do not rework them.
- `expr.canonicalize`/`render` caches are process-wide `lru_cache`; if you add a very large
  synthetic benchmark, consider clearing them between runs to measure honestly.

## Acceptance
- `compare_skeletons` output (diff json, index csv, report) is byte-identical before/after on the
  example fixtures.
- On the 10k benchmark (task 07), compare-stage wall-clock drops materially (target ≥ 2× faster)
  with unchanged results.
