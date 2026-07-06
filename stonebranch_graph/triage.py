from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .domain import PACK_CRITICAL_RELATIONS
from .exporters import export_csv_rows, write_json, write_text_file

TRIAGE_FIELDS = [
    "severity",
    "category",
    "status",
    "side",
    "relation",
    "key",
    "object",
    "source",
    "target",
    "review_file",
    "reason",
    "details",
]

TRIAGE_OUTPUT_FILES = ["triage-report.md", "triage-findings.csv", "triage-summary.json"]


@dataclass(frozen=True)
class TriageResult:
    compare_dir: Path
    output_dir: Path
    summary: dict[str, Any]
    files: list[Path]


@dataclass(frozen=True)
class TriageFinding:
    severity: str
    category: str
    status: str
    side: str = ""
    relation: str = ""
    key: str = ""
    object: str = ""
    source: str = ""
    target: str = ""
    review_file: str = ""
    reason: str = ""
    details: str = ""

    def to_row(self) -> dict[str, str]:
        return {field: str(getattr(self, field)) for field in TRIAGE_FIELDS}


def create_triage_report(compare_output: Path, output_dir: Path | None = None) -> TriageResult:
    compare_dir = resolve_compare_dir(compare_output)
    output = output_dir or compare_dir
    output.mkdir(parents=True, exist_ok=True)

    comparison = load_json_file(compare_json_path(compare_dir, "comparison.json"))
    metrics = load_json_file(compare_json_path(compare_dir, "metrics.json"))
    findings = collect_triage_findings(compare_dir, comparison, metrics)
    summary = build_triage_summary(findings, comparison, metrics)

    write_json(output / "triage-summary.json", summary)
    export_csv_rows(output / "triage-findings.csv", TRIAGE_FIELDS, (finding.to_row() for finding in findings))
    write_text_file(output / "triage-report.md", render_triage_report(findings, summary))
    return TriageResult(compare_dir=compare_dir, output_dir=output, summary=summary, files=[output / name for name in TRIAGE_OUTPUT_FILES])


def resolve_compare_dir(path: Path) -> Path:
    candidates = [path, path / "compare"]
    for candidate in candidates:
        if (candidate / "json" / "comparison.json").exists() or (candidate / "comparison.json").exists():
            return candidate
    raise FileNotFoundError(f"No compare/json/comparison.json or comparison.json found under: {path}")


def compare_json_path(compare_dir: Path, name: str) -> Path:
    current = compare_dir / "json" / name
    if current.exists():
        return current
    return compare_dir / name


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def collect_triage_findings(compare_dir: Path, comparison: dict[str, Any], metrics: dict[str, Any]) -> list[TriageFinding]:
    findings: list[TriageFinding] = []
    findings.extend(collision_findings(comparison))
    findings.extend(edge_gap_findings(comparison))
    findings.extend(object_gap_findings(comparison))
    findings.extend(command_findings(comparison))
    findings.extend(condition_findings(comparison))
    findings.extend(mapping_findings(comparison))
    findings.extend(log_findings(compare_dir))
    findings.extend(readiness_findings(metrics or comparison.get("summary", {})))
    return sorted(findings, key=finding_sort_key)


def finding_sort_key(finding: TriageFinding) -> tuple[int, str, str, str, str]:
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    return (
        severity_order.get(finding.severity, 9),
        finding.category,
        finding.side,
        finding.key,
        finding.object,
    )


def comparison_section(comparison: dict[str, Any], section: str) -> dict[str, list[dict[str, Any]]]:
    payload = comparison.get(section, {})
    return payload if isinstance(payload, dict) else {}


