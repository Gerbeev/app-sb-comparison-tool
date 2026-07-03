"""Skeleton comparison engine and report exports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stonebranch_graph.compare import command_difference_payload
from stonebranch_graph.core import Node
from stonebranch_graph.exporters import export_csv_rows, write_text_file
from stonebranch_graph.metrics import metric_rows, readiness_grade
from stonebranch_graph.skeleton import (
    STRICTNESS_LEVELS,
    Skeleton,
    SkeletonNode,
    index_rows,
)

LEVELS = ("topology", "logic", "strict")
STATUSES = ("matched", "changed", "only_in_stonebranch", "only_in_jil")
REASON_ORDER = (
    "kind_changed",
    "parent_changed",
    "trigger_changed",
    "completion_changed",
    "qualifier_only",
)


@dataclass(frozen=True)
class SkeletonDiffEntry:
    id: str
    status_by_level: dict[str, str]
    reasons: list[str] = field(default_factory=list)
    sb_line: str = ""
    jil_line: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status_by_level": self.status_by_level,
            "reasons": self.reasons,
            "sb_line": self.sb_line,
            "jil_line": self.jil_line,
        }


@dataclass
class SkeletonComparison:
    stonebranch: Skeleton
    jil: Skeleton
    summary_by_level: dict[str, dict[str, Any]]
    entries: list[SkeletonDiffEntry]
    externals: dict[str, list[str]]
    meta: dict[str, Any]
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary_by_level": self.summary_by_level,
            "nodes": [entry.to_dict() for entry in self.entries],
            "externals": self.externals,
            "plumbing": {
                "stonebranch_erasures": self.stonebranch.erasures,
                "jil_erasures": self.jil.erasures,
            },
            "collisions": {
                "stonebranch": self.stonebranch.collisions,
                "jil": self.jil.collisions,
            },
            "meta": self.meta,
            "risks": self.risks,
        }


def compare_skeletons(sb: Skeleton, jil: Skeleton) -> SkeletonComparison:
    """Compare two skeletons by keyed canonical records at each strictness level."""

    _validate_levels()
    sb_lines, sb_records = _canonical_maps(sb)
    jil_lines, jil_records = _canonical_maps(jil)
    sb_index = _row_index(sb)
    jil_index = _row_index(jil)
    all_ids = sorted(set(sb.nodes) | set(jil.nodes))

    entries: list[SkeletonDiffEntry] = []
    for node_id in all_ids:
        status_by_level = {
            level: _status_at_level(node_id, level, sb_index, jil_index) for level in LEVELS
        }
        entries.append(
            SkeletonDiffEntry(
                id=node_id,
                status_by_level=status_by_level,
                reasons=_reasons(node_id, status_by_level, sb, jil, sb_records, jil_records),
                sb_line=sb_lines["strict"].get(node_id, ""),
                jil_line=jil_lines["strict"].get(node_id, ""),
            )
        )

    summary_by_level = {
        level: _summary_for_level(level, entries) for level in LEVELS
    }
    comparison = SkeletonComparison(
        stonebranch=sb,
        jil=jil,
        summary_by_level=summary_by_level,
        entries=entries,
        externals=_external_diff(sb, jil),
        meta=_meta_layer(sb, jil),
    )
    comparison.risks = build_skeleton_risks(comparison)
    return comparison


def export_skeleton_comparison(comparison: SkeletonComparison, output_dir: Path) -> None:
    """Write skeleton comparison artifacts under ``output_dir/compare-skeleton``."""

    compare_dir = output_dir / "compare-skeleton"
    compare_dir.mkdir(parents=True, exist_ok=True)

    write_text_file(
        compare_dir / "skeleton-stonebranch.jsonl",
        comparison.stonebranch.to_canonical_jsonl("strict"),
    )
    write_text_file(compare_dir / "skeleton-jil.jsonl", comparison.jil.to_canonical_jsonl("strict"))
    _write_json(compare_dir / "skeleton-diff.json", comparison.to_dict())

    export_csv_rows(compare_dir / "skeleton-index.csv", _index_fields(), _index_rows(comparison))

    metrics = skeleton_metrics(comparison)
    _write_json(compare_dir / "metrics.json", metrics)
    export_csv_rows(compare_dir / "metrics.csv", ["metric", "value"], metric_rows(metrics))

    write_skeleton_report(compare_dir / "report.md", comparison, metrics)
    write_skeleton_remediation_plan(compare_dir / "remediation-plan.md", comparison)


def skeleton_metrics(comparison: SkeletonComparison) -> dict[str, Any]:
    """Return per-level counts, match rates, and a skeleton readiness score."""

    levels = {
        level: {
            "matched": int(summary["matched"]),
            "changed": int(summary["changed"]),
            "only_in_stonebranch": int(summary["only_in_stonebranch"]),
            "only_in_jil": int(summary["only_in_jil"]),
            "total": int(summary["total"]),
            "match_rate_percent": float(summary["match_rate_percent"]),
        }
        for level, summary in comparison.summary_by_level.items()
    }

    topology_missing = (
        levels["topology"]["only_in_stonebranch"] + levels["topology"]["only_in_jil"]
    )
    logic_changes = levels["logic"]["changed"]
    strict_only = sum(
        1
        for entry in comparison.entries
        if entry.status_by_level["logic"] == "matched"
        and entry.status_by_level["strict"] == "changed"
    )
    sb_collisions = _real_collisions(comparison.stonebranch)
    jil_collisions = _real_collisions(comparison.jil)
    sb_collisions_allowed = _allowed_collisions(comparison.stonebranch)
    jil_collisions_allowed = _allowed_collisions(comparison.jil)
    real_collisions = len(sb_collisions) + len(jil_collisions)
    score = max(
        0,
        min(
            100,
            round(
                100
                - topology_missing * 8.0
                - logic_changes * 4.0
                - strict_only * 1.0
                - real_collisions * 8.0
            ),
        ),
    )
    return {
        "levels": levels,
        "topology_missing_nodes": topology_missing,
        "logic_changed_nodes": logic_changes,
        "strict_only_differences": strict_only,
        "command_differences": len(comparison.meta.get("command_differences", [])),
        "sb_collisions": len(sb_collisions),
        "jil_collisions": len(jil_collisions),
        "sb_collisions_allowed": len(sb_collisions_allowed),
        "jil_collisions_allowed": len(jil_collisions_allowed),
        "skeleton_readiness_score": score,
        "readiness_grade": readiness_grade(score),
    }


def build_skeleton_risks(comparison: SkeletonComparison) -> list[str]:
    risks: list[str] = []
    topology = comparison.summary_by_level["topology"]
    if topology["only_in_stonebranch"] or topology["only_in_jil"]:
        risks.append("Topology-level nodes are missing on one side of the skeleton comparison.")
    if _reason_count(comparison, "trigger_changed"):
        risks.append("Logic-level trigger changes detected; migration dependency behavior changed.")
    if _kept_plumbing_warnings(comparison.stonebranch) or _kept_plumbing_warnings(comparison.jil):
        risks.append("Dependency plumbing was kept as real work due to unsafe erasure conditions.")
    if _cycle_warnings(comparison.stonebranch) or _cycle_warnings(comparison.jil):
        risks.append("Skeleton cycle warnings were reported and need manual review.")
    if _real_collisions(comparison.stonebranch) or _real_collisions(comparison.jil):
        risks.append(
            "Alias/id collisions dropped native objects that were not on the merge "
            "allow-list; those definitions are missing from the comparison."
        )
    return risks


def write_skeleton_report(
    path: Path, comparison: SkeletonComparison, metrics: dict[str, Any]
) -> None:
    lines = [
        "# Stonebranch vs JIL skeleton comparison report",
        "",
        "`skeleton-stonebranch.jsonl` and `skeleton-jil.jsonl` are strict canonical",
        "serializations designed for direct `git diff` review.",
        "",
        "Topology compares ids, kind, parent, and dependency shape with predicates erased.",
        "Logic keeps dependency predicates but erases qualifiers such as lookback windows.",
        "Strict keeps the full canonical skeleton line, including qualifiers and completion.",
        "",
        "## Summary",
        "",
        "| Level | Matched | Changed | Only SB | Only JIL | Match rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for level in LEVELS:
        summary = comparison.summary_by_level[level]
        lines.append(
            f"| {level} | {summary['matched']} | {summary['changed']} | "
            f"{summary['only_in_stonebranch']} | {summary['only_in_jil']} | "
            f"{summary['match_rate_percent']:.2f}% |"
        )

    lines.extend(
        [
            "",
            "## Readiness",
            "",
            f"- Skeleton readiness score: **{metrics['skeleton_readiness_score']}/100** "
            f"(`{metrics['readiness_grade']}`)",
        ]
    )
    _append_plumbing_section(lines, comparison)
    _append_id_collisions(lines, comparison)
    _append_changed_nodes(lines, comparison)
    _append_qualifier_only(lines, comparison)
    _append_only_in(lines, comparison)
    _append_meta_layer(lines, comparison)
    _append_risks(lines, comparison)
    write_text_file(path, "\n".join(lines) + "\n")


def write_skeleton_remediation_plan(path: Path, comparison: SkeletonComparison) -> None:
    lines = [
        "# Skeleton remediation plan",
        "",
        "Use this checklist to close skeleton-level migration gaps.",
        "",
        "## Create missing objects",
        "",
    ]
    missing = [
        entry
        for entry in comparison.entries
        if entry.status_by_level["topology"] in {"only_in_stonebranch", "only_in_jil"}
    ]
    if not missing:
        lines.append("- [ ] No missing topology objects detected.")
    for entry in missing[:500]:
        side = (
            "JIL"
            if entry.status_by_level["topology"] == "only_in_stonebranch"
            else "Stonebranch"
        )
        lines.append(f"- [ ] Create or map `{entry.id}` in {side}.")

    lines.extend(["", "## Rewire triggers", ""])
    trigger_changes = _entries_with_reason(comparison, "trigger_changed")
    if not trigger_changes:
        lines.append("- [ ] No logic-level trigger rewires detected.")
    for entry in trigger_changes[:500]:
        expected = _record_value(entry.jil_line, "trigger")
        current = _record_value(entry.sb_line, "trigger")
        lines.append(
            f"- [ ] Rewire `{entry.id}` trigger. Stonebranch: `{current}`; "
            f"expected JIL trigger: `{expected}`."
        )

    lines.extend(["", "## Review qualifier gaps", ""])
    qualifier_only = _strict_only_entries(comparison)
    if not qualifier_only:
        lines.append("- [ ] No strict-only qualifier/completion gaps detected.")
    for entry in qualifier_only[:500]:
        reasons = ", ".join(entry.reasons) or "strict-only difference"
        lines.append(f"- [ ] Review `{entry.id}` strict-only gap: {reasons}.")

    write_text_file(path, "\n".join(lines) + "\n")


def _validate_levels() -> None:
    missing = set(LEVELS) - set(STRICTNESS_LEVELS)
    if missing:
        raise ValueError(f"Skeleton model does not support strictness levels: {sorted(missing)}")


def _canonical_maps(
    skeleton: Skeleton,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, dict[str, Any]]]]:
    lines_by_level: dict[str, dict[str, str]] = {}
    records_by_level: dict[str, dict[str, dict[str, Any]]] = {}
    for level in LEVELS:
        lines_by_level[level] = {}
        records_by_level[level] = {}
        for line in skeleton.to_canonical_jsonl(level).splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            node_id = str(record["id"])
            lines_by_level[level][node_id] = line
            records_by_level[level][node_id] = record
    return lines_by_level, records_by_level


def _row_index(skeleton: Skeleton) -> dict[str, dict[str, str | None]]:
    return {str(row["id"]): row for row in index_rows(skeleton)}


def _status_at_level(
    node_id: str,
    level: str,
    sb_index: dict[str, dict[str, str | None]],
    jil_index: dict[str, dict[str, str | None]],
) -> str:
    if node_id not in sb_index:
        return "only_in_jil"
    if node_id not in jil_index:
        return "only_in_stonebranch"
    hash_key = f"{level}_hash"
    if sb_index[node_id][hash_key] == jil_index[node_id][hash_key]:
        return "matched"
    return "changed"


def _reasons(
    node_id: str,
    status_by_level: dict[str, str],
    sb: Skeleton,
    jil: Skeleton,
    sb_records: dict[str, dict[str, dict[str, Any]]],
    jil_records: dict[str, dict[str, dict[str, Any]]],
) -> list[str]:
    if node_id not in sb.nodes or node_id not in jil.nodes:
        return []

    reasons: set[str] = set()
    sb_strict = sb_records["strict"][node_id]
    jil_strict = jil_records["strict"][node_id]
    sb_logic = sb_records["logic"][node_id]
    jil_logic = jil_records["logic"][node_id]

    if sb_strict.get("kind") != jil_strict.get("kind"):
        reasons.add("kind_changed")
    if sb_strict.get("parent") != jil_strict.get("parent"):
        reasons.add("parent_changed")
    if sb_logic.get("trigger") != jil_logic.get("trigger"):
        reasons.add("trigger_changed")
    if sb_strict.get("completion") != jil_strict.get("completion"):
        reasons.add("completion_changed")
    if status_by_level["logic"] == "matched" and status_by_level["strict"] == "changed":
        reasons.add("qualifier_only")

    return [reason for reason in REASON_ORDER if reason in reasons]


def _summary_for_level(level: str, entries: list[SkeletonDiffEntry]) -> dict[str, Any]:
    counts = {status: 0 for status in STATUSES}
    for entry in entries:
        counts[entry.status_by_level[level]] += 1
    total = sum(counts.values())
    return {
        **counts,
        "total": total,
        "match_rate_percent": _percent(counts["matched"], total),
    }


def _external_diff(sb: Skeleton, jil: Skeleton) -> dict[str, list[str]]:
    return {
        "stonebranch": sorted(sb.externals),
        "jil": sorted(jil.externals),
        "only_in_stonebranch": sorted(sb.externals - jil.externals),
        "only_in_jil": sorted(jil.externals - sb.externals),
        "matched": sorted(sb.externals & jil.externals),
    }


def _meta_layer(sb: Skeleton, jil: Skeleton) -> dict[str, Any]:
    command_differences = []
    for node_id in sorted(set(sb.nodes) & set(jil.nodes)):
        item = command_difference_payload(
            node_id,
            _node_adapter(sb.nodes[node_id], "stonebranch"),
            _node_adapter(jil.nodes[node_id], "jil"),
        )
        if item:
            command_differences.append(item)
    return {
        "command_differences": command_differences,
        "stonebranch_warnings": sorted(sb.warnings),
        "jil_warnings": sorted(jil.warnings),
    }


def _node_adapter(node: SkeletonNode, source_system: str) -> Node:
    return Node(
        id=f"{source_system}:{node.id}",
        canonical_key=node.id,
        source_system=source_system,
        env="default",
        kind=node.kind,
        name=str(node.meta.get("native") or node.id),
        native_kind=str(node.meta.get("type") or node.kind),
        source_file=str(node.meta.get("source_file") or ""),
        metadata=dict(node.meta),
    )


def _index_fields() -> list[str]:
    return [
        "id",
        "sides",
        "topology_hash_sb",
        "topology_hash_jil",
        "logic_hash_sb",
        "logic_hash_jil",
        "strict_hash_sb",
        "strict_hash_jil",
        "status_topology",
        "status_logic",
        "status_strict",
    ]


def _index_rows(comparison: SkeletonComparison) -> list[dict[str, str]]:
    sb_index = {row["id"]: row for row in index_rows(comparison.stonebranch)}
    jil_index = {row["id"]: row for row in index_rows(comparison.jil)}
    rows: list[dict[str, str]] = []
    for entry in comparison.entries:
        sb_row = sb_index.get(entry.id, {})
        jil_row = jil_index.get(entry.id, {})
        rows.append(
            {
                "id": entry.id,
                "sides": _sides(entry),
                "topology_hash_sb": str(sb_row.get("topology_hash") or ""),
                "topology_hash_jil": str(jil_row.get("topology_hash") or ""),
                "logic_hash_sb": str(sb_row.get("logic_hash") or ""),
                "logic_hash_jil": str(jil_row.get("logic_hash") or ""),
                "strict_hash_sb": str(sb_row.get("strict_hash") or ""),
                "strict_hash_jil": str(jil_row.get("strict_hash") or ""),
                "status_topology": entry.status_by_level["topology"],
                "status_logic": entry.status_by_level["logic"],
                "status_strict": entry.status_by_level["strict"],
            }
        )
    return rows


def _sides(entry: SkeletonDiffEntry) -> str:
    if entry.sb_line and entry.jil_line:
        return "both"
    if entry.sb_line:
        return "stonebranch"
    return "jil"


def _append_plumbing_section(lines: list[str], comparison: SkeletonComparison) -> None:
    sb_kept = _kept_plumbing_warnings(comparison.stonebranch)
    jil_kept = _kept_plumbing_warnings(comparison.jil)
    lines.extend(
        [
            "",
            "## Plumbing erasure",
            "",
            "| Side | Erased nodes | Kept with warning |",
            "|---|---:|---:|",
            (
                f"| Stonebranch | {len(comparison.stonebranch.erasures)} | "
                f"{len(sb_kept)} |"
            ),
            f"| JIL | {len(comparison.jil.erasures)} | {len(jil_kept)} |",
        ]
    )
    kept = [("Stonebranch", item) for item in sb_kept] + [("JIL", item) for item in jil_kept]
    if kept:
        lines.extend(["", "| Side | Warning |", "|---|---|"])
        for side, warning in kept[:100]:
            lines.append(f"| {side} | {_cell(warning)} |")


def _append_changed_nodes(lines: list[str], comparison: SkeletonComparison) -> None:
    rows = [
        entry for entry in comparison.entries if entry.status_by_level["logic"] == "changed"
    ]
    lines.extend(
        [
            "",
            "## Changed nodes",
            "",
            "| ID | Reasons | Stonebranch trigger | JIL trigger |",
            "|---|---|---|---|",
        ]
    )
    if not rows:
        lines.append("| n/a | No logic-level node changes. |  |  |")
        return
    for entry in rows[:200]:
        lines.append(
            f"| `{entry.id}` | {_cell(', '.join(entry.reasons))} | "
            f"`{_record_value(entry.sb_line, 'trigger')}` | "
            f"`{_record_value(entry.jil_line, 'trigger')}` |"
        )


def _append_qualifier_only(lines: list[str], comparison: SkeletonComparison) -> None:
    rows = _strict_only_entries(comparison)
    lines.extend(
        [
            "",
            "## Qualifier-only differences",
            "",
            "Expected UC gaps: lookback windows, notrunning/terminated, box_success overrides.",
            "",
            "| ID | Reasons | Stonebranch strict line | JIL strict line |",
            "|---|---|---|---|",
        ]
    )
    if not rows:
        lines.append("| n/a | No strict-only differences. |  |  |")
        return
    for entry in rows[:200]:
        lines.append(
            f"| `{entry.id}` | {_cell(', '.join(entry.reasons))} | "
            f"`{_cell(entry.sb_line)}` | `{_cell(entry.jil_line)}` |"
        )


def _append_only_in(lines: list[str], comparison: SkeletonComparison) -> None:
    for status, title in (
        ("only_in_stonebranch", "Only in Stonebranch"),
        ("only_in_jil", "Only in JIL"),
    ):
        rows = [
            entry
            for entry in comparison.entries
            if entry.status_by_level["topology"] == status
        ]
        lines.extend(["", f"## {title}", "", "| ID | Canonical line |", "|---|---|"])
        if not rows:
            lines.append("| n/a | No topology-level missing nodes. |")
            continue
        for entry in rows[:200]:
            line = entry.sb_line if status == "only_in_stonebranch" else entry.jil_line
            lines.append(f"| `{entry.id}` | `{_cell(line)}` |")


def _append_meta_layer(lines: list[str], comparison: SkeletonComparison) -> None:
    command_diffs = comparison.meta.get("command_differences", [])
    lines.extend(
        [
            "",
            "## Meta layer",
            "",
            "Command differences, external references, and warnings are reported here but",
            "are excluded from skeleton identity.",
            "",
            "### Command differences",
            "",
            "| Status | ID | Semantic match | Reason |",
            "|---|---|---:|---|",
        ]
    )
    if not command_diffs:
        lines.append("| n/a | n/a |  | No command differences. |")
    for item in command_diffs[:100]:
        lines.append(
            f"| `{item.get('status', '')}` | `{item.get('key', '')}` | "
            f"{bool(item.get('semantic_match'))} | {_cell(item.get('reason', ''))} |"
        )

    lines.extend(
        [
            "",
            "### External references",
            "",
            f"- Matched external refs: **{len(comparison.externals['matched'])}**",
            f"- Only in Stonebranch: **{len(comparison.externals['only_in_stonebranch'])}**",
            f"- Only in JIL: **{len(comparison.externals['only_in_jil'])}**",
        ]
    )
    _append_warning_list(lines, "Stonebranch warnings", comparison.meta["stonebranch_warnings"])
    _append_warning_list(lines, "JIL warnings", comparison.meta["jil_warnings"])


def _append_id_collisions(lines: list[str], comparison: SkeletonComparison) -> None:
    lines.extend(
        [
            "",
            "## Id collisions",
            "",
            "Two distinct native objects that resolved to the same skeleton id. The second",
            "definition was dropped; unless the id is on the alias `merge` allow-list, this is",
            "an alias/id error and the dropped definition is missing from the comparison.",
            "",
            "| Side | Id | Kept native | Dropped native | Kept source | Dropped source | Status |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    rows = [("Stonebranch", item) for item in comparison.stonebranch.collisions] + [
        ("JIL", item) for item in comparison.jil.collisions
    ]
    if not rows:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | No id collisions detected. |")
        return
    for side, item in rows[:200]:
        status = "info (merge allow-listed)" if item.get("merge_allowed") else "risk"
        lines.append(
            f"| {side} | `{item.get('id', '')}` | {_cell(item.get('kept_native', ''))} | "
            f"{_cell(item.get('dropped_native', ''))} | {_cell(item.get('kept_src', ''))} | "
            f"{_cell(item.get('dropped_src', ''))} | {status} |"
        )


def _append_warning_list(lines: list[str], title: str, warnings: list[str]) -> None:
    lines.extend(["", f"### {title}", ""])
    if not warnings:
        lines.append("- None.")
        return
    lines.extend(f"- {warning}" for warning in warnings[:100])


def _append_risks(lines: list[str], comparison: SkeletonComparison) -> None:
    lines.extend(["", "## Risks", ""])
    if not comparison.risks:
        lines.append("- No critical skeleton risks detected by the current rules.")
        return
    lines.extend(f"- {risk}" for risk in comparison.risks)


def _entries_with_reason(
    comparison: SkeletonComparison, reason: str
) -> list[SkeletonDiffEntry]:
    return [entry for entry in comparison.entries if reason in entry.reasons]


def _strict_only_entries(comparison: SkeletonComparison) -> list[SkeletonDiffEntry]:
    return [
        entry
        for entry in comparison.entries
        if entry.status_by_level["logic"] == "matched"
        and entry.status_by_level["strict"] == "changed"
    ]


def _reason_count(comparison: SkeletonComparison, reason: str) -> int:
    return len(_entries_with_reason(comparison, reason))


def _kept_plumbing_warnings(skeleton: Skeleton) -> list[str]:
    return [warning for warning in skeleton.warnings if "kept plumbing" in warning.lower()]


def _cycle_warnings(skeleton: Skeleton) -> list[str]:
    return [warning for warning in skeleton.warnings if "cycle" in warning.lower()]


def _real_collisions(skeleton: Skeleton) -> list[dict[str, Any]]:
    """Collisions that are not on the alias merge allow-list: a correctness risk."""

    return [item for item in skeleton.collisions if not item.get("merge_allowed")]


def _allowed_collisions(skeleton: Skeleton) -> list[dict[str, Any]]:
    """Collisions downgraded to informational because they are intentional N1 merges."""

    return [item for item in skeleton.collisions if item.get("merge_allowed")]


def _record_value(line: str, key: str) -> str:
    if not line:
        return ""
    return str(json.loads(line).get(key) or "")


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _percent(numerator: int, denominator: int) -> float:
    if not denominator:
        return 100.0
    return round((numerator / denominator) * 100.0, 2)


def _write_json(path: Path, payload: Any) -> None:
    write_text_file(path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
