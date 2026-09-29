"""Registry supply-chain: signed manifests, catalog-derived permission scopes, and
tamper detection at import time."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.security import signing  # noqa: E402
from tests.spike.conftest import isolated_db_module, test_session  # noqa: E402,F401 (fixture import)

client = TestClient(app)
H = {"Authorization": "Bearer testtoken"}

GRAPH = {
    "id": "wf_sign_tpl",
    "name": "Signed follow-up template",
    "triggers": [{"type": "schedule", "cron": "0 9 * * MON-FR"}],
    "nodes": [
        {"id": "src", "type": "file.read_table", "params": {"alias": "sample-tracking-file", "max_rows": 1000}},
        {"id": "due", "type": "data.filter", "params": {"from": "src.rows", "where": "due"}},
        {"id": "note", "type": "notify.desktop", "params": {"title_key": "run_done"}},
    ],
    "edges": [{"from": "src", "to": "due"}, {"from": "due", "to": "note"}],
}


@pytest.fixture(scope="module", autouse=True)
def _auth(isolated_db_module):
    from backend.security import tokens
    original = tokens.get_expected_token
    tokens.get_expected_token = lambda: "testtoken"
    yield
    tokens.get_expected_token = original


def _publish(connectors=None):
    res = client.post("/api/registry/publish",
                      json={"slug": f"signed-{uuid.uuid4().hex[:8]}", "title": "Signed",
                            "graph": GRAPH, "compatible_connectors": connectors or [],
                            "publication_consent": True}, headers=H)
    assert res.status_code == 200, res.text
    return res.json()


def _tamper(template_id: str, **changes):
    from backend.db import SessionLocal
    from backend.models import RegistryTemplate
    with SessionLocal() as db:
        row = db.get(RegistryTemplate, template_id)
        for k, v in changes.items():
            setattr(row, k, v)
        db.commit()


def _import(template_id: str, **extra):
    return client.post("/api/registry/import",
                       json={"template_id": template_id, "local_mapping": {}, **extra}, headers=H)


def test_publish_signs_manifest_and_derives_scopes_from_catalog():
    pub = _publish(connectors=["tally"])
    scopes = {(p["scope"], p["target"]) for p in pub["permissions"]}
    assert scopes == {("read-content", "sample-tracking-file"), ("notify", ""), ("connector", "tally")}
    assert pub["signer_pubkey"] == signing.local_public_key()

    listed = [t for t in client.get("/api/registry/templates", headers=H).json()
              if t["template_id"] == pub["template_id"]][0]
    assert listed["signed"] is True
    assert listed["permissions"] == pub["permissions"]


def test_clean_import_reports_verification_and_scopes():
    pub = _publish()
    res = _import(pub["template_id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "untrusted_draft"
    assert body["verified"]["signature"] is True
    assert body["permissions"] == pub["permissions"]


def test_graph_edited_after_publication_is_refused():
    pub = _publish()
    evil = json.loads(json.dumps(GRAPH))
    evil["nodes"].append({"id": "w", "type": "file.update_rows",
                          "params": {"alias": "payroll", "filename": "x.csv",
                                     "set": "paid", "purpose": "exfil"}})
    _tamper(pub["template_id"], graph_json=signing.canonical(evil))
    res = _import(pub["template_id"])
    assert res.status_code == 409
    assert "artifact hash" in res.text


def test_rehashed_graph_still_fails_signature():
    pub = _publish()
    evil = dict(GRAPH, name="renamed by attacker")
    text = signing.canonical(evil)
    _tamper(pub["template_id"], graph_json=text, artifact_sha256=signing.sha256_hex(text))
    res = _import(pub["template_id"])
    assert res.status_code == 409
    assert "signature does not verify" in res.text


def test_under_declared_permissions_are_refused():
    pub = _publish()
    _tamper(pub["template_id"], permissions_json="[]")
    res = _import(pub["template_id"])
    assert res.status_code == 409
    assert "declared permissions" in res.text


def test_unsigned_legacy_template_is_refused():
    pub = _publish()
    _tamper(pub["template_id"], signature="", signer_pubkey="")
    res = _import(pub["template_id"])
    assert res.status_code == 409
    assert "unsigned" in res.text


def test_untrusted_signer_is_refused():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64
    from cryptography.hazmat.primitives import serialization

    pub = _publish()
    from backend.db import SessionLocal
    from backend.models import RegistryTemplate
    with SessionLocal() as db:
        row = db.get(RegistryTemplate, pub["template_id"])
        text = signing.manifest(slug=row.slug, version=row.version, title=row.title,
                                artifact_sha256=row.artifact_sha256,
                                compatible_connectors=json.loads(row.compatible_connectors_json),
                                permissions=json.loads(row.permissions_json))
    stranger = Ed25519PrivateKey.generate()
    sig = base64.b64encode(stranger.sign(text.encode())).decode()
    stranger_pub = base64.b64encode(stranger.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    _tamper(pub["template_id"], signature=sig, signer_pubkey=stranger_pub)
    res = _import(pub["template_id"])
    assert res.status_code == 409
    assert "trusted signer" in res.text


def test_import_requires_all_scopes_when_grants_given():
    pub = _publish()
    denied = _import(pub["template_id"], granted_scopes=["notify"])
    assert denied.status_code == 403
    assert denied.json()["detail"]["missing_scopes"] == ["read-content"]
    ok = _import(pub["template_id"], granted_scopes=["notify", "read-content"])
    assert ok.status_code == 200, ok.text
