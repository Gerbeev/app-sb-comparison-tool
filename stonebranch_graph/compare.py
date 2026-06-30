from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from pathlib import Path
from typing import Any

from .config import AnalyzerConfig, MappingConfig
from .core import Edge, Graph, Node, normalize_name
from .exporters import export_csv_rows, write_json
from .metrics import compute_comparison_metrics, metric_rows, metrics_to_dict


@dataclass
class Comparison:
    summary: dict[str, int] = field(default_factory=dict)
    nodes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    edges: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    attributes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "nodes": self.nodes,
            "edges": self.edges,
            "attributes": self.attributes,
            "risks": self.risks,
        }


def compare_graphs(
    stonebranch: Graph,
    jil: Graph,
    mapping: MappingConfig,
    config: AnalyzerConfig,
) -> Comparison:
    sb_node_index = {comparison_node_key(n, mapping, left=True): n for n in stonebranch.nodes.values()}
    jil_node_index = {comparison_node_key(n, mapping, left=False): n for n in jil.nodes.values()}

    sb_keys = set(sb_node_index)
    jil_keys = set(jil_node_index)
    matched_keys = sb_keys & jil_keys
    missing_in_sb = sorted(jil_keys - sb_keys)
    missing_in_jil = sorted(sb_keys - jil_keys)

    sb_edge_index = {
        comparison_edge_key(e, stonebranch, mapping, left=True): e for e in stonebranch.edges.values()
    }
    jil_edge_index = {
        comparison_edge_key(e, jil, mapping, left=False): e for e in jil.edges.values()
    }

    sb_edge_keys = set(sb_edge_index)
    jil_edge_keys = set(jil_edge_index)
    matched_edge_keys = sb_edge_keys & jil_edge_keys
    missing_edges_in_sb = sorted(jil_edge_keys - sb_edge_keys)
    missing_edges_in_jil = sorted(sb_edge_keys - jil_edge_keys)

    changed_attributes = []
    command_diff = []
    condition_diff = []

    for key in sorted(matched_keys):
        sb_node = sb_node_index[key]
        jil_node = jil_node_index[key]
        if comparable_hash(sb_node) and comparable_hash(jil_node) and sb_node.attributes_hash != jil_node.attributes_hash:
            changed_attributes.append(node_pair_payload(sb_node, jil_node))

        sb_command = sb_node.metadata.get("command_hash")
        jil_command = jil_node.metadata.get("command_hash")
        if sb_command and jil_command and sb_command != jil_command:
            command_diff.append(
                {
                    "key": key,
                    "stonebranch": sb_node.name,
                    "jil": jil_node.name,
                    "stonebranch_command_hash": sb_command,
                    "jil_command_hash": jil_command,
                }
            )

        sb_condition = sb_node.metadata.get("condition_raw")
        jil_condition = jil_node.metadata.get("condition_raw")
        if sb_condition and jil_condition and sb_condition != jil_condition:
            condition_diff.append(
                {
                    "key": key,
                    "stonebranch_condition": sb_condition,
                    "jil_condition": jil_condition,
                }
            )

    summary = {
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
    }
    nodes = {
        "matched": [
            node_pair_payload(sb_node_index[key], jil_node_index[key]) for key in sorted(matched_keys)
        ],
        "missing_in_stonebranch": [node_payload(jil_node_index[key]) for key in missing_in_sb],
        "missing_in_jil": [node_payload(sb_node_index[key]) for key in missing_in_jil],
    }
    edges = {
        "matched": [
            edge_pair_payload(sb_edge_index[key], jil_edge_index[key], stonebranch, jil)
            for key in sorted(matched_edge_keys)
        ],
        "missing_in_stonebranch": [
            edge_payload(jil_edge_index[key], jil) for key in missing_edges_in_sb
        ],
        "missing_in_jil": [
            edge_payload(sb_edge_index[key], stonebranch) for key in missing_edges_in_jil
        ],
    }
    attributes = {
        "changed": changed_attributes,
        "command_differences": command_diff,
        "condition_differences": condition_diff,
    }
    metrics = metrics_to_dict(
        compute_comparison_metrics(
            summary=summary,
            comparison_nodes=nodes,
            comparison_edges=edges,
            comparison_attributes=attributes,
            stonebranch=stonebranch,
            jil=jil,
        )
    )
    summary.update(metrics)

    comparison = Comparison(
        summary=summary,
        nodes=nodes,
        edges=edges,
        attributes=attributes,
    )

    comparison.risks = build_risks(comparison)
    return comparison


def comparison_node_key(node: Node, mapping: MappingConfig, left: bool) -> str:
    if left and node.canonical_key in mapping.node_mappings:
        return normalize_key(mapping.node_mappings[node.canonical_key], mapping)

    return normalize_key(node.canonical_key, mapping)


