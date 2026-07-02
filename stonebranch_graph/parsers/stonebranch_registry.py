from __future__ import annotations

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import Graph, make_node_id
from stonebranch_graph.domain import KIND_COMMAND
from stonebranch_graph.parsers.stonebranch_discovery import make_stonebranch_node

Registry = dict[str, dict]


def build_registry(graph: Graph) -> Registry:
    by_kind: dict[tuple[str, str, str], str] = {}
    by_name: dict[tuple[str, str], set[str]] = {}
    for node in graph.nodes.values():
        name_key = node.name.lower()
        by_kind[(node.env, node.kind, name_key)] = node.id
        by_name.setdefault((node.env, name_key), set()).add(node.id)
    return {"by_kind": by_kind, "by_name": by_name}


def resolve_or_create_ref_node(
    *,
    graph: Graph,
    registry: Registry,
    config: AnalyzerConfig,
    env: str,
    target_kind: str,
    target_name: str,
    native_relation: str,
    source_file: str,
    append_warning,
) -> str:
    existing = registry["by_kind"].get((env, target_kind, target_name.lower()))
    if existing:
        return existing

    same_name_matches = set(registry["by_name"].get((env, target_name.lower()), set()))
    if len(same_name_matches) == 1:
        matched_node = graph.nodes[next(iter(same_name_matches))]
        append_warning(
            graph,
            f"Stonebranch reference {target_name!r} in {source_file!r} via {native_relation!r} "
            f"expected {target_kind!r}, but only found {matched_node.kind!r}; "
            f"created synthetic {target_kind!r} node instead of linking to the wrong kind.",
        )
    elif len(same_name_matches) > 1:
        append_warning(
            graph,
            f"Ambiguous Stonebranch reference {target_name!r} in {source_file!r} via {native_relation!r}: "
            f"matched {len(same_name_matches)} objects by name, created synthetic {target_kind!r} node.",
        )

    metadata = {"synthetic": True, "reason": "referenced_without_object_file"}
    if target_kind == KIND_COMMAND:
        metadata["semantic_command_hash"] = target_name
    node = make_stonebranch_node(
        env=env,
        kind=target_kind,
        name=target_name,
        native_kind=f"referenced:{native_relation}",
        source_file=source_file,
        metadata=metadata,
        attributes=None,
    )
    graph.add_node(node)
    registry["by_kind"][(env, target_kind, target_name.lower())] = node.id
    registry["by_name"].setdefault((env, target_name.lower()), set()).add(node.id)
    return node.id
