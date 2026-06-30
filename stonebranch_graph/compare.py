from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path
from typing import Any

from .config import AnalyzerConfig, MappingConfig
from .core import Edge, Graph, Node, normalize_name
from .exporters import export_csv_rows, write_json
from .metrics import compute_comparison_metrics, metric_rows, metrics_to_dict


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


def compare_graphs(stonebranch: Graph, jil: Graph, mapping: MappingConfig, config: AnalyzerConfig) -> Comparison:
    mapping_usage: set[str] = set()
    sb_buckets = bucket_nodes(stonebranch, mapping, left=True, mapping_usage=mapping_usage)
    jil_buckets = bucket_nodes(jil, mapping, left=False, mapping_usage=mapping_usage)

    sb_collisions = collision_payload(sb_buckets)
    jil_collisions = collision_payload(jil_buckets)
    sb_node_index = {k: v[0] for k, v in sb_buckets.items() if len(v) == 1}
    jil_node_index = {k: v[0] for k, v in jil_buckets.items() if len(v) == 1}

    sb_keys = set(sb_node_index)
    jil_keys = set(jil_node_index)
    matched_keys = sb_keys & jil_keys
    missing_in_sb = sorted(jil_keys - sb_keys)
    missing_in_jil = sorted(sb_keys - jil_keys)

    sb_edge_buckets = bucket_edges(stonebranch, mapping, left=True, mapping_usage=mapping_usage)
    jil_edge_buckets = bucket_edges(jil, mapping, left=False, mapping_usage=mapping_usage)
    sb_edge_collisions = edge_collision_payload(sb_edge_buckets, stonebranch)
    jil_edge_collisions = edge_collision_payload(jil_edge_buckets, jil)

    sb_edge_index = {k: v[0] for k, v in sb_edge_buckets.items() if len(v) == 1}
    jil_edge_index = {k: v[0] for k, v in jil_edge_buckets.items() if len(v) == 1}
    sb_edge_keys = set(sb_edge_index)
    jil_edge_keys = set(jil_edge_index)
    matched_edge_keys = sb_edge_keys & jil_edge_keys
    missing_edges_in_sb = sorted(jil_edge_keys - sb_edge_keys)
    missing_edges_in_jil = sorted(sb_edge_keys - jil_edge_keys)

    changed_attributes: list[dict[str, Any]] = []
    command_diff: list[dict[str, Any]] = []
    condition_diff: list[dict[str, Any]] = []

    for key in sorted(matched_keys):
        sb_node = sb_node_index[key]
        jil_node = jil_node_index[key]
        if comparable_hash(sb_node) and comparable_hash(jil_node) and sb_node.attributes_hash != jil_node.attributes_hash:
            changed_attributes.append(node_pair_payload(sb_node, jil_node))
        sb_command = sb_node.metadata.get("command_hash")
        jil_command = jil_node.metadata.get("command_hash")
        if sb_command and jil_command and sb_command != jil_command:
            command_diff.append({
                "key": key,
                "stonebranch": sb_node.name,
                "jil": jil_node.name,
                "stonebranch_command_hash": sb_command,
                "jil_command_hash": jil_command,
            })
        sb_condition = sb_node.metadata.get("condition_hash") or sb_node.metadata.get("condition_raw")
        jil_condition = jil_node.metadata.get("condition_hash") or jil_node.metadata.get("condition_raw")
        if sb_condition and jil_condition and sb_condition != jil_condition:
            condition_diff.append({"key": key, "stonebranch_condition": sb_condition, "jil_condition": jil_condition})

    nodes = {
        "matched": [node_pair_payload(sb_node_index[k], jil_node_index[k]) for k in sorted(matched_keys)],
        "missing_in_stonebranch": [node_payload(jil_node_index[k]) for k in missing_in_sb],
        "missing_in_jil": [node_payload(sb_node_index[k]) for k in missing_in_jil],
    }
    edges = {
        "matched": [edge_pair_payload(sb_edge_index[k], jil_edge_index[k], stonebranch, jil) for k in sorted(matched_edge_keys)],
        "missing_in_stonebranch": [edge_payload(jil_edge_index[k], jil) for k in missing_edges_in_sb],
        "missing_in_jil": [edge_payload(sb_edge_index[k], stonebranch) for k in missing_edges_in_jil],
    }
    attributes = {
        "changed": changed_attributes,
        "command_differences": command_diff,
        "condition_differences": condition_diff,
    }
    diagnostics = {
        "stonebranch_key_collisions": sb_collisions,
        "jil_key_collisions": jil_collisions,
        "stonebranch_edge_collisions": sb_edge_collisions,
        "jil_edge_collisions": jil_edge_collisions,
        "unused_mappings": unused_mapping_payload(mapping, mapping_usage),
    }
    summary: dict[str, Any] = {
        "stonebranch_nodes": len(stonebranch.nodes),
        "jil_nodes": len(jil.nodes),
        "matched_nodes": len(matched_keys),
        "missing_in_stonebranch": len(missing_in_sb),
        "missing_in_jil": len(missing_in_jil),
        "stonebranch_edges": len(stonebranch.edges),
        "jil_edges": len(jil.edges),
        "matched_edges": len(matched_edge_keys),
        "missing_edges_in_stonebranch": len(missing_edges_in_sb),
        "missing_edges_in_jil": len(missing_edges_in_jil),
        "changed_attributes": len(changed_attributes),
        "command_differences": len(command_diff),
        "condition_differences": len(condition_diff),
        "stonebranch_key_collision_count": len(sb_collisions),
        "jil_key_collision_count": len(jil_collisions),
        "stonebranch_edge_collision_count": len(sb_edge_collisions),
        "jil_edge_collision_count": len(jil_edge_collisions),
        "unused_mapping_count": len(diagnostics["unused_mappings"]),
    }
    metrics = metrics_to_dict(compute_comparison_metrics(summary, nodes, edges, attributes, stonebranch, jil))
    summary.update(metrics)

    comparison = Comparison(summary=summary, nodes=nodes, edges=edges, attributes=attributes, diagnostics=diagnostics)
    comparison.risks = build_risks(comparison)
    return comparison