def normalize_key(key: str, mapping: MappingConfig) -> str:
    parts = key.split(":", 2)
    if len(parts) == 3:
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


def comparison_edge_key(edge: Edge, graph: Graph, mapping: MappingConfig, left: bool) -> str:
    source = graph.nodes.get(edge.source)
    target = graph.nodes.get(edge.target)
    if not source or not target:
        return f"broken:{edge.id}"

    source_key = comparison_node_key(source, mapping, left)
    target_key = comparison_node_key(target, mapping, left)
    return f"{source_key}->{edge.relation}->{target_key}"


def comparable_hash(node: Node) -> bool:
    # Raw attributes from two different orchestrators are rarely directly equal.
    # Keep this hook conservative for future normalized attribute hashes.
    return bool(node.metadata.get("normalized_attribute_hash"))


def node_payload(node: Node) -> dict[str, Any]:
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
    return {
        "key": left.canonical_key,
        "stonebranch": node_payload(left),
        "jil": node_payload(right),
    }


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
    return {
        "stonebranch": edge_payload(left, left_graph),
        "jil": edge_payload(right, right_graph),
    }


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

    if s.get("migration_readiness_score", 100) < 70:
        risks.append("Migration readiness score is below 70. Manual review is required before production use.")

    return risks


def export_comparison(
    comparison: Comparison,
    output_dir: Path,
    stonebranch: Graph,
    jil: Graph,
) -> None:
    compare_dir = output_dir / "compare"
    compare_dir.mkdir(parents=True, exist_ok=True)

    write_json(compare_dir / "comparison.json", comparison.to_dict())
    write_json(compare_dir / "metrics.json", comparison.summary)
    export_csv_rows(compare_dir / "metrics.csv", ["metric", "value"], metric_rows(comparison.summary))
    write_report(compare_dir / "report.md", comparison)
    write_missing_csvs(compare_dir, comparison)
    write_edge_diff_csv(compare_dir, comparison)
    write_overlay_mermaid(compare_dir / "overlay-graph.mmd", comparison, stonebranch, jil)


