"""Skeleton node model from docs/mapping-theory.md sections 2, 5, and 7."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from stonebranch_graph.core import comparison_name, normalize_name, stable_hash
from stonebranch_graph.expr import (
    Expr,
    atoms,
    logic_view,
    parse,
    render,
    strict_view,
    success_and_only,
)
from stonebranch_graph.expr import topology_view as expr_topology_view

KIND_UNIT = "unit"
KIND_CONTAINER = "container"
EXT_PREFIX = "ext:"

STRICTNESS_LEVELS = frozenset({"topology", "logic", "strict"})


@dataclass(frozen=True)
class SkeletonNode:
    """A canonical unit or container node in a scheduling skeleton."""

    id: str
    kind: str
    parent: str | None
    trigger: Expr | None
    completion: Expr | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Skeleton:
    """A mutable collection of skeleton nodes plus diagnostics."""

    nodes: dict[str, SkeletonNode] = field(default_factory=dict)
    externals: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    erasures: list[dict[str, Any]] = field(default_factory=list)
    collisions: list[dict[str, Any]] = field(default_factory=list)

    def add_node(self, node: SkeletonNode, *, merge_allowed: bool = False) -> SkeletonNode:
        """Add a node, keeping the first definition when ids duplicate.

        When a second, distinct native object resolves to an id already present in
        this skeleton, the collision is recorded as structured data in
        :attr:`collisions` in addition to the free-text warning, so callers such as
        ``skeleton_compare`` can surface it as a risk instead of silently losing the
        second definition. ``merge_allowed`` marks the collision as an intentional
        alias merge (N1) rather than an alias/id error.
        """

        if node.id in self.nodes:
            existing = self.nodes[node.id]
            self.warnings.append(f"Duplicate skeleton node id ignored: {node.id}")
            self.collisions.append(
                {
                    "id": node.id,
                    "kept_native": existing.meta.get("native"),
                    "dropped_native": node.meta.get("native"),
                    "kept_src": existing.meta.get("source_file"),
                    "dropped_src": node.meta.get("source_file"),
                    "merge_allowed": merge_allowed,
                }
            )
            return self.nodes[node.id]
        self.nodes[node.id] = node
        return node

    def validate(self) -> None:
        """Register missing trigger references as externals and report parent cycles."""

        for node in self.nodes.values():
            for expr in (node.trigger, node.completion):
                if expr is None:
                    continue
                for atom in atoms(expr):
                    if atom.node_ref not in self.nodes:
                        self.externals.add(atom.node_ref)
        self._detect_parent_cycles()

    def to_jsonl(self) -> str:
        """Serialize the skeleton to sorted JSON Lines."""

        return to_jsonl(self)

    @classmethod
    def from_jsonl(cls, text: str) -> Skeleton:
        """Deserialize sorted JSON Lines into a skeleton."""

        return from_jsonl(text)

    def to_canonical_jsonl(self, level: str) -> str:
        """Serialize the skeleton comparison view for a strictness level."""

        return to_canonical_jsonl(self, level)

    def _detect_parent_cycles(self) -> None:
        warned: set[str] = set()
        visiting: dict[str, int] = {}
        visited: set[str] = set()
        stack: list[str] = []

        for node_id in self.nodes:
            if node_id in visited:
                continue
            current: str | None = node_id
            while current is not None and current in self.nodes:
                if current in visited:
                    break
                if current in visiting:
                    cycle_nodes = stack[visiting[current] :]
                    cycle = " -> ".join(cycle_nodes + [current])
                    if cycle not in warned:
                        self.warnings.append(f"Containment cycle detected: {cycle}")
                        warned.add(cycle)
                    break
                visiting[current] = len(stack)
                stack.append(current)
                current = self.nodes[current].parent

            while stack:
                visited.add(stack.pop())
            visiting.clear()


def logical_leaf(name: str) -> str:
    """Return the normalized comparison leaf id for a native object name."""

    return normalize_name(comparison_name(name))


def child_id(parent_id: str | None, leaf: str) -> str:
    """Return a containment-path id for a leaf under an optional parent."""

    if parent_id is None:
        return leaf
    return f"{parent_id}/{leaf}"


def to_jsonl(skeleton: Skeleton) -> str:
    """Serialize a skeleton as deterministic JSON Lines sorted by node id."""

    lines = [_json_line(_node_record(node, level=None)) for node in _sorted_nodes(skeleton)]
    return "\n".join(lines) + ("\n" if lines else "")


def from_jsonl(text: str) -> Skeleton:
    """Deserialize deterministic JSON Lines into a skeleton."""

    skeleton = Skeleton()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        trigger = parse(payload["trigger"]) if payload.get("trigger") is not None else None
        completion = parse(payload["completion"]) if payload.get("completion") is not None else None
        skeleton.add_node(
            SkeletonNode(
                id=payload["id"],
                kind=payload["kind"],
                parent=payload["parent"],
                trigger=trigger,
                completion=completion,
                meta=dict(payload.get("meta", {})),
            )
        )
        if not isinstance(payload.get("id"), str):
            skeleton.warnings.append(f"Line {line_number} has a non-string id")
    return skeleton


def to_canonical_jsonl(skeleton: Skeleton, level: str) -> str:
    """Serialize the comparison view as deterministic JSON Lines."""

    _validate_level(level)
    lines = [_json_line(_node_record(node, level=level)) for node in _sorted_nodes(skeleton)]
    return "\n".join(lines) + ("\n" if lines else "")


def node_hash(node: SkeletonNode, level: str) -> str:
    """Return the stable hash of a node's canonical line content at a level."""

    _validate_level(level)
    return stable_hash(_node_record(node, level=level))


