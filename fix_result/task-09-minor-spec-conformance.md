# Task 09 — Minor spec-conformance gaps (LOW)

Small deviations from the concept. None change a correct comparison result on the current examples,
but each is a latent source of confusion or a false diff in an edge case.

## 9a — Topology level compares AND/OR structure, not just nodeRefs
Concept §5 level 1: *"Topology — node set + containment + atom **nodeRefs only** (are the same
things wired?)."* `expr.topology_view` (in `expr.py`) erases predicates and qualifiers but
**keeps** the `AND`/`OR` boolean structure. So `AND(a,b)` vs `OR(a,b)` differ at topology even
though the same things are wired. Two acceptable resolutions — pick one and document it:
- (a) Make `topology_view` collapse to a **sorted set of nodeRefs** (drop AND/OR entirely), matching
  the literal spec; boolean shape then first appears at the `logic` level. Recommended.
- (b) Keep current behavior but update `mapping-theory.md` §5 to state that topology retains
  boolean shape by design.
Update the report legend in `skeleton_compare.write_skeleton_report` to match whichever is chosen.

## 9b — Broken doc paths to the golden example
`IMPLEMENTATION_PLAN.md` §5 already flags this. `mapping-theory.md` §7 links
`../data/skeleton-example.json` and `mapping-explained.md` §8 links `data/skeleton-example.json`,
but the file lives at `docs/concept/skeleton-example.json`. Fix the two relative links so the
worked example resolves. Add a test (task 07) that asserts every relative link in the concept docs
resolves to an existing file.

## 9c — `box_failure` completion modeled as `Not(condition)`
`skeleton_autosys._completion_expression` maps `box_failure` to `Not(parsed)`. This is a heuristic:
AutoSys `box_failure` names the jobs whose failure fails the box; `NOT(...)` is not a faithful
"box completes successfully when" expression. Because UC has no completion analog, any non-null
completion already diffs at strict — so this does not cause a false match, but the rendered
completion string can mislead a reviewer. Either (a) keep raw `box_success`/`box_failure` intent in
`meta` and render completion only when `box_success` is present, or (b) document the `Not(...)`
convention in the report. Low priority; do not block on it.
