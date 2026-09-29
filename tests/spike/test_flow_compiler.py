"""Spike S3: flow compiler round-trip + catalog validation tests (pytest)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.engine.catalog import validate_graph  # noqa: E402
from backend.nodebridge import flow_compiler as fc  # noqa: E402

WORKER = "http://127.0.0.1:8747"
TOKEN = "test-token"


def client_followup_graph() -> dict:
    return {
        "id": "wf_client_followup",
        "triggers": [{"type": "schedule", "cron": "0 9 * * MON-FR"}],
        "nodes": [
            {"id": "src", "type": "file.read_table", "params": {"alias": "sample-tracking-file", "max_rows": 1000}},
            {"id": "due", "type": "data.filter", "params": {"from": "src.rows", "where": "due"}},
            {"id": "upd", "type": "file.update_rows",
             "params": {"alias": "sample-tracking-file", "filename": "clients.csv",
                        "set": "Draft prepared", "purpose": "followup"}},
            {"id": "drft", "type": "draft.create",
             "params": {"record_key": "{{row}}", "template_id": "followup_en", "destination": "in_app"}},
            {"id": "note", "type": "notify.desktop", "params": {"title_key": "run_done"}},
        ],
        "edges": [
            {"from": "src", "to": "due"}, {"from": "due", "to": "upd"},
            {"from": "upd", "to": "drft"}, {"from": "drft", "to": "note"},
        ],
    }


def test_valid_graph_passes_validation():
    assert validate_graph(client_followup_graph()) == []


def test_unknown_node_type_rejected():
    graph = client_followup_graph()
    graph["nodes"].append({"id": "x", "type": "shell.exec", "params": {"cmd": "rm -rf /"}})
    errors = validate_graph(graph)
    assert any("unknown node type" in e for e in errors)


def test_unknown_param_rejected():
    graph = client_followup_graph()
    graph["nodes"][0]["params"]["evil"] = "x"
    assert any("unknown param" in e for e in validate_graph(graph))


def test_cycle_rejected():
    graph = client_followup_graph()
    graph["edges"].append({"from": "note", "to": "src"})
    assert any("cycle" in e for e in validate_graph(graph))


def test_compile_produces_node_red_flow():
    flow = fc.compile_graph(client_followup_graph(), worker_url=WORKER, worker_token=TOKEN,
                            flow_label="Client Follow-up")
    types = [n["type"] for n in flow["nodes"]]
    assert "inject" in types and "catch" in types
    for bridge in ["as-read-due", "as-update-row", "as-draft-create", "as-notify"]:
        assert bridge in types
    # every bridge node carries the worker token (S3: Node-RED holds no secrets of its own)
    for n in flow["nodes"]:
        if n["type"].startswith("as-"):
            assert n["workerToken"] == TOKEN
            assert n["workerUrl"] == WORKER


def test_compile_rejects_unmapped_types():
    graph = client_followup_graph()
    graph["nodes"].append({"id": "py", "type": "python.code", "params": {"artifact": "x"}})
    try:
        fc.compile_graph(graph, worker_url=WORKER, worker_token=TOKEN, flow_label="x")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "python.code" in str(exc)


def test_round_trip_normalizes_to_same_graph():
    graph = client_followup_graph()
    flow = fc.compile_graph(graph, worker_url=WORKER, worker_token=TOKEN, flow_label="RT")
    rebuilt = fc.flows_to_graph(flow)
    assert [n["type"] for n in rebuilt["nodes"]] == [
        "file.read_table+data.filter", "file.update_rows", "draft.create", "notify.desktop"]
    assert len(rebuilt["edges"]) == 3
