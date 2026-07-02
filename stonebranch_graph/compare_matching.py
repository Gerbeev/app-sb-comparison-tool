from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .core import Edge, Graph, Node
from .domain import DEPENDENCY_RELATIONS, REL_DEPENDS_ON, STONEBRANCH_ONLY_KINDS, STONEBRANCH_ONLY_RELATIONS
from .comparison_model import SideComparisonIndex
from .compare_keys import edge_key_parts
from .compare_payloads import edge_payload


@dataclass(frozen=True)
class DiffSets:
    matched_keys: set[str] = field(default_factory=set)
    missing_in_sb: list[str] = field(default_factory=list)
    missing_in_jil: list[str] = field(default_factory=list)
    sb_only_node_keys: list[str] = field(default_factory=list)
    matched_edge_keys: set[str] = field(default_factory=set)
    missing_edges_in_sb: list[str] = field(default_factory=list)
    missing_edges_in_jil: list[str] = field(default_factory=list)
    sb_only_edge_keys: list[str] = field(default_factory=list)
    relaxed_pairs: list[tuple[str, str]] = field(default_factory=list)


def compute_diff_sets(sb: SideComparisonIndex, jl: SideComparisonIndex) -> DiffSets:
    matched_keys = sb.node_keys & jl.node_keys
    missing_in_sb = sorted(jl.node_keys - sb.node_keys)
    # Stonebranch-only object kinds (triggers, credentials, ...) cannot exist in
    # JIL, so they are informational rather than migration mismatches.
    missing_in_jil, sb_only_node_keys = partition_stonebranch_only_nodes(
        sorted(sb.node_keys - jl.node_keys), sb.node_index
    )

    matched_edge_keys = sb.edge_keys & jl.edge_keys
    missing_edges_in_sb = sorted(jl.edge_keys - sb.edge_keys)
    missing_edges_in_jil = sorted(sb.edge_keys - jl.edge_keys)
    # A generic depends_on on one side matches a specific depends_on_* between
    # the same objects on the other side: it is the same dependency with an
    # unspecified condition, not a lost edge.
    relaxed_pairs, missing_edges_in_jil, missing_edges_in_sb = match_relaxed_dependency_edges(
        missing_edges_in_jil, missing_edges_in_sb
    )
    missing_edges_in_jil, sb_only_edge_keys = partition_stonebranch_only_edges(missing_edges_in_jil)

    return DiffSets(
        matched_keys=matched_keys,
        missing_in_sb=missing_in_sb,
        missing_in_jil=missing_in_jil,
        sb_only_node_keys=sb_only_node_keys,
        matched_edge_keys=matched_edge_keys,
        missing_edges_in_sb=missing_edges_in_sb,
        missing_edges_in_jil=missing_edges_in_jil,
        sb_only_edge_keys=sb_only_edge_keys,
        relaxed_pairs=relaxed_pairs,
    )


def diff_summary_extras(diff: DiffSets, stonebranch_nodes: int, stonebranch_edges: int) -> dict[str, int]:
    return {
        "relaxed_dependency_matches": len(diff.relaxed_pairs),
        "stonebranch_only_nodes": len(diff.sb_only_node_keys),
        "stonebranch_only_edges": len(diff.sb_only_edge_keys),
        "stonebranch_comparable_nodes": stonebranch_nodes - len(diff.sb_only_node_keys),
        "stonebranch_comparable_edges": stonebranch_edges - len(diff.sb_only_edge_keys),
    }


def partition_stonebranch_only_nodes(
    missing_in_jil: list[str],
    sb_node_index: dict[str, Node],
) -> tuple[list[str], list[str]]:
    comparable: list[str] = []
    stonebranch_only: list[str] = []
    for key in missing_in_jil:
        node = sb_node_index.get(key)
        if node is not None and node.kind in STONEBRANCH_ONLY_KINDS:
            stonebranch_only.append(key)
        else:
            comparable.append(key)
    return comparable, stonebranch_only


def partition_stonebranch_only_edges(missing_in_jil: list[str]) -> tuple[list[str], list[str]]:
    comparable: list[str] = []
    stonebranch_only: list[str] = []
    for key in missing_in_jil:
        parts = edge_key_parts(key)
        if parts is not None and parts[1] in STONEBRANCH_ONLY_RELATIONS:
            stonebranch_only.append(key)
        else:
            comparable.append(key)
    return comparable, stonebranch_only


def match_relaxed_dependency_edges(
    missing_edges_in_jil: list[str],
    missing_edges_in_sb: list[str],
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """Pair generic depends_on edges with specific depends_on_* counterparts.

    Returns (matched (sb_key, jil_key) pairs, remaining sb-extra keys,
    remaining jil-extra keys). Only pairs where one side is the generic
    depends_on are matched; success-vs-failure style conflicts remain
    mismatches.
    """
    jil_by_endpoints: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for key in missing_edges_in_sb:
        parts = edge_key_parts(key)
        if parts is None or parts[1] not in DEPENDENCY_RELATIONS:
            continue
        jil_by_endpoints.setdefault((parts[0], parts[2]), []).append((parts[1], key))

    pairs: list[tuple[str, str]] = []
    matched_sb: set[str] = set()
    matched_jil: set[str] = set()
    for sb_key in missing_edges_in_jil:
        parts = edge_key_parts(sb_key)
        if parts is None or parts[1] not in DEPENDENCY_RELATIONS:
            continue
        sb_relation = parts[1]
        candidates = jil_by_endpoints.get((parts[0], parts[2]), [])
        for jil_relation, jil_key in sorted(candidates, key=lambda item: item[1]):
            if jil_key in matched_jil:
                continue
            if REL_DEPENDS_ON not in (sb_relation, jil_relation):
                continue
            pairs.append((sb_key, jil_key))
            matched_sb.add(sb_key)
            matched_jil.add(jil_key)
            break

    remaining_sb_extra = [key for key in missing_edges_in_jil if key not in matched_sb]
    remaining_jil_extra = [key for key in missing_edges_in_sb if key not in matched_jil]
    return pairs, remaining_sb_extra, remaining_jil_extra


def relaxed_edge_pair_payload(
    sb_edge: Edge,
    jil_edge: Edge,
    stonebranch: Graph,
    jil: Graph,
    sb_key: str,
    jil_key: str,
) -> dict[str, Any]:
    return {
        "key": jil_key,
        "match_type": "dependency_family_relaxed",
        "stonebranch_key": sb_key,
        "jil_key": jil_key,
        "stonebranch": edge_payload(sb_edge, stonebranch, comparison_key=sb_key),
        "jil": edge_payload(jil_edge, jil, comparison_key=jil_key),
    }
