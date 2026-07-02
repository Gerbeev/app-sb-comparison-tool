from __future__ import annotations

import csv
import json
from pathlib import Path
from collections.abc import Iterable
from typing import Any

from .core import Graph
from .graph_utils import GraphTraversalCache
from .metrics import GraphMetrics, compute_graph_metrics, metric_rows, metrics_to_dict
from .rendering import escape_dot, escape_mmd, mmd_id

TOP_LEVEL_GRAPH_MAX_EDGES = 800

NODE_CSV_FIELDS = [
    "id",
    "canonical_key",
    "source_system",
    "env",
    "kind",
    "native_kind",
    "name",
    "source_file",
    "attributes_hash",
]

EDGE_CSV_FIELDS = [
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
]

METRICS_CSV_FIELDS = ["metric", "value"]


def export_graph_bundle(
    graph: Graph,
    output_dir: Path,
    *,
    max_graph_edges: int | None = TOP_LEVEL_GRAPH_MAX_EDGES,
    traversal: GraphTraversalCache | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    traversal = traversal or GraphTraversalCache.build(graph)
    graph_metrics = compute_graph_metrics(graph, traversal=traversal)
    write_json(output_dir / "graph.json", graph.to_dict())
    export_nodes_csv(graph, output_dir / "objects.csv", traversal=traversal)
    export_edges_csv(graph, output_dir / "edges.csv", traversal=traversal)
    export_mermaid(graph, output_dir / "dependency-graph.mmd", max_edges=max_graph_edges, traversal=traversal)
    export_dot(graph, output_dir / "dependency-graph.dot", max_edges=max_graph_edges, traversal=traversal)
    metrics_payload = metrics_to_dict(graph_metrics)
    write_json(output_dir / "metrics.json", metrics_payload)
    export_csv_rows(output_dir / "metrics.csv", METRICS_CSV_FIELDS, metric_rows(metrics_payload))
    export_report(
        graph,
        output_dir / "report.md",
        graph_metrics=graph_metrics,
        graph_view_max_edges=max_graph_edges,
        traversal=traversal,
    )


def write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    write_text_file(path, json.dumps(payload, indent=2, ensure_ascii=False))


def load_graph_json(path: Path) -> Graph:
    return Graph.from_dict(json.loads(path.read_text(encoding="utf-8")))


def export_nodes_csv(graph: Graph, path: Path, *, traversal: GraphTraversalCache | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=NODE_CSV_FIELDS)
        writer.writeheader()
        traversal = traversal or GraphTraversalCache.build(graph)
        for node in traversal.sorted_nodes:
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


def export_edges_csv(graph: Graph, path: Path, *, traversal: GraphTraversalCache | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EDGE_CSV_FIELDS)
        writer.writeheader()
        traversal = traversal or GraphTraversalCache.build(graph)
        for edge in traversal.sorted_edges:
            writer.writerow(edge.__dict__)


def export_mermaid(
    graph: Graph,
    path: Path,
    edge_filter: set[str] | None = None,
    *,
    max_edges: int | None = TOP_LEVEL_GRAPH_MAX_EDGES,
    traversal: GraphTraversalCache | None = None,
) -> None:
    traversal = traversal or GraphTraversalCache.build(graph)
    matching_edges = [
        edge
        for edge in traversal.sorted_edges
        if edge_filter is None or edge.id in edge_filter
    ]
    capped = max_edges is not None and len(matching_edges) > max_edges
    visible_edges = matching_edges[:max_edges] if capped else matching_edges

    visible_node_ids = {edge.source for edge in visible_edges} | {edge.target for edge in visible_edges}
    if not visible_edges:
        visible_node_ids = set(graph.nodes)

    lines = ["flowchart LR"]
    if capped:
        lines.append(
            f'  export_note["Graph view capped at {max_edges} of {len(matching_edges)} edges. '
            'Use graph.json or edges.csv for the full dependency graph."]'
        )

    for node in (node for node in traversal.sorted_nodes if node.id in visible_node_ids):
        label = f"{node.source_system}/{node.env}/{node.kind}: {node.name}"
        lines.append(f'  {mmd_id(node.id)}["{escape_mmd(label)}"]')

    for edge in visible_edges:
        lines.append(
            f"  {mmd_id(edge.source)} -->|{escape_mmd(edge.relation)}| {mmd_id(edge.target)}"
        )

    write_text_file(path, "\n".join(lines) + "\n")


def export_dot(
    graph: Graph,
    path: Path,
    *,
    max_edges: int | None = TOP_LEVEL_GRAPH_MAX_EDGES,
    traversal: GraphTraversalCache | None = None,
) -> None:
    traversal = traversal or GraphTraversalCache.build(graph)
    matching_edges = traversal.sorted_edges
    capped = max_edges is not None and len(matching_edges) > max_edges
    visible_edges = matching_edges[:max_edges] if capped else matching_edges
    visible_node_ids = {edge.source for edge in visible_edges} | {edge.target for edge in visible_edges}
    if not visible_edges:
        visible_node_ids = set(graph.nodes)

    lines = []
    if capped:
        lines.append(f"// Graph view capped at {max_edges} of {len(matching_edges)} edges. Use graph.json or edges.csv for the full dependency graph.")
    lines.extend(["digraph dependencies {", "  rankdir=LR;"])
    if capped:
        note = f"Graph view capped at {max_edges} of {len(matching_edges)} edges. Use graph.json or edges.csv for the full graph."
        lines.append(f'  "__export_note" [label="{escape_dot(note)}", shape=note];')
    for node in (node for node in traversal.sorted_nodes if node.id in visible_node_ids):
        label = f"{node.source_system}/{node.env}/{node.kind}: {node.name}"
        lines.append(f'  "{escape_dot(node.id)}" [label="{escape_dot(label)}"];')
    for edge in visible_edges:
        lines.append(
            f'  "{escape_dot(edge.source)}" -> "{escape_dot(edge.target)}" '
            f'[label="{escape_dot(edge.relation)}"];'
        )
    lines.append("}")
    write_text_file(path, "\n".join(lines) + "\n")


def export_report(
    graph: Graph,
    path: Path,
    *,
    graph_metrics: GraphMetrics | None = None,
    graph_view_max_edges: int | None = TOP_LEVEL_GRAPH_MAX_EDGES,
    traversal: GraphTraversalCache | None = None,
) -> None:
    traversal = traversal or GraphTraversalCache.build(graph)
    graph_metrics = graph_metrics or compute_graph_metrics(graph, traversal=traversal)
    lines: list[str] = []
    append_report_summary(lines, graph)
    append_quality_metrics(lines, graph_metrics)
    append_capped_graph_note(lines, graph, graph_view_max_edges)
    append_count_table(lines, title="Object types", first_column="Kind", counts=traversal.kind_counts)
    append_count_table(lines, title="Relation types", first_column="Relation", counts=traversal.relation_counts)
    append_warnings(lines, graph.warnings)
    append_most_connected(lines, traversal)
    write_text_file(path, "\n".join(lines) + "\n")


def append_report_summary(lines: list[str], graph: Graph) -> None:
    lines.extend(
        [
            f"# {graph.source_system} dependency graph report",
            "",
            "## Summary",
            "",
            f"- Env: **{graph.env}**",
            f"- Objects: **{len(graph.nodes)}**",
            f"- Dependencies: **{len(graph.edges)}**",
        ]
    )


def append_quality_metrics(lines: list[str], graph_metrics: GraphMetrics) -> None:
    lines.extend(
        [
            "",
            "## Quality metrics",
            "",
            f"- Synthetic nodes: **{graph_metrics.synthetic_nodes}**",
            f"- Low-confidence edges: **{graph_metrics.low_confidence_edges}**",
            f"- Orphan nodes: **{graph_metrics.orphan_nodes}**",
            f"- Orphan tasks: **{graph_metrics.orphan_tasks}**",
            f"- Tasks without inbound dependency: **{graph_metrics.tasks_without_inbound_dependency}**",
            f"- Tasks without outbound dependency: **{graph_metrics.tasks_without_outbound_dependency}**",
            f"- Tasks without trigger: **{graph_metrics.tasks_without_trigger}**",
            f"- Condition nodes: **{graph_metrics.condition_nodes}**",
            f"- Conditions not parsed: **{graph_metrics.conditions_not_parsed}**",
        ]
    )


def append_capped_graph_note(lines: list[str], graph: Graph, graph_view_max_edges: int | None) -> None:
    if graph_view_max_edges is None or len(graph.edges) <= graph_view_max_edges:
        return
    lines.extend(
        [
            "",
            "## Generated graph views",
            "",
            (
                f"- `dependency-graph.mmd` and `dependency-graph.dot` are capped at "
                f"**{graph_view_max_edges}** of **{len(graph.edges)}** edges. "
                "Use `graph.json` or `edges.csv` for the full dependency graph."
            ),
        ]
    )


def append_count_table(lines: list[str], *, title: str, first_column: str, counts: dict[str, int]) -> None:
    lines.extend(["", f"## {title}", "", f"| {first_column} | Count |", "|---|---:|"])
    for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {name} | {count} |")


def append_warnings(lines: list[str], warnings: list[str]) -> None:
    if not warnings:
        return
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in warnings)


def append_most_connected(lines: list[str], traversal: GraphTraversalCache) -> None:
    most_connected = sorted(
        traversal.sorted_nodes,
        key=lambda node: traversal.inbound.get(node.id, 0) + traversal.outbound.get(node.id, 0),
        reverse=True,
    )[:50]
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
        inbound_count = traversal.inbound.get(node.id, 0)
        outbound_count = traversal.outbound.get(node.id, 0)
        lines.append(f"| {node.kind} | `{node.name}` | {inbound_count} | {outbound_count} | {inbound_count + outbound_count} |")


def export_csv_rows(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
