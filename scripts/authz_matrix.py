"""Authorization matrix verification (QA round 7): creates one real account per
role (observer/operator/approver/owner) and drives every protected endpoint with
each role's token against the LIVE server, checking actual HTTP outcomes against
the intended permission model (backend/teams.py PERMISSION_MIN_ROLE).

Role ladder: observer(0) < operator(1) < approver(2) < owner(3); service token
= owner-equivalent. Permission model:
  observe/read   -> observer+   run/stage     -> operator+
  test/activate  -> approver+   publish/admin -> owner

Run-level permission tiers used here:
  W (writer-level, require_writer)  -> observer 403, operator 200/4xx-contract
  A (admin-level, admin_guard)      -> observer/operator 403, approver 403/200*
  R (read, require_token/principal) -> any authenticated role 200
*approver may get contract-4xx (409/422) where the operation itself needs extra
state — the assertion is "not 403" (permission granted), not "200".

Usage: AUTOSTACK_TOKEN=<service token> python scripts/authz_matrix.py
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("AUTOSTACK_BASE", "http://127.0.0.1:8747")
SERVICE = os.environ.get("AUTOSTACK_TOKEN", "")
if not SERVICE:
    print("AUTOSTACK_TOKEN env required", file=sys.stderr)
    sys.exit(2)

RESULTS: list[tuple[bool, str, str]] = []


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token if token is not None else SERVICE}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def check(name, ok, note=""):
    RESULTS.append((ok, name, note))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {note}" if note else ""))


def expect(role, label, got_status, allowed, forbidden_note="403"):
    ok = got_status in allowed
    check(f"{role}: {label}", ok,
          f"got {got_status}, want {'/'.join(map(str, allowed))}" + ("" if ok else f" ({forbidden_note} expected)"))


# ── setup: one account per role ───────────────────────────────────────────────
s, b = call("GET", "/api/team/members")
existing = {m["username"]: m for m in b.get("members", [])}
non_admin_members = [m for m in b.get("members", []) if m["role"] != "owner"]
admin_member = next((m for m in b.get("members", []) if m["role"] == "owner"), None)

TOKENS = {}
PASSWORD = "authz-matrix-pass-1"

print("== setup: role accounts ==")
role_roles = ["observer", "operator", "approver"]
for role in role_roles:
    uname = f"mx-{role}-{secrets.token_hex(3)}"
    s, b = call("POST", "/api/auth/register", {"username": uname, "password": PASSWORD})
    assert s == 200, (role, s, b)
    s, b = call("POST", "/api/auth/tokens", {"username": uname, "password": PASSWORD})
    assert s == 200, (role, s, b)
    TOKENS[role] = b["token"]
    # set role via admin API (service principal is admin)
    s, b = call("GET", "/api/team/members")
    mid = next(m["membership_id"] for m in b["members"] if m["username"] == uname)
    s, b = call("POST", f"/api/team/members/{mid}/role", {"role": role})
    assert s == 200, (role, s, b)
    print(f"  {role}: {uname}")

# owner: use an existing owner membership; create a fresh owner account
uname = f"mx-owner-{secrets.token_hex(3)}"
s, b = call("POST", "/api/auth/register", {"username": uname, "password": PASSWORD})
assert s == 200, b
s, b = call("GET", "/api/team/members")
oid = next(m["membership_id"] for m in b["members"] if m["username"] == uname)
s, b = call("POST", f"/api/team/members/{oid}/role", {"role": "owner"})
assert s == 200, b
s, b = call("POST", "/api/auth/tokens", {"username": uname, "password": PASSWORD})
TOKENS["owner"] = b["token"]
print(f"  owner: {uname}")

# ── fixtures ─────────────────────────────────────────────────────────────────
WID = f"wf-mx-{secrets.token_hex(4)}"
s, b = call("POST", "/api/workflows", {
    "id": WID, "name": "authz matrix target",
    "graph": {"nodes": [{"id": "n", "type": "notify.desktop", "params": {"title_key": "Name"}}],
              "edges": []}})
assert s == 200, b

RUN_DATE = "2027-06-01"
s, b = call("POST", "/api/runs", {"workflow_id": WID, "run_date": RUN_DATE})
RID = b.get("run_id")
assert RID, b

s, b = call("POST", "/api/triggers", {"workflow_id": WID, "kind": "webhook",
                                      "config": {}, "evidence_note": "authz matrix"})
assert s == 200, b
TRIG = b["trigger_id"]
TSECRET = b.get("secret")

import datetime as _dt
import uuid as _uuid
_ev = {"schema_version": 2, "source_version": "authz-matrix-1", "event_id": str(_uuid.uuid4()),
       "captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
       "processed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
       "source": "saved_file_comparison", "action": "row.updated", "resource": "clients",
       "record_key": "clients:C001", "changed_fields": ["Status"], "outcome": "success",
       "synthetic": False}
s, b = call("POST", "/api/events", [_ev])
assert s == 200, b
s, b = call("GET", "/api/candidates")
CAND = next((c["id"] for c in b if isinstance(c, dict) and c.get("status") == "suggested"), None) or \
       next((c["id"] for c in b if isinstance(c, dict)), None)

ROLES = ["observer", "operator", "approver", "owner"]

# ── the matrix ───────────────────────────────────────────────────────────────
print("\n== writer-level operations (observer must be denied) ==")
_ev_body = [{**_ev, "event_id": str(_uuid.uuid4()), "record_key": "clients:C003"}]
WRITER_OPS = [
    ("POST", "/api/runs", {"workflow_id": WID, "run_date": "2027-06-02"}),
    ("POST", "/api/workflows", {"id": "wf-mx-new", "name": "x",
                                "graph": {"nodes": [], "edges": []}}),
    ("POST", "/api/events", _ev_body),
    ("POST", "/api/resources/stage", {"fixture": "clients-before.csv", "as_filename": "mx-stage.csv"}),
    ("POST", "/api/plans", {"client_id_field": "ClientID",
                            "field_mappings": {"Name": "Name"},
                            "eligibility": {"status": "Follow-up due", "status_field": "Status",
                                            "date_field": "FollowUpDate", "date_value": "2026-09-20"},
                            "action": "create_draft", "destinations": ["in_app"]}),
    ("POST", "/api/capture/poll", {}),
]
for method, path, body in WRITER_OPS:
    label = f"{method} {path}"
    for role in ROLES:
        p = path.replace("{r}", role)
        s, _ = call(method, p, body, token=TOKENS[role])
        if role == "observer":
            expect(role, label, s, (403,))
        else:
            expect(role, label, s, (200, 400, 404, 409, 422), "contract error ok")

print("\n== approver-level operations (observer+operator denied) ==")
APPROVER_OPS = [
    ("POST", "/api/test-jobs", {"artifact_id": "nonexistent", "consent": True}),
    ("POST", "/api/approvals/activation", {"artifact_id": "nonexistent", "job_id": "nonexistent"}),
]
for method, path, body in APPROVER_OPS:
    label = f"{method} {path}"
    for role in ROLES:
        p = path.replace("{r}", role)
        s, _ = call(method, p, body, token=TOKENS[role])
        if role in ("observer", "operator"):
            expect(role, label, s, (403,))
        else:
            expect(role, label, s, (200, 400, 404, 409, 422), "contract error ok")

print("\n== publish: owner-only (publish = owner in the permission model) ==")
for role in ROLES:
    s, _ = call("POST", "/api/registry/publish", {"slug": f"mx-{role}-{secrets.token_hex(3)}",
                                                 "title": "t", "publication_consent": True,
                                                 "graph": {"nodes": [], "edges": []}},
                token=TOKENS[role])
    expect(role, "POST /api/registry/publish", s, (200,) if role == "owner" else (403,))

print("\n== registry import (operator+) and withdraw (publish-level, owner) ==")
for role in ROLES:
    s, _ = call("POST", "/api/registry/import", {"template_id": "nonexistent",
                                                 "local_mapping": {}}, token=TOKENS[role])
    expect(role, "POST /api/registry/import", s,
           (403,) if role == "observer" else (200, 400, 404, 409, 422), "contract error ok")
for role in ROLES:
    s, _ = call("POST", "/api/registry/withdraw", {"slug": "mx-nope"}, token=TOKENS[role])
    expect(role, "POST /api/registry/withdraw", s,
           (403,) if role in ("observer", "operator", "approver") else (200, 404, 400, 422),
           "contract error ok")

print("\n== trigger management: operator+ (workflow operations, not admin) ==")
for role in ROLES:
    s, _ = call("POST", "/api/triggers", {"workflow_id": WID, "kind": "file",
                                          "config": {"alias": "sample-tracking-file"},
                                          "evidence_note": "mx"}, token=TOKENS[role])
    expect(role, "POST /api/triggers", s, (403,) if role == "observer" else (200, 400, 404, 409, 422),
           "contract error ok")
for role in ROLES:
    s, _ = call("POST", f"/api/triggers/{TRIG}/disable", token=TOKENS[role])
    expect(role, f"POST /api/triggers/{'{id}'}/disable", s,
           (403,) if role == "observer" else (200, 404), "contract error ok")

print("\n== admin-level operations (observer/operator/approver denied) ==")
ADMIN_OPS = [
    ("POST", "/api/org/tier", {"tier": "solo"}),
    ("POST", "/api/team/members", {"username": "mx-nope", "role": "observer"}),
    ("POST", "/api/team/invitations", {"role": "observer"}),
    ("POST", "/api/processes", {"name": "mx-proc"}),
    ("POST", "/api/runners", {"name": "mx-runner", "kind": "local"}),
    ("POST", "/api/workflows/{WID}/parameters", {"parameters": []}),
    ("POST", "/api/registry/templates/nonexistent/review", {"decision": "approve"}),
]
for method, path, body in ADMIN_OPS:
    label = f"{method} {path}"
    for role in ROLES:
        s, _ = call(method, path, body, token=TOKENS[role])
        if role == "owner":
            expect(role, label, s, (200, 400, 404, 409, 422), "contract error ok")
        else:
            expect(role, label, s, (403,))

print("\n== workflow delete: owner-only ==")
for role in ROLES:
    s, _ = call("DELETE", f"/api/workflows/{WID}", token=TOKENS[role])
    expect(role, "DELETE /api/workflows/{id}", s, (200,) if role == "owner" else (403,))
# the id is now soft-deleted (and must NOT be reusable); continue on a fresh id
WID_DELETED = WID
WID = f"wf-mx-{secrets.token_hex(4)}"
s, b = call("POST", "/api/workflows", {
    "id": WID, "name": "authz matrix target (fresh id)",
    "graph": {"nodes": [{"id": "n", "type": "notify.desktop", "params": {"title_key": "Name"}}],
              "edges": []}})
assert s == 200, b
s, b = call("POST", "/api/runs", {"workflow_id": WID, "run_date": RUN_DATE})
RID = b.get("run_id")
assert RID, b

print("\n== node-callback effect routes: operator+ (service bridge unaffected) ==")
NODE_OPS = [
    ("POST", "/api/nodes/read-due", {"alias": "sample-tracking-file", "run_id": RID, "node_id": "x"}),
    ("POST", "/api/nodes/notify", {"run_id": RID, "node_id": "x", "title_key": "Name"}),
    ("POST", f"/api/runs/{RID}/complete", {"status": "passed"}),
]
for method, path, body in NODE_OPS:
    label = f"{method} {path}"
    for role in ROLES:
        s, _ = call(method, path, body, token=TOKENS[role])
        if role == "observer":
            expect(role, label, s, (403,))
        else:
            expect(role, label, s, (200, 400, 404, 409, 422), "contract error ok")
# service principal still passes (Node-RED bridge path)
s, _ = call("POST", "/api/nodes/read-due", {"alias": "sample-tracking-file", "run_id": RID, "node_id": "x"})
check("service: node callback passes (bridge compatibility)", s in (200, 400, 404, 409, 422), str(s))

print("\n== reads: every role allowed ==")
READ_PATHS = ["/api/workflows", "/api/runs/list", "/api/candidates", "/api/notifications",
              "/api/audit?limit=5", "/api/team/members", "/api/me/capabilities",
              "/api/privacy/ledger", "/api/connectors", "/api/triggers", "/api/org/profile"]
for path in READ_PATHS:
    for role in ROLES:
        s, _ = call("GET", path, token=TOKENS[role])
        expect(role, f"GET {path.split('?')[0]}", s, (200,))

print("\n== org catalog: public context source for the create wizard ==")
s, b = call("GET", "/api/org/catalog", token="")
check("anon: GET /api/org/catalog -> 200", s == 200, str(s))
check("catalog covers corporate/government/individual",
      s == 200 and all(t in b.get("org_types", []) for t in ("corporate", "government", "individual")))

print("\n== unauthenticated: everything denied ==")
UNAUTH = [("GET", "/api/workflows"), ("POST", "/api/runs", {"workflow_id": WID}),
          ("GET", "/api/team/members"), ("GET", "/api/audit"), ("POST", "/api/triggers/tick", {}),
          ("GET", "/api/org/sso"), ("DELETE", f"/api/workflows/{WID}")]
for item in UNAUTH:
    method, path = item[0], item[1]
    body = item[2] if len(item) > 2 else None
    s, _ = call(method, path, body, token="")
    check(f"anon: {method} {path.split('?')[0]} -> 401", s == 401, str(s))

print("\n== invalid & tampered tokens ==")
s, _ = call("GET", "/api/workflows", token="ask_totally-made-up")
check("garbage user token -> 401", s == 401, str(s))
s, _ = call("GET", "/api/workflows", token=SERVICE + "x")
check("tampered service token -> 401", s == 401, str(s))
s, _ = call("POST", "/api/runs", {"workflow_id": WID}, token=SERVICE + "x")
check("tampered token on mutation -> 401", s == 401, str(s))

print("\n== privilege escalation attempts ==")
# observer tries to elevate self via the role-change endpoint
s, b = call("GET", "/api/team/members")
members = b["members"]
obs_mid = next(m["membership_id"] for m in members if m["username"].startswith("mx-observer"))
s, _ = call("POST", f"/api/team/members/{obs_mid}/role", {"role": "owner"}, token=TOKENS["observer"])
check("observer cannot set own role to owner", s == 403, str(s))
opr_mid = next(m["membership_id"] for m in members if m["username"].startswith("mx-operator"))
s, _ = call("POST", f"/api/team/members/{opr_mid}/role", {"role": "owner"}, token=TOKENS["operator"])
check("operator cannot self-elevate", s == 403, str(s))
s, _ = call("POST", "/api/team/members", {"username": "mx-forged", "role": "owner"}, token=TOKENS["operator"])
check("operator cannot add members", s == 403, str(s))
# hidden-field manipulation: register body ignores extra privileged fields
s, b = call("POST", "/api/auth/register", {"username": f"mx-forged-{secrets.token_hex(3)}",
                                           "password": PASSWORD, "is_admin": True, "role": "owner"})
check("register ignores injected is_admin/role fields", s in (200, 400, 422), str(s))
if s == 200:
    s, b = call("GET", "/api/team/members")
    forged = next((m for m in b["members"] if m["username"].startswith("mx-forged")), None)
    check("forged user did NOT land as owner", forged is not None and forged["role"] != "owner",
          forged["role"] if forged else "not a member")
# service principal keeps admin (documented compat)
s, _ = call("POST", "/api/org/tier", {"tier": "solo"})
check("service token retains admin (documented)", s == 200, str(s))

print("\n== token lifecycle ==")
s, b = call("POST", "/api/auth/tokens", {"username": "mx-owner-" + "", "password": ""})
check("token issue requires credentials", s in (400, 401), str(s))

# cross-user token revocation (IDOR): observer tries to revoke owner's token
s, b = call("GET", "/api/auth/tokens", token=TOKENS["owner"])
own_tok = next((t["id"] for t in b.get("tokens", [])), None)
if own_tok:
    s, _ = call("POST", f"/api/auth/tokens/{own_tok}/revoke", {}, token=TOKENS["observer"])
    check("observer cannot revoke another user's token (IDOR)", s == 404, str(s))

print("\n== revocation takes effect immediately ==")
# issue a fresh token for the approver, revoke THAT token by matching its id in
# the listing (list is oldest-first), then use it
apr_user = next(m["username"] for m in call("GET", "/api/team/members")[1]["members"]
                if m["username"].startswith("mx-approver"))
s, b = call("POST", "/api/auth/tokens", {"username": apr_user, "password": PASSWORD})
fresh = b["token"]
s, b = call("GET", "/api/auth/tokens", token=fresh)
known = {t["id"] for t in call("GET", "/api/auth/tokens", token=fresh)[1].get("tokens", [])}
s, b2 = call("GET", "/api/auth/tokens", token=fresh)
# the fresh token's id = the one present now; revoke by user's own listing —
# identity.list_tokens returns this user's tokens; pick the newest by created_at
newest = max(b2["tokens"], key=lambda t: t["created_at"])
s, _ = call("POST", f"/api/auth/tokens/{newest['id']}/revoke", {}, token=fresh)
check("self-revoke ok", s == 200, str(s))
s, _ = call("GET", "/api/workflows", token=fresh)
check("revoked token immediately dead", s == 401, str(s))

print("\n== deleted-workflow save semantics ==")
s, _ = call("POST", "/api/workflows", {
    "id": WID_DELETED, "name": "resurrect attempt",
    "graph": {"nodes": [], "edges": []}})
check("saving into a soft-deleted id -> 409 (no silent resurrection)", s == 409, str(s))

print("\n== cleanup ==")
WID2 = f"wf-mx-cleanup-{secrets.token_hex(4)}"
s, _ = call("POST", "/api/workflows", {"id": WID2, "name": "cleanup",
                                      "graph": {"nodes": [], "edges": []}})
s, _ = call("DELETE", f"/api/workflows/{WID2}")
check("cleanup: workflow soft-deleted", s == 200, str(s))

fails = [r for r in RESULTS if not r[0]]
print(f"\nTOTAL: {len(RESULTS)} checks — {len(RESULTS) - len(fails)} pass, {len(fails)} fail")
for _, name, note in fails:
    print(f"  FAIL: {name} — {note}")
sys.exit(1 if fails else 0)
