"""Phase 5→10 keystone chain: confirmed plan → activated artifact → bound workflow
→ real Run-now through the graph executor → exactly-once on the second run.

Also proves list APIs the frontend uses (workflows/runs/nodes) and honest failure
on an unknown workflow.
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
from backend.security import safeio  # noqa: E402

client = TestClient(app)
H = {"Authorization": "Bearer testtoken"}

PLAN = {
    "client_id_field": "ClientID",
    "field_mappings": {"Name": "Name", "FollowUpDate": "FollowUpDate"},
    "eligibility": {"status": "Follow-up due", "status_field": "Status",
                    "date_field": "FollowUpDate", "date_value": "2026-09-20"},
    "action": "create_draft",
    "destinations": ["in_app"],
}


@pytest.fixture(scope="module", autouse=True)
def _auth(isolated_db_module):
    from backend.security import tokens
    original = tokens.get_expected_token
    tokens.get_expected_token = lambda: "testtoken"
    pass  # schema created by isolated_db_module
    yield
    tokens.get_expected_token = original


def _reset_tracking_file():
    safeio.write_resource("sample-tracking-file", "clients.csv",
                          (ROOT / "tests" / "fixtures" / "clients-before.csv").read_bytes(),
                          backup=False)
    db = test_session()
    try:
        from backend.models import IdempotencyClaim
        for claim in db.query(IdempotencyClaim).all():
            if "followup-draft" in claim.effect_key:
                db.delete(claim)
        db.commit()
    finally:
        db.close()


def test_full_keystone_chain_plan_to_run_now():
    _reset_tracking_file()

    # 1. plan (confirmed rules; invalid plans would be blocked here)
    res = client.post("/api/plans", json={"plan": PLAN}, headers=H)
    assert res.status_code == 200, res.text
    plan_id = res.json()["plan_id"]
    assert res.json()["generatable"] is True

    # 2. generate (mock synthesizes real plan-derived code; static checks clean)
    res = client.post("/api/artifacts/generate",
                      json={"plan_id": plan_id, "approve_generation": True}, headers=H)
    assert res.status_code == 200, res.text
    artifact_id = res.json()["artifact_id"]
    assert res.json()["violations"] == []

    # 3. isolated sandbox test against plan-derived expected outputs
    res = client.post("/api/test-jobs",
                      json={"artifact_id": artifact_id, "fixture": "reset", "consent": True},
                      headers=H)
    assert res.status_code == 200, res.text
    job = res.json()
    assert job["status"] == "passed", res.text
    assert any(c["name"] == "expected_outputs_match" and c["ok"] for c in job["report"]["checks"])

    # 4. separate human activation approval
    res = client.post("/api/approvals/activation",
                      json={"artifact_id": artifact_id, "job_id": job["job_id"],
                            "note": "keystone chain test"}, headers=H)
    assert res.status_code == 200, res.text

    # 5. bind → versioned workflow whose hash covers graph+plan+code
    res = client.post(f"/api/plan/{plan_id}/create-workflow", json=None, headers=H)
    assert res.status_code == 200, res.text
    wf = res.json()
    workflow_id = wf["workflow_id"]
    assert workflow_id.startswith("wf-")
    assert wf["graph"]["nodes"], "compiled graph must be present"

    # 6. list APIs (frontend sources) show the bound workflow
    res = client.get("/api/workflows", headers=H)
    assert res.status_code == 200
    wf_ids = [w["id"] for w in res.json()["workflows"]]
    assert workflow_id in wf_ids

    # 7. RUN-NOW through the graph executor
    res = client.post("/api/runs", json={"workflow_id": workflow_id,
                                         "run_date": "2026-09-20",
                                         "filename": "clients.csv"}, headers=H)
    assert res.status_code == 200, res.text
    run = res.json()
    assert run["status"] == "passed"
    assert sorted(run["drafted"]) == ["sample:C001", "sample:C003"]
    assert run["drafted"] or run["updated"], "effects must be real"

    # node records are honest and complete
    res = client.get(f"/api/runs/{run['run_id']}/nodes", headers=H)
    nodes = res.json()["nodes"]
    kinds = [n["node"].split(":")[1] for n in nodes]
    assert "file.read_table" in kinds and "data.filter" in kinds and "draft.create" in kinds

    # 8. exactly-once: second run claims nothing new
    res = client.post("/api/runs", json={"workflow_id": workflow_id,
                                         "run_date": "2026-09-20",
                                         "filename": "clients.csv"}, headers=H)
    assert res.status_code == 200
    run2 = res.json()
    assert run2["drafted"] == [] and run2["skipped"], "second run must be idempotent-claimed"

    # 9. runs list shows both, with workflow linkage
    res = client.get("/api/runs/list", headers=H)
    runs_for_wf = [r for r in res.json()["runs"] if r["workflow_id"] == workflow_id]
    assert len(runs_for_wf) >= 2
    assert all(r["status"] == "passed" for r in runs_for_wf)


def test_run_now_unknown_workflow_fails_closed():
    res = client.post("/api/runs", json={"workflow_id": "wf_does_not_exist",
                                         "run_date": "2026-09-20",
                                         "filename": "clients.csv"}, headers=H)
    assert res.status_code == 404


def test_binding_requires_activated_artifact():
    res = client.post("/api/plans", json={"plan": PLAN}, headers=H)
    plan_id = res.json()["plan_id"]
    res = client.post(f"/api/plan/{plan_id}/create-workflow", json=None, headers=H)
    assert res.status_code == 409  # no activated artifact for this plan