def bucket_nodes(graph: Graph, mapping: MappingConfig, left: bool, mapping_usage: set[str]) -> dict[str, list[Node]]:
    buckets: dict[str, list[Node]] = {}
    for node in graph.nodes.values():
        key = comparison_node_key(node, mapping, left, mapping_usage)
        buckets.setdefault(key, []).append(node)
    return buckets


def bucket_edges(graph: Graph, mapping: MappingConfig, left: bool, mapping_usage: set[str]) -> dict[str, list[Edge]]:
    buckets: dict[str, list[Edge]] = {}
    for edge in graph.edges.values():
        key = comparison_edge_key(edge, graph, mapping, left, mapping_usage)
        buckets.setdefault(key, []).append(edge)
    return buckets


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
    if len(parts) == 4 and parts[0] in {"stonebranch", "autosys_jil", "jil"}:
        _, env, kind, name = parts
    elif len(parts) == 3:
        env, kind, name = parts
    else:
        env, kind, name = "default", "object", key
    kind = mapping.kind_aliases.get(kind, kind)
    name = normalize_name(name)
    for rule in mapping.name_rewrites:
        pattern = rule.get("from", "")
        repl = rule.get("to", "")
        if pattern:
            name = re.sub(pattern, repl, name)
    return f"{env}:{kind}:{name}"


def comparison_edge_key(edge: Edge, graph: Graph, mapping: MappingConfig, left: bool, mapping_usage: set[str] | None = None) -> str:
    source = graph.nodes.get(edge.source)
    target = graph.nodes.get(edge.target)
    if not source or not target:
        return f"broken:{edge.id}"
    return f"{comparison_node_key(source, mapping, left, mapping_usage)}->{edge.relation}->{comparison_node_key(target, mapping, left, mapping_usage)}"


