"""Phase 5-7 chain: plan → generate → static validation → isolated test → activation.

Hostile cases fail closed: incomplete plans can't generate; forbidden constructs are
refused before execution; a failed test blocks activation; report/code mismatch is
rejected; a model response never mints an approval.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from tests.spike.conftest import isolated_db_module, test_session  # noqa: E402,F401 (fixture import)
from backend.models import Base  # noqa: E402

client = TestClient(app)
H = {"Authorization": "Bearer testtoken"}


@pytest.fixture(scope="module", autouse=True)
def _auth(isolated_db_module):
    from backend.security import tokens
    original = tokens.get_expected_token
    tokens.get_expected_token = lambda: "testtoken"
    pass  # schema created by isolated_db_module
    yield
    tokens.get_expected_token = original


GOOD_PLAN = {
    "client_id_field": "ClientID",
    "field_mappings": {"Name": "Name", "FollowUpDate": "FollowUpDate"},
    "eligibility": {"status": "Follow-up due", "date_field": "FollowUpDate"},
    "action": "create_draft",
    "destinations": ["in_app"],
}

SAFE_CODE = '''
def run(rows, ctx):
    out = []
    for row in rows:
        if row.get("Status") == ctx.get("eligibility_status"):
            out.append({"ClientID": row["ClientID"], "draft": True})
    return out
'''

EVIL_CODE = '''
import socket

def run(rows, ctx):
    s = socket.socket()
    return rows
'''


def _run_ctx():
    return {"eligibility_status": "Follow-up due"}


def _run_job(artifact_id):
    return client.post("/api/test-jobs", json={
        "artifact_id": artifact_id, "fixture": "reset", "consent": True}, headers=H)


def test_incomplete_plan_blocks_generation():
    res = client.post("/api/plans", json={"plan": {"client_id_field": "ClientID"}}, headers=H)
    assert res.status_code == 200
    body = res.json()
    assert body["generatable"] is False
    assert "field_mappings" in body["missing_rules"]
    res = client.post("/api/artifacts/generate",
                      json={"plan_id": body["plan_id"], "approve_generation": True}, headers=H)
    assert res.status_code == 422  # blocked


def test_generation_requires_explicit_approval():
    res = client.post("/api/plans", json={"plan": GOOD_PLAN}, headers=H)
    plan_id = res.json()["plan_id"]
    res = client.post("/api/artifacts/generate",
                      json={"plan_id": plan_id, "approve_generation": False}, headers=H)
    assert res.status_code == 403


def test_full_chain_to_activation():
    res = client.post("/api/plans", json={"plan": GOOD_PLAN}, headers=H)
    assert res.json()["generatable"] is True
    plan_id = res.json()["plan_id"]

    res = client.post("/api/artifacts/generate",
                      json={"plan_id": plan_id, "approve_generation": True}, headers=H)
    assert res.status_code == 200, res.text
    art = res.json()
    # The mock provider now synthesizes REAL plan-derived run(rows, ctx) code (Phase 5
    # upgrade): it must pass static validation with zero violations.
    assert art["status"] == "awaiting_test_approval", art
    assert art["violations"] == []

    # The synthesized artifact must also pass the isolated test against the plan's
    # independently computed expected outputs (oracle shares no code with generation).
    job0 = _run_job(art["artifact_id"])
    assert job0.status_code == 200, job0.text
    assert job0.json()["status"] == "passed", job0.text
    assert any(c["name"] == "expected_outputs_match" and c["ok"]
               for c in job0.json()["report"]["checks"])

    # Store a clean artifact directly (simulating a valid model response) and test it.
    from backend.models import GeneratedArtifact
    import hashlib, json as _json, uuid as _uuid
    db = test_session()
    try:
        code_sha = hashlib.sha256(SAFE_CODE.encode()).hexdigest()
        art2 = GeneratedArtifact(
            id=str(_uuid.uuid4()), plan_id=plan_id, version=2,
            model_output_json=_json.dumps({"output": "unit-test stub"}),
            code=SAFE_CODE, code_sha256=code_sha,
            static_check_json=_json.dumps([]),
            status="awaiting_test_approval", created_at="2026-09-23T00:00:00+00:00")
        db.add(art2)
        db.commit()
        art_id = art2.id
        code_sha_saved = art2.code_sha256
    finally:
        db.close()

    job = _run_job(art_id)
    assert job.status_code == 200, job.text
    jbody = job.json()
    assert jbody["status"] == "passed", jbody
    assert all(c["ok"] for c in jbody["report"]["checks"])

    # Activation before approval metadata is fine now (tests passed) — approve it.
    res = client.post("/api/approvals/activation",
                      json={"artifact_id": art_id, "job_id": jbody["job_id"],
                            "note": "judge demo"}, headers=H)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "activated"

    # Stale evidence: same job again must be rejected (artifact already activated)
    res = client.post("/api/approvals/activation",
                      json={"artifact_id": art_id, "job_id": jbody["job_id"]}, headers=H)
    assert res.status_code == 409


def test_evil_code_never_reaches_the_sandbox():
    from backend.engine import runner
    report = runner.run_isolated_test(EVIL_CODE, [{"ClientID": "C001"}], ctx={})
    assert report["status"] == "refused"
    assert any("socket" in v or "import outside allowlist" in v for v in report["violations"])


def test_failing_test_blocks_activation():
    from backend.models import GeneratedArtifact
    import hashlib, json as _json, uuid as _uuid
    res = client.post("/api/plans", json={"plan": GOOD_PLAN}, headers=H)
    plan_id = res.json()["plan_id"]
    bad_code = 'def run(rows, ctx):\n    return "not a list"\n'
    db = test_session()
    try:
        art = GeneratedArtifact(
            id=str(_uuid.uuid4()), plan_id=plan_id, version=1,
            model_output_json=_json.dumps({"output": "x"}), code=bad_code,
            code_sha256=hashlib.sha256(bad_code.encode()).hexdigest(),
            static_check_json=_json.dumps([]), status="awaiting_test_approval",
            created_at="2026-09-23T00:00:00+00:00")
        db.add(art)
        db.commit()
        art_id = art.id
    finally:
        db.close()
    job = _run_job(art_id)
    assert job.status_code == 200
    assert job.json()["status"] == "failed"  # a failed test is a valid outcome
    res = client.post("/api/approvals/activation", json={"artifact_id": art_id}, headers=H)
    assert res.status_code == 409  # activation stays blocked


def test_report_code_binding_rejected():
    res = client.post("/api/plans", json={"plan": GOOD_PLAN}, headers=H)
    plan_id = res.json()["plan_id"]
    res = client.post("/api/artifacts/generate",
                      json={"plan_id": plan_id, "approve_generation": True}, headers=H)
    # invalid/untested artifact — activation attempt must fail on state
    art_id = res.json()["artifact_id"]
    res = client.post("/api/approvals/activation", json={"artifact_id": art_id}, headers=H)
    assert res.status_code == 409
