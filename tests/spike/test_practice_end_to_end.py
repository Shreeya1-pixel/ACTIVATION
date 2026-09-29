"""Practice workspace, end to end with no sample data: the user's own edits are
captured from the saved file, identified, turned into a plan, coded, repaired,
tested on a copy of the sheet, dry-run, run for real and rolled back."""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend import app as app_mod  # noqa: E402
from backend import practice, roadmap_routes  # noqa: E402
from backend.capture import config as capture_config  # noqa: E402
from tests.spike.conftest import isolated_db_module, test_session  # noqa: E402,F401

client = TestClient(app_mod.app)
H = {"Authorization": "Bearer testtoken"}
CTX = {"org_type": "corporate", "size": "medium", "department": "finance",
       "process_type": "accounts_payable"}


@pytest.fixture(scope="module", autouse=True)
def _env(isolated_db_module, tmp_path_factory):
    from backend.security import tokens
    tmp = tmp_path_factory.mktemp("practice")
    saved = (tokens.get_expected_token, roadmap_routes.get_expected_token, capture_config.CONFIG_FILE,
             capture_config.DEFAULT_FOLDER, practice.FOLDER, app_mod._WATCHER, app_mod._WATCHER_FOLDER)
    tokens.get_expected_token = lambda: "testtoken"
    roadmap_routes.get_expected_token = lambda: "testtoken"
    capture_config.CONFIG_FILE = tmp / "capture_config.json"
    capture_config.DEFAULT_FOLDER = tmp / "watched"
    practice.FOLDER = (tmp / "practice-workspace")
    app_mod._WATCHER = None
    yield tmp
    (tokens.get_expected_token, roadmap_routes.get_expected_token, capture_config.CONFIG_FILE,
     capture_config.DEFAULT_FOLDER, practice.FOLDER, app_mod._WATCHER, app_mod._WATCHER_FOLDER) = saved


def _sheet():
    return client.get("/api/practice/sheet", headers=H).json()


def _edit(row_id, **changes):
    rows = _sheet()["rows"]
    for r in rows:
        if r["Invoice No"] == row_id:
            r.update(changes)
    res = client.post("/api/practice/save", json={"rows": rows}, headers=H)
    assert res.status_code == 200, res.text
    return res.json()


def _file_rows():
    text = (practice.FOLDER / practice.FILENAME).read_text(encoding="utf-8")
    return {r["Invoice No"]: r for r in csv.DictReader(io.StringIO(text))}


def test_full_loop_from_the_users_own_edits():
    start = client.post("/api/practice/start", headers=H)
    assert start.status_code == 200, start.text
    assert _sheet()["active"] is True and _sheet()["candidates"] == []

    # 1. the user's routine, done by hand on three invoices
    for inv in ("INV-2001", "INV-2002", "INV-2003"):
        first = _edit(inv, **{"Status": "Approved", "Checked By": "SG"})
        assert [(c["action"], c["row"], sorted(c["columns"])) for c in first["changes"]] == \
            [("row.updated", inv, ["Checked By", "Status"])]
        _edit(inv, **{"Payment Requested": "Yes"})
        done = client.post("/api/practice/done", json={"row_id": inv}, headers=H).json()
    assert done["progress"]["repeats"] == 3

    # 2. identified from that evidence alone
    cands = [c for c in done["candidates"] if c["status"] == "suggested"]
    assert len(cands) == 1 and cands[0]["occurrences"] == 3

    # 3. plan inferred from the sheet as it is now
    sug = client.post("/api/practice/suggest-plan", json={"candidate_id": cands[0]["id"]}, headers=H).json()
    plan = sug["plan"]
    assert plan["eligibility"] == {"status_field": "Status", "status": "Received"}
    assert plan["set_fields"] == {"Status": "Approved", "Checked By": "SG", "Payment Requested": "Yes"}
    assert set(sug["would_match_now"]) == {f"INV-200{i}" for i in range(4, 9)}

    plan_id = client.post("/api/plans", json={"plan": plan, "candidate_id": cands[0]["id"]},
                          headers=H).json()["plan_id"]

    # 4. code written, broken first draft caught on a copy of the real sheet, repaired
    gen = client.post("/api/artifacts/generate",
                      json={"plan_id": plan_id, "approve_generation": True, "start_broken": True},
                      headers=H).json()
    assert gen["attempts"][0]["seeded"] and gen["attempts"][0]["problems"]
    assert gen["repaired"] is True and "row.get('Status')" in gen["attempts"][-1]["code"]

    job = client.post("/api/test-jobs", json={"artifact_id": gen["artifact_id"], "fixture": "reset",
                                              "consent": True}, headers=H).json()
    assert job["status"] == "passed", job
    assert client.post("/api/approvals/activation",
                       json={"artifact_id": gen["artifact_id"], "job_id": job["job_id"]},
                       headers=H).json()["status"] == "activated"
    wf = client.post(f"/api/plan/{plan_id}/create-workflow", json=CTX, headers=H)
    assert wf.status_code == 200, wf.text
    wf_id = wf.json()["workflow_id"]

    # 5. dry run changes nothing
    before = (practice.FOLDER / practice.FILENAME).read_bytes()
    dry = client.post("/api/runs", json={"workflow_id": wf_id, "dry_run": True}, headers=H)
    assert dry.status_code == 200, dry.text
    assert sorted(dry.json()["would_update"]) == [f"INV-200{i}" for i in range(4, 9)]
    assert (practice.FOLDER / practice.FILENAME).read_bytes() == before

    # 6. live run does the routine on the remaining rows, exactly as the user did
    live = client.post("/api/runs", json={"workflow_id": wf_id}, headers=H)
    assert live.status_code == 200, live.text
    after = _file_rows()
    for i in range(1, 9):
        r = after[f"INV-200{i}"]
        assert (r["Status"], r["Checked By"], r["Payment Requested"]) == ("Approved", "SG", "Yes")

    # the app's own write is not learned as user work
    assert client.post("/api/practice/rebaseline", headers=H).status_code == 200
    assert client.post("/api/capture/poll", headers=H).json()["events"] == 0

    # 7. undo restores the rows it changed
    rb = client.post(f"/api/runs/{live.json()['run_id']}/rollback", headers=H)
    assert rb.status_code == 200, rb.text
    restored = _file_rows()
    assert restored["INV-2005"]["Status"] == "Received" and restored["INV-2001"]["Status"] == "Approved"


def test_save_rejects_formulas_and_duplicate_ids():
    client.post("/api/practice/start", headers=H)
    rows = _sheet()["rows"]
    rows[0]["Vendor"] = "=HYPERLINK(1)"
    assert client.post("/api/practice/save", json={"rows": rows}, headers=H).status_code == 400
    rows = _sheet()["rows"]
    rows[1]["Invoice No"] = rows[0]["Invoice No"]
    assert client.post("/api/practice/save", json={"rows": rows}, headers=H).status_code == 400


def test_values_that_could_escape_a_rule_are_refused():
    from backend.engine.generation import PlanError
    from backend.engine.graph_build import safe_literal
    for bad in ("x' or 'a'=='a", "a;Status='hacked'", "{{7*7}}"):
        with pytest.raises(PlanError):
            safe_literal(bad)
