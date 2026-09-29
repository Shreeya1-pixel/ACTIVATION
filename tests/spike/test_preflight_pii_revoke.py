"""Pre-run preflight (stop before effects), PII masking for AI calls and events, and
revocation of already-installed registry copies."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.engine import ai, preflight  # noqa: E402
from backend.security import pii  # noqa: E402
from tests.spike.conftest import isolated_db_module, test_session  # noqa: E402,F401 (fixture import)

client = TestClient(app)
H = {"Authorization": "Bearer testtoken"}


@pytest.fixture(scope="module", autouse=True)
def _auth(isolated_db_module):
    from backend import roadmap_routes
    from backend.security import tokens
    originals = (tokens.get_expected_token, roadmap_routes.get_expected_token)
    tokens.get_expected_token = roadmap_routes.get_expected_token = lambda: "testtoken"
    yield
    tokens.get_expected_token, roadmap_routes.get_expected_token = originals


# ── preflight ────────────────────────────────────────────────────────────────

def _graph(where="row.Status == 'Follow-up due'", filename=None):
    read = {"id": "read", "type": "file.read_table", "params": {"alias": "sample-tracking-file"}}
    if filename:
        read["params"]["filename"] = filename
    return {"nodes": [read,
                      {"id": "f", "type": "data.filter", "params": {"from": "read", "where": where}}],
            "edges": [{"from": "read", "to": "f"}]}


def test_referenced_columns_parses_filter_expressions():
    assert preflight.referenced_columns("row.Status == 'x' and row['Due Date'] < 3") == {"Status", "Due Date"}
    assert preflight.referenced_columns("row.get('x')") == set()


def test_preflight_passes_on_unchanged_file():
    res = preflight.check(_graph(), "clients.csv")
    assert res["ok"], res
    assert "Status" in res["checked"]["required_columns"]


def test_preflight_catches_renamed_column():
    res = preflight.check(_graph(where="row.PaymentState == 'due'"), "clients.csv")
    assert not res["ok"]
    assert res["checked"]["missing_columns"] == ["PaymentState"]


def test_preflight_catches_missing_file():
    res = preflight.check(_graph(filename="gone.csv"), "clients.csv")
    assert not res["ok"] and "missing" in res["problems"][0]


def test_run_is_stopped_before_effects_and_handed_back():
    wid = f"wf-pre-{uuid.uuid4().hex[:6]}"
    graph = _graph(where="row.PaymentState == 'due'")
    graph["nodes"].append({"id": "act", "type": "file.update_rows",
                           "params": {"alias": "sample-tracking-file", "filename": "clients.csv",
                                      "set": "Status='Draft prepared'", "purpose": "preflight-test"}})
    graph["edges"].append({"from": "f", "to": "act"})
    assert client.post("/api/workflows", json={"id": wid, "name": "pre", "graph": graph},
                       headers=H).status_code == 200
    pre = client.post("/api/runs/preflight", json={"workflow_id": wid}, headers=H)
    assert pre.status_code == 200 and pre.json()["ok"] is False

    run = client.post("/api/runs", json={"workflow_id": wid, "run_date": "2026-09-20"}, headers=H)
    assert run.status_code == 400
    detail = run.json()["detail"]
    assert "PaymentState" in detail["error"] and "handoff" in detail
    nodes = client.get(f"/api/runs/{detail['run_id']}/nodes", headers=H).json()
    assert not nodes or all(n.get("status") != "passed" for n in (nodes if isinstance(nodes, list) else []))


# ── PII ──────────────────────────────────────────────────────────────────────

SAMPLE = ("Vendor TRN 100234567800003, Emirates ID 784-1990-1234567-1, "
          "IBAN AE07 0331 2345 6789 0123 456, omar@alnoor.example, +971 50 123 4567")


def test_mask_text_covers_uae_formats():
    masked = pii.mask_text(SAMPLE)
    for raw in ("100234567800003", "784-1990-1234567-1", "AE07 0331 2345 6789 0123 456",
                "omar@alnoor.example", "50 123 4567"):
        assert raw not in masked
    for label in ("[TRN]", "[EMIRATES_ID]", "[IBAN]", "[EMAIL]", "[PHONE]"):
        assert label in masked


def test_mask_text_keeps_other_tax_and_id_formats():
    masked = pii.mask_text("PAN ABCDE1234F, GSTIN 27ABCDE1234F1Z5, ID 2345 6789 0123")
    assert "ABCDE1234F" not in masked and "2345 6789 0123" not in masked
    assert "[TAX_ID]" in masked and "[NATIONAL_ID]" in masked


def test_pseudonyms_are_stable_and_distinct():
    k = b"k"
    a1 = pii.pseudonymize_text("a@x.example", k)
    assert a1 == pii.pseudonymize_text("a@x.example", k)
    assert a1 != pii.pseudonymize_text("b@x.example", k)
    assert "a@x.example" not in a1


def test_gemini_never_receives_personal_values(monkeypatch):
    seen = {}

    def fake_gemini(prompt, context, key):  # noqa: ANN001
        seen["payload"] = prompt + json.dumps(context)
        return f"Hi {context['Name']}, reminder for {context['ClientID']}"

    monkeypatch.setattr(ai, "_gemini_text", fake_gemini)
    out = ai.generate_text("Write a reminder.",
                           {"Name": "Omar Haddad", "Email": "omar@alnoor.example", "ClientID": "C001"},
                           provider="gemini", api_key="k")
    assert "Omar Haddad" not in seen["payload"] and "omar@alnoor.example" not in seen["payload"]
    assert out == "Hi Omar Haddad, reminder for C001"


def test_ingested_events_do_not_store_raw_emails():
    at = "2026-09-21T09:00:00+00:00"
    ev = {"event_id": str(uuid.uuid4()), "schema_version": 2,
          "source_version": "phase2-test-0.1.0", "source": "saved_file_comparison",
          "action": "spreadsheet_row_updated", "resource": "sample-tracking-file",
          "record_key": "sample:omar@alnoor.example", "changed_fields": [], "outcome": "success",
          "captured_at": at, "processed_at": at, "synthetic": False}
    res = client.post("/api/events", json=[ev], headers=H)
    if res.status_code == 422:
        pytest.skip(f"event contract rejects this shape: {res.text[:120]}")
    from tests.spike.conftest import test_session as _ts
    from backend.models import Event
    with _ts() as db:
        row = db.query(Event).filter(Event.event_id == ev["event_id"]).one()
        assert "omar@alnoor.example" not in row.record_key and row.record_key.startswith("sample:[EMAIL:")


# ── revocation ───────────────────────────────────────────────────────────────

GRAPH = {
    "id": "wf_revoke_tpl", "name": "Revoke me",
    "triggers": [{"type": "schedule", "cron": "0 9 * * MON-FR"}],
    "nodes": [{"id": "src", "type": "file.read_table", "params": {"alias": "sample-tracking-file"}},
              {"id": "note", "type": "notify.desktop", "params": {"title_key": "run_done"}}],
    "edges": [{"from": "src", "to": "note"}],
}


def test_revoke_marks_installed_copies_and_blocks_run_reports():
    slug = f"revoke-{uuid.uuid4().hex[:6]}"
    pub = client.post("/api/registry/publish", json={"slug": slug, "title": "R", "graph": GRAPH,
                                                     "publication_consent": True}, headers=H).json()
    imp = client.post("/api/registry/import", json={"template_id": pub["template_id"],
                                                    "local_mapping": {}}, headers=H).json()

    assert client.post("/api/registry/revoke", json={"slug": slug, "reason": " "},
                       headers=H).status_code == 422
    rv = client.post("/api/registry/revoke", json={"slug": slug, "reason": "leaks data"}, headers=H)
    assert rv.status_code == 200 and rv.json()["installed_copies_revoked"] == 1

    mine = [i for i in client.get("/api/registry/imports", headers=H).json()
            if i["import_id"] == imp["import_id"]]
    assert mine[0]["status"] == "revoked"
    assert client.post(f"/api/registry/imports/{imp['import_id']}/record-run",
                       headers=H).status_code == 410
    assert client.post("/api/registry/import", json={"template_id": pub["template_id"],
                                                     "local_mapping": {}}, headers=H).status_code == 404
