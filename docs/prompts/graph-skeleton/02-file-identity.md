# Agent prompt — Item 2: File identity canonicalization

You are implementing Item 2 of `GRAPH_SKELETON_IMPLEMENTATION_PLAN.md` (package `stonebranch_graph`). Goal: one physical file path ⇒ one `KIND_FILE` node, regardless of quoting/case/separators/date stamps.

## Token budget rules
Read ONLY: `stonebranch_graph/core.py` (functions `normalize_name`, `make_node_id`, `make_canonical_key`), `stonebranch_graph/parsers/autosys_jil.py` method `_add_watch_file_edge`, and grep `stonebranch_json.py` for `KIND_FILE` / `watch_file` usages with context. Do not read html_graph, compare, tui, metrics. Minimal diff.

## Task
1. Create `stonebranch_graph/file_identity.py`:
   ```python
   @dataclass(frozen=True)
   class FileIdentity:
       key: str            # canonical key used for node identity
       pattern: str        # stem pattern with {date}/{seq} placeholders
       raw: str
       unresolved_vars: tuple[str, ...]
   def canonical_file_key(raw: str, variables: dict[str, str] | None = None) -> FileIdentity: ...
   ```
   Rules, applied in order: strip surrounding quotes/whitespace; substitute `$VAR`, `${VAR}`, `%VAR%` when present in `variables`, else record in `unresolved_vars` and keep token as `{var:NAME}`; replace `\` with `/`; collapse duplicate slashes; case-fold the whole path if it looks Windows-style (drive letter or contained `\`); replace date-like stamps (`20260701`, `2026-07-01`, `01JUL2026`) with `{date}` and 2–4 digit trailing sequence suffixes (`.001`, `_01`) with `{seq}` — only in the basename, only when surrounded by separators `._-` or extension boundaries. `key = pattern` (identity by pattern).
2. Wire it in: in `autosys_jil.py::_add_watch_file_edge` and in the Stonebranch parser's `watch_file` handling, name the `KIND_FILE` node by `FileIdentity.key`, and store `{"raw_path": raw, "path_pattern": pattern, "unresolved_vars": [...]}` in node metadata (merge-safe: `Graph.add_node` already merges metadata).

## Acceptance
Create `tests/test_file_identity.py` (pytest, stdlib only) with cases: `"C:\\Data\\Out\\Report_20260701.CSV"` ≡ `c:/data/out/report_{date}.csv`; quoted path; `%DATE%` unknown var; `${ENV}/in/file.txt` with resolvable var; unix path untouched case-wise; `.001` seq. Run `python -m pytest tests/test_file_identity.py -q` — green.

Do not implement producer inference (Item 3). Report: new file line count + test result.
