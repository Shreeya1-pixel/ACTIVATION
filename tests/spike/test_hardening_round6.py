"""Production-hardening armor (QA round 6): locks in defects found during the
production-readiness pass. Each test maps to a real finding:

  teams.workflow_process_map used a name imported only inside a sibling function
      (_json NameError) — silently swallowed by `except Exception`, returning raw
      JSON strings instead of parsed values.
  /api/compare/run computed the independent oracle (expected_matches) but never
      checked the engine's categories against it — docstring promised an oracle
      gate that did not exist.
  POST /api/triggers/tick accepted any authenticated principal (observer included)
      — a read-only role could force trigger firing.
  POST /api/capture/poll likewise ignored the role model.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SERVICE = {"Authorization": "Bearer spiketoken", "Content-Type": "application/json"}


def _mk_user_token(client, username, role=None):
    """Register + mint a user token; optionally set the org membership role."""
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


def test_workflow_process_map_roundtrips(client, isolated_db):
    """teams.workflow_process_map must return parsed values, not raw JSON strings
    (the old code hit a NameError swallowed by `except Exception`)."""
    from backend import teams
    from tests.spike.conftest import test_session as _ts
    wid = f"wf-proc-{uuid.uuid4().hex[:6]}"
    assert client.post("/api/workflows",
                       json={"id": wid, "name": "proc-map",
                             "graph": {"nodes": [], "edges": []}},
                       headers=SERVICE).status_code == 200
    with _ts() as db:
        teams.attach_workflow_to_process(db, f"proc-{uuid.uuid4().hex[:6]}", wid)
        mapping = teams.workflow_process_map(db, [wid])
    assert wid in mapping, mapping
    assert isinstance(mapping[wid], str) and mapping[wid].startswith("proc-")
    assert not mapping[wid].startswith('"'), "raw JSON string leaked (the _json bug)"


def test_compare_run_passes_oracle_gate(client, isolated_db):
    """The compare engine's categories must agree with the independent oracle —
    and the route must actually run that gate (it silently didn't before)."""
    r = client.post("/api/compare/run", json={}, headers=SERVICE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "passed"
    assert body["mismatched"] >= 1 and body["updated"], body
    # exactly-once rerun: second pass updates nothing
    r2 = client.post("/api/compare/run", json={}, headers=SERVICE)
    assert r2.status_code == 200 and r2.json()["updated"] == []


def test_trigger_tick_rejects_observer(client):
    """POST /api/triggers/tick is a mutation; a read-only observer must get 403."""
    obs = _mk_user_token(client, f"tick-obs-{uuid.uuid4().hex[:4]}", role="observer")
    H = {"Authorization": f"Bearer {obs}", "Content-Type": "application/json"}
    assert client.post("/api/triggers/tick", json={}, headers=H).status_code == 403


def test_capture_poll_rejects_observer(client):
    """POST /api/capture/poll ingests events — observer-only callers get 403."""
    obs = _mk_user_token(client, f"poll-obs-{uuid.uuid4().hex[:4]}", role="observer")
    H = {"Authorization": f"Bearer {obs}", "Content-Type": "application/json"}
    assert client.post("/api/capture/poll", json={}, headers=H).status_code == 403


UNAUTH_READS = [
    "/api/me/capabilities", "/api/team/members", "/api/team/invitations",
    "/api/processes", "/api/runners",
]


def test_org_reads_require_token(client, isolated_db):
    """QA round 6: org roster/capabilities endpoints served data with NO token at
    all (username/user_id/role disclosure). Every one must 401 anonymous now."""
    for path in UNAUTH_READS:
        assert client.get(path).status_code == 401, path
    assert client.get("/api/registry/templates/t/signals").status_code == 401


def test_org_reads_work_for_authenticated_user(client, isolated_db):
    """The auth fix must not break legitimate authenticated reads."""
    tok = _mk_user_token(client, f"reader-{uuid.uuid4().hex[:4]}")
    H = {"Authorization": f"Bearer {tok}"}
    for path in UNAUTH_READS:
        r = client.get(path, headers=H)
        assert r.status_code == 200, (path, r.status_code, r.text[:100])


def test_node_data_error_is_400_not_500(client, isolated_db):
    """QA round 6: a run whose node hits a caller-caused data violation (missing
    column) must end 'failed' AND return HTTP 400 — never a misleading 500."""
    wid = f"wf-cde-{uuid.uuid4().hex[:6]}"
    graph = {"nodes": [
        {"id": "src", "type": "file.read_table", "params": {"alias": "sample-tracking-file"}},
        {"id": "upd", "type": "file.update_rows", "params": {"alias": "sample-tracking-file",
                                                             "filename": "clients.csv", "set": "NoSuchColumn",
                                                             "purpose": "round6"}},
    ], "edges": [{"from": "src", "to": "upd"}]}
    assert client.post("/api/workflows", json={"id": wid, "name": "cde", "graph": graph},
                       headers=SERVICE).status_code == 200
    r = client.post("/api/runs", json={"workflow_id": wid, "run_date": "2027-05-05"},
                    headers=SERVICE)
    assert r.status_code == 400, (r.status_code, r.text[:200])
    body = r.json()["detail"]
    assert "missing column" in body["error"] and body["run_id"]
    from tests.spike.conftest import test_session as _ts
    from backend.models import Run
    with _ts() as db:
        run = db.get(Run, body["run_id"])
        assert run is not None and run.status == "failed" and run.error


# ── QA round 7: lifecycle-route permission tiers + delete semantics ──

def test_approver_level_routes_reject_operator(client, isolated_db):
    """test/activate = approver in PERMISSION_MIN_ROLE; the legacy lifecycle
    routes used to accept operator (RBAC tier bypass via the legacy path)."""
    op = _mk_user_token(client, f"tier-op-{uuid.uuid4().hex[:4]}", role="operator")
    assert client.post("/api/test-jobs", json={"artifact_id": "x", "consent": True},
                       headers={"Authorization": f"Bearer {op}"}).status_code == 403
    assert client.post("/api/approvals/activation", json={"artifact_id": "x", "job_id": "y"},
                       headers={"Authorization": f"Bearer {op}"}).status_code == 403
    # service principal and approver keep non-403 contract behavior
    assert client.post("/api/test-jobs", json={"artifact_id": "x", "consent": True},
                       headers=SERVICE).status_code == 404


def test_publish_requires_owner(client, isolated_db):
    """publish = owner; the legacy /api/registry/publish used to accept approver."""
    apr = _mk_user_token(client, f"pub-apr-{uuid.uuid4().hex[:4]}", role="approver")
    H = {"Authorization": f"Bearer {apr}", "Content-Type": "application/json"}
    r = client.post("/api/registry/publish",
                    json={"slug": f"pub-{uuid.uuid4().hex[:6]}", "title": "t",
                          "publication_consent": True, "graph": {"nodes": [], "edges": []}},
                    headers=H)
    assert r.status_code == 403, r.text
    # owner-equivalent service principal still publishes (probe depends on this)
    r2 = client.post("/api/registry/publish",
                     json={"slug": f"pub-svc-{uuid.uuid4().hex[:6]}", "title": "t",
                           "publication_consent": True, "graph": {"nodes": [], "edges": []}},
                     headers=SERVICE)
    assert r2.status_code in (200, 422), r2.text


def test_node_callback_routes_reject_observer(client, isolated_db):
    """Node callbacks execute real effects (row updates, drafts); an observer's
    user token must not drive them. The Node-RED bridge uses the service token."""
    obs = _mk_user_token(client, f"node-obs-{uuid.uuid4().hex[:4]}", role="observer")
    H = {"Authorization": f"Bearer {obs}", "Content-Type": "application/json"}
    for path, body in (
        ("/api/nodes/update-row", {"run_id": "r", "node_id": "n", "record_key": "k"}),
        ("/api/nodes/draft-create", {"run_id": "r", "node_id": "n", "record_key": "k",
                                     "template_id": "followup_en"}),
        ("/api/runs/nonexistent/complete", {"status": "passed"}),
    ):
        assert client.post(path, json=body, headers=H).status_code == 403, path


def test_soft_deleted_workflow_id_cannot_be_reused(client, isolated_db):
    """Saving into a soft-deleted workflow id returned 200 but left the workflow
    deleted — a silent no-op that also bypassed the owner-only delete gate."""
    wid = f"wf-del-{uuid.uuid4().hex[:6]}"
    assert client.post("/api/workflows", json={"id": wid, "name": "x",
                                               "graph": {"nodes": [], "edges": []}},
                       headers=SERVICE).status_code == 200
    assert client.delete(f"/api/workflows/{wid}", headers=SERVICE).status_code == 200
    r = client.post("/api/workflows", json={"id": wid, "name": "resurrect",
                                            "graph": {"nodes": [], "edges": []}},
                    headers=SERVICE)
    assert r.status_code == 409, r.text
    from tests.spike.conftest import test_session as _ts
    from backend.models import Workflow
    with _ts() as db:
        assert db.get(Workflow, wid).deleted_at is not None


def test_org_sso_requires_token(client, isolated_db):
    """Tier capability info (sso flag) was served anonymously."""
    assert client.get("/api/org/sso").status_code == 401
    assert client.get("/api/org/sso", headers=SERVICE).status_code == 200
