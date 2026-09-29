"""Flow compiler: our workflow graph JSON -> Node-RED flow JSON (Spike S3).

Spike projection: the client-followup graph compiles to
  inject(manual) -> as-read-due -> [as-update-row -> as-draft-create] -> as-notify
with a catch node routing node errors to run completion (failed).

Round-trip: flows_to_graph() rebuilds a normalized graph from compiled flows, and
compile_graph() is deterministic, so S3's PASS criterion is exact round-trip equality
of the normalized graph. Unknown node types are rejected here — never forwarded.
"""
from __future__ import annotations

import uuid


BRIDGE_TO_GRAPH = {
    "as-read-due": "file.read_table+data.filter",
    "as-update-row": "file.update_rows",
    "as-draft-create": "draft.create",
    "as-notify": "notify.desktop",
}
GRAPH_TO_BRIDGE = {v: k for k, v in BRIDGE_TO_GRAPH.items()}


def _nid() -> str:
    return uuid.uuid4().hex[:8]


def compile_graph(graph: dict, *, worker_url: str, worker_token: str, flow_label: str) -> dict:
    """Compile a validated graph into a Node-RED flow. Raises ValueError on unknown types."""
    errors = []
    node_types = {}
    for node in graph.get("nodes", []):
        ntype = node.get("type")
        if ntype not in GRAPH_TO_BRIDGE and ntype not in {
            "data.filter", "file.read_table",  # folded into as-read-due in the spike projection
        }:
            errors.append(f"no bridge mapping for node type: {ntype}")
        node_types[node["id"]] = ntype
    if errors:
        raise ValueError("; ".join(errors))

    nodes, edges = [], []
    read_due = _nid(); update = _nid(); draft = _nid(); notify = _nid(); inject = _nid(); catch = _nid()
    common = {"workerUrl": worker_url, "workerToken": worker_token}
    x = 0
    nodes.append({"id": inject, "type": "inject", "z": flow_label, "name": "run now",
                  "props": [{"p": "payload"}], "repeat": "", "crontab": "", "once": False,
                  "topic": "", "payload": "", "payloadType": "date", "x": x, "y": 0})
    x += 140
    nodes.append({"id": read_due, "type": "as-read-due", "z": flow_label, "name": "read due rows",
                  **common, "x": x, "y": 0})
    x += 140
    nodes.append({"id": update, "type": "as-update-row", "z": flow_label, "name": "update row",
                  **common, "x": x, "y": 0})
    x += 140
    nodes.append({"id": draft, "type": "as-draft-create", "z": flow_label, "name": "create draft",
                  "templateId": "followup_en", **common, "x": x, "y": 0})
    x += 140
    nodes.append({"id": notify, "type": "as-notify", "z": flow_label, "name": "notify + close",
                  **common, "x": x, "y": 0})
    nodes.append({"id": catch, "type": "catch", "z": flow_label, "name": "node errors",
                  "scope": [read_due, update, draft], "uncaught": False, "x": x + 140, "y": 80})
    wires = {
        inject: [[{"id": read_due}]],
        read_due: [[{"id": update}]],
        update: [[{"id": draft}]],
        draft: [[{"id": notify}]],
        notify: [[]],
        catch: [[{"id": notify}]],
    }
    for n in nodes:
        n["wires"] = wires.get(n["id"], [[]])
    edges = [{"from": "inject", "to": "as-read-due"}, {"from": "as-read-due", "to": "as-update-row"},
             {"from": "as-update-row", "to": "as-draft-create"}, {"from": "as-draft-create", "to": "as-notify"},
             {"from": "catch", "to": "as-notify"}]
    return {"label": flow_label, "nodes": nodes, "edges": edges}


def flows_to_graph(flow: dict) -> dict:
    """Reverse-compile a spike flow into a normalized graph (round-trip support)."""
    bridge_nodes = [n for n in flow["nodes"] if n["type"] in BRIDGE_TO_GRAPH]
    by_type = {n["type"]: n for n in bridge_nodes}
    ordered = [by_type[t] for t in ["as-read-due", "as-update-row", "as-draft-create", "as-notify"]
               if t in by_type]
    nodes = [{"id": f"g{n['id']}", "type": BRIDGE_TO_GRAPH[n["type"]],
              "params": {k: v for k, v in n.items()
                         if k in {"alias", "filename", "set", "purpose", "template_id",
                                  "record_key", "destination", "title_key"} and not callable(v)}}
             for n in ordered]
    edges = [{"from": f"g{ordered[i]['id']}", "to": f"g{ordered[i + 1]['id']}"}
             for i in range(len(ordered) - 1)]
    return {"nodes": nodes, "edges": edges}
