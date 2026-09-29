"""RBAC + context-model regression tests (create-flow audit).

Covers the two bug classes the audit found:
  1. False denials for operators: registration now grants operator (not
     observer), missing memberships fall back to operator, and the plan gate
     is a RUN-level (operator+) check — an operator can complete
     plan -> generate -> create-workflow end to end.
  2. The organization context model (product §5): the /api/org/catalog drives
     cascading org type -> size -> department -> process type selection,
     invalid tuples are refused server-side, and bound workflows carry their
     classification in /api/workflows.

Role ladder under test: observer(0) < operator(1) < approver(2) < owner(3).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend import roadmap_routes  # noqa: E402
from backend import teams  # noqa: E402
from tests.spike.conftest import isolated_db_module, test_session  # noqa: E402,F401
from backend.models import Base  # noqa: E402

client = TestClient(app)
PASSWORD = "rbac-context-pass-1"


@pytest.fixture(scope="module", autouse=True)
def _auth(isolated_db_module):
    from backend.security import tokens
    original_tokens = tokens.get_expected_token
    original_routes = roadmap_routes.get_expected_token
    tokens.get_expected_token = lambda: "testtoken"
    roadmap_routes.get_expected_token = lambda: "testtoken"
    yield
    tokens.get_expected_token = original_tokens
    roadmap_routes.get_expected_token = original_routes


@pytest.fixture(scope="module")
def owner_h():
    """The FIRST account in this module's DB is the owner (machine admin).
    Every later registration is an operator; role changes go through owner."""
    return _register("rbac-owner-0")


def _promote(owner_headers: dict, username: str, role: str) -> None:
    members = client.get("/api/team/members", headers=owner_headers).json()["members"]
    mid = next(m["membership_id"] for m in members if m["username"] == username)
    r = client.post(f"/api/team/members/{mid}/role", json={"role": role},
                    headers=owner_headers)
    assert r.status_code == 200, r.text


def _register(username: str) -> dict:
    r = client.post("/api/auth/register",
                    json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    tok = client.post("/api/auth/tokens",
                      json={"username": username, "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


PLAN = {
    "client_id_field": "ClientID",
    "field_mappings": {"Name": "Name", "FollowUpDate": "FollowUpDate"},
    "eligibility": {"status": "Follow-up due", "status_field": "Status",
                    "date_field": "FollowUpDate", "date_value": "2026-09-20"},
    "action": "create_draft",
    "destinations": ["in_app"],
}

CTX = {"org_type": "corporate", "size": "medium",
       "department": "finance", "process_type": "accounts_payable"}


# ── role model ────────────────────────────────────────────────────────────────

def test_registration_grants_operator_and_missing_membership_falls_back(owner_h):
    """The first account is owner; every later registration is operator. A
    provisioned account whose membership row went missing still acts as
    operator (the old observer fallback produced false 403s everywhere)."""
    me = client.get("/api/auth/me", headers=owner_h).json()
    assert me["role"] == "owner"

    op_h = _register("rbac-operator-a")
    me = client.get("/api/auth/me", headers=op_h).json()
    assert me["role"] == "operator", me

    # simulate a legacy account without a membership row
    from backend.models import Membership
    db = test_session()
    try:
        row = db.query(Membership).filter(Membership.role == "operator").first()
        assert row is not None
        db.delete(row)
        db.commit()
    finally:
        db.close()
    me = client.get("/api/auth/me", headers=op_h).json()
    assert me["role"] == "operator", "missing membership must fall back to operator"
    # and the operator can still create plans (the old bug: false 403 here)
    r = client.post("/api/plans", json={"plan": PLAN}, headers=op_h)
    assert r.status_code == 200, (r.status_code, r.text)


def test_observer_is_read_only_but_operator_runs_and_creates(owner_h):
    op_h = _register("rbac-operator-b")

    # make a real observer: register a user, then the owner demotes them
    obs_h = _register("rbac-observer-b")
    _promote(owner_h, "rbac-observer-b", "observer")

    # observer: read OK, everything mutating 403
    assert client.get("/api/workflows", headers=obs_h).status_code == 200
    r = client.post("/api/plans", json={"plan": PLAN}, headers=obs_h)
    assert r.status_code == 403, "observer must not create plans"
    r = client.post("/api/runs", json={"workflow_id": "x"}, headers=obs_h)
    assert r.status_code == 403
    r = client.post("/api/triggers/tick", headers=obs_h)
    assert r.status_code == 403

    # operator: plan (run-level) OK — the exact reported bug
    r = client.post("/api/plans", json={"plan": PLAN}, headers=op_h)
    assert r.status_code == 200, r.text
    plan_id = r.json()["plan_id"]

    # operator: generate OK …
    r = client.post("/api/artifacts/generate",
                    json={"plan_id": plan_id, "approve_generation": True}, headers=op_h)
    assert r.status_code == 200, r.text
    artifact_id = r.json()["artifact_id"]

    # … but sandbox test / activation need approver (403 with actionable detail)
    r = client.post("/api/test-jobs",
                    json={"artifact_id": artifact_id, "fixture": "reset", "consent": True},
                    headers=op_h)
    assert r.status_code == 403, r.text
    r = client.post("/api/approvals/activation",
                    json={"artifact_id": artifact_id}, headers=op_h)
    assert r.status_code == 403

    # approver: can test + activate
    appr_h = _register("rbac-approver-b")
    _promote(owner_h, "rbac-approver-b", "approver")
    r = client.post("/api/test-jobs",
                    json={"artifact_id": artifact_id, "fixture": "reset", "consent": True},
                    headers=appr_h)
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    r = client.post("/api/approvals/activation",
                    json={"artifact_id": artifact_id, "job_id": job_id}, headers=appr_h)
    assert r.status_code == 200, r.text

    # operator completes creation (post-activation binding is a run-level act)
    r = client.post(f"/api/plan/{plan_id}/create-workflow", json=CTX, headers=op_h)
    assert r.status_code == 200, r.text
    wf_id = r.json()["workflow_id"]

    # owner-only: publish (operator/approver refused)
    graph = r.json()["graph"]
    pub = {"slug": "rbac-pub-1", "title": "t", "graph": graph,
           "publication_consent": True}
    assert client.post("/api/registry/publish", json=pub, headers=op_h).status_code == 403
    assert client.post("/api/registry/publish", json=pub, headers=appr_h).status_code == 403
    r = client.post("/api/registry/publish", json=pub, headers=owner_h)
    assert r.status_code == 200, r.text

    # admin-only: delete workflow (observer/operator/approver refused)
    assert client.delete(f"/api/workflows/{wf_id}", headers=obs_h).status_code == 403
    assert client.delete(f"/api/workflows/{wf_id}", headers=op_h).status_code == 403
    assert client.delete(f"/api/workflows/{wf_id}", headers=owner_h).status_code == 200

    # registry import: writes an untrusted draft — observer refused, operator OK
    tpl = client.get("/api/registry/templates", headers=owner_h).json()[0]
    imp = {"template_id": tpl["template_id"], "local_mapping": {}}
    assert client.post("/api/registry/import", json=imp, headers=obs_h).status_code == 403
    assert client.post("/api/registry/import", json=imp, headers=op_h).status_code == 200

    # withdraw is publish-level: owner only
    assert client.post("/api/registry/withdraw", json={"slug": "rbac-pub-1"},
                       headers=op_h).status_code == 403
    assert client.post("/api/registry/withdraw", json={"slug": "rbac-pub-1"},
                       headers=owner_h).status_code == 200


def test_trigger_management_is_operator_level(owner_h):
    op_h = _register("rbac-operator-c")
    obs_h = _register("rbac-observer-c")
    _promote(owner_h, "rbac-observer-c", "observer")

    wfs = client.get("/api/workflows", headers=owner_h).json()["workflows"]
    if not wfs:
        pytest.skip("no workflow available to attach a trigger to")
    wid = wfs[0]["id"]
    body = {"workflow_id": wid, "kind": "schedule",
            "config": {"observed_dates": ["2026-09-01", "2026-09-08", "2026-09-15"],
                       "user_confirmed": True}}
    assert client.post("/api/triggers", json=body, headers=obs_h).status_code == 403
    r = client.post("/api/triggers", json=body, headers=op_h)
    # operator passes the gate; the worker may still 400 on evidence contract
    assert r.status_code in (200, 400), r.text
    if r.status_code == 200:
        tid = r.json()["trigger_id"]
        assert client.post(f"/api/triggers/{tid}/disable", headers=op_h).status_code == 200
        assert client.post(f"/api/triggers/{tid}/enable", headers=op_h).status_code == 200


# ── context model ─────────────────────────────────────────────────────────────

def test_org_catalog_shapes():
    r = client.get("/api/org/catalog")
    assert r.status_code == 200, r.text
    cat = r.json()
    for t in ("corporate", "government", "individual", "nonprofit", "education"):
        assert t in cat["org_types"]
    assert cat["sizes_for_type"]["individual"] == ["solo"]
    assert set(cat["sizes_for_type"]["corporate"]) == {"small", "medium", "large"}
    assert "revenue" in cat["departments"]["government"]
    assert "finance" in cat["departments"]["corporate"]
    assert "tax_filing" in cat["process_types"]["revenue"]
    assert "accounts_payable" in cat["process_types"]["finance"]
    # every listed department has process types (never an empty menu)
    for otype, depts in cat["departments"].items():
        for d in depts:
            assert cat["process_types"].get(d) or cat["default_process_types"]


def test_catalog_matches_teams_validation():
    """The UI catalog and the server validator can never disagree."""
    cat = client.get("/api/org/catalog").json()
    for otype in cat["org_types"]:
        for size in cat["sizes_for_type"][otype]:
            for dept in cat["departments"][otype]:
                for pt in cat["process_types"].get(dept, cat["default_process_types"]):
                    assert teams.valid_context(otype, size, dept, pt) == []


def test_workflow_carries_context_and_rejects_incoherent_tuples(owner_h):
    op_h = _register("rbac-operator-d")

    r = client.post("/api/plans", json={"plan": PLAN}, headers=op_h)
    plan_id = r.json()["plan_id"]
    art = client.post("/api/artifacts/generate",
                      json={"plan_id": plan_id, "approve_generation": True},
                      headers=op_h).json()
    appr_h = _register("rbac-approver-d")
    _promote(owner_h, "rbac-approver-d", "approver")
    job = client.post("/api/test-jobs",
                      json={"artifact_id": art["artifact_id"], "fixture": "reset",
                            "consent": True}, headers=appr_h)
    assert job.status_code == 200, job.text
    client.post("/api/approvals/activation",
                json={"artifact_id": art["artifact_id"], "job_id": job.json()["job_id"]},
                headers=appr_h)

    # incoherent tuple: corporate has no 'solo' size
    bad = dict(CTX, size="solo")
    r = client.post(f"/api/plan/{plan_id}/create-workflow", json=bad, headers=op_h)
    assert r.status_code == 422, r.text
    # process type not in the finance catalog
    bad2 = dict(CTX, process_type="license_renewal")
    r = client.post(f"/api/plan/{plan_id}/create-workflow", json=bad2, headers=op_h)
    assert r.status_code == 422, r.text

    r = client.post(f"/api/plan/{plan_id}/create-workflow", json=CTX, headers=op_h)
    assert r.status_code == 200, r.text
    wf_id = r.json()["workflow_id"]

    wfs = client.get("/api/workflows", headers=op_h).json()["workflows"]
    ctx = next(w for w in wfs if w["id"] == wf_id)["context"]
    assert ctx == CTX, ctx


def test_org_profile_roundtrip(owner_h):
    r = client.post("/api/org/profile",
                    json={"org_type": "government", "size": "large",
                          "department": "revenue"}, headers=owner_h)
    assert r.status_code == 200, r.text
    got = client.get("/api/org/profile", headers=owner_h).json()["profile"]
    assert got["org_type"] == "government" and got["department"] == "revenue"
    # invalid profile refused
    r = client.post("/api/org/profile",
                    json={"org_type": "individual", "size": "large",
                          "department": "personal"}, headers=owner_h)
    assert r.status_code == 422, r.text


def test_processes_carry_context(owner_h):
    r = client.post("/api/processes",
                    json={"name": "AP processing", "org_type": "corporate",
                          "size": "medium", "department": "finance",
                          "process_type": "accounts_payable"}, headers=owner_h)
    assert r.status_code == 200, r.text
    procs = client.get("/api/processes", headers=owner_h).json()["processes"]
    row = next(p for p in procs if p["name"] == "AP processing")
    assert row["org_type"] == "corporate" and row["process_type"] == "accounts_payable"
    # incoherent context refused
    r = client.post("/api/processes",
                    json={"name": "bad", "org_type": "corporate", "size": "solo",
                          "department": "finance", "process_type": "tax_filing"},
                    headers=owner_h)
    assert r.status_code == 422, r.text
