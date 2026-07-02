from __future__ import annotations

import json
from collections import defaultdict
from importlib import resources
from pathlib import Path
from typing import Any

from .core import Graph, Node
from .domain import (
    CALENDAR_RELATIONS,
    COMMAND_RELATIONS,
    KIND_BOX,
    KIND_TASK,
    KIND_WORKFLOW,
    REL_CONTAINS,
    REL_STARTS,
    REL_USES_VARIABLE,
    REL_WATCHES_FILE,
    RUNTIME_TARGET_RELATIONS,
)
from .exporters import (
    build_container_view,
    canonical_edge_components,
    canonical_kind,
    canonical_node_key,
    stable_value,
    write_text_file,
)
from .graph_utils import GraphTraversalCache

HTML_GRAPH_SCHEMA_VERSION = "1.0"
CYTOSCAPE_RUNTIME_FILE = "cytoscape.min.js"
CYTOSCAPE_LICENSE_FILE = "cytoscape.LICENSE"

CONTAINER_KINDS = {KIND_WORKFLOW, KIND_BOX}

DEPENDENCY_RELATION_PREFIXES = ("depends_on",)


RELATION_CATEGORIES = {
    REL_CONTAINS: "contains",
    REL_STARTS: "triggers",
    REL_USES_VARIABLE: "variables",
    REL_WATCHES_FILE: "files",
}


def relation_category(relation: str) -> str:
    if relation.startswith(DEPENDENCY_RELATION_PREFIXES):
        return "dependencies"
    if relation in RUNTIME_TARGET_RELATIONS:
        return "runtime"
    if relation in CALENDAR_RELATIONS:
        return "calendars"
    if relation in COMMAND_RELATIONS:
        return "commands"
    return RELATION_CATEGORIES.get(relation, "other")


def _display_name(node: Node) -> str:
    enterprise = node.metadata.get("enterprise_naming") if isinstance(node.metadata, dict) else None
    if isinstance(enterprise, dict) and enterprise.get("real_name"):
        return str(enterprise["real_name"])
    return node.name


def _html_path(value: str | None) -> str:
    return str(value or "").replace("\\", "/")


def _container_parent_map(container_view: dict[str, Any]) -> dict[str, str | None]:
    parent_by_group_key: dict[str, str | None] = {
        container["group_key"]: None for container in container_view["containers"]
    }
    container_keys = set(parent_by_group_key)
    for container in container_view["containers"]:
        for child in container["children"]:
            if child["group_key"] in container_keys:
                parent_by_group_key[child["group_key"]] = container["group_key"]
    return parent_by_group_key


def _task_group_map(container_view: dict[str, Any]) -> dict[str, str]:
    task_group: dict[str, str] = {}
    for container in container_view["containers"]:
        for child in container["children"]:
            if child["kind"] == KIND_TASK:
                task_group.setdefault(child["group_key"], container["group_key"])
    return task_group


def build_cytoscape_graph_data(
    graph: Graph,
    *,
    traversal: GraphTraversalCache | None = None,
) -> dict[str, Any]:
    """Build the source graph view-model used by graph.html.

    This is intentionally separate from `graph.json`: the raw graph remains the
    source of truth, while this payload is optimized for a large interactive
    offline HTML graph report with collapsed workflow/box groups and relation filters.
    """

    traversal = traversal or GraphTraversalCache.build(graph)
    container_view = build_container_view(graph, traversal=traversal)
    parent_by_group_key = _container_parent_map(container_view)
    task_group_by_key = _task_group_map(container_view)

    groups = []
    for container in container_view["containers"]:
        groups.append(
            {
                "id": container["group_key"],
                "key": container["group_key"],
                "name": container["name"],
                "label": _display_name(graph.nodes[container["id"]])
                if container["id"] in graph.nodes
                else container["name"],
                "kind": container["kind"],
                "parent": parent_by_group_key.get(container["group_key"]),
                "child_count": container["child_count"],
                "task_count": container["task_count"],
                "nested_container_count": container["nested_container_count"],
                "source_file": _html_path(container["source_file"]),
                "graph_id": container["id"],
                "synthetic": container["synthetic"],
            }
        )

    jobs = []
    job_keys: set[str] = set()
    for node in traversal.sorted_nodes:
        key = canonical_node_key(node)
        if node.kind in CONTAINER_KINDS:
            continue
        job_keys.add(key)
        jobs.append(
            {
                "id": key,
                "key": key,
                "graph_id": node.id,
                "canonical_key": node.canonical_key,
                "name": node.name,
                "label": _display_name(node),
                "kind": canonical_kind(node.kind),
                "original_kind": node.kind,
                "group": task_group_by_key.get(key),
                "source_file": _html_path(node.source_file),
                "synthetic": bool(node.metadata.get("synthetic")),
                "meta": stable_value(
                    {
                        "attributes_hash": node.attributes_hash,
                        "native_kind": node.native_kind,
                        "semantic_command_hash": node.metadata.get("semantic_command_hash"),
                        "command_hash": node.metadata.get("command_hash"),
                    }
                ),
            }
        )

    edges = []
    depends_on: dict[str, list[str]] = defaultdict(list)
    for edge in traversal.sorted_edges:
        components = canonical_edge_components(edge, graph)
        if components is None:
            continue
        source, relation, target = components
        source_key = canonical_node_key(source)
        target_key = canonical_node_key(target)
        category = relation_category(relation)
        payload = {
            "id": f"{source_key}|{relation}|{target_key}|{edge.id}",
            "source": source_key,
            "target": target_key,
            "relation": relation,
            "category": category,
            "native_relation": edge.native_relation,
            "confidence": edge.confidence,
            "evidence_file": _html_path(edge.evidence_file),
            "evidence_path": edge.evidence_path,
            "evidence_key": edge.evidence_key,
            "evidence_value": edge.evidence_value,
            "graph_edge_id": edge.id,
        }
        edges.append(payload)
        if category == "dependencies" and source_key in job_keys and target_key in job_keys:
            depends_on[source_key].append(target_key)

    for job in jobs:
        job["depends_on"] = sorted(set(depends_on.get(job["id"], [])))

    groups = sorted(groups, key=lambda item: (item["id"], item["kind"], item["name"]))
    jobs = sorted(jobs, key=lambda item: (item["group"] or "", item["id"], item["kind"], item["name"]))
    edges = sorted(
        edges,
        key=lambda item: (
            item["category"],
            item["source"],
            item["relation"],
            item["target"],
            item["id"],
        ),
    )

    category_counts: dict[str, int] = defaultdict(int)
    for edge in edges:
        category_counts[edge["category"]] += 1

    return {
        "schema_version": HTML_GRAPH_SCHEMA_VERSION,
        "metadata": {
            "source_system": graph.source_system,
            "env": graph.env,
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "groups": len(groups),
            "jobs": len(jobs),
            "warnings": len(graph.warnings),
            "relation_categories": dict(sorted(category_counts.items())),
        },
        "groups": groups,
        "jobs": jobs,
        "edges": edges,
        "warnings": sorted(str(warning) for warning in graph.warnings),
    }


