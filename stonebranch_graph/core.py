from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Any


@dataclass(frozen=True)
class Node:
    id: str
    canonical_key: str
    source_system: str
    env: str
    kind: str
    name: str
    native_kind: str = ""
    source_file: str = ""
    attributes_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    target: str
    relation: str
    source_system: str
    native_relation: str = ""
    evidence_file: str = ""
    evidence_path: str = ""
    evidence_key: str = ""
    evidence_value: str = ""
    confidence: float = 1.0


@dataclass
class Graph:
    source_system: str
    env: str = "default"
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def add_node(self, node: Node) -> Node:
        existing = self.nodes.get(node.id)
        if existing:
            merged_metadata = dict(existing.metadata)
            for key, value in node.metadata.items():
                if key == "synthetic" and not existing.metadata.get("synthetic", False):
                    continue
                merged_metadata.setdefault(key, value)
            merged = Node(
                id=existing.id,
                canonical_key=existing.canonical_key,
                source_system=existing.source_system,
                env=existing.env,
                kind=existing.kind,
                name=existing.name,
                native_kind=existing.native_kind or node.native_kind,
                source_file=existing.source_file or node.source_file,
                attributes_hash=existing.attributes_hash or node.attributes_hash,
                metadata=merged_metadata,
            )
            self.nodes[node.id] = merged
            return merged
        self.nodes[node.id] = node
        return node

    def add_edge(self, edge: Edge) -> None:
        if edge.source == edge.target:
            return
        self.edges.setdefault(edge.id, edge)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_system": self.source_system,
            "env": self.env,
            "nodes": [asdict(n) for n in sorted(self.nodes.values(), key=lambda x: x.id)],
            "edges": [asdict(e) for e in sorted(self.edges.values(), key=lambda x: x.id)],
            "warnings": self.warnings,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Graph":
        graph = Graph(source_system=data.get("source_system", "unknown"), env=data.get("env", "default"))
        for node_data in data.get("nodes", []):
            node = Node(**node_data)
            graph.nodes[node.id] = node
        for edge_data in data.get("edges", []):
            edge = Edge(**edge_data)
            graph.edges[edge.id] = edge
        graph.warnings = list(data.get("warnings", []))
        return graph


def normalize_name(value: str) -> str:
    text = value.strip().strip('"').strip("'")
    text = re.sub(r"\s+", "_", text)
    return text.lower()


def stable_hash(payload: Any, length: int = 16) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def make_node_id(source_system: str, env: str, kind: str, name: str) -> str:
    raw = f"{source_system}:{env}:{kind}:{name}"
    return sanitize_id(raw)


def make_canonical_key(env: str, kind: str, name: str) -> str:
    return f"{env}:{kind}:{normalize_name(name)}"


def make_edge_id(source_id: str, target_id: str, relation: str, native_relation: str = "") -> str:
    return stable_hash(
        {
            "source": source_id,
            "target": target_id,
            "relation": relation,
            "native_relation": native_relation,
        },
        length=24,
    )


def sanitize_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", value).strip("_")


def redacted_preview(value: str, max_len: int = 180) -> str:
    compact = " ".join(str(value).split())
    if len(compact) > max_len:
        return compact[: max_len - 1] + "…"
    return compact
