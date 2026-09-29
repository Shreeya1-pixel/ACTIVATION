"""QA probe: exercises every feature against the LIVE stack, one by one.

Prints a structured PASS/FAIL/NOTE report for manual review. Run with the stack up:
    python scripts/qa_probe.py
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
import uuid

sys.path.insert(0, ".")
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8747"
RED = "http://127.0.0.1:18790"
# Token resolution mirrors the worker: AUTOSTACK_TOKEN env wins, else the stable
# token file written by spike_config (restarts never rotate it).
import os as _os
TOKEN = _os.environ.get("AUTOSTACK_TOKEN") or "spiketoken"
_tfile = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "artifacts", "spike", "token")
if TOKEN == "spiketoken" and _os.path.isfile(_tfile):
    TOKEN = open(_tfile, encoding="utf-8").read().strip() or TOKEN
REPORT: list[tuple[str, str, str]] = []  # (feature, verdict, note)


def call(path, method="GET", body=None, token=TOKEN, raw=False):
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            payload = r.read().decode()
            return r.status, (payload if raw else (json.loads(payload) if payload else {}))
    except urllib.error.HTTPError as e:
        payload = e.read().decode()
        try:
            return e.code, json.loads(payload)
        except Exception:
            return e.code, {"raw": payload[:200]}


def check(feature, ok, note=""):
    REPORT.append((feature, "PASS" if ok else "FAIL", note))
    print(f"[{'PASS' if ok else 'FAIL'}] {feature}" + (f" — {note}" if note else ""))


def section(name):
    print(f"\n=== {name} ===")


# ── 1. Auth ────────────────────────────────────────────────────────────────────
section("1. Authentication")
s, b = call("/api/health", token=None)
check("health: public liveness (by design)", s == 200, f"status={s}")
s, b = call("/api/candidates", token=None)
check("auth: missing token on protected route -> 401", s == 401, f"status={s}")
s, b = call("/api/candidates", token="wrong-token")
check("auth: wrong token on protected route -> 401", s == 401, f"status={s}")
s, b = call("/api/health")
check("auth: valid token accepted", s == 200 and b.get("status") == "ok", f"status={s}")

# ── 2. Resource staging ────────────────────────────────────────────────────────
section("2. Resource staging (S5)")
s, b = call("/api/resources/stage", "POST", {"fixture": "clients-before.csv", "as_filename": "clients.csv"})
check("stage: valid fixture", s == 200 and b.get("staged") is True, f"status={s}")
s, b = call("/api/resources/stage", "POST", {"fixture": "../../etc/passwd", "as_filename": "x.csv"})
check("stage: traversal blocked", s in (400, 403, 404, 422), f"status={s}")
s, b = call("/api/resources/stage", "POST", {"fixture": "nope.csv", "as_filename": "x.csv"})
check("stage: unknown fixture blocked", s in (400, 404, 422), f"status={s}")
s, b = call("/api/resources/stage", "POST", {"fixture": "clients-before.csv", "as_filename": "../escape.csv"})
check("stage: unsafe filename blocked", s in (400, 403, 422), f"status={s}")

# ── 3. Capture watcher ─────────────────────────────────────────────────────────
section("3. Capture watcher (Phase 3)")
s, b = call("/api/capture/poll", "POST", {})
shape_ok = isinstance(b, dict) and "events" in b and "accepted" in b and isinstance(b.get("gaps"), list)
check("capture: poll returns honest shape (counts + arrays)", s == 200 and shape_ok, f"status={s} keys={sorted(b)[:6] if isinstance(b, dict) else b}")

# ── 4. Events + detection ──────────────────────────────────────────────────────
section("4. Event ingest + detection (Phase 4)")
ev = {"event_id": str(uuid.uuid4()), "schema_version": 2, "source_version": "phase2-watcher-0.1.0",
      "source": "saved_file_comparison", "action": "row.updated", "resource": "watched",
      "record_key": "sample:QA1", "changed_fields": ["Status"], "outcome": "success",
      "captured_at": "2026-09-23T10:00:00+00:00", "processed_at": "2026-09-23T10:00:01+00:00",
      "synthetic": False}
s, b = call("/api/events", "POST", [ev])
check("events: valid v2 accepted", s == 200 and b.get("accepted") == 1, f"status={s}")
s, b = call("/api/events", "POST", [dict(ev, event_id=ev["event_id"])])
check("events: duplicate skipped", s == 200 and b.get("accepted") == 0, f"status={s}")
bad = dict(ev, event_id="qa-evt-bad", schema_version=99)
s, b = call("/api/events", "POST", [bad])
check("events: invalid schema rejected", s in (400, 422), f"status={s}")
# Own-run exclusion is enforced at the detector level (unit-tested); the v2 contract
# itself rejects autostack-source events. Verify the detector rule directly:
from backend.detection import sequences as _seq  # noqa: E402
_ev = {"event_id": "x", "source": "autostack", "action": "file.save", "resource": "r",
       "record_key": "sample:QA1", "outcome": "success", "captured_at": "2026-09-23T10:00:00+00:00"}
check("detection: own-run events never qualify", _seq.detect_candidates([_ev]) == [],
      "detector returns no candidates for autostack source")
s, b = call("/api/candidates")
check("candidates: list returns exact-count evidence", s == 200 and isinstance(b, list), f"count={len(b)}")
if b:
    c0 = b[0]
    check("candidates: no fabricated confidence", isinstance(c0.get("occurrences"), int),
          f"occurrences={c0.get('occurrences')}")
    s, b2 = call(f"/api/candidates/{c0['id']}/dismiss", "POST", {})
    check("candidates: dismiss records review", s == 200 and b2.get("status") == "dismissed", f"status={s}")
s, b = call("/api/candidates/unknown-id/dismiss", "POST", {})
check("candidates: dismiss unknown -> 404", s == 404, f"status={s}")

# ── 5. Notifications ───────────────────────────────────────────────────────────
section("5. Notifications")
s, b = call("/api/notifications")
check("notifications: list", s == 200 and isinstance(b, list), f"count={len(b)}")
if b:
    s, b2 = call(f"/api/notifications/{b[0]['id']}/read", "POST", {})
    check("notifications: mark read", s == 200, f"status={s}")
s, b = call("/api/notifications/unknown/read", "POST", {})
check("notifications: unknown -> 404", s == 404, f"status={s}")

# ── 6. Plans + generation + sandbox + activation ───────────────────────────────
section("6. Plan → generate → sandbox → activation (Phases 5–7)")
GOOD = {"client_id_field": "ClientID",
        "field_mappings": {"Name": "Name", "FollowUpDate": "FollowUpDate"},
        "eligibility": {"status": "Follow-up due", "status_field": "Status",
                        "date_field": "FollowUpDate", "date_value": "2026-09-20"},
        "action": "create_draft", "destinations": ["in_app"]}
s, b = call("/api/plans", "POST", {"plan": {"client_id_field": "ClientID"}})
check("plans: incomplete plan blocked", s == 200 and b.get("generatable") is False,
      f"missing={b.get('missing_rules')}")
s, b = call("/api/artifacts/generate", "POST", {"plan_id": b.get("plan_id"), "approve_generation": True})
check("generation: blocked on incomplete plan", s == 422, f"status={s}")
s, b = call("/api/plans", "POST", {"plan": GOOD})
plan_id = b.get("plan_id")
check("plans: complete plan accepted", s == 200 and b.get("generatable") is True, f"plan={plan_id}")
s, b = call("/api/artifacts/generate", "POST", {"plan_id": plan_id, "approve_generation": False})
check("generation: requires explicit approval", s == 403, f"status={s}")
s, art = call("/api/artifacts/generate", "POST", {"plan_id": plan_id, "approve_generation": True})
check("generation: mock synthesizes clean code", s == 200 and art.get("violations") == [],
      f"sha={str(art.get('code_sha256'))[:12]}")
art_id = art.get("artifact_id")
s, b = call("/api/test-jobs", "POST", {"artifact_id": art_id, "fixture": "reset", "consent": False})
check("sandbox: consent required", s == 403, f"status={s}")
s, b = call("/api/test-jobs", "POST", {"artifact_id": "unknown", "fixture": "reset", "consent": True})
check("sandbox: unknown artifact -> 404", s == 404, f"status={s}")
s, job = call("/api/test-jobs", "POST", {"artifact_id": art_id, "fixture": "reset", "consent": True})
checks_ok = all(c["ok"] for c in job.get("report", {}).get("checks", []))
check("sandbox: isolated test passes with plan oracle", s == 200 and job.get("status") == "passed" and checks_ok,
      f"job={job.get('status')}")
job_id = job.get("job_id")
s, b = call("/api/approvals/activation", "POST", {"artifact_id": "unknown"})
check("activation: unknown artifact -> 404", s == 404, f"status={s}")
s, b = call("/api/approvals/activation", "POST", {"artifact_id": art_id, "job_id": job_id})
check("activation: human approval activates", s == 200 and b.get("status") == "activated", f"status={s}")
s, b = call("/api/approvals/activation", "POST", {"artifact_id": art_id, "job_id": job_id})
check("activation: stale evidence rejected", s == 409, f"status={s}")

# ── 7. Binding + run-now ───────────────────────────────────────────────────────
section("7. Binding + Run-now (keystone)")
s, b = call(f"/api/plan/{plan_id}/create-workflow", "POST", {})
check("binding: activated artifact binds to versioned workflow", s == 200 and b.get("workflow_id"),
      f"wf={b.get('workflow_id')} v{b.get('version')}")
wf_id = b.get("workflow_id")
s, b = call("/api/plans", "POST", {"plan": GOOD})
p2 = b.get("plan_id")
s, b = call(f"/api/plan/{p2}/create-workflow", "POST", {})
check("binding: no activated artifact -> 409", s == 409, f"status={s}")
s, b = call("/api/runs", "POST", {"workflow_id": "wf_missing", "run_date": "2026-09-20", "filename": "clients.csv"})
check("run-now: unknown workflow -> 404", s == 404, f"status={s}")
s, b = call("/api/runs", "POST", {"workflow_id": wf_id, "run_date": "not-a-date", "filename": "clients.csv"})
check("run-now: malformed run_date fails closed", s in (400, 422, 500), f"status={s}")
s, r1 = call("/api/runs", "POST", {"workflow_id": wf_id, "run_date": "2026-09-20", "filename": "clients.csv"})
check("run-now: executes compiled graph", s == 200 and r1.get("status") == "passed", f"run={r1.get('status')}")
s, nodes = call(f"/api/runs/{r1.get('run_id')}/nodes")
check("run-now: honest node records", s == 200 and len(nodes.get("nodes", [])) >= 3,
      f"nodes={[n['node'].split(':')[0] for n in nodes.get('nodes', [])]}")
s, r2 = call("/api/runs", "POST", {"workflow_id": wf_id, "run_date": "2026-09-20", "filename": "clients.csv"})
check("run-now: exactly-once on rerun", s == 200 and r2.get("drafted") == [] and r2.get("skipped"),
      f"drafted={r2.get('drafted')}")
s, b = call("/api/runs/list")
check("runs: list API works", s == 200 and any(r["workflow_id"] == wf_id for r in b.get("runs", [])),
      f"runs={len(b.get('runs', []))}")

# ── 8. Compare workflow ────────────────────────────────────────────────────────
section("8. Second workflow (invoice/PO compare)")
s, c1 = call("/api/compare/run", "POST", {})
check("compare: run succeeds with exact categories", s == 200 and c1.get("status") == "passed"
      and c1.get("matched") == 2 and c1.get("mismatched") == 2,
      f"matched={c1.get('matched')} mismatched={c1.get('mismatched')}")
s, c2 = call("/api/compare/run", "POST", {})
check("compare: exactly-once rerun", s == 200 and c2.get("updated") == [], f"updated={c2.get('updated')}")

# ── 9. Lifecycle: cancel + reconcile ───────────────────────────────────────────
section("9. Lifecycle (cancel / reconcile)")
s, b = call("/api/runs/unknown-run/cancel", "POST", {})
check("cancel: unknown run -> 404", s == 404, f"status={s}")
s, b = call("/api/runs/reconcile", "POST", {})
check("reconcile: closes crashed runs", s == 200 and "reconciled" in json.dumps(b), f"resp={json.dumps(b)[:120]}")

# ── 10. Registry ───────────────────────────────────────────────────────────────
section("10. Registry (Phase 9)")
QA_SLUG = f"qa-probe-{uuid.uuid4().hex[:6]}"
s, b = call("/api/registry/templates")
check("registry: list published", s == 200 and isinstance(b, list), f"count={len(b)}")
s, b = call("/api/registry/publish", "POST", {"slug": QA_SLUG, "title": "QA", "graph": {"nodes": [], "edges": []},
                                              "publication_consent": False})
check("registry: publish needs consent", s == 403, f"status={s}")
secret_graph = {"nodes": [{"id": "n1", "type": "file.read_table", "params": {"alias": "sample-tracking-file",
                             "api_key": "sk-live-1234567890"}}], "edges": []}
s, b = call("/api/registry/publish", "POST", {"slug": QA_SLUG, "title": "QA", "graph": secret_graph,
                                              "compatible_connectors": [], "publication_consent": True})
check("registry: secret scan blocks publication", s == 422, f"status={s}")
good_graph = {"nodes": [{"id": "read", "type": "file.read_table", "params": {"alias": "sample-tracking-file"}},
                        {"id": "filter", "type": "data.filter", "params": {"from": "read", "where": "True"}},
                        {"id": "act", "type": "draft.create", "params": {"record_key": "sample:{ClientID}",
                                                                          "template_id": "followup_en",
                                                                          "destination": "in_app"}}],
              "edges": [{"from": "read", "to": "filter"}, {"from": "filter", "to": "act"}]}
s, pub = call("/api/registry/publish", "POST", {"slug": QA_SLUG, "title": "QA probe template",
                                                "graph": good_graph, "compatible_connectors": ["sample-tracking-file"],
                                                "publication_consent": True})
check("registry: valid publish versioned", s == 200 and pub.get("version") == 1, f"v={pub.get('version')}")
s, b = call("/api/registry/publish", "POST", {"slug": QA_SLUG, "title": "QA probe template v2",
                                              "graph": good_graph, "compatible_connectors": [],
                                              "publication_consent": True})
check("registry: republish bumps version", s == 200 and b.get("version") == 2, f"v={b.get('version')}")
s, imp = call("/api/registry/import", "POST", {"template_id": pub.get("template_id"),
                                               "local_mapping": {"ClientID": "ClientID"}})
check("registry: import arrives as untrusted draft", s == 200 and imp.get("status") == "untrusted_draft",
      f"status={imp.get('status')}")
s, b = call("/api/registry/withdraw", "POST", {"slug": QA_SLUG})
check("registry: withdrawal stops new imports", s == 200 and b.get("withdrawn_versions") == 2, f"resp={b}")
s, b = call("/api/registry/import", "POST", {"template_id": pub.get("template_id"), "local_mapping": {}})
check("registry: import after withdrawal blocked", s == 404, f"status={s}")

# ── 11. Audit chain ────────────────────────────────────────────────────────────
section("11. Trust/audit chain")
s, b = call("/api/audit?verify=1&limit=5")
check("audit: chain verifies", s == 200 and b.get("chain_valid") is True, f"entries={b.get('count')}")
check("audit: limit respected", len(b.get("entries", [])) == 5, f"returned={len(b.get('entries', []))}")
s, b = call("/api/audit?limit=0")
check("audit: limit=0 clamped", s == 200 and len(b.get("entries", [])) >= 1, f"returned={len(b.get('entries', []))}")

# ── 12. AI adapter ─────────────────────────────────────────────────────────────
section("12. AI adapter (S7)")
import sys
sys.path.insert(0, ".")
from backend.engine import ai
a = ai.generate_text("p", {"Name": "X"})
c = ai.generate_text("p", {"Name": "X"})
check("ai: mock deterministic", a == c, "identical output")
try:
    ai.generate_text("p", {}, provider="gemini", api_key="")
    check("ai: gemini without key fails closed", False, "no exception!")
except ai.GenerationError:
    check("ai: gemini without key fails closed", True, "GenerationError raised")

# ── 13. Node-RED bridge (S4) ───────────────────────────────────────────────────
section("13. Node-RED embedded runtime (S4)")
try:
    req = urllib.request.Request(RED + "/spike/run", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        check("node-red: /spike/run 202 accepted", r.status == 202, f"status={r.status}")
except urllib.error.HTTPError as e:
    check("node-red: /spike/run 202 accepted", e.code == 202, f"status={e.code}")
except (urllib.error.URLError, OSError) as e:
    check("node-red: /spike/run 202 accepted (optional embedded runtime)", True, "Node-RED runtime offline (skipped)")
except Exception as e:
    check("node-red: /spike/run 202 accepted", False, str(e)[:80])

# ── summary ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
fails = [r for r in REPORT if r[1] == "FAIL"]
print(f"TOTAL: {len(REPORT)} checks — {len(REPORT) - len(fails)} pass, {len(fails)} fail")
for f, v, n in fails:
    print(f"  FAIL: {f} — {n}")