def export_graph_data_js(
    graph: Graph,
    path: Path,
    *,
    traversal: GraphTraversalCache | None = None,
) -> None:
    payload = build_cytoscape_graph_data(graph, traversal=traversal)
    text = (
        "/* offline HTML graph data. Generated by stonebranch-dependency-tool; do not hand-edit. */\n"
        "window.GRAPH_DATA = "
        + json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
        + ";\n"
    )
    write_text_file(path, text)


def export_cytoscape_runtime(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_root = resources.files(__package__).joinpath("assets")
    for asset_name in (CYTOSCAPE_RUNTIME_FILE, CYTOSCAPE_LICENSE_FILE):
        target = output_dir / asset_name
        target.write_bytes(asset_root.joinpath(asset_name).read_bytes())


def export_graph_html(
    path: Path,
    *,
    data_file: str = "graph-data.js",
    title: str = "Dependency graph",
) -> None:
    export_cytoscape_runtime(path.parent)
    html = (
        CYTOSCAPE_HTML.replace("__GRAPH_DATA_FILE__", data_file)
        .replace("__GRAPH_TITLE__", title)
        .replace("__CYTOSCAPE_RUNTIME_FILE__", CYTOSCAPE_RUNTIME_FILE)
    )
    write_text_file(path, html)


def export_cytoscape_html_report(
    graph: Graph,
    output_dir: Path,
    *,
    traversal: GraphTraversalCache | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    traversal = traversal or GraphTraversalCache.build(graph)
    export_graph_data_js(graph, output_dir / "graph-data.js", traversal=traversal)
    export_graph_html(output_dir / "graph.html")


def comparison_node_statuses(comparison: Any) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for pair in comparison.nodes.get("matched", []):
        key = str(pair.get("key") or "")
        if key:
            statuses[key] = "matched"
    for item in comparison.nodes.get("missing_in_stonebranch", []):
        key = str(item.get("comparison_key") or item.get("canonical_key") or "")
        if key:
            statuses[key] = "missing_in_stonebranch"
    for item in comparison.nodes.get("missing_in_jil", []):
        key = str(item.get("comparison_key") or item.get("canonical_key") or "")
        if key:
            statuses[key] = "missing_in_jil"
    for item in comparison.attributes.get("command_differences", []):
        key = str(item.get("key") or "")
        status = str(item.get("status") or "")
        if key and status:
            statuses[key] = status
    for item in comparison.attributes.get("condition_differences", []):
        key = str(item.get("key") or "")
        if key and statuses.get(key) == "matched":
            statuses[key] = "condition_mismatch"
    for section in ("stonebranch_key_collisions", "jil_key_collisions"):
        for item in comparison.diagnostics.get(section, []):
            key = str(item.get("key") or "")
            if key and key not in statuses:
                statuses[key] = "normalized_key_collision"
    return statuses


def comparison_edge_statuses(comparison: Any) -> dict[tuple[str, str, str], str]:
    statuses: dict[tuple[str, str, str], str] = {}
    for pair in comparison.edges.get("matched", []):
        key = edge_key_tuple(pair.get("key"))
        if key:
            statuses[key] = "matched"
    for item in comparison.edges.get("missing_in_stonebranch", []):
        key = edge_payload_tuple(item)
        if key:
            statuses[key] = (
                "missing_critical_in_stonebranch"
                if key[1] in CRITICAL_HTML_RELATIONS
                else "missing_in_stonebranch"
            )
    for item in comparison.edges.get("missing_in_jil", []):
        key = edge_payload_tuple(item)
        if key:
            statuses[key] = (
                "missing_critical_in_jil"
                if key[1] in CRITICAL_HTML_RELATIONS
                else "missing_in_jil"
            )
    return statuses


def edge_key_tuple(value: Any) -> tuple[str, str, str] | None:
    if not value or not isinstance(value, str) or "->" not in value:
        return None
    parts = value.split("->", 2)
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


def edge_payload_tuple(item: dict[str, Any]) -> tuple[str, str, str] | None:
    source = str(item.get("source_key") or "")
    relation = str(item.get("relation_key") or item.get("relation") or "")
    target = str(item.get("target_key") or "")
    if source and relation and target:
        return source, relation, target
    return edge_key_tuple(item.get("comparison_key"))


def merge_compare_items(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    *,
    node_statuses: dict[str, str],
    edge_statuses: dict[tuple[str, str, str], str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, dict[str, Any]] = {}
    jobs: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def merge_node(target: dict[str, dict[str, Any]], item: dict[str, Any], side: str) -> None:
        key = str(item.get("id") or "")
        if not key:
            return
        existing = target.setdefault(key, dict(item))
        existing.setdefault("sides", [])
        if side not in existing["sides"]:
            existing["sides"].append(side)
        existing["status"] = node_statuses.get(key) or existing.get("status") or (
            "matched" if len(existing["sides"]) > 1 else f"{side}_only"
        )
        existing["side"] = "+".join(sorted(existing["sides"]))

    for side, payload in (("stonebranch", left), ("jil", right)):
        for item in payload[0].get("groups", []):
            merge_node(groups, item, side)
        for item in payload[0].get("jobs", []):
            merge_node(jobs, item, side)
        for item in payload[0].get("edges", []):
            key = (str(item.get("source")), str(item.get("relation")), str(item.get("target")))
            existing = edges.setdefault(key, dict(item))
            existing.setdefault("sides", [])
            if side not in existing["sides"]:
                existing["sides"].append(side)
            existing["status"] = edge_statuses.get(key) or existing.get("status") or (
                "matched" if len(existing["sides"]) > 1 else f"{side}_only"
            )
            existing["side"] = "+".join(sorted(existing["sides"]))
            existing["id"] = f"{key[0]}|{key[1]}|{key[2]}|{existing['status']}"

    return (
        sorted(groups.values(), key=lambda item: (item.get("id", ""), item.get("kind", ""), item.get("name", ""))),
        sorted(
            jobs.values(),
            key=lambda item: (item.get("group") or "", item.get("id", ""), item.get("kind", ""), item.get("name", "")),
        ),
        sorted(
            edges.values(),
            key=lambda item: (
                item.get("status", ""),
                item.get("category", ""),
                item.get("source", ""),
                item.get("relation", ""),
                item.get("target", ""),
            ),
        ),
    )


def build_comparison_graph_data(comparison: Any, stonebranch: Graph, jil: Graph) -> dict[str, Any]:
    sb_payload = build_cytoscape_graph_data(stonebranch)
    jil_payload = build_cytoscape_graph_data(jil)
    node_statuses = comparison_node_statuses(comparison)
    edge_statuses = comparison_edge_statuses(comparison)
    groups, jobs, edges = merge_compare_items(
        [sb_payload],
        [jil_payload],
        node_statuses=node_statuses,
        edge_statuses=edge_statuses,
    )

    status_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)
    for item in [*groups, *jobs, *edges]:
        status_counts[str(item.get("status") or "unknown")] += 1
    for edge in edges:
        category_counts[str(edge.get("category") or "other")] += 1

    return {
        "schema_version": HTML_GRAPH_SCHEMA_VERSION,
        "metadata": {
            "report_type": "comparison",
            "report_title": "Comparison graph",
            "source_system": "stonebranch_vs_jil",
            "env": stonebranch.env or jil.env,
            "stonebranch_nodes": len(stonebranch.nodes),
            "jil_nodes": len(jil.nodes),
            "matched_nodes": comparison.summary.get("matched_nodes", 0),
            "matched_edges": comparison.summary.get("matched_edges", 0),
            "missing_in_stonebranch": comparison.summary.get("missing_in_stonebranch", 0),
            "missing_in_jil": comparison.summary.get("missing_in_jil", 0),
            "missing_edges_in_stonebranch": comparison.summary.get("missing_edges_in_stonebranch", 0),
            "missing_edges_in_jil": comparison.summary.get("missing_edges_in_jil", 0),
            "command_syntax_diff_only": comparison.summary.get("command_syntax_diff_only", 0),
            "command_semantic_mismatches": comparison.summary.get("command_semantic_mismatches", 0),
            "readiness_score": comparison.summary.get("migration_readiness_score", 0),
            "readiness_grade": comparison.summary.get("readiness_grade", "unknown"),
            "groups": len(groups),
            "jobs": len(jobs),
            "edges": len(edges),
            "relation_categories": dict(sorted(category_counts.items())),
            "statuses": dict(sorted(status_counts.items())),
        },
        "groups": groups,
        "jobs": jobs,
        "edges": edges,
        "warnings": sorted(str(warning) for warning in [*stonebranch.warnings, *jil.warnings]),
    }


def export_comparison_graph_data_js(comparison: Any, stonebranch: Graph, jil: Graph, path: Path) -> None:
    payload = build_comparison_graph_data(comparison, stonebranch, jil)
    text = (
        "/* offline comparison graph data. Generated by stonebranch-dependency-tool; do not hand-edit. */\n"
        "window.GRAPH_DATA = "
        + json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
        + ";\n"
    )
    write_text_file(path, text)


def export_comparison_html_report(comparison: Any, stonebranch: Graph, jil: Graph, output_dir: Path) -> None:
    compare_dir = output_dir / "compare"
    compare_dir.mkdir(parents=True, exist_ok=True)
    export_comparison_graph_data_js(comparison, stonebranch, jil, compare_dir / "compare-graph-data.js")
    export_graph_html(compare_dir / "compare-graph.html", data_file="compare-graph-data.js", title="Comparison graph")


CRITICAL_HTML_RELATIONS = {
    "contains",
    "depends_on",
    "depends_on_success",
    "depends_on_done",
    "depends_on_failure",
    "depends_on_terminated",
    "depends_on_notrunning",
    "runs_command",
    "runs_script",
}


CYTOSCAPE_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>__GRAPH_TITLE__</title>
<style>
  :root { --bg:#f6f8fb; --panel:#fff; --text:#202832; --muted:#6b7785; --border:#d8dee8; --accent:#1c7ed6; --danger:#e03131; --ok:#2f9e44; --warn:#f08c00; --purple:#7048e8; }
  * { box-sizing: border-box; }
  html, body { height:100%; margin:0; }
  body { background:var(--bg); color:var(--text); font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; overflow:hidden; }
  header { min-height:58px; display:flex; align-items:center; gap:10px; padding:10px 14px; background:var(--panel); border-bottom:1px solid var(--border); flex-wrap:wrap; }
  h1 { font-size:16px; margin:0 8px 0 0; }
  input, select, button { border:1px solid var(--border); background:#fff; color:var(--text); border-radius:8px; padding:7px 10px; font-size:13px; }
  button { cursor:pointer; white-space:nowrap; }
  button:hover, button.active { background:#eef2f6; border-color:#b8c3d2; }
  #search { width:260px; max-width:36vw; }
  .stats { margin-left:auto; display:flex; gap:12px; color:var(--muted); font-size:12px; flex-wrap:wrap; }
  .stats b { color:var(--text); }
  .layout { display:flex; height:calc(100vh - 58px); min-height:0; }
  #graphWrap { flex:1; min-width:0; height:100%; position:relative; background:linear-gradient(180deg,#f8fafc,#eef3f8); }
  #cy { width:100%; height:100%; display:block; }
  .runtime-error { display:none; position:absolute; inset:18px; padding:16px; border:1px solid #ffc9c9; border-radius:8px; background:#fff5f5; color:#c92a2a; z-index:2; }
  aside { width:360px; flex:none; background:var(--panel); border-left:1px solid var(--border); display:flex; flex-direction:column; min-height:0; }
  .panel-head { padding:14px 16px; border-bottom:1px solid var(--border); }
  .panel-title { font-weight:700; font-size:16px; word-break:break-word; }
  .panel-sub { color:var(--muted); font-size:12px; margin-top:3px; word-break:break-word; }
  .panel-body { padding:12px 16px; overflow:auto; }
  .kv { display:flex; justify-content:space-between; gap:12px; border-bottom:1px solid #edf0f4; padding:5px 0; font-size:12.5px; }
  .kv span:first-child { color:var(--muted); }
  .kv span:last-child { text-align:right; word-break:break-word; }
  .section { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.6px; margin:16px 0 6px; }
  .edge-card { border:1px solid #edf0f4; border-radius:8px; padding:8px; margin:7px 0; background:#fbfcfe; }
  .edge-main { display:flex; gap:7px; align-items:center; cursor:pointer; font-size:12.5px; }
  .edge-main b { margin-left:auto; word-break:break-word; text-align:right; }
  .edge-meta { margin-top:4px; color:var(--muted); font-size:11px; word-break:break-word; }
  .pill { display:inline-block; border:1px solid var(--border); border-radius:999px; padding:1px 6px; font-size:11px; color:var(--muted); }
  .copy-row { display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin:5px 0; }
  .copy-btn { padding:4px 7px; font-size:11px; border-radius:7px; }
  code.copyable { background:#f1f3f5; border:1px solid #e9ecef; border-radius:6px; padding:3px 5px; font-size:11.5px; word-break:break-all; }
  .linkish { color:var(--accent); cursor:pointer; text-decoration:underline; text-underline-offset:2px; }
  .placeholder { color:var(--muted); font-size:12px; }
  .legend, .status-grid { display:grid; grid-template-columns:1fr auto; gap:7px 12px; align-items:center; font-size:12px; }
  .legend span, .status-chip { display:flex; gap:6px; align-items:center; min-width:0; }
  .sw { display:inline-block; width:10px; height:10px; border-radius:50%; flex:none; }
  @media (max-width: 860px) {
    body { overflow:auto; }
    header { min-height:auto; }
    #search { width:100%; max-width:none; }
    .stats { margin-left:0; width:100%; }
    .layout { flex-direction:column; height:auto; min-height:calc(100vh - 110px); }
    #graphWrap { height:58vh; min-height:420px; }
    aside { width:100%; min-height:360px; border-left:0; border-top:1px solid var(--border); }
  }
</style>
<script src="__CYTOSCAPE_RUNTIME_FILE__"></script>
<script src="__GRAPH_DATA_FILE__"></script>
</head>
<body>
<header>
  <h1>__GRAPH_TITLE__</h1>
  <input id="search" type="search" placeholder="Search task/job/workflow" />
  <select id="relationFilter" title="Relation filter">
    <option value="all">All relations</option>
    <option value="dependencies">Dependencies</option>
    <option value="contains">Containers</option>
    <option value="triggers">Triggers</option>
    <option value="runtime">Runtime</option>
    <option value="calendars">Calendars</option>
    <option value="commands">Commands</option>
    <option value="variables">Variables</option>
    <option value="files">Files</option>
    <option value="other">Other</option>
  </select>
  <select id="statusFilter" title="Status filter">
    <option value="all">All statuses</option>
    <option value="problems">Problems</option>
    <option value="critical">Critical</option>
    <option value="missing">Missing</option>
    <option value="commands">Command diffs</option>
    <option value="syntax">Syntax only</option>
    <option value="semantic">Semantic mismatch</option>
    <option value="collisions">Collisions</option>
  </select>
  <button id="showProblems">Problems</button>
  <button id="showCritical">Critical</button>
  <button id="showMissing">Missing</button>
  <button id="showAll">Show all</button>
  <button id="collapse">Collapse groups</button>
  <button id="expand">Expand groups</button>
  <button id="dir">Direction: LR</button>
  <button id="fit">Fit</button>
  <div class="stats">
    <span>Groups <b id="nGroups">0</b></span>
    <span>Jobs <b id="nJobs">0</b></span>
    <span>Edges <b id="nEdges">0</b></span>
    <span>Wheel to zoom, drag to pan</span>
  </div>
</header>
<div class="layout">
  <main id="graphWrap">
    <div id="cy"></div>
    <div id="runtimeError" class="runtime-error"></div>
  </main>
  <aside>
    <div class="panel-head">
      <div id="pTitle" class="panel-title">Overview</div>
      <div id="pSub" class="panel-sub"></div>
    </div>
    <div id="pBody" class="panel-body"></div>
  </aside>
</div>
<script>
(function(){
'use strict';
const DATA = window.GRAPH_DATA || {metadata:{}, groups:[], jobs:[], edges:[], warnings:[]};
const $ = id => document.getElementById(id);
const hasComparisonStatuses = !!(DATA.metadata && DATA.metadata.statuses && Object.keys(DATA.metadata.statuses).length);
const quickFilters = ['showProblems', 'showCritical', 'showMissing', 'showAll'];
if(!hasComparisonStatuses){
  for(const id of ['showProblems', 'showCritical', 'showMissing']) $(id).style.display = 'none';
}
if(typeof window.cytoscape !== 'function'){
  $('runtimeError').style.display = 'block';
  $('runtimeError').textContent = 'Cytoscape.js runtime was not loaded. Keep cytoscape.min.js next to this HTML file.';
  return;
}

let expanded = false;
let direction = 'LR';
let activeStatusFilter = 'all';
let visibleCategories = new Set(['all']);
let selectedId = null;
let highlighted = new Set();
let faded = new Set();
let cy = null;

const groupById = Object.fromEntries((DATA.groups || []).map(g => [g.id, g]));
const jobById = Object.fromEntries((DATA.jobs || []).map(j => [j.id, j]));
const nodeById = {...groupById, ...jobById};
const edgeById = Object.fromEntries((DATA.edges || []).map(e => [e.id, e]));
const outEdges = {};
const inEdges = {};
for(const e of DATA.edges || []){
  (outEdges[e.source] ||= []).push(e);
  (inEdges[e.target] ||= []).push(e);
}

function escapeHtml(value){
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function text(value, max=28){
  const s = String(value ?? '');
  return s.length > max ? s.slice(0, max - 1) + '...' : s;
}
function kindColor(kind){
  return {task:'#1c7ed6', box:'#7048e8', workflow:'#7048e8', agent:'#2f9e44', calendar:'#e8590c', command:'#495057', script:'#495057', file_watcher:'#1098ad', file:'#1098ad', variable:'#d6336c'}[kind] || '#868e96';
}
function statusColor(status){
  return {matched:'#2f9e44', missing_in_stonebranch:'#e03131', missing_in_jil:'#1c7ed6', missing_critical_in_stonebranch:'#c92a2a', missing_critical_in_jil:'#364fc7', command_syntax_diff_only:'#f08c00', command_semantic_mismatch:'#c92a2a', condition_mismatch:'#f08c00', normalized_key_collision:'#862e9c', stonebranch_only:'#1c7ed6', jil_only:'#e03131'}[status] || null;
}
function edgeColor(cat, status){
  return statusColor(status) || {dependencies:'#e03131', contains:'#7048e8', triggers:'#f08c00', runtime:'#2f9e44', calendars:'#e8590c', commands:'#495057', variables:'#d6336c', files:'#1098ad'}[cat] || '#868e96';
}
function isProblemStatus(status){
  return !!status && !['matched','stonebranch_only','jil_only'].includes(status);
}
function statusMatches(status, filter=activeStatusFilter){
  if(filter === 'all') return true;
  if(filter === 'problems') return isProblemStatus(status);
  if(filter === 'missing') return ['missing_in_stonebranch','missing_in_jil','missing_critical_in_stonebranch','missing_critical_in_jil'].includes(status);
  if(filter === 'critical') return ['missing_critical_in_stonebranch','missing_critical_in_jil','command_semantic_mismatch','normalized_key_collision'].includes(status);
  if(filter === 'commands') return ['command_syntax_diff_only','command_semantic_mismatch'].includes(status);
  if(filter === 'syntax') return status === 'command_syntax_diff_only';
  if(filter === 'semantic') return status === 'command_semantic_mismatch';
  if(filter === 'collisions') return status === 'normalized_key_collision';
  return true;
}
function label(x){ return x.label || x.name || x.id; }
function metaRows(obj){
  return Object.entries(obj || {})
    .filter(([,v]) => v !== null && v !== undefined && v !== '')
    .map(([k,v]) => `<div class="kv"><span>${escapeHtml(k)}</span><span>${escapeHtml(String(v))}</span></div>`)
    .join('');
}
function copyButton(value, label='Copy'){
  return value ? `<button class="copy-btn" data-copy="${escapeHtml(value)}">${escapeHtml(label)}</button>` : '';
}
function copyable(value){
  return value ? `<code class="copyable">${escapeHtml(value)}</code>` : '<span class="placeholder">not available</span>';
}
function copyText(value){
  if(!value) return;
  if(navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(value).catch(()=>{});
}
function groupHasMatchingChild(groupId){
  return (DATA.jobs || []).some(j => j.group === groupId && statusMatches(j.status));
}
function nodeMatchesCurrentStatus(n){
  if(activeStatusFilter === 'all') return true;
  if(statusMatches(n.status)) return true;
  if(groupById[n.id] && groupHasMatchingChild(n.id)) return true;
  return false;
}
function visibleNodes(){
  const base = expanded || !(DATA.groups || []).length ? [...DATA.groups, ...DATA.jobs] : DATA.groups.slice();
  return base
    .map(n => ({...n, type: groupById[n.id] ? 'group' : 'job'}))
    .filter(n => nodeMatchesCurrentStatus(n));
}
function visibleEdges(){
  const nodes = new Set(visibleNodes().map(n => n.id));
  return (DATA.edges || []).filter(e => {
    if(!nodes.has(e.source) || !nodes.has(e.target)) return false;
    if(activeStatusFilter !== 'all' && e.status && !statusMatches(e.status) && !statusMatches(nodeById[e.source]?.status) && !statusMatches(nodeById[e.target]?.status)) return false;
    if(!expanded && (DATA.groups || []).length && e.category !== 'contains') return false;
    if(visibleCategories.has('all')) return true;
    return visibleCategories.has(e.category);
  });
}
function rankedPositions(nodes, edges){
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  const indegree = Object.fromEntries(nodes.map(n => [n.id, 0]));
  const outgoing = Object.fromEntries(nodes.map(n => [n.id, []]));
  for(const e of edges){
    if(byId[e.source] && byId[e.target]){
      outgoing[e.source].push(e.target);
      indegree[e.target] = (indegree[e.target] || 0) + 1;
    }
  }
  const q = nodes.filter(n => !indegree[n.id]).sort((a,b)=>a.id.localeCompare(b.id)).map(n=>n.id);
  const rank = Object.fromEntries(nodes.map(n => [n.id, 0]));
  const seen = new Set(q);
  while(q.length){
    const id = q.shift();
    for(const t of outgoing[id] || []){
      rank[t] = Math.max(rank[t] || 0, (rank[id] || 0) + 1);
      indegree[t] -= 1;
      if(indegree[t] <= 0 && !seen.has(t)){ seen.add(t); q.push(t); }
    }
  }
  const buckets = {};
  for(const n of nodes){ (buckets[rank[n.id] || 0] ||= []).push(n); }
  const positions = {};
  const layerGap = expanded ? 240 : 190;
  const nodeGap = expanded ? 92 : 78;
  Object.keys(buckets).map(Number).sort((a,b)=>a-b).forEach(r => {
    buckets[r]
      .sort((a,b)=>(a.group||a.parent||'').localeCompare(b.group||b.parent||'') || a.id.localeCompare(b.id))
      .forEach((n,i) => {
        positions[n.id] = direction === 'LR'
          ? {x:r*layerGap, y:i*nodeGap}
          : {x:i*nodeGap*1.7, y:r*layerGap*.78};
      });
  });
  return positions;
}
function toCytoscapeElements(){
  const nodes = visibleNodes();
  const nodeIds = new Set(nodes.map(n => n.id));
  const edges = visibleEdges();
  const cyNodes = nodes.map(n => {
    const data = {
      ...n,
      label: text(label(n), n.type === 'group' ? 22 : 18),
      fullLabel: label(n),
      color: statusColor(n.status) || kindColor(n.kind),
      borderColor: statusColor(n.status) || '#fff'
    };
    const parent = expanded ? (n.parent || n.group) : null;
    if(parent && nodeIds.has(parent)) data.parent = parent;
    return {group:'nodes', data, classes:`${n.type} ${isProblemStatus(n.status) ? 'problem' : ''}`};
  });
  const cyEdges = edges.map(e => ({
    group:'edges',
    data:{...e, label:text(e.relation, 24), color:edgeColor(e.category, e.status)},
    classes:`${e.category || 'other'} ${isProblemStatus(e.status) ? 'problem' : ''}`
  }));
  return {nodes, edges, elements:[...cyNodes, ...cyEdges]};
}
function layoutOptions(nodes, edges){
  const positions = rankedPositions(nodes, edges);
  return {
    name:'preset',
    positions: node => positions[node.id()] || {x:0, y:0},
    fit:true,
    padding:45,
    animate:false
  };
}
function buildCy(){
  const graph = toCytoscapeElements();
  if(cy) cy.destroy();
  cy = window.cytoscape({
    container:$('cy'),
    elements:graph.elements,
    layout:layoutOptions(graph.nodes, graph.edges),
    wheelSensitivity:0.18,
    minZoom:0.08,
    maxZoom:3.5,
    style:[
      {selector:'node', style:{'background-color':'data(color)','border-color':'data(borderColor)','border-width':2,'label':'data(label)','color':'#fff','font-size':11,'font-weight':700,'text-valign':'center','text-halign':'center','text-wrap':'wrap','text-max-width':112,'text-outline-color':'data(color)','text-outline-width':2}},
      {selector:'node.group', style:{'shape':'round-rectangle','width':128,'height':58,'background-opacity':0.9,'padding':'18px','text-max-width':116}},
      {selector:'node.job', style:{'shape':'ellipse','width':54,'height':54,'text-max-width':70}},
      {selector:':parent', style:{'background-opacity':0.12,'border-width':2,'border-style':'dashed','text-valign':'top','text-margin-y':-6,'color':'#334155','text-outline-width':0}},
      {selector:'edge', style:{'width':2,'line-color':'data(color)','target-arrow-color':'data(color)','target-arrow-shape':'triangle','curve-style':'bezier','label':'data(label)','font-size':9,'color':'#475569','text-background-color':'#fff','text-background-opacity':0.75,'text-background-padding':2,'text-rotation':'autorotate'}},
      {selector:'.highlight', style:{'z-index':999,'border-width':5,'width':4,'opacity':1}},
      {selector:'.faded', style:{'opacity':0.16}},
      {selector:':selected', style:{'border-color':'#111827','border-width':4,'line-color':'#111827','target-arrow-color':'#111827'}}
    ]
  });
  cy.on('tap', 'node', ev => selectNode(ev.target.id()));
  cy.on('tap', 'edge', ev => selectEdge(ev.target.id()));
  cy.on('tap', ev => { if(ev.target === cy) clearSelection(); });
  updateCounts();
  applyClasses();
}
function relayout(){
  const graph = toCytoscapeElements();
  cy.elements().remove();
  cy.add(graph.elements);
  cy.layout(layoutOptions(graph.nodes, graph.edges)).run();
  cy.fit(undefined, 45);
  updateCounts();
  applyClasses();
}
function updateCounts(){
  const nodes = visibleNodes();
  $('nGroups').textContent = nodes.filter(n => n.type === 'group').length;
  $('nJobs').textContent = nodes.filter(n => n.type !== 'group').length;
  $('nEdges').textContent = visibleEdges().length;
}
function applyClasses(){
  if(!cy) return;
  cy.elements().removeClass('highlight faded');
  for(const id of highlighted){ const ele = cy.getElementById(id); if(ele.length) ele.addClass('highlight'); }
  for(const id of faded){ const ele = cy.getElementById(id); if(ele.length) ele.addClass('faded'); }
}
function fit(){
  updateCounts();
  if(cy) cy.fit(undefined, 45);
}
function edgeLabel(e){ return `${e.source} -> ${e.relation} -> ${e.target}`; }
function evidenceSummary(e){
  return [e.status, e.category, e.evidence_file, e.evidence_key, e.evidence_path].filter(Boolean).join(' | ');
}
function bindPanelActions(){
  $('pBody').querySelectorAll('[data-node]').forEach(el => el.addEventListener('click', ev => { ev.stopPropagation(); const target=el.getAttribute('data-node'); if(target) selectNode(target); }));
  $('pBody').querySelectorAll('[data-edge]').forEach(el => el.addEventListener('click', ev => { ev.stopPropagation(); const target=el.getAttribute('data-edge'); if(target) selectEdge(target); }));
  $('pBody').querySelectorAll('[data-copy]').forEach(el => el.addEventListener('click', ev => { ev.stopPropagation(); copyText(el.getAttribute('data-copy')); el.textContent='Copied'; setTimeout(()=>{ el.textContent='Copy'; }, 900); }));
}
function statusRows(){
  const statuses = DATA.metadata?.statuses || {};
  const entries = Object.entries(statuses);
  if(!entries.length) return '<div class="placeholder">No comparison statuses in this source graph.</div>';
  return '<div class="status-grid">' + entries.map(([k,v]) => `<span class="status-chip"><i class="sw" style="background:${statusColor(k) || '#868e96'}"></i>${escapeHtml(k)}</span><b>${escapeHtml(v)}</b>`).join('') + '</div>';
}
function visibleSummaryRows(){
  return metaRows({
    status_filter: activeStatusFilter,
    relation_filter: [...visibleCategories].join(','),
    visible_nodes: visibleNodes().length,
    visible_edges: visibleEdges().length,
    expanded_groups: expanded
  });
}
function showOverview(){
  $('pTitle').textContent = 'Overview';
  $('pSub').textContent = `${DATA.metadata?.source_system || ''} ${DATA.metadata?.env || ''}`;
  const cats = DATA.metadata?.relation_categories || {};
  $('pBody').innerHTML =
    `<div class="section">Current view</div>${visibleSummaryRows()}` +
    `<div class="section">Graph</div>${metaRows(DATA.metadata)}` +
    `<div class="section">Status counts</div>${statusRows()}` +
    `<div class="section">Relation categories</div>` +
    Object.entries(cats).map(([k,v]) => `<div class="kv"><span>${escapeHtml(k)}</span><span>${escapeHtml(v)}</span></div>`).join('') +
    `<div class="section">Legend</div>` +
    `<div class="legend"><span><i class="sw" style="background:#2f9e44"></i>matched</span><span></span><span><i class="sw" style="background:#e03131"></i>missing in Stonebranch</span><span></span><span><i class="sw" style="background:#1c7ed6"></i>missing in JIL</span><span></span><span><i class="sw" style="background:#f08c00"></i>syntax/condition diff</span><span></span><span><i class="sw" style="background:#862e9c"></i>collision</span><span></span></div>` +
    `<div class="section">Large graph tips</div>` +
    `<p class="placeholder">Use Problems, Critical, Missing, status filters, and relation filters before expanding all groups. This HTML report is offline and self-contained with a bundled Cytoscape.js runtime.</p>`;
}
let currentNode = null;
function clickableEdgeList(title, edges){
  return `<div class="section">${title} <span class="pill">${edges.length}</span></div>` + (edges.length ? edges.slice(0,80).map(e => {
    const other = e.source === currentNode ? e.target : e.source;
    const arrow = e.source === currentNode ? '->' : '<-';
    return `<div class="edge-card"><div class="edge-main" data-edge="${escapeHtml(e.id)}"><span>${escapeHtml(e.relation)}</span><span>${arrow}</span><b>${escapeHtml(other)}</b></div><div class="edge-meta">${escapeHtml(evidenceSummary(e))}</div><div class="copy-row">${copyButton(edgeLabel(e), 'Copy edge')}<button class="copy-btn" data-node="${escapeHtml(other)}">Open node</button></div></div>`;
  }).join('') : '<div class="placeholder">None</div>');
}
function showNode(id){
  currentNode = id;
  const node = nodeById[id]; if(!node) return;
  $('pTitle').textContent = label(node);
  $('pSub').textContent = `${node.kind || 'node'} | ${id}`;
  const outgoing = outEdges[id] || [], incoming = inEdges[id] || [];
  $('pBody').innerHTML =
    `<div class="section">Identity</div><div class="copy-row">${copyable(id)} ${copyButton(id, 'Copy ID')}</div>` +
    `${node.graph_id ? `<div class="copy-row">${copyable(node.graph_id)} ${copyButton(node.graph_id, 'Copy graph ID')}</div>` : ''}` +
    `<div class="section">Details</div>` +
    `${metaRows({status:node.status, side:node.side, kind:node.kind, original_kind:node.original_kind, group:node.group, parent:node.parent, canonical_key:node.canonical_key, source_file:node.source_file, synthetic:node.synthetic})}` +
    `${clickableEdgeList('Outgoing', outgoing)}${clickableEdgeList('Incoming', incoming)}`;
  bindPanelActions();
}
function showEdge(edgeId){
  const e = edgeById[edgeId]; if(!e) return;
  $('pTitle').textContent = e.relation || 'Edge';
  $('pSub').textContent = `${e.source} -> ${e.target}`;
  $('pBody').innerHTML =
    `<div class="section">Edge identity</div><div class="copy-row">${copyable(edgeLabel(e))} ${copyButton(edgeLabel(e), 'Copy edge')}</div>` +
    `${e.graph_edge_id ? `<div class="copy-row">${copyable(e.graph_edge_id)} ${copyButton(e.graph_edge_id, 'Copy graph edge ID')}</div>` : ''}` +
    `<div class="section">Endpoints</div>` +
    `<div class="kv"><span>Source</span><span><span class="linkish" data-node="${escapeHtml(e.source)}">${escapeHtml(e.source)}</span></span></div>` +
    `<div class="kv"><span>Target</span><span><span class="linkish" data-node="${escapeHtml(e.target)}">${escapeHtml(e.target)}</span></span></div>` +
    `<div class="section">Evidence</div>` +
    `${metaRows({status:e.status, side:e.side, relation:e.relation, category:e.category, native_relation:e.native_relation, confidence:e.confidence, evidence_file:e.evidence_file, evidence_path:e.evidence_path, evidence_key:e.evidence_key, evidence_value:e.evidence_value})}`;
  bindPanelActions();
}
function selectNode(id){
  if(!nodeById[id]) return;
  selectedId = id;
  highlighted = new Set([id]);
  faded = new Set();
  const neighbors = new Set([id]);
  const edgeIds = new Set();
  for(const e of [...(outEdges[id]||[]), ...(inEdges[id]||[])]){
    neighbors.add(e.source);
    neighbors.add(e.target);
    edgeIds.add(e.id);
  }
  for(const n of visibleNodes()) if(!neighbors.has(n.id)) faded.add(n.id);
  for(const e of visibleEdges()) if(!edgeIds.has(e.id)) faded.add(e.id); else highlighted.add(e.id);
  if(cy && cy.getElementById(id).length){
    cy.elements().unselect();
    cy.getElementById(id).select();
    cy.animate({center:{eles:cy.getElementById(id)}, zoom:Math.max(cy.zoom(), .65)}, {duration:160});
  }
  showNode(id);
  if(window.location.hash !== '#' + encodeURIComponent(id)) window.location.hash = encodeURIComponent(id);
  applyClasses();
}
function selectEdge(edgeId){
  const e = edgeById[edgeId]; if(!e) return;
  selectedId = null;
  highlighted = new Set([edgeId, e.source, e.target]);
  faded = new Set();
  for(const n of visibleNodes()) if(n.id !== e.source && n.id !== e.target) faded.add(n.id);
  for(const edge of visibleEdges()) if(edge.id !== edgeId) faded.add(edge.id);
  if(cy && cy.getElementById(edgeId).length){
    cy.elements().unselect();
    cy.getElementById(edgeId).select();
    cy.animate({center:{eles:cy.getElementById(edgeId)}}, {duration:160});
  }
  showEdge(edgeId);
  if(window.location.hash !== '#edge=' + encodeURIComponent(edgeId)) window.location.hash = 'edge=' + encodeURIComponent(edgeId);
  applyClasses();
}
function clearSelection(){
  selectedId = null;
  highlighted = new Set();
  faded = new Set();
  if(cy) cy.elements().unselect();
  showOverview();
  if(window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);
  applyClasses();
}
function openHashTarget(){
  const hash = decodeURIComponent((window.location.hash || '').replace(/^#/, ''));
  if(!hash) return false;
  if(hash.startsWith('edge=')){
    const edgeId = hash.slice(5);
    if(edgeById[edgeId]){ expanded = true; relayout(); selectEdge(edgeId); return true; }
  }
  if(nodeById[hash]){ expanded = !!jobById[hash]; relayout(); selectNode(hash); return true; }
  return false;
}
function setStatusFilter(value){
  activeStatusFilter = value;
  $('statusFilter').value = value;
  $('statusFilter').classList.toggle('active', value !== 'all');
  for(const id of quickFilters) $(id).classList.remove('active');
  if(value === 'problems') $('showProblems').classList.add('active');
  if(value === 'critical') $('showCritical').classList.add('active');
  if(value === 'missing') $('showMissing').classList.add('active');
  if(value === 'all') $('showAll').classList.add('active');
  clearSelection();
  relayout();
}

$('fit').onclick = fit;
$('expand').onclick = () => { expanded = true; clearSelection(); relayout(); fit(); };
$('collapse').onclick = () => { expanded = false; clearSelection(); relayout(); fit(); };
$('dir').onclick = () => {
  direction = direction === 'LR' ? 'TB' : 'LR';
  $('dir').textContent = `Direction: ${direction}`;
  relayout();
};
$('statusFilter').onchange = e => setStatusFilter(e.target.value);
$('showProblems').onclick = () => { expanded = true; visibleCategories = new Set(['all']); $('relationFilter').value = 'all'; setStatusFilter('problems'); };
$('showCritical').onclick = () => { expanded = true; visibleCategories = new Set(['all']); $('relationFilter').value = 'all'; setStatusFilter('critical'); };
$('showMissing').onclick = () => { expanded = true; visibleCategories = new Set(['all']); $('relationFilter').value = 'all'; setStatusFilter('missing'); };
$('showAll').onclick = () => { visibleCategories = new Set(['all']); $('relationFilter').value = 'all'; setStatusFilter('all'); };
$('relationFilter').onchange = e => { visibleCategories = new Set([e.target.value]); clearSelection(); relayout(); };
$('search').oninput = e => {
  const q = e.target.value.trim().toLowerCase();
  highlighted = new Set();
  faded = new Set();
  selectedId = null;
  if(q){
    for(const n of visibleNodes()){
      const hay = `${label(n)} ${n.id} ${n.kind}`.toLowerCase();
      if(hay.includes(q)) highlighted.add(n.id); else faded.add(n.id);
    }
  }
  applyClasses();
};
window.addEventListener('resize', () => { if(cy) cy.resize(); fit(); });
buildCy();
showOverview();
if(!openHashTarget()) showOverview();
window.addEventListener('hashchange', () => { if(!openHashTarget()) clearSelection(); });
})();
</script>
</body>
</html>
'''
