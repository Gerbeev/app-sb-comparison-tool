from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from .core import Edge, Graph, Node
from .metrics import compute_graph_metrics, metric_rows, metrics_to_dict


def export_graph_bundle(graph: Graph, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "graph.json", graph.to_dict())
    export_nodes_csv(graph, output_dir / "objects.csv")
    export_edges_csv(graph, output_dir / "edges.csv")
    export_mermaid(graph, output_dir / "dependency-graph.mmd")
    export_dot(graph, output_dir / "dependency-graph.dot")
    graph_metrics = compute_graph_metrics(graph)
    write_json(output_dir / "metrics.json", metrics_to_dict(graph_metrics))
    export_csv_rows(output_dir / "metrics.csv", ["metric", "value"], metric_rows(metrics_to_dict(graph_metrics)))
    export_report(graph, output_dir / "report.md")


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_graph_json(path: Path) -> Graph:
    return Graph.from_dict(json.loads(path.read_text(encoding="utf-8")))


def export_nodes_csv(graph: Graph, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "canonical_key",
                "source_system",
                "env",
                "kind",
                "native_kind",
                "name",
                "source_file",
                "attributes_hash",
            ],
        )
        writer.writeheader()
        for node in sorted(graph.nodes.values(), key=lambda n: n.id):
            writer.writerow(
                {
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
            )


def export_edges_csv(graph: Graph, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "source",
                "target",
                "relation",
                "source_system",
                "native_relation",
                "evidence_file",
                "evidence_path",
                "evidence_key",
                "evidence_value",
                "confidence",
            ],
        )
        writer.writeheader()
        for edge in sorted(graph.edges.values(), key=lambda e: e.id):
            writer.writerow(edge.__dict__)


def export_mermaid(graph: Graph, path: Path, edge_filter: set[str] | None = None) -> None:
    visible_edges = [
        edge for edge in sorted(graph.edges.values(), key=lambda e: e.id)
        if edge_filter is None or edge.id in edge_filter
    ]
    visible_node_ids = {edge.source for edge in visible_edges} | {edge.target for edge in visible_edges}
    if not visible_edges:
        visible_node_ids = set(graph.nodes)

    lines = ["flowchart LR"]
    for node in sorted((graph.nodes[n] for n in visible_node_ids if n in graph.nodes), key=lambda n: n.id):
        label = f"{node.source_system}/{node.env}/{node.kind}: {node.name}"
        lines.append(f'  {mmd_id(node.id)}["{escape_mmd(label)}"]')

    for edge in visible_edges:
        lines.append(
            f"  {mmd_id(edge.source)} -->|{escape_mmd(edge.relation)}| {mmd_id(edge.target)}"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_dot(graph: Graph, path: Path) -> None:
    lines = ["digraph dependencies {", "  rankdir=LR;"]
    for node in sorted(graph.nodes.values(), key=lambda n: n.id):
        label = f"{node.source_system}/{node.env}/{node.kind}: {node.name}"
        lines.append(f'  "{escape_dot(node.id)}" [label="{escape_dot(label)}"];')
    for edge in sorted(graph.edges.values(), key=lambda e: e.id):
        lines.append(
            f'  "{escape_dot(edge.source)}" -> "{escape_dot(edge.target)}" '
            f'[label="{escape_dot(edge.relation)}"];'
        )
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_report(graph: Graph, path: Path) -> None:
    kind_counts = Counter(node.kind for node in graph.nodes.values())
    relation_counts = Counter(edge.relation for edge in graph.edges.values())
    inbound, outbound = degree_maps(graph)
    most_connected = sorted(
        graph.nodes.values(),
        key=lambda n: inbound.get(n.id, 0) + outbound.get(n.id, 0),
        reverse=True,
    )[:50]

    lines = [
        f"# {graph.source_system} dependency graph report",
        "",
        "## Summary",
        "",
        f"- Env: **{graph.env}**",
        f"- Objects: **{len(graph.nodes)}**",
        f"- Dependencies: **{len(graph.edges)}**",
        "",
        "## Quality metrics",
        "",
        f"- Synthetic nodes: **{compute_graph_metrics(graph).synthetic_nodes}**",
        f"- Low-confidence edges: **{compute_graph_metrics(graph).low_confidence_edges}**",
        f"- Orphan nodes: **{compute_graph_metrics(graph).orphan_nodes}**",
        f"- Orphan tasks: **{compute_graph_metrics(graph).orphan_tasks}**",
        f"- Tasks without inbound dependency: **{compute_graph_metrics(graph).tasks_without_inbound_dependency}**",
        f"- Tasks without outbound dependency: **{compute_graph_metrics(graph).tasks_without_outbound_dependency}**",
        f"- Tasks without trigger: **{compute_graph_metrics(graph).tasks_without_trigger}**",
        f"- Condition nodes: **{compute_graph_metrics(graph).condition_nodes}**",
        f"- Conditions not parsed: **{compute_graph_metrics(graph).conditions_not_parsed}**",
        "",
        "## Object types",
        "",
        "| Kind | Count |",
        "|---|---:|",
    ]
    for kind, count in sorted(kind_counts.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| {kind} | {count} |")

    lines.extend(["", "## Relation types", "", "| Relation | Count |", "|---|---:|"])
    for rel, count in sorted(relation_counts.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| {rel} | {count} |")

    if graph.warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in graph.warnings:
            lines.append(f"- {warning}")

    lines.extend(
        [
            "",
            "## Most connected objects",
            "",
            "| Kind | Object | In | Out | Total |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for node in most_connected:
        inc = inbound.get(node.id, 0)
        out = outbound.get(node.id, 0)
        lines.append(f"| {node.kind} | `{node.name}` | {inc} | {out} | {inc + out} |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def degree_maps(graph: Graph) -> tuple[dict[str, int], dict[str, int]]:
    inbound = {node_id: 0 for node_id in graph.nodes}
    outbound = {node_id: 0 for node_id in graph.nodes}
    for edge in graph.edges.values():
        outbound[edge.source] = outbound.get(edge.source, 0) + 1
        inbound[edge.target] = inbound.get(edge.target, 0) + 1
    return inbound, outbound


def mmd_id(value: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)


def escape_mmd(value: str) -> str:
    return str(value).replace('"', "'").replace("|", "/")


def escape_dot(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def export_csv_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
