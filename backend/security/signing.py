"""Registry supply-chain: Ed25519-signed template manifests + declared permission scopes.

A published template carries a manifest {slug, version, title, artifact_sha256,
compatible_connectors, permissions} signed by the publishing office's key. On import the
graph hash and the signature are re-verified, so a template edited after publication (in
the DB, in transit, or by a compromised mirror) is refused instead of installed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from backend.engine.catalog import CATALOG
from backend.spike_config import DATA_DIR

_KEY_FILE = "registry_signing_key.pem"
_cached_key: Ed25519PrivateKey | None = None


def canonical(obj) -> str:  # noqa: ANN001
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _load_or_create_key() -> Ed25519PrivateKey:
    global _cached_key
    if _cached_key is not None:
        return _cached_key
    path = DATA_DIR / _KEY_FILE
    if path.is_file():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RuntimeError(f"{path} is not an Ed25519 key")
    else:
        key = Ed25519PrivateKey.generate()
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    _cached_key = key
    return key


def _pub_b64(pub: Ed25519PublicKey) -> str:
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def local_public_key() -> str:
    return _pub_b64(_load_or_create_key().public_key())


def trusted_signers() -> set[str]:
    """This office's own key plus any keys listed in AUTOSTACK_TRUSTED_SIGNERS (comma-separated)."""
    extra = {k.strip() for k in os.environ.get("AUTOSTACK_TRUSTED_SIGNERS", "").split(",") if k.strip()}
    return {local_public_key(), *extra}


def derive_permissions(graph: dict, connectors: list[str]) -> list[dict]:
    """Scopes a template needs, derived from the node catalog — never self-declared by the
    publisher, so a template cannot under-report what it touches."""
    scopes: dict[tuple, dict] = {}
    for node in graph.get("nodes", []):
        spec = CATALOG.get(node.get("type", ""))
        if spec is None or spec.permission is None:
            continue
        params = node.get("params", {}) or {}
        target = params.get("alias") or params.get("destination") or ""
        key = (spec.permission, target)
        entry = scopes.setdefault(key, {"scope": spec.permission, "target": target, "nodes": []})
        entry["nodes"].append(node.get("id"))
    for conn in connectors:
        scopes.setdefault(("connector", conn), {"scope": "connector", "target": conn, "nodes": []})
    return sorted(scopes.values(), key=lambda s: (s["scope"], s["target"]))


def scope_names(permissions: list[dict]) -> set[str]:
    return {p["scope"] for p in permissions}


def manifest(*, slug: str, version: int, title: str, artifact_sha256: str,
             compatible_connectors: list[str], permissions: list[dict]) -> str:
    return canonical({"slug": slug, "version": version, "title": title,
                      "artifact_sha256": artifact_sha256,
                      "compatible_connectors": sorted(compatible_connectors),
                      "permissions": permissions})


def sign(manifest_text: str) -> tuple[str, str]:
    key = _load_or_create_key()
    sig = key.sign(manifest_text.encode())
    return base64.b64encode(sig).decode(), _pub_b64(key.public_key())


def verify(manifest_text: str, signature_b64: str, signer_pubkey_b64: str) -> bool:
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(signer_pubkey_b64))
        pub.verify(base64.b64decode(signature_b64), manifest_text.encode())
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
