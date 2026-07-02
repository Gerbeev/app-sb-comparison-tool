from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.core import Edge, Graph, Node
from stonebranch_graph.exporters import export_csv_rows, export_graph_bundle
from stonebranch_graph.graph_utils import GraphTraversalCache
from stonebranch_graph.pack import create_analysis_pack, write_graph_views


def make_dense_enough_graph(edge_count: int = 12) -> Graph:
    graph = Graph(source_system="test", env="DEV")
    for idx in range(edge_count + 1):
        node = Node(
            id=f"node-{idx:03d}",
            canonical_key=f"DEV:task:node_{idx:03d}",
            source_system="test",
            env="DEV",
            kind="task",
            name=f"node_{idx:03d}",
        )
        graph.add_node(node)
    for idx in range(edge_count):
        graph.add_edge(
            Edge(
                id=f"edge-{idx:03d}",
                source=f"node-{idx:03d}",
                target=f"node-{idx + 1:03d}",
                relation="depends_on_success",
                source_system="test",
            )
        )
    return graph


def test_graph_traversal_cache_centralizes_sort_counts_and_degrees() -> None:
    graph = make_dense_enough_graph(3)

    cache = GraphTraversalCache.build(graph)

    assert [node.id for node in cache.sorted_nodes] == ["node-000", "node-001", "node-002", "node-003"]
    assert [edge.id for edge in cache.sorted_edges] == ["edge-000", "edge-001", "edge-002"]
    assert cache.kind_counts == {"task": 4}
    assert cache.relation_counts == {"depends_on_success": 3}
    assert cache.outbound["node-000"] == 1
    assert cache.inbound["node-003"] == 1


def test_export_graph_bundle_builds_traversal_cache_once(tmp_path: Path, monkeypatch) -> None:
    graph = make_dense_enough_graph(5)
    original_build = GraphTraversalCache.build
    calls = 0

    def counted_build(cls, graph: Graph) -> GraphTraversalCache:
        nonlocal calls
        calls += 1
        return original_build(graph)

    monkeypatch.setattr(GraphTraversalCache, "build", classmethod(counted_build))

    export_graph_bundle(graph, tmp_path)

    assert calls == 1
    assert (tmp_path / "graph.json").exists()
    assert (tmp_path / "report.md").exists()


def test_create_analysis_pack_reuses_single_traversal_cache_for_pack_outputs(tmp_path: Path, monkeypatch) -> None:
    graph = make_dense_enough_graph(5)
    original_build = GraphTraversalCache.build
    calls = 0

    def counted_build(cls, graph: Graph) -> GraphTraversalCache:
        nonlocal calls
        calls += 1
        return original_build(graph)

    monkeypatch.setattr(GraphTraversalCache, "build", classmethod(counted_build))

    create_analysis_pack(
        graph=graph,
        output_dir=tmp_path,
        pack_type="test-analysis-pack",
        source_path=Path("/tmp/source"),
        env="DEV",
        include_raw_values=False,
    )

    assert calls == 1
    assert (tmp_path / "indexes" / "node-index.json").exists()
    assert (tmp_path / "graphs" / "README.md").exists()
    assert (tmp_path / "reports" / "relation-summary.csv").exists()


def test_pack_graph_views_do_not_build_traversal_cache(tmp_path: Path, monkeypatch) -> None:
    def fail_if_rebuilt(cls, graph: Graph) -> GraphTraversalCache:
        raise AssertionError("write_graph_views should not build traversal cache")

    monkeypatch.setattr(GraphTraversalCache, "build", classmethod(fail_if_rebuilt))

    write_graph_views(tmp_path)

    assert (tmp_path / "README.md").exists()
    assert not (tmp_path / "full.mmd").exists()
    assert not (tmp_path / "dependencies-only.mmd").exists()


def test_export_csv_rows_accepts_streaming_iterables(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"

    export_csv_rows(path, ["idx", "value"], ({"idx": idx, "value": f"v{idx}"} for idx in range(3)))

    assert path.read_text(encoding="utf-8").splitlines() == [
        "idx,value",
        "0,v0",
        "1,v1",
        "2,v2",
    ]


def test_index_outputs_remain_deterministic_after_cache_refactor(tmp_path: Path) -> None:
    graph = make_dense_enough_graph(4)

    create_analysis_pack(
        graph=graph,
        output_dir=tmp_path,
        pack_type="test-analysis-pack",
        source_path=Path("/tmp/source"),
        env="DEV",
        include_raw_values=False,
    )

    edge_index = json.loads((tmp_path / "indexes" / "edge-index.json").read_text(encoding="utf-8"))
    assert edge_index["by_relation"]["depends_on_success"] == [
        "edge-000",
        "edge-001",
        "edge-002",
        "edge-003",
    ]
