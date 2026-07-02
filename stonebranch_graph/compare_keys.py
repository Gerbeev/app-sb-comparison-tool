from __future__ import annotations

import re
from typing import Any

from .config import MappingConfig
from .core import Edge, Graph, Node, comparison_name, normalize_name
from .domain import (
    KIND_AGENT,
    KIND_AGENT_CLUSTER,
    KIND_BOX,
    KIND_OBJECT,
    KIND_WORKFLOW,
    KNOWN_SOURCE_SYSTEMS,
    REL_CONTAINS,
    REL_DEPENDS_ON_SUCCESS,
    REL_RUNS_ON,
    REL_RUNS_ON_CLUSTER,
    REL_SUCCESSOR_OF,
)

def comparison_node_key(node: Node, mapping: MappingConfig, left: bool, mapping_usage: set[str] | None = None) -> str:
    if left:
        mapped = lookup_mapping(node, mapping)
        if mapped:
            if mapping_usage is not None:
                mapping_usage.add(mapped[0])
            return normalize_key(mapped[1], mapping)
    return normalize_key(node.canonical_key, mapping)


def lookup_mapping(node: Node, mapping: MappingConfig) -> tuple[str, str] | None:
    candidates = [
        node.id,
        node.canonical_key,
        normalize_key(node.canonical_key, mapping),
        node.name,
        normalize_name(node.name),
    ]
    for candidate in candidates:
        if candidate in mapping.node_mappings:
            return candidate, mapping.node_mappings[candidate]
    return None


def normalize_key(key: str, mapping: MappingConfig) -> str:
    key = str(key)
    parts = key.split(":", 3)
    # Accept source_system:env:kind:name IDs and env:kind:name canonical keys.
    if len(parts) == 4 and parts[0] in KNOWN_SOURCE_SYSTEMS:
        _, env, kind, name = parts
    elif len(parts) == 3:
        env, kind, name = parts
    else:
        env, kind, name = "default", KIND_OBJECT, key
    kind = comparison_kind(mapping.kind_aliases.get(kind, kind))
    name = normalize_name(comparison_name(name))
    for rule in mapping.name_rewrites:
        pattern = rule.get("from", "")
        repl = rule.get("to", "")
        if pattern:
            name = re.sub(pattern, repl, name)
    return f"{env}:{kind}:{name}"


def comparison_kind(kind: str) -> str:
    """Return kind used for cross-system comparison keys.

    AutoSys boxes and Stonebranch workflows represent the same containment
    concept in migration analysis, so compare them as box-like containers while
    preserving the original node kind in graph.json and reports.

    AutoSys machines are commonly migrated to Stonebranch agent clusters, so
    agents and agent clusters compare as the same runtime-target concept.
    """
    if kind == KIND_WORKFLOW:
        return KIND_BOX
    if kind == KIND_AGENT_CLUSTER:
        return KIND_AGENT
    return kind


# Relations unified for cross-system comparison. runs_on_cluster is the
# Stonebranch counterpart of the AutoSys machine relation (runs_on).
COMPARISON_RELATION_ALIASES = {
    REL_RUNS_ON_CLUSTER: REL_RUNS_ON,
}


def comparison_relation(relation: str) -> str:
    return COMPARISON_RELATION_ALIASES.get(relation, relation)


def comparison_edge_key(edge: Edge, graph: Graph, mapping: MappingConfig, left: bool, mapping_usage: set[str] | None = None) -> str:
    components = comparison_edge_components(edge, graph)
    if components is None:
        return f"broken:{edge.id}"
    source, relation, target = components
    relation = comparison_relation(relation)
    return f"{comparison_node_key(source, mapping, left, mapping_usage)}->{relation}->{comparison_node_key(target, mapping, left, mapping_usage)}"


def comparison_edge_components(edge: Edge, graph: Graph) -> tuple[Node, str, Node] | None:
    source = graph.nodes.get(edge.source)
    target = graph.nodes.get(edge.target)
    if not source or not target:
        return None

    relation = edge.relation
    if relation == REL_SUCCESSOR_OF:
        # Legacy Stonebranch exports represented successorTask as current -> successor.
        # For comparison, normalize to dependent -> prerequisite like AutoSys condition edges.
        return target, REL_DEPENDS_ON_SUCCESS, source

    if relation == REL_CONTAINS and source.kind not in {KIND_BOX, KIND_WORKFLOW} and target.kind in {KIND_BOX, KIND_WORKFLOW}:
        # Legacy task.workflowName edges could be written as task -> contains -> workflow.
        # A containment relation should always point container -> child.
        return target, relation, source

    return source, relation, target


def edge_key_parts(comparison_key: str | None) -> tuple[str, str, str] | None:
    if not comparison_key or "->" not in comparison_key:
        return None
    parts = comparison_key.split("->", 2)
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]
