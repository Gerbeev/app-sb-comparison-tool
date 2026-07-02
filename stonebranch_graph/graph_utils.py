from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .core import Edge, Graph, Node


@dataclass(frozen=True)
class GraphTraversalCache:
    """Precomputed graph traversal data shared by exporters and pack writers."""

    sorted_nodes: list[Node]
    sorted_edges: list[Edge]
    inbound: dict[str, int]
    outbound: dict[str, int]
    kind_counts: Counter[str]
    relation_counts: Counter[str]

    @classmethod
    def build(cls, graph: Graph) -> "GraphTraversalCache":
        sorted_nodes = sorted(graph.nodes.values(), key=lambda node: node.id)
        sorted_edges = sorted(graph.edges.values(), key=lambda edge: edge.id)
        inbound = {node.id: 0 for node in sorted_nodes}
        outbound = {node.id: 0 for node in sorted_nodes}
        kind_counts: Counter[str] = Counter()
        relation_counts: Counter[str] = Counter()

        for node in sorted_nodes:
            kind_counts[node.kind] += 1

        for edge in sorted_edges:
            relation_counts[edge.relation] += 1
            if edge.source in outbound:
                outbound[edge.source] += 1
            if edge.target in inbound:
                inbound[edge.target] += 1

        return cls(
            sorted_nodes=sorted_nodes,
            sorted_edges=sorted_edges,
            inbound=inbound,
            outbound=outbound,
            kind_counts=kind_counts,
            relation_counts=relation_counts,
        )


def degree_maps(
    graph: Graph,
    *,
    include_external_nodes: bool = False,
) -> tuple[dict[str, int], dict[str, int]]:
    """Return inbound and outbound edge counts keyed by node id.

    By default only declared graph nodes are counted. Set ``include_external_nodes``
    for diagnostic/reporting code that wants to surface dangling edge endpoints too.
    """

    if not include_external_nodes:
        cache = GraphTraversalCache.build(graph)
        return dict(cache.inbound), dict(cache.outbound)

    inbound = {node_id: 0 for node_id in graph.nodes}
    outbound = {node_id: 0 for node_id in graph.nodes}

    for edge in graph.edges.values():
        outbound[edge.source] = outbound.get(edge.source, 0) + 1
        inbound[edge.target] = inbound.get(edge.target, 0) + 1

    return inbound, outbound
