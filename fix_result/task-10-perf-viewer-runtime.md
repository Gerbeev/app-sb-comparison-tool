# Task 10 — Browser viewer is slow at thousands of nodes after the user opens it (HIGH, UX)

> Performance track. **Must not reduce graph-report fidelity** — no dropping nodes/edges, no
> lossy simplification of what is shown. Only make the same render cheaper.

## Where the cost is
The generated HTML viewer (`html_graph.py`, the inlined `<script>` starting near the
`buildCy`/`relayout`/`visibleNodes`/`visibleEdges` functions) recomputes and re-renders more than
it needs to. Concrete hot spots, all in the embedded JS:

1. **`visibleNodes()` is O(groups × jobs) when a status filter is active.** For each candidate node
   it calls `nodeMatchesCurrentStatus`, which for group nodes calls
   `groupHasMatchingChild(groupId)` → `(DATA.jobs||[]).some(...)`, a full scan of all jobs. With G
   groups and J jobs that is O(G·J) per rebuild.
2. **`visibleNodes()` is recomputed several times per rebuild.** `visibleEdges()` calls
   `visibleNodes()` again to build its node set, and `toCytoscapeElements()` calls both
   `visibleNodes()` and `visibleEdges()` — so the O(G·J) scan runs 3× per `buildCy`/`relayout`.
3. **Cytoscape style is expensive per element at scale:** bezier curves, per-node `text-outline`,
   always-on labels, and no viewport optimizations. At a few thousand nodes this makes pan/zoom
   janky even though the preset layout itself is O(V+E).

## Fix (fidelity-preserving)
1. **Precompute a group→children index once** from `DATA` (e.g. `childrenByGroup`) and make
   `groupHasMatchingChild` an O(children) check instead of scanning all jobs.
2. **Compute visible sets once per rebuild.** Have `toCytoscapeElements()` compute
   `visibleNodes()` a single time, derive the node-id `Set`, and pass it into edge filtering rather
   than re-deriving. Memoize on a `(activeStatusFilter, visibleCategories, expanded, direction)`
   key so repeated `applyClasses`/UI toggles that don't change inputs reuse the result.
3. **Add node-count-gated Cytoscape performance options** in `buildCy` when
   `elements.length` exceeds a threshold (e.g. > 1500): `hideEdgesOnViewport: true`,
   `textureOnViewport: true`, `motionBlur: false`, and wrap `cy.add(...)` in `cy.batch(...)`.
   Below the threshold keep today's richer rendering. This preserves full detail on small graphs
   and stays interactive on large ones — no data is hidden, only deferred during motion.
4. **Cheaper edge style at scale:** switch `curve-style` to `haystack` for non-selected edges above
   the threshold (straight lines, dramatically faster) and drop `text-outline` on nodes above it;
   keep labels. Selected/highlighted elements keep the rich style.
5. Keep the preset ranked layout (`rankedPositions`) — it is already linear; do not swap in dagre.

## Acceptance
- Generate a viewer for a 5k-node skeleton; first paint and pan/zoom are smooth (no multi-second
  freeze) on a mid-range laptop.
- Toggling a status filter no longer triggers a visible multi-second stall.
- Small graphs (< 1500 elements) render pixel-identical to today (same colors, labels, curves).
- No node or edge present in `DATA` is ever omitted from the rendered graph at rest.
