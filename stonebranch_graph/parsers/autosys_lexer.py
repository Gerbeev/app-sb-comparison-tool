from __future__ import annotations

import re
import shlex

from stonebranch_graph.parsers.autosys_model import JilJob

JOB_START_RE = re.compile(r"^\s*(insert_job|update_job)\s*:\s*(?P<body>.+?)\s*$", re.IGNORECASE)
DELETE_JOB_RE = re.compile(r"^\s*delete_job\s*:\s*(?P<name>.+?)\s*$", re.IGNORECASE)
ATTR_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(?P<value>.*?)\s*$", re.IGNORECASE)


def parse_jil_file(relative: str, text: str) -> tuple[list[JilJob], list[str], list[str]]:
    jobs: list[JilJob] = []
    deleted_jobs: list[str] = []
    warnings: list[str] = []
    current_name: str | None = None
    current_action = "insert_job"
    current_attrs: dict[str, str] = {}
    current_line = 1

    def flush() -> None:
        nonlocal current_name, current_attrs, current_action, current_line
        if current_name:
            jobs.append(
                JilJob(
                    name=current_name,
                    action=current_action,
                    attributes=dict(current_attrs),
                    source_file=relative,
                    start_line=current_line,
                )
            )
        current_name = None
        current_attrs = {}
        current_action = "insert_job"
        current_line = 1

    for line_no, raw_line in enumerate(join_continuations(text), start=1):
        line = strip_comments(raw_line).strip()
        if not line:
            continue

        delete_match = DELETE_JOB_RE.match(line)
        if delete_match:
            flush()
            deleted_jobs.append(clean_value(delete_match.group("name")))
            continue

        start_match = JOB_START_RE.match(line)
        if start_match:
            flush()
            current_action = start_match.group(1).lower()
            current_name, inline_attrs = parse_job_start_body(start_match.group("body"))
            current_attrs.update(inline_attrs)
            current_line = line_no
            continue

        attr_match = ATTR_RE.match(line)
        if attr_match and current_name:
            key = attr_match.group("key").lower()
            value = clean_value(attr_match.group("value"))
            current_attrs[key] = value
            continue
        if attr_match and not current_name:
            warnings.append(
                f"Ignored JIL attribute outside job block at {relative}:{line_no}: "
                f"{attr_match.group('key').lower()}"
            )
            continue

        warnings.append(f"Ignored unparsed JIL line at {relative}:{line_no}.")

    flush()
    return jobs, deleted_jobs, warnings


def parse_job_start_body(body: str) -> tuple[str, dict[str, str]]:
    name_text, inline_text = split_name_and_inline_attrs(body)
    return clean_value(name_text), parse_inline_attrs(inline_text)


def split_name_and_inline_attrs(text: str) -> tuple[str, str]:
    quote = ""
    for idx, char in enumerate(text):
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if not char.isspace():
            continue
        candidate = text[idx + 1 :]
        if re.match(r"[A-Za-z_][A-Za-z0-9_-]*\s*:", candidate):
            return text[:idx].strip(), candidate.strip()
    return text.strip(), ""


def parse_inline_attrs(text: str) -> dict[str, str]:
    if not text.strip():
        return {}

    starts: list[tuple[int, str, int]] = []
    quote = ""
    idx = 0
    while idx < len(text):
        char = text[idx]
        if quote:
            if char == quote:
                quote = ""
            idx += 1
            continue
        if char in {"'", '"'}:
            quote = char
            idx += 1
            continue
        if idx == 0 or text[idx - 1].isspace():
            match = re.match(r"(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*:", text[idx:])
            if match:
                starts.append((idx, match.group("key").lower(), idx + match.end()))
                idx += match.end()
                continue
        idx += 1

    attrs: dict[str, str] = {}
    for pos, key, value_start in starts:
        next_pos = len(text)
        for other_pos, _, _ in starts:
            if other_pos > pos:
                next_pos = other_pos
                break
        value = text[value_start:next_pos].strip()
        attrs[key] = clean_value(value)
    return attrs


def join_continuations(text: str) -> list[str]:
    lines: list[str] = []
    buffer = ""
    for raw in text.splitlines():
        if buffer:
            buffer += " " + raw.strip()
        else:
            buffer = raw
        if buffer.rstrip().endswith("\\"):
            buffer = buffer.rstrip()[:-1].rstrip()
            continue
        lines.append(buffer)
        buffer = ""
    if buffer:
        lines.append(buffer)
    return lines


def strip_comments(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("#") or stripped.startswith("/*") or stripped.startswith("//"):
        return ""
    return line


def clean_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def split_csv_like(value: str) -> list[str]:
    lexer = shlex.shlex(value, posix=True)
    lexer.whitespace = ", \t\r\n"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return [item.strip() for item in lexer if item.strip()]
