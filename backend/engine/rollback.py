"""Roadmap Phase E: run rollback — honest, audited inverse of a run's effects.

Rules:
  - Row updates: `update_row_field` now records the prior value at claim time, so a
    rollback re-applies the INVERSE update (exactly-once via a rollback-purpose
    effect key — a rollback can itself never double-apply).
  - Drafts: drafts created by the run are removed (they are review items, not source
    data); each removal is audited with the draft id.
  - A run can only be rolled back once; a still-running run can never be rolled back.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.engine import journal, rows
from backend.models import AuditEntry, Draft, Run


def run_is_rolled_back(db: Session, run_id: str) -> bool:
    rows = db.scalars(select(AuditEntry).where(AuditEntry.kind == "run.rolled_back")).all()
    for e in rows:
        try:
            if json.loads(e.payload_json).get("run_id") == run_id:
                return True
        except Exception:
            continue
    return False


def rollback_run(db: Session, run_id: str) -> dict:
    run = db.get(Run, run_id)
    if run is None:
        raise ValueError("run not found")
    if run.status == "running":
        raise ValueError("cannot roll back a running run")
    if run_is_rolled_back(db, run_id):
        raise ValueError("run already rolled back")

    claims = journal.claims_for_run(db, run_id)
    restored_rows: list[str] = []
    removed_drafts: list[str] = []
    skipped: list[str] = []

    for claim in claims:
        # effect_key layout: {key_field}:{key_value}|{purpose}|{run_date}|{alias}
        # row-update purposes from the follow-up/compare workflows:
        purposes = ("followup-draft", "status_update", "row_update")
        # plan-built automations use an "auto-<id>" purpose (one per column they set)
        if not (any(f"|{p}|" in claim.effect_key for p in purposes) or "|auto-" in claim.effect_key):
            continue
        # find the audit entry that applied this effect (it carries the prior value)
        entry = None
        for e in db.scalars(select(AuditEntry).where(AuditEntry.kind == "effect.applied").order_by(AuditEntry.seq)):
            try:
                payload = json.loads(e.payload_json)
            except Exception:
                continue
            if payload.get("effect_key") == claim.effect_key and payload.get("kind") == "row_update":
                entry = payload
                break
        if entry is None or "prior" not in entry:
            skipped.append(claim.effect_key)
            continue
        prior = entry["prior"]
        # effect key layout: {key_field}:{key_value}|{purpose}|{run_date}|{alias}
        try:
            ident, _purpose, run_date, alias = claim.effect_key.split("|", 3)
            key_field, key_value = ident.split(":", 1)
            field = entry.get("field", "Status")
        except ValueError:
            skipped.append(claim.effect_key)
            continue
        res = rows.update_row_field(
            db, run_id=run_id, alias=alias, filename=entry.get("filename", "clients.csv"),
            key_field=key_field, key_value=key_value, field=field,
            new_value=prior.get("value", ""), purpose=f"rollback:{entry.get('purpose', 'row_update')}",
            effect_ns=run_date)
        if res.get("skipped"):
            skipped.append(claim.effect_key)
        else:
            restored_rows.append(key_value)

    drafts = list(db.scalars(select(Draft).where(Draft.run_id == run_id)))
    for d in drafts:
        db.delete(d)
        removed_drafts.append(d.record_key)
    if drafts:
        db.commit()

    from backend.security import audit as audit_mod
    summary = {"run_id": run_id, "restored_rows": restored_rows,
               "removed_drafts": removed_drafts, "skipped": skipped}
    audit_mod.append(db, "run.rolled_back", summary)
    db.commit()
    return summary
