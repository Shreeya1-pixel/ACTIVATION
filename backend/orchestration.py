"""Roadmap Phase D: runners, triggers, and calendar-validated scheduling.

README §7: paired runners pair identities, authenticate connections, and take
explicit consent before data leaves a device. README §5: schedules need real
calendar evidence — accelerated demo cycles can NEVER create one. Quota
enforcement uses a process's daily run quota (0 = unlimited).
"""
from __future__ import annotations

import json

import hashlib
import secrets
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Process, Runner, Run, RunParameter, Trigger, WorkflowVersion

# ── runners ──────────────────────────────────────────────────────────────────

def register_runner(db: Session, name: str, kind: str = "local",
                    org_id: str | None = None) -> Runner:
    if kind not in ("local", "paired"):
        raise ValueError("kind must be local|paired")
    r = Runner(id=secrets.token_hex(12), org_id=org_id, name=(name or "runner")[:160],
               kind=kind, status="registered")
    db.add(r)
    db.commit()
    return r


def begin_pairing(db: Session, runner_id: str) -> dict:
    """Paired-runner pairing: generate a one-time pairing code + identity keypair seed.
    The endpoint pairs only after presenting the code (README: pair identities)."""
    r = db.get(Runner, runner_id)
    if r is None or r.kind != "paired":
        raise ValueError("paired runner not found")
    code = "pair-" + secrets.token_urlsafe(18)
    fingerprint = hashlib.sha256(code.encode()).hexdigest()[:32]
    r.identity_pubkey = fingerprint
    db.commit()
    return {"runner_id": r.id, "pairing_code": code, "fingerprint": fingerprint,
            "note": "enter the code on the runner host; it must match the fingerprint shown there"}


def confirm_pairing(db: Session, runner_id: str, code: str) -> dict:
    r = db.get(Runner, runner_id)
    if r is None or r.kind != "paired":
        raise ValueError("paired runner not found")
    expected = r.identity_pubkey or ""
    if not code or hashlib.sha256(code.encode()).hexdigest()[:32] != expected:
        raise ValueError("pairing code does not match")
    r.status = "paired"
    r.last_seen_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    return {"runner_id": r.id, "status": r.status}


def revoke_runner(db: Session, runner_id: str) -> bool:
    r = db.get(Runner, runner_id)
    if r is None:
        return False
    r.status = "revoked"
    db.commit()
    return True


def list_runners(db: Session) -> list[Runner]:
    return list(db.scalars(select(Runner).order_by(Runner.created_at)))


# ── triggers ─────────────────────────────────────────────────────────────────

def create_trigger(db: Session, workflow_id: str, kind: str, config: dict,
                   evidence_note: str = "") -> tuple[Trigger, str | None]:
    """Create a trigger. Returns (row, webhook_secret_plaintext_or_None).

    Schedule triggers REQUIRE calendar evidence (README §5): at least 3 distinct
    observed dates, or an explicit user confirmation note. Demo cycles never qualify.
    """
    if kind not in ("webhook", "file", "schedule"):
        raise ValueError("kind must be webhook|file|schedule")
    if kind == "schedule":
        dates = config.get("observed_dates") or []
        confirmed = bool(config.get("user_confirmed"))
        distinct = sorted({str(d) for d in dates})
        if len(distinct) < 3 and not confirmed:
            raise ValueError(
                "schedule needs calendar evidence: 3+ distinct observed dates, or explicit "
                "user confirmation; accelerated demo cycles never create schedules")
        for pattern in ("interval_seconds", "cron"):
            if pattern in config:
                raise ValueError(f"schedule config may not use demo-cycle shortcut '{pattern}'")
    secret_plain = None
    secret_hash = None
    if kind == "webhook":
        secret_plain = "whk_" + secrets.token_urlsafe(24)
        secret_hash = hashlib.sha256(secret_plain.encode()).hexdigest()
    row = Trigger(id=secrets.token_hex(12), workflow_id=workflow_id, kind=kind,
                  config_json=json.dumps(config),
                  secret_hash=secret_hash, evidence_note=(evidence_note or "")[:500])
    db.add(row)
    db.commit()
    return row, secret_plain


