from __future__ import annotations

import json
from pathlib import Path

import pytest

from stonebranch_graph.compare import compare_graphs, export_reconciliation_report
from stonebranch_graph.config import AnalyzerConfig, MappingConfig
from stonebranch_graph.core import Graph, Node, make_canonical_key, make_node_id
from stonebranch_graph.exporters import export_reconciliation_keys
from stonebranch_graph.parsers.autosys_jil import AutosysJilParser
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _node(source_system: str, env: str, kind: str, name: str, *, native_kind: str = "") -> Node:
    return Node(
        id=make_node_id(source_system, env, kind, name),
        canonical_key=make_canonical_key(env, kind, name),
        source_system=source_system,
        env=env,
        kind=kind,
        name=name,
        native_kind=native_kind or kind,
    )


# --- Golden test over the bundled offline examples --------------------------


@pytest.fixture(scope="module")
def example_graphs() -> tuple[Graph, Graph]:
    config = AnalyzerConfig.default()
    sb_graph = StonebranchJsonParser(config, env="PROD").parse(EXAMPLES_DIR / "stonebranch" / "PROD")
    jil_graph = AutosysJilParser(config, env="PROD").parse(EXAMPLES_DIR / "jil" / "PROD")
    return sb_graph, jil_graph


def test_known_twins_match_in_bundled_examples(example_graphs: tuple[Graph, Graph]) -> None:
    sb_graph, jil_graph = example_graphs
    mapping = MappingConfig.from_file(EXAMPLES_DIR / "mapping.json", AnalyzerConfig.default())
    comparison = compare_graphs(sb_graph, jil_graph, mapping, AnalyzerConfig.default())

    matched_keys = {item["key"] for item in comparison.nodes["matched"]}
    # These job/task pairs share a name on both sides and must match 1:1.
    for expected in (
        "PROD:task:extract",
        "PROD:task:transform",
        "PROD:task:load",
        "PROD:task:build_report",
        "PROD:task:publish",
        "PROD:task:copy_files",
        "PROD:agent:machine01",
        "PROD:calendar:business_days",
        "PROD:variable:run_date",
    ):
        assert expected in matched_keys, f"expected known twin {expected} to match"

    # Regression pin: the bundled examples intentionally also carry known,
    # NOT-yet-resolved divergences (WF_ prefix naming, Stonebranch Task
    # Monitor objects, extra AutoSys-only objects). These must stay reported,
    # not silently absorbed, so a future change that over-normalizes gets
    # caught here.
    only_in_stonebranch = {item["comparison_key"] for item in comparison.nodes["missing_in_jil"]}
    only_in_autosys = {item["comparison_key"] for item in comparison.nodes["missing_in_stonebranch"]}
    assert "PROD:task:mon_etl" in only_in_stonebranch
    assert "PROD:task:mon_load" in only_in_stonebranch
    assert "PROD:task:job_c" in only_in_autosys


def test_reconciliation_report_matches_compare_result(tmp_path: Path, example_graphs: tuple[Graph, Graph]) -> None:
    sb_graph, jil_graph = example_graphs
    mapping = MappingConfig.from_file(EXAMPLES_DIR / "mapping.json", AnalyzerConfig.default())
    comparison = compare_graphs(sb_graph, jil_graph, mapping, AnalyzerConfig.default())

    out_path = tmp_path / "reconciliation.json"
    export_reconciliation_report(comparison, out_path)
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    assert set(payload) == {"only_in_autosys", "only_in_stonebranch", "matched"}
    assert payload["matched"] == sorted(payload["matched"]), "must be deterministically sorted"
    assert payload["matched"] == sorted(item["key"] for item in comparison.nodes["matched"])
    assert payload["only_in_autosys"] == sorted(
        item["comparison_key"] for item in comparison.nodes["missing_in_stonebranch"]
    )
    assert payload["only_in_stonebranch"] == sorted(
        item["comparison_key"] for item in comparison.nodes["missing_in_jil"]
    )


