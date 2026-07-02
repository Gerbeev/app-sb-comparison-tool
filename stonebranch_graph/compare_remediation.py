from __future__ import annotations

from pathlib import Path

from .comparison_model import Comparison
from .compare_payloads import count_command_differences_by_status
from .exporters import write_json

def write_remediation_plan(compare_dir: Path, comparison: Comparison) -> None:
    lines = [
        "# Remediation plan",
        "",
        "Use this file as a working checklist for closing migration gaps.",
        "",
        "## 1. Missing objects in Stonebranch",
        "",
    ]
    for item in comparison.nodes.get("missing_in_stonebranch", [])[:500]:
        lines.append(f"- [ ] Create or map `{item.get('kind')}` `{item.get('name')}` from JIL source `{item.get('source_file')}`.")

    lines.extend(["", "## 2. Missing objects in JIL", ""])
    for item in comparison.nodes.get("missing_in_jil", [])[:500]:
        lines.append(f"- [ ] Review Stonebranch-only `{item.get('kind')}` `{item.get('name')}` from `{item.get('source_file')}`.")

    lines.extend(["", "## 3. Missing dependencies in Stonebranch", ""])
    for edge in comparison.edges.get("missing_in_stonebranch", [])[:500]:
        source = edge.get("source", {})
        target = edge.get("target", {})
        lines.append(
            f"- [ ] Add/check `{edge.get('relation')}` from `{source.get('name', source.get('id'))}` "
            f"to `{target.get('name', target.get('id'))}`. Evidence: `{edge.get('evidence_file')}`."
        )

    lines.extend(["", "## 4. Missing dependencies in JIL / extra Stonebranch behavior", ""])
    for edge in comparison.edges.get("missing_in_jil", [])[:500]:
        source = edge.get("source", {})
        target = edge.get("target", {})
        lines.append(
            f"- [ ] Review Stonebranch `{edge.get('relation')}` from `{source.get('name', source.get('id'))}` "
            f"to `{target.get('name', target.get('id'))}`. Evidence: `{edge.get('evidence_file')}`."
        )

    lines.extend(["", "## 5. Command differences", ""])
    for item in comparison.attributes.get("command_differences", [])[:500]:
        status = item.get("status", "command_semantic_mismatch")
        if status == "command_syntax_diff_only":
            reasons = ", ".join(item.get("normalization_reasons", [])) or "command syntax"
            lines.append(
                f"- [ ] Review variable/environment/script-path syntax mapping for `{item.get('stonebranch')}` / `{item.get('jil')}`. Reasons: {reasons}."
            )
        else:
            lines.append(f"- [ ] Compare semantic command behavior for `{item.get('stonebranch')}` / `{item.get('jil')}`.")

    lines.extend(["", "## 6. Condition differences", ""])
    for item in comparison.attributes.get("condition_differences", [])[:500]:
        lines.append(f"- [ ] Compare condition for `{item.get('key')}`.")

    write_json(compare_dir / "remediation-summary.json", {
        "missing_in_stonebranch": len(comparison.nodes.get("missing_in_stonebranch", [])),
        "missing_in_jil": len(comparison.nodes.get("missing_in_jil", [])),
        "missing_edges_in_stonebranch": len(comparison.edges.get("missing_in_stonebranch", [])),
        "missing_edges_in_jil": len(comparison.edges.get("missing_in_jil", [])),
        "command_differences": len(comparison.attributes.get("command_differences", [])),
        "command_syntax_diff_only": count_command_differences_by_status(comparison.attributes, "command_syntax_diff_only"),
        "command_semantic_mismatches": count_command_differences_by_status(comparison.attributes, "command_semantic_mismatch"),
        "condition_differences": len(comparison.attributes.get("condition_differences", [])),
    })
    (compare_dir / "remediation-plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
