from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Kind tokens that can appear as the leading segment(s) of a reconciliation
# key ("kind:name" for the common single-env export, or "env:kind:name" when
# a graph mixes more than one env label -- see `exporters.build_reconciliation_ids`).
# Mirrors the canonical comparison kinds produced by `core.comparison_kind`
# plus the raw kinds they collapse from, so a keys.json built by an older
# export (or hand-edited) still parses correctly.
KNOWN_KEY_KINDS = {
    "agent",
    "agent_cluster",
    "box",
    "calendar",
    "file",
    "file_watcher",
    "object",
    "task",
    "variable",
    "workflow",
}

UNKNOWN_KIND = "unknown"


def parse_key(key: str) -> tuple[str, str, str | None]:
    """Split a reconciliation key into (kind, name, env).

    Handles both export shapes written by `export_reconciliation_keys`: the
    common single-env `kind:name` and the multi-env `env:kind:name` (emitted
    only when a graph mixes more than one env label). `env` is `None` for the
    common single-env shape. Falls back to treating the first `:`-separated
    segment as the kind if it isn't a recognized kind token, so unexpected
    input still parses instead of raising.
    """
    parts = key.split(":")
    if len(parts) >= 2 and parts[0] in KNOWN_KEY_KINDS:
        return parts[0], ":".join(parts[1:]), None
    if len(parts) >= 3 and parts[1] in KNOWN_KEY_KINDS:
        return parts[1], ":".join(parts[2:]), parts[0]
    if len(parts) >= 2:
        return parts[0], ":".join(parts[1:]), None
    return UNKNOWN_KIND, key, None


