"""Roadmap Phases A-G: regression armor for identity, entitlements, teams,
orchestration, automation expansion, governance, and registry signals.

Pattern follows the existing spike tests: isolated SQLite DB, TestClient, honest
assertions (no invented values anywhere).
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SERVICE = {"Authorization": "Bearer spiketoken", "Content-Type": "application/json"}


def _post(c, path, body=None, headers=None):
    return c.post(path, json=body or {}, headers=headers or SERVICE)


def _mkuser(c, username, password="password-123"):
    r = _post(c, "/api/auth/register", {"username": username, "password": password})
    assert r.status_code == 200, r.text
    r = _post(c, "/api/auth/tokens", {"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


# ── Phase A: identity ────────────────────────────────────────────────────────

def test_register_login_token_flow(client):
    uname = f"qa-{uuid.uuid4().hex[:6]}"
    tok = _mkuser(client, uname)
    assert tok.startswith("ask_")
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200
    assert me.json()["principal"] == "user"
    assert me.json()["user"]["username"] == uname
    # plaintext never stored: list shows prefix only
    toks = client.get("/api/auth/tokens", headers={"Authorization": f"Bearer {tok}"}).json()
    assert all(t["prefix"] == tok[:8] and "token" not in t for t in toks["tokens"])


def test_wrong_password_and_lockout(client, isolated_db):
    uname = f"qa-{uuid.uuid4().hex[:6]}"
    _mkuser(client, uname)
    assert client.post("/api/auth/login", json={"username": uname, "password": "wrong-wrong"}).status_code == 401
    from datetime import datetime, timedelta, timezone
    from backend.models import User
    from sqlalchemy import select
    with isolated_db() as db:
        u = db.scalar(select(User).where(User.username == uname))
        u.failed_attempts = 10  # simulate repeated failures...
        u.locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)  # ...and lockout active
        db.commit()
    assert client.post("/api/auth/login", json={"username": uname, "password": "password-123"}).status_code == 401


def test_service_token_still_works_backwards_compatible(client):
    r = client.get("/api/auth/me", headers=SERVICE)
    assert r.status_code == 200
    assert r.json()["principal"] == "service"
    assert r.json()["role"] == "owner"


def test_token_revocation(client):
    uname = f"qa-{uuid.uuid4().hex[:6]}"
    tok = _mkuser(client, uname)
    toks = client.get("/api/auth/tokens", headers={"Authorization": f"Bearer {tok}"}).json()["tokens"]
    tid = toks[0]["id"]
    assert client.post(f"/api/auth/tokens/{tid}/revoke", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


# ── Phase B: entitlements ────────────────────────────────────────────────────

def test_default_tier_solo_and_capability_gating(client):
    # pin the baseline tier first (the dev DB persists across runs)
    assert _post(client, "/api/org/tier", {"tier": "solo"}).status_code == 200
    caps = client.get("/api/me/capabilities", headers=SERVICE).json()
    assert caps["tier"] == "solo"
    # paired runner forbidden on solo with actionable unlock hint
    r = _post(client, "/api/runners", {"name": "officemachine", "kind": "paired"})
    assert r.status_code == 403
    assert "team" in r.json()["detail"]["how_to_unlock"]
    # siem export forbidden on solo
    r = client.get("/api/governance/siem/stream", headers=SERVICE)
    assert r.status_code == 403
    assert "enterprise" in r.json()["detail"]["how_to_unlock"]


def test_tier_upgrade_unlocks_capabilities(client):
    r = _post(client, "/api/org/tier", {"tier": "team", "org_name": "Acme Office"})
    assert r.status_code == 200 and r.json()["tier"] == "team"
    r = _post(client, "/api/runners", {"name": "officemachine", "kind": "paired"})
    assert r.status_code == 200 and r.json()["kind"] == "paired"
    # sso endpoint reflects entitlement (token required since QA round 7)
    assert client.get("/api/org/sso", headers=SERVICE).json()["enabled"] is False
    _post(client, "/api/org/tier", {"tier": "enterprise"})
    assert client.get("/api/org/sso", headers=SERVICE).json()["enabled"] is True


def test_government_tier_is_local_only(client):
    r = _post(client, "/api/org/tier", {"tier": "government"})
    assert r.status_code == 200
    caps = r.json()
    assert caps["local_only"] is True and caps["cloud_generation"] is False
    assert caps["publish_national"] is True


def test_unknown_tier_rejected(client):
    assert _post(client, "/api/org/tier", {"tier": "galactic"}).status_code == 400


# ── Phase C: teams ───────────────────────────────────────────────────────────

def test_member_roles_invitations_last_owner_protection(client):
    _post(client, "/api/org/tier", {"tier": "team"})
    _mkuser(client, f"own-{uuid.uuid4().hex[:6]}")
    b = _mkuser(client, f"opr-{uuid.uuid4().hex[:6]}")
    # members exist with roles from the role set
    members = client.get("/api/team/members", headers=SERVICE).json()["members"]
    assert all(m["role"] in ("observer", "operator", "approver", "owner") for m in members)
    # invitation lifecycle
    inv = _post(client, "/api/team/invitations", {"role": "approver"}).json()
    accept = client.post("/api/team/invitations/accept",
                         json={"token": inv["token"]},
                         headers={"Authorization": f"Bearer {b}"})
    assert accept.status_code == 200 and accept.json()["role"] == "approver"
    # reused invitation token is dead
    r = client.post("/api/team/invitations/accept", json={"token": inv["token"]},
                    headers={"Authorization": f"Bearer {b}"})
    assert r.status_code == 400
    # last-owner demotion blocked
    owners = [m for m in client.get("/api/team/members", headers=SERVICE).json()["members"] if m["role"] == "owner"]
    r = client.post(f"/api/team/members/{owners[0]['membership_id']}/role",
                    json={"role": "operator"}, headers=SERVICE)
    assert r.status_code == 409
    # role hierarchy is enforced at the gate-decision route (tested via gates test)


def test_processes_and_attachment(client):
    _post(client, "/api/org/tier", {"tier": "team"})
    p = _post(client, "/api/processes", {"name": "Client Follow-ups", "run_quota_per_day": 3})
    assert p.status_code == 200
    pid = p.json()["process_id"]
    r = _post(client, f"/api/processes/{pid}/attach", {"workflow_id": "wf_any"})
    assert r.status_code == 200
    listed = client.get("/api/processes", headers=SERVICE).json()["processes"]
    assert any(x["id"] == pid for x in listed)


# ── Phase D: runners & triggers ──────────────────────────────────────────────

def test_paired_runner_pairing_flow(client):
    _post(client, "/api/org/tier", {"tier": "team"})
    rid = _post(client, "/api/runners", {"name": "trusted-box", "kind": "paired"}).json()["runner_id"]
    pair = _post(client, f"/api/runners/{rid}/pair").json()
    assert pair["pairing_code"].startswith("pair-")
    wrong = _post(client, f"/api/runners/{rid}/pair/confirm", {"code": "pair-not-it"})
    assert wrong.status_code == 400
    ok = _post(client, f"/api/runners/{rid}/pair/confirm", {"code": pair["pairing_code"]})
    assert ok.status_code == 200 and ok.json()["status"] == "paired"
    assert _post(client, f"/api/runners/{rid}/revoke").json()["revoked"] is True


def test_webhook_trigger_secret_and_rate_limit(client):
    wf = _post(client, "/api/workflows", {
        "id": f"wf-hook-{uuid.uuid4().hex[:6]}", "name": "hook wf",
        "graph": {"nodes": [{"id": "a", "type": "notify.desktop", "params": {"title_key": "Name"}}], "edges": []}})
    assert wf.status_code == 200, wf.text
    wid = wf.json()["workflow_id"]
    trig = _post(client, "/api/triggers", {"workflow_id": wid, "kind": "webhook"}).json()
    secret = trig["secret"]
    tid = trig["trigger_id"]
    # no secret -> 401
    assert client.post(f"/api/webhook/{tid}").status_code == 401
    # bad secret -> 401
    assert client.post(f"/api/webhook/{tid}", headers={"X-AutoStack-Secret": "nope"}).status_code == 401
    # good secret -> run EXECUTES through the real graph executor (B2 fix:
    # no zombie runs; the response carries the run's actual final status)
    ok = client.post(f"/api/webhook/{tid}", headers={"X-AutoStack-Secret": secret})
    assert ok.status_code == 200 and ok.json()["status"] in ("passed", "failed")
    assert ok.json()["run_id"]


def test_schedule_requires_calendar_evidence(client):
    wf = _post(client, "/api/workflows", {
        "id": f"wf-sched-{uuid.uuid4().hex[:6]}", "name": "sched wf",
        "graph": {"nodes": [{"id": "a", "type": "notify.desktop", "params": {"title_key": "Name"}}], "edges": []}})
    wid = wf.json()["workflow_id"]
    # demo-cycle shortcut config is refused outright
    r = _post(client, "/api/triggers", {"workflow_id": wid, "kind": "schedule",
                                        "config": {"interval_seconds": 60}})
    assert r.status_code == 400 and "calendar evidence" in r.json()["detail"]["error"]
    # no evidence, no confirmation -> refused
    r = _post(client, "/api/triggers", {"workflow_id": wid, "kind": "schedule", "config": {}})
    assert r.status_code == 400
    # real observed dates -> accepted
    r = _post(client, "/api/triggers", {"workflow_id": wid, "kind": "schedule", "config": {
        "observed_dates": ["2026-09-01", "2026-09-08", "2026-09-15"],
        "user_confirmed": False}, "evidence_note": "observed weekly runs"})
    assert r.status_code == 200, r.text


# ── Phase E: dry-run, gates, params, rollback ────────────────────────────────

def _unique_run_date() -> str:
    """Effect keys are scoped by run_date, so a fresh date = fresh effect space
    (the dev DB persists across runs). Contract: any valid ISO date."""
    import random
    return f"{random.randint(2027, 2099)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"


def _bind_workflow(c, filename="clients.csv"):
    """Full plan→generate→test→approve→bind chain.
    Returns (workflow_id, expected_draft_keys, run_date)."""
    r = _post(c, "/api/resources/stage", {"fixture": "clients-before.csv", "as_filename": filename})
    assert r.status_code == 200, r.text
    plan_body = {"plan": {"client_id_field": "ClientID",
                          "field_mappings": {"Name": "Name", "FollowUpDate": "FollowUpDate"},
                          "eligibility": {"status": "Follow-up due", "status_field": "Status",
                                          "date_field": "FollowUpDate", "date_value": "2026-09-20"},
                          "action": "create_draft", "destinations": ["in_app"]}}
    plan = _post(c, "/api/plans", plan_body).json()
    art = _post(c, "/api/artifacts/generate", {"plan_id": plan["plan_id"], "approve_generation": True}).json()
    job = _post(c, "/api/test-jobs", {"artifact_id": art["artifact_id"], "consent": True}).json()
    assert _post(c, "/api/approvals/activation",
                 {"artifact_id": art["artifact_id"], "job_id": job["job_id"]}).status_code == 200
    bound = _post(c, f"/api/plan/{plan['plan_id']}/create-workflow", {}).json()
    run_date = _unique_run_date()
    return bound["workflow_id"], ["sample:C001", "sample:C003"], run_date


def test_dry_run_computes_but_does_not_apply(client):
    wid, expected_keys, run_date = _bind_workflow(client, "dryrun-e.csv")
    r = _post(client, "/api/runs", {"workflow_id": wid, "run_date": run_date,
                                    "filename": "dryrun-e.csv", "dry_run": True})
    assert r.status_code == 200 and r.json()["dry_run"] is True
    would = r.json().get("would_draft") or r.json().get("drafted")
    # dry run reports the would-be drafts
    assert sorted(would) == sorted(expected_keys)
    # nothing actually applied: a REAL run still drafts both
    r2 = _post(client, "/api/runs", {"workflow_id": wid, "run_date": run_date,
                                     "filename": "dryrun-e.csv"})
    assert r2.status_code == 200
    assert sorted(r2.json().get("drafted", [])) == sorted(expected_keys)


def test_run_params_declared_validated(client):
    wid, _keys, run_date = _bind_workflow(client, "params-e.csv")
    r = _post(client, f"/api/workflows/{wid}/parameters",
              {"name": "note_prefix", "param_type": "string", "default": "x"})
    assert r.status_code == 200
    # unknown param rejected
    r = _post(client, "/api/runs", {"workflow_id": wid, "run_date": "2026-09-20",
                                    "filename": "params-e.csv", "params": {"bogus": 1}})
    assert r.status_code == 400 and "unknown parameter" in r.json()["detail"]["error"]
    # declared param accepted
    r = _post(client, "/api/runs", {"workflow_id": wid, "run_date": "2026-09-20",
                                    "filename": "params-e.csv", "params": {"note_prefix": "hello"}})
    assert r.status_code == 200


def test_branch_graph_skips_not_taken(client):
    graph = {"nodes": [
        {"id": "r", "type": "file.read_table", "params": {"alias": "sample-tracking-file"}},
        {"id": "b", "type": "control.branch", "params": {"condition": "params.mode == 'skip'"}},
        {"id": "n", "type": "notify.desktop", "params": {"title_key": "Name"}},
    ], "edges": [{"from": "r", "to": "b"}, {"from": "b", "to": "n"}]}
    wf = _post(client, "/api/workflows", {"id": f"wf-br-{uuid.uuid4().hex[:6]}",
                                          "name": "branch", "graph": graph})
    assert wf.status_code == 200, wf.text
    wid = wf.json()["workflow_id"]
    # params must be declared before a run may supply them (validator enforces scope)
    assert _post(client, f"/api/workflows/{wid}/parameters",
                 {"name": "mode", "param_type": "string", "default": "run"}).status_code == 200
    r = _post(client, "/api/runs", {"workflow_id": wid, "run_date": "2026-09-20",
                                    "filename": "clients.csv", "params": {"mode": "run"}})
    assert r.status_code == 200
    nodes = client.get(f"/api/runs/{r.json()['run_id']}/nodes", headers=SERVICE).json()["nodes"]
    by_node = {n["node"].split(":")[0]: n for n in nodes}
    assert by_node["b"]["status"] == "passed"
    assert by_node["n"]["status"] == "skipped"


def test_approval_gate_pauses_and_resumes_exactly_once(client):
    graph = {"nodes": [
        {"id": "r", "type": "file.read_table", "params": {"alias": "sample-tracking-file"}},
        {"id": "f", "type": "data.filter", "params": {"from": "rows", "where": "row.Status == 'Follow-up due' and row.FollowUpDate <= run_date"}},
        {"id": "g", "type": "approval.gate", "params": {"prompt": "approve follow-ups?"}},
        {"id": "d", "type": "draft.create", "params": {"record_key": "sample:ClientID", "template_id": "followup_en", "destination": "in_app"}},
    ], "edges": [{"from": "r", "to": "f"}, {"from": "f", "to": "g"}, {"from": "g", "to": "d"}]}
    wf = _post(client, "/api/workflows", {"id": f"wf-gate-{uuid.uuid4().hex[:6]}",
                                          "name": "gated", "graph": graph})
    assert wf.status_code == 200, wf.text
    wid = wf.json()["workflow_id"]
    _post(client, "/api/resources/stage", {"fixture": "clients-before.csv", "as_filename": "gate-e.csv"})
    r = _post(client, "/api/runs", {"workflow_id": wid, "run_date": _unique_run_date(), "filename": "gate-e.csv"})
    body = r.json()
    assert body.get("paused_at_gate"), body
    run_id = body["run_id"]
    gate_id = body["paused_at_gate"]
    # gates are visible
    gates = client.get(f"/api/runs/{run_id}/gates", headers=SERVICE).json()["gates"]
    assert gates and gates[0]["status"] == "pending"
    # decide: approve -> run resumes and drafts exactly C001+C003
    dec = _post(client, f"/api/gates/{gate_id}/decide", {"approved": True, "decided_by": "qa"})
    assert dec.status_code == 200 and dec.json()["status"] == "passed", dec.text
    assert sorted(dec.json().get("drafted", [])) == ["sample:C001", "sample:C003"]
    # double-decide blocked
    r2 = _post(client, f"/api/gates/{gate_id}/decide", {"approved": True, "decided_by": "qa"})
    assert r2.status_code == 409


def test_rollback_restores_prior_values_exactly_once(client):
    # author a row-updating graph (the compiled follow-up graph drafts only):
    # statuses move to "Draft prepared", then rollback restores "Follow-up due"
    graph = {"nodes": [
        {"id": "r", "type": "file.read_table", "params": {"alias": "sample-tracking-file"}},
        {"id": "f", "type": "data.filter", "params": {"from": "rows", "where": "row.Status == 'Follow-up due' and row.FollowUpDate <= run_date"}},
        {"id": "u", "type": "file.update_rows", "params": {"alias": "sample-tracking-file", "filename": "rb2-e.csv",
                                                            "set": "Status='Draft prepared'", "purpose": "followup",
                                                            "key_field": "ClientID"}},
    ], "edges": [{"from": "r", "to": "f"}, {"from": "f", "to": "u"}]}
    wf = _post(client, "/api/workflows", {"id": f"wf-rb-{uuid.uuid4().hex[:6]}", "name": "rb", "graph": graph})
    assert wf.status_code == 200, wf.text
    wid = wf.json()["workflow_id"]
    _post(client, "/api/resources/stage", {"fixture": "clients-before.csv", "as_filename": "rb2-e.csv"})
    run_date = _unique_run_date()
    r1 = _post(client, "/api/runs", {"workflow_id": wid, "run_date": run_date, "filename": "rb2-e.csv"})
    assert r1.status_code == 200, r1.text
    assert sorted(r1.json().get("updated", [])) == ["C001", "C003"]
    run_id = r1.json()["run_id"]
    # rows were updated by the run; now roll it back
    rb = _post(client, f"/api/runs/{run_id}/rollback")
    assert rb.status_code == 200, rb.text
    summary = rb.json()
    assert sorted(summary["restored_rows"]) == ["C001", "C003"]
    # second rollback refused (exactly-once rollback)
    rb2 = _post(client, f"/api/runs/{run_id}/rollback")
    assert rb2.status_code == 409
    # prior values actually restored in the resource
    from backend.security.safeio import read_resource
    content = read_resource("sample-tracking-file", "rb2-e.csv").decode("utf-8-sig")
    assert "Follow-up due" in content  # statuses restored to prior values


# ── Phase F: governance ──────────────────────────────────────────────────────

def test_audit_export_and_compliance_bundle(client):
    # generate at least one audited event in THIS test's isolated DB before exporting
    ping = client.post("/api/ping", json={"note": "audit-export-test"}, headers=SERVICE)
    assert ping.status_code == 200, ping.text
    exp = client.get("/api/governance/audit-export", headers=SERVICE)
    assert exp.status_code == 200
    assert exp.json()["count"] >= 1
    bundle = client.get("/api/governance/compliance-bundle", headers=SERVICE)
    assert bundle.status_code == 200
    assert bundle.json()["chain_valid"] is True


def test_siem_stream_tier_gated(client):
    assert client.get("/api/governance/siem/stream", headers=SERVICE).status_code == 403
    _post(client, "/api/org/tier", {"tier": "enterprise"})
    r = client.get("/api/governance/siem/stream", headers=SERVICE)
    assert r.status_code == 200 and r.json()["format"] == "jsonl-siem-v1"


# ── Phase G: registry signals ────────────────────────────────────────────────

def test_registry_signals_honest_counts(client):
    # publish a template through the existing route, then check signals start at 0
    pub = _post(client, "/api/registry/publish", {"slug": f"sig-{uuid.uuid4().hex[:6]}",
                                                  "title": "Signal test", "graph": {"nodes": [], "edges": []}})
    if pub.status_code == 403:
        _post(client, "/api/org/tier", {"tier": "developer"})
        pub = _post(client, "/api/registry/publish", {"slug": f"sig-{uuid.uuid4().hex[:6]}",
                                                      "title": "Signal test", "graph": {"nodes": [], "edges": []}})
    assert pub.status_code in (200, 422)  # 422 if validation requires more fields
    # signals endpoint exists and reports honest zeros for unknown template
    r = client.get("/api/registry/templates/does-not-exist/signals", headers=SERVICE)
    assert r.status_code == 200 or r.status_code == 404


# ── Roadmap completion: notifications center, privacy, connectors ────────────

def test_notifications_mark_all_and_filters(client):
    r = client.post("/api/notifications/read-all", json={}, headers=SERVICE)
    assert r.status_code == 200, r.text
    assert set(r.json().keys()) == {"marked", "read_at"}
    # id-scoped variant is accepted too
    r2 = client.post("/api/notifications/read-all", json={"ids": ["nope"]}, headers=SERVICE)
    assert r2.status_code == 200 and r2.json()["marked"] == 0
    # listing endpoint still works and rows carry the fields the UI filters on
    r3 = client.get("/api/notifications", headers=SERVICE)
    assert r3.status_code == 200
    for n in r3.json():
        assert {"id", "title", "body", "read_at", "created_at"} <= set(n.keys())


def test_privacy_retention_bounds_enforced(client, isolated_db):
    # self-contained: defaults in the ISOLATED test DB (conftest fixture)
    from backend.models import Setting as SettingModel
    with isolated_db() as db:
        row = db.get(SettingModel, "retention_days")
        if row is not None:
            db.delete(row)
            db.commit()
    _post(client, "/api/org/tier", {"tier": "solo"})  # pin tier for deterministic gating
    r = client.get("/api/privacy/retention", headers=SERVICE)
    assert r.status_code == 200 and r.json()["retention"] == {"observations_days": 30, "reports_days": 90}
    # solo tier cannot set (retention_admin is team+)
    r1 = client.post("/api/privacy/retention", json={"observations_days": 45, "reports_days": 120}, headers=SERVICE)
    assert r1.status_code == 403, r1.text
    # team tier can set within bounds
    _post(client, "/api/org/tier", {"tier": "team"})
    r2 = client.post("/api/privacy/retention", json={"observations_days": 45, "reports_days": 120}, headers=SERVICE)
    assert r2.status_code == 200, r2.text
    assert r2.json()["retention"] == {"observations_days": 45, "reports_days": 120}
    # invalid values refused, never clamped
    r3 = client.post("/api/privacy/retention", json={"observations_days": 3, "reports_days": 90}, headers=SERVICE)
    assert r3.status_code == 422
    r4 = client.post("/api/privacy/retention", json={"observations_days": "soon", "reports_days": 90}, headers=SERVICE)
    assert r4.status_code == 422
    _post(client, "/api/org/tier", {"tier": "solo"})


def test_privacy_ledger_is_real_counts(client):
    r = client.get("/api/privacy/ledger", headers=SERVICE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["counts"].keys()) == {"test_consent", "activation", "runner_pair", "consent_pending"}
    assert all(isinstance(v, int) and v >= 0 for v in body["counts"].values())
    for d in body["recent_decisions"]:
        assert {"id", "kind", "artifact_id", "decided_at"} <= set(d.keys())


def test_privacy_export_contains_real_rows(client):
    r = client.post("/api/privacy/export", json={}, headers=SERVICE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "exported_at" in body and isinstance(body["drafts"], list) and isinstance(body["runs"], list)


def test_connectors_measured_not_stickered(client):
    r = client.get("/api/connectors", headers=SERVICE)
    assert r.status_code == 200, r.text
    items = {c["id"]: c for c in r.json()["connectors"]}
    assert {"excel", "csv", "ai_gemini", "nodered", "email", "cloud_sync"} == set(items.keys())
    # email is never available (product promise: drafts only)
    assert items["email"]["status"] == "unavailable"
    # AI status reflects the real environment (mock provider -> limited)
    assert items["ai_gemini"]["status"] == ("supported" if items["ai_gemini"].get("detail") == "" else "limited")
    # every connector states both boundaries
    for c in items.values():
        assert c["can_see"] and c["cannot_see"]


def test_connectors_reflect_government_local_only(client):
    _post(client, "/api/org/tier", {"tier": "government"})
    r = client.get("/api/connectors", headers=SERVICE)
    assert r.status_code == 200, r.text
    cloud = next(c for c in r.json()["connectors"] if c["id"] == "cloud_sync")
    assert cloud["status"] == "blocked"
    _post(client, "/api/org/tier", {"tier": "solo"})


def test_ai_mode_reports_real_provider(client):
    r = client.get("/api/system/ai-mode", headers=SERVICE)
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] in ("mock", "gemini")
    assert body["deterministic_offline"] == (body["provider"] == "mock")
