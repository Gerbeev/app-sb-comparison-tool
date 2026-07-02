# Prompt 01 — Expression core and skeleton model

## Objective

Create two new modules, `stonebranch_graph/expr.py` and `stonebranch_graph/skeleton.py`,
implementing the canonical trigger-expression model and the skeleton node model defined in
`docs/mapping-theory.md` §2, §5 (N4, N5, N7) and §7. These are pure, dependency-free data
modules; nothing else in the codebase is modified in this step.

## Context — read ONLY these, in this order

1. `docs/mapping-theory.md` — sections 2, 5, 7 (skip 3, 4, 6, 8).
2. `docs/skeleton-example.json` — the target serialization shape.
3. `stonebranch_graph/core.py` — reuse `stable_hash`, `normalize_name`, `comparison_name`.
4. `stonebranch_graph/exporters.py` lines 112–147 only (`write_canonical_json`, `stable_value`)
   — follow the same determinism conventions.

Do not read the parsers, compare.py, or the HTML modules. They are irrelevant here.

## Requirements

### A. `stonebranch_graph/expr.py`

1. Immutable expression tree (frozen dataclasses):
   - `Atom(node_ref: str, predicate: str, qualifier: str = "")`
   - `And(children: tuple[Expr, ...])`, `Or(children: tuple[Expr, ...])`, `Not(child: Expr)`
   - `Expr = Atom | And | Or | Not` (type alias).
2. Predicate constants: `SUCCESS`, `FAILURE`, `DONE`, `TERMINATED`, `NOT_RUNNING`, and
   `EXIT` with qualifier carrying the operator+operand (e.g. qualifier `"=0"`, `">1"`).
   Lookback windows are also qualifiers (e.g. `"04:00"`). One `qualifier` string field is
   enough; do not build a qualifier class hierarchy.
3. `canonicalize(expr) -> Expr` implementing **N4 exactly**:
   - flatten nested same-type n-ary nodes: `AND(AND(a,b),c) → AND(a,b,c)`;
   - deduplicate identical children;
   - collapse single-child `And`/`Or` to the child;
   - sort children by sort key `(node_ref, predicate, qualifier)` for atoms and by rendered
     string for composite branches;
   - **no DNF conversion, no distribution, no negation pushing** — docs explicitly forbid
     aggressive minimization.
4. `render(expr) -> str` producing the canonical string used in skeleton lines:
   - atom: `node_ref:PREDICATE` — with qualifier: `node_ref:PREDICATE[qualifier]`;
   - composite: `AND(child, child, ...)` / `OR(...)` / `NOT(child)`, children comma+space
     separated, rendered after canonicalization. Must reproduce the trigger strings shown in
     `docs/skeleton-example.json` and mapping-theory §7 byte-for-byte.
5. `parse(text) -> Expr` — recursive-descent parser accepting exactly the `render` grammar
   (round-trip guarantee: `parse(render(e)) == canonicalize(e)`). Raise `ExprSyntaxError`
   (define it here) with position info on bad input.
6. `atoms(expr) -> tuple[Atom, ...]` — all atoms, document order.
7. `success_and_only(expr) -> list[str] | None` — if the expression is exactly one atom with
   predicate SUCCESS and no qualifier, or an `And` of such atoms, return the sorted node_refs;
   else `None`. This is the §7 backward-compat bridge to `depends_on` lists.
8. `fold_done(pairs)` helper for **N5**: given an iterable of `(node_ref, predicate, qualifier)`
   atoms that feed one AND context, replace any {SUCCESS, FAILURE} pair on the same `node_ref`
   with a single `DONE` atom (qualifiers must be empty/equal to fold). Never expand `DONE`.
9. Projection helpers for strictness levels (used later by compare):
   - `topology_view(expr) -> str` — canonical render with predicates and qualifiers erased,
     atoms reduced to node_refs, still sorted/deduped (an AND(a:SUCCESS,a:FAILURE) topology
     view is just the ref once);
   - `logic_view(expr) -> str` — canonical render with qualifiers erased;
   - `strict_view(expr) -> str` — full canonical render.

