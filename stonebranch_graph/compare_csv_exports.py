from __future__ import annotations

from .comparison_model import Comparison
from .exporters import export_csv_rows

def write_missing_csvs(compare_dir: Path, comparison: Comparison) -> None:
    node_fields = ["id", "canonical_key", "source_system", "env", "kind", "native_kind", "name", "source_file"]
    export_csv_rows(compare_dir / "missing-in-stonebranch.csv", node_fields, comparison.nodes.get("missing_in_stonebranch", []))
    export_csv_rows(compare_dir / "missing-in-jil.csv", node_fields, comparison.nodes.get("missing_in_jil", []))


def write_edge_diff_csv(compare_dir: Path, comparison: Comparison) -> None:
    rows = []
    for side in ("missing_in_stonebranch", "missing_in_jil"):
        for item in comparison.edges.get(side, []):
            rows.append({
                "side": side,
                "relation": item["relation"],
                "source": item.get("source_key") or item["source"].get("canonical_key", item["source"].get("id")),
                "target": item.get("target_key") or item["target"].get("canonical_key", item["target"].get("id")),
                "evidence_file": item.get("evidence_file", ""),
                "evidence_key": item.get("evidence_key", ""),
                "evidence_value": item.get("evidence_value", ""),
            })
    export_csv_rows(compare_dir / "edge-diff.csv", ["side", "relation", "source", "target", "evidence_file", "evidence_key", "evidence_value"], rows)


def write_command_diff_csv(compare_dir: Path, comparison: Comparison) -> None:
    fields = [
        "status",
        "key",
        "stonebranch",
        "jil",
        "strict_match",
        "semantic_match",
        "normalization_reasons",
        "variable_names",
        "env_tokens",
        "script_basenames",
        "stonebranch_command_hash",
        "jil_command_hash",
        "stonebranch_semantic_command_hash",
        "jil_semantic_command_hash",
        "stonebranch_semantic_preview",
        "jil_semantic_preview",
        "semantic_preview_truncated",
        "reason",
    ]
    rows = []
    for item in comparison.attributes.get("command_differences", []):
        sb_norm = item.get("stonebranch_command_normalization", {})
        jil_norm = item.get("jil_command_normalization", {})
        if not isinstance(sb_norm, dict):
            sb_norm = {}
        if not isinstance(jil_norm, dict):
            jil_norm = {}
        rows.append({
            "status": item.get("status", ""),
            "key": item.get("key", ""),
            "stonebranch": item.get("stonebranch", ""),
            "jil": item.get("jil", ""),
            "strict_match": str(bool(item.get("strict_match", False))).lower(),
            "semantic_match": str(bool(item.get("semantic_match", False))).lower(),
            "normalization_reasons": ";".join(item.get("normalization_reasons", [])),
            "variable_names": ";".join(item.get("variable_names", [])),
            "env_tokens": ";".join(item.get("env_tokens", [])),
            "script_basenames": ";".join(item.get("script_basenames", [])),
            "stonebranch_command_hash": item.get("stonebranch_command_hash", ""),
            "jil_command_hash": item.get("jil_command_hash", ""),
            "stonebranch_semantic_command_hash": item.get("stonebranch_semantic_command_hash", ""),
            "jil_semantic_command_hash": item.get("jil_semantic_command_hash", ""),
            "stonebranch_semantic_preview": sb_norm.get("semantic_preview", ""),
            "jil_semantic_preview": jil_norm.get("semantic_preview", ""),
            "semantic_preview_truncated": str(bool(sb_norm.get("semantic_preview_truncated") or jil_norm.get("semantic_preview_truncated"))).lower(),
            "reason": item.get("reason", ""),
        })
    export_csv_rows(compare_dir / "command-diff.csv", fields, rows)


def write_diagnostics_csv(compare_dir: Path, comparison: Comparison) -> None:
    collision_rows = []
    for section in ("stonebranch_key_collisions", "jil_key_collisions"):
        for item in comparison.diagnostics.get(section, []):
            collision_rows.append({
                "section": section,
                "key": item["key"],
                "reason": item.get("reason", "normalized_key_collision"),
                "count": item.get("count", len(item.get("nodes", []))),
                "names": ";".join(item.get("names", [])),
                "business_codes": ";".join(item.get("business_codes", [])),
                "env_tokens": ";".join(item.get("env_tokens", [])),
                "real_names": ";".join(item.get("real_names", [])),
                "objects": ";".join(n.get("id", "") for n in item.get("nodes", [])),
                "source_files": ";".join(sorted({n.get("source_file", "") for n in item.get("nodes", []) if n.get("source_file")})),
            })
    export_csv_rows(
        compare_dir / "collisions.csv",
        [
            "section",
            "key",
            "reason",
            "count",
            "names",
            "business_codes",
            "env_tokens",
            "real_names",
            "objects",
            "source_files",
        ],
        collision_rows,
    )
    export_csv_rows(compare_dir / "mapping-diagnostics.csv", ["stonebranch", "jil"], comparison.diagnostics.get("unused_mappings", []))
