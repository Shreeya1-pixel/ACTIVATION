"""Node catalog + graph validation.

The catalog is the single source of truth for node types, params, and permissions.
validate_graph() rejects unknown nodes/params and cycles BEFORE anything can deploy (S9 posture:
invalid structure never reaches the runtime). This is the same catalog the editors and the
flow compiler (Milestone B) will code against.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_ROWS = 1000  # contracts.md parser budget


@dataclass(frozen=True)
class NodeSpec:
    type: str
    params: dict[str, type]  # name -> python type
    required: tuple[str, ...]
    outputs: tuple[str, ...]
    permission: str | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)


CATALOG: dict[str, NodeSpec] = {
    spec.type: spec
    for spec in [
        NodeSpec("file.read_table", {"alias": str, "filename": str, "max_rows": int}, ("alias",), ("rows",), "read-content",
                 ("unsupported-format", "too-large", "bad-ids")),
        NodeSpec("data.filter", {"from": str, "where": str}, ("from", "where"), ("rows",)),
        NodeSpec("file.update_rows", {"alias": str, "filename": str, "set": str, "purpose": str,
                                       "key_field": str},
                 ("alias", "filename", "set", "purpose"), ("updated",), "write-target",
                 ("lock", "conflict", "idempotent-claimed")),
        NodeSpec("draft.create", {"record_key": str, "template_id": str, "destination": str},
                 ("record_key", "template_id", "destination"), ("draft_id",), "draft-create",
                 ("claimed", "invalid-row")),
        NodeSpec("notify.desktop", {"title_key": str}, ("title_key",), ("notified",), "notify"),
        # Roadmap §E: control-flow + human-gate nodes (same validation as the rest).
        NodeSpec("control.branch", {"condition": str}, ("condition",), ("taken",)),
        NodeSpec("approval.gate", {"prompt": str}, ("prompt",), ("gate_id",), "activate"),
    ]
}

VALID_ON_FAIL = {"halt", "continue", "error_branch"}


def validate_graph(graph: dict) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors: list[str] = []
    nodes = graph.get("nodes", [])
    node_ids = [n.get("id") for n in nodes]
    if len(node_ids) != len(set(node_ids)):
        errors.append("duplicate node ids")
    known = set()
    for node in nodes:
        nid = node.get("id")
        ntype = node.get("type")
        if not nid or not ntype:
            errors.append(f"node missing id/type: {node!r}")
            continue
        spec = CATALOG.get(ntype)
        if spec is None:
            errors.append(f"unknown node type: {ntype}")
            continue
        known.add(nid)
        params = node.get("params", {})
        for name in spec.required:
            if name not in params:
                errors.append(f"{nid}: missing required param '{name}'")
        for name, value in params.items():
            if name not in spec.params:
                errors.append(f"{nid}: unknown param '{name}' for {ntype}")
            elif spec.params[name] is int and not isinstance(value, int):
                errors.append(f"{nid}: param '{name}' must be int")
            elif spec.params[name] is str and not isinstance(value, str):
                errors.append(f"{nid}: param '{name}' must be str")
        if node.get("on_fail") not in (None, *VALID_ON_FAIL):
            errors.append(f"{nid}: invalid on_fail {node.get('on_fail')!r}")
        retry = node.get("retry")
        if retry is not None:
            if not isinstance(retry, dict) or not isinstance(retry.get("attempts", 0), int) or retry.get("attempts", 0) > 3:
                errors.append(f"{nid}: retry.attempts must be int <= 3")
    edges = graph.get("edges", [])
    for edge in edges:
        if edge.get("from") not in known or edge.get("to") not in known:
            errors.append(f"edge references unknown node: {edge!r}")
    # Cycle detection (Kahn's algorithm).
    indegree = {nid: 0 for nid in known}
    adjacency: dict[str, list[str]] = {nid: [] for nid in known}
    for edge in edges:
        f, t = edge.get("from"), edge.get("to")
        if f in known and t in known:
            adjacency[f].append(t)
            indegree[t] += 1
    queue = [nid for nid, deg in indegree.items() if deg == 0]
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for nxt in adjacency[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if visited != len(known):
        errors.append("graph contains a cycle")
    return errors