def list_section(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key, [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def collision_findings(comparison: dict[str, Any]) -> list[TriageFinding]:
    diagnostics = comparison_section(comparison, "diagnostics")
    findings: list[TriageFinding] = []
    for section, side in (("stonebranch_key_collisions", "stonebranch"), ("jil_key_collisions", "jil")):
        for item in list_section(diagnostics, section):
            reason = str(item.get("reason", "normalized_key_collision"))
            category = "enterprise_naming_collision" if reason == "enterprise_name_collision" else "normalized_key_collision"
            names = join_values(item.get("names"))
            business_codes = join_values(item.get("business_codes"))
            env_tokens = join_values(item.get("env_tokens"))
            findings.append(
                TriageFinding(
                    severity="high",
                    category=category,
                    status="manual_mapping_required",
                    side=side,
                    key=str(item.get("key", "")),
                    object=names,
                    review_file="compare/csv/collisions.csv",
                    reason=reason,
                    details=compact_details({"business_codes": business_codes, "env_tokens": env_tokens}),
                )
            )
    return findings


def edge_gap_findings(comparison: dict[str, Any]) -> list[TriageFinding]:
    edges = comparison_section(comparison, "edges")
    findings: list[TriageFinding] = []
    for section, side, status in (
        ("missing_in_stonebranch", "missing_in_stonebranch", "possible_lost_migration_behavior"),
        ("missing_in_jil", "missing_in_jil", "stonebranch_extra_or_new_behavior"),
    ):
        for edge in list_section(edges, section):
            relation = str(edge.get("relation", ""))
            critical = relation in PACK_CRITICAL_RELATIONS
            category = "critical_edge_gap" if critical else "edge_gap"
            severity = "high" if critical else "medium"
            findings.append(
                TriageFinding(
                    severity=severity,
                    category=category,
                    status=status,
                    side=side,
                    relation=relation,
                    key=str(edge.get("key", "")),
                    source=node_label(edge.get("source")),
                    target=node_label(edge.get("target")),
                    review_file="compare/csv/edge-diff.csv",
                    reason="Missing normalized edge in comparison.",
                    details=compact_details({"evidence_file": edge.get("evidence_file", ""), "evidence_key": edge.get("evidence_key", "")}),
                )
            )
    return findings


def object_gap_findings(comparison: dict[str, Any]) -> list[TriageFinding]:
    nodes = comparison_section(comparison, "nodes")
    findings: list[TriageFinding] = []
    for section, side, review_file in (
        ("missing_in_stonebranch", "missing_in_stonebranch", "compare/csv/missing-in-stonebranch.csv"),
        ("missing_in_jil", "missing_in_jil", "compare/csv/missing-in-jil.csv"),
    ):
        for item in list_section(nodes, section):
            findings.append(
                TriageFinding(
                    severity="medium",
                    category="object_gap",
                    status="map_create_or_confirm_retired",
                    side=side,
                    key=str(item.get("canonical_key", "")),
                    object=str(item.get("name", "")),
                    review_file=review_file,
                    reason="Object exists on one side only after normalized matching.",
                    details=compact_details({"kind": item.get("kind", ""), "source_file": item.get("source_file", "")}),
                )
            )
    return findings


def command_findings(comparison: dict[str, Any]) -> list[TriageFinding]:
    attributes = comparison_section(comparison, "attributes")
    findings: list[TriageFinding] = []
    for item in list_section(attributes, "command_differences"):
        status = str(item.get("status", "command_semantic_mismatch"))
        syntax_only = status == "command_syntax_diff_only"
        findings.append(
            TriageFinding(
                severity="low" if syntax_only else "high",
                category="command_syntax_mapping" if syntax_only else "command_semantic_mismatch",
                status="syntax_mapping_review" if syntax_only else "real_command_review_required",
                key=str(item.get("key", "")),
                object=f"{item.get('stonebranch', '')} / {item.get('jil', '')}",
                review_file="compare/csv/command-diff.csv",
                reason=str(item.get("reason", "")),
                details=compact_details(
                    {
                        "normalization_reasons": join_values(item.get("normalization_reasons")),
                        "variables": join_values(item.get("variable_names")),
                        "env_tokens": join_values(item.get("env_tokens")),
                        "scripts": join_values(item.get("script_basenames")),
                    }
                ),
            )
        )
    return findings


def condition_findings(comparison: dict[str, Any]) -> list[TriageFinding]:
    attributes = comparison_section(comparison, "attributes")
    return [
        TriageFinding(
            severity="high",
            category="condition_mismatch",
            status="condition_logic_review_required",
            key=str(item.get("key", "")),
            review_file="compare/json/comparison.json",
            reason="Matched objects have different condition hashes.",
        )
        for item in list_section(attributes, "condition_differences")
    ]


def mapping_findings(comparison: dict[str, Any]) -> list[TriageFinding]:
    diagnostics = comparison_section(comparison, "diagnostics")
    return [
        TriageFinding(
            severity="medium",
            category="mapping_rule_issue",
            status="unused_mapping_review",
            key=str(item.get("from", item.get("key", ""))),
            object=str(item.get("to", "")),
            review_file="compare/csv/mapping-diagnostics.csv",
            reason="Manual mapping rule was not used during comparison.",
        )
        for item in list_section(diagnostics, "unused_mappings")
    ]


def log_findings(compare_dir: Path) -> list[TriageFinding]:
    log_path = compare_dir.parent / "run.log" if compare_dir.name == "compare" else compare_dir / "run.log"
    if not log_path.exists():
        return []
    findings: list[TriageFinding] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "[ERROR]" in line:
            findings.append(
                TriageFinding(
                    severity="critical",
                    category="workflow_error",
                    status="fix_before_trusting_reports",
                    review_file="run.log",
                    reason="Workflow error was logged.",
                    details=strip_log_prefix(line),
                )
            )
        elif "[WARNING]" in line:
            findings.append(
                TriageFinding(
                    severity="medium",
                    category="parser_or_comparison_warning",
                    status="warning_review",
                    review_file="run.log",
                    reason="Warning was logged during dry run.",
                    details=strip_log_prefix(line),
                )
            )
    return findings


def readiness_findings(metrics: dict[str, Any]) -> list[TriageFinding]:
    score = int(metrics.get("migration_readiness_score", 100) or 0)
    if score >= 70:
        return []
    return [
        TriageFinding(
            severity="high",
            category="readiness_score",
            status="baseline_not_ready",
            review_file="compare/json/metrics.json",
            reason=f"Migration readiness score is below 70: {score}/100.",
        )
    ]


def build_triage_summary(findings: list[TriageFinding], comparison: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    by_category = Counter(finding.category for finding in findings)
    by_severity = Counter(finding.severity for finding in findings)
    high_priority = [finding for finding in findings if finding.severity in {"critical", "high"}]
    return {
        "finding_count": len(findings),
        "high_priority_count": len(high_priority),
        "by_category": dict(sorted(by_category.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "migration_readiness_score": metrics.get("migration_readiness_score", comparison.get("summary", {}).get("migration_readiness_score")),
        "readiness_grade": metrics.get("readiness_grade", comparison.get("summary", {}).get("readiness_grade")),
        "next_review_order": next_review_order(findings),
    }


def next_review_order(findings: list[TriageFinding]) -> list[str]:
    categories = {finding.category for finding in findings}
    order = [
        ("enterprise_naming_collision", "Review collisions.csv and create/adjust manual mappings before trusting match rates."),
        ("normalized_key_collision", "Review normalized-key collisions before trusting missing-object counts."),
        ("critical_edge_gap", "Review critical edge gaps in edge-diff.csv."),
        ("command_semantic_mismatch", "Review real command mismatches in command-diff.csv."),
        ("condition_mismatch", "Review condition hash mismatches."),
        ("object_gap", "Review object gaps after collisions and critical edges are understood."),
        ("command_syntax_mapping", "Review syntax-only command differences as variable/env/script-path mapping checks."),
        ("parser_or_comparison_warning", "Review run.log warnings for parser/matching improvements."),
    ]
    return [message for category, message in order if category in categories] or ["No triage findings were generated from the available comparison outputs."]


def render_triage_report(findings: list[TriageFinding], summary: dict[str, Any]) -> str:
    lines = [
        "# Dry-run findings triage",
        "",
        "This report classifies comparison outputs into review categories. It does not decide whether a gap is a real migration issue; it tells you what to inspect first.",
        "",
        "## Summary",
        "",
        f"- Findings: **{summary.get('finding_count', 0)}**",
        f"- High priority: **{summary.get('high_priority_count', 0)}**",
        f"- Migration readiness score: **{summary.get('migration_readiness_score', 'n/a')}**",
        f"- Readiness grade: **{summary.get('readiness_grade', 'n/a')}**",
        "",
        "## Recommended review order",
        "",
    ]
    lines.extend(f"{idx}) {item}" for idx, item in enumerate(summary.get("next_review_order", []), start=1))
    lines.extend(["", "## Counts by category", "", "| Category | Count |", "|---|---:|"])
    for category, count in summary.get("by_category", {}).items():
        lines.append(f"| `{category}` | {count} |")
    lines.extend(["", "## High-priority findings", "", "| Severity | Category | Status | Object/Key | Review file | Reason |", "|---|---|---|---|---|---|"])
    for finding in [item for item in findings if item.severity in {"critical", "high"}][:200]:
        label = finding.object or finding.key or f"{finding.source} -> {finding.target}"
        lines.append(
            f"| `{finding.severity}` | `{finding.category}` | `{finding.status}` | `{escape_table(label)}` | `{finding.review_file}` | {escape_table(finding.reason)} |"
        )
    lines.extend(["", "## Full export", "", "Use `triage-findings.csv` for filtering all findings in Excel.", ""])
    return "\n".join(lines)


def join_values(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return ";".join(str(item) for item in value if str(item))


def compact_details(values: dict[str, Any]) -> str:
    parts = [f"{key}={value}" for key, value in values.items() if value not in (None, "", [])]
    return "; ".join(parts)


def node_label(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("name") or value.get("canonical_key") or value.get("id") or "")


def strip_log_prefix(line: str) -> str:
    return re.sub(r"^\S+\s+\[(INFO|WARNING|ERROR)\]\s*", "", line).strip()


def escape_table(value: str) -> str:
    return str(value).replace("|", "\\|")
