"""Pre-run preflight: check the world still looks like it did at approval time.

Before any effect is attempted, every file a workflow reads or writes must resolve and
open, and every column its filters and updates reference must still exist. A renamed
column or a missing file stops the run BEFORE anything is written and hands the task
back to a person, instead of failing half-way through.
"""
from __future__ import annotations

import re

from backend.engine import rows
from backend.security import safeio

_ROW_ATTR = re.compile(r"\brow\.([A-Za-z_][A-Za-z0-9_]*)")
_ROW_ITEM = re.compile(r"\brow\[\s*['\"]([^'\"]+)['\"]\s*\]")
_ROW_METHODS = {"get", "items", "keys", "values"}


def referenced_columns(expr: str) -> set[str]:
    cols = {m for m in _ROW_ATTR.findall(expr or "") if m not in _ROW_METHODS}
    return cols | set(_ROW_ITEM.findall(expr or ""))


def _required_columns(graph: dict) -> set[str]:
    cols: set[str] = set()
    for node in graph.get("nodes", []):
        p = node.get("params", {}) or {}
        ntype = node.get("type", "")
        if ntype == "data.filter":
            cols |= referenced_columns(p.get("where", ""))
        elif ntype == "control.branch":
            cols |= referenced_columns(p.get("condition", ""))
        elif ntype == "file.update_rows":
            for part in (p.get("set", "") or "").split(";"):
                field = part.partition("=")[0].strip()
                if field:
                    cols.add(field)
            if p.get("key_field"):
                cols.add(p["key_field"])
    return cols


def check(graph: dict, filename: str) -> dict:
    """Return {"ok": bool, "problems": [...], "checked": {...}}. Never writes."""
    problems: list[str] = []
    checked_files: list[str] = []
    header: set[str] | None = None
    for node in graph.get("nodes", []):
        ntype = node.get("type", "")
        if ntype not in ("file.read_table", "file.update_rows"):
            continue
        p = node.get("params", {}) or {}
        alias = p.get("alias", "sample-tracking-file")
        fn = p.get("filename", filename)
        label = f"{alias}/{fn}"
        if label in checked_files:
            continue
        checked_files.append(label)
        try:
            path = safeio.resolve_resource(alias, fn)
        except PermissionError as exc:
            problems.append(f"{node.get('id')}: {exc}")
            continue
        if not path.is_file():
            problems.append(f"{node.get('id')}: file missing: {label}")
            continue
        if ntype == "file.read_table" and header is None:
            try:
                table = rows.read_table(alias, fn)
            except Exception as exc:  # noqa: BLE001 - any parse failure is a preflight stop
                problems.append(f"{node.get('id')}: cannot read {label}: {str(exc)[:160]}")
                continue
            if table:
                from backend.engine.graph_build import _safe_ident
                header = set(table[0].keys()) | {_safe_ident(k) for k in table[0]}
    required = _required_columns(graph)
    missing_cols: list[str] = []
    if header is not None:
        missing_cols = sorted(required - header)
        if missing_cols:
            problems.append(f"missing column(s) no longer in the file: {', '.join(missing_cols)}")
    return {"ok": not problems, "problems": problems,
            "checked": {"files": checked_files, "required_columns": sorted(required),
                        "missing_columns": missing_cols}}
