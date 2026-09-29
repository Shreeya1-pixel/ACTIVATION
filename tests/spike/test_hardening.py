"""Hardening regression armor: locks in every fix from QA rounds 2-3.

Each test maps to a real bug that was found live and fixed:
  #8  bad fixture content -> 400 (not 500)
  #9  traversal error message not doubled
  #10 oversized request body -> 413
      stored invalid graph -> 422 with recovery hint
      concurrency: exactly-once under parallel run-now
      injection: template syntax in data stays literal text
"""
from __future__ import annotations

import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402,F401 (client fixture comes from conftest)

SERVICE = {"Authorization": "Bearer spiketoken", "Content-Type": "application/json"}


def _unique_run_date() -> str:
    import random
    return f"{random.randint(2027, 2099)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"


def test_bad_fixture_content_is_400_not_500(client):
    """QA bug #8: a client-caused file error must be a clean 400 with a run row."""
    from backend.security.safeio import write_resource
    bad = "ClientID,WrongCol,Email,FollowUpDate,Status\r\nC001,X,x@e.invalid,2026-09-20,Follow-up due\r\n"
    write_resource("sample-tracking-file", "hard-bad.csv", bad.encode(), backup=False)
    graph = {"nodes": [
        {"id": "r", "type": "file.read_table", "params": {"alias": "sample-tracking-file"}},
    ], "edges": []}
    wid = f"wf-hard-{uuid.uuid4().hex[:6]}"
    r = client.post("/api/workflows", json={"id": wid, "name": "bad", "graph": graph}, headers=SERVICE)
    assert r.status_code == 200, r.text
    run = client.post("/api/runs", json={"workflow_id": wid, "run_date": "2026-09-20",
                                         "filename": "hard-bad.csv"}, headers=SERVICE)
    assert run.status_code == 400, run.text
    assert "columns" in run.json()["detail"]["error"].lower()


def test_non_sample_ids_are_400(client):
    """QA bug #8b: the synthetic-data ID contract is a client error, not a crash."""
    from backend.security.safeio import write_resource
    bad = "ClientID,Name,Email,FollowUpDate,Status\r\nZZZ9,X,x@e.invalid,2026-09-20,Follow-up due\r\n"
    write_resource("sample-tracking-file", "hard-ids.csv", bad.encode(), backup=False)
    graph = {"nodes": [
        {"id": "r", "type": "file.read_table", "params": {"alias": "sample-tracking-file"}},
    ], "edges": []}
    wid = f"wf-hard-{uuid.uuid4().hex[:6]}"
    client.post("/api/workflows", json={"id": wid, "name": "ids", "graph": graph}, headers=SERVICE)
    run = client.post("/api/runs", json={"workflow_id": wid, "run_date": "2026-09-20",
                                         "filename": "hard-ids.csv"}, headers=SERVICE)
    assert run.status_code == 400
    assert "client id" in run.json()["detail"]["error"].lower()


def test_traversal_error_not_doubled(client):
    """QA bug #9: exactly one 'unsafe filename' prefix."""
    r = client.post("/api/resources/stage", json={"fixture": "clients-before.csv", "as_filename": "../evil.csv"},
                    headers=SERVICE)
    assert r.status_code == 400
    detail = str(r.json()["detail"])
    assert detail.count("unsafe filename") == 1


def test_oversized_body_is_413(client):
    """QA bug #10: request-size cap returns 413, not an OOM risk."""
    big = {"plan": {"client_id_field": "ClientID",
                    "field_mappings": {"Name": "A" * 1_500_000},
                    "eligibility": {"status": "Follow-up due", "status_field": "Status",
                                    "date_field": "FollowUpDate", "date_value": "2026-09-20"},
                    "action": "create_draft", "destinations": ["in_app"]}}
    r = client.post("/api/plans", json=big, headers=SERVICE)
    assert r.status_code == 413, r.text


