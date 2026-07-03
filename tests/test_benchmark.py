"""Performance regression tests (IMPLEMENTATION_PLAN.md Definition of Done #4).

Guards against an accidental O(N^2) blowup in parse -> build -> erase -> compare
by checking wall-clock time scales roughly linearly from 1k to 10k units, and
stays under a generous CI bound in absolute terms. This must not reduce
fidelity: task 10/11 performance work should only ever change *how* results
are computed, never *what* they are -- these tests assert both.
"""

from __future__ import annotations

import time
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.parsers.autosys_jil import AutosysJilParser
from stonebranch_graph.skeleton_autosys import build_autosys_skeleton
from stonebranch_graph.skeleton_compare import compare_skeletons
from stonebranch_graph.skeleton_normalize import erase_plumbing


def _generate_jil(n_boxes: int, jobs_per_box: int) -> str:
    """Synthetic AutoSys JIL: n_boxes boxes, each holding a job chain, boxes chained via s(box)."""

    lines: list[str] = []
    for b in range(n_boxes):
        box_name = f"BOX_{b}"
        lines.append(f"insert_job: {box_name}")
        lines.append("job_type: b")
        if b > 0:
            lines.append(f"condition: s(BOX_{b - 1})")
        lines.append("")
        for j in range(jobs_per_box):
            job_name = f"BOX_{b}_JOB_{j}"
            lines.append(f"insert_job: {job_name}")
            lines.append("job_type: c")
            lines.append(f"box_name: {box_name}")
            if j > 0:
                lines.append(f"condition: s(BOX_{b}_JOB_{j - 1})")
            lines.append(f"command: /app/job_{b}_{j}.sh")
            lines.append("")
    return "\n".join(lines)


def _build_pipeline(tmp_path: Path, n_boxes: int, jobs_per_box: int):
    config = AnalyzerConfig.default()
    jil_dir = tmp_path / f"jil_{n_boxes}_{jobs_per_box}"
    jil_dir.mkdir()
    (jil_dir / "synthetic.jil").write_text(_generate_jil(n_boxes, jobs_per_box), encoding="utf-8")

    start = time.perf_counter()
    jobs = AutosysJilParser(config).parse_raw(jil_dir)
    skeleton = build_autosys_skeleton(jobs, alias=None)
    skeleton = erase_plumbing(skeleton)
    comparison = compare_skeletons(skeleton, skeleton)
    elapsed = time.perf_counter() - start
    return elapsed, skeleton, comparison


def test_10k_units_completes_within_generous_bound(tmp_path):
    # 100 boxes * 100 jobs = 10,000 unit nodes (+ 100 container nodes).
    elapsed, skeleton, comparison = _build_pipeline(tmp_path, n_boxes=100, jobs_per_box=100)

    unit_count = sum(1 for node in skeleton.nodes.values() if node.kind == "unit")
    assert unit_count == 10_000
    assert elapsed < 20.0, f"parse->build->erase->compare took {elapsed:.2f}s for 10k units"

    # Fidelity check: self-comparison must be a perfect match at every level.
    for level, summary in comparison.summary_by_level.items():
        assert summary["only_in_stonebranch"] == 0
        assert summary["only_in_jil"] == 0
        assert summary["changed"] == 0


def test_scaling_from_1k_to_10k_is_roughly_linear(tmp_path):
    small_elapsed, small_skeleton, _ = _build_pipeline(tmp_path, n_boxes=10, jobs_per_box=100)
    large_elapsed, large_skeleton, _ = _build_pipeline(tmp_path, n_boxes=100, jobs_per_box=100)

    small_units = sum(1 for node in small_skeleton.nodes.values() if node.kind == "unit")
    large_units = sum(1 for node in large_skeleton.nodes.values() if node.kind == "unit")
    assert small_units == 1_000
    assert large_units == 10_000

    # Guard against accidental O(N^2): a 10x size increase should not translate
    # into a 15x+ time increase. Floor the small-run time to avoid dividing by
    # near-zero timer noise on very fast machines.
    ratio = large_elapsed / max(small_elapsed, 0.01)
    assert ratio < 15.0, (
        f"scaling ratio {ratio:.1f}x looks superlinear "
        f"(1k={small_elapsed:.3f}s, 10k={large_elapsed:.3f}s)"
    )
