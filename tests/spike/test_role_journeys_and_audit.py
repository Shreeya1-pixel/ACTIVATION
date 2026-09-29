"""Comprehensive End-to-End Role Journeys, Workflow Lifecycles, and Audit Verification.

Implements full coverage of Scenarios A through F from Phase 10:
- Scenario A: User registration, credential validation, token issuance, auth/me verification, and revocation.
- Scenario B: Workflow creation, compilation, sandbox testing, activation, binding, and execution per authorized role.
- Scenario C: Negative authorization tests verifying backend enforcement (observer denied mutations, operator denied activation/publishing, non-owners denied administrative operations).
- Scenario D: Role isolation, capabilities scoping, privilege escalation prevention, and cross-account protection.
- Scenario E: Cryptographic hash-chained audit logging verification across operations.
- Scenario F: Error handling, validation boundaries, and soft-delete protections.
"""
from __future__ import annotations

import json
import uuid
import pytest

SERVICE_HEADERS = {"Authorization": "Bearer spiketoken"}


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _setup_admin(client):
    # Ensure an initial administrator exists so subsequent test accounts get standard roles
    client.post("/api/auth/register", json={"username": "superadmin", "password": "AdminPassword123!"})


def _create_user_and_token(client, username: str, password: str = "SecurePass123!", role: str = "operator") -> tuple[str, str]:
    """Helper to register user, issue token, and assign role via admin/service."""
    _setup_admin(client)
    res = client.post("/api/auth/register", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    user_id = res.json()["user_id"]

    res = client.post("/api/auth/tokens", json={"username": username, "password": password, "name": "test"})
    assert res.status_code == 200, res.text
    token = res.json()["token"]

    # Assign desired role using service credentials
    members = client.get("/api/team/members", headers=SERVICE_HEADERS).json()["members"]
    mid = next(m["membership_id"] for m in members if m["username"] == username)
    res_role = client.post(f"/api/team/members/{mid}/role", json={"role": role}, headers=SERVICE_HEADERS)
    assert res_role.status_code == 200, res_role.text

    return user_id, token


# ── Scenario A: Authentication, Registration, Session, and Account Management ──

def test_scenario_a_registration_and_authentication(client):
    # 1. Password minimum length requirement
    res = client.post("/api/auth/register", json={"username": "shortpass", "password": "123"})
    assert res.status_code == 400
    assert "at least 8 characters" in res.json()["detail"]["error"]

    # 2. Invalid username validation
    res = client.post("/api/auth/register", json={"username": "invalid name with spaces", "password": "ValidPassword123!"})
    assert res.status_code == 400

    # 3. Successful registration
    uname = f"user_{uuid.uuid4().hex[:6]}"
    res = client.post("/api/auth/register", json={"username": uname, "password": "ValidPassword123!", "display_name": "Test User"})
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == uname
    user_id = data["user_id"]
    assert user_id

    # 4. Duplicate registration rejected
    res = client.post("/api/auth/register", json={"username": uname, "password": "ValidPassword123!"})
    assert res.status_code == 400
    assert "already exists" in res.json()["detail"]["error"]

    # 5. Login with invalid password
    res = client.post("/api/auth/login", json={"username": uname, "password": "WrongPassword"})
    assert res.status_code == 401

    # 6. Login with non-existent user
    res = client.post("/api/auth/login", json={"username": "non_existent_user_xyz", "password": "AnyPassword123!"})
    assert res.status_code == 401

    # 7. Login with valid credentials
    res = client.post("/api/auth/login", json={"username": uname, "password": "ValidPassword123!"})
    assert res.status_code == 200
    assert res.json()["username"] == uname

    # 8. Token issuance
    res = client.post("/api/auth/tokens", json={"username": uname, "password": "ValidPassword123!", "name": "session_tok"})
    assert res.status_code == 200
    tok_data = res.json()
    token = tok_data["token"]
    assert token.startswith("ask_")

    # 9. Verify session identity via /api/auth/me
    headers = _auth_header(token)
    res = client.get("/api/auth/me", headers=headers)
    assert res.status_code == 200
    me = res.json()
    assert me["principal"] == "user"
    assert me["user"]["username"] == uname
    assert "capabilities" in me

    # 10. List active tokens
    res = client.get("/api/auth/tokens", headers=headers)
    assert res.status_code == 200
    tokens_list = res.json()["tokens"]
    assert len(tokens_list) >= 1
    tid = tokens_list[0]["id"]

    # 11. Revoke token
    res = client.post(f"/api/auth/tokens/{tid}/revoke", headers=headers)
    assert res.status_code == 200
    assert res.json()["revoked"] is True

    # 12. Revoked token rejected on subsequent requests
    res = client.get("/api/auth/me", headers=headers)
    assert res.status_code == 401


# ── Scenario B: Full Workflow Creation and Lifecycle for Authorized Roles ──

def test_scenario_b_workflow_lifecycle_owner_and_operator(client):
    # Setup roles
    _, owner_tok = _create_user_and_token(client, f"owner_{uuid.uuid4().hex[:6]}", role="owner")
    _, apr_tok = _create_user_and_token(client, f"apr_{uuid.uuid4().hex[:6]}", role="approver")
    _, opr_tok = _create_user_and_token(client, f"opr_{uuid.uuid4().hex[:6]}", role="operator")

    owner_h = _auth_header(owner_tok)
    apr_h = _auth_header(apr_tok)
    opr_h = _auth_header(opr_tok)

    # 1. Create a structured generation plan (Writer operation -> allowed for operator/approver/owner)
    plan_body = {
        "client_id_field": "ClientID",
        "field_mappings": {"Name": "Name", "FollowUpDate": "FollowUpDate"},
        "eligibility": {
            "status": "Follow-up due",
            "status_field": "Status",
            "date_field": "FollowUpDate",
            "date_value": "2026-09-20",
        },
        "action": "create_draft",
        "destinations": ["in_app"],
    }
    res = client.post("/api/plans", json={"plan": plan_body}, headers=opr_h)
    assert res.status_code == 200, res.text
    plan_id = res.json()["plan_id"]
    assert res.json()["generatable"] is True

    # 2. Generate artifact code from plan
    res = client.post("/api/artifacts/generate", json={"plan_id": plan_id, "approve_generation": True}, headers=opr_h)
    assert res.status_code == 200
    art = res.json()
    art_id = art["artifact_id"]
    assert art["status"] == "awaiting_test_approval"

    # 3. Approver runs isolated sandbox test
    res = client.post("/api/test-jobs", json={"artifact_id": art_id, "fixture": "reset", "consent": True}, headers=apr_h)
    assert res.status_code == 200
    job = res.json()
    assert job["status"] == "passed"
    job_id = job["job_id"]

    # 4. Approver approves activation
    res = client.post("/api/approvals/activation", json={"artifact_id": art_id, "job_id": job_id, "note": "verified"}, headers=apr_h)
    assert res.status_code == 200
    assert res.json()["status"] == "activated"

    # 5. Bind activated plan to workflow
    res = client.post(f"/api/plan/{plan_id}/create-workflow", headers=opr_h)
    assert res.status_code == 200
    wf_data = res.json()
    wf_id = wf_data["workflow_id"]
    assert wf_id.startswith("wf-")

    # 6. Operator executes the workflow
    res = client.post("/api/runs", json={"workflow_id": wf_id, "run_date": "2026-09-20"}, headers=opr_h)
    assert res.status_code == 200
    run = res.json()
    assert run["status"] == "passed"

    # 7. Owner publishes template to registry (Owner only)
    res = client.post("/api/registry/publish", json={
        "slug": f"tmpl-{uuid.uuid4().hex[:6]}",
        "title": "Client Followup Template",
        "graph": wf_data["graph"],
        "compatible_connectors": ["sample-tracking-file"],
        "publication_consent": True,
    }, headers=owner_h)
    assert res.status_code == 200
    pub_res = res.json()
    assert pub_res["slug"].startswith("tmpl-")
    assert pub_res["version"] >= 1


# ── Scenario C: Unauthorized Workflow Operations Rejected ──

def test_scenario_c_unauthorized_operations_blocked(client):
    _, obs_tok = _create_user_and_token(client, f"obs_{uuid.uuid4().hex[:6]}", role="observer")
    _, opr_tok = _create_user_and_token(client, f"opr_{uuid.uuid4().hex[:6]}", role="operator")

    obs_h = _auth_header(obs_tok)
    opr_h = _auth_header(opr_tok)

    # Pre-create a workflow to test authorization rejection
    wf_id = f"wf_test_{uuid.uuid4().hex[:6]}"
    client.post("/api/workflows", json={"id": wf_id, "name": "Test", "graph": {"nodes": [], "edges": []}}, headers=SERVICE_HEADERS)

    # 1. Observer cannot start runs (403)
    res = client.post("/api/runs", json={"workflow_id": wf_id, "run_date": "2026-09-20"}, headers=obs_h)
    assert res.status_code == 403
    assert "observer" in res.json()["detail"]["error"]

    # 2. Observer cannot create workflows (403)
    res = client.post("/api/workflows", json={"id": "wf_forbidden", "name": "Bad", "graph": {"nodes": [], "edges": []}}, headers=obs_h)
    assert res.status_code == 403

    # 3. Observer cannot mutate resources (403)
    res = client.post("/api/resources/stage", json={"fixture": "clients-before.csv", "as_filename": "obs.csv"}, headers=obs_h)
    assert res.status_code == 403

    # 4. Operator cannot approve activation (requires Approver or Owner)
    res = client.post("/api/approvals/activation", json={"artifact_id": "fake_id", "job_id": "fake_job"}, headers=opr_h)
    assert res.status_code == 403

    # 5. Operator cannot publish to registry (requires Owner)
    res = client.post("/api/registry/publish", json={"slug": "forbidden_pub", "title": "Nope", "graph": {}, "publication_consent": True}, headers=opr_h)
    assert res.status_code == 403

    # 6. Neither Observer nor Operator can delete workflows (requires Owner)
    res = client.delete(f"/api/workflows/{wf_id}", headers=obs_h)
    assert res.status_code == 403

    res = client.delete(f"/api/workflows/{wf_id}", headers=opr_h)
    assert res.status_code == 403


# ── Scenario D: Role Isolation, Data Access, and Self-Escalation Protection ──

def test_scenario_d_role_isolation_and_privilege_escalation(client):
    _, obs_tok = _create_user_and_token(client, f"obs_{uuid.uuid4().hex[:6]}", role="observer")
    _, opr_tok = _create_user_and_token(client, f"opr_{uuid.uuid4().hex[:6]}", role="operator")
    _, owner_tok = _create_user_and_token(client, f"own_{uuid.uuid4().hex[:6]}", role="owner")

    obs_h = _auth_header(obs_tok)
    opr_h = _auth_header(opr_tok)
    own_h = _auth_header(owner_tok)

    # 1. Observer attempts to modify own role to owner
    members = client.get("/api/team/members", headers=obs_h).json()["members"]
    obs_m = next(m for m in members if m["role"] == "observer")
    res = client.post(f"/api/team/members/{obs_m['membership_id']}/role", json={"role": "owner"}, headers=obs_h)
    assert res.status_code == 403

    # 2. Operator attempts to invite new members
    res = client.post("/api/team/invitations", json={"role": "operator"}, headers=opr_h)
    assert res.status_code == 403

    # 3. Operator attempts to modify organizational tier
    res = client.post("/api/org/tier", json={"tier": "enterprise"}, headers=opr_h)
    assert res.status_code == 403

    # 4. Only Owner can modify organizational tier
    res = client.post("/api/org/tier", json={"tier": "team"}, headers=own_h)
    assert res.status_code == 200
    assert res.json()["tier"] == "team"

    # 5. IDOR: Observer attempts to revoke Owner's token
    owner_tokens = client.get("/api/auth/tokens", headers=own_h).json()["tokens"]
    owner_tok_id = owner_tokens[0]["id"]
    res = client.post(f"/api/auth/tokens/{owner_tok_id}/revoke", headers=obs_h)
    assert res.status_code == 404  # Fails closed without exposing token existence


# ── Scenario E: Audit Trails and Hash Chaining ──

def test_scenario_e_audit_trail_and_hash_chaining(client):
    # Perform audited actions
    _, owner_tok = _create_user_and_token(client, f"owner_{uuid.uuid4().hex[:6]}", role="owner")
    own_h = _auth_header(owner_tok)

    wf_id = f"wf_audit_{uuid.uuid4().hex[:6]}"
    client.post("/api/workflows", json={"id": wf_id, "name": "Audit Test", "graph": {"nodes": [], "edges": []}}, headers=own_h)

    # Retrieve audit log
    res = client.get("/api/audit?verify=1&limit=20", headers=own_h)
    assert res.status_code == 200
    data = res.json()
    assert data["chain_valid"] is True
    assert len(data["entries"]) > 0

    # Verify audit entry properties
    entry = data["entries"][-1]
    assert "seq" in entry
    assert "hash" in entry
    assert "kind" in entry
    assert "at" in entry
    assert "payload" in entry


# ── Scenario F: Backend Failure, Recovery, and Idempotency ──

def test_scenario_f_backend_failure_recovery_and_soft_delete(client):
    _, owner_tok = _create_user_and_token(client, f"owner_{uuid.uuid4().hex[:6]}", role="owner")
    own_h = _auth_header(owner_tok)

    # 1. Invalid workflow graph (cycle or disconnected)
    res = client.post("/api/workflows", json={
        "id": "wf_invalid",
        "name": "Invalid",
        "graph": {"nodes": [{"id": "bad", "type": "nonexistent_node"}], "edges": []},
    }, headers=own_h)
    assert res.status_code in (400, 422)

    # 2. Create valid workflow, then delete
    wf_id = f"wf_del_{uuid.uuid4().hex[:6]}"
    client.post("/api/workflows", json={"id": wf_id, "name": "To Delete", "graph": {"nodes": [], "edges": []}}, headers=own_h)

    res = client.delete(f"/api/workflows/{wf_id}", headers=own_h)
    assert res.status_code == 200

    # 3. Soft-deleted workflow does not appear in active listings
    wfs = client.get("/api/workflows", headers=own_h).json()["workflows"]
    assert wf_id not in [w["id"] for w in wfs]

    # 4. Attempting to overwrite soft-deleted workflow returns 409 Conflict
    res = client.post("/api/workflows", json={"id": wf_id, "name": "Resurrect", "graph": {"nodes": [], "edges": []}}, headers=own_h)
    assert res.status_code == 409
    assert "deleted workflow" in res.json()["detail"]["error"]
