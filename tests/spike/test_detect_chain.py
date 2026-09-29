"""Phase 3→4 integration: real events → candidates with evidence → notifications,
plus the capture watcher chain, exercised through the real FastAPI app (TestClient)."""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from tests.spike.conftest import isolated_db_module, test_session  # noqa: E402,F401 (fixture import)
from backend.models import Base, Candidate, Event, Notification  # noqa: E402

client = TestClient(app)
HEADERS = {"Authorization": "Bearer " + ("x" * 8)}  # replaced below via dependency override


@pytest.fixture(scope="module", autouse=True)
def _auth_and_db(isolated_db_module):
    from backend.security import tokens
    original = tokens.get_expected_token
    tokens.get_expected_token = lambda: "testtoken"
    pass  # schema created by isolated_db_module
    db = test_session()
    db.query(Notification).delete()
    db.query(Candidate).delete()
    db.query(Event).delete()
    db.commit()
    db.close()
    yield
    tokens.get_expected_token = original


def _ev(action, minute, record_key, source="saved_file_comparison"):
    from datetime import datetime, timedelta, timezone
    base = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
    at = (base + timedelta(minutes=minute)).isoformat()
    return {"event_id": str(uuid.uuid4()), "schema_version": 2,
            "source_version": "phase2-test-0.1.0", "source": source,
            "action": action, "resource": "sample-tracking-file", "record_key": record_key,
            "changed_fields": [], "outcome": "success", "captured_at": at,
            "processed_at": at, "synthetic": False}


def test_events_become_candidates_and_notifications():
    events = []
    for k, minute in enumerate([0, 1, 15, 16, 30, 31]):
        client_id = "sample:C001" if k % 2 == 0 else "sample:C002"
        events.append(_ev("record_opened", minute, client_id))
        events.append(_ev("spreadsheet_row_updated", minute + 0.5, client_id))
    res = client.post("/api/events", json=events,
                      headers={"Authorization": "Bearer testtoken"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["accepted"] == 12
    assert body["detection"]["candidates_created"] >= 1

    res = client.get("/api/candidates", headers={"Authorization": "Bearer testtoken"})
    cands = res.json()
    q = [c for c in cands if c["status"] == "suggested"]
    assert len(q) == 1
    assert q[0]["pattern"]["sequence"] == ["record_opened", "spreadsheet_row_updated"]
    assert q[0]["evidence"]["distinct_clients"] == 2
    assert q[0]["evidence"]["instances"] == 4  # trailing instances now incomplete

    res = client.get("/api/notifications", headers={"Authorization": "Bearer testtoken"})
    notes = res.json()
    assert len(notes) == 1
    assert "2" in notes[0]["body"] and "clients" in notes[0]["body"]

    # Re-alert suppression: identical evidence again → no new notification
    dup = [dict(e, event_id=f"dup-{uuid.uuid4()}") for e in events]
    client.post("/api/events", json=dup, headers={"Authorization": "Bearer testtoken"})
    res = client.get("/api/notifications", headers={"Authorization": "Bearer testtoken"})
    assert len(res.json()) == 1


def test_capture_poll_end_to_end(tmp_path, monkeypatch):
    from backend import app as app_mod
    from backend import spike_config as cfg
    from backend.capture import config as capture_config
    # the user's own capture settings must not decide which folder this test reads
    monkeypatch.setattr(capture_config, "CONFIG_FILE", tmp_path / "capture_config.json")
    monkeypatch.setattr(app_mod, "_WATCHER", None)
    watched = cfg.DATA_DIR / "watched"
    watched.mkdir(parents=True, exist_ok=True)
    csv_a = ("ClientID,Name,Email,FollowUpDate,Status\n"
             "C101,One,o@x.invalid,2026-09-20,Follow-up due\n")
    csv_b = ("ClientID,Name,Email,FollowUpDate,Status\n"
             "C101,One,o@x.invalid,2026-09-20,Draft prepared\n")
    (watched / "ledger.csv").write_text(csv_a, encoding="utf-8")
    res = client.post("/api/capture/poll", json=None,
                      headers={"Authorization": "Bearer testtoken"})
    assert res.status_code == 200, res.text
    first = res.json()
    assert first["events"] == 0  # baseline, not an event

    (watched / "ledger.csv").write_text(csv_b, encoding="utf-8")
    time.sleep(0.6)
    res = client.post("/api/capture/poll", json=None,
                      headers={"Authorization": "Bearer testtoken"})
    body = res.json()
    assert body["events"] >= 1
    # the update event must have landed in the events table as watcher-source
    db = test_session()
    try:
        evs = db.query(Event).filter(Event.source == "saved_file_comparison",
                                     Event.record_key == "ledger:C101").all()
        assert evs, "watcher update event missing"
        assert all(e.synthetic is False for e in evs)
    finally:
        db.close()