def write_report(path: Path, comparison: Comparison) -> None:
    s = comparison.summary
    lines = [
        "# Stonebranch vs JIL comparison report",
        "",
        "## Summary",
        "",
        f"- Stonebranch nodes: **{s.get('stonebranch_nodes', 0)}**",
        f"- JIL nodes: **{s.get('jil_nodes', 0)}**",
        f"- Matched nodes: **{s.get('matched_nodes', 0)}**",
        f"- Missing in Stonebranch: **{s.get('missing_in_stonebranch', 0)}**",
        f"- Missing in JIL: **{s.get('missing_in_jil', 0)}**",
        f"- Stonebranch edges: **{s.get('stonebranch_edges', 0)}**",
        f"- JIL edges: **{s.get('jil_edges', 0)}**",
        f"- Matched edges: **{s.get('matched_edges', 0)}**",
        f"- Missing edges in Stonebranch: **{s.get('missing_edges_in_stonebranch', 0)}**",
        f"- Missing edges in JIL: **{s.get('missing_edges_in_jil', 0)}**",
        "",
        "## Migration metrics",
        "",
        f"- Migration readiness score: **{s.get('migration_readiness_score', 0)}/100** (`{s.get('readiness_grade', 'unknown')}`)",
        f"- Node match rate: **{s.get('node_match_rate_percent', 0)}%**",
        f"- Edge match rate: **{s.get('edge_match_rate_percent', 0)}%**",
        f"- JIL → Stonebranch node coverage: **{s.get('jil_to_stonebranch_node_coverage_percent', 0)}%**",
        f"- Stonebranch → JIL node coverage: **{s.get('stonebranch_to_jil_node_coverage_percent', 0)}%**",
        f"- JIL → Stonebranch edge coverage: **{s.get('jil_to_stonebranch_edge_coverage_percent', 0)}%**",
        f"- Stonebranch → JIL edge coverage: **{s.get('stonebranch_to_jil_edge_coverage_percent', 0)}%**",
        f"- Critical dependency loss count: **{s.get('critical_dependency_loss_count', 0)}**",
        f"- Critical dependency extra count: **{s.get('critical_dependency_extra_count', 0)}**",
        f"- Calendar mismatch count: **{s.get('calendar_mismatch_count', 0)}**",
        f"- Agent/machine mismatch count: **{s.get('agent_machine_mismatch_count', 0)}**",
        f"- Command mismatch count: **{s.get('command_mismatch_count', 0)}**",
        f"- JIL conditions not parsed: **{s.get('jil_conditions_not_parsed_count', 0)}**",
        f"- Synthetic nodes total: **{s.get('synthetic_nodes_total', 0)}**",
        f"- Low-confidence edges total: **{s.get('low_confidence_edges_total', 0)}**",
        "",
        "## Critical risks",
        "",
    ]

    if comparison.risks:
        for risk in comparison.risks:
            lines.append(f"- {risk}")
    else:
        lines.append("- No critical graph risks detected by the current rules.")

    lines.extend(["", "## Missing objects in Stonebranch", "", "| Kind | Object | JIL source |", "|---|---|---|"])
    for item in comparison.nodes.get("missing_in_stonebranch", [])[:200]:
        lines.append(f"| {item['kind']} | `{item['name']}` | `{item['source_file']}` |")

    lines.extend(["", "## Missing objects in JIL", "", "| Kind | Object | Stonebranch source |", "|---|---|---|"])
    for item in comparison.nodes.get("missing_in_jil", [])[:200]:
        lines.append(f"| {item['kind']} | `{item['name']}` | `{item['source_file']}` |")

    lines.extend(["", "## Missing dependencies in Stonebranch", "", "| Relation | Source | Target | Evidence |", "|---|---|---|---|"])
    for item in comparison.edges.get("missing_in_stonebranch", [])[:200]:
        lines.append(
            f"| {item['relation']} | `{item['source'].get('name', item['source'].get('id'))}` | "
            f"`{item['target'].get('name', item['target'].get('id'))}` | `{item['evidence_file']}` |"
        )

    lines.extend(["", "## Missing dependencies in JIL", "", "| Relation | Source | Target | Evidence |", "|---|---|---|---|"])
    for item in comparison.edges.get("missing_in_jil", [])[:200]:
        lines.append(
            f"| {item['relation']} | `{item['source'].get('name', item['source'].get('id'))}` | "
            f"`{item['target'].get('name', item['target'].get('id'))}` | `{item['evidence_file']}` |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_missing_csvs(compare_dir: Path, comparison: Comparison) -> None:
    node_fields = ["id", "canonical_key", "source_system", "env", "kind", "native_kind", "name", "source_file"]
    export_csv_rows(compare_dir / "missing-in-stonebranch.csv", node_fields, comparison.nodes.get("missing_in_stonebranch", []))
    export_csv_rows(compare_dir / "missing-in-jil.csv", node_fields, comparison.nodes.get("missing_in_jil", []))


def write_edge_diff_csv(compare_dir: Path, comparison: Comparison) -> None:
    rows = []
    for side in ("missing_in_stonebranch", "missing_in_jil"):
        for item in comparison.edges.get(side, []):
            rows.append(
                {
                    "side": side,
                    "relation": item["relation"],
                    "source": item["source"].get("canonical_key", item["source"].get("id")),
                    "target": item["target"].get("canonical_key", item["target"].get("id")),
                    "evidence_file": item.get("evidence_file", ""),
                    "evidence_key": item.get("evidence_key", ""),
                    "evidence_value": item.get("evidence_value", ""),
                }
            )
    export_csv_rows(
        compare_dir / "edge-diff.csv",
        ["side", "relation", "source", "target", "evidence_file", "evidence_key", "evidence_value"],
        rows,
    )


def write_overlay_mermaid(path: Path, comparison: Comparison, stonebranch: Graph, jil: Graph) -> None:
    lines = [
        "flowchart LR",
        "  classDef sbOnly fill:#ffe6e6,stroke:#cc0000,stroke-width:1px;",
        "  classDef jilOnly fill:#e6ecff,stroke:#0047cc,stroke-width:1px;",
        "  classDef matched fill:#e9ffe6,stroke:#178a00,stroke-width:1px;",
    ]

    for item in comparison.nodes.get("missing_in_jil", [])[:300]:
        node_id = mmd_id("sb_" + item["canonical_key"])
        lines.append(f'  {node_id}["SB only: {escape_mmd(item["kind"] + ": " + item["name"])}"]:::sbOnly')

    for item in comparison.nodes.get("missing_in_stonebranch", [])[:300]:
        node_id = mmd_id("jil_" + item["canonical_key"])
        lines.append(f'  {node_id}["JIL only: {escape_mmd(item["kind"] + ": " + item["name"])}"]:::jilOnly')

    for pair in comparison.nodes.get("matched", [])[:300]:
        sb = pair["stonebranch"]
        node_id = mmd_id("matched_" + sb["canonical_key"])
        lines.append(f'  {node_id}["Matched: {escape_mmd(sb["kind"] + ": " + sb["name"])}"]:::matched')

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mmd_id(value: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)


def escape_mmd(value: str) -> str:
    return str(value).replace('"', "'").replace("|", "/")