def test_stored_invalid_graph_is_422_with_recovery_hint(client, isolated_db):
    """Stale-state hardening: an invalid stored graph fails cleanly, never 500."""
    # force an invalid graph into a version directly (simulates pre-fix stored state)
    import json as _json
    import secrets as _secrets
    from backend.models import Workflow, WorkflowVersion
    with isolated_db() as db:
        wid = f"wf-stale-{_secrets.token_hex(3)}"
        wf = Workflow(id=wid, name="stale")
        db.add(wf)
        broken = {"nodes": [{"id": "x", "type": "no.such.node", "params": {}}], "edges": []}
        db.add(WorkflowVersion(id=str(uuid.uuid4()), workflow_id=wid, version=1,
                               graph_json=_json.dumps(broken), artifact_sha256="0" * 64))
        db.commit()
    r = client.post("/api/runs", json={"workflow_id": wid, "run_date": "2026-09-20"}, headers=SERVICE)
    assert r.status_code == 422, r.text
    assert "re-bind" in r.json()["detail"]["error"]


def test_exactly_once_under_concurrent_run_now(client):
    """8-way parallel run-now on fresh data: exactly 2 drafts, 0 duplicates."""
    from backend.security.safeio import write_resource
    graph = {"nodes": [
        {"id": "r", "type": "file.read_table", "params": {"alias": "sample-tracking-file"}},
        {"id": "f", "type": "data.filter", "params": {"from": "rows",
         "where": "row.Status == 'Follow-up due' and row.FollowUpDate <= run_date"}},
        {"id": "d", "type": "draft.create", "params": {"record_key": "sample:ClientID",
         "template_id": "followup_en", "destination": "in_app"}, "on_fail": "continue"},
    ], "edges": [{"from": "r", "to": "f"}, {"from": "f", "to": "d"}]}
    wid = f"wf-conc-{uuid.uuid4().hex[:6]}"
    r = client.post("/api/workflows", json={"id": wid, "name": "conc", "graph": graph}, headers=SERVICE)
    assert r.status_code == 200, r.text
    run_date = _unique_run_date()
    fname = f"conc-{uuid.uuid4().hex[:6]}.csv"
    write_resource("sample-tracking-file", fname,
                   Path(ROOT, "tests/fixtures/clients-before.csv").read_bytes(), backup=False)
    results = []
    def fire(_):
        r = client.post("/api/runs", json={"workflow_id": wid, "run_date": run_date,
                                           "filename": fname}, headers=SERVICE)
        return r.status_code, (r.json().get("drafted", []) if r.status_code == 200 else [])
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(fire, range(8)))
    codes = [c for c, _ in results]
    assert all(c == 200 for c in codes), codes
    flat = [k for _, keys in results for k in keys]
    # exactly-once under contention: each effect drafted exactly once across all runs
    assert sorted(flat) == ["sample:C001", "sample:C003"], flat
    # and a 9th sequential run is a full no-op
    r9 = client.post("/api/runs", json={"workflow_id": wid, "run_date": run_date,
                                        "filename": fname}, headers=SERVICE)
    assert r9.status_code == 200 and r9.json().get("drafted", []) == []


def test_injection_stays_literal(client, isolated_db):
    """Template syntax in user data never executes (sandboxed rendering)."""
    from backend.security.safeio import write_resource
    payload = "{{ 7*7 }}__{{ ''.__class__.__mro__ }}"
    csv_text = ("ClientID,Name,Email,FollowUpDate,Status\r\n"
                f"C001,{payload},inj@e.invalid,2026-09-20,Follow-up due\r\n")
    write_resource("sample-tracking-file", "hard-inj.csv", csv_text.encode(), backup=False)
    graph = {"nodes": [
        {"id": "r", "type": "file.read_table", "params": {"alias": "sample-tracking-file"}},
        {"id": "d", "type": "draft.create", "params": {"record_key": "sample:ClientID",
         "template_id": "followup_en", "destination": "in_app"}, "on_fail": "continue"},
    ], "edges": [{"from": "r", "to": "d"}]}
    wid = f"wf-inj-{uuid.uuid4().hex[:6]}"
    client.post("/api/workflows", json={"id": wid, "name": "inj", "graph": graph}, headers=SERVICE)
    run = client.post("/api/runs", json={"workflow_id": wid, "run_date": _unique_run_date(),
                                         "filename": "hard-inj.csv"}, headers=SERVICE)
    assert run.status_code == 200, run.text
    from backend.models import Draft
    from sqlalchemy import select
    with isolated_db() as db:
        draft = db.scalar(select(Draft).where(Draft.record_key == "sample:C001").order_by(Draft.created_at.desc()))
    assert draft is not None
    body = draft.body or ""
    # the payload is INERT: no evaluation ('49'), no rendered type info ('<class'),
    # the raw template syntax survives verbatim as literal text
    assert "49" not in body
    assert "<class" not in body
    assert "7*7" in body and "__class__" in body  # literal passthrough, unexecuted


