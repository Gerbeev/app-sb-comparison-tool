# Agent prompt — Item 5: Semantic-core metrics

You are implementing Item 5 of `GRAPH_SKELETON_IMPLEMENTATION_PLAN.md`. Item 4 (`skeleton.py`, `SkeletonView`) is merged. Goal: node-importance scoring on the skeleton (proposal §3.4).

## Token budget rules
Read ONLY: `stonebranch_graph/skeleton.py`, proposal §3.4 in `GRAPH_SKELETON_AND_SEMANTIC_CORE_PROPOSAL.md`, and the imports/`GraphMetrics` head of `stonebranch_graph/metrics.py` (first ~60 lines; do not read the whole file). Pure stdlib. Minimal diff.

## Task
Create `stonebranch_graph/semantic_core.py` (keep it separate from metrics.py to avoid touching that file):

```python
@dataclass(frozen=True)
class NodeScores:
    in_degree: int; out_degree: int
    betweenness: float      # normalized 0..1
    k_core: int
    reach: int              # descendant count on condensation, expanded back
    articulation: bool
    criticality: float      # 0..1

def score_skeleton(view: SkeletonView, *, weights=(0.4, 0.3, 0.2, 0.1)) -> dict[str, NodeScores]
def top_core(scores, n=50) -> list[str]
```

- Betweenness: Brandes on the condensation DAG (iterative BFS since edges are unweighted), map back to members; normalize by max.
- k-core: standard peeling on the undirected version.
- Reach: descendants per condensation node (reverse topological accumulation of member counts).
- Articulation points: iterative Hopcroft–Tarjan on undirected skeleton.
- `criticality = w0*betweenness + w1*reach/max_reach + w2*(deg/max_deg) + w3*(k_core/max_k)`; guard div-by-zero.

## Acceptance
`tests/test_semantic_core.py` on tiny fixtures asserting RANKINGS not absolute values: chain a→b→c ⇒ b highest betweenness, articulation=True for b; star center ⇒ max degree + criticality; 4-clique ⇒ k_core=3. Pytest green. Report: test summary only.
