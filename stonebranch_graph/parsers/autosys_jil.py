from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
from typing import Any

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import (
    Edge,
    Graph,
    Node,
    make_canonical_key,
    make_edge_id,
    make_node_id,
    redacted_preview,
    stable_hash,
    enterprise_name_parts,
    comparison_name,
)
from stonebranch_graph.domain import (
    KIND_AGENT,
    KIND_BOX,
    KIND_CALENDAR,
    KIND_COMMAND,
    KIND_FILE,
    KIND_FILE_WATCHER,
    KIND_TASK,
    KIND_VARIABLE,
    REL_CONTAINS,
    REL_DEPENDS_ON,
    REL_DEPENDS_ON_DONE,
    REL_DEPENDS_ON_FAILURE,
    REL_DEPENDS_ON_NOTRUNNING,
    REL_DEPENDS_ON_SUCCESS,
    REL_DEPENDS_ON_TERMINATED,
    REL_EXCLUDES_CALENDAR,
    REL_RUNS_COMMAND,
    REL_RUNS_ON,
    REL_USES_CALENDAR,
    REL_USES_VARIABLE,
    REL_WATCHES_FILE,
    SOURCE_AUTOSYS_JIL,
)
from stonebranch_graph.normalizers import command_evidence, command_hash, command_normalization_diagnostics, command_variable_names, condition_hash, normalize_command, semantic_command_hash
from stonebranch_graph.utils import discover_source_files, is_secret_key, normalized_kind, read_text_file, safe_metadata


JOB_START_RE = re.compile(r"^\s*(insert_job|update_job)\s*:\s*(?P<body>.+?)\s*$", re.IGNORECASE)
DELETE_JOB_RE = re.compile(r"^\s*delete_job\s*:\s*(?P<name>.+?)\s*$", re.IGNORECASE)
ATTR_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(?P<value>.*?)\s*$", re.IGNORECASE)

CONDITION_RE = re.compile(
    r"\b(?P<event>s|success|d|done|f|failure|t|terminated|n|notrunning)\s*\(\s*(?P<body>[^)]+?)\s*\)",
    re.IGNORECASE,
)

JIL_EXTENSIONS = {".jil", ".txt", ".job", ".autosys"}


@dataclass
class JilJob:
    name: str
    action: str
    attributes: dict[str, str]
    source_file: str
    start_line: int


