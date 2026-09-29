"""Effect journal + idempotency claims (S11 / USP-3): exactly-once business effects.

claim_effect() is INSERT-first: the database's PRIMARY KEY is the claim — two concurrent
runs can never both hold the same effect key. Unclaimed = applied; loss of claim = not applied.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.models import IdempotencyClaim


def effect_key(record_key: str, purpose: str, run_date: str, destination: str) -> str:
    return f"{record_key}|{purpose}|{run_date}|{destination}"


def claim_effect(db: Session, key: str, run_id: str) -> bool:
    """Try to claim an effect key. True = this run owns it; False = already claimed/applied."""
    existing = db.get(IdempotencyClaim, key)
    if existing is not None:
        return False
    db.add(IdempotencyClaim(effect_key=key, run_id=run_id, applied=False))
    try:
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False


def mark_applied(db: Session, key: str) -> None:
    claim = db.get(IdempotencyClaim, key)
    if claim is not None:
        claim.applied = True
        db.commit()


def claims_for_run(db: Session, run_id: str) -> list[IdempotencyClaim]:
    return (
        db.query(IdempotencyClaim)
        .filter(IdempotencyClaim.run_id == run_id)
        .order_by(IdempotencyClaim.effect_key)
        .all()
    )
