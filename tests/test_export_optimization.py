from __future__ import annotations

from pathlib import Path

from stonebranch_graph import exporters
from stonebranch_graph.core import Edge, Graph, Node
from stonebranch_graph.exporters import export_dot, export_graph_bundle, export_mermaid
from stonebranch_graph.pack import write_mermaid


def make_linear_graph(edge_count: int) -> Graph:
    graph = Graph(source_system="test", env="DEV")
    for idx in range(edge_count + 1):
        node_id = f"node-{idx}"
        graph.add_node(
            Node(
                id=node_id,
                canonical_key=f"DEV:task:node_{idx}",
                source_system="test",
                env="DEV",
                kind="task",
                name=f"node_{idx}",
            )
        )
    for idx in range(edge_count):
        graph.add_edge(
            Edge(
                id=f"edge-{idx:03d}",
                source=f"node-{idx}",
                target=f"node-{idx + 1}",
                relation="depends_on_success",
                source_system="test",
            )
        )
    return graph


def test_export_graph_bundle_computes_metrics_once(tmp_path: Path, monkeypatch) -> None:
    graph = make_linear_graph(3)
    original = exporters.compute_graph_metrics
    calls = 0

    def counted_compute_graph_metrics(graph: Graph, **kwargs):
        nonlocal calls
        calls += 1
        return original(graph)

    monkeypatch.setattr(exporters, "compute_graph_metrics", counted_compute_graph_metrics)

    export_graph_bundle(graph, tmp_path)

    assert calls == 1
    assert (tmp_path / "metrics.json").exists()
    assert (tmp_path / "report.md").exists()


def test_top_level_mermaid_and_dot_exports_are_capped(tmp_path: Path) -> None:
    graph = make_linear_graph(5)
    mermaid_path = tmp_path / "dependency-graph.mmd"
    dot_path = tmp_path / "dependency-graph.dot"

    export_mermaid(graph, mermaid_path, max_edges=2)
    export_dot(graph, dot_path, max_edges=2)

    mermaid = mermaid_path.read_text(encoding="utf-8")
    dot = dot_path.read_text(encoding="utf-8")

    assert "Graph view capped at 2 of 5 edges" in mermaid
    assert mermaid.count("-->|depends_on_success|") == 2
    assert "Graph view capped at 2 of 5 edges" in dot
    assert dot.count(" -> ") == 2


def test_export_report_mentions_capped_graph_views(tmp_path: Path) -> None:
    graph = make_linear_graph(4)

    export_graph_bundle(graph, tmp_path, max_graph_edges=2)

    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Generated graph views" in report
    assert "capped at **2** of **4** edges" in report
    assert "graph.json" in report
    assert "edges.csv" in report


def test_pack_mermaid_views_are_deterministically_sorted(tmp_path: Path) -> None:
    graph = Graph(source_system="test", env="DEV")
    for name in ("a", "b", "c"):
        graph.add_node(
            Node(
                id=name,
                canonical_key=f"DEV:task:{name}",
                source_system="test",
                env="DEV",
                kind="task",
                name=name,
            )
        )
    graph.add_edge(Edge(id="edge-b", source="b", target="c", relation="depends_on", source_system="test"))
    graph.add_edge(Edge(id="edge-a", source="a", target="b", relation="depends_on", source_system="test"))

    output = tmp_path / "view.mmd"
    write_mermaid(graph, output, relations={"depends_on"}, max_edges=10)

    edge_lines = [line for line in output.read_text(encoding="utf-8").splitlines() if "-->|" in line]
    assert edge_lines == [
        "  n_a -->|depends_on| n_b",
        "  n_b -->|depends_on| n_c",
    ]
