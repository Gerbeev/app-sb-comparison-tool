from __future__ import annotations

from stonebranch_graph.compare import compare_graphs
from stonebranch_graph.config import AnalyzerConfig, MappingConfig
from stonebranch_graph.core import Graph, Node, make_canonical_key, make_node_id


def make_test_node(source_system: str, name: str, attributes_hash: str) -> Node:
    return Node(
        id=make_node_id(source_system, "PROD", "task", name),
        canonical_key=make_canonical_key("PROD", "task", name),
        source_system=source_system,
        env="PROD",
        kind="task",
        name=name,
        native_kind="task",
        attributes_hash=attributes_hash,
    )


def test_changed_attributes_use_node_attributes_hash() -> None:
    config = AnalyzerConfig.default()
    mapping = MappingConfig.empty(config)

    stonebranch = Graph(source_system="stonebranch", env="PROD")
    stonebranch.add_node(make_test_node("stonebranch", "JOB_A", "stonebranch-hash"))

    jil = Graph(source_system="autosys_jil", env="PROD")
    jil.add_node(make_test_node("autosys_jil", "JOB_A", "jil-hash"))

    comparison = compare_graphs(stonebranch, jil, mapping, config)

    assert comparison.summary["matched_nodes"] == 1
    assert comparison.summary["changed_attributes"] == 1
    assert comparison.attributes["changed"][0]["stonebranch"]["attributes_hash"] == "stonebranch-hash"
    assert comparison.attributes["changed"][0]["jil"]["attributes_hash"] == "jil-hash"


def test_blank_attributes_hash_is_not_reported_as_changed() -> None:
    config = AnalyzerConfig.default()
    mapping = MappingConfig.empty(config)

    stonebranch = Graph(source_system="stonebranch", env="PROD")
    stonebranch.add_node(make_test_node("stonebranch", "JOB_A", ""))

    jil = Graph(source_system="autosys_jil", env="PROD")
    jil.add_node(make_test_node("autosys_jil", "JOB_A", "jil-hash"))

    comparison = compare_graphs(stonebranch, jil, mapping, config)

    assert comparison.summary["matched_nodes"] == 1
    assert comparison.summary["changed_attributes"] == 0
    assert comparison.attributes["changed"] == []
