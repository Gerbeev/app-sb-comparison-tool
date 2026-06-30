from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .compare import compare_graphs, export_comparison
from .config import AnalyzerConfig, MappingConfig
from .core import Graph
from .exporters import export_csv_rows, export_graph_bundle, load_graph_json, write_json
from .metrics import compute_graph_metrics, metrics_to_dict


def create_analysis_pack(
    *,
    graph: Graph,
    output_dir: Path,
    pack_type: str,
    source_path: Path,
    env: str,
    include_raw_values: bool,
    deep_scan: bool = False,
    env_aware: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    export_graph_bundle(graph, output_dir)
    write_pack_manifest(
        graph=graph,
        output_dir=output_dir,
        pack_type=pack_type,
        source_path=source_path,
        env=env,
        include_raw_values=include_raw_values,
        deep_scan=deep_scan,
        env_aware=env_aware,
    )
    write_indexes(graph, output_dir / "indexes")
    write_graph_views(graph, output_dir / "graphs")
    write_detailed_reports(graph, output_dir / "reports")
    write_pack_readme(graph, output_dir, pack_type)


def write_pack_manifest(
    *,
    graph: Graph,
    output_dir: Path,
    pack_type: str,
    source_path: Path,
    env: str,
    include_raw_values: bool,
    deep_scan: bool,
    env_aware: bool,
) -> None:
    manifest = {
        "pack_schema_version": "1.0",
        "pack_type": pack_type,
        "source_system": graph.source_system,
        "env": env,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source_path),
        "graph_file": "graph.json",
        "metrics_file": "metrics.json",
        "objects_file": "objects.csv",
        "edges_file": "edges.csv",
        "settings": {
            "include_raw_values": include_raw_values,
            "deep_scan": deep_scan,
            "env_aware": env_aware,
        },
        "counts": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
        },
        "important_files": [
            "README.md",
            "report.md",
            "graph.json",
            "metrics.json",
            "indexes/node-index.json",
            "indexes/adjacency.json",
            "graphs/full.mmd",
            "reports/top-connected.md",
            "reports/orphans.md",
        ],
    }
    write_json(output_dir / "pack-manifest.json", manifest)


def write_indexes(graph: Graph, index_dir: Path) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)

    nodes_by_id = {node.id: node.__dict__ for node in graph.nodes.values()}
    nodes_by_name: dict[str, list[str]] = defaultdict(list)
    nodes_by_kind: dict[str, list[str]] = defaultdict(list)
    nodes_by_canonical: dict[str, list[str]] = defaultdict(list)

    for node in graph.nodes.values():
        nodes_by_name[node.name.lower()].append(node.id)
        nodes_by_kind[node.kind].append(node.id)
        nodes_by_canonical[node.canonical_key.lower()].append(node.id)

    edges_by_id = {edge.id: edge.__dict__ for edge in graph.edges.values()}
    edges_by_relation: dict[str, list[str]] = defaultdict(list)
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    reverse_adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for edge in graph.edges.values():
        edges_by_relation[edge.relation].append(edge.id)
        adjacency[edge.source].append(
            {
                "edge_id": edge.id,
                "target": edge.target,
                "relation": edge.relation,
                "native_relation": edge.native_relation,
                "confidence": edge.confidence,
            }
        )
        reverse_adjacency[edge.target].append(
            {
                "edge_id": edge.id,
                "source": edge.source,
                "relation": edge.relation,
                "native_relation": edge.native_relation,
                "confidence": edge.confidence,
            }
        )

    write_json(index_dir / "node-index.json", {
        "by_id": nodes_by_id,
        "by_name": dict(sorted(nodes_by_name.items())),
        "by_kind": dict(sorted(nodes_by_kind.items())),
        "by_canonical_key": dict(sorted(nodes_by_canonical.items())),
    })
    write_json(index_dir / "edge-index.json", {
        "by_id": edges_by_id,
        "by_relation": dict(sorted(edges_by_relation.items())),
    })
    write_json(index_dir / "adjacency.json", dict(sorted(adjacency.items())))
    write_json(index_dir / "reverse-adjacency.json", dict(sorted(reverse_adjacency.items())))


