"""Shared row-processing core used by both the worker's direct runner and the Node-RED bridge nodes.

Keeping the logic here (not in route handlers) means the S4 spike exercises the exact same code
path a production node would call — one implementation, two transports.
"""
from __future__ import annotations

import csv
import io
import sys
import threading
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from backend.engine import journal
from backend.engine.expressions import eval_bool
from backend.security import audit, safeio
from backend.spike_config import RUN_DATE

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.file_diff import read_snapshot  # noqa: E402  (reuse the Phase 1 proof as-is)


class ClientDataError(ValueError):
    """Caller-caused data/config contract violation (bad column, unknown template,
    missing row). Subclasses ValueError so every existing handler keeps working;
    the run route maps it to HTTP 400 instead of 500."""

DRAFT_TEMPLATES = {
    "followup_en": "Hello {Name}, this is a sample follow-up reminder for {FollowUpDate}.",
    "followup_hi": "नमस्ते {Name}, यह {FollowUpDate} के लिए एक नमूना फॉलो-अप अनुस्मारक है।",
}


def read_table(resource_alias: str, filename: str, max_rows: int = 1000) -> list[dict]:
    """Bounded read of the tracking table via the existing Phase 1 parser contract."""
    if max_rows > 1000:
        raise ClientDataError("max_rows exceeds fixture budget (1000)")
    if resource_alias == safeio.WATCHED_ALIAS:
        # the user's own sheet: generic header/rows reader, not the sample contract
        from backend.capture import sheets
        _header, table, _blank = sheets.read_table(safeio.resolve_resource(resource_alias, filename))
        return table[:max_rows]
    payload = safeio.read_resource(resource_alias, filename)
    rows = list(read_snapshot(_as_fixture_path(payload, filename)).values())
    return rows[:max_rows]


def _as_fixture_path(payload: bytes, filename: str) -> Path:
    # read_snapshot takes a Path in Phase 1; for the spike we stage the bytes into scratch
    # (production Milestone C refactor: read_snapshot gains a bytes/TextIO entrypoint).
    scratch = safeio.resolve_resource("spike-scratch", f"staged-{safeio.sha256_bytes(payload)[:12]}-{filename}")
    if not scratch.exists():
        scratch.write_bytes(payload)
    return scratch


def filter_due(rows: list[dict], run_date: str) -> list[dict]:
    context = {"run_date": run_date}
    due = []
    for row in rows:
        ctx = {"row": row, **context}
        if eval_bool("row.Status == 'Follow-up due' and row.FollowUpDate <= run_date", ctx):
            due.append(row)
    return due


def update_status(db: Session, *, run_id: str, alias: str, filename: str, row: dict,
                  new_status: str, purpose: str, run_date: str) -> dict:
    """Claim the update effect, then apply the row status change through safeio. Exactly-once.

    The whole read-modify-write cycle runs under a per-resource lock: concurrent bridge
    calls (Node-RED fans out one message per row) would otherwise read the same original
    bytes and the last write would silently drop the other row's update (lost update).
    """
    lock = _rmw_lock(alias, filename)
    with lock:
        return _update_status_locked(db, run_id=run_id, alias=alias, filename=filename, row=row,
                                     new_status=new_status, purpose=purpose, run_date=run_date)


_RMW_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_RMW_LOCKS_GUARD = threading.Lock()


def _rmw_lock(alias: str, filename: str) -> threading.Lock:
    key = (alias, filename)
    with _RMW_LOCKS_GUARD:
        if key not in _RMW_LOCKS:
            _RMW_LOCKS[key] = threading.Lock()
        return _RMW_LOCKS[key]


def _update_status_locked(db: Session, *, run_id: str, alias: str, filename: str, row: dict,
                          new_status: str, purpose: str, run_date: str) -> dict:
    """Claim the update effect, then apply the row status change through safeio. Exactly-once."""
    effect = journal.effect_key(row["ClientID"], purpose + ":status", run_date, alias)
    if not journal.claim_effect(db, effect, run_id):
        return {"skipped": True, "reason": "idempotent-claimed", "effect_key": effect}
    current = safeio.read_resource(alias, filename).decode("utf-8-sig")
    reader = list(csv.reader(io.StringIO(current)))
    header, body = reader[0], reader[1:]
    updated = False
    for r in body:
        if r and r[0] == row["ClientID"]:
            idx = header.index("Status")
            r[idx] = new_status
            updated = True
    if not updated:
        journal.mark_applied(db, effect)  # nothing changed; release claim to avoid stuck state
        raise ClientDataError(f"row not found: {row['ClientID']}")
    out = io.StringIO()
    csv.writer(out).writerows([header, *body])
    result = safeio.write_resource(alias, filename, out.getvalue().encode("utf-8"), backup=True)
    journal.mark_applied(db, effect)
    audit.append(db, "effect.applied", {"effect_key": effect, "kind": "row_update",
                                        "sha256": result["sha256"], "run_id": run_id})
    db.commit()
    return {"skipped": False, "effect_key": effect, **result}