def collision_payload(buckets: dict[str, list[Node]]) -> list[dict[str, Any]]:
    return [{"key": k, "nodes": [node_payload(n) for n in v]} for k, v in sorted(buckets.items()) if len(v) > 1]


def edge_collision_payload(buckets: dict[str, list[Edge]], graph: Graph) -> list[dict[str, Any]]:
    return [{"key": k, "edges": [edge_payload(e, graph) for e in v]} for k, v in sorted(buckets.items()) if len(v) > 1]


def unused_mapping_payload(mapping: MappingConfig, used: set[str]) -> list[dict[str, str]]:
    return [{"stonebranch": k, "jil": v} for k, v in sorted(mapping.node_mappings.items()) if k not in used]


def comparable_hash(node: Node) -> bool:
    return bool(node.metadata.get("normalized_attribute_hash"))


def node_payload(node: Node | None) -> dict[str, Any]:
    if node is None:
        return {}
    return {
        "id": node.id,
        "canonical_key": node.canonical_key,
        "source_system": node.source_system,
        "env": node.env,
        "kind": node.kind,
        "native_kind": node.native_kind,
        "name": node.name,
        "source_file": node.source_file,
        "attributes_hash": node.attributes_hash,
    }


def node_pair_payload(left: Node, right: Node) -> dict[str, Any]:
    return {"key": left.canonical_key, "stonebranch": node_payload(left), "jil": node_payload(right)}


def edge_payload(edge: Edge, graph: Graph) -> dict[str, Any]:
    source = graph.nodes.get(edge.source)
    target = graph.nodes.get(edge.target)
    return {
        "id": edge.id,
        "relation": edge.relation,
        "native_relation": edge.native_relation,
        "source": node_payload(source) if source else {"id": edge.source},
        "target": node_payload(target) if target else {"id": edge.target},
        "evidence_file": edge.evidence_file,
        "evidence_key": edge.evidence_key,
        "evidence_value": edge.evidence_value,
        "confidence": edge.confidence,
    }


def edge_pair_payload(left: Edge, right: Edge, left_graph: Graph, right_graph: Graph) -> dict[str, Any]:
    return {"stonebranch": edge_payload(left, left_graph), "jil": edge_payload(right, right_graph)}


def build_risks(comparison: Comparison) -> list[str]:
    risks: list[str] = []
    s = comparison.summary
    if s.get("missing_edges_in_stonebranch", 0):
        risks.append("JIL dependencies exist that were not found in Stonebranch. Possible lost migration dependencies.")
    if s.get("missing_edges_in_jil", 0):
        risks.append("Stonebranch dependencies exist that were not found in JIL. Possible new/extra orchestration behavior.")
    if s.get("missing_in_stonebranch", 0):
        risks.append("JIL objects exist without Stonebranch matches.")
    if s.get("missing_in_jil", 0):
        risks.append("Stonebranch objects exist without JIL matches.")
    if s.get("command_differences", 0):
        risks.append("Matched objects have different command hashes.")
    if s.get("critical_dependency_loss_count", 0):
        risks.append("Critical JIL dependency edges are missing in Stonebranch.")
    if s.get("calendar_mismatch_count", 0):
        risks.append("Calendar relation mismatches detected.")
    if s.get("agent_machine_mismatch_count", 0):
        risks.append("Agent/machine runtime target mismatches detected.")
    if s.get("jil_conditions_not_parsed_count", 0):
        risks.append("Some JIL conditions were detected but no condition dependencies were parsed.")
    if s.get("stonebranch_key_collision_count", 0) or s.get("jil_key_collision_count", 0):
        risks.append("Normalized node key collisions detected. Some matches were excluded to avoid false positives.")
    if s.get("unused_mapping_count", 0):
        risks.append("Some manual mapping rules were not used. Check mapping-diagnostics.csv.")
    if s.get("migration_readiness_score", 100) < 70:
        risks.append("Migration readiness score is below 70. Manual review is required before production use.")
    return risks