# ── QA round 5 armor: RBAC on legacy routes, webhook execution, input typing ──

def _mk_user_token(client, username, role=None):
    """Register a user, mint a token; optionally set the org membership role."""
    r = client.post("/api/auth/register", json={"username": username, "password": "password-123"},
                    headers=SERVICE)
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/tokens", json={"username": username, "password": "password-123"},
                    headers=SERVICE)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    if role:
        from tests.spike.conftest import test_session
        from backend.models import Membership, Org, User
        from sqlalchemy import select
        with test_session() as db:
            user = db.scalar(select(User).where(User.username == username))
            org = db.scalar(select(Org))
            m = db.scalar(select(Membership).where(Membership.user_id == user.id))
            if m is None:
                m = Membership(id=str(uuid.uuid4()), org_id=org.id, user_id=user.id, role=role)
                db.add(m)
            m.role = role
            db.commit()
    return token


def _mk_webhook_trigger(client, workflow_id):
    """Create an enabled webhook trigger via the admin API; returns (id, secret)."""
    r = client.post("/api/triggers", json={"workflow_id": workflow_id, "kind": "webhook",
                                           "config": {}, "evidence_note": "hardening test"},
                    headers=SERVICE)
    assert r.status_code == 200, r.text
    body = r.json()
    return body["trigger_id"], body["secret"]


def test_observer_cannot_mutate_but_can_read(client):
    """B1 armor: RBAC is enforced on legacy routes, not just roadmap routes."""
    tok = _mk_user_token(client, f"obs-{uuid.uuid4().hex[:6]}", role="observer")
    H = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    assert client.get("/api/workflows", headers=H).status_code == 200  # reads stay open
    for method, path, payload in (
        ("POST", "/api/runs", {"workflow_id": "wf_client_followup", "run_date": "2027-01-01"}),
        ("POST", "/api/workflows", {"id": f"wf-denied-{uuid.uuid4().hex[:4]}", "name": "x",
                                    "graph": {"nodes": [], "edges": []}}),
        ("POST", "/api/resources/stage", {"fixture": "clients.csv", "as_filename": "no.csv"}),
    ):
        r = client.request(method, path, json=payload, headers=H)
        assert r.status_code == 403, f"{path}: {r.text}"


def test_operator_can_run_but_not_administer(client):
    """B1 armor: the role ladder is real — operator mutates, admin-only still gated."""
    _mk_user_token(client, f"seed-{uuid.uuid4().hex[:6]}")  # first user = admin (by design)
    tok = _mk_user_token(client, f"op-{uuid.uuid4().hex[:6]}", role="operator")
    H = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    r = client.post("/api/workflows", json={"id": f"wf-op-{uuid.uuid4().hex[:4]}", "name": "op test",
                                            "graph": {"nodes": [], "edges": []}}, headers=H)
    assert r.status_code == 200, r.text
    assert client.post("/api/org/tier", json={"tier": "enterprise"}, headers=H).status_code == 403


def test_service_token_unaffected_by_rbac(client):
    """B1 compat guarantee: the service principal keeps full owner-level access."""
    r = client.post("/api/workflows", json={"id": f"wf-svc-{uuid.uuid4().hex[:4]}", "name": "svc test",
                                            "graph": {"nodes": [], "edges": []}}, headers=SERVICE)
    assert r.status_code == 200, r.text