def create_draft(db: Session, *, run_id: str, record_key: str, row: dict, template_id: str,
                 destination: str, run_date: str, purpose: str = "followup-draft",
                 templates: dict | None = None, format_fields: dict | None = None) -> dict:
    """Claim the draft effect, then create the in-app draft. Exactly-once.

    `purpose` namespaces the effect key (followup vs invoice/PO approval) and
    `templates` lets a second workflow bring its own template pack (Phase 8) without
    touching the followup pack.
    """
    from backend.models import Draft
    import uuid

    effect = journal.effect_key(record_key, purpose, run_date, destination)
    if not journal.claim_effect(db, effect, run_id):
        return {"skipped": True, "reason": "idempotent-claimed", "effect_key": effect}
    template = (templates if templates is not None else DRAFT_TEMPLATES).get(template_id)
    if template is not None:
        # contracts.md template style: str.format placeholders. format_fields lets a
        # second workflow render from its own row fields (Phase 8); the followup pack
        # keeps its fixed kwargs behavior unchanged.
        if format_fields is not None:
            body = template.format(**format_fields)
        else:
            body = template.format(Name=row.get("Name", ""), FollowUpDate=row.get("FollowUpDate", ""),
                                   ClientID=row.get("ClientID", ""))
    elif template_id == "ai:auto":
        # Spike S7: AI generation through the provider adapter (mock default, Gemini when keyed).
        # Fail-closed: a provider error releases the claim (same precedent as row-not-found)
        # so a retry run can claim again instead of the effect being stuck.
        from backend.engine import ai
        try:
            body = ai.generate_text(
                "Write a short, warm client follow-up reminder. Plain text, 1-2 sentences, no markdown.",
                {"Name": row.get("Name", ""), "FollowUpDate": row.get("FollowUpDate", ""),
                 "ClientID": row.get("ClientID", "")},
            )
        except ai.GenerationError:
            journal.mark_applied(db, effect)
            raise
    else:
        raise ClientDataError(f"unknown template: {template_id}")
    draft = Draft(id=str(uuid.uuid4()), run_id=run_id, record_key=record_key,
                  body=body, lang="hi" if template_id.endswith("_hi") else "en",
                  destination=destination)
    db.add(draft)
    db.commit()
    journal.mark_applied(db, effect)
    audit.append(db, "effect.applied", {"effect_key": effect, "kind": "draft",
                                        "draft_id": draft.id, "run_id": run_id})
    db.commit()
    return {"skipped": False, "effect_key": effect, "draft_id": draft.id, "body": body}


def update_row_field(db: Session, *, run_id: str, alias: str, filename: str, key_field: str,
                     key_value: str, field: str, new_value: str, purpose: str,
                     effect_ns: str) -> dict:
    """Generic exactly-once keyed field update for any declared CSV resource (Phase 8).

    Same guarantees as update_status: per-resource RMW lock, journal claim BEFORE the
    write, staged atomic replace with backup, audit entry. Any keyed workflow reuses
    this instead of growing per-workflow copies of the effect path.
    """
    lock = _rmw_lock(alias, filename)
    with lock:
        current = safeio.read_resource(alias, filename).decode("utf-8-sig")
        effect = journal.effect_key(f"{key_field}:{key_value}", purpose, effect_ns, alias)
        if not journal.claim_effect(db, effect, run_id):
            return {"skipped": True, "reason": "idempotent-claimed", "effect_key": effect}
        reader = list(csv.reader(io.StringIO(current)))
        header, body = reader[0], reader[1:]
        try:
            ki = header.index(key_field)
            fi = header.index(field)
        except ValueError as exc:
            journal.mark_applied(db, effect)
            raise ClientDataError(f"missing column: {exc}") from exc
        updated = False
        prior_value = None
        for r in body:
            if r and len(r) > ki and r[ki] == key_value:
                if prior_value is None:
                    prior_value = r[fi]  # captured for honest rollback (roadmap §E)
                r[fi] = new_value
                updated = True
        if not updated:
            journal.mark_applied(db, effect)
            raise ClientDataError(f"row not found: {key_value}")
        out = io.StringIO()
        csv.writer(out).writerows([header, *body])
        result = safeio.write_resource(alias, filename, out.getvalue().encode("utf-8"), backup=True)
        journal.mark_applied(db, effect)
        audit.append(db, "effect.applied", {"effect_key": effect, "kind": "row_update",
                                            "sha256": result["sha256"], "run_id": run_id,
                                            "field": field, "filename": filename,
                                            "purpose": purpose,
                                            "prior": {"value": prior_value}})
        db.commit()
        return {"skipped": False, "effect_key": effect, **result}


def due_rows_from_fixture(db: Session, alias: str, filename: str, run_date: str = RUN_DATE) -> list[dict]:
    rows = read_table(alias, filename)
    return filter_due(rows, run_date)


def ensure_run_date_within_contract(run_date: str) -> None:
    date.fromisoformat(run_date)  # raises on malformed dates (fail-closed)