def export_comparison(comparison: Comparison, output_dir: Path, stonebranch: Graph, jil: Graph) -> None:
    compare_dir = output_dir / "compare"
    compare_dir.mkdir(parents=True, exist_ok=True)
    write_json(compare_dir / "comparison.json", comparison.to_dict())
    write_json(compare_dir / "metrics.json", comparison.summary)
    export_csv_rows(compare_dir / "metrics.csv", ["metric", "value"], metric_rows(comparison.summary))
    write_report(compare_dir / "report.md", comparison)
    write_missing_csvs(compare_dir, comparison)
    write_edge_diff_csv(compare_dir, comparison)
    write_diagnostics_csv(compare_dir, comparison)
    write_overlay_mermaid(compare_dir / "overlay-graph.mmd", comparison, stonebranch, jil)


def write_report(path: Path, comparison: Comparison) -> None:
    s = comparison.summary
    lines = [
        "# Stonebranch vs JIL comparison report", "", "## Summary", "",
        f"- Stonebranch nodes: **{s.get('stonebranch_nodes', 0)}**",
        f"- JIL nodes: **{s.get('jil_nodes', 0)}**",
        f"- Matched nodes: **{s.get('matched_nodes', 0)}**",
        f"- Missing in Stonebranch: **{s.get('missing_in_stonebranch', 0)}**",
        f"- Missing in JIL: **{s.get('missing_in_jil', 0)}**",
        f"- Stonebranch edges: **{s.get('stonebranch_edges', 0)}**",
        f"- JIL edges: **{s.get('jil_edges', 0)}**",
        f"- Matched edges: **{s.get('matched_edges', 0)}**",
        f"- Missing edges in Stonebranch: **{s.get('missing_edges_in_stonebranch', 0)}**",
        f"- Missing edges in JIL: **{s.get('missing_edges_in_jil', 0)}**", "", "## Migration metrics", "",
        f"- Migration readiness score: **{s.get('migration_readiness_score', 0)}/100** (`{s.get('readiness_grade', 'unknown')}`)",
        f"- Node match rate: **{s.get('node_match_rate_percent', 0)}%**",
        f"- Edge match rate: **{s.get('edge_match_rate_percent', 0)}%**",
        f"- Critical dependency loss count: **{s.get('critical_dependency_loss_count', 0)}**",
        f"- Calendar mismatch count: **{s.get('calendar_mismatch_count', 0)}**",
        f"- Agent/machine mismatch count: **{s.get('agent_machine_mismatch_count', 0)}**",
        f"- Command mismatch count: **{s.get('command_mismatch_count', 0)}**",
        f"- Node key collisions: **{s.get('stonebranch_key_collision_count', 0) + s.get('jil_key_collision_count', 0)}**",
        f"- Unused mappings: **{s.get('unused_mapping_count', 0)}**", "", "## Critical risks", "",
    ]
    if comparison.risks:
        lines += [f"- {risk}" for risk in comparison.risks]
    else:
        lines.append("- No critical graph risks detected by the current rules.")
    lines += ["", "## Missing objects in Stonebranch", "", "| Kind | Object | JIL source |", "|---|---|---|"]
    for item in comparison.nodes.get("missing_in_stonebranch", [])[:200]:
        lines.append(f"| {item['kind']} | `{item['name']}` | `{item['source_file']}` |")
    lines += ["", "## Missing objects in JIL", "", "| Kind | Object | Stonebranch source |", "|---|---|---|"]
    for item in comparison.nodes.get("missing_in_jil", [])[:200]:
        lines.append(f"| {item['kind']} | `{item['name']}` | `{item['source_file']}` |")
    lines += ["", "## Missing dependencies in Stonebranch", "", "| Relation | Source | Target | Evidence |", "|---|---|---|---|"]
    for item in comparison.edges.get("missing_in_stonebranch", [])[:200]:
        lines.append(f"| {item['relation']} | `{item['source'].get('name', item['source'].get('id'))}` | `{item['target'].get('name', item['target'].get('id'))}` | `{item['evidence_file']}` |")
    lines += ["", "## Missing dependencies in JIL", "", "| Relation | Source | Target | Evidence |", "|---|---|---|---|"]
    for item in comparison.edges.get("missing_in_jil", [])[:200]:
        lines.append(f"| {item['relation']} | `{item['source'].get('name', item['source'].get('id'))}` | `{item['target'].get('name', item['target'].get('id'))}` | `{item['evidence_file']}` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_missing_csvs(compare_dir: Path, comparison: Comparison) -> None:
    node_fields = ["id", "canonical_key", "source_system", "env", "kind", "native_kind", "name", "source_file"]
    export_csv_rows(compare_dir / "missing-in-stonebranch.csv", node_fields, comparison.nodes.get("missing_in_stonebranch", []))
    export_csv_rows(compare_dir / "missing-in-jil.csv", node_fields, comparison.nodes.get("missing_in_jil", []))


def write_edge_diff_csv(compare_dir: Path, comparison: Comparison) -> None:
    rows = []
    for side in ("missing_in_stonebranch", "missing_in_jil"):
        for item in comparison.edges.get(side, []):
            rows.append({"side": side, "relation": item["relation"], "source": item["source"].get("canonical_key", item["source"].get("id")), "target": item["target"].get("canonical_key", item["target"].get("id")), "evidence_file": item.get("evidence_file", ""), "evidence_key": item.get("evidence_key", ""), "evidence_value": item.get("evidence_value", "")})
    export_csv_rows(compare_dir / "edge-diff.csv", ["side", "relation", "source", "target", "evidence_file", "evidence_key", "evidence_value"], rows)


def write_diagnostics_csv(compare_dir: Path, comparison: Comparison) -> None:
    collision_rows = []
    for section in ("stonebranch_key_collisions", "jil_key_collisions"):
        for item in comparison.diagnostics.get(section, []):
            collision_rows.append({"section": section, "key": item["key"], "count": len(item.get("nodes", [])), "objects": ";".join(n.get("id", "") for n in item.get("nodes", []))})
    export_csv_rows(compare_dir / "collisions.csv", ["section", "key", "count", "objects"], collision_rows)
    export_csv_rows(compare_dir / "mapping-diagnostics.csv", ["stonebranch", "jil"], comparison.diagnostics.get("unused_mappings", []))


def write_overlay_mermaid(path: Path, comparison: Comparison, stonebranch: Graph, jil: Graph) -> None:
    lines = ["flowchart LR", "  classDef sbOnly fill:#ffe6e6,stroke:#cc0000,stroke-width:1px;", "  classDef jilOnly fill:#e6ecff,stroke:#0047cc,stroke-width:1px;", "  classDef matched fill:#e9ffe6,stroke:#178a00,stroke-width:1px;"]
    for item in comparison.nodes.get("missing_in_jil", [])[:300]:
        lines.append(f'  {mmd_id("sb_" + item["canonical_key"])}["SB only: {escape_mmd(item["kind"] + ": " + item["name"])}"]:::sbOnly')
    for item in comparison.nodes.get("missing_in_stonebranch", [])[:300]:
        lines.append(f'  {mmd_id("jil_" + item["canonical_key"])}["JIL only: {escape_mmd(item["kind"] + ": " + item["name"])}"]:::jilOnly')
    for pair in comparison.nodes.get("matched", [])[:300]:
        sb = pair["stonebranch"]
        lines.append(f'  {mmd_id("matched_" + sb["canonical_key"])}["Matched: {escape_mmd(sb["kind"] + ": " + sb["name"])}"]:::matched')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mmd_id(value: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)


def escape_mmd(value: str) -> str:
    return str(value).replace('"', "'").replace("|", "/")
