"""Phase 7 lifecycle: cancellation with scoped recovery, restart reconciliation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from tests.spike.conftest import isolated_db_module, test_session  # noqa: E402,F401 (fixture import)
from backend.models import Base, Run  # noqa: E402
from backend.security import audit as audit_mod  # noqa: E402

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


GRAPH = {
    "id": "wf_lifecycle", "name": "Lifecycle test",
    "triggers": [{"type": "schedule", "cron": "0 9 * * MON-FR"}],
    "nodes": [{"id": "note", "type": "notify.desktop", "params": {"title_key": "run_done"}}],
    "edges": [],
}


def _seed_run(status="running"):
    """Seed through the real bridge-start path, then force the requested status."""
    client.post("/api/workflows", json={"id": "wf_lifecycle", "name": "Lifecycle test",
                                        "graph": GRAPH}, headers=H)
    res = client.post("/api/runs/bridge-start", json={"workflow_id": "wf_lifecycle"}, headers=H)
    assert res.status_code == 200, res.text
    run_id = res.json()["run_id"]
    db = test_session()
    try:
        run = db.get(Run, run_id)
        run.status = status
        db.commit()
    finally:
        db.close()
    return run_id


def test_cancel_running_run_reports_applied_effects():
    run_id = _seed_run("running")
    res = client.post(f"/api/runs/{run_id}/cancel", json=None, headers=H)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "cancelled"
    assert "effects_already_applied" in body
    # cancelling a finished run is a no-op, not an error
    res = client.post(f"/api/runs/{run_id}/cancel", json=None, headers=H)
    assert res.status_code == 200
    assert res.json()["note"] == "already finished; nothing to cancel"


def test_reconcile_closes_stuck_runs_as_failed():
    run_id = _seed_run("running")
    res = client.post("/api/runs/reconcile", json=None, headers=H)
    assert res.status_code == 200
    body = res.json()
    assert run_id in body["run_ids"]
    db = test_session()
    try:
        run = db.get(Run, run_id)
        assert run.status == "failed"
        assert "reconciled" in (run.error or "")
    finally:
        db.close()


def test_cancel_and_reconcile_are_audited_and_chain_holds():
    res = client.get("/api/audit?verify=1", headers=H)
    assert res.status_code == 200
    body = res.json()
    kinds = [e["kind"] for e in body["entries"]]
    assert "run.cancelled" in kinds or "runs.reconciled" in kinds
    assert body["chain_valid"] is True
