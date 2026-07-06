# Performance scaling plan — Cytoscape HTML reports at 10k+ objects

Scope: `stonebranch_graph/html_graph.py` only — the Python payload builders
(`build_cytoscape_graph_data`, `build_skeleton_graph_data`, their comparison
variants) and the embedded `CYTOSCAPE_HTML` viewer (CSS/HTML/JS). This is a
plan, nothing here has been implemented yet.

The Python side runs once, offline, in the CLI — it is not the bottleneck.
Everything below happens in the browser, on the machine opening the report,
so it's where "tens of thousands of jobs/edges start to lag" actually comes
from.

## What's actually slow, and why

1. **Every click destroys and rebuilds the whole Cytoscape instance.**
   `buildCy()` (`html_graph.py` ~1541) calls `cy.destroy()` and constructs a
   brand-new `cytoscape({...})` on *every* interaction — expanding a box,
   collapsing one, clicking a job, typing in search, toggling a status
   filter. At a few hundred visible elements this is invisible; at a few
   thousand it's a noticeable stutter per click, because Cytoscape has to
   re-parse the whole style, re-render every node/edge, and re-bind every
   event handler from scratch each time, even though most of the graph
   didn't actually change between clicks.

2. **`layoutOf()` scans the full edge list once per expanded group, not once
   per graph.** Inside `layoutOf()` (~1411): `for (const e of DATA.edges ||
   []) { ... resolveToUnit(...) ... }` runs for *every* group that gets
   laid out — root, and then again for every expanded subgroup, recursively.
   With G expanded groups and E total edges this is O(G × E). At small scale
   (tens of groups, hundreds of edges) that's nothing. At tens of thousands
   of edges and, say, "Expand all" on a few hundred groups, it turns into
   tens of millions of iterations on the main thread — this is the single
   biggest risk for the "expand a lot / expand all" scenario, and it gets
   quadratically worse as both numbers grow together.

3. **No large-graph rendering flags.** The previous (pre-simplification)
   template gated `hideEdgesOnViewport` / `textureOnViewport` / `motionBlur`
   behind an element-count threshold, which keeps pan/zoom smooth once
   there are thousands of rendered elements by not repainting every edge on
   every frame while the view is moving. The new lightweight template does
   not set any of these — worth restoring, since it's a Cytoscape built-in,
   not something we have to build.

4. **Panel lists are unbounded.** `showJobPanel()` renders
   `up.map(depRow).join('')` / `down.map(depRow).join('')` with no cap. A
   root job with a few thousand downstream jobs (common in a big shared
   "staging" or "ingestion" box) would dump a few thousand DOM nodes into
   the side panel in one shot. Edge evidence lists are already capped at
   `.slice(0, 60/80)` — the dependency lists aren't.

5. **Whole-graph JSON payload, parsed synchronously, pretty-printed.**
   `graph-data.js` is one `window.GRAPH_DATA = {...}` literal, generated with
   `json.dumps(payload, indent=2, ...)` unconditionally (`html_graph.py`
   lines 248, 473, 945). `indent=2` is meant for the small/medium case where
   the file should stay diff-friendly for humans; at tens of thousands of
   objects it roughly doubles file size for no runtime benefit, which adds
   directly to load-and-parse time before the page can render anything.

6. **Layout is synchronous on the main thread.** `layeredLayout()` and the
   recursive `layoutOf()` block the UI thread while they run. At small/medium
   scale this is sub-frame. At the scale where (2) above also kicks in, the
   browser tab will visibly freeze for the duration.

None of this is a fundamental design problem — the "everything starts
collapsed" model from the last redesign is exactly the right foundation for
scaling (you never lay out 10,000 jobs unless the user actually expands into
them). The issues above are specifically about what happens *once the user
starts expanding*, and about constant-factor overhead that scales linearly
with total graph size regardless of what's expanded.

## Plan, in priority order

### Phase 1 — quick, low-risk, do these regardless of how large graphs get

- **Index edges per job and reuse it in `layoutOf()`.** `outEdges`/`inEdges`
  (keyed by job id) already exist at the top of the script. Instead of
  scanning all of `DATA.edges` inside every `layoutOf()` call, gather only
  the edges touching `descendantJobs(groupId)` (which is already cached).
  Turns issue (2) from O(G × E) into O(edges actually touching that
  subtree) — the fix that matters most once graphs get big.
- **Restore viewport-performance flags** (`hideEdgesOnViewport`,
  `textureOnViewport`, `motionBlur: false`) in `buildCy()`, gated behind an
  element-count threshold (e.g. > 1500 visible elements, same idea the old
  template used).
- **Cap the up/down dependency lists** in `showJobPanel()` the same way
  evidence lists already are (`.slice(0, N)` + a "N more, not shown" note),
  so one heavily-connected job can't dump thousands of DOM nodes into the
  panel.
