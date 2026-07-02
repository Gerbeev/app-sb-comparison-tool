from __future__ import annotations

from pathlib import Path
from typing import Any

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import Edge, Graph, Node, make_canonical_key, make_edge_id, make_node_id, redacted_preview
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
    REL_EXCLUDES_CALENDAR,
    REL_RUNS_COMMAND,
    REL_RUNS_ON,
    REL_USES_CALENDAR,
    REL_USES_VARIABLE,
    REL_WATCHES_FILE,
    SOURCE_AUTOSYS_JIL,
)
from stonebranch_graph.normalizers import (
    command_evidence,
    command_hash,
    command_normalization_diagnostics,
    command_variable_names,
    condition_hash,
    semantic_command_hash,
)
from stonebranch_graph.parsers.autosys_conditions import condition_relation, parse_condition_refs
from stonebranch_graph.parsers.autosys_lexer import parse_jil_file, split_csv_like
from stonebranch_graph.parsers.autosys_model import JilJob, count_jobs_by_source_file
from stonebranch_graph.parsers.autosys_nodes import (
    ensure_jil_ref_node,
    inferred_box_name_for_job,
    is_self_box_reference,
    jil_job_kind,
    jil_job_metadata,
    make_jil_node,
)
from stonebranch_graph.utils import discover_source_files, is_secret_key, read_text_file

JIL_EXTENSIONS = {".jil", ".txt", ".job", ".autosys"}


class AutosysJilParser:
    def __init__(self, config: AnalyzerConfig, env: str = "default") -> None:
        self.config = config
        self.env = env
        self._job_counts_by_source_file: dict[str, int] = {}

    def parse(self, input_path: Path) -> Graph:
        jobs, deleted, warnings = self._read_jobs(input_path)
        graph = Graph(source_system=SOURCE_AUTOSYS_JIL, env=self.env)
        self._job_counts_by_source_file = count_jobs_by_source_file(jobs)
        for warning in warnings:
            self._append_warning_once(graph, warning)

        for job in jobs:
            self._add_job_node(graph, job)
        for job in jobs:
            self._add_job_edges(graph, job)

        if deleted:
            self._append_warning_once(graph, f"Found {len(deleted)} delete_job records. They were not added as active nodes.")
        if not jobs:
            self._append_warning_once(graph, f"No active JIL insert_job/update_job records were parsed from {input_path}.")
        return graph

    def _read_jobs(self, input_path: Path) -> tuple[list[JilJob], list[str], list[str]]:
        jobs: list[JilJob] = []
        deleted: list[str] = []
        warnings: list[str] = []
        for _, relative, text in self._load_jil_files(input_path):
            parsed, deleted_jobs, parse_warnings = parse_jil_file(relative, text)
            jobs.extend(parsed)
            deleted.extend(deleted_jobs)
            warnings.extend(parse_warnings)
        return jobs, deleted, warnings

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

    def _add_job_node(self, graph: Graph, job: JilJob) -> None:
        kind = self._job_kind(job.attributes)
        node = make_jil_node(
            env=self.env,
            kind=kind,
            name=job.name,
            native_kind=job.attributes.get("job_type", "unknown"),
            source_file=job.source_file,
            metadata=jil_job_metadata(job, self.config, self._job_counts_by_source_file),
            attributes=job.attributes,
        )
        existing = graph.nodes.get(node.id)
        if existing:
            self._append_warning_once(
                graph,
                f"Duplicate JIL job id {node.id!r}: keeping first definition from "
                f"{existing.source_file!r}, merging duplicate from {job.source_file!r}.",
            )
        graph.add_node(node)

    def _add_job_edges(self, graph: Graph, job: JilJob) -> None:
        source_id = make_node_id(SOURCE_AUTOSYS_JIL, self.env, self._job_kind(job.attributes), job.name)
        self._add_box_edge(graph, job, source_id)
        self._add_machine_edge(graph, job, source_id)
        self._add_calendar_edges(graph, job, source_id)
        self._add_command_edge(graph, job, source_id)
        self._add_watch_file_edge(graph, job, source_id)
        self._add_condition_edges(graph, job, source_id)

    def _job_kind(self, attrs: dict[str, str]) -> str:
        return jil_job_kind(attrs, self.config)

    def _ensure_ref_node(
        self,
        graph: Graph,
        kind: str,
        name: str,
        native_kind: str,
        source_file: str,
        metadata: dict[str, Any] | None = None,
    ) -> Node:
        return ensure_jil_ref_node(graph, self.env, kind, name, native_kind, source_file, metadata=metadata)

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
            box_name = inferred_box_name_for_job(job, self._job_counts_by_source_file)
            native_relation = "source_file_box"
        if not box_name or is_self_box_reference(job, box_name, self.config):
            return

        box = self._resolve_ref_node(graph, KIND_BOX, box_name, native_relation, job.source_file)
        self._add_edge(graph, box.id, source_id, REL_CONTAINS, native_relation, job, box_name)

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
        matches = [node for node in graph.nodes.values() if node.kind == kind and node.canonical_key == requested_key]
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
            for name in split_csv_like(value):
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

        refs = parse_condition_refs(condition)
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
            self._add_edge(
                graph,
                source_id,
                dep_node.id,
                condition_relation(event),
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
            requested_keys = {make_canonical_key(self.env, kind, name): kind for kind in (KIND_TASK, KIND_BOX, KIND_FILE_WATCHER)}
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

    def _append_warning_once(self, graph: Graph, warning: str) -> None:
        if warning not in graph.warnings:
            graph.warnings.append(warning)
