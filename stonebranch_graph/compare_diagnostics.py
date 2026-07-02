from __future__ import annotations

from typing import Any

from .config import MappingConfig
from .compare_payloads import edge_payload, node_payload
from .core import Edge, Graph, Node, enterprise_name_parts

def collision_payload(buckets: dict[str, list[Node]]) -> list[dict[str, Any]]:
    return [node_collision_payload(k, v) for k, v in sorted(buckets.items()) if len(v) > 1]


def node_collision_payload(key: str, nodes: list[Node]) -> dict[str, Any]:
    parts = [node_enterprise_parts(node) for node in nodes]
    populated_parts = [item for item in parts if item]
    reason = "normalized_key_collision"
    if populated_parts and len({item.get("real_name", "") for item in populated_parts}) == 1:
        reason = "enterprise_name_collision"
    return {
        "key": key,
        "reason": reason,
        "count": len(nodes),
        "names": sorted({node.name for node in nodes}),
        "business_codes": sorted({item.get("business_code", "") for item in populated_parts if item.get("business_code")}),
        "env_tokens": sorted({item.get("env_token", "") for item in populated_parts if item.get("env_token")}),
        "real_names": sorted({item.get("real_name", "") for item in populated_parts if item.get("real_name")}),
        "nodes": [collision_node_payload(n) for n in nodes],
    }


def node_enterprise_parts(node: Node) -> dict[str, str]:
    metadata_parts = node.metadata.get("enterprise_naming")
    if isinstance(metadata_parts, dict) and metadata_parts.get("real_name"):
        return {str(key): str(value) for key, value in metadata_parts.items()}
    return enterprise_name_parts(node.name)


def collision_node_payload(node: Node) -> dict[str, Any]:
    payload = node_payload(node)
    parts = node_enterprise_parts(node)
    if parts:
        payload["enterprise_naming"] = parts
    return payload


def edge_collision_payload(buckets: dict[str, list[Edge]], graph: Graph) -> list[dict[str, Any]]:
    return [{"key": k, "edges": [edge_payload(e, graph) for e in v]} for k, v in sorted(buckets.items()) if len(v) > 1]


def unused_mapping_payload(mapping: MappingConfig, used: set[str]) -> list[dict[str, str]]:
    return [{"stonebranch": k, "jil": v} for k, v in sorted(mapping.node_mappings.items()) if k not in used]
