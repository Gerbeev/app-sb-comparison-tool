from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
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
)
from stonebranch_graph.normalizers import command_evidence, command_hash, condition_hash, normalize_command, normalize_condition
from stonebranch_graph.utils import is_secret_key, normalized_kind, read_text_file, safe_metadata


JOB_START_RE = re.compile(r"^\s*(insert_job|update_job)\s*:\s*(?P<name>.+?)\s*$", re.IGNORECASE)
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

    def parse(self, input_path: Path) -> Graph:
        files = self._load_jil_files(input_path)
        jobs: list[JilJob] = []
        deleted: list[str] = []
        for file, relative, text in files:
            parsed, deleted_jobs = self._parse_file(relative, text)
            jobs.extend(parsed)
            deleted.extend(deleted_jobs)

        graph = Graph(source_system="autosys_jil", env=self.env)

        for job in jobs:
            kind = self._job_kind(job.attributes)
            native_kind = job.attributes.get("job_type", "unknown")
            metadata = self._job_metadata(job)
            graph.add_node(
                self._make_node(
                    kind=kind,
                    name=job.name,
                    native_kind=native_kind,
                    source_file=job.source_file,
                    metadata=metadata,
                    attributes=job.attributes,
                )
            )

        for job in jobs:
            source_id = make_node_id("autosys_jil", self.env, self._job_kind(job.attributes), job.name)
            self._add_box_edge(graph, job, source_id)
            self._add_machine_edge(graph, job, source_id)
            self._add_calendar_edges(graph, job, source_id)
            self._add_command_edge(graph, job, source_id)
            self._add_watch_file_edge(graph, job, source_id)
            self._add_condition_edges(graph, job, source_id)

        if deleted:
            graph.warnings.append(f"Found {len(deleted)} delete_job records. They were not added as active nodes.")

        return graph

    def _load_jil_files(self, input_path: Path) -> list[tuple[Path, str, str]]:
        if not input_path.exists():
            raise FileNotFoundError(f"Input path does not exist: {input_path}")

        root = input_path.parent if input_path.is_file() else input_path
        if input_path.is_file():
            files = [input_path]
        else:
            files = sorted(
                p for p in input_path.rglob("*")
                if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in JIL_EXTENSIONS
            )

        if not files:
            raise FileNotFoundError(f"No JIL files found under: {input_path}")

        loaded = []
        for file in files:
            relative = str(file.relative_to(root)) if file.is_relative_to(root) else str(file)
            loaded.append((file, relative, read_text_file(file)))
        return loaded

    def _parse_file(self, relative: str, text: str) -> tuple[list[JilJob], list[str]]:
        jobs: list[JilJob] = []
        deleted_jobs: list[str] = []
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
                current_name = self._clean_value(start_match.group("name"))
                current_line = line_no
                continue

            attr_match = ATTR_RE.match(line)
            if attr_match and current_name:
                key = attr_match.group("key").lower()
                value = self._clean_value(attr_match.group("value"))
                current_attrs[key] = value

        flush()
        return jobs, deleted_jobs


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
        return value.strip().strip('"').strip("'")

    def _job_kind(self, attrs: dict[str, str]) -> str:
        raw = attrs.get("job_type", "c").lower()
        mapping = {
            "b": "box",
            "box": "box",
            "c": "task",
            "cmd": "task",
            "command": "task",
            "f": "file_watcher",
            "fw": "file_watcher",
            "file_watcher": "file_watcher",
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
            id=make_node_id("autosys_jil", self.env, kind, name),
            canonical_key=make_canonical_key(self.env, kind, name),
            source_system="autosys_jil",
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
        metadata = {
            "action": job.action,
            "start_line": job.start_line,
            "command_hash": command_hash(command) if command else "",
            "condition_raw": job.attributes.get("condition", ""),
            "condition_hash": condition_hash(job.attributes.get("condition", "")) if job.attributes.get("condition") else "",
            "has_condition": bool(job.attributes.get("condition")),
        }
        if command and self.config.include_raw_values:
            metadata["command_raw"] = normalize_command(command)
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
        node_id = make_node_id("autosys_jil", self.env, kind, name)
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
                source_system="autosys_jil",
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
        if not box_name:
            return
        box = self._ensure_ref_node(graph, "box", box_name, "box_name", job.source_file)
        # Direction: box contains job.
        self._add_edge(graph, box.id, source_id, "contains", "box_name", job, box_name)

    def _add_machine_edge(self, graph: Graph, job: JilJob, source_id: str) -> None:
        machine = job.attributes.get("machine")
        if not machine:
            return
        node = self._ensure_ref_node(graph, "agent", machine, "machine", job.source_file)
        self._add_edge(graph, source_id, node.id, "runs_on", "machine", job, machine)

    def _add_calendar_edges(self, graph: Graph, job: JilJob, source_id: str) -> None:
        for key, relation in (
            ("calendar", "uses_calendar"),
            ("run_calendar", "uses_calendar"),
            ("exclude_calendar", "excludes_calendar"),
        ):
            value = job.attributes.get(key)
            if not value:
                continue
            for name in self._split_csv_like(value):
                node = self._ensure_ref_node(graph, "calendar", name, key, job.source_file)
                self._add_edge(graph, source_id, node.id, relation, key, job, name)

    def _add_command_edge(self, graph: Graph, job: JilJob, source_id: str) -> None:
        command = job.attributes.get("command")
        if not command or is_secret_key("command"):
            return
        command_hash_value = command_hash(command)
        node = self._ensure_ref_node(
            graph,
            "command",
            command_hash_value,
            "command_hash",
            job.source_file,
            metadata={"command_hash": command_hash_value},
        )
        evidence = command_evidence(command, include_raw_values=self.config.include_raw_values)
        self._add_edge(graph, source_id, node.id, "runs_command", "command", job, evidence)

    def _add_watch_file_edge(self, graph: Graph, job: JilJob, source_id: str) -> None:
        watch_file = job.attributes.get("watch_file")
        if not watch_file:
            return
        node = self._ensure_ref_node(graph, "file", watch_file, "watch_file", job.source_file)
        self._add_edge(graph, source_id, node.id, "watches_file", "watch_file", job, watch_file)

    def _add_condition_edges(self, graph: Graph, job: JilJob, source_id: str) -> None:
        condition = job.attributes.get("condition")
        if not condition:
            return

        for event, dep_job_name in self._parse_condition_refs(condition):
            dep_kind = "task"
            dep_node = self._ensure_ref_node(
                graph,
                dep_kind,
                dep_job_name,
                f"condition:{event}",
                job.source_file,
            )
            relation = {
                "success": "depends_on_success",
                "done": "depends_on_done",
                "failure": "depends_on_failure",
                "terminated": "depends_on_terminated",
                "notrunning": "depends_on_notrunning",
            }.get(event, "depends_on")
            self._add_edge(
                graph,
                source_id,
                dep_node.id,
                relation,
                f"condition_{event}",
                job,
                condition,
                confidence=0.95,
            )

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


    def _split_csv_like(self, value: str) -> list[str]:
        return [item.strip().strip('"').strip("'") for item in re.split(r"[,\s]+", value) if item.strip()]
