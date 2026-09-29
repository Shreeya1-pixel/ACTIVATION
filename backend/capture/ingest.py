"""Single path for persisting capture events: validate, pseudonymize, dedupe, store."""
from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import Session

from backend import spike_config as cfg
from backend import validate_events as phase1_validate
from backend.models import Event
from backend.security import pii

BATCH = 100  # validator bound per call


def store_events(db: Session, events: list[dict]) -> list[str]:
    """Validate against the event contract (raises ValueError), then insert events whose
    event_id is new. Record keys and resources are pseudonymized before storage."""
    for i in range(0, len(events), BATCH):
        phase1_validate.validate_events(events[i:i + BATCH])
    key = cfg.SPIKE_TOKEN.encode()
    accepted: list[str] = []
    for ev in events:
        if db.query(Event).filter(Event.event_id == ev["event_id"]).first() is not None:
            continue
        db.add(Event(id=str(uuid.uuid4()), event_id=ev["event_id"],
                     schema_version=ev["schema_version"], source=ev["source"],
                     action=ev["action"],
                     resource=pii.pseudonymize_text(ev["resource"], key),
                     record_key=pii.pseudonymize_text(ev["record_key"], key),
                     changed_fields_json=json.dumps(ev["changed_fields"]),
                     outcome=ev["outcome"], captured_at=ev["captured_at"],
                     processed_at=ev["processed_at"], synthetic=ev["synthetic"]))
        accepted.append(ev["event_id"])
    db.commit()
    return accepted
