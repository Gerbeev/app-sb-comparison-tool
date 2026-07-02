from __future__ import annotations

import ast
from pathlib import Path

from stonebranch_graph.core import Edge, Graph, Node
from stonebranch_graph.graph_utils import degree_maps
from stonebranch_graph.rendering import escape_dot, escape_mmd, mmd_id


def test_degree_maps_counts_declared_nodes_and_can_include_external_endpoints() -> None:
    graph = Graph(source_system="test", env="DEV")
    graph.add_node(Node(id="node:a", canonical_key="dev:task:a", source_system="test", env="DEV", kind="task", name="A"))
    graph.add_node(Node(id="node:b", canonical_key="dev:task:b", source_system="test", env="DEV", kind="task", name="B"))
    graph.add_edge(Edge(id="edge:ab", source="node:a", target="node:b", relation="depends_on", source_system="test"))
    graph.add_edge(Edge(id="edge:bc", source="node:b", target="external:c", relation="depends_on", source_system="test"))

    inbound, outbound = degree_maps(graph)

    assert inbound == {"node:a": 0, "node:b": 1}
    assert outbound == {"node:a": 1, "node:b": 1}

    inbound_with_external, outbound_with_external = degree_maps(graph, include_external_nodes=True)

    assert inbound_with_external["external:c"] == 1
    assert outbound_with_external["node:b"] == 1


def test_rendering_helpers_escape_common_graph_output_formats() -> None:
    assert mmd_id("stonebranch:PROD/task A") == "n_stonebranch_PROD_task_A"
    assert escape_mmd('task "A" | prod') == "task 'A' / prod"
    assert escape_dot('C:\\jobs\\"A"') == 'C:\\\\jobs\\\\\\"A\\"'


def test_graph_rendering_helpers_have_single_implementation() -> None:
    root = Path(__file__).resolve().parents[1] / "stonebranch_graph"
    definitions: dict[str, list[str]] = {"degree_maps": [], "mmd_id": [], "escape_mmd": [], "escape_dot": []}

    for source_path in root.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in definitions:
                definitions[node.name].append(source_path.name)

    assert definitions == {
        "degree_maps": ["graph_utils.py"],
        "mmd_id": ["rendering.py"],
        "escape_mmd": ["rendering.py"],
        "escape_dot": ["rendering.py"],
    }
