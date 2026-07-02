from __future__ import annotations

from pathlib import Path
from typing import Any

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import Edge, Graph, make_edge_id, make_node_id, redacted_preview
from stonebranch_graph.domain import SOURCE_STONEBRANCH
from stonebranch_graph.parsers.stonebranch_discovery import (
    detect_object_name,
    env_from_path,
    iter_object_dicts,
    kind_from_path,
    load_stonebranch_json_files,
    make_stonebranch_node,
    native_kind,
    object_metadata,
)
from stonebranch_graph.parsers.stonebranch_registry import build_registry, resolve_or_create_ref_node
from stonebranch_graph.parsers.stonebranch_relations import directed_relation, find_stonebranch_references, kind_from_relation


class StonebranchJsonParser:
    def __init__(
        self,
        config: AnalyzerConfig,
        env: str = "default",
        env_aware: bool = False,
        deep_scan: bool = False,
    ) -> None:
        self.config = config
        self.env = env
        self.env_aware = env_aware
        self.deep_scan = deep_scan

    def parse(self, input_path: Path) -> Graph:
        files = load_stonebranch_json_files(input_path, self.config)
        graph = Graph(source_system=SOURCE_STONEBRANCH, env=self.env)
        records = self._collect_object_records(files, graph, input_path)
        registry = build_registry(graph)
        self._add_reference_edges(graph, records, registry)
        self._add_warnings(graph)
        return graph

    def _collect_object_records(
        self,
        files: list[tuple[Path, str, Any]],
        graph: Graph,
        input_path: Path,
    ) -> list[tuple[Path, str, str, str, str, dict[str, Any]]]:
        records: list[tuple[Path, str, str, str, str, dict[str, Any]]] = []
        for path, relative_path, data in files:
            kind = kind_from_path(path, self.config)
            if not kind:
                self._append_warning_once(
                    graph,
                    f"Skipped Stonebranch JSON file outside a configured object-kind folder: {relative_path}.",
                )
                continue
            for warning in self._objects_from_json(path, relative_path, data, kind, graph, records):
                self._append_warning_once(graph, warning)

        if not records:
            self._append_warning_once(graph, f"No Stonebranch objects were parsed from {input_path}.")
        return records

    def _objects_from_json(
        self,
        path: Path,
        relative_path: str,
        data: Any,
        kind: str,
        graph: Graph,
        records: list[tuple[Path, str, str, str, str, dict[str, Any]]],
    ) -> list[str]:
        objects, warnings = iter_object_dicts(data, relative_path)
        for item_relative_path, item in objects:
            env = env_from_path(path, self.config, self.env) if self.env_aware else self.env
            name = detect_object_name(item, kind, path)
            node = make_stonebranch_node(
                env=env,
                kind=kind,
                name=name,
                native_kind=native_kind(item, self.config) or kind,
                source_file=item_relative_path,
                metadata=object_metadata(item, name),
                attributes=item,
            )
            existing = graph.nodes.get(node.id)
            if existing and existing.source_file != item_relative_path:
                self._append_warning_once(
                    graph,
                    f"Duplicate Stonebranch object id {node.id!r}: keeping first definition from "
                    f"{existing.source_file!r}, merging duplicate from {item_relative_path!r}.",
                )
            graph.add_node(node)
            records.append((path, item_relative_path, env, kind, name, item))
        return warnings

    def _add_reference_edges(
        self,
        graph: Graph,
        records: list[tuple[Path, str, str, str, str, dict[str, Any]]],
        registry: dict[str, dict],
    ) -> None:
        for _, relative_path, env, source_kind, source_name, data in records:
            source_id = make_node_id(SOURCE_STONEBRANCH, env, source_kind, source_name)
            for ref_value, native_relation, relation, evidence_path, evidence_key, evidence_value in find_stonebranch_references(
                data,
                source_kind,
                self.config,
                self.deep_scan,
            ):
                target_id = resolve_or_create_ref_node(
                    graph=graph,
                    registry=registry,
                    config=self.config,
                    env=env,
                    target_kind=kind_from_relation(native_relation, relation),
                    target_name=ref_value,
                    native_relation=native_relation,
                    source_file=relative_path,
                    append_warning=self._append_warning_once,
                )
                edge_source, edge_target, edge_relation, edge_native_relation = directed_relation(
                    source_id,
                    target_id,
                    relation,
                    native_relation,
                )
                graph.add_edge(
                    Edge(
                        id=make_edge_id(edge_source, edge_target, edge_relation, edge_native_relation),
                        source=edge_source,
                        target=edge_target,
                        relation=edge_relation,
                        source_system=SOURCE_STONEBRANCH,
                        native_relation=edge_native_relation,
                        evidence_file=relative_path,
                        evidence_path=evidence_path,
                        evidence_key=evidence_key,
                        evidence_value=redacted_preview(evidence_value, self.config.max_evidence_value_len),
                        confidence=0.95 if native_relation != "deep_scan_reference" else 0.55,
                    )
                )

    def _append_warning_once(self, graph: Graph, warning: str) -> None:
        if warning not in graph.warnings:
            graph.warnings.append(warning)

    def _add_warnings(self, graph: Graph) -> None:
        synthetic = sum(1 for n in graph.nodes.values() if n.metadata.get("synthetic"))
        if synthetic:
            self._append_warning_once(graph, f"Created {synthetic} synthetic nodes for unresolved references.")
