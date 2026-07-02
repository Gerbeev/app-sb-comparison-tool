from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import Graph, Node, make_canonical_key, make_node_id
from stonebranch_graph.domain import KIND_TASK, SOURCE_AUTOSYS_JIL, SOURCE_STONEBRANCH
from stonebranch_graph.exporters import write_json
from stonebranch_graph.workflows import (
    build_jil_pack,
    build_stonebranch_pack,
    compare_graph_json,
    compare_packs,
    comparison_files,
    comparison_pack_files,
)


def _single_node_graph(source_system: str, env: str, name: str) -> Graph:
    graph = Graph(source_system=source_system, env=env)
    node_id = make_node_id(source_system, env, KIND_TASK, name)
    graph.add_node(
        Node(
            id=node_id,
            canonical_key=make_canonical_key(env, KIND_TASK, name),
            source_system=source_system,
            env=env,
            kind=KIND_TASK,
            name=name,
            native_kind="task",
            attributes_hash="same-hash",
        )
    )
    return graph


def test_workflow_compare_graph_json_contract_uses_prebuilt_graphs(tmp_path: Path) -> None:
    sb_path = tmp_path / "stonebranch-graph.json"
    jil_path = tmp_path / "jil-graph.json"
    output = tmp_path / "compare-json"
    write_json(sb_path, _single_node_graph(SOURCE_STONEBRANCH, "PROD", "JOB_A").to_dict())
    write_json(jil_path, _single_node_graph(SOURCE_AUTOSYS_JIL, "PROD", "JOB_A").to_dict())

    result = compare_graph_json(
        stonebranch_graph_path=sb_path,
        jil_graph_path=jil_path,
        output_dir=output,
        config=AnalyzerConfig.default(),
    )

    assert result.comparison is not None
    assert result.summary["matched_nodes"] == 1
    assert result.summary["missing_in_stonebranch"] == 0
    assert result.summary["missing_in_jil"] == 0
    assert result.files == comparison_files(output)
    assert all(path.exists() for path in result.files)


def test_workflow_compare_packs_contract_returns_manifest_and_diff_files(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    sb_pack = tmp_path / "sb-pack"
    jil_pack = tmp_path / "jil-pack"
    output = tmp_path / "pack-compare"

    build_stonebranch_pack(
        root / "examples" / "stonebranch" / "PROD",
        sb_pack,
        AnalyzerConfig.default(),
        env="PROD",
    )
    build_jil_pack(
        root / "examples" / "jil" / "PROD",
        jil_pack,
        AnalyzerConfig.default(),
        env="PROD",
    )

    result = compare_packs(
        stonebranch_pack=sb_pack,
        jil_pack=jil_pack,
        output_dir=output,
        config=AnalyzerConfig.default(),
    )

    assert result.comparison is None
    assert result.summary["matched_nodes"] >= 6
    assert result.files == comparison_pack_files(output)
    assert all(path.exists() for path in result.files)
    manifest = json.loads((output / "compare-pack-manifest.json").read_text(encoding="utf-8"))
    assert manifest["pack_type"] == "comparison-analysis-pack"
    assert manifest["stonebranch_pack"].endswith("sb-pack")
    assert manifest["jil_pack"].endswith("jil-pack")
    assert manifest["summary"]["matched_nodes"] == result.summary["matched_nodes"]