def index_rows(skeleton: Skeleton) -> list[dict[str, str | None]]:
    """Return sorted per-node hash index rows for all comparison levels."""

    return [
        {
            "id": node.id,
            "kind": node.kind,
            "parent": node.parent,
            "topology_hash": node_hash(node, "topology"),
            "logic_hash": node_hash(node, "logic"),
            "strict_hash": node_hash(node, "strict"),
        }
        for node in _sorted_nodes(skeleton)
    ]


def depends_on_view(skeleton: Skeleton) -> dict[str, list[str]]:
    """Return legacy depends_on lists for pure SUCCESS conjunction triggers."""

    result: dict[str, list[str]] = {}
    for node in _sorted_nodes(skeleton):
        if node.trigger is None:
            continue
        refs = success_and_only(node.trigger)
        if refs is not None:
            result[node.id] = refs
    return result


def _sorted_nodes(skeleton: Skeleton) -> list[SkeletonNode]:
    return [skeleton.nodes[node_id] for node_id in sorted(skeleton.nodes)]


def _node_record(node: SkeletonNode, *, level: str | None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": node.id,
        "kind": node.kind,
        "parent": node.parent,
        "trigger": _render_optional(node.trigger, level),
    }
    completion = _render_optional(node.completion, level) if level in {None, "strict"} else None
    if completion is not None:
        record["completion"] = completion
    if level is None and node.meta:
        record["meta"] = _stable_value(node.meta)
    return record


def _render_optional(expr: Expr | None, level: str | None) -> str | None:
    if expr is None:
        return None
    if level is None:
        return render(expr)
    if level == "topology":
        return expr_topology_view(expr)
    if level == "logic":
        return logic_view(expr)
    if level == "strict":
        return strict_view(expr)
    raise ValueError(f"Unknown strictness level: {level}")


def _json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _stable_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list):
        return [_stable_value(item) for item in value]
    if isinstance(value, tuple):
        return [_stable_value(item) for item in value]
    if isinstance(value, set):
        return sorted(_stable_value(item) for item in value)
    return value


def _validate_level(level: str) -> None:
    if level not in STRICTNESS_LEVELS:
        raise ValueError(f"Unknown strictness level: {level}")