### B. `stonebranch_graph/skeleton.py`

1. `SkeletonNode` frozen dataclass, field order fixed: `id: str`, `kind: str` (`"unit"` |
   `"container"`), `parent: str | None`, `trigger: Expr | None`,
   `completion: Expr | None = None`, `meta: dict = field(default_factory=dict)`.
   Constants `KIND_UNIT = "unit"`, `KIND_CONTAINER = "container"`, external prefix
   `EXT_PREFIX = "ext:"`.
2. `Skeleton` container: `nodes: dict[str, SkeletonNode]`, `externals: set[str]`,
   `warnings: list[str]`; `add_node` rejects duplicate ids with a warning (keep first);
   ids referenced by any atom but not present and not `ext:` are auto-registered in
   `externals` by a `validate()` method that also detects containment cycles.
3. Logical-id helpers:
   - `logical_leaf(name: str) -> str` = `normalize_name(comparison_name(name))` from core.py;
   - `child_id(parent_id: str | None, leaf: str) -> str` = `leaf` if no parent else
     `f"{parent_id}/{leaf}"` (containment-path ids per N6/§7).
4. Serialization (`to_jsonl`, `from_jsonl`):
   - one JSON object per line, **sorted by id**, key order exactly
     `id, kind, parent, trigger, completion, meta`; `trigger`/`completion` rendered via
     `expr.render` or `null`; omit `completion` and `meta` keys entirely when empty;
   - `to_canonical_jsonl(level)` — comparison view: meta always omitted; level
     `"topology"|"logic"|"strict"` selects the expr projection; at topology level `trigger`
     holds the topology view string.
5. Per-node hashes: `node_hash(node, level) -> str` = `stable_hash` of the canonical line
   content for that level. `index_rows(skeleton) -> list[dict]` producing
   `{id, kind, parent, topology_hash, logic_hash, strict_hash}` sorted by id.
6. `depends_on_view(skeleton) -> dict[str, list[str]]` — for every node whose trigger passes
   `success_and_only`, its id → sorted ref list (viewer bridge, §7 backward compatibility).

### C. Tests — `tests/test_expr.py`, `tests/test_skeleton.py`

- Round-trip parse/render on: single atom; qualifier atom (`etl/load:SUCCESS[04:00]`);
  nested AND/OR from mapping-theory §8 worked example
  (`AND(etl/extract:SUCCESS, OR(ref/dim_fallback:FAILURE, ref/dim_load:DONE))`).
- Canonicalization: `B & A` ≡ `A & B`; `AND(AND(a,b),c)` flattening; dedupe; single-child
  collapse; stable ordering of mixed atom/composite children.
- `fold_done`: success+failure same ref folds; different refs don't; DONE never expands.
- `success_and_only` on positive/negative cases.
- Skeleton JSONL: serialize the exact 9-node example from `docs/skeleton-example.json` and
  assert byte equality with a checked-in expected string (rebuild it in the test; do not read
  the docs file at runtime).
- `validate()` external auto-registration and containment cycle detection.

## Out of scope

No parser changes, no builders, no comparison, no CLI, no viewer. No new dependencies
(stdlib only, matching the project).

## Acceptance criteria

1. `python -m pytest tests/test_expr.py tests/test_skeleton.py -q` passes.
2. `ruff check stonebranch_graph/expr.py stonebranch_graph/skeleton.py` clean
   (line-length 100, py311 — see pyproject).
3. Rendered trigger strings match docs examples byte-for-byte.
4. All public functions have one-line docstrings; module docstrings reference
   `docs/mapping-theory.md` section numbers.

## Cost guidance

Read only the four context items listed. Write both modules in single Write calls (no
incremental edits). Run only the two new test files, not a full suite. Do not reformat or
touch any existing file.
