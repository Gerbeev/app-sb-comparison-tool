from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.artifacts import (
    ANALYSIS_PACK_FILE_NAMES,
    COMPARISON_FILE_NAMES,
    COMPARISON_PACK_FILE_NAMES,
    GRAPH_BUNDLE_FILE_NAMES,
    SCHEMA_PROFILE_FILE_NAMES,
    TRIAGE_OUTPUT_FILE_NAMES,
    analysis_pack_files,
    comparison_files,
    comparison_pack_files,
    graph_bundle_files,
    schema_profile_files,
    triage_output_files,
)
from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import Graph
from stonebranch_graph.pack import write_compare_pack_manifest, write_pack_manifest
from stonebranch_graph.triage import TRIAGE_OUTPUT_FILES
from stonebranch_graph.workflows import (
    analysis_pack_files as workflow_analysis_pack_files,
    comparison_files as workflow_comparison_files,
    comparison_pack_files as workflow_comparison_pack_files,
    graph_bundle_files as workflow_graph_bundle_files,
    schema_profile_files as workflow_schema_profile_files,
)

ROOT = Path(__file__).resolve().parents[1]


def test_r3_artifact_name_contracts_are_unique() -> None:
    contracts = [
        GRAPH_BUNDLE_FILE_NAMES,
        ANALYSIS_PACK_FILE_NAMES,
        COMPARISON_FILE_NAMES,
        COMPARISON_PACK_FILE_NAMES,
        TRIAGE_OUTPUT_FILE_NAMES,
        SCHEMA_PROFILE_FILE_NAMES,
    ]

    for contract in contracts:
        assert len(contract) == len(set(contract))
        assert all(not name.startswith("/") for name in contract)


def test_r3_workflow_file_helpers_delegate_to_artifact_contracts(tmp_path: Path) -> None:
    assert workflow_graph_bundle_files(tmp_path) == graph_bundle_files(tmp_path)
    assert workflow_analysis_pack_files(tmp_path) == analysis_pack_files(tmp_path)
    assert workflow_comparison_files(tmp_path) == comparison_files(tmp_path)
    assert workflow_comparison_pack_files(tmp_path) == comparison_pack_files(tmp_path)
    assert workflow_schema_profile_files(tmp_path) == schema_profile_files(tmp_path)



def test_r3_analysis_pack_manifest_uses_central_contract(tmp_path: Path) -> None:
    graph = Graph(source_system="stonebranch", env="PROD")

    write_pack_manifest(
        graph=graph,
        output_dir=tmp_path,
        pack_type="stonebranch-analysis-pack",
        source_path=tmp_path / "source",
        env="PROD",
        include_raw_values=False,
        deep_scan=False,
        env_aware=False,
    )

    manifest = json.loads((tmp_path / "pack-manifest.json").read_text(encoding="utf-8"))
    assert manifest["important_files"] == list(ANALYSIS_PACK_FILE_NAMES)



def test_r3_compare_pack_manifest_uses_central_contract(tmp_path: Path) -> None:
    write_compare_pack_manifest(tmp_path, tmp_path / "sb-pack", tmp_path / "jil-pack", {"matched_nodes": 0})

    manifest = json.loads((tmp_path / "compare-pack-manifest.json").read_text(encoding="utf-8"))
    assert manifest["important_files"] == list(COMPARISON_FILE_NAMES)



def test_r3_triage_file_contract_is_centralized(tmp_path: Path) -> None:
    assert TRIAGE_OUTPUT_FILES == TRIAGE_OUTPUT_FILE_NAMES
    assert triage_output_files(tmp_path) == [tmp_path / name for name in TRIAGE_OUTPUT_FILE_NAMES]



def test_r3_docs_reference_artifact_contract_source() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    baseline = (ROOT / "docs" / "QA_BASELINE.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "stonebranch_graph/artifacts.py" in readme
    assert "stonebranch_graph/artifacts.py" in baseline
    assert "### R3" in changelog