def load_keys_file(path: Path) -> list[str]:
    """Load a `*.keys.json` file: a flat JSON array of plain ID strings."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise ValueError(f"{path} is not a flat JSON array of strings (unexpected keys.json shape)")
    return data


@dataclass(frozen=True)
class KeysCompareStats:
    kind: str
    stonebranch_total: int
    jil_total: int
    matched: int
    only_in_stonebranch: int
    only_in_jil: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "stonebranch_total": self.stonebranch_total,
            "jil_total": self.jil_total,
            "matched": self.matched,
            "only_in_stonebranch": self.only_in_stonebranch,
            "only_in_jil": self.only_in_jil,
        }


@dataclass(frozen=True)
class KeysComparison:
    stonebranch_path: Path
    jil_path: Path
    stonebranch_keys: list[str]
    jil_keys: list[str]
    matched: list[str]
    only_in_stonebranch: list[str]
    only_in_jil: list[str]
    by_kind: list[KeysCompareStats]
    generated_at: str

    @property
    def summary(self) -> dict[str, Any]:
        sb_total = len(self.stonebranch_keys)
        jil_total = len(self.jil_keys)
        union_total = len(set(self.stonebranch_keys) | set(self.jil_keys))
        matched_total = len(self.matched)
        match_rate = round(matched_total / union_total * 100, 2) if union_total else 0.0
        return {
            "stonebranch_keys_total": sb_total,
            "jil_keys_total": jil_total,
            "union_total": union_total,
            "matched_total": matched_total,
            "only_in_stonebranch_total": len(self.only_in_stonebranch),
            "only_in_jil_total": len(self.only_in_jil),
            "match_rate_percent": match_rate,
        }


def _kind_of(key: str) -> str:
    kind, _name, _env = parse_key(key)
    return kind


def compare_keys(
    stonebranch_keys: list[str],
    jil_keys: list[str],
    *,
    stonebranch_path: Path | None = None,
    jil_path: Path | None = None,
) -> KeysComparison:
    """Diff two reconciliation key lists and compute per-kind statistics."""
    sb_set = set(stonebranch_keys)
    jil_set = set(jil_keys)

    matched = sorted(sb_set & jil_set)
    only_sb = sorted(sb_set - jil_set)
    only_jil = sorted(jil_set - sb_set)

    kinds = sorted({_kind_of(key) for key in (sb_set | jil_set)})
    by_kind: list[KeysCompareStats] = []
    for kind in kinds:
        sb_kind = {key for key in sb_set if _kind_of(key) == kind}
        jil_kind = {key for key in jil_set if _kind_of(key) == kind}
        by_kind.append(
            KeysCompareStats(
                kind=kind,
                stonebranch_total=len(sb_kind),
                jil_total=len(jil_kind),
                matched=len(sb_kind & jil_kind),
                only_in_stonebranch=len(sb_kind - jil_kind),
                only_in_jil=len(jil_kind - sb_kind),
            )
        )

    return KeysComparison(
        stonebranch_path=stonebranch_path or Path("stonebranch.keys.json"),
        jil_path=jil_path or Path("autosys.keys.json"),
        stonebranch_keys=sorted(sb_set),
        jil_keys=sorted(jil_set),
        matched=matched,
        only_in_stonebranch=only_sb,
        only_in_jil=only_jil,
        by_kind=by_kind,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )


def compare_keys_files(stonebranch_path: Path, jil_path: Path) -> KeysComparison:
    """Read the two `*.keys.json` files and diff them. See `compare_keys`."""
    sb_keys = load_keys_file(stonebranch_path)
    jil_keys = load_keys_file(jil_path)
    return compare_keys(sb_keys, jil_keys, stonebranch_path=stonebranch_path, jil_path=jil_path)


def export_keys_comparison_json(comparison: KeysComparison, path: Path) -> None:
    payload = {
        "generated_at": comparison.generated_at,
        "stonebranch_source": str(comparison.stonebranch_path),
        "jil_source": str(comparison.jil_path),
        "summary": comparison.summary,
        "by_kind": [stats.as_dict() for stats in comparison.by_kind],
        "matched": comparison.matched,
        "only_in_stonebranch": comparison.only_in_stonebranch,
        "only_in_jil": comparison.only_in_jil,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


# Cap the number of individual object names listed per kind-section in the
# Markdown report so a very large one-sided drift doesn't produce an
# unreadable multi-thousand-line document; the JSON report always carries
# the full lists for tooling/further processing.
MAX_LISTED_OBJECTS_PER_KIND = 500


def _grouped_object_lines(keys: list[str]) -> list[str]:
    if not keys:
        return ["_None -- every object on this side has a twin on the other side._", ""]
    grouped: dict[str, list[str]] = {}
    for key in keys:
        kind, name, env = parse_key(key)
        grouped.setdefault(kind, []).append(f"{env + ':' if env else ''}{name}")
    lines: list[str] = []
    for kind in sorted(grouped):
        names = sorted(grouped[kind])
        lines.append(f"### {kind} ({len(names)})")
        lines.append("")
        shown = names[:MAX_LISTED_OBJECTS_PER_KIND]
        for name in shown:
            lines.append(f"- `{name}`")
        if len(names) > MAX_LISTED_OBJECTS_PER_KIND:
            lines.append(f"- _...and {len(names) - MAX_LISTED_OBJECTS_PER_KIND} more (see the JSON report for the full list)._")
        lines.append("")
    return lines


def export_keys_comparison_markdown(comparison: KeysComparison, path: Path) -> None:
    s = comparison.summary
    lines: list[str] = [
        "# Reconciliation keys comparison report",
        "",
        f"Generated: {comparison.generated_at}",
        "",
        f"- Stonebranch keys file: `{comparison.stonebranch_path}`",
        f"- AutoSys keys file: `{comparison.jil_path}`",
        "",
        "## Overall statistics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Stonebranch objects | {s['stonebranch_keys_total']} |",
        f"| AutoSys objects | {s['jil_keys_total']} |",
        f"| Union (distinct objects across both systems) | {s['union_total']} |",
        f"| Matched (present in both systems) | {s['matched_total']} |",
        f"| Only in Stonebranch | {s['only_in_stonebranch_total']} |",
        f"| Only in AutoSys | {s['only_in_jil_total']} |",
        f"| Match rate | {s['match_rate_percent']}% |",
        "",
        "## Breakdown by object type",
        "",
        "| Kind | Stonebranch | AutoSys | Matched | Only in Stonebranch | Only in AutoSys |",
        "|---|---|---|---|---|---|",
    ]
    for stats in comparison.by_kind:
        lines.append(
            f"| {stats.kind} | {stats.stonebranch_total} | {stats.jil_total} | "
            f"{stats.matched} | {stats.only_in_stonebranch} | {stats.only_in_jil} |"
        )
    lines += ["", "## Objects only in Stonebranch", ""]
    lines += _grouped_object_lines(comparison.only_in_stonebranch)
    lines += ["## Objects only in AutoSys", ""]
    lines += _grouped_object_lines(comparison.only_in_jil)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
