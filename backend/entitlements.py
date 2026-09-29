"""Roadmap Phase B: entitlements. Tiers resolve server-side; the UI only mirrors.

Rules:
  - The server is the gate: enforcing endpoints check capabilities, never the UI.
  - Solo = everything that exists today; paid tiers ADD capabilities, never remove.
  - Government/sovereign mode is expressed as `local_only`: cloud generation is
    refused, template automation stays local. A feature expressed as refusal.
  - Every capability check that fails returns an actionable explanation naming the
    tier that unlocks it (the API never just says "forbidden").
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Org

TIERS = ("solo", "team", "enterprise", "government", "developer")

# Capability matrix — mirrors docs/product-roadmap.md §2. Values are limits (ints)
# or booleans. `local_only` is implied for the government tier.
MATRIX: dict[str, dict] = {
    "solo": {
        "discovery": True, "generation": True, "sandbox_test": True, "activation": True,
        "local_runner": True, "paired_runner": False, "scheduling": True,
        "members": 1, "approval_policy": False, "private_registry": False,
        "publish_national": False, "audit_export_local": True, "audit_export_stream": False,
        "cloud_generation": True, "connector_vault": "os_keyring", "api_access": False,
        "siem_export": False, "sso": False, "retention_admin": False, "data_residency_option": False,
    },
    "team": {
        "discovery": True, "generation": True, "sandbox_test": True, "activation": True,
        "local_runner": True, "paired_runner": True, "scheduling": True,
        "members": 25, "approval_policy": True, "private_registry": True,
        "publish_national": False, "audit_export_local": True, "audit_export_stream": False,
        "cloud_generation": True, "connector_vault": "team", "api_access": False,
        "siem_export": False, "sso": False, "retention_admin": True, "data_residency_option": False,
    },
    "enterprise": {
        "discovery": True, "generation": True, "sandbox_test": True, "activation": True,
        "local_runner": True, "paired_runner": True, "scheduling": True,
        "members": 100000, "approval_policy": True, "private_registry": True,
        "publish_national": False, "audit_export_local": True, "audit_export_stream": True,
        "cloud_generation": True, "connector_vault": "org", "api_access": True,
        "siem_export": True, "sso": True, "retention_admin": True, "data_residency_option": True,
    },
    "government": {
        "discovery": True, "generation": False, "sandbox_test": True, "activation": True,
        "local_runner": True, "paired_runner": True, "scheduling": True,
        "members": 100000, "approval_policy": True, "private_registry": True,
        "publish_national": True, "audit_export_local": True, "audit_export_stream": True,
        "cloud_generation": False, "connector_vault": "on_prem", "api_access": True,
        "siem_export": True, "sso": True, "retention_admin": True, "data_residency_option": True,
        "local_only": True,
    },
    "developer": {
        "discovery": True, "generation": True, "sandbox_test": True, "activation": True,
        "local_runner": True, "paired_runner": False, "scheduling": True,
        "members": 5, "approval_policy": False, "private_registry": True,
        "publish_national": True, "audit_export_local": True, "audit_export_stream": False,
        "cloud_generation": True, "connector_vault": "sandbox_keys", "api_access": True,
        "siem_export": False, "sso": False, "retention_admin": False, "data_residency_option": False,
    },
}

# Friendly unlock hints for 403 responses (the actionable-explanation rule).
UNLOCK_TIER: dict[str, str] = {
    "paired_runner": "team",
    "approval_policy": "team",
    "private_registry": "team",
    "retention_admin": "team",
    "api_access": "enterprise",
    "siem_export": "enterprise",
    "audit_export_stream": "enterprise",
    "sso": "enterprise",
    "data_residency_option": "enterprise",
    "publish_national": "developer",  # developer or government
}


def capabilities_for_tier(tier: str) -> dict:
    base = dict(MATRIX.get(tier, MATRIX["solo"]))
    return base


def get_or_create_org(db: Session) -> Org:
    org = db.scalar(select(Org).limit(1))
    if org is None:
        org = Org(id="org-local", name="Local Workspace", tier="solo", local_only=False)
        db.add(org)
        db.commit()
    return org


def get_capabilities(db: Session) -> dict:
    org = get_or_create_org(db)
    caps = capabilities_for_tier(org.tier)
    caps["tier"] = org.tier
    caps["org_id"] = org.id
    caps["org_name"] = org.name
    caps["local_only"] = bool(org.local_only or caps.get("local_only"))
    return caps


def set_tier(db: Session, tier: str, org_name: str | None = None) -> dict:
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    org = get_or_create_org(db)
    org.tier = tier
    org.local_only = (tier == "government")
    if org_name:
        org.name = org_name[:160]
    db.commit()
    return get_capabilities(db)


def check(db: Session, capability: str) -> tuple[bool, dict, str]:
    """Server-side gate. Returns (allowed, capabilities, explanation)."""
    caps = get_capabilities(db)
    if caps.get(capability) is True:
        return True, caps, ""
    limit = caps.get(capability)
    if isinstance(limit, int) and limit > 0:
        return True, caps, ""
    need = UNLOCK_TIER.get(capability)
    why = caps.get(f"{capability}_why") or "not enabled for this tier"
    return False, caps, f"{why}" + (f" (unlocked by the {need} tier)" if need else "")


def require(db: Session, capability: str) -> dict:
    ok, caps, why = check(db, capability)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail={"error": "capability not enabled",
                                                     "capability": capability,
                                                     "how_to_unlock": why})
    return caps
