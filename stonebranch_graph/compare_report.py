from __future__ import annotations

from .comparison_model import Comparison
from .metrics import metric_rows

def write_report(path: Path, comparison: Comparison) -> None:
    s = comparison.summary
    lines = [
        "# Stonebranch vs JIL comparison report", "", "## Summary", "",
        f"- Stonebranch nodes: **{s.get('stonebranch_nodes', 0)}**",
        f"- JIL nodes: **{s.get('jil_nodes', 0)}**",
        f"- Matched nodes: **{s.get('matched_nodes', 0)}**",
        f"- Missing in Stonebranch: **{s.get('missing_in_stonebranch', 0)}**",
        f"- Missing in JIL: **{s.get('missing_in_jil', 0)}**",
        f"- Stonebranch edges: **{s.get('stonebranch_edges', 0)}**",
        f"- JIL edges: **{s.get('jil_edges', 0)}**",
        f"- Matched edges: **{s.get('matched_edges', 0)}**",
        f"- Missing edges in Stonebranch: **{s.get('missing_edges_in_stonebranch', 0)}**",
        f"- Missing edges in JIL: **{s.get('missing_edges_in_jil', 0)}**", "", "## Migration metrics", "",
        f"- Migration readiness score: **{s.get('migration_readiness_score', 0)}/100** (`{s.get('readiness_grade', 'unknown')}`)",
        f"- Node match rate: **{s.get('node_match_rate_percent', 0)}%**",
        f"- Edge match rate: **{s.get('edge_match_rate_percent', 0)}%**",
        f"- Critical dependency loss count: **{s.get('critical_dependency_loss_count', 0)}**",
        f"- Calendar mismatch count: **{s.get('calendar_mismatch_count', 0)}**",
        f"- Agent/machine mismatch count: **{s.get('agent_machine_mismatch_count', 0)}**",
        f"- Command mismatch count: **{s.get('command_mismatch_count', 0)}**",
        f"- Command syntax-only differences: **{s.get('command_syntax_diff_only', 0)}**",
        f"- Node key collisions: **{s.get('stonebranch_key_collision_count', 0) + s.get('jil_key_collision_count', 0)}**",
        f"- Unused mappings: **{s.get('unused_mapping_count', 0)}**", "", "## Critical risks", "",
    ]
    if comparison.risks:
        lines += [f"- {risk}" for risk in comparison.risks]
    else:
        lines.append("- No critical graph risks detected by the current rules.")
    append_collision_section(lines, comparison)
    append_command_normalization_section(lines, comparison)
    lines += ["", "## Missing objects in Stonebranch", "", "| Kind | Object | JIL source |", "|---|---|---|"]
    for item in comparison.nodes.get("missing_in_stonebranch", [])[:200]:
        lines.append(f"| {item['kind']} | `{item['name']}` | `{item['source_file']}` |")
    lines += ["", "## Missing objects in JIL", "", "| Kind | Object | Stonebranch source |", "|---|---|---|"]
    for item in comparison.nodes.get("missing_in_jil", [])[:200]:
        lines.append(f"| {item['kind']} | `{item['name']}` | `{item['source_file']}` |")
    lines += ["", "## Missing dependencies in Stonebranch", "", "| Relation | Source | Target | Evidence |", "|---|---|---|---|"]
    for item in comparison.edges.get("missing_in_stonebranch", [])[:200]:
        lines.append(f"| {item['relation']} | `{item['source'].get('name', item['source'].get('id'))}` | `{item['target'].get('name', item['target'].get('id'))}` | `{item['evidence_file']}` |")
    lines += ["", "## Missing dependencies in JIL", "", "| Relation | Source | Target | Evidence |", "|---|---|---|---|"]
    for item in comparison.edges.get("missing_in_jil", [])[:200]:
        lines.append(f"| {item['relation']} | `{item['source'].get('name', item['source'].get('id'))}` | `{item['target'].get('name', item['target'].get('id'))}` | `{item['evidence_file']}` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_command_normalization_section(lines: list[str], comparison: Comparison) -> None:
    items = comparison.attributes.get("command_differences", [])
    if not items:
        return
    lines += [
        "",
        "## Command normalization diagnostics",
        "",
        "| Status | Object | Reasons | Variables | Env tokens | Scripts |",
        "|---|---|---|---|---|---|",
    ]
    for item in items[:100]:
        reasons = ", ".join(item.get("normalization_reasons", [])) or "n/a"
        variables = ", ".join(item.get("variable_names", [])) or "n/a"
        env_tokens = ", ".join(item.get("env_tokens", [])) or "n/a"
        scripts = ", ".join(item.get("script_basenames", [])) or "n/a"
        lines.append(
            f"| `{item.get('status', '')}` | `{item.get('stonebranch', '')}` / `{item.get('jil', '')}` "
            f"| {reasons} | {variables} | {env_tokens} | {scripts} |"
        )


def append_collision_section(lines: list[str], comparison: Comparison) -> None:
    collisions: list[tuple[str, dict[str, Any]]] = []
    for section in ("stonebranch_key_collisions", "jil_key_collisions"):
        for item in comparison.diagnostics.get(section, []):
            collisions.append((section, item))
    if not collisions:
        return
    lines += ["", "## Normalized key collisions", "", "| Side | Key | Reason | Objects |", "|---|---|---|---|"]
    for section, item in collisions[:100]:
        side = "Stonebranch" if section.startswith("stonebranch") else "JIL"
        names = ", ".join(f"`{name}`" for name in item.get("names", []))
        lines.append(f"| {side} | `{item.get('key', '')}` | `{item.get('reason', 'normalized_key_collision')}` | {names} |")