def write_graph_views(graph: Graph, graph_dir: Path) -> None:
    graph_dir.mkdir(parents=True, exist_ok=True)
    write_mermaid(graph, graph_dir / "full.mmd")
    write_mermaid(graph, graph_dir / "tasks-only.mmd", node_kinds={"task", "box", "workflow"})
    write_mermaid(graph, graph_dir / "triggers-to-tasks.mmd", relations={"starts"})
    write_mermaid(graph, graph_dir / "dependencies-only.mmd", relation_prefixes=("depends_on",), relations={"contains"})
    write_mermaid(graph, graph_dir / "runtime.mmd", relations={"runs_on", "runs_on_cluster"})
    write_mermaid(graph, graph_dir / "calendars.mmd", relations={"uses_calendar", "excludes_calendar"})
    write_mermaid(graph, graph_dir / "variables.mmd", relations={"uses_variable"})


def write_mermaid(
    graph: Graph,
    path: Path,
    *,
    node_kinds: set[str] | None = None,
    relations: set[str] | None = None,
    relation_prefixes: tuple[str, ...] = (),
    max_edges: int = 800,
) -> None:
    selected_edges = []
    for edge in graph.edges.values():
        if relations is not None and edge.relation not in relations:
            if not any(edge.relation.startswith(prefix) for prefix in relation_prefixes):
                continue
        source = graph.nodes.get(edge.source)
        target = graph.nodes.get(edge.target)
        if not source or not target:
            continue
        if node_kinds is not None and source.kind not in node_kinds and target.kind not in node_kinds:
            continue
        selected_edges.append(edge)

    capped = len(selected_edges) > max_edges
    selected_edges = selected_edges[:max_edges]

    node_ids = {edge.source for edge in selected_edges} | {edge.target for edge in selected_edges}
    if not selected_edges and node_kinds:
        node_ids = {node.id for node in graph.nodes.values() if node.kind in node_kinds}

    lines = ["flowchart LR"]
    if capped:
        lines.append(f'  note["Graph capped at {max_edges} edges. Use graph.json/indexes for full analysis."]')

    for node_id in sorted(node_ids):
        node = graph.nodes.get(node_id)
        if not node:
            continue
        label = f"{node.kind}: {node.name}"
        lines.append(f'  {mmd_id(node.id)}["{escape_mmd(label)}"]')

    for edge in selected_edges:
        lines.append(f"  {mmd_id(edge.source)} -->|{escape_mmd(edge.relation)}| {mmd_id(edge.target)}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_detailed_reports(graph: Graph, reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    inbound, outbound = degree_maps(graph)

    top_connected = sorted(
        graph.nodes.values(),
        key=lambda n: inbound.get(n.id, 0) + outbound.get(n.id, 0),
        reverse=True,
    )[:100]

    lines = [
        "# Top connected objects",
        "",
        "| Kind | Object | In | Out | Total | Source |",
        "|---|---|---:|---:|---:|---|",
    ]
    for node in top_connected:
        inc = inbound.get(node.id, 0)
        out = outbound.get(node.id, 0)
        lines.append(f"| {node.kind} | `{node.name}` | {inc} | {out} | {inc + out} | `{node.source_file}` |")
    (reports_dir / "top-connected.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    orphan_nodes = [
        node for node in graph.nodes.values()
        if inbound.get(node.id, 0) == 0 and outbound.get(node.id, 0) == 0
    ]
    lines = [
        "# Orphan objects",
        "",
        "Objects below have no detected inbound or outbound dependencies.",
        "",
        "| Kind | Object | Source | Synthetic |",
        "|---|---|---|---|",
    ]
    for node in sorted(orphan_nodes, key=lambda n: (n.kind, n.name))[:1000]:
        lines.append(
            f"| {node.kind} | `{node.name}` | `{node.source_file}` | {bool(node.metadata.get('synthetic'))} |"
        )
    (reports_dir / "orphans.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    relation_rows = []
    relation_counts = Counter(edge.relation for edge in graph.edges.values())
    for relation, count in sorted(relation_counts.items(), key=lambda item: (-item[1], item[0])):
        relation_rows.append({"relation": relation, "count": count})
    export_csv_rows(reports_dir / "relation-summary.csv", ["relation", "count"], relation_rows)

    kind_rows = []
    kind_counts = Counter(node.kind for node in graph.nodes.values())
    for kind, count in sorted(kind_counts.items(), key=lambda item: (-item[1], item[0])):
        kind_rows.append({"kind": kind, "count": count})
    export_csv_rows(reports_dir / "object-summary.csv", ["kind", "count"], kind_rows)


def write_pack_readme(graph: Graph, output_dir: Path, pack_type: str) -> None:
    text = f"""# {pack_type} analysis pack

This folder is a self-contained analysis pack for `{graph.source_system}`.

## Start here

1. `report.md` - human-readable summary.
2. `graph.json` - full machine-readable graph.
3. `metrics.json` - graph metrics.
4. `indexes/node-index.json` - lookup by id, name, kind, canonical key.
5. `indexes/adjacency.json` - outgoing dependency index.
6. `indexes/reverse-adjacency.json` - incoming dependency index.
7. `graphs/*.mmd` - Mermaid graph views.
8. `reports/top-connected.md` - most connected objects.
9. `reports/orphans.md` - isolated objects.

## Important note

`graph.json` is the source of truth. Indexes and graph views are generated from it and can be regenerated.
"""
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def compare_analysis_packs(
    *,
    stonebranch_pack: Path,
    jil_pack: Path,
    output_dir: Path,
    config: AnalyzerConfig,
    mapping_path: Path | None = None,
) -> None:
    sb_graph_path = stonebranch_pack / "graph.json"
    jil_graph_path = jil_pack / "graph.json"
    if not sb_graph_path.exists():
        raise FileNotFoundError(f"Stonebranch pack graph.json not found: {sb_graph_path}")
    if not jil_graph_path.exists():
        raise FileNotFoundError(f"JIL pack graph.json not found: {jil_graph_path}")

    sb_graph = load_graph_json(sb_graph_path)
    jil_graph = load_graph_json(jil_graph_path)
    mapping = MappingConfig.from_file(mapping_path, config)

    comparison = compare_graphs(sb_graph, jil_graph, mapping, config)
    export_comparison(comparison, output_dir, sb_graph, jil_graph)

    write_compare_pack_manifest(output_dir, stonebranch_pack, jil_pack, comparison.summary)
    write_compare_indexes(output_dir / "compare", comparison)
    write_detailed_diff_reports(output_dir / "compare", comparison)


def write_compare_pack_manifest(output_dir: Path, stonebranch_pack: Path, jil_pack: Path, summary: dict[str, Any]) -> None:
    manifest = {
        "pack_schema_version": "1.0",
        "pack_type": "comparison-analysis-pack",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stonebranch_pack": str(stonebranch_pack),
        "jil_pack": str(jil_pack),
        "summary": summary,
        "important_files": [
            "compare/report.md",
            "compare/comparison.json",
            "compare/metrics.json",
            "compare/edge-diff.csv",
            "compare/missing-in-stonebranch.csv",
            "compare/missing-in-jil.csv",
            "compare/diff-index.json",
            "compare/critical-diff.json",
            "compare/remediation-plan.md",
        ],
    }
    write_json(output_dir / "compare-pack-manifest.json", manifest)


def write_compare_indexes(compare_dir: Path, comparison: Any) -> None:
    diff_index = {
        "missing_in_stonebranch": comparison.nodes.get("missing_in_stonebranch", []),
        "missing_in_jil": comparison.nodes.get("missing_in_jil", []),
        "missing_edges_in_stonebranch": comparison.edges.get("missing_in_stonebranch", []),
        "missing_edges_in_jil": comparison.edges.get("missing_in_jil", []),
        "command_differences": comparison.attributes.get("command_differences", []),
        "condition_differences": comparison.attributes.get("condition_differences", []),
    }
    write_json(compare_dir / "diff-index.json", diff_index)

    critical_relations = {
        "depends_on",
        "depends_on_success",
        "depends_on_done",
        "depends_on_failure",
        "depends_on_terminated",
        "depends_on_notrunning",
        "contains",
        "starts",
        "uses_calendar",
        "runs_on",
        "runs_command",
    }
    critical = {
        "missing_critical_edges_in_stonebranch": [
            edge for edge in comparison.edges.get("missing_in_stonebranch", [])
            if edge.get("relation") in critical_relations
        ],
        "missing_critical_edges_in_jil": [
            edge for edge in comparison.edges.get("missing_in_jil", [])
            if edge.get("relation") in critical_relations
        ],
        "missing_objects_in_stonebranch": comparison.nodes.get("missing_in_stonebranch", []),
        "missing_objects_in_jil": comparison.nodes.get("missing_in_jil", []),
        "command_differences": comparison.attributes.get("command_differences", []),
    }
    write_json(compare_dir / "critical-diff.json", critical)


def write_detailed_diff_reports(compare_dir: Path, comparison: Any) -> None:
    lines = [
        "# Remediation plan",
        "",
        "Use this file as a working checklist for closing migration gaps.",
        "",
        "## 1. Missing objects in Stonebranch",
        "",
    ]
    for item in comparison.nodes.get("missing_in_stonebranch", [])[:500]:
        lines.append(f"- [ ] Create or map `{item.get('kind')}` `{item.get('name')}` from JIL source `{item.get('source_file')}`.")

    lines.extend(["", "## 2. Missing objects in JIL", ""])
    for item in comparison.nodes.get("missing_in_jil", [])[:500]:
        lines.append(f"- [ ] Review Stonebranch-only `{item.get('kind')}` `{item.get('name')}` from `{item.get('source_file')}`.")

    lines.extend(["", "## 3. Missing dependencies in Stonebranch", ""])
    for edge in comparison.edges.get("missing_in_stonebranch", [])[:500]:
        source = edge.get("source", {})
        target = edge.get("target", {})
        lines.append(
            f"- [ ] Add/check `{edge.get('relation')}` from `{source.get('name', source.get('id'))}` "
            f"to `{target.get('name', target.get('id'))}`. Evidence: `{edge.get('evidence_file')}`."
        )

    lines.extend(["", "## 4. Missing dependencies in JIL / extra Stonebranch behavior", ""])
    for edge in comparison.edges.get("missing_in_jil", [])[:500]:
        source = edge.get("source", {})
        target = edge.get("target", {})
        lines.append(
            f"- [ ] Review Stonebranch `{edge.get('relation')}` from `{source.get('name', source.get('id'))}` "
            f"to `{target.get('name', target.get('id'))}`. Evidence: `{edge.get('evidence_file')}`."
        )

    lines.extend(["", "## 5. Command differences", ""])
    for item in comparison.attributes.get("command_differences", [])[:500]:
        lines.append(f"- [ ] Compare command for `{item.get('stonebranch')}` / `{item.get('jil')}`.")

    (compare_dir / "remediation-plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def degree_maps(graph: Graph) -> tuple[dict[str, int], dict[str, int]]:
    inbound = {node_id: 0 for node_id in graph.nodes}
    outbound = {node_id: 0 for node_id in graph.nodes}
    for edge in graph.edges.values():
        if edge.source in outbound:
            outbound[edge.source] += 1
        if edge.target in inbound:
            inbound[edge.target] += 1
    return inbound, outbound


def mmd_id(value: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)


def escape_mmd(value: str) -> str:
    return str(value).replace('"', "'").replace("|", "/")
