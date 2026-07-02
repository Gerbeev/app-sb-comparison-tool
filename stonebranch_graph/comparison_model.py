from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .core import Edge, Node

@dataclass
class Comparison:
    summary: dict[str, Any] = field(default_factory=dict)
    nodes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    edges: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    attributes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    diagnostics: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "nodes": self.nodes,
            "edges": self.edges,
            "attributes": self.attributes,
            "diagnostics": self.diagnostics,
            "risks": self.risks,
        }


@dataclass
class SideComparisonIndex:
    node_index: dict[str, Node]
    node_collisions: list[dict[str, Any]]
    node_keys: set[str]
    edge_index: dict[str, Edge]
    edge_collisions: list[dict[str, Any]]
    edge_keys: set[str]
