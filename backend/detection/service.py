"""Detection service (Phase 4): persisted candidates + notifications from real events.

Flow: events table → sequences.detect_candidates (pure) → candidates table (upsert by
sequence+resource fingerprint) → persistent notifications (suppressed for unchanged
candidates). Evidence is exact counts and dates — never a fabricated percentage.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.detection import sequences
from backend.models import Candidate, Event, Notification

FINGERPRINT_UNCHANGED: dict[str, str] = {}  # candidate_id -> last evidence fingerprint


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _candidate_fingerprint(sequence: list[str], resource: str) -> str:
    material = json.dumps([sequence, resource])
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def _evidence_fingerprint(evidence: dict) -> str:
    return hashlib.sha256(
        json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()[:32]


def refresh_from_events(db: Session, now: str | None = None) -> dict:
    """Recompute candidates from all stored events; upsert + notify. Returns summary."""
    events = [e._to_dict_() if hasattr(e, "_to_dict_") else _event_dict(e)
              for e in db.query(Event).order_by(Event.captured_at).all()]
    candidates = sequences.detect_candidates(events, now=now)

    created = updated = notified = 0
    for cand in candidates:
        fp = _candidate_fingerprint(cand["sequence"], cand["resource"])
        row = db.query(Candidate).filter(Candidate.fingerprint == fp).first() \
            if hasattr(Candidate, "fingerprint") else None
        # Candidate model in the spike has no fingerprint column; look up by pattern_json
        if row is None:
            rows = (db.query(Candidate)
                    .filter(Candidate.pattern_json.like(f"%{cand['resource']}%")).all())
            for r in rows:
                if json.loads(r.pattern_json).get("sequence") == cand["sequence"]:
                    row = r
                    break
        evidence_fp = _evidence_fingerprint(cand["evidence"])
        if row is None:
            row = Candidate(
                id=str(uuid.uuid4()),
                pattern_json=json.dumps({"sequence": cand["sequence"],
                                         "resource": cand["resource"]}),
                evidence_json=json.dumps(cand["evidence"], sort_keys=True),
                status="suggested" if cand["qualifies"] else "observed",
                first_seen=cand["first_seen"], last_seen=cand["last_seen"],
                occurrences=cand["occurrences"],
                workflow_id=None,
            )
            db.add(row)
            created += 1
        else:
            row.evidence_json = json.dumps(cand["evidence"], sort_keys=True)
            row.last_seen = cand["last_seen"]
            row.occurrences = cand["occurrences"]
            if cand["qualifies"] and row.status == "observed":
                row.status = "suggested"
            updated += 1
        db.flush()

        if cand["qualifies"]:
            existing = (db.query(Notification)
                        .filter(Notification.candidate_fingerprint == evidence_fp).first())
            if existing is None:
                # generic content only (S7); details live behind the authorized UI
                db.add(Notification(
                    id=str(uuid.uuid4()), candidate_id=row.id,
                    candidate_fingerprint=evidence_fp,
                    title="Repeated workflow detected",
                    body=f"{cand['occurrences']} completed instances across "
                         f"{cand['evidence']['distinct_clients']} clients on "
                         f"{cand['resource']}. Open the candidate for evidence.",
                    created_at=_now(),
                ))
                notified += 1
    db.commit()
    return {"candidates_created": created, "candidates_updated": updated,
            "notifications_created": notified, "events_considered": len(events)}


def _event_dict(e: Event) -> dict:
    return {
        "event_id": e.event_id, "source": e.source, "action": e.action,
        "resource": e.resource, "record_key": e.record_key, "outcome": e.outcome,
        "captured_at": e.captured_at, "synthetic": bool(e.synthetic),
        "changed_fields": json.loads(e.changed_fields_json or "[]"),
    }