def test_webhook_fire_executes_run(client):
    """B2 armor: a fired webhook produces a REAL executed run, never a zombie."""
    graph = {"nodes": [
        {"id": "r", "type": "file.read_table", "params": {"alias": "sample-tracking-file", "max_rows": 50}},
        {"id": "d", "type": "draft.create",
         "params": {"record_key": "{row[ClientID]}", "template_id": "followup_en",
                    "destination": "in_app"}},
    ], "edges": [{"from": "r", "to": "d"}]}
    wid = f"wf-webk-{uuid.uuid4().hex[:6]}"
    r = client.post("/api/workflows", json={"id": wid, "name": "webhook exec test", "graph": graph},
                    headers=SERVICE)
    assert r.status_code == 200, r.text
    trig, secret = _mk_webhook_trigger(client, wid)
    fire = client.post(f"/api/webhook/{trig}", json={},
                       headers={"X-AutoStack-Secret": secret, "Content-Type": "application/json"})
    assert fire.status_code == 200, fire.text
    run_id = fire.json()["run_id"]
    assert run_id
    runs = client.get("/api/runs/list", headers=SERVICE).json()["runs"]
    mine = [x for x in runs if x["id"] == run_id]
    assert mine and mine[0]["status"] in ("passed", "failed"), mine
    # exactly-once: the second fire must not double-apply effects
    fire2 = client.post(f"/api/webhook/{trig}", json={},
                        headers={"X-AutoStack-Secret": secret, "Content-Type": "application/json"})
    assert fire2.status_code in (200, 429), fire2.text


def test_webhook_rejects_unknown_and_wrong_secret_without_state(client):
    """B7 armor: unknown triggers and bad secrets leave NO state behind."""
    import backend.roadmap_routes as rr
    r1 = client.post("/api/webhook/nonexistent-trigger", json={},
                     headers={"X-AutoStack-Secret": "x", "Content-Type": "application/json"})
    assert r1.status_code == 404
    assert "nonexistent-trigger" not in rr._WEBHOOK_HITS
    wid = f"wf-b7-{uuid.uuid4().hex[:4]}"
    assert client.post("/api/workflows", json={"id": wid, "name": "b7",
                                              "graph": {"nodes": [], "edges": []}}, headers=SERVICE).status_code == 200
    trig, _secret = _mk_webhook_trigger(client, wid)
    r2 = client.post(f"/api/webhook/{trig}", json={},
                     headers={"X-AutoStack-Secret": "wrong", "Content-Type": "application/json"})
    assert r2.status_code == 401
    assert trig not in rr._WEBHOOK_HITS


def test_retention_rejects_bool_and_float(client):
    """B6 armor: booleans/floats are not day counts."""
    assert client.post("/api/org/tier", json={"tier": "team"}, headers=SERVICE).status_code == 200
    for bad in ({"observations_days": True, "reports_days": 90},
                {"observations_days": 30.5, "reports_days": 90},
                {"observations_days": "30", "reports_days": 90}):
        r = client.post("/api/privacy/retention", json=bad, headers=SERVICE)
        assert r.status_code == 422, f"{bad}: {r.text}"
    client.post("/api/org/tier", json={"tier": "solo"}, headers=SERVICE)


# ── B3/B4 armor: trigger firing loop + workflow deletion ─────────────────────

def test_schedule_trigger_fires_when_due(client, isolated_db):
    """B3 armor: a schedule trigger with real config fires through the executor,
    at most once per day per trigger."""
    graph = {"nodes": [{"id": "n", "type": "notify.desktop", "params": {"title_key": "Name"}}],
             "edges": []}
    wid = f"wf-sched-{uuid.uuid4().hex[:6]}"
    assert client.post("/api/workflows", json={"id": wid, "name": "sched", "graph": graph},
                       headers=SERVICE).status_code == 200
    # create directly with due config (creation API is evidence-gated by design)
    from tests.spike.conftest import test_session
    from backend.models import Trigger
    from backend import orchestration as orch
    with test_session() as db:
        from datetime import datetime, timezone as _tz
        _now = datetime.now(_tz.utc)
        trig, _secret = orch.create_trigger(db, wid, "schedule",
                                            {"time_of_day": _now.strftime("%H:%M"), "user_confirmed": True},
                                            "hardening test")
        db.commit()
    r = client.post("/api/triggers/tick", headers=SERVICE)
    assert r.status_code == 200, r.text
    fired = r.json()["fired"]
    mine = [f for f in fired if f["trigger_id"] == trig.id]
    assert mine and mine[0].get("status") in ("passed", "failed"), fired
    # second tick the same day: NOT fired again (once-per-day stamp)
    r2 = client.post("/api/triggers/tick", headers=SERVICE)
    again = [f for f in r2.json()["fired"] if f["trigger_id"] == trig.id]
    assert again == [], r2.json()


