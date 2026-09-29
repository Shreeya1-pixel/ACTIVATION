"""Security: token authentication (S3). Spike uses env-or-generated token; Milestone A moves to keyring + rotation."""
from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

from backend.spike_config import SPIKE_TOKEN


def get_expected_token() -> str:
    env = os.environ.get("AUTOSTACK_TOKEN")
    return env if env else SPIKE_TOKEN


def require_token(request: Request) -> None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "missing bearer token"})
    presented = auth.removeprefix("Bearer ").strip()
    if hmac.compare_digest(presented, get_expected_token()):
        return
    # Roadmap Phase A: per-user tokens are accepted by every route so a signed-in
    # user gets the whole app, not just the new pages. The legacy service-token
    # path above is unchanged; invalid user tokens fail closed below.
    from backend import identity
    from backend.db import SessionLocal
    with SessionLocal() as db:
        user = identity.user_for_token(db, presented)
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "invalid or revoked token"})


def _principal_for_token(presented: str):
    """('service', None) for the service token, ('user', user) for a valid user
    token, or None when the token is invalid/revoked (fail closed)."""
    if hmac.compare_digest(presented, get_expected_token()):
        return "service", None
    from backend import identity
    from backend.db import SessionLocal
    with SessionLocal() as db:
        user = identity.user_for_token(db, presented)
    return ("user", user) if user else None


def require_writer(request: Request) -> None:
    """B1: mutating legacy routes require operator role or the service principal.

    Compat: every pre-existing caller (QA probe, Node-RED bridge, Electron shell,
    tests) authenticates with the service token, which keeps owner-equivalent
    rights — nothing that worked before changes behavior.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "missing bearer token"})
    presented = auth.removeprefix("Bearer ").strip()
    principal = _principal_for_token(presented)
    if principal is None:
        raise HTTPException(status_code=401, detail={"error": "invalid or revoked token"})
    kind, user = principal
    if kind == "service":
        return
    from backend import teams
    from backend.db import SessionLocal
    with SessionLocal() as db:
        role = teams.user_role(db, user)
    if not teams.role_allows(role, "run"):
        raise HTTPException(status_code=403, detail={
            "error": f"role '{role}' may not perform this action",
            "how_to_unlock": "operator role or higher"})


def require_admin(request: Request) -> None:
    """B1: administrative legacy routes (tier/org changes) require owner role or
    the service principal. Mirrors admin_guard on the roadmap routes."""
    _require_permission(request, "admin")


def _require_permission(request: Request, permission: str) -> None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "missing bearer token"})
    presented = auth.removeprefix("Bearer ").strip()
    principal = _principal_for_token(presented)
    if principal is None:
        raise HTTPException(status_code=401, detail={"error": "invalid or revoked token"})
    kind, user = principal
    if kind == "service":
        return
    from backend import teams
    from backend.db import SessionLocal
    with SessionLocal() as db:
        role = teams.user_role(db, user)
    if not teams.role_allows(role, permission):
        need = teams.PERMISSION_MIN_ROLE.get(permission, "owner")
        raise HTTPException(status_code=403, detail={
            "error": f"role '{role}' may not perform this action",
            "how_to_unlock": f"{need} role"})


def require_tester(request: Request) -> None:
    """QA round 7: sandbox-test/activation routes need approver+ (the legacy
    lifecycle routes previously accepted operator, contradicting the product's
    own PERMISSION_MIN_ROLE: test/activate = approver)."""
    _require_permission(request, "test")


def require_publisher(request: Request) -> None:
    """QA round 7: registry publication needs owner+ (publish = owner)."""
    _require_permission(request, "publish")
