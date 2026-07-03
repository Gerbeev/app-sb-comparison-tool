from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import SECRET_KEYWORDS, AnalyzerConfig
from .utils import read_text_file

JIL_EXTENSIONS = {".jil", ".txt", ".job", ".autosys"}
ATTR_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*:")
JOB_START_RE = re.compile(r"^\s*(insert_job|update_job|delete_job)\s*:", re.IGNORECASE)


@dataclass
class FieldStats:
    count: int = 0
    types: Counter[str] = field(default_factory=Counter)
    example_files: set[str] = field(default_factory=set)


def profile_stonebranch(input_path: Path, output_dir: Path, config: AnalyzerConfig) -> None:
    files = load_json_files(input_path, config)
    by_kind: dict[str, dict[str, FieldStats]] = defaultdict(dict)
    for file, relative, data in files:
        kind = kind_from_path(file, config) or "unknown"
        walk_json_schema(data, "$", relative, by_kind[kind])
    write_schema_profile(by_kind, output_dir / "schema-profile.md")
    write_schema_csv(by_kind, output_dir / "schema-profile.csv")


def profile_jil(input_path: Path, output_dir: Path) -> None:
    files = load_jil_files(input_path)
    stats: dict[str, FieldStats] = {}
    file_count = 0
    job_count = 0
    for _file, relative, text in files:
        file_count += 1
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "//", "/*")):
                continue
            if JOB_START_RE.match(stripped):
                job_count += 1
                touch(stats, "$.job_statement", "statement", relative)
                continue
            m = ATTR_RE.match(stripped)
            if m:
                key = m.group("key").lower()
                if is_secret_key(key):
                    touch(stats, f"$.{key}", "secret_redacted", relative)
                else:
                    touch(stats, f"$.{key}", "attribute", relative)
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# AutoSys JIL schema profile",
        "",
        "This report contains attribute names, counts, and example file names only. It does not include values.",
        "",
        "## Summary",
        "",
        f"- Files: **{file_count}**",
        f"- Job statements: **{job_count}**",
        "",
        "## Fields",
        "",
        "| Field | Count | Types | Example files |",
        "|---|---:|---|---|",
    ]
    for field_name, s in sorted(stats.items(), key=lambda x: (-x[1].count, x[0])):
        types = ", ".join(f"{k}:{v}" for k, v in s.types.most_common())
        examples = ", ".join(sorted(s.example_files)[:3])
        lines.append(f"| `{field_name}` | {s.count} | {types} | `{examples}` |")
    (output_dir / "schema-profile.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (output_dir / "schema-profile.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["field", "count", "types", "example_files"])
        writer.writeheader()
        for field_name, s in sorted(stats.items()):
            writer.writerow({
                "field": field_name,
                "count": s.count,
                "types": ";".join(f"{k}:{v}" for k, v in s.types.most_common()),
                "example_files": ";".join(sorted(s.example_files)[:5]),
            })


def load_json_files(input_path: Path, config: AnalyzerConfig) -> list[tuple[Path, str, Any]]:
    if input_path.is_file():
        files = [input_path]
        root = input_path.parent
    else:
        root = input_path
        ignored = set(config.ignored_filenames)
        files = sorted(p for p in input_path.rglob("*.json") if p.name not in ignored and not p.name.startswith("."))
    loaded = []
    for file in files:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            data = json.loads(file.read_text(encoding="utf-8-sig"))
        loaded.append((file, str(file.relative_to(root)) if file.is_relative_to(root) else str(file), data))
    return loaded


def load_jil_files(input_path: Path) -> list[tuple[Path, str, str]]:
    if input_path.is_file():
        files = [input_path]
        root = input_path.parent
    else:
        root = input_path
        files = sorted(p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() in JIL_EXTENSIONS)
    return [(file, str(file.relative_to(root)) if file.is_relative_to(root) else str(file), read_text_file(file)) for file in files]


def kind_from_path(path: Path, config: AnalyzerConfig) -> str | None:
    mapping = config.folder_kind_map or {}
    for part in reversed(path.parts[:-1]):
        kind = mapping.get(part.lower())
        if kind:
            return kind
    return None


def walk_json_schema(value: Any, prefix: str, source: str, bucket: dict[str, FieldStats]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{prefix}.{key_text}"
            touch(bucket, child_path, type_name(child), source)
            if is_secret_key(key_text):
                continue
            walk_json_schema(child, child_path, source, bucket)
    elif isinstance(value, list):
        for child in value:
            child_path = f"{prefix}[]"
            touch(bucket, child_path, type_name(child), source)
            walk_json_schema(child, child_path, source, bucket)


def touch(bucket: dict[str, FieldStats], field: str, type_: str, source: str) -> None:
    s = bucket.setdefault(field, FieldStats())
    s.count += 1
    s.types.update([type_])
    s.example_files.add(source)


def write_schema_profile(profile: dict[str, dict[str, FieldStats]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Stonebranch JSON schema profile",
        "",
        "This report contains field names, value types, counts, and example file names only. It does not include values.",
        "",
    ]
    for kind, fields in sorted(profile.items()):
        lines += [f"## {kind}", "", "| Field path | Count | Types | Example files |", "|---|---:|---|---|"]
        for field_name, s in sorted(fields.items(), key=lambda x: (-x[1].count, x[0]))[:1000]:
            types = ", ".join(f"{k}:{v}" for k, v in s.types.most_common())
            examples = ", ".join(sorted(s.example_files)[:3])
            lines.append(f"| `{field_name}` | {s.count} | {types} | `{examples}` |")
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def write_schema_csv(profile: dict[str, dict[str, FieldStats]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["kind", "field", "count", "types", "example_files"])
        writer.writeheader()
        for kind, fields in sorted(profile.items()):
            for field_name, s in sorted(fields.items()):
                writer.writerow({
                    "kind": kind,
                    "field": field_name,
                    "count": s.count,
                    "types": ";".join(f"{k}:{v}" for k, v in s.types.most_common()),
                    "example_files": ";".join(sorted(s.example_files)[:5]),
                })


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def is_secret_key(key: str) -> bool:
    lower = key.lower().replace("-", "_")
    return any(secret in lower for secret in SECRET_KEYWORDS)