def webhook_secret_matches(db: Session, trigger_id: str, secret: str) -> bool:
    row = db.get(Trigger, trigger_id)
    if row is None or row.kind != "webhook" or not row.secret_hash:
        return False
    return hashlib.sha256((secret or "").encode()).hexdigest() == row.secret_hash


def find_enabled_trigger(db: Session, kind: str, workflow_id: str | None = None) -> Trigger | None:
    q = select(Trigger).where(Trigger.kind == kind, Trigger.enabled == True)  # noqa: E712
    if workflow_id:
        q = q.where(Trigger.workflow_id == workflow_id)
    return db.scalar(q.order_by(Trigger.created_at).limit(1))


def list_triggers(db: Session) -> list[dict]:
    out = []
    for t in db.scalars(select(Trigger).order_by(Trigger.created_at)):
        out.append({"id": t.id, "workflow_id": t.workflow_id, "kind": t.kind,
                    "enabled": t.enabled, "config": __import__("json").loads(t.config_json),
                    "evidence_note": t.evidence_note,
                    "has_secret": t.secret_hash is not None})
    return out


def set_trigger_enabled(db: Session, trigger_id: str, enabled: bool) -> bool:
    t = db.get(Trigger, trigger_id)
    if t is None:
        return False
    t.enabled = bool(enabled)
    db.commit()
    return True


# ── run parameters (Phase E) ─────────────────────────────────────────────────

def declare_parameter(db: Session, version_id: str, name: str, param_type: str = "string",
                      required: bool = False, default=None) -> RunParameter:
    if param_type not in ("string", "number", "date"):
        raise ValueError("param_type must be string|number|date")
    row = RunParameter(id=secrets.token_hex(12), version_id=version_id, name=name[:80],
                       param_type=param_type, required=bool(required),
                       default_json=__import__("json").dumps(default))
    db.add(row)
    db.commit()
    return row


def validate_run_params(db: Session, version_id: str, supplied: dict) -> dict:
    """Validate supplied params against declared ones. Unknown params rejected;
    required missing params rejected; types coerced. Defaults fill the rest."""
    import json as _json
    declared = list(db.scalars(select(RunParameter).where(RunParameter.version_id == version_id)))
    resolved: dict[str, object] = {}
    known = {p.name for p in declared}
    for k in supplied:
        if k not in known:
            raise ValueError(f"unknown parameter: {k}")
    for p in declared:
        if p.name in supplied:
            val = supplied[p.name]
        else:
            val = _json.loads(p.default_json)
            if val is None:
                if p.required:
                    raise ValueError(f"missing required parameter: {p.name}")
                continue
        if p.param_type == "number":
            val = float(val)
        elif p.param_type == "date":
            date.fromisoformat(str(val))
            val = str(val)
        else:
            val = str(val)[:500]
        resolved[p.name] = val
    return resolved


# ── process quota ────────────────────────────────────────────────────────────

def process_quota_ok(db: Session, workflow_id: str) -> tuple[bool, str]:
    """Check the owning process's daily run quota (0 = unlimited)."""
    import json as _json
    from backend.models import Setting
    row = db.get(Setting, f"workflow_process:{workflow_id}")
    if row is None:
        return True, ""
    try:
        proc_id = _json.loads(row.value_json)
    except Exception:
        proc_id = row.value_json
    proc = db.get(Process, proc_id)
    if proc is None or proc.run_quota_per_day <= 0:
        return True, ""
    today = datetime.now(timezone.utc).date().isoformat()
    # count today's runs for all workflows attached to this process
    ids = [k.split(":", 1)[1] for k, v in db.query(Setting.key, Setting.value_json)
           .filter(Setting.key.like("workflow_process:%"), Setting.value_json == _json.dumps(proc.id)).all()]
    count = 0
    for wid in ids:
        vs = list(db.scalars(select(WorkflowVersion.id).where(WorkflowVersion.workflow_id == wid)))
        if not vs:
            continue
        count += (db.query(Run).filter(Run.version_id.in_(vs), Run.started_at >= today).count())
    if count >= proc.run_quota_per_day:
        return False, f"process '{proc.name}' reached its daily run quota ({proc.run_quota_per_day})"
    return True, ""