class AutosysJilParser:
    def __init__(self, config: AnalyzerConfig, env: str = "default") -> None:
        self.config = config
        self.env = env
        self._job_counts_by_source_file: dict[str, int] = {}

    def parse(self, input_path: Path) -> Graph:
        files = self._load_jil_files(input_path)
        jobs: list[JilJob] = []
        deleted: list[str] = []
        warnings: list[str] = []
        for file, relative, text in files:
            parsed, deleted_jobs, parse_warnings = self._parse_file(relative, text)
            jobs.extend(parsed)
            deleted.extend(deleted_jobs)
            warnings.extend(parse_warnings)

        graph = Graph(source_system=SOURCE_AUTOSYS_JIL, env=self.env)
        self._job_counts_by_source_file = self._count_jobs_by_source_file(jobs)
        for warning in warnings:
            self._append_warning_once(graph, warning)

        for job in jobs:
            kind = self._job_kind(job.attributes)
            native_kind = job.attributes.get("job_type", "unknown")
            metadata = self._job_metadata(job)
            node = self._make_node(
                kind=kind,
                name=job.name,
                native_kind=native_kind,
                source_file=job.source_file,
                metadata=metadata,
                attributes=job.attributes,
            )
            existing = graph.nodes.get(node.id)
            if existing:
                self._append_warning_once(
                    graph,
                    f"Duplicate JIL job id {node.id!r}: keeping first definition from "
                    f"{existing.source_file!r}, merging duplicate from {job.source_file!r}."
                )
            graph.add_node(node)

        for job in jobs:
            source_id = make_node_id(SOURCE_AUTOSYS_JIL, self.env, self._job_kind(job.attributes), job.name)
            self._add_box_edge(graph, job, source_id)
            self._add_machine_edge(graph, job, source_id)
            self._add_calendar_edges(graph, job, source_id)
            self._add_command_edge(graph, job, source_id)
            self._add_watch_file_edge(graph, job, source_id)
            self._add_condition_edges(graph, job, source_id)

        if deleted:
            self._append_warning_once(graph, f"Found {len(deleted)} delete_job records. They were not added as active nodes.")
        if not jobs:
            self._append_warning_once(graph, f"No active JIL insert_job/update_job records were parsed from {input_path}.")

        return graph

    def _load_jil_files(self, input_path: Path) -> list[tuple[Path, str, str]]:
        if not input_path.exists():
            raise FileNotFoundError(f"Input path does not exist: {input_path}")

        root = input_path.parent if input_path.is_file() else input_path
        files = discover_source_files(input_path, extensions=JIL_EXTENSIONS)

        if not files:
            raise FileNotFoundError(f"No JIL files found under: {input_path}")

        loaded = []
        for file in files:
            relative = str(file.relative_to(root)) if file.is_relative_to(root) else str(file)
            loaded.append((file, relative, read_text_file(file)))
        return loaded

    def _count_jobs_by_source_file(self, jobs: list[JilJob]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for job in jobs:
            counts[job.source_file] = counts.get(job.source_file, 0) + 1
        return counts

    def _parse_file(self, relative: str, text: str) -> tuple[list[JilJob], list[str], list[str]]:
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

        for line_no, raw_line in enumerate(self._join_continuations(text), start=1):
            line = self._strip_comments(raw_line).strip()
            if not line:
                continue

            delete_match = DELETE_JOB_RE.match(line)
            if delete_match:
                flush()
                deleted_jobs.append(self._clean_value(delete_match.group("name")))
                continue

            start_match = JOB_START_RE.match(line)
            if start_match:
                flush()
                current_action = start_match.group(1).lower()
                current_name, inline_attrs = self._parse_job_start_body(start_match.group("body"))
                current_attrs.update(inline_attrs)
                current_line = line_no
                continue

            attr_match = ATTR_RE.match(line)
            if attr_match and current_name:
                key = attr_match.group("key").lower()
                value = self._clean_value(attr_match.group("value"))
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


    def _parse_job_start_body(self, body: str) -> tuple[str, dict[str, str]]:
        name_text, inline_text = self._split_name_and_inline_attrs(body)
        return self._clean_value(name_text), self._parse_inline_attrs(inline_text)

    def _split_name_and_inline_attrs(self, text: str) -> tuple[str, str]:
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

    def _parse_inline_attrs(self, text: str) -> dict[str, str]:
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
            attrs[key] = self._clean_value(value)
        return attrs

    def _join_continuations(self, text: str) -> list[str]:
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

    def _strip_comments(self, line: str) -> str:
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("/*") or stripped.startswith("//"):
            return ""
        return line

    def _clean_value(self, value: str) -> str:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            return value[1:-1].strip()
        return value

    def _job_kind(self, attrs: dict[str, str]) -> str:
        raw = attrs.get("job_type", "c").lower()
        mapping = {
            "b": KIND_BOX,
            "box": KIND_BOX,
            "c": KIND_TASK,
            "cmd": KIND_TASK,
            "command": KIND_TASK,
            "f": KIND_FILE_WATCHER,
            "fw": KIND_FILE_WATCHER,
            "file_watcher": KIND_FILE_WATCHER,
        }
        return normalized_kind(mapping.get(raw, raw), self.config.kind_aliases)

    def _make_node(
        self,
        kind: str,
        name: str,
        native_kind: str,
        source_file: str,
        metadata: dict[str, Any],
        attributes: dict[str, Any] | None = None,
    ) -> Node:
        safe_attrs = safe_metadata(attributes or {})
        return Node(
            id=make_node_id(SOURCE_AUTOSYS_JIL, self.env, kind, name),
            canonical_key=make_canonical_key(self.env, kind, name),
            source_system=SOURCE_AUTOSYS_JIL,
            env=self.env,
            kind=kind,
            name=name,
            native_kind=native_kind,
            source_file=source_file,
            attributes_hash=stable_hash(safe_attrs, 16) if safe_attrs else "",
            metadata=metadata,
        )

    def _job_metadata(self, job: JilJob) -> dict[str, Any]:
        command = job.attributes.get("command", "")
        condition = job.attributes.get("condition", "")
        metadata = {
            "action": job.action,
            "start_line": job.start_line,
            "command_hash": command_hash(command) if command else "",
            "semantic_command_hash": semantic_command_hash(command) if command else "",
            "command_normalization": command_normalization_diagnostics(command) if command else {},
            "condition_hash": condition_hash(condition) if condition else "",
            "has_condition": bool(condition),
        }
        naming = enterprise_name_parts(job.name)
        if naming:
            metadata["enterprise_naming"] = naming
        inferred_box_name = self._inferred_box_name_for_job(job)
        if inferred_box_name:
            metadata["source_file_box_name"] = inferred_box_name
            inferred_naming = enterprise_name_parts(inferred_box_name)
            if inferred_naming:
                metadata["source_file_box_naming"] = inferred_naming
        if command and self.config.include_raw_values:
            metadata["command_raw"] = normalize_command(command)
        if condition and self.config.include_raw_values:
            metadata["condition_raw"] = condition
        return metadata

    def _ensure_ref_node(
        self,
        graph: Graph,
        kind: str,
        name: str,
        native_kind: str,
        source_file: str,
        metadata: dict[str, Any] | None = None,
    ) -> Node:
        node_id = make_node_id(SOURCE_AUTOSYS_JIL, self.env, kind, name)
        existing = graph.nodes.get(node_id)
        if existing:
            return existing
        node = self._make_node(
            kind=kind,
            name=name,
            native_kind=native_kind,
            source_file=source_file,
            metadata={"synthetic": True, **(metadata or {})},
            attributes=None,
        )
        return graph.add_node(node)

    def _add_edge(
        self,
        graph: Graph,
        source_id: str,
        target_id: str,
        relation: str,
        native_relation: str,
        job: JilJob,
        evidence_value: str,
        confidence: float = 1.0,
    ) -> None:
        graph.add_edge(
            Edge(
                id=make_edge_id(source_id, target_id, relation, native_relation),
                source=source_id,
                target=target_id,
                relation=relation,
                source_system=SOURCE_AUTOSYS_JIL,
                native_relation=native_relation,
                evidence_file=job.source_file,
                evidence_path=f"job:{job.name}",
                evidence_key=native_relation,
                evidence_value=redacted_preview(evidence_value, self.config.max_evidence_value_len),
                confidence=confidence,
            )
        )

    def _add_box_edge(self, graph: Graph, job: JilJob, source_id: str) -> None:
        box_name = job.attributes.get("box_name")
        native_relation = "box_name"
        if not box_name:
            box_name = self._inferred_box_name_for_job(job)
            native_relation = "source_file_box"
        if not box_name:
            return

        if self._is_self_box_reference(job, box_name):
            return

        box = self._resolve_ref_node(
            graph,
            kind=KIND_BOX,
            name=box_name,
            native_kind=native_relation,
            source_file=job.source_file,
        )
        # Direction: box contains job/child box.
        self._add_edge(graph, box.id, source_id, REL_CONTAINS, native_relation, job, box_name)

    def _inferred_box_name_for_job(self, job: JilJob) -> str:
        if self._job_counts_by_source_file.get(job.source_file, 0) < 2:
            return ""
        stem = Path(job.source_file).stem
        if enterprise_name_parts(stem):
            return stem
        return ""

    def _is_self_box_reference(self, job: JilJob, box_name: str) -> bool:
        if self._job_kind(job.attributes) != KIND_BOX:
            return False
        return comparison_name(job.name).lower() == comparison_name(box_name).lower()

    def _resolve_ref_node(
        self,
        graph: Graph,
        kind: str,
        name: str,
        native_kind: str,
        source_file: str,
        metadata: dict[str, Any] | None = None,
    ) -> Node:
        exact_id = make_node_id(SOURCE_AUTOSYS_JIL, self.env, kind, name)
        exact = graph.nodes.get(exact_id)
        if exact:
            return exact

        requested_key = make_canonical_key(self.env, kind, name)
        matches = [
            node
            for node in graph.nodes.values()
            if node.kind == kind and node.canonical_key == requested_key
        ]
        real_matches = [node for node in matches if not node.metadata.get("synthetic")]
        candidates = real_matches or matches
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            self._append_warning_once(
                graph,
                f"Ambiguous JIL {kind!r} reference {name!r}: matched {len(candidates)} objects by "
                "comparison key, created synthetic node instead.",
            )

        return self._ensure_ref_node(graph, kind, name, native_kind, source_file, metadata=metadata)

    def _add_machine_edge(self, graph: Graph, job: JilJob, source_id: str) -> None:
        machine = job.attributes.get("machine")
        if not machine:
            return
        node = self._ensure_ref_node(graph, KIND_AGENT, machine, "machine", job.source_file)
        self._add_edge(graph, source_id, node.id, REL_RUNS_ON, "machine", job, machine)

    def _add_calendar_edges(self, graph: Graph, job: JilJob, source_id: str) -> None:
        for key, relation in (
            ("calendar", REL_USES_CALENDAR),
            ("run_calendar", REL_USES_CALENDAR),
            ("exclude_calendar", REL_EXCLUDES_CALENDAR),
        ):
            value = job.attributes.get(key)
            if not value:
                continue
            for name in self._split_csv_like(value):
                node = self._ensure_ref_node(graph, KIND_CALENDAR, name, key, job.source_file)
                self._add_edge(graph, source_id, node.id, relation, key, job, name)

    def _add_command_edge(self, graph: Graph, job: JilJob, source_id: str) -> None:
        command = job.attributes.get("command")
        if not command or is_secret_key("command"):
            return
        command_hash_value = command_hash(command)
        semantic_hash_value = semantic_command_hash(command)
        node = self._ensure_ref_node(
            graph,
            KIND_COMMAND,
            semantic_hash_value,
            "semantic_command_hash",
            job.source_file,
            metadata={
                # Hash-named helper node: commands are compared at attribute
                # level (strict + semantic hash), never as graph objects.
                "artifact": True,
                "command_hash": command_hash_value,
                "semantic_command_hash": semantic_hash_value,
                "command_normalization": command_normalization_diagnostics(command),
            },
        )
        evidence = command_evidence(command, include_raw_values=self.config.include_raw_values)
        self._add_edge(graph, source_id, node.id, REL_RUNS_COMMAND, "command", job, evidence)
        for variable_name in command_variable_names(command):
            variable = self._ensure_ref_node(graph, KIND_VARIABLE, variable_name, "command_variable", job.source_file)
            self._add_edge(graph, source_id, variable.id, REL_USES_VARIABLE, "command_variable", job, variable_name)

    def _add_watch_file_edge(self, graph: Graph, job: JilJob, source_id: str) -> None:
        watch_file = job.attributes.get("watch_file")
        if not watch_file:
            return
        node = self._ensure_ref_node(graph, KIND_FILE, watch_file, "watch_file", job.source_file)
        self._add_edge(graph, source_id, node.id, REL_WATCHES_FILE, "watch_file", job, watch_file)

    def _add_condition_edges(self, graph: Graph, job: JilJob, source_id: str) -> None:
        condition = job.attributes.get("condition")
        if not condition:
            return

        refs = self._parse_condition_refs(condition)
        if not refs:
            self._append_warning_once(
                graph,
                f"Could not extract JIL condition dependencies for job {job.name!r}; "
                f"condition_hash={condition_hash(condition)}.",
            )
            return

        evidence = condition if self.config.include_raw_values else condition_hash(condition)
        for event, dep_job_name in refs:
            dep_node = self._resolve_dependency_node(graph, dep_job_name, f"condition:{event}", job.source_file)
            relation = {
                "success": REL_DEPENDS_ON_SUCCESS,
                "done": REL_DEPENDS_ON_DONE,
                "failure": REL_DEPENDS_ON_FAILURE,
                "terminated": REL_DEPENDS_ON_TERMINATED,
                "notrunning": REL_DEPENDS_ON_NOTRUNNING,
            }.get(event, REL_DEPENDS_ON)
            self._add_edge(
                graph,
                source_id,
                dep_node.id,
                relation,
                f"condition_{event}",
                job,
                evidence,
                confidence=0.95,
            )

    def _resolve_dependency_node(self, graph: Graph, name: str, native_kind: str, source_file: str) -> Node:
        candidates: list[Node] = []
        for kind in (KIND_TASK, KIND_BOX, KIND_FILE_WATCHER):
            exact = graph.nodes.get(make_node_id(SOURCE_AUTOSYS_JIL, self.env, kind, name))
            if exact:
                candidates.append(exact)

        if not candidates:
            requested_keys = {
                make_canonical_key(self.env, kind, name): kind
                for kind in (KIND_TASK, KIND_BOX, KIND_FILE_WATCHER)
            }
            candidates = [
                node
                for node in graph.nodes.values()
                if node.kind in {KIND_TASK, KIND_BOX, KIND_FILE_WATCHER}
                and node.canonical_key in requested_keys
                and not node.metadata.get("synthetic")
            ]

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            self._append_warning_once(
                graph,
                f"Ambiguous JIL condition reference {name!r}: matched {len(candidates)} active jobs/boxes, "
                "created synthetic task node instead.",
            )

        return self._ensure_ref_node(graph, KIND_TASK, name, native_kind, source_file)

    def _parse_condition_refs(self, condition: str) -> list[tuple[str, str]]:
        refs: list[tuple[str, str]] = []
        for match in CONDITION_RE.finditer(condition):
            raw_event = match.group("event").lower()
            body = match.group("body").strip()
            job_name = body.split(",", 1)[0].strip().strip('"').strip("'")
            if not job_name:
                continue
            event = {
                "s": "success",
                "success": "success",
                "d": "done",
                "done": "done",
                "f": "failure",
                "failure": "failure",
                "t": "terminated",
                "terminated": "terminated",
                "n": "notrunning",
                "notrunning": "notrunning",
            }.get(raw_event, raw_event)
            refs.append((event, job_name))
        return refs


    def _append_warning_once(self, graph: Graph, warning: str) -> None:
        if warning not in graph.warnings:
            graph.warnings.append(warning)

    def _split_csv_like(self, value: str) -> list[str]:
        lexer = shlex.shlex(value, posix=True)
        lexer.whitespace = ", \t\r\n"
        lexer.whitespace_split = True
        lexer.commenters = ""
        return [item.strip() for item in lexer if item.strip()]
