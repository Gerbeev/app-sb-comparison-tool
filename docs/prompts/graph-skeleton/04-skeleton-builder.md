# Agent prompt — Item 4: Data-flow contraction + skeleton builder

You are implementing Item 4 of `GRAPH_SKELETON_IMPLEMENTATION_PLAN.md`. Items 1–3 are merged. Goal: `stonebranch_graph/skeleton.py` producing the analytical skeleton per proposal §3.1 (see `GRAPH_SKELETON_AND_SEMANTIC_CORE_PROPOSAL.md`, read ONLY section 3).

## Token budget rules
Read ONLY: proposal §3, `stonebranch_graph/domain.py`, `stonebranch_graph/core.py`, `stonebranch_graph/graph_utils.py`. Nothing else. Pure stdlib, no new dependencies. Minimal diff (one new file + tests).

## Task
Create `stonebranch_graph/skeleton.py`:

```python
@dataclass
class SkeletonView:
    node_ids: list[str]                 # job-like nodes, sorted
    edges: list[Edge]                   # dependency edges + derived data edges
    containment_parent: dict[str, str]  # child -> parent (forest)
    scc_id: dict[str, int]              # node -> component id
    scc_members: dict[int, list[str]]   # only non-trivial SCCs
    layer: dict[str, int]               # longest-path layer on condensation
    warnings: list[str]

def build_skeleton(graph: Graph, *, transitive_reduction: bool = False,
                   pair_cap: int = 25) -> SkeletonView: ...
```

Steps:
1. Restrict: nodes with `kind ∈ JOB_LIKE_KINDS`; edges with `relation ∈ DEPENDENCY_RELATIONS` between them. Containment: `contains` edges between job-like nodes → parent map; if a node gets two parents, keep first by sorted edge id and warn.
2. Contraction: per `KIND_FILE` node, `P = sources of produces_file`, `W = sources of watches_file`. If `len(P)*len(W) > pair_cap`: warn, skip expansion. Else for each (p,w), p≠w, add `Edge(relation=REL_DATA_DEPENDS_ON, source=w, target=p, derived=True, inference="contraction", confidence=κ_watch*κ_produce, source_system=graph.source_system, evidence_*=file node reference, id=make_edge_id(...))`.
3. Tarjan SCC (iterative, no recursion — graphs can be large) on the restricted+derived edge set. Non-trivial SCCs → warning listing members (max 10 names, then "…").
4. On the condensation DAG: longest-path layering (`layer = 0` for sources). If `transitive_reduction=True`, drop edges (u,v) when a longer u⇝v path exists — DAG-only, implement via reachability with memoized descendant bitsets or interval trick; O(V·E) acceptable.
5. Deterministic: sort everything by id.

## Acceptance
`tests/test_skeleton.py`: (a) producer/file/watcher triple ⇒ one derived edge with confidence product; (b) pair_cap=1 with 2 producers ⇒ no expansion + warning; (c) 3-cycle ⇒ one SCC id shared, warning; (d) diamond a→b,c→d ⇒ layers 0/1/1/2; (e) transitive reduction drops a→d in a→b→d + a→d. Pytest green. Report: public API signature + test summary only.
