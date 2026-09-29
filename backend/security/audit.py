"""Hash-chained append-only audit log (USP-2).

hash = sha256(prev_hash | payload_json | at_iso | seq)
verify_chain() recomputes every link; any tampering breaks it loudly.

Concurrency: appends are serialized by a process-wide lock and committed in their
own dedicated transaction before the lock releases. Two concurrent bridge calls
therefore can never read the same chain tail (same prev_hash/seq) — the failure
mode that forks a hash chain. The `db` parameter is kept for call-site
compatibility; the audit row is intentionally independent of the caller's
transaction so a chain link is never lost to an unrelated rollback.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import AuditEntry

GENESIS = "0" * 64

_APPEND_LOCK = threading.Lock()


def _compute(prev_hash: str, payload_json: str, at_iso: str, seq: int) -> str:
    material = f"{prev_hash}|{payload_json}|{at_iso}|{seq}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def append(db: Session, kind: str, payload: dict) -> AuditEntry:
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    at = datetime.now(timezone.utc).isoformat()
    # SQLite is single-writer: the caller's pending transaction holds the write lock,
    # so commit it BEFORE the dedicated audit session tries to insert (otherwise the
    # two connections deadlock until busy_timeout). Trade-off (documented in the plan):
    # caller effects commit first and the audit link follows; the idempotency journal,
    # not the audit chain, is the source of truth for effect atomicity. Milestone C
    # upgrades this to an outbox pattern for strict atomicity.
    db.commit()
    with _APPEND_LOCK:
        from backend.db import SessionLocal  # local import: avoids circulars at module load
        session = SessionLocal()
        try:
            last = session.execute(
                select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(1)
            ).scalar_one_or_none()
            prev_hash = last.hash if last else GENESIS
            seq = (last.seq + 1) if last else 1
            entry = AuditEntry(
                seq=seq,
                at=at,
                kind=kind,
                payload_json=payload_json,
                prev_hash=prev_hash,
                hash=_compute(prev_hash, payload_json, at, seq),
            )
            session.add(entry)
            session.commit()
            return entry
        finally:
            session.close()


def verify_chain(db: Session) -> dict:
    """Recompute every link. Returns {chain_valid, first_bad_seq, count}."""
    entries = db.execute(select(AuditEntry).order_by(AuditEntry.seq.asc())).scalars().all()
    prev = GENESIS
    for entry in entries:
        expected = _compute(prev, entry.payload_json, entry.at, entry.seq)
        if entry.prev_hash != prev or entry.hash != expected:
            return {"chain_valid": False, "first_bad_seq": entry.seq, "count": len(entries)}
        prev = entry.hash
    return {"chain_valid": True, "first_bad_seq": None, "count": len(entries)}