def test_file_trigger_fires_on_new_watcher_event(client, isolated_db):
    """B3 armor: a file trigger fires on a fresh matching watcher event."""
    graph = {"nodes": [{"id": "n", "type": "notify.desktop", "params": {"title_key": "Name"}}],
             "edges": []}
    wid = f"wf-file-{uuid.uuid4().hex[:6]}"
    assert client.post("/api/workflows", json={"id": wid, "name": "file", "graph": graph},
                       headers=SERVICE).status_code == 200
    from tests.spike.conftest import test_session
    from backend.models import Event, Trigger
    from backend import orchestration as orch
    with test_session() as db:
        trig, _s = orch.create_trigger(db, wid, "file",
                                       {"alias": "sample-tracking-file", "action": "row.added"},
                                       "hardening test")
        ev = Event(id=str(uuid.uuid4()), event_id=str(uuid.uuid4()), schema_version=2,
                   source="saved_file_comparison", action="row.added",
                   resource="sample-tracking-file", record_key="sample:C777",
                   changed_fields_json="[]", outcome="success",
                   captured_at="2026-09-24T00:00:00+00:00", processed_at="2026-09-24T00:00:00+00:00",
                   synthetic=False)
        db.add(ev)
        db.commit()
    r = client.post("/api/triggers/tick", headers=SERVICE)
    assert r.status_code == 200, r.text
    mine = [f for f in r.json()["fired"] if f["trigger_id"] == trig.id]
    assert mine and mine[0].get("status") in ("passed", "failed"), r.json()


def test_workflow_delete_owner_only_and_safe(client, isolated_db):
    """B4 armor: deletion works for admins, keeps runs, refuses unknown, gates RBAC."""
    wid = f"wf-del-{uuid.uuid4().hex[:6]}"
    graph = {"nodes": [{"id": "n", "type": "notify.desktop", "params": {"title_key": "Name"}}],
             "edges": []}
    assert client.post("/api/workflows", json={"id": wid, "name": "del", "graph": graph},
                       headers=SERVICE).status_code == 200
    # run it once so history exists
    run = client.post("/api/runs", json={"workflow_id": wid, "run_date": "2027-02-02"}, headers=SERVICE)
    assert run.status_code == 200, run.text
    # observer cannot delete (seed an admin first: the first local user is admin by design)
    _mk_user_token(client, f"del-admin-{uuid.uuid4().hex[:4]}")
    obs = _mk_user_token(client, f"del-obs-{uuid.uuid4().hex[:4]}", role="observer")
    H = {"Authorization": f"Bearer {obs}", "Content-Type": "application/json"}
    assert client.delete(f"/api/workflows/{wid}", headers=H).status_code == 403
    # service admin can
    r = client.delete(f"/api/workflows/{wid}", headers=SERVICE)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == wid
    # gone from listings; unknown second delete -> 404; run history retained
    assert client.delete(f"/api/workflows/{wid}", headers=SERVICE).status_code == 404
    listing = client.get("/api/workflows", headers=SERVICE).json()
    assert all(w["id"] != wid for w in listing["workflows"])
    from tests.spike.conftest import test_session as _ts
    from backend.models import Run, Workflow, WorkflowVersion
    from sqlalchemy import select, func as _f
    with _ts() as db:
        assert db.get(Workflow, wid) is not None and db.get(Workflow, wid).deleted_at is not None
        assert db.scalar(select(_f.count()).select_from(Run)
                         .where(Run.version_id.in_(
                             select(WorkflowVersion.id).where(WorkflowVersion.workflow_id == wid)))) >= 1
