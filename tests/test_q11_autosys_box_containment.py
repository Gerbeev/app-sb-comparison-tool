from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import Graph, Node, make_node_id
from stonebranch_graph.domain import (
    KIND_BOX,
    KIND_TASK,
    REL_CONTAINS,
    REL_DEPENDS_ON_SUCCESS,
    SOURCE_AUTOSYS_JIL,
)
from stonebranch_graph.parsers.autosys_jil import AutosysJilParser


def parse_jil(tmp_path: Path, text: str, filename: str = "jobs.jil"):
    path = tmp_path / filename
    path.write_text(text, encoding="utf-8")
    return AutosysJilParser(AnalyzerConfig.default(), env="PROD").parse(path)


def edge_exists(graph, source: str, target: str, relation: str) -> bool:
    return any(edge.source == source and edge.target == target and edge.relation == relation for edge in graph.edges.values())


def test_jil_box_name_creates_parent_contains_child_box_and_task(tmp_path: Path) -> None:
    graph = parse_jil(
        tmp_path,
        "\n".join(
            [
                "insert_job: PARENT_BOX job_type: b",
                "insert_job: CHILD_BOX job_type: b",
                "box_name: PARENT_BOX",
                "insert_job: CHILD_JOB job_type: c",
                "box_name: CHILD_BOX",
            ]
        ),
    )

    parent_id = make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_BOX, "PARENT_BOX")
    child_box_id = make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_BOX, "CHILD_BOX")
    child_job_id = make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_TASK, "CHILD_JOB")

    assert edge_exists(graph, parent_id, child_box_id, REL_CONTAINS)
    assert edge_exists(graph, child_box_id, child_job_id, REL_CONTAINS)


def test_jil_file_name_box_is_used_for_multi_job_box_file_when_box_name_is_missing(tmp_path: Path) -> None:
    graph = parse_jil(
        tmp_path,
        "\n".join(
            [
                "insert_job: IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS job_type: c",
                "insert_job: IB_CT_CVA_1109_0en0_VALIDATE_CUSTOMERS job_type: c",
            ]
        ),
        filename="IB_CT_CVA_1109_EN_DAILY_BOX.jil",
    )

    box_id = make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_BOX, "IB_CT_CVA_1109_EN_DAILY_BOX")
    job_id = make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_TASK, "IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS")

    assert graph.nodes[box_id].metadata.get("synthetic") is True
    assert edge_exists(graph, box_id, job_id, REL_CONTAINS)
    assert graph.nodes[job_id].metadata["source_file_box_name"] == "IB_CT_CVA_1109_EN_DAILY_BOX"


def test_jil_file_name_box_prefers_existing_inner_box_by_real_name(tmp_path: Path) -> None:
    graph = parse_jil(
        tmp_path,
        "\n".join(
            [
                "insert_job: IB_CT_CVA_1109_0en0_DAILY_BOX job_type: b",
                "insert_job: IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS job_type: c",
            ]
        ),
        filename="IB_CT_CVA_1109_EN_DAILY_BOX.jil",
    )

    en_box_id = make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_BOX, "IB_CT_CVA_1109_EN_DAILY_BOX")
    real_box_id = make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_BOX, "IB_CT_CVA_1109_0en0_DAILY_BOX")
    job_id = make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_TASK, "IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS")

    assert en_box_id not in graph.nodes
    assert graph.nodes[real_box_id].metadata.get("synthetic") is not True
    assert edge_exists(graph, real_box_id, job_id, REL_CONTAINS)
    assert not edge_exists(graph, real_box_id, real_box_id, REL_CONTAINS)


def test_graph_add_node_replaces_synthetic_placeholder_with_real_definition() -> None:
    graph = Graph(source_system=SOURCE_AUTOSYS_JIL, env="PROD")
    node_id = make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_BOX, "BOX_A")
    graph.add_node(
        Node(
            id=node_id,
            canonical_key="PROD:box:box_a",
            source_system=SOURCE_AUTOSYS_JIL,
            env="PROD",
            kind=KIND_BOX,
            name="BOX_A",
            native_kind="box_name",
            source_file="child.jil",
            metadata={"synthetic": True, "reason": "referenced_without_definition"},
        )
    )
    graph.add_node(
        Node(
            id=node_id,
            canonical_key="PROD:box:box_a",
            source_system=SOURCE_AUTOSYS_JIL,
            env="PROD",
            kind=KIND_BOX,
            name="BOX_A",
            native_kind="b",
            source_file="box.jil",
            attributes_hash="abc123",
            metadata={"action": "insert_job"},
        )
    )

    node = graph.nodes[node_id]
    assert node.metadata.get("synthetic") is not True
    assert node.native_kind == "b"
    assert node.source_file == "box.jil"
    assert node.attributes_hash == "abc123"


def test_jil_condition_reference_to_box_targets_box_node(tmp_path: Path) -> None:
    graph = parse_jil(
        tmp_path,
        "\n".join(
            [
                "insert_job: DAILY_BOX job_type: b",
                "insert_job: CHILD_JOB job_type: c",
                "condition: s(DAILY_BOX)",
            ]
        ),
    )

    job_id = make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_TASK, "CHILD_JOB")
    box_id = make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_BOX, "DAILY_BOX")
    task_placeholder_id = make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_TASK, "DAILY_BOX")

    assert task_placeholder_id not in graph.nodes
    assert edge_exists(graph, job_id, box_id, REL_DEPENDS_ON_SUCCESS)
