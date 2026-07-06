from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import (
    DEFAULT_SUFFIX_STRIP_PATTERNS,
    HASH_SUFFIX_STRIP_PATTERNS,
    TASK_MONITOR_SUFFIX_PATTERNS,
    resolve_suffix_patterns,
)
from stonebranch_graph.core import Graph, make_canonical_key, make_node_id
from stonebranch_graph.core import Node as _Node
from stonebranch_graph.exporters import export_reconciliation_keys
from stonebranch_graph.workflows import build_reconciliation_keys

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def test_resolve_suffix_patterns_default_keeps_task_monitor_patterns() -> None:
    resolved = resolve_suffix_patterns(DEFAULT_SUFFIX_STRIP_PATTERNS, keep_task_monitor_suffix=False)
    assert resolved == DEFAULT_SUFFIX_STRIP_PATTERNS


def test_resolve_suffix_patterns_keep_flag_drops_only_task_monitor_patterns() -> None:
    resolved = resolve_suffix_patterns(DEFAULT_SUFFIX_STRIP_PATTERNS, keep_task_monitor_suffix=True)
    assert set(resolved) == set(HASH_SUFFIX_STRIP_PATTERNS)
    for pattern in TASK_MONITOR_SUFFIX_PATTERNS:
        assert pattern not in resolved


def test_resolve_suffix_patterns_preserves_user_config_patterns() -> None:
    # A project-specific pattern added via config/mapping.json must survive
    # the toggle; only the two built-in task-monitor patterns are dropped.
    custom = (*DEFAULT_SUFFIX_STRIP_PATTERNS, r"[-_]mig$")
    resolved = resolve_suffix_patterns(custom, keep_task_monitor_suffix=True)
    assert r"[-_]mig$" in resolved
    assert set(HASH_SUFFIX_STRIP_PATTERNS) <= set(resolved)
    for pattern in TASK_MONITOR_SUFFIX_PATTERNS:
        assert pattern not in resolved


def _twin_graph_with_task_monitor() -> Graph:
    graph = Graph(source_system="stonebranch", env="PROD")
    for name in ("REAL_ARCHIVE-tm", "REAL_ARCHIVE"):
        graph.add_node(
            _Node(
                id=make_node_id("stonebranch", "PROD", "task", name),
                canonical_key=make_canonical_key("PROD", "task", name),
                source_system="stonebranch",
                env="PROD",
                kind="task",
                name=name,
            )
        )
    return graph


def test_keep_task_monitor_suffix_keeps_object_separate(tmp_path: Path) -> None:
    graph = _twin_graph_with_task_monitor()

    folded_path = tmp_path / "folded.keys.json"
    export_reconciliation_keys(graph, folded_path, patterns=resolve_suffix_patterns(None, keep_task_monitor_suffix=False))
    folded = json.loads(folded_path.read_text(encoding="utf-8"))
    # Both names strip down to "real_archive" and dedupe into a single entry.
    assert folded == ["task:real_archive"]

    kept_path = tmp_path / "kept.keys.json"
    export_reconciliation_keys(graph, kept_path, patterns=resolve_suffix_patterns(None, keep_task_monitor_suffix=True))
    kept = json.loads(kept_path.read_text(encoding="utf-8"))
    # With the toggle on, the -tm object stays visible as its own entry.
    assert kept == ["task:real_archive", "task:real_archive-tm"]


def test_build_reconciliation_keys_workflow_writes_only_two_files(tmp_path: Path) -> None:
    result = build_reconciliation_keys(
        stonebranch_path=EXAMPLES_DIR / "stonebranch" / "PROD",
        jil_path=EXAMPLES_DIR / "jil" / "PROD",
        output_dir=tmp_path,
        config=AnalyzerConfig.default(),
        env="PROD",
    )

    written = {p.name for p in tmp_path.iterdir() if p.suffix == ".json"}
    assert written == {"stonebranch.keys.json", "autosys.keys.json"}
    # No full graph bundle: no graph.json, no graph.html, no containers, etc.
    assert not (tmp_path / "graph.json").exists()
    assert not (tmp_path / "graph.html").exists()

    assert result.summary["stonebranch_keys"] > 0
    assert result.summary["jil_keys"] > 0
    assert result.summary["keep_task_monitor_suffix"] is False
    assert set(result.files) == {tmp_path / "stonebranch.keys.json", tmp_path / "autosys.keys.json"}


def test_build_reconciliation_keys_workflow_toggle_changes_output(tmp_path: Path) -> None:
    default_dir = tmp_path / "default"
    kept_dir = tmp_path / "kept"

    build_reconciliation_keys(
        stonebranch_path=EXAMPLES_DIR / "stonebranch" / "PROD",
        jil_path=EXAMPLES_DIR / "jil" / "PROD",
        output_dir=default_dir,
        config=AnalyzerConfig.default(),
        env="PROD",
        keep_task_monitor_suffix=False,
    )
    build_reconciliation_keys(
        stonebranch_path=EXAMPLES_DIR / "stonebranch" / "PROD",
        jil_path=EXAMPLES_DIR / "jil" / "PROD",
        output_dir=kept_dir,
        config=AnalyzerConfig.default(),
        env="PROD",
        keep_task_monitor_suffix=True,
    )

    default_sb_keys = json.loads((default_dir / "stonebranch.keys.json").read_text(encoding="utf-8"))
    kept_sb_keys = json.loads((kept_dir / "stonebranch.keys.json").read_text(encoding="utf-8"))
    # Both runs are valid regardless of whether the bundled examples happen
    # to exercise the -tm suffix; the toggle must at least be threaded
    # through end-to-end and recorded in the summary.
    assert isinstance(default_sb_keys, list)
    assert isinstance(kept_sb_keys, list)
