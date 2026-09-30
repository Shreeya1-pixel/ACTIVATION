"""Registry tamper demo: publish a signed template, then try to import it after tampering.

Runs against a throwaway SQLite database through the real API routes. Each attempt edits the
stored template the way an attacker with database or file access could, then calls
/api/registry/import. Results are written to docs/registry-tamper.json and rendered to
docs/images/registry-tamper.png.
"""
from __future__ import annotations

import base64
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if "--render-only" not in sys.argv:
    from fastapi.testclient import TestClient

    from backend import db as db_mod
    from backend.app import app
    from backend.security import signing, tokens
    from tests.spike.conftest import _install_isolated_db

GRAPH = {
    "id": "wf_followup",
    "name": "Weekly follow-up reminder",
    "triggers": [{"type": "schedule", "cron": "0 9 * * MON-FRI"}],
    "nodes": [
        {"id": "src", "type": "file.read_table", "params": {"alias": "sample-tracking-file", "max_rows": 1000}},
        {"id": "due", "type": "data.filter", "params": {"from": "src.rows", "where": "due"}},
        {"id": "note", "type": "notify.desktop", "params": {"title_key": "run_done"}},
    ],
    "edges": [{"from": "src", "to": "due"}, {"from": "due", "to": "note"}],
}
H = {"Authorization": "Bearer demotoken"}


def _publish(client):
    res = client.post("/api/registry/publish",
                      json={"slug": f"followup-{uuid.uuid4().hex[:6]}", "title": "Weekly follow-up",
                            "graph": GRAPH, "compatible_connectors": [], "publication_consent": True},
                      headers=H)
    res.raise_for_status()
    return res.json()


def _tamper(template_id, **changes):
    from backend.models import RegistryTemplate
    with db_mod._TEST_SESSION() as db:
        row = db.get(RegistryTemplate, template_id)
        for k, v in changes.items():
            setattr(row, k, v)
        db.commit()


def _row(template_id):
    from backend.models import RegistryTemplate
    with db_mod._TEST_SESSION() as db:
        return db.get(RegistryTemplate, template_id)


def _import(client, template_id):
    return client.post("/api/registry/import",
                       json={"template_id": template_id, "local_mapping": {}}, headers=H)


def attack_add_write_step(tid):
    evil = json.loads(json.dumps(GRAPH))
    evil["nodes"].append({"id": "w", "type": "file.update_rows",
                          "params": {"alias": "payroll", "filename": "x.csv", "set": "paid", "purpose": "x"}})
    _tamper(tid, graph_json=signing.canonical(evil))


def attack_rehash(tid):
    text = signing.canonical(dict(GRAPH, name="renamed by attacker"))
    _tamper(tid, graph_json=text, artifact_sha256=signing.sha256_hex(text))


def attack_strip_permissions(tid):
    _tamper(tid, permissions_json="[]")


def attack_strip_signature(tid):
    _tamper(tid, signature="", signer_pubkey="")


def attack_foreign_signer(tid):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    row = _row(tid)
    text = signing.manifest(slug=row.slug, version=row.version, title=row.title,
                            artifact_sha256=row.artifact_sha256,
                            compatible_connectors=json.loads(row.compatible_connectors_json),
                            permissions=json.loads(row.permissions_json))
    key = Ed25519PrivateKey.generate()
    sig = base64.b64encode(key.sign(text.encode())).decode()
    pub = base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    _tamper(tid, signature=sig, signer_pubkey=pub)


ATTACKS = [
    ("Added a hidden 'write to payroll' step", attack_add_write_step),
    ("Edited the steps and recomputed the hash", attack_rehash),
    ("Removed the declared permissions", attack_strip_permissions),
    ("Stripped the signature", attack_strip_signature),
    ("Re-signed with an untrusted key", attack_foreign_signer),
]


def _error(res):
    try:
        detail = res.json().get("detail")
    except ValueError:
        return res.text
    if isinstance(detail, dict):
        if detail.get("problems"):
            return "; ".join(detail["problems"])
        return detail.get("error") or json.dumps(detail)
    return str(detail)


def run():
    tokens.get_expected_token = lambda: "demotoken"
    session, cleanup = _install_isolated_db()
    db_mod._TEST_SESSION = session
    results = []
    try:
        client = TestClient(app)
        clean = _publish(client)
        res = _import(client, clean["template_id"])
        results.append({"attempt": "Untouched template (control)", "status": res.status_code,
                        "result": "imported as untrusted draft" if res.status_code == 200 else _error(res)})
        for label, fn in ATTACKS:
            pub = _publish(client)
            fn(pub["template_id"])
            res = _import(client, pub["template_id"])
            results.append({"attempt": label, "status": res.status_code, "result": _error(res)})
    finally:
        db_mod._TEST_SESSION = None
        cleanup()
    return results


def render(results, path: Path):
    from PIL import Image, ImageDraw, ImageFont

    def font(size, bold=False):
        for name in (["Menlo-Bold.ttf", "/System/Library/Fonts/Menlo.ttc"] if bold
                     else ["/System/Library/Fonts/Menlo.ttc"]):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    import textwrap

    mono, head = font(22), font(27)
    w, pad, indent, line_h = 1150, 36, 125, 30
    wrapped = [textwrap.wrap(r["result"], 70) for r in results]
    h = pad * 2 + 70 + sum(48 + line_h * len(lines) + 22 for lines in wrapped)
    img = Image.new("RGB", (w, h), (20, 24, 31))
    d = ImageDraw.Draw(img)
    d.text((pad, pad), "POST /api/registry/import  (real responses)", font=head, fill=(200, 210, 225))
    y = pad + 70
    for r, lines in zip(results, wrapped):
        colour = (80, 200, 120) if r["status"] == 200 else (240, 90, 90)
        d.rounded_rectangle((pad, y, pad + 95, y + 42), radius=8, fill=colour)
        d.text((pad + 19, y + 6), str(r["status"]), font=head, fill=(15, 15, 15))
        d.text((pad + indent, y + 4), r["attempt"], font=head, fill=(235, 238, 245))
        y += 48
        for line in lines:
            d.text((pad + indent, y), line, font=mono, fill=(150, 160, 175))
            y += line_h
        y += 22
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


if __name__ == "__main__":
    out = ROOT / "docs" / "registry-tamper.json"
    if "--render-only" in sys.argv:
        results = json.loads(out.read_text())
    else:
        results = run()
        for r in results:
            print(f"{r['status']}  {r['attempt']:<45} {r['result']}")
        out.write_text(json.dumps(results, indent=2) + "\n")
    try:
        render(results, ROOT / "docs" / "images" / "registry-tamper.png")
    except ImportError:
        print("Pillow not installed; rerun with --render-only in an environment that has it")