- **Emit compact JSON above a size threshold.** Keep `indent=2` for small
  graphs (nice to read/diff), switch to `indent=None` once
  `len(jobs) + len(edges)` crosses a threshold (e.g. 5,000) — free size
  reduction, no behavior change.
- **Guard "Expand all" / unfiltered search-driven expansion** behind a
  confirmation once job count is large (e.g. > 2,000): "This will lay out
  N jobs and may take a few seconds — continue?" so a slow operation is
  opt-in and explained, not a silent freeze.

Expected effect: fixes the worst-case blowup (2), makes pan/zoom usable once
a large subgraph is expanded (3), and prevents the panel/DOM from being the
next bottleneck (4). Low risk — no behavior change for small/medium graphs,
which is what's been tested so far.

### Phase 2 — moderate effort, biggest win for click-to-click responsiveness

- **Stop destroying Cytoscape on every click.** Replace `cy.destroy()` +
  full rebuild with an incremental diff: compute the previous vs. next
  visible element id sets, `cy.batch()` a remove of what disappeared and an
  add of what's new, and reposition anything that moved — instead of
  tearing down and reconstructing everything (issue 1). This is the change
  most directly responsible for "expand a box → feels instant" vs. "expand a
  box → visible stutter," and it also means the user's pan/zoom position
  survives interactions that don't need `fitToVisible()` to re-center.
- **Stop resetting the whole layout cache on every rebuild.**
  `buildVisible()` currently does `groupLayoutCache = {}` unconditionally.
  Subtrees whose expansion state, status filter, and direction haven't
  changed since the last build don't need to be laid out again — cache
  keyed on `(groupId, direction, activeStatusFilter, activeStrictnessLevel)`
  instead of being wiped every time.

Expected effect: turns "expand/collapse/click" from a full-graph operation
into a local one — the actual fix for "тормозит" during normal use, not just
during "expand all."

### Phase 3 — for graphs that are routinely tens of thousands of objects

- **Move layout off the main thread.** Once (1) and (2) from Phase 1/2 are
  in place, the remaining cost at real scale is layout math on a big
  expansion. Running `layeredLayout()`/`layoutOf()` in a Web Worker
  (`postMessage` the visible subgraph in, positions back out) keeps the tab
  responsive — scrollable/clickable — while a large expansion computes,
  instead of a hard freeze.
- **Lazy-load per-edge evidence fields.** `evidence_file` / `evidence_path`
  / `evidence_key` / `evidence_value` / `native_relation` / `confidence` are
  only ever read when a user opens the panel for that specific edge. At tens
  of thousands of edges this is a meaningful fraction of payload size for
  data that's rarely looked at. Since this tool's reports already rely on
  plain `<script src="...">` tags (which work fine over `file://`, unlike
  `fetch()`), this can be split into a second `evidence-data.js` file loaded
  eagerly but only *walked* when a panel actually needs it — or, if the
  report format changes to multiple files becomes acceptable, split per
  top-level group so nothing has to be parsed until that branch is touched.
- **Semantic zoom for very dense collapsed boxes.** A box chip already only
  shows a job count when collapsed — for a box with, say, 5,000 direct jobs,
  even "expand this one box" means laying out 5,000 job nodes at once.
  Worth considering a middle state: show the count and let the user drill
  into *sub-ranges* (e.g. paginate/virtualize very flat, very wide boxes)
  rather than always laying out every direct child on first expand.

This phase is genuinely more involved (worker message-passing, a second data
file, a new intermediate UI state) and I'd only reach for it once real
report sizes are confirmed to be in the tens-of-thousands range and Phases
1–2 aren't enough on their own.

## How I'd validate this before/after

- Generate a synthetic fixture (a small script producing N jobs across a
  realistic box-nesting shape) at ~2k / ~10k / ~50k jobs, run it through the
  existing CLI, and open the report.
- Wrap `buildCy()` and `layoutOf()` in `console.time`/`console.timeEnd`
  behind a `?perf=1` query flag (cheap, removable, no effect on normal
  usage) so before/after numbers for "time to first render" and "time per
  box-expand click" are concrete rather than eyeballed.
- Rough targets to aim for once Phase 1–2 land: initial (fully collapsed)
  render under ~2s at 20k jobs; a single box-expand click under ~200–300ms
  for a box with a few hundred direct children; "Expand all" explicitly
  opt-in and allowed to take longer, since it's an unusual, deliberate
  action rather than the common path.

## What I'm *not* proposing

- No change to the Python-side data model or the skeleton mapping logic —
  this is purely about how the already-reduced job/box/dependency payload
  gets rendered.
- No change to what's collapsed by default — that's already the right
  starting point for scale, the plan above is about what happens once the
  user expands into it.