def test_keys_json_has_no_migration_noise_fields(tmp_path: Path, example_graphs: tuple[Graph, Graph]) -> None:
    sb_graph, _jil_graph = example_graphs
    out_path = tmp_path / "stonebranch.keys.json"
    export_reconciliation_keys(sb_graph, out_path)
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    assert isinstance(payload, list)
    assert payload == sorted(payload), "must be ascending sorted"
    assert len(payload) == len(set(payload)), "must be deduped"
    for entry in payload:
        assert isinstance(entry, str)
        # Plain "kind:name" strings only (single-env example): no wrapper
        # objects, no source_file/attributes_hash/metadata noise.
        assert entry.count(":") == 1
        assert "source_file" not in entry
        assert "attributes_hash" not in entry


# --- Targeted suffix-stripping fixture (bundled examples have no -tm case) --
#
# The bundled examples don't happen to exercise the "-tm" / trailing-hash
# migration-noise convention described in RECONCILIATION_PLAN.md's root
# cause, so this test builds a minimal, deliberate pair of twin objects to
# pin exactly the behavior the plan asks for: a Stonebranch task named with a
# migration-tooling suffix must collapse onto its unsuffixed AutoSys twin.


def _twin_graphs() -> tuple[Graph, Graph]:
    sb_graph = Graph(source_system="stonebranch", env="PROD")
    sb_graph.add_node(_node("stonebranch", "PROD", "task", "REAL_ARCHIVE-tm"))
    sb_graph.add_node(_node("stonebranch", "PROD", "task", "STONEBRANCH_ONLY_TASK"))

    jil_graph = Graph(source_system="autosys_jil", env="PROD")
    jil_graph.add_node(_node("autosys_jil", "PROD", "task", "REAL_ARCHIVE"))
    jil_graph.add_node(_node("autosys_jil", "PROD", "task", "AUTOSYS_ONLY_TASK"))
    return sb_graph, jil_graph


def test_suffixed_twin_collapses_onto_unsuffixed_object() -> None:
    sb_graph, jil_graph = _twin_graphs()
    mapping = MappingConfig.empty(AnalyzerConfig.default())
    comparison = compare_graphs(sb_graph, jil_graph, mapping, AnalyzerConfig.default())

    matched_keys = {item["key"] for item in comparison.nodes["matched"]}
    assert "PROD:task:real_archive" in matched_keys

    only_in_stonebranch = {item["comparison_key"] for item in comparison.nodes["missing_in_jil"]}
    only_in_autosys = {item["comparison_key"] for item in comparison.nodes["missing_in_stonebranch"]}
    assert only_in_stonebranch == {"PROD:task:stonebranch_only_task"}
    assert only_in_autosys == {"PROD:task:autosys_only_task"}
    # The suffix must not leak through as a spurious mismatch on either side.
    assert "PROD:task:real_archive-tm" not in only_in_stonebranch
    assert "PROD:task:real_archive" not in only_in_autosys


def test_keys_json_byte_identical_line_for_suffixed_twin(tmp_path: Path) -> None:
    sb_graph, jil_graph = _twin_graphs()
    sb_path = tmp_path / "stonebranch.keys.json"
    jil_path = tmp_path / "autosys.keys.json"
    export_reconciliation_keys(sb_graph, sb_path)
    export_reconciliation_keys(jil_graph, jil_path)

    # JSON pretty-printing puts a trailing "," on every array element except
    # the last, so the *raw* line for an entry can legitimately differ by a
    # single trailing comma depending on where it sorts among its file's own
    # neighbors (this only ever affects each file's alphabetically-last
    # entry). Strip that before comparing "byte-identical" at the level the
    # plan cares about: the ID string content itself.
    def content_lines(path: Path) -> set[str]:
        return {line.strip().rstrip(",") for line in path.read_text(encoding="utf-8").splitlines()}

    sb_lines = content_lines(sb_path)
    jil_lines = content_lines(jil_path)

    # The shared twin must render as the exact same entry in both files
    # despite the Stonebranch-side "-tm" suffix and despite the different
    # source_system between the two graphs.
    shared_line = next(line for line in sb_lines if "real_archive" in line)
    assert shared_line in jil_lines, "same logical object must be an identical entry on both sides"

    # And the two genuinely divergent objects must NOT collide.
    sb_only_line = next(line for line in sb_lines if "stonebranch_only_task" in line)
    jil_only_line = next(line for line in jil_lines if "autosys_only_task" in line)
    assert sb_only_line not in jil_lines
    assert jil_only_line not in sb_lines
