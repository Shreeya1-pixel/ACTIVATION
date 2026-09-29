"""Generate → test → repair: failures from the static check and the real sandbox are fed
back to the model, every attempt is preserved, and a broken final attempt stays blocked."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.engine import ai, generation  # noqa: E402
from tests.spike.conftest import isolated_db_module, test_session  # noqa: E402,F401 (fixture import)

client = TestClient(app)
H = {"Authorization": "Bearer testtoken"}

PLAN = {
    "client_id_field": "ClientID",
    "field_mappings": {"Name": "Name", "FollowUpDate": "FollowUpDate"},
    "eligibility": {"status": "Follow-up due", "date_field": "FollowUpDate"},
    "action": "create_draft",
    "destinations": ["in_app"],
}

FORBIDDEN = "```python\nimport os\n\ndef run(rows, ctx):\n    return []\n```"
WRONG_ROWS = ("```python\ndef run(rows, ctx):\n"
              "    return [{'ClientID': r.get('ClientID')} for r in rows]\n```")
CRASHES = "```python\ndef run(rows, ctx):\n    return 1 / 0\n```"


@pytest.fixture(scope="module", autouse=True)
def _auth(isolated_db_module):
    from backend.security import tokens
    original = tokens.get_expected_token
    tokens.get_expected_token = lambda: "testtoken"
    yield
    tokens.get_expected_token = original


def _scripted(monkeypatch, outputs):
    """Model that returns the scripted bad outputs first, then the real synthesis."""
    real = ai.generate_text
    calls = []

    def fake(prompt, context=None, **kw):
        calls.append({"prompt": prompt, "context": dict(context or {})})
        if len(calls) <= len(outputs):
            return outputs[len(calls) - 1]
        return real(prompt, context, **kw)

    monkeypatch.setattr(ai, "generate_text", fake)
    return calls


def _generate(**extra):
    plan_id = client.post("/api/plans", json={"plan": PLAN}, headers=H).json()["plan_id"]
    res = client.post("/api/artifacts/generate",
                      json={"plan_id": plan_id, "approve_generation": True, **extra}, headers=H)
    assert res.status_code == 200, res.text
    return res.json()


def test_forbidden_code_is_repaired_from_static_feedback(monkeypatch):
    calls = _scripted(monkeypatch, [FORBIDDEN])
    out = _generate()
    assert out["repaired"] is True and out["status"] == "awaiting_test_approval"
    assert [a["status"] for a in out["attempts"]] == ["invalid", "awaiting_test_approval"]
    assert any("import outside allowlist" in p for p in out["attempts"][0]["problems"])
    assert calls[1]["context"]["repair_feedback"] and "import os" in calls[1]["context"]["previous_code"]
    assert "rejected" in calls[1]["prompt"]


def test_wrong_output_is_repaired_from_sandbox_feedback(monkeypatch):
    calls = _scripted(monkeypatch, [WRONG_ROWS])
    out = _generate()
    assert out["repaired"] is True and out["self_check"] == "passed"
    first = out["attempts"][0]
    assert first["self_check"] == "failed"
    assert any("expected_outputs_match" in p for p in first["problems"])
    assert any("expected_outputs_match" in f for f in calls[1]["context"]["repair_feedback"])


def test_runtime_crash_is_reported_back(monkeypatch):
    _scripted(monkeypatch, [CRASHES])
    out = _generate()
    assert out["repaired"] is True
    assert any("sandbox error" in p or "failed" in p for p in out["attempts"][0]["problems"])


def test_attempts_are_capped_and_final_failure_is_not_activatable(monkeypatch):
    _scripted(monkeypatch, [FORBIDDEN] * 10)
    out = _generate()
    assert len(out["attempts"]) == generation.MAX_REPAIR_ATTEMPTS
    assert out["repaired"] is False and out["status"] == "invalid"
    res = client.post("/api/approvals/activation",
                      json={"artifact_id": out["artifact_id"], "note": "try"}, headers=H)
    assert res.status_code == 409


def test_superseded_attempts_cannot_be_tested(monkeypatch):
    _scripted(monkeypatch, [WRONG_ROWS])
    out = _generate()
    from backend.models import GeneratedArtifact
    with test_session() as db:
        first = db.query(GeneratedArtifact).filter(
            GeneratedArtifact.version == out["attempts"][0]["version"],
            GeneratedArtifact.status == "invalid").first()
        assert first is not None
        first_id = first.id
    res = client.post("/api/test-jobs", json={"artifact_id": first_id, "fixture": "reset",
                                              "consent": True}, headers=H)
    assert res.status_code == 409


def test_clean_first_attempt_needs_no_repair():
    out = _generate()
    assert out["repaired"] is False and len(out["attempts"]) == 1
    assert out["self_check"] == "passed"


def test_self_repair_can_be_disabled(monkeypatch):
    _scripted(monkeypatch, [FORBIDDEN])
    out = _generate(self_repair=False)
    assert len(out["attempts"]) == 1 and out["status"] == "invalid"


def test_report_problems_are_specific():
    rep = {"status": "failed", "error": None, "checks": [
        {"name": "result_is_list", "ok": True},
        {"name": "expected_outputs_match", "ok": False, "detail": {"expected": ["C1"], "got": ["C2"]}}]}
    probs = generation.report_problems(rep)
    assert len(probs) == 1 and "C1" in probs[0] and "C2" in probs[0]


DATED_PLAN = {**PLAN, "eligibility": {**PLAN["eligibility"], "date_value": "2026-09-20"}}


def test_boundary_rows_catch_a_missing_date_rule():
    from backend.app import _self_check
    report = _self_check(generation.broken_draft(DATED_PLAN)["code"], DATED_PLAN)
    problems = generation.report_problems(report)
    assert problems and "EDGE-LATE" in problems[0]


def test_start_broken_is_labelled_and_repaired_by_the_real_loop():
    plan_id = client.post("/api/plans", json={"plan": DATED_PLAN}, headers=H).json()["plan_id"]
    res = client.post("/api/artifacts/generate",
                      json={"plan_id": plan_id, "approve_generation": True, "start_broken": True},
                      headers=H).json()
    first, last = res["attempts"][0], res["attempts"][-1]
    assert first["seeded"] is True and first["status"] == "invalid" and first["problems"]
    assert last["seeded"] is False and not last["problems"] and "def run" in last["code"]
    assert res["repaired"] is True and res["status"] == "awaiting_test_approval"
