"""Phase 9 registry: consent-gated publication, secret scan, untrusted imports,
withdrawal stops new imports without invalidating installed copies."""
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

GRAPH = {
    "id": "wf_followup_tpl",
    "name": "Client Follow-up template",
    "triggers": [{"type": "schedule", "cron": "0 9 * * MON-FR"}],
    "nodes": [
        {"id": "src", "type": "file.read_table", "params": {"alias": "sample-tracking-file", "max_rows": 1000}},
        {"id": "due", "type": "data.filter", "params": {"from": "src.rows", "where": "due"}},
        {"id": "note", "type": "notify.desktop", "params": {"title_key": "run_done"}},
    ],
    "edges": [{"from": "src", "to": "due"}, {"from": "due", "to": "note"}],
}

LEAKY_GRAPH = dict(GRAPH, id="wf_leak", params={"api_key": "sk-live-123"})


@pytest.fixture(scope="module", autouse=True)
def _auth(isolated_db_module):
    from backend.security import tokens
    original = tokens.get_expected_token
    tokens.get_expected_token = lambda: "testtoken"
    pass  # schema created by isolated_db_module
    yield
    tokens.get_expected_token = original


def test_publication_requires_consent():
    res = client.post("/api/registry/publish",
                      json={"slug": "followup", "title": "T", "graph": GRAPH,
                            "publication_consent": False}, headers=H)
    assert res.status_code == 403


def test_secret_scan_blocks_leaky_template():
    res = client.post("/api/registry/publish",
                      json={"slug": "leaky", "title": "T", "graph": LEAKY_GRAPH,
                            "publication_consent": True}, headers=H)
    assert res.status_code == 422
    assert "api_key" in res.text


def test_publish_list_and_version_bump():
    import time as _time
    slug = f"followup-{_time.time_ns()}"  # unique slug: the spike DB persists between runs
    r1 = client.post("/api/registry/publish",
                     json={"slug": slug, "title": "Follow-up v1", "graph": GRAPH,
                           "publication_consent": True}, headers=H)
    assert r1.status_code == 200, r1.text
    assert r1.json()["version"] == 1
    r2 = client.post("/api/registry/publish",
                     json={"slug": slug, "title": "Follow-up v2", "graph": GRAPH,
                           "publication_consent": True}, headers=H)
    assert r2.json()["version"] == 2

    listing = client.get("/api/registry/templates", headers=H).json()
    followups = [t for t in listing if t["slug"] == slug]
    assert len(followups) == 1 and followups[0]["version"] == 2  # only latest per slug


def test_import_is_untrusted_draft_and_never_inherits_approval():
    tpl = client.get("/api/registry/templates", headers=H).json()[0]
    imp = client.post("/api/registry/import",
                      json={"template_id": tpl["template_id"],
                            "local_mapping": {"Status": "State"}}, headers=H)
    assert imp.status_code == 200
    body = imp.json()
    assert body["status"] == "untrusted_draft"
    assert "activation" in body["note"]
    # imported graph must differ from the published artifact (mapping applied)
    assert body["artifact_sha256"] != tpl["artifact_sha256"]


def test_withdrawal_stops_new_imports_only():
    slug = "withdraw-me"
    pub = client.post("/api/registry/publish",
                      json={"slug": slug, "title": "W", "graph": GRAPH,
                            "publication_consent": True}, headers=H).json()
    w = client.post("/api/registry/withdraw", json={"slug": slug}, headers=H)
    assert w.status_code == 200
    # withdrawn template no longer listed, import rejected
    listing = client.get("/api/registry/templates", headers=H).json()
    assert all(t["slug"] != slug for t in listing)
    res = client.post("/api/registry/import",
                      json={"template_id": pub["template_id"],
                            "local_mapping": {}}, headers=H)
    assert res.status_code == 404
