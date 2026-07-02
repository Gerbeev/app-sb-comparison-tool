# Prompt 08 — Cytoscape viewer: trigger semantics and skeleton diff view

## Objective

Teach the offline Cytoscape HTML viewer the skeleton semantics per
`docs/mapping-explained.md` §10: nodes carry `kind` + `parent` + `trigger`; edges are
*derived* from trigger atoms and labeled with predicates; edges targeting a container are
first-class and permanent; the comparison view renders the union of two skeletons colored by
diff status (green = only in SB, red = only in JIL, amber = same node different trigger).

## Context — read ONLY these

1. `docs/mapping-explained.md` §9–§10 (viewer capabilities, verified behaviors) and §4
   (how to read combine rules).
2. `stonebranch_graph/html_graph.py` — full file.
3. `stonebranch_graph/skeleton.py` — `Skeleton`, `depends_on_view`, `to_jsonl`.
4. `stonebranch_graph/expr.py` — `atoms`, `render`, `success_and_only`.
5. The generated `graph.html`/`graph-data.js` template strings inside `html_graph.py` (or
   `rendering.py`/assets if the HTML lives there — locate with one grep for `cytoscape`).

## Requirements

### A. Skeleton view-model — new function in `html_graph.py`

`build_skeleton_graph_data(skeleton: Skeleton) -> dict` producing:

1. `nodes`: one entry per skeleton node: `{id, label (leaf of id), kind (unit|container),
   parent, trigger (rendered string or null), plumbing_erased_count?, meta.src, meta.native}`.
   Containers are compound nodes (children set `parent`); keep the existing collapse
   view-model swap mechanism working for them.
2. `edges`: derived per trigger atom: for node T with atom `(R, P, q)` emit
   `{id: "R|P|T", source: R, target: T, predicate: P, qualifier: q, or_group: <int|null>}`.
   `or_group`: atoms under the same OR branch share an index so the JS can style them dashed
   and show "any of" in tooltips; atoms under the root AND get `null`. Direction:
   prerequisite → dependent (arrowhead on the dependent), matching the mental model
   "A --success--> B". Atoms referencing `ext:` ids create stub nodes styled distinctly.
3. Edge label: `P` when SUCCESS, else `P` (+ `[q]` if qualifier). SUCCESS edges may render
   unlabeled in the default style to reduce clutter (docs: predicate labels needed on
   *non-success* edges).
4. **Container-target edges are permanent** — never rewired to children on expand/collapse
   (today edges point at boxes only as a collapse-display trick; that behavior stays for the
   *legacy* view-model but must not apply to skeleton edges).
5. Keep `depends_on` arrays on nodes via `skeleton.depends_on_view` for backward-compatible
   JS paths (docs §7: pure success-ANDs degrade gracefully).

### B. HTML/JS updates

1. Style: `node[kind="container"]` compound styling reused from groups today;
   `node[kind="unit"]` as today's jobs; `edge[predicate!="SUCCESS"]` gets a visible label and
   distinct color; `edge[?or_group]` dashed; `ext:` stubs ghosted.
2. Tooltip/details panel for a node shows the full rendered `trigger` string — this is the
   authoritative combine rule (docs §4), the edges are a projection.
3. Layout: keep the existing hierarchical two-pass preset layout; container-level edges feed
   the outer box-arrangement pass ordering if trivially pluggable — otherwise skip
   (docs note it as "useful input", not a requirement).

### C. Diff view

`export_skeleton_comparison_html(diff_json_path_or_dict, sb_skeleton, jil_skeleton, output_dir)`:

1. Render the **union** of both skeletons: nodes present on both sides once.
2. Node classes from `skeleton-diff.json` statuses (logic level default, switchable to
   topology/strict via a toolbar toggle): `only-sb` green, `only-jil` red, `changed` amber,
   `matched` neutral.
3. Clicking a changed node shows both trigger lines (sb vs jil) in the details panel.
4. Edges: from the SB skeleton for matched/only-sb nodes, from JIL for only-jil; changed
   nodes show SB edges solid + JIL-only atoms as dotted overlays if cheap — otherwise just
   SB edges + textual diff in panel (choose the simpler; note choice in code comment).

### D. Wiring

`export_skeleton_html_report(skeleton, output_dir)` alongside the existing
`export_cytoscape_html_report`; called from `workflows.compare_skeleton_direct` (prompt 07)
for both sides and the diff. Reuse `export_cytoscape_runtime` for cytoscape.min.js.

### E. Tests — `tests/test_skeleton_viewer.py`

View-model only (no browser): OR grouping indices; container-target edge present when a
trigger references a container id; predicate/qualifier labels; ext stub emission;
diff view-model statuses and union-node dedup. Plus one smoke test that the emitted
`graph-data.js` is valid JS-wrapped JSON (strip prefix, `json.loads`).

## Out of scope

Legacy view-model changes, CLI flags, performance tuning of the JS (prompt 09 may cap sizes).

## Acceptance criteria

1. Tests pass; `ruff check` clean.
2. Open the generated `skeleton-graph.html` for the prompt-05 equivalence fixture once
   (headless not required — just assert files exist and JSON parses) — node count 9,
   `reporting/build_report` has an edge whose source is container `etl`.
3. Legacy `graph.html` output unchanged for legacy pipelines.

## Cost guidance

The JS template is large — modify it surgically (targeted string edits near existing style
blocks), never rewrite the whole template. Build view-model logic in Python where it's
testable; keep new JS minimal.
