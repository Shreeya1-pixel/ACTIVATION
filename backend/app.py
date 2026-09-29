"""AutoStack spike worker: FastAPI on loopback :8747, token-authenticated (S3).

Serves both transports the S4 spike needs:
  - /api/runs (direct run: worker executes the compiled graph itself)
  - /api/nodes/* (bridge callbacks the Node-RED custom nodes call)
Both call the SAME engine core in backend/engine/rows.py.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select as sa_select, text as _sqltext
from sqlalchemy.orm import Session

from backend import spike_config as cfg
from backend.db import engine as db_engine, get_db
from backend.engine import journal, preflight, rows
from backend.engine.catalog import validate_graph
from backend.models import (AuditEntry, Candidate, Draft, Event, Run, RunNodeRecord,
                            Setting, Workflow, WorkflowVersion, Base)
from backend.security import audit as audit_mod
from backend.security import pii, signing
from backend.security.safeio import sha256_bytes, write_resource
from backend.security.tokens import require_token, require_writer, require_tester, require_publisher
from backend import validate_events as phase1_validate
from backend.roadmap_routes import router as roadmap_router

Base.metadata.create_all(db_engine)

# Runtime indexes for hot filter columns (additive; idempotent for existing DBs
# where create_all cannot ALTER). Queries filter workflow_id/run_id/plan_id/slug
# on every run, listing, and registry lookup.
with db_engine.begin() as _conn:
    for _idx, _tbl, _col in (
        ("ix_workflow_versions_workflow_id", "workflow_versions", "workflow_id"),
        ("ix_runs_version_id", "runs", "version_id"),
        ("ix_run_node_records_run_id", "run_node_records", "run_id"),
        ("ix_generated_artifacts_plan_id", "generated_artifacts", "plan_id"),
        ("ix_registry_templates_slug", "registry_templates", "slug"),
        ("ix_registry_events_template_id", "registry_events", "template_id"),
        ("ix_triggers_workflow_id", "triggers", "workflow_id"),
        ("ix_memberships_org_id", "memberships", "org_id"),
        ("ix_review_gates_run_id", "review_gates", "run_id"),
    ):
        _conn.execute(_sqltext(
            f"CREATE INDEX IF NOT EXISTS {_idx} ON {_tbl}({_col})"))

# Ensure sample tracking CSV and default built-in workflow exist
_sample_target = cfg.DATA_DIR / "resources" / "sample-tracking-file" / "clients.csv"
if not _sample_target.is_file() and (cfg.FIXTURES_DIR / "clients-before.csv").is_file():
    _sample_target.parent.mkdir(parents=True, exist_ok=True)
    _sample_target.write_bytes((cfg.FIXTURES_DIR / "clients-before.csv").read_bytes())

with Session(db_engine) as _init_db:
    if _init_db.get(Workflow, "wf_client_followup") is None:
        _wf = Workflow(id="wf_client_followup", name="Client Follow-up (spike)", demo=True)
        _init_db.add(_wf)
        _graph = {
            "id": "wf_client_followup",
            "name": "Client Follow-up (spike)",
            "triggers": [{"type": "schedule", "cron": "0 9 * * MON-FR"}],
            "nodes": [
                {"id": "src", "type": "file.read_table", "params": {"alias": "sample-tracking-file", "max_rows": 1000}},
                {"id": "due", "type": "data.filter", "params": {"from": "src.rows", "where": "due"}},
                {"id": "note", "type": "notify.desktop", "params": {"title_key": "run_done"}},
            ],
            "edges": [{"from": "src", "to": "due"}, {"from": "due", "to": "note"}],
        }
        _canonical = json.dumps(_graph, sort_keys=True)
        _artifact = sha256_bytes(_canonical.encode())
        _init_db.add(WorkflowVersion(
            id=str(uuid.uuid4()),
            workflow_id="wf_client_followup",
            version=1,
            graph_json=_canonical,
            artifact_sha256=_artifact,
            changelog="Initial built-in workflow",
        ))
        _init_db.commit()

# Additive migration for the context model (product §5): existing databases
# predate processes.org_type/size/department/process_type. create_all cannot
# ALTER, so add any missing columns idempotently (legacy rows keep '' meaning
# "unclassified").
with db_engine.begin() as _conn:
    _existing = {row[1] for row in _conn.execute(_sqltext("PRAGMA table_info(processes)"))}
    for _col, _ddl in (
        ("org_type", "VARCHAR(24) NOT NULL DEFAULT ''"),
        ("size", "VARCHAR(16) NOT NULL DEFAULT ''"),
        ("department", "VARCHAR(40) NOT NULL DEFAULT ''"),
        ("process_type", "VARCHAR(40) NOT NULL DEFAULT ''"),
    ):
        if _col not in _existing:
            _conn.execute(_sqltext(f"ALTER TABLE processes ADD COLUMN {_col} {_ddl}"))
    # Legacy registry rows get empty signatures and are refused at import until republished.
    _existing = {row[1] for row in _conn.execute(_sqltext("PRAGMA table_info(registry_templates)"))}
    for _col, _ddl in (
        ("permissions_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("signature", "TEXT NOT NULL DEFAULT ''"),
        ("signer_pubkey", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ):
        if _existing and _col not in _existing:
            _conn.execute(_sqltext(f"ALTER TABLE registry_templates ADD COLUMN {_col} {_ddl}"))

app = FastAPI(title="AutoStack spike worker", version="0.1.0")
app.include_router(roadmap_router)
from backend.practice import router as practice_router  # noqa: E402
app.include_router(practice_router)


@app.middleware("http")
async def body_size_limit(request, call_next):  # noqa: ANN001
    """Roadmap hardening (QA bug #10): reject oversized request bodies with 413.
    All real payloads (plans, callbacks, staging) are tiny JSON; 1 MB is ~500× headroom."""
    max_bytes = 1_000_000
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > max_bytes:
        from fastapi.responses import JSONResponse as _JR
        return _JR(status_code=413, content={"error": "request body too large",
                                             "limit_bytes": max_bytes})
    return await call_next(request)

# CORS: allow the Vite dev servers locally, plus any origins listed in ALLOWED_ORIGINS
# (comma-separated). Set ALLOWED_ORIGINS=https://<frontend>.up.railway.app on Railway.
import os as _os
_default_origins = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:4173", "http://127.0.0.1:4173",
]
_extra = [o.strip() for o in _os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── health & spike primitives ────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "autostack-worker", "ts": now_iso()}


class PingBody(BaseModel):
    note: str = ""


@app.post("/api/ping", dependencies=[Depends(require_token)])
def ping(body: PingBody, db: Session = Depends(get_db)):
    """Spike S2 target: one settings row + one audit-chain entry per call."""
    setting = db.get(Setting, "last_ping")
    payload = json.dumps({"note": body.note, "ts": now_iso()})
    if setting is None:
        db.add(Setting(key="last_ping", value_json=payload))
    else:
        setting.value_json = payload
    db.commit()
    audit_mod.append(db, "spike.ping", {"note": body.note})
    db.commit()
    return {"pong": True, "audited": True}


class StageBody(BaseModel):
    fixture: str          # e.g. "clients-before.csv" (from tests/fixtures) or "reset"
    as_filename: str = "clients.csv"


@app.post("/api/resources/stage", dependencies=[Depends(require_writer)])
def stage_resource(body: StageBody, db: Session = Depends(get_db)):
    """Stage a fixture into the sample-tracking-file alias (simulates the user's tracked file)."""
    if body.fixture == "reset":
        # A demo reset must restore a reproducible state: tracking file back to the fixture
        # AND run-scoped state cleared (journal claims, drafts, runs). Audit history stays
        # append-only — it is never deleted.
        from backend.models import Draft, IdempotencyClaim, ReviewGate, Run, RunNodeRecord
        from backend.models import Setting as _Setting
        for model in (RunNodeRecord, IdempotencyClaim, Draft, ReviewGate, Run):
            deleted = db.query(model).delete()
            if deleted:
                audit_mod.append(db, "spike.reset", {"cleared": model.__tablename__, "rows": deleted})
        # run-scoped context rows go with the runs they describe
        cleared_ctx = db.query(_Setting).filter(_Setting.key.like("run_context:%")).delete()
        if cleared_ctx:
            audit_mod.append(db, "spike.reset", {"cleared": "run_context keys", "rows": cleared_ctx})
        reset = (cfg.FIXTURES_DIR / "clients-before.csv").read_bytes()
    else:
        path = (cfg.FIXTURES_DIR / body.fixture)
        if not path.is_file() or path.suffix != ".csv" or "/" in body.fixture or ".." in body.fixture:
            raise HTTPException(status_code=400, detail={"error": "unknown fixture"})
        reset = path.read_bytes()
    try:
        result = write_resource("sample-tracking-file", body.as_filename, reset, backup=False)
    except PermissionError as exc:
        # unsafe filename / traversal — a client error, not a server error (QA finding)
        msg = str(exc)
        if msg.startswith("unsafe filename:"):
            msg = msg.split(":", 1)[1].strip()
        raise HTTPException(status_code=400, detail={"error": f"unsafe filename: {msg}"}) from exc
    audit_mod.append(db, "resource.staged", {"fixture": body.fixture, "sha256": result["sha256"]})
    db.commit()
    return {"staged": True, **result}


# ─── workflows ────────────────────────────────────────────────────────────────
class WorkflowBody(BaseModel):
    id: str
    name: str
    graph: dict


@app.post("/api/workflows", dependencies=[Depends(require_writer)])
def save_workflow(body: WorkflowBody, db: Session = Depends(get_db)):
    errors = validate_graph(body.graph)
    if errors:
        return JSONResponse(status_code=422, content={"validation_errors": errors})
    canonical = json.dumps(body.graph, sort_keys=True, separators=(",", ":"))
    artifact = hashlib.sha256(canonical.encode()).hexdigest()
    wf = db.get(Workflow, body.id)
    if wf is not None and wf.deleted_at is not None:
        # QA round 7: saving into a soft-deleted id must NOT silently resurrect it
        # (that would bypass the owner-only delete gate). Recreating requires a new id.
        raise HTTPException(status_code=409, detail={
            "error": "workflow id belongs to a deleted workflow; history is retained",
            "how_to_unlock": "choose a different workflow id"})
    if wf is None:
        wf = Workflow(id=body.id, name=body.name)
        db.add(wf)
        wf.name = body.name
    else:
        wf.name = body.name
    version = (db.query(WorkflowVersion)
               .filter(WorkflowVersion.workflow_id == body.id)
               .order_by(WorkflowVersion.version.desc()).first())
    vnext = (version.version + 1) if version else 1
    db.add(WorkflowVersion(id=str(uuid.uuid4()), workflow_id=body.id, version=vnext,
                           graph_json=canonical, artifact_sha256=artifact,
                           changelog=f"spike save {now_iso()}"))
    db.commit()
    audit_mod.append(db, "workflow.saved", {"workflow_id": body.id, "version": vnext,
                                            "artifact_sha256": artifact})
    db.commit()
    return {"workflow_id": body.id, "version": vnext, "artifact_sha256": artifact}


@app.get("/api/workflows/{workflow_id}", dependencies=[Depends(require_token)])
def get_workflow(workflow_id: str, db: Session = Depends(get_db)):
    wf = db.get(Workflow, workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail={"error": "not found"})
    version = (db.query(WorkflowVersion)
               .filter(WorkflowVersion.workflow_id == workflow_id)
               .order_by(WorkflowVersion.version.desc()).first())
    return {"id": wf.id, "name": wf.name, "version": version.version,
            "graph": json.loads(version.graph_json), "artifact_sha256": version.artifact_sha256}


# ─── runs (direct runner + bridge control) ────────────────────────────────────
class RunBody(BaseModel):
    workflow_id: str
    run_date: str = cfg.RUN_DATE
    filename: str = "clients.csv"
    dry_run: bool = False          # roadmap §E: compute effects, apply nothing
    params: dict = {}              # roadmap §E: declared run parameters (approved scope)


def _node_record(db: Session, run_id: str, seq: int, node_id: str, status: str,
                 input_obj, output_obj, error: str | None = None,
                 ms: int | None = None) -> RunNodeRecord:
    def digest(obj) -> str | None:
        if obj is None:
            return None
        return sha256_bytes(json.dumps(obj, sort_keys=True, default=str).encode())[:64]
    rec = RunNodeRecord(id=str(uuid.uuid4()), run_id=run_id, node_id=node_id, seq=seq,
                        status=status, input_digest=digest(input_obj), output_digest=digest(output_obj),
                        error=error, ms=ms or 0)
    db.add(rec)
    return rec


@app.post("/api/runs", dependencies=[Depends(require_writer)])
def start_run(body: RunBody, db: Session = Depends(get_db)):
    """Run-now. Compiled-graph versions execute via the graph executor (plan-driven);
    legacy spike versions keep the original direct-runner behavior."""
    version = (db.query(WorkflowVersion)
               .filter(WorkflowVersion.workflow_id == body.workflow_id)
               .order_by(WorkflowVersion.version.desc()).first())
    if version is None:
        raise HTTPException(status_code=404, detail={"error": "workflow not found"})
    try:
        rows.ensure_run_date_within_contract(body.run_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": f"invalid run_date: {exc}"}) from exc
    version_payload = json.loads(version.graph_json)
    if isinstance(version_payload, dict) and "graph" in version_payload:
        return _start_run_graph(db, version, version_payload["graph"], body)
    # Roadmap fix: user-authored graphs stored bare (POST /api/workflows) must run
    # as authored — not silently fall into the legacy runner.
    if isinstance(version_payload, dict) and "nodes" in version_payload:
        return _start_run_graph(db, version, version_payload, body)
    return _start_run_legacy(db, version, body)


def _is_client_error(exc: BaseException) -> bool:
    """Client-caused run failures (bad file contents, data-contract violations) are
    400, not 500 (QA findings).

    Node errors are re-raised as RuntimeError with the original exception chained,
    so walk the __cause__/__context__ chain for fixture/data-contract violations.
    """
    from backend.engine.rows import ClientDataError
    from backend.file_diff import InvalidFixture
    e, seen = exc, 0
    while e is not None and seen < 5:
        if isinstance(e, (InvalidFixture, ClientDataError, FileNotFoundError)):
            return True
        e = e.__cause__ or e.__context__
        seen += 1
    return False


def _start_run_graph(db: Session, version: WorkflowVersion, graph: dict,
                     body: RunBody) -> dict:
    from backend.models import GenerationPlan
    plan_row = (db.query(GenerationPlan)
                .filter(GenerationPlan.plan_sha256 == version_payload_plan_hash(version))
                .first()) if version_payload_plan_hash(version) else None
    plan = json.loads(plan_row.plan_json) if plan_row else {}
    # Roadmap safety: a stored graph that no longer validates must fail CLEANLY
    # (422 + recovery hint), never an opaque 500 (QA round-2 stale-state finding).
    graph_errors = validate_graph(graph)
    if graph_errors:
        run = Run(id=str(uuid.uuid4()), version_id=version.id, trigger_type="manual", status="failed")
        run.error = "stored graph invalid; re-bind the workflow from its plan"
        db.add(run)
        db.commit()
        raise HTTPException(status_code=422, detail={
            "error": "stored graph invalid; re-bind the workflow from its plan",
            "validation_errors": graph_errors, "run_id": run.id})
    # Declared run parameters are validated against the approved scope (roadmap §E).
    try:
        from backend import orchestration as _orch
        resolved_params = _orch.validate_run_params(db, version.id, body.params or {})
        ok_q, why_q = _orch.process_quota_ok(db, body.workflow_id)
        if not ok_q:
            raise HTTPException(status_code=429, detail={"error": why_q})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    pre = preflight.check(graph, body.filename)
    if not pre["ok"]:
        run = Run(id=str(uuid.uuid4()), version_id=version.id, trigger_type="manual", status="failed")
        run.error = "preflight stopped the run before any effect: " + "; ".join(pre["problems"])[:400]
        run.ended_at = datetime.now(timezone.utc)
        db.add(run)
        db.commit()
        _node_record(db, run.id, 1, "preflight", "failed", pre["checked"], None,
                     error="; ".join(pre["problems"])[:500])
        db.commit()
        audit_mod.append(db, "run.preflight_failed", {"run_id": run.id,
                                                      "workflow_id": body.workflow_id,
                                                      "problems": pre["problems"]})
        db.commit()
        raise HTTPException(status_code=400, detail={
            "error": "preflight stopped the run, nothing was changed: " + "; ".join(pre["problems"])[:300],
            "problems": pre["problems"], "checked": pre["checked"], "run_id": run.id,
            "handoff": "do this task by hand today, then re-bind or re-approve the workflow"})
    run = Run(id=str(uuid.uuid4()), version_id=version.id, trigger_type="manual", status="running")
    db.add(run)
    db.commit()
    try:
        result = _exec_graph(db, run, graph, plan, body.run_date, body.filename,
                             dry_run=body.dry_run, params=resolved_params)
        if body.dry_run:
            run.status = "dry_run"
            run.error = None
        else:
            run.status = "passed"
        run.ended_at = datetime.now(timezone.utc)
        db.commit()
        audit_mod.append(db, "run.completed", {"run_id": run.id, "status": run.status,
                                               "dry_run": body.dry_run, **result})
        db.commit()
        out = {"run_id": run.id, "status": run.status, "dry_run": body.dry_run, **result}
        if plan_row is not None:
            out["file"] = _write_artifact(plan_row.id, f"{'dry_run' if body.dry_run else 'live_run'}_{run.id[:8]}.json",
                                          json.dumps(out, indent=2, default=str))
        return out
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)[:500]
        run.ended_at = datetime.now(timezone.utc)
        db.commit()
        _status = 400 if _is_client_error(exc) else 500
        raise HTTPException(status_code=_status,
                            detail={"error": str(exc)[:200], "run_id": run.id})


class PreflightBody(BaseModel):
    workflow_id: str
    filename: str = "clients.csv"


@app.post("/api/runs/preflight", dependencies=[Depends(require_token)])
def preflight_route(body: PreflightBody, db: Session = Depends(get_db)):
    """Read-only check that a workflow's files and columns still match; writes nothing."""
    version = (db.query(WorkflowVersion)
               .filter(WorkflowVersion.workflow_id == body.workflow_id)
               .order_by(WorkflowVersion.version.desc()).first())
    if version is None:
        raise HTTPException(status_code=404, detail={"error": "workflow not found"})
    payload = json.loads(version.graph_json)
    graph = payload.get("graph") if isinstance(payload, dict) and "graph" in payload else payload
    if not isinstance(graph, dict) or "nodes" not in graph:
        raise HTTPException(status_code=422, detail={"error": "workflow has no graph to check"})
    return preflight.check(graph, body.filename)


def _dry_run_status_note() -> str:
    return "dry_run runs compute effects without applying them; no journal claims are consumed"


@app.post("/api/runs/{run_id}/rollback", dependencies=[Depends(require_writer)])
def rollback_run_route(run_id: str, db: Session = Depends(get_db)):
    """Roadmap §E: honest inverse of a run's applied effects.

    Row updates are restored from the prior values captured at effect time; drafts
    from the run are removed. The rollback itself is exactly-once and audited.
    """
    from backend.engine.rollback import rollback_run
    try:
        summary = rollback_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
    return {"run_id": run_id, **summary}


def version_payload_plan_hash(version: WorkflowVersion) -> str | None:
    try:
        payload = json.loads(version.graph_json)
        return payload.get("plan_sha256") if isinstance(payload, dict) else None
    except Exception:
        return None


def _start_run_legacy(db: Session, version: WorkflowVersion, body: RunBody) -> dict:
    run = Run(id=str(uuid.uuid4()), version_id=version.id, trigger_type="manual", status="running")
    db.add(run)
    db.commit()

    seq = 0
    try:
        table = rows.read_table("sample-tracking-file", body.filename)
        seq += 1; _node_record(db, run.id, seq, "file.read_table", "passed",
                               {"filename": body.filename}, {"count": len(table)}); db.commit()
        due = rows.filter_due(table, body.run_date)
        seq += 1; _node_record(db, run.id, seq, "data.filter", "passed",
                               {"rows": len(table)}, {"due": [r["ClientID"] for r in due]}); db.commit()
        updated, drafted, skipped = [], [], []
        for row in due:
            rec_key = f"sample:{row['ClientID']}"
            u = rows.update_status(db, run_id=run.id, alias="sample-tracking-file",
                                   filename=body.filename, row=row, new_status="Draft prepared",
                                   purpose="followup", run_date=body.run_date)
            (skipped if u.get("skipped") else updated).append(row["ClientID"])
            d = rows.create_draft(db, run_id=run.id, record_key=rec_key, row=row,
                                  template_id="followup_en", destination="in_app",
                                  run_date=body.run_date)
            (skipped if d.get("skipped") else drafted).append(rec_key)
        seq += 1; _node_record(db, run.id, seq, "file.update_rows", "passed",
                               {"due": [r["ClientID"] for r in due]},
                               {"updated": updated, "skipped": skipped}); db.commit()
        seq += 1; _node_record(db, run.id, seq, "draft.create", "passed",
                               {"due": [r["ClientID"] for r in due]},
                               {"drafted": drafted, "skipped": skipped}); db.commit()
        seq += 1; _node_record(db, run.id, seq, "notify.desktop", "passed",
                               {"drafted": len(drafted)}, {"notified": True}); db.commit()
        run.status = "passed"
        run.ended_at = datetime.now(timezone.utc)
        db.commit()
        audit_mod.append(db, "run.completed", {"run_id": run.id, "status": "passed",
                                               "updated": updated, "drafted": drafted,
                                               "skipped": skipped})
        db.commit()
        return {"run_id": run.id, "status": "passed", "updated": updated,
                "drafted": drafted, "skipped": skipped}
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)[:500]
        run.ended_at = datetime.now(timezone.utc)
        seq += 1
        _node_record(db, run.id, seq, "error", "failed", None, None, str(exc)[:500])
        db.commit()
        _status = 400 if _is_client_error(exc) else 500
        raise HTTPException(status_code=_status,
                            detail={"error": str(exc)[:200], "run_id": run.id})


class BridgeStartBody(BaseModel):
    workflow_id: str
    run_date: str = cfg.RUN_DATE


@app.post("/api/runs/{run_id}/cancel", dependencies=[Depends(require_writer)])
def cancel_run(run_id: str, db: Session = Depends(get_db)):
    """Phase 7: cancel a running job. Already-applied effects are NEVER undone
    silently — they are reported so recovery is clearly scoped."""
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"error": "run not found"})
    if run.status in {"passed", "failed", "cancelled"}:
        return {"run_id": run.id, "status": run.status,
                "note": "already finished; nothing to cancel"}
    run.status = "cancelled"
    run.ended_at = datetime.now(timezone.utc)
    db.commit()
    claims = journal.claims_for_run(db, run_id)
    applied = [c.effect_key for c in claims if c.applied]
    audit_mod.append(db, "run.cancelled", {"run_id": run_id,
                                           "effects_already_applied": len(applied)})
    db.commit()
    return {"run_id": run.id, "status": "cancelled",
            "effects_already_applied": applied,
            "note": "completed effects are kept; the journal records them"}


@app.post("/api/runs/reconcile", dependencies=[Depends(require_writer)])
def reconcile_runs(db: Session = Depends(get_db)):
    """Phase 7 restart reconciliation: runs stuck in 'running' after a crash are
    closed as 'failed' (never silently passed); applied effects stay journaled."""
    stuck = db.query(Run).filter(Run.status == "running").all()
    closed = []
    for run in stuck:
        run.status = "failed"
        run.error = "reconciled after restart: process did not report completion"
        run.ended_at = datetime.now(timezone.utc)
        closed.append(run.id)
    db.commit()
    if closed:
        audit_mod.append(db, "runs.reconciled", {"closed": closed})
        db.commit()
    return {"reconciled": len(closed), "run_ids": closed}


@app.post("/api/runs/bridge-start", dependencies=[Depends(require_writer)])
def bridge_start(body: BridgeStartBody, db: Session = Depends(get_db)):
    """Transport B: Node-RED drives the nodes; worker owns the run row + effects."""
    version = (db.query(WorkflowVersion)
               .filter(WorkflowVersion.workflow_id == body.workflow_id)
               .order_by(WorkflowVersion.version.desc()).first())
    if version is None:
        raise HTTPException(status_code=404, detail={"error": "workflow not found"})
    try:
        rows.ensure_run_date_within_contract(body.run_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": f"invalid run_date: {exc}"}) from exc
    run = Run(id=str(uuid.uuid4()), version_id=version.id, trigger_type="inject", status="running")
    db.add(run)
    db.commit()
    audit_mod.append(db, "run.bridge-started", {"run_id": run.id, "workflow_id": body.workflow_id})
    db.commit()
    return {"run_id": run.id, "run_date": body.run_date}


class NodeCallback(BaseModel):
    run_id: str
    filename: str = "clients.csv"
    record_key: str | None = None
    template_id: str = "followup_en"
    destination: str = "in_app"
    title: str = "AutoStack run finished"
    note: dict | None = None
    status: str = "passed"
    error: str | None = None


@app.post("/api/nodes/read-due", dependencies=[Depends(require_writer)])
def node_read_due(cb: NodeCallback, db: Session = Depends(get_db)):
    table = rows.read_table("sample-tracking-file", cb.filename)
    due = rows.filter_due(table, cfg.RUN_DATE)
    seq = (db.query(RunNodeRecord).filter(RunNodeRecord.run_id == cb.run_id).count()) + 1
    _node_record(db, cb.run_id, seq, "file.read_table+data.filter", "passed",
                 {"filename": cb.filename}, {"due": [r["ClientID"] for r in due]})
    db.commit()
    return {"due": due}


@app.post("/api/nodes/update-row", dependencies=[Depends(require_writer)])
def node_update_row(cb: NodeCallback, db: Session = Depends(get_db)):
    row = {"ClientID": (cb.record_key or "").removeprefix("sample:")}
    if not row["ClientID"]:
        raise HTTPException(status_code=400, detail={"error": "record_key required"})
    result = rows.update_status(db, run_id=cb.run_id, alias="sample-tracking-file",
                                filename=cb.filename, row=row, new_status="Draft prepared",
                                purpose="followup", run_date=cfg.RUN_DATE)
    seq = (db.query(RunNodeRecord).filter(RunNodeRecord.run_id == cb.run_id).count()) + 1
    _node_record(db, cb.run_id, seq, "file.update_rows", "passed",
                 {"record_key": cb.record_key}, result)
    db.commit()
    return result


@app.post("/api/nodes/draft-create", dependencies=[Depends(require_writer)])
def node_draft_create(cb: NodeCallback, db: Session = Depends(get_db)):
    if not cb.record_key:
        raise HTTPException(status_code=400, detail={"error": "record_key required"})
    client_id = cb.record_key.removeprefix("sample:")
    row = {"ClientID": client_id, "Name": f"Sample Client {client_id}", "FollowUpDate": cfg.RUN_DATE}
    result = rows.create_draft(db, run_id=cb.run_id, record_key=cb.record_key, row=row,
                               template_id=cb.template_id, destination=cb.destination,
                               run_date=cfg.RUN_DATE)
    seq = (db.query(RunNodeRecord).filter(RunNodeRecord.run_id == cb.run_id).count()) + 1
    _node_record(db, cb.run_id, seq, "draft.create", "passed",
                 {"record_key": cb.record_key}, result)
    db.commit()
    return result


@app.post("/api/nodes/notify", dependencies=[Depends(require_writer)])
def node_notify(cb: NodeCallback, db: Session = Depends(get_db)):
    audit_mod.append(db, "notify.desktop", {"title": cb.title, "redacted": True})
    db.commit()
    seq = (db.query(RunNodeRecord).filter(RunNodeRecord.run_id == cb.run_id).count()) + 1
    _node_record(db, cb.run_id, seq, "notify.desktop", "passed", {"title": cb.title}, {"notified": True})
    db.commit()
    return {"notified": True}


@app.post("/api/runs/{run_id}/complete", dependencies=[Depends(require_writer)])
def bridge_complete(run_id: str, cb: NodeCallback, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"error": "run not found"})
    run.status = cb.status if cb.status in {"passed", "failed", "cancelled"} else "failed"
    run.error = cb.error
    run.ended_at = datetime.now(timezone.utc)
    db.commit()
    audit_mod.append(db, "run.completed", {"run_id": run.id, "status": run.status, "transport": "bridge"})
    db.commit()
    return {"run_id": run.id, "status": run.status}


@app.get("/api/runs/list", dependencies=[Depends(require_token)])
def list_runs(db: Session = Depends(get_db)):
    runs = (db.query(Run).order_by(Run.started_at.desc()).limit(100).all())
    versions = {v.id: v for v in db.query(WorkflowVersion).all()}
    out = []
    for r in runs:
        v = versions.get(r.version_id)
        out.append({"id": r.id, "workflow_id": v.workflow_id if v else None,
                    "status": r.status, "trigger": r.trigger_type,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                    "error": r.error, "measured_ms": r.measured_ms})
    return {"runs": out}

@app.get("/api/runs/last", dependencies=[Depends(require_token)])
def get_last_run(db: Session = Depends(get_db)):
    """Newest run regardless of state — the bridge failure path uses this to close a run
    whose id it never learned (e.g. bridge-start itself threw before returning an id)."""
    run = db.query(Run).order_by(Run.started_at.desc()).first()
    if run is None:
        return {"run_id": None}
    return {"run_id": run.id, "status": run.status}


@app.get("/api/runs/{run_id}", dependencies=[Depends(require_token)])
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"error": "run not found"})
    records = (db.query(RunNodeRecord).filter(RunNodeRecord.run_id == run_id)
               .order_by(RunNodeRecord.seq).all())
    claims = journal.claims_for_run(db, run_id)
    drafts = db.query(Draft).filter(Draft.run_id == run_id).all()
    return {
        "run_id": run.id, "status": run.status, "error": run.error,
        "nodes": [{"node_id": r.node_id, "seq": r.seq, "status": r.status,
                   "error": r.error} for r in records],
        "journal": [{"effect_key": c.effect_key, "applied": c.applied} for c in claims],
        "drafts": [{"id": d.id, "record_key": d.record_key, "body": d.body} for d in drafts],
    }


# ─── events + candidates (S5) + audit ─────────────────────────────────────────
@app.post("/api/events", dependencies=[Depends(require_writer)])
def ingest_events(body: list[dict], db: Session = Depends(get_db)):
    from backend.capture.ingest import store_events
    try:
        phase1_validate.validate_events(body)  # reuse the Phase 1 validator as-is
        accepted = store_events(db, body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc)[:300]})
    # Phase 4: real events immediately recompute evidence-based candidates + notifications.
    from backend.detection.service import refresh_from_events
    detection = refresh_from_events(db)
    return {"accepted": len(accepted), "duplicates_skipped": len(body) - len(accepted),
            "detection": detection}


@app.get("/api/candidates", dependencies=[Depends(require_token)])
def list_candidates(db: Session = Depends(get_db)):
    cands = db.query(Candidate).order_by(Candidate.last_seen).all()
    return [{"id": c.id, "status": c.status, "occurrences": c.occurrences,
             "pattern": json.loads(c.pattern_json),
             "evidence": json.loads(c.evidence_json)} for c in cands]


@app.get("/api/notifications", dependencies=[Depends(require_token)])
def list_notifications(db: Session = Depends(get_db)):
    from backend.models import Notification
    notes = db.query(Notification).order_by(Notification.created_at.desc()).all()
    return [{"id": n.id, "candidate_id": n.candidate_id, "title": n.title,
             "body": n.body, "read_at": n.read_at, "created_at": n.created_at}
            for n in notes]


@app.post("/api/notifications/{notification_id}/read", dependencies=[Depends(require_token)])
def mark_notification_read(notification_id: str, db: Session = Depends(get_db)):
    from backend.models import Notification
    note = db.get(Notification, notification_id)
    if note is None:
        raise HTTPException(status_code=404, detail={"error": "not found"})
    note.read_at = now_iso()
    db.commit()
    return {"id": note.id, "read_at": note.read_at}


# ─── capture: watcher pass over the configured folder ─────────────────────────
_WATCHER = None
_WATCHER_FOLDER: str | None = None


def _capture_watcher():
    """The watcher's baseline must persist across polls (a fresh instance treats every
    file as first sight), so it is rebuilt only when the watched folder changes."""
    global _WATCHER, _WATCHER_FOLDER
    from backend.capture import config as capture_config
    from backend.capture.watcher import FolderWatcher
    folder = capture_config.folder()
    if folder == capture_config.DEFAULT_FOLDER:
        folder.mkdir(parents=True, exist_ok=True)
    if _WATCHER is None or _WATCHER_FOLDER != str(folder):
        _WATCHER = FolderWatcher(folder, alias="watched", settle_seconds=0.5,
                                 settings=lambda name: capture_config.file_settings(capture_config.load(), name))
        _WATCHER_FOLDER = str(folder)
    return _WATCHER


class CaptureConfigBody(BaseModel):
    folder: str | None = None
    files: dict | None = None


@app.get("/api/capture/config", dependencies=[Depends(require_token)])
def capture_config_get():
    from backend.capture import config as capture_config
    c = capture_config.load()
    return {"folder": str(capture_config.folder(c)), "custom_folder": bool(c.get("folder")),
            "files": c.get("files") or {}}


@app.post("/api/capture/config", dependencies=[Depends(require_publisher)])
def capture_config_set(body: CaptureConfigBody, db: Session = Depends(get_db)):
    """Owner-only: point the watcher at another folder and/or set per-file ID and tracked
    columns. An empty folder string resets to the built-in sample folder."""
    from backend.capture import config as capture_config
    try:
        c = capture_config.save(body.folder, body.files)
    except capture_config.CaptureConfigError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc
    audit_mod.append(db, "capture.config_changed", {"custom_folder": bool(c.get("folder")),
                                                    "files": sorted((c.get("files") or {}).keys())})
    db.commit()
    return {"folder": str(capture_config.folder(c)), "files": c.get("files") or {}}


@app.get("/api/capture/preview", dependencies=[Depends(require_token)])
def capture_preview():
    """What the watcher would read in the current folder: per file, the header, the ID
    column in use (configured or suggested), row counts and any reason it cannot be read.
    Column names only — no cell values are returned."""
    from backend.capture import config as capture_config
    from backend.capture import sheets
    c = capture_config.load()
    folder = capture_config.folder(c)
    files = []
    if folder.is_dir():
        for path in sorted(p for p in folder.iterdir()
                           if p.is_file() and p.suffix.lower() in (".csv", ".xlsx")
                           and not p.name.startswith(("~$", ".")))[:50]:
            s = capture_config.file_settings(c, path.name)
            entry = {"file": path.name, "id_column": s["id_column"], "columns": s["columns"]}
            try:
                header, rows, blank = sheets.read_table(path, s["sheet"])
                entry.update({"header": header, "rows": len(rows), "blank_rows": blank,
                              "suggested_id_column": sheets.suggest_id_column(header, rows)})
                sheet = sheets.read_sheet(path, s["id_column"], s["sheet"])
                entry.update({"id_column_in_use": sheet.id_column, "records": len(sheet.rows),
                              "rows_without_id": sheet.skipped_blank_ids, "ok": True})
            except sheets.InvalidSheet as exc:
                entry.update({"ok": False, "error": str(exc)})
            files.append(entry)
    return {"folder": str(folder), "exists": folder.is_dir(), "files": files}


@app.post("/api/demo/load", dependencies=[Depends(require_writer)])
def demo_load(db: Session = Depends(get_db)):
    """Load the bundled SAMPLE workspace (demo_data/): replays its edit timeline through the
    real sheet diff, stores the events, and runs detection. Safe to run more than once."""
    from backend import demo
    try:
        result = demo.load(db)
    except demo.DemoError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc
    audit_mod.append(db, "demo.loaded", {"events": result["events_new"],
                                         "files": result["files"]})
    db.commit()
    return result

@app.post("/api/capture/poll", dependencies=[Depends(require_writer)])
def capture_poll(db: Session = Depends(get_db)):
    """One bounded watcher pass over the configured folder; events go through the
    event contract and the same ingest + detection chain as POST /api/events."""
    from backend.capture.ingest import store_events
    w = _capture_watcher()
    events = w.poll()
    accepted: list[str] = []
    if events:
        try:
            accepted = store_events(db, events)
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"error": f"watcher emitted invalid events: {str(exc)[:200]}"})
    from backend.detection.service import refresh_from_events
    detection = refresh_from_events(db)
    # Superset response: counts for the contract tests + arrays for the UI.
    # `gaps` is capped in the watcher so this stays bounded.
    return {"events": len(accepted), "accepted": accepted,
            "gaps": list(w.gaps)[-20:], "detection": detection}


@app.get("/api/audit", dependencies=[Depends(require_token)])
def get_audit(verify: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    result = audit_mod.verify_chain(db) if verify else {"chain_valid": None}
    entries = db.query(AuditEntry).order_by(AuditEntry.seq).all()
    limit = max(1, min(limit, 200))
    tail = entries[-limit:]
    return {"count": len(entries), **result,
            "entries": [{"seq": e.seq, "kind": e.kind, "hash": e.hash[:12],
                         "at": e.at,
                         "payload": (json.loads(e.payload_json)
                                     if e.payload_json else {})}
                        for e in tail]}


# ─── Phase 5: plan → generation → static validation ─────────────────────────
class PlanBody(BaseModel):
    candidate_id: str | None = None
    plan: dict


@app.post("/api/plans", dependencies=[Depends(require_writer)])
def create_plan(body: PlanBody, db: Session = Depends(get_db)):
    from backend.engine.generation import plan_sha256, validate_plan
    from backend.models import GenerationPlan
    missing = validate_plan(body.plan)
    row = GenerationPlan(id=str(uuid.uuid4()), candidate_id=body.candidate_id,
                         plan_json=json.dumps(body.plan, sort_keys=True),
                         plan_sha256=plan_sha256(body.plan),
                         missing_rules_json=json.dumps(missing),
                         status="draft", created_at=now_iso())
    db.add(row)
    db.commit()
    audit_mod.append(db, "plan.created", {"plan_id": row.id, "missing": missing})
    db.commit()
    return {"plan_id": row.id, "missing_rules": missing,
            "generatable": not missing, "plan_sha256": row.plan_sha256}


@app.get("/api/plans/{plan_id}", dependencies=[Depends(require_writer)])
def get_plan(plan_id: str, db: Session = Depends(get_db)):
    from backend.models import GenerationPlan
    plan_row = db.get(GenerationPlan, plan_id)
    if plan_row is None:
        raise HTTPException(status_code=404, detail={"error": "plan not found"})
    return {
        "plan_id": plan_row.id,
        "candidate_id": plan_row.candidate_id,
        "plan": json.loads(plan_row.plan_json),
        "plan_sha256": plan_row.plan_sha256,
        "status": plan_row.status,
        "missing_rules": json.loads(plan_row.missing_rules_json or "[]"),
        "created_at": plan_row.created_at,
    }


@app.get("/api/plans/{plan_id}/artifacts", dependencies=[Depends(require_writer)])
def list_plan_artifacts(plan_id: str, db: Session = Depends(get_db)):
    from backend.models import Approval, GeneratedArtifact, TestJob
    arts = (db.query(GeneratedArtifact)
            .filter(GeneratedArtifact.plan_id == plan_id)
            .order_by(GeneratedArtifact.version.desc()).all())
    out = []
    for a in arts:
        job = (db.query(TestJob)
               .filter(TestJob.artifact_id == a.id)
               .order_by(TestJob.created_at.desc()).first())
        approval = (db.query(Approval)
                    .filter(Approval.artifact_id == a.id, Approval.kind == "activation").first())
        out.append({
            "artifact_id": a.id,
            "plan_id": a.plan_id,
            "version": a.version,
            "code_sha256": a.code_sha256,
            "status": a.status,
            "violations": json.loads(a.static_check_json or "[]"),
            "created_at": a.created_at,
            "last_job": {"job_id": job.id, "status": job.status, "report": json.loads(job.report_json or "{}")} if job else None,
            "approval": {"approval_id": approval.id, "decided_at": approval.decided_at} if approval else None,
        })
    return {"artifacts": out}


class GenerateBody(BaseModel):
    plan_id: str
    approve_generation: bool
    self_repair: bool = True
    start_broken: bool = False  # demo: seed attempt 1 with a known-flawed draft


@app.post("/api/artifacts/generate", dependencies=[Depends(require_writer)])
def generate_artifact(body: GenerateBody, db: Session = Depends(get_db)):
    """Generation requires an explicit approval flag AND a complete plan. The model
    output can never mint permissions: code is stored only after static validation."""
    from backend.engine import generation as gen
    from backend.models import GeneratedArtifact, GenerationPlan
    if not body.approve_generation:
        raise HTTPException(status_code=403, detail={"error": "generation requires explicit approval"})
    plan_row = db.get(GenerationPlan, body.plan_id)
    if plan_row is None:
        raise HTTPException(status_code=404, detail={"error": "plan not found"})
    if json.loads(plan_row.missing_rules_json):
        raise HTTPException(status_code=422, detail={"error": "plan incomplete; generation blocked",
                                                     "missing": json.loads(plan_row.missing_rules_json)})
    if plan_row.status != "approved_for_generation":
        plan_row.status = "approved_for_generation"
        db.commit()
    plan = json.loads(plan_row.plan_json)
    try:
        if body.self_repair:
            loop = gen.generate_with_repair(plan, lambda code: _self_check(code, plan),
                                            max_attempts=gen.MAX_REPAIR_ATTEMPTS,
                                            start_broken=body.start_broken)
            attempts = loop["attempts"]
        else:
            one = gen.generate(plan)
            attempts = [{**one, "attempt": 1, "problems": list(one["violations"]), "self_check": None}]
    except gen.PlanError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc)})
    base = db.query(GeneratedArtifact).filter(GeneratedArtifact.plan_id == plan_row.id).count()
    art = None
    log = []
    for i, att in enumerate(attempts):
        last = i == len(attempts) - 1
        # superseded repair attempts are kept for provenance but can never be tested
        status = ("invalid" if att["violations"] or not last else "awaiting_test_approval")
        art = GeneratedArtifact(
            id=str(uuid.uuid4()), plan_id=plan_row.id, version=base + i + 1,
            model_output_json=json.dumps({"output": att["model_output"][:4000],
                                          "attempt": att["attempt"], "problems": att["problems"]}),
            code=att["code"], code_sha256=att["code_sha256"],
            static_check_json=json.dumps(att["violations"] or ([] if last else att["problems"])),
            status=status, created_at=now_iso())
        db.add(art)
        db.commit()
        audit_mod.append(db, "artifact.generated", {"artifact_id": art.id, "version": art.version,
                                                    "status": art.status, "attempt": att["attempt"],
                                                    "violations": att["violations"],
                                                    "problems": att["problems"][:5],
                                                    "seeded": bool(att.get("seeded"))})
        db.commit()
        log.append({"attempt": att["attempt"], "version": art.version, "status": status,
                    "problems": att["problems"], "code": att["code"],
                    "seeded": bool(att.get("seeded")),
                    "gen_ms": att.get("gen_ms"), "check_ms": att.get("check_ms"),
                    "code_sha256": att["code_sha256"],
                    "checks": [{"name": c.get("name"), "ok": c.get("ok")}
                               for c in ((att["self_check"] or {}).get("checks") or [])],
                    "self_check": (att["self_check"] or {}).get("status")})
    final = attempts[-1]
    files = [_write_artifact(plan_row.id, "plan.json", json.dumps(plan, indent=2, sort_keys=True))]
    for entry in log:
        files.append(_write_artifact(plan_row.id, f"automation_v{entry['version']}.py", entry["code"]))
        files.append(_write_artifact(plan_row.id, f"sandbox_v{entry['version']}.json", json.dumps(
            {"attempt": entry["attempt"], "passed": not entry["problems"], "problems": entry["problems"],
             "checks": entry["checks"]}, indent=2)))
    return {"artifact_id": art.id, "version": art.version, "status": art.status, "files": files,
            "violations": final["violations"], "code_sha256": art.code_sha256,
            "attempts": log, "repaired": len(attempts) > 1 and not final["problems"],
            "provider": _os.environ.get("AUTOSTACK_AI_PROVIDER", "mock"),
            "self_check": (final["self_check"] or {}).get("status")}


def _automation_dir(plan_id: str):
    d = cfg.DATA_DIR / "automations" / f"automation-{plan_id[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_artifact(plan_id: str, name: str, content: str) -> dict:
    """Every stage leaves a real file on disk next to the automation it belongs to."""
    path = _automation_dir(plan_id) / name
    path.write_text(content, encoding="utf-8")
    return {"name": name, "path": str(path), "folder": path.parent.name,
            "lines": content.count("\n") + 1, "bytes": len(content.encode("utf-8")),
            "content": content[:20000]}


def _self_check(code: str, plan: dict) -> dict:
    """Sandbox run of freshly generated code against the plan-derived oracle, used only
    to drive repair. The formal, consented test job is still required before activation."""
    from backend.engine import generation, runner
    table, _payload = _plan_test_table(plan)
    id_field = plan.get("client_id_field", "ClientID")
    table.extend(_boundary_rows(table, plan, id_field))
    policy = {"max_output_items": 1000, "forbidden": ["network", "filesystem", "subprocess"]}
    return runner.run_isolated_test(code, table, ctx=generation.plan_run_context(plan), policy=policy,
                                    expected=_expected_outputs(table, plan, id_field), key_field=id_field)


# ─── Phase 6: consent → isolated test → report → separate activation approval ─
class TestJobBody(BaseModel):
    artifact_id: str
    fixture: str = "clients-before.csv"
    consent: bool


@app.post("/api/test-jobs", dependencies=[Depends(require_tester)])
def create_test_job(body: TestJobBody, db: Session = Depends(get_db)):
    from backend.engine import runner
    from backend.models import GeneratedArtifact, TestJob
    if not body.consent:
        raise HTTPException(status_code=403, detail={"error": "test consent required"})
    art = db.get(GeneratedArtifact, body.artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail={"error": "artifact not found"})
    if art.status == "activated":
        raise HTTPException(status_code=409, detail={"error": "artifact already activated"})
    if art.status not in ("awaiting_test_approval", "test_passed"):
        raise HTTPException(status_code=409, detail={"error": f"artifact not testable in state {art.status}"})
    from backend.models import GenerationPlan
    plan_row = db.get(GenerationPlan, art.plan_id)
    plan = json.loads(plan_row.plan_json) if plan_row else {}
    fixture_name = body.fixture
    if plan.get("resource_alias") == "watched":
        try:
            table, fixture_payload = _plan_test_table(plan)
        except Exception as exc:  # noqa: BLE001 - unreadable sheet blocks the test
            raise HTTPException(status_code=400, detail={"error": f"cannot read your sheet: {str(exc)[:160]}"})
        fixture_name = f"copy of {plan['resource_filename']}"
    elif body.fixture == "reset":
        fixture_payload = (cfg.FIXTURES_DIR / "clients-before.csv").read_bytes()
    else:
        fpath = (cfg.FIXTURES_DIR / body.fixture)
        if not fpath.is_file() or fpath.suffix != ".csv" or "/" in body.fixture or ".." in body.fixture:
            raise HTTPException(status_code=400, detail={"error": "unknown fixture"})
        fixture_payload = fpath.read_bytes()
    if plan.get("resource_alias") != "watched":
        from backend.file_diff import read_snapshot as _rs
        table = list(_rs(_as_tmp_fixture(fixture_payload)).values())
    policy = {"max_output_items": 1000, "forbidden": ["network", "filesystem", "subprocess"]}
    job = TestJob(id=str(uuid.uuid4()), artifact_id=art.id, code_sha256=art.code_sha256,
                  input_sha256=sha256_bytes(fixture_payload), fixture_name=fixture_name,
                  policy_json=json.dumps(policy), status="running", created_at=now_iso())
    db.add(job)
    db.commit()
    # Runner context + expected outputs come from the CONFIRMED PLAN, never from the
    # model — the approved plan is the only source of eligibility truth (Phase 5/8).
    from backend.engine import generation
    ctx = generation.plan_run_context(plan)
    id_field = plan.get("client_id_field", "ClientID")
    expected = _expected_outputs(table[:50], plan, id_field)
    report = runner.run_isolated_test(art.code, table[:50], ctx=ctx, policy=policy,
                                      expected=expected, key_field=id_field)
    if report["status"] == "refused":
        job.status = "failed"
        job.report_json = json.dumps(report)
        job.report_sha256 = report["report_sha256"]
        db.commit()
        raise HTTPException(status_code=422, detail={"error": "static checks refused execution",
                                                     "violations": report["violations"]})
    job.status = report["status"]  # passed | failed (a failed test is a valid outcome)
    job.report_json = json.dumps(report)
    job.report_sha256 = report["report_sha256"]
    if report["status"] == "passed":
        art.status = "test_passed"
    else:
        art.status = "awaiting_test_approval"
    db.commit()
    audit_mod.append(db, "test.completed", {"job_id": job.id, "artifact_id": art.id,
                                            "status": job.status,
                                            "policy_sha256": report["policy_sha256"]})
    db.commit()
    test_file = _write_artifact(art.plan_id, f"test_report_v{art.version}.json", json.dumps(
        {"status": job.status, "tested_on": fixture_name, "rows": len(table[:50]),
         "checks": report.get("checks"), "error": report.get("error"),
         "report_sha256": report.get("report_sha256")}, indent=2, default=str))
    return {"job_id": job.id, "status": job.status, "report": report, "file": test_file,
            "rows_tested": len(table[:50]), "tested_on": fixture_name}


@app.get("/api/test-jobs/{job_id}", dependencies=[Depends(require_tester)])
def get_test_job(job_id: str, db: Session = Depends(get_db)):
    from backend.models import TestJob
    job = db.get(TestJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"error": "job not found"})
    return {
        "job_id": job.id,
        "artifact_id": job.artifact_id,
        "status": job.status,
        "fixture_name": job.fixture_name,
        "report": json.loads(job.report_json or "{}"),
        "created_at": job.created_at,
    }


def _expected_outputs(rows_list: list[dict], plan: dict, id_field: str) -> list[dict]:
    """Independent expected outputs, computed DIRECTLY from the confirmed plan.

    This is the oracle for Phase 8's 'expected results from real data' — it shares no
    code with the generated function, so a wrong synthesis fails the comparison.
    """
    elig = plan.get("eligibility") or {}
    status = elig.get("status")
    status_field = elig.get("status_field") or "Status"
    date_field = elig.get("date_field")
    date_value = elig.get("date_value") or elig.get("run_date")
    out = []
    for row in rows_list:
        if status is not None and row.get(status_field) != status:
            continue
        if date_field and date_value is not None:
            due = row.get(date_field)
            if due is None or str(due) > str(date_value):
                continue
        out.append({id_field: row.get(id_field)})
    return out


def _plan_test_table(plan: dict) -> tuple[list[dict], bytes]:
    """Rows the generated code is tested on: a read-only copy of the plan's own sheet
    when it targets the user's folder, otherwise the bundled sample fixture."""
    if plan.get("resource_alias") == "watched" and plan.get("resource_filename"):
        from backend.security import safeio
        payload = safeio.read_resource("watched", plan["resource_filename"])
        return rows.read_table("watched", plan["resource_filename"])[:50], payload
    from backend.file_diff import read_snapshot as _rs
    payload = (cfg.FIXTURES_DIR / "clients-before.csv").read_bytes()
    return list(_rs(_as_tmp_fixture(payload)).values())[:50], payload


def _boundary_rows(rows_list: list[dict], plan: dict, id_field: str) -> list[dict]:
    """Edge cases the fixture may not cover: right status but due one day after the
    cut-off (must be skipped), and due exactly on it (must be kept)."""
    from datetime import date, timedelta
    elig = plan.get("eligibility") or {}
    date_field, date_value = elig.get("date_field"), elig.get("date_value") or elig.get("run_date")
    if not date_field or not date_value or not rows_list:
        return []
    try:
        cutoff = date.fromisoformat(str(date_value)[:10])
    except ValueError:
        return []
    template = dict(rows_list[0])
    if elig.get("status") is not None:
        template[elig.get("status_field") or "Status"] = elig["status"]
    late = {**template, id_field: "EDGE-LATE", date_field: (cutoff + timedelta(days=1)).isoformat()}
    on_day = {**template, id_field: "EDGE-ONDAY", date_field: cutoff.isoformat()}
    return [late, on_day]


def _as_tmp_fixture(payload: bytes):
    """Stage fixture bytes for the runner's independent read (scratch dir)."""
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="as-fixture-")) / "fixture.csv"
    tmp.write_bytes(payload)
    return tmp


class ApprovalBody(BaseModel):
    artifact_id: str
    job_id: str | None = None
    note: str = ""


@app.post("/api/approvals/activation", dependencies=[Depends(require_tester)])
def activation_approval(body: ApprovalBody, db: Session = Depends(get_db)):
    """Separate human decision AFTER tests pass. Rejects stale/mismatched evidence."""
    from backend.models import Approval, GeneratedArtifact, TestJob
    art = db.get(GeneratedArtifact, body.artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail={"error": "artifact not found"})
    if art.status != "test_passed":
        raise HTTPException(status_code=409, detail={"error": f"activation blocked in state {art.status}"})
    if body.job_id:
        job = db.get(TestJob, body.job_id)
        if job is None or job.artifact_id != art.id or job.code_sha256 != art.code_sha256:
            raise HTTPException(status_code=409, detail={"error": "report mismatch: job/code binding failed"})
        if job.status != "passed":
            raise HTTPException(status_code=409, detail={"error": "referenced test did not pass"})
    art.status = "activated"
    art.activated_code_sha256 = art.code_sha256
    db.add(Approval(id=str(uuid.uuid4()), kind="activation", artifact_id=art.id,
                    code_sha256=art.code_sha256, job_id=body.job_id,
                    decided_at=now_iso(), note=body.note))
    db.commit()
    audit_mod.append(db, "artifact.activated", {"artifact_id": art.id,
                                                "code_sha256": art.code_sha256[:16]})
    db.commit()
    return {"artifact_id": art.id, "status": "activated", "code_sha256": art.code_sha256}


# ─── Phase 9: shared registry — publish consent, untrusted imports, withdrawal ──
class PublishBody(BaseModel):
    slug: str
    title: str
    graph: dict
    compatible_connectors: list[str] = []
    publication_consent: bool


def _graph_secret_scan(graph: dict) -> list[str]:
    """Reject templates carrying records, credentials, or private paths (S8)."""
    blob = json.dumps(graph).lower()
    violations = []
    for banned in ("password", "secret", "token", "api_key", "apikey", "c:\\users",
                   "@example.invalid", "client1@example"):
        if banned in blob:
            violations.append(f"template contains forbidden material: {banned}")
    return violations


@app.post("/api/registry/publish", dependencies=[Depends(require_publisher)])
def registry_publish(body: PublishBody, db: Session = Depends(get_db)):
    from backend.models import RegistryTemplate
    if not body.publication_consent:
        raise HTTPException(status_code=403, detail={"error": "publication consent required"})
    violations = _graph_secret_scan(body.graph)
    if violations:
        raise HTTPException(status_code=422, detail={"error": "publication blocked",
                                                     "violations": violations})
    graph_errors = validate_graph(body.graph)
    if graph_errors:
        return JSONResponse(status_code=422, content={"validation_errors": graph_errors})
    canonical = json.dumps(body.graph, sort_keys=True, separators=(",", ":"))
    artifact = hashlib.sha256(canonical.encode()).hexdigest()
    last = (db.query(RegistryTemplate)
            .filter(RegistryTemplate.slug == body.slug)
            .order_by(RegistryTemplate.version.desc()).first())
    version = (last.version + 1) if last else 1
    permissions = signing.derive_permissions(body.graph, body.compatible_connectors)
    signature, signer = signing.sign(signing.manifest(
        slug=body.slug, version=version, title=body.title, artifact_sha256=artifact,
        compatible_connectors=body.compatible_connectors, permissions=permissions))
    row = RegistryTemplate(id=str(uuid.uuid4()), slug=body.slug, version=version,
                           title=body.title, graph_json=canonical, artifact_sha256=artifact,
                           compatible_connectors_json=json.dumps(body.compatible_connectors),
                           status="published", published_at=now_iso(),
                           permissions_json=json.dumps(permissions),
                           signature=signature, signer_pubkey=signer)
    db.add(row)
    db.commit()
    audit_mod.append(db, "registry.published", {"slug": body.slug, "version": version,
                                                "artifact_sha256": artifact[:16],
                                                "signer": signer[:16]})
    db.commit()
    return {"template_id": row.id, "slug": body.slug, "version": version,
            "artifact_sha256": artifact, "signature": signature, "signer_pubkey": signer,
            "permissions": permissions}


def _verify_template(tpl) -> list[str]:  # noqa: ANN001
    """Re-derive everything the signature covers from stored data; any mismatch = tampered."""
    problems = []
    if not tpl.signature or not tpl.signer_pubkey:
        return ["template is unsigned (published before signing existed); republish it"]
    if signing.sha256_hex(tpl.graph_json) != tpl.artifact_sha256:
        problems.append("graph does not match its published artifact hash")
    connectors = json.loads(tpl.compatible_connectors_json)
    stored_perms = json.loads(tpl.permissions_json)
    derived = signing.derive_permissions(json.loads(tpl.graph_json), connectors)
    if derived != stored_perms:
        problems.append("declared permissions do not match what the graph actually does")
    text = signing.manifest(slug=tpl.slug, version=tpl.version, title=tpl.title,
                            artifact_sha256=tpl.artifact_sha256,
                            compatible_connectors=connectors, permissions=stored_perms)
    if not signing.verify(text, tpl.signature, tpl.signer_pubkey):
        problems.append("signature does not verify")
    if tpl.signer_pubkey not in signing.trusted_signers():
        problems.append("signer is not in this office's trusted signer list")
    return problems


@app.get("/api/registry/templates", dependencies=[Depends(require_token)])
def registry_list(db: Session = Depends(get_db)):
    """Search/cards source: no invented ratings, office counts, or savings."""
    from backend.models import RegistryTemplate
    rows_q = (db.query(RegistryTemplate)
              .filter(RegistryTemplate.status == "published")
              .order_by(RegistryTemplate.slug, RegistryTemplate.version.desc()).all())
    seen = set()
    out = []
    for r in rows_q:
        if r.slug in seen:
            continue
        seen.add(r.slug)
        out.append({"template_id": r.id, "slug": r.slug, "version": r.version,
                    "title": r.title, "artifact_sha256": r.artifact_sha256,
                    "compatible_connectors": json.loads(r.compatible_connectors_json),
                    "permissions": json.loads(r.permissions_json),
                    "signed": bool(r.signature), "signer_pubkey": r.signer_pubkey})
    return out


class ImportBody(BaseModel):
    template_id: str
    local_mapping: dict
    # When given, the import is refused unless every scope the template needs is granted.
    granted_scopes: list[str] | None = None


@app.post("/api/registry/import", dependencies=[Depends(require_writer)])
def registry_import(body: ImportBody, db: Session = Depends(get_db)):
    """Imports are ALWAYS untrusted drafts: approvals are never inherited, the imported
    graph must re-pass local mapping, tests, and activation in the importing office."""
    from backend.models import RegistryImport, RegistryTemplate
    tpl = db.get(RegistryTemplate, body.template_id)
    if tpl is None or tpl.status != "published":
        raise HTTPException(status_code=404, detail={"error": "template not available"})
    problems = _verify_template(tpl)
    if problems:
        audit_mod.append(db, "registry.import_refused", {"template_id": tpl.id, "slug": tpl.slug,
                                                         "version": tpl.version,
                                                         "problems": problems})
        db.commit()
        raise HTTPException(status_code=409, detail={"error": "template failed integrity check",
                                                     "problems": problems})
    permissions = json.loads(tpl.permissions_json)
    if body.granted_scopes is not None:
        missing = sorted(signing.scope_names(permissions) - set(body.granted_scopes))
        if missing:
            raise HTTPException(status_code=403, detail={"error": "permission scopes not granted",
                                                         "missing_scopes": missing,
                                                         "permissions": permissions})
    graph = json.loads(tpl.graph_json)
    # Apply the local mapping (column renames) — validated structurally.
    if not isinstance(body.local_mapping, dict):
        raise HTTPException(status_code=422, detail={"error": "local_mapping must be an object"})
    imported = json.loads(json.dumps(graph))  # deep copy
    mappings = imported.setdefault("params", {})
    if isinstance(mappings, dict):
        mappings["local_mapping"] = body.local_mapping
    imp = RegistryImport(id=str(uuid.uuid4()), template_id=tpl.id,
                         template_version=tpl.version,
                         local_mapping_json=json.dumps(body.local_mapping, sort_keys=True),
                         imported_graph_json=json.dumps(imported, sort_keys=True),
                         status="untrusted_draft",
                         artifact_sha256=hashlib.sha256(
                             json.dumps(imported, sort_keys=True).encode()).hexdigest(),
                         created_at=now_iso())
    db.add(imp)
    db.commit()
    audit_mod.append(db, "registry.imported", {"import_id": imp.id, "slug": tpl.slug,
                                               "version": tpl.version})
    db.commit()
    return {"import_id": imp.id, "status": imp.status,
            "artifact_sha256": imp.artifact_sha256,
            "verified": {"signature": True, "signer_pubkey": tpl.signer_pubkey,
                         "template_artifact_sha256": tpl.artifact_sha256},
            "permissions": permissions,
            "note": "untrusted draft: local tests and activation approval required"}


class WithdrawBody(BaseModel):
    slug: str


@app.post("/api/registry/withdraw", dependencies=[Depends(require_publisher)])
def registry_withdraw(body: WithdrawBody, db: Session = Depends(get_db)):
    """Withdrawal stops NEW imports; safe installed copies are not auto-invalidated."""
    from backend.models import RegistryTemplate
    rows_q = (db.query(RegistryTemplate)
              .filter(RegistryTemplate.slug == body.slug,
                      RegistryTemplate.status == "published").all())
    if not rows_q:
        raise HTTPException(status_code=404, detail={"error": "no published template with that slug"})
    for r in rows_q:
        r.status = "withdrawn"
        r.withdrawn_at = now_iso()
    db.commit()
    audit_mod.append(db, "registry.withdrawn", {"slug": body.slug,
                                                "versions": [r.version for r in rows_q]})
    db.commit()
    return {"slug": body.slug, "withdrawn_versions": len(rows_q)}


class RevokeBody(BaseModel):
    slug: str
    reason: str


@app.post("/api/registry/revoke", dependencies=[Depends(require_publisher)])
def registry_revoke(body: RevokeBody, db: Session = Depends(get_db)):
    """Security recall: withdraw every version AND mark every installed copy revoked, so
    offices that already imported a bad template are told and cannot keep running it."""
    from backend.models import RegistryImport, RegistryTemplate
    if not body.reason.strip():
        raise HTTPException(status_code=422, detail={"error": "a revocation reason is required"})
    versions = db.query(RegistryTemplate).filter(RegistryTemplate.slug == body.slug).all()
    if not versions:
        raise HTTPException(status_code=404, detail={"error": "no template with that slug"})
    at = now_iso()
    for v in versions:
        if v.status == "published":
            v.status = "withdrawn"
            v.withdrawn_at = at
    ids = [v.id for v in versions]
    imports = (db.query(RegistryImport)
               .filter(RegistryImport.template_id.in_(ids),
                       RegistryImport.status != "revoked").all())
    for imp in imports:
        imp.status = "revoked"
    db.commit()
    audit_mod.append(db, "registry.revoked", {"slug": body.slug, "reason": body.reason[:200],
                                              "versions": [v.version for v in versions],
                                              "installed_copies_revoked": len(imports)})
    db.commit()
    return {"slug": body.slug, "versions_withdrawn": len(versions),
            "installed_copies_revoked": len(imports)}


@app.get("/api/registry/imports", dependencies=[Depends(require_token)])
def registry_imports(db: Session = Depends(get_db)):
    from backend.models import RegistryImport
    rows_q = db.query(RegistryImport).order_by(RegistryImport.created_at.desc()).all()
    return [{"import_id": i.id, "template_id": i.template_id, "version": i.template_version,
             "status": i.status, "created_at": i.created_at} for i in rows_q]


# --- Phase 5->9 keystone: graph executor, plan binding, run-now ---------------


def _topo_order(graph: dict) -> list[str]:
    nodes = graph.get("nodes", [])
    ids = [n.get("id") for n in nodes]
    incoming = {nid: 0 for nid in ids}
    succ = {nid: [] for nid in ids}
    for e in graph.get("edges", []):
        f, t = e.get("from"), e.get("to")
        if f in incoming and t in incoming:
            succ[f].append(t)
            incoming[t] += 1
    queue = sorted([nid for nid, d in incoming.items() if d == 0])
    order = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for s in succ[nid]:
            incoming[s] -= 1
            if incoming[s] == 0:
                queue.append(s)
    return order


def _expr_row(row: dict) -> dict:
    """Filters address columns as `row.Payment_Status`; expose identifier-safe
    aliases for headers with spaces or punctuation alongside the originals."""
    from backend.engine.graph_build import _safe_ident
    return {**{_safe_ident(k): v for k, v in row.items()}, **row}


def _exec_graph(db: Session, run: Run, graph: dict, plan: dict,
                run_date: str, filename: str, *, dry_run: bool = False,
                params: dict | None = None) -> dict:
    """Execute a compiled workflow graph in topological order.

    Shares the exactly-once effect paths in rows.py with the Node-RED bridge (S4):
    same journal claims, same safeio staged writes, same audit chain. Node records
    are honest per-node outcomes; on_fail=continue keeps the run walking.

    Roadmap §E additions: dry_run (effects computed, nothing applied — no journal
    claims consumed), branch nodes (sandboxed condition), approval-gate nodes
    (pause the run honestly), and declared run parameters via `params`.
    """
    from backend.engine.expressions import eval_bool
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    seq = 0
    table: list[dict] = []
    alias = "sample-tracking-file"
    updated: list[str] = []
    drafted: list[str] = []
    skipped: list[str] = []
    notified = False
    templates = plan.get("templates") or None
    purpose = plan.get("purpose", "followup-draft")
    params = params or {}
    branch_skips: set[str] = set()
    would_update: list[str] = []
    would_draft: list[str] = []
    for nid in _topo_order(graph):
        node = nodes[nid]
        ntype = node.get("type", "")
        params_n = node.get("params", {})
        t0 = time.perf_counter()
        error = None
        error_exc = None
        detail: dict = {}
        if nid in branch_skips:
            seq += 1
            _node_record(db, run.id, seq, f"{nid}:{ntype}", "skipped",
                         {"note": "branch condition not taken"}, None, None, ms=0)
            db.commit()
            continue
        try:
            if ntype == "file.read_table":
                alias = params_n.get("alias", alias)
                fn = params_n.get("filename", filename)
                table = rows.read_table(alias, fn)
                detail = {"rows": len(table)}
            elif ntype == "data.filter":
                where = params_n.get("where", "True")
                table = [r for r in table
                         if eval_bool(where, {"row": _expr_row(r), "run_date": run_date, "params": params})]
                detail = {"due": [r.get(plan.get("client_id_field", "ClientID")) for r in table]}
            elif ntype == "control.branch":
                cond = params_n.get("condition", "True")
                taken = bool(eval_bool(cond, {"row": (table[0] if table else {}),
                                              "run_date": run_date, "params": params}))
                detail = {"condition": cond, "taken": taken}
                if not taken:
                    downstream = _branch_targets(graph, nid)
                    branch_skips.update(downstream)
                    detail["skipped_downstream"] = len(downstream)
            elif ntype == "file.update_rows":
                assignments = []
                for part in params_n.get("set", "").split(";"):
                    field, _, literal = part.partition("=")
                    if field.strip():
                        assignments.append((field.strip(), literal.strip().strip("\"'")))
                key_field = params_n.get("key_field", plan.get("client_id_field", "ClientID"))
                fn = params_n.get("filename", filename)
                if dry_run:
                    would_update.extend(str(r.get(key_field)) for r in table if r.get(key_field) is not None)
                    detail = {"dry_run": True, "would_update": would_update}
                else:
                    for r in table:
                        kv = r.get(key_field)
                        if kv is None:
                            continue
                        results = [rows.update_row_field(
                            db, run_id=run.id, alias=alias, filename=fn,
                            key_field=key_field, key_value=str(kv), field=field,
                            new_value=new_value,
                            purpose=purpose if len(assignments) == 1 else f"{purpose}:{field}",
                            effect_ns=run_date) for field, new_value in assignments]
                        (skipped if all(x.get("skipped") for x in results) else updated).append(str(kv))
                    detail = {"updated": updated, "skipped": skipped}
            elif ntype == "draft.create":
                id_field = plan.get("client_id_field", "ClientID")
                template_id = params_n.get("template_id", "followup_en")
                destination = params_n.get("destination", "in_app")
                if dry_run:
                    would_draft.extend(f"sample:{r.get(id_field)}" for r in table if r.get(id_field) is not None)
                    detail = {"dry_run": True, "would_draft": would_draft}
                else:
                    for r in table:
                        kv = r.get(id_field)
                        if kv is None:
                            continue
                        res = rows.create_draft(
                            db, run_id=run.id, record_key=f"sample:{kv}", row=r,
                            template_id=template_id, destination=destination,
                            run_date=run_date, purpose=purpose, templates=templates)
                        (skipped if res.get("skipped") else drafted).append(f"sample:{kv}")
                    detail = {"drafted": drafted, "skipped": skipped}
            elif ntype == "approval.gate":
                if dry_run:
                    detail = {"dry_run": True, "would_pause": True}
                else:
                    from backend.models import ReviewGate
                    # resuming after approval: this node was already decided — pass through
                    decided = db.scalar(sa_select(ReviewGate).where(
                        ReviewGate.run_id == run.id, ReviewGate.node_id == nid,
                        ReviewGate.status == "approved").limit(1))
                    if decided is not None:
                        detail = {"resumed_after_gate": decided.id}
                    else:
                        gate = ReviewGate(id=secrets.token_hex(12), run_id=run.id, node_id=nid,
                                          prompt=str(params_n.get("prompt", "approval required"))[:500],
                                          status="pending", created_at=now_iso())
                        db.add(gate)
                        db.commit()
                        run.status = "awaiting_gate"
                        db.commit()
                        # persist the run context so resume re-executes with identical inputs
                        from backend.models import Setting
                        db.add(Setting(key=f"run_context:{run.id}",
                                       value_json=json.dumps({"filename": filename, "run_date": run_date})))
                        db.commit()
                        detail = {"gate_id": gate.id, "status": "awaiting_gate"}
                        return {"updated": updated, "drafted": drafted, "skipped": skipped,
                                "notified": notified, "paused_at_gate": gate.id, **detail}
            elif ntype == "notify.desktop":
                notified = True
                detail = {"notified": True}
            else:
                detail = {"note": "executed by bridge runtime only"}
        except Exception as exc:
            error = str(exc)[:400]
            error_exc = exc
            if node.get("on_fail") == "continue":
                detail = {"continued_after_error": error}
        ms = int((time.perf_counter() - t0) * 1000)
        seq += 1
        _node_record(db, run.id, seq, f"{nid}:{ntype}", "failed" if error else "passed",
                     detail, None, error, ms=ms)
        db.commit()
        if error and node.get("on_fail") != "continue":
            raise RuntimeError(f"node {nid} failed: {error}") from error_exc
    result = {"updated": updated, "drafted": drafted, "skipped": skipped, "notified": notified}
    if dry_run:
        result["would_update"] = would_update
        result["would_draft"] = would_draft
    return result


def _branch_targets(graph: dict, from_id: str) -> set[str]:
    """All nodes reachable from `from_id` (the branch NOT taken gets skipped)."""
    succ: dict[str, list[str]] = {}
    for e in graph.get("edges", []):
        f, t = e.get("from"), e.get("to")
        if f and t:
            succ.setdefault(f, []).append(t)
    seen: set[str] = set()
    queue = list(succ.get(from_id, []))
    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        queue.extend(succ.get(nid, []))
    return seen


def resume_run_after_gate(db: Session, gate_id: str, approved: bool, decided_by: str) -> dict:
    """Roadmap §E: record a gate decision and resume the paused run by re-executing
    the graph — completed effects are exactly-once-claimed, so no work is redone."""
    from backend.models import ReviewGate
    gate = db.get(ReviewGate, gate_id)
    if gate is None:
        raise ValueError("gate not found")
    if gate.status != "pending":
        raise ValueError(f"gate already decided ({gate.status})")
    gate.status = "approved" if approved else "rejected"
    gate.decided_by = decided_by[:80]
    gate.decided_at = now_iso()
    db.commit()
    run = db.get(Run, gate.run_id)
    audit_mod.append(db, "run.gate_decision", {"gate_id": gate_id, "run_id": run.id,
                                                "approved": approved, "decided_by": decided_by})
    db.commit()
    if not approved:
        run.status = "failed"
        run.error = f"rejected at gate {gate.node_id} by {decided_by}"
        run.ended_at = datetime.now(timezone.utc)
        db.commit()
        return {"gate_id": gate_id, "run_id": run.id, "status": "failed",
                "note": "run rejected at approval gate"}
    # resume: re-run the graph; node effects already claimed are skipped by the journal
    from backend.models import GenerationPlan
    version = db.get(WorkflowVersion, run.version_id)
    payload = json.loads(version.graph_json)
    graph = payload.get("graph", payload) if isinstance(payload, dict) else {}
    plan_row = (db.query(GenerationPlan)
                .filter(GenerationPlan.plan_sha256 == version_payload_plan_hash(version)).first())
    plan = json.loads(plan_row.plan_json) if plan_row else {}
    from backend.models import Setting
    ctx_row = db.get(Setting, f"run_context:{run.id}")
    ctx = json.loads(ctx_row.value_json) if ctx_row else {"filename": "clients.csv", "run_date": cfg.RUN_DATE}
    result = _exec_graph(db, run, graph, plan, ctx["run_date"], ctx["filename"])
    run.status = "passed"
    run.ended_at = datetime.now(timezone.utc)
    db.commit()
    audit_mod.append(db, "run.completed", {"run_id": run.id, "status": "passed",
                                           "resumed_after_gate": gate_id, **result})
    db.commit()
    return {"gate_id": gate_id, "run_id": run.id, "status": "passed", **result}


# --- plan binding + run-now + list APIs (Phase 5->9/10) -----------------------


def _plan_summary(plan: dict) -> str:
    elig = plan.get("eligibility") or {}
    parts = [plan.get("action", "automation")]
    if elig.get("status"):
        parts.append(f"when {elig.get('status_field', 'Status')} = {elig['status']}")
    if elig.get("date_field"):
        parts.append(f"by {elig.get('date_value') or elig.get('run_date') or 'date'}")
    return " · ".join(parts)


class ContextBody(BaseModel):
    """Create step 1 classification (product §5): org type/size, department,
    process type. All fields optional so an empty body = legacy no-context
    bind; a partially-filled body is validated as a whole."""
    org_type: str = ""
    size: str = ""
    department: str = ""
    process_type: str = ""


@app.post("/api/plan/{plan_id}/create-workflow", dependencies=[Depends(require_writer)])
def create_workflow_from_plan(plan_id: str, body: ContextBody | None = None,
                              db: Session = Depends(get_db)):
    """Bind an activated generated artifact to a real versioned workflow (Phase 5->9).

    The version records graph + plan hash + activated code hash together, so the
    provenance chain plan -> code -> workflow is content-addressed end to end.
    Body (optional): {org_type, size, department, process_type} from create
    step 1 — validated and stored so the workflow carries its classification.
    Omitted (or empty) body binds without classification (legacy behavior).
    """
    from backend import teams
    from backend.engine import graph_build
    from backend.models import GeneratedArtifact
    from backend.models import GenerationPlan  # local import (spike module layout)
    plan_row = db.get(GenerationPlan, plan_id)
    if plan_row is None:
        raise HTTPException(status_code=404, detail={"error": "plan not found"})
    ctx = body.model_dump() if body is not None else {}
    if any(ctx.values()):
        problems = teams.valid_context(ctx.get("org_type", ""), ctx.get("size", ""),
                                       ctx.get("department", ""),
                                       ctx.get("process_type", ""))
        if problems:
            raise HTTPException(status_code=422, detail={"error": "; ".join(problems)})
    else:
        ctx = None
    plan = json.loads(plan_row.plan_json)
    art = (db.query(GeneratedArtifact)
           .filter(GeneratedArtifact.plan_id == plan_id,
                   GeneratedArtifact.status == "activated").first())
    if art is None:
        raise HTTPException(status_code=409,
                            detail={"error": "no activated artifact for this plan"})
    graph = graph_build.plan_to_graph(plan)
    errors = validate_graph(graph)
    if errors:
        raise HTTPException(status_code=422,
                            detail={"error": "compiler produced invalid graph",
                                    "validation_errors": errors})
    wf_id = f"wf-{plan_id[:8]}"
    version_payload = {"graph": graph, "plan_sha256": plan_row.plan_sha256,
                       "code_sha256": art.activated_code_sha256}
    canonical = json.dumps(version_payload, sort_keys=True, separators=(",", ":"))
    artifact = hashlib.sha256(canonical.encode()).hexdigest()
    wf = db.get(Workflow, wf_id)
    if wf is None:
        wf = Workflow(id=wf_id, name=_plan_summary(plan), demo=False)
        db.add(wf)
    wf.name = _plan_summary(plan)
    last = (db.query(WorkflowVersion)
            .filter(WorkflowVersion.workflow_id == wf_id)
            .order_by(WorkflowVersion.version.desc()).first())
    vnext = (last.version + 1) if last else 1
    db.add(WorkflowVersion(id=str(uuid.uuid4()), workflow_id=wf_id, version=vnext,
                           graph_json=json.dumps(version_payload),
                           artifact_sha256=artifact,
                           changelog="bound from activated generation"))
    plan_row.status = "bound_to_workflow"
    if ctx is not None:
        teams.set_workflow_context(db, wf_id, ctx["org_type"], ctx["size"],
                                   ctx["department"], ctx["process_type"])
    db.commit()
    audit_mod.append(db, "workflow.from_plan",
                     {"plan_id": plan_id, "workflow_id": wf_id, "version": vnext,
                      "artifact_sha256": artifact,
                      "code_sha256": art.activated_code_sha256})
    db.commit()
    return {"workflow_id": wf_id, "version": vnext, "artifact_sha256": artifact,
            "graph": graph}


@app.get("/api/workflows", dependencies=[Depends(require_token)])
def list_workflows(db: Session = Depends(get_db)):
    # B4: soft-deleted workflows disappear from listings (history is retained)
    from backend import teams
    wfs = (db.query(Workflow)
           .filter(Workflow.deleted_at.is_(None))
           .order_by(Workflow.created_at).all())
    contexts = teams.workflow_context_map(db, [wf.id for wf in wfs])
    out = []
    for wf in wfs:
        last = (db.query(WorkflowVersion)
                .filter(WorkflowVersion.workflow_id == wf.id)
                .order_by(WorkflowVersion.version.desc()).first())
        runs = (db.query(Run).join(WorkflowVersion, Run.version_id == WorkflowVersion.id)
                .filter(WorkflowVersion.workflow_id == wf.id).count())
        out.append({"id": wf.id, "name": wf.name, "version": last.version if last else None,
                    "artifact_sha256": last.artifact_sha256 if last else None,
                    "runs": runs, "created_at": wf.created_at.isoformat() if wf.created_at else None,
                    "context": contexts.get(wf.id, {})})
    return {"workflows": out}



@app.get("/api/runs/{run_id}/nodes", dependencies=[Depends(require_token)])
def run_nodes(run_id: str, db: Session = Depends(get_db)):
    recs = (db.query(RunNodeRecord).filter(RunNodeRecord.run_id == run_id)
            .order_by(RunNodeRecord.seq).all())
    return {"run_id": run_id,
            "nodes": [{"seq": r.seq, "node": r.node_id, "status": r.status,
                       "error": r.error, "ms": r.ms} for r in recs]}


@app.post("/api/candidates/{candidate_id}/dismiss", dependencies=[Depends(require_writer)])
def dismiss_candidate(candidate_id: str, db: Session = Depends(get_db)):
    cand = db.get(Candidate, candidate_id)
    if cand is None:
        raise HTTPException(status_code=404, detail={"error": "not found"})
    cand.status = "dismissed"
    db.commit()
    audit_mod.append(db, "candidate.dismissed", {"candidate_id": candidate_id})
    db.commit()
    return {"id": candidate_id, "status": "dismissed"}


# --- Phase 8: second workflow (invoice/PO comparison) -------------------------


def _seed_if_missing(alias: str, filename: str, payload: bytes) -> None:
    from backend.security import safeio
    try:
        safeio.read_resource(alias, filename)
    except FileNotFoundError:
        safeio.write_resource(alias, filename, payload, backup=False)


@app.post("/api/compare/run", dependencies=[Depends(require_writer)])
def compare_run(db: Session = Depends(get_db)):
    """Second workflow (Phase 8): compare invoices to purchase orders, mark the
    register with exact categories, and prepare per-mismatch drafts.

    Effects go through the SAME exactly-once paths as the followup workflow
    (journal claims + safeio + audit). Expected categories are checked against
    compare.expected_matches — an independent oracle — before any effect applies.
    """
    from backend.engine import compare
    from backend.security import safeio

    _seed_if_missing("invoice-register", "invoices.csv", cfg.FIXTURES_DIR.joinpath("invoices-before.csv").read_bytes())
    _seed_if_missing("invoice-register", "purchase-orders.csv", cfg.FIXTURES_DIR.joinpath("purchase-orders.csv").read_bytes())

    invoices = compare.parse_table(safeio.read_resource("invoice-register", "invoices.csv"))
    purchase_orders = compare.parse_table(safeio.read_resource("invoice-register", "purchase-orders.csv"))
    enriched = compare.compare_invoices(invoices, purchase_orders, tolerance=0.01)
    expected = compare.expected_matches(invoices, purchase_orders, tolerance=0.01)
    # Fail-closed oracle gate: the compare engine (hash-index) must agree with the
    # independent oracle (per-invoice linear scan) BEFORE any effect applies.
    disagreements = [inv_id for inv_id, cat in expected.items()
                     for e in enriched
                     if str(e.get("InvoiceID", "")) == inv_id
                     and str(e.get("po_match", "")) != cat]
    if disagreements:
        audit_mod.append(db, "run.refused", {"workflow": "invoice-po-compare",
                        "reason": "compare/oracle disagreement", "invoices": disagreements})
        db.commit()
        raise HTTPException(status_code=503, detail={"error":
                            "compare engine disagrees with independent oracle; "
                            "no effects applied", "invoices": disagreements})

    run = Run(id=str(uuid.uuid4()), version_id=_compare_version_id(db),
              trigger_type="manual", status="running")
    db.add(run)
    db.commit()

    seq = 0
    seq += 1
    _node_record(db, run.id, seq, "compare:match", "passed", {"invoices": len(invoices), "pos": len(purchase_orders)}, None, None)
    db.commit()

    mismatches = [e for e in enriched if e.get("po_match") != "matched"]
    status_map = {"matched": "Matched", "amount_mismatch": "Mismatch", "missing_po": "No PO"}
    updated: list[str] = []
    skipped: list[str] = []
    for e in mismatches:
        inv_id = str(e.get("InvoiceID", ""))
        res = rows.update_row_field(
            db, run_id=run.id, alias="invoice-register", filename="invoices.csv",
            key_field="InvoiceID", key_value=inv_id, field="POStatus",
            new_value=status_map[e["po_match"]], purpose="invoice-po-compare",
            effect_ns="compare")
        (skipped if res.get("skipped") else updated).append(inv_id)
    seq += 1
    _node_record(db, run.id, seq, "compare:update_rows", "passed",
                 {"updated": updated, "skipped": skipped}, None, None)
    db.commit()

    drafted: list[str] = []
    for e in mismatches:
        inv_id = str(e.get("InvoiceID", ""))
        body_line = (f"Invoice {inv_id} for PO {e.get('PONumber', '')}: "
                     f"{e.get('po_match')} (invoice {e.get('Amount', '')} vs PO {e.get('po_amount', '')})")
        res = rows.create_draft(
            db, run_id=run.id, record_key=f"invoice:{inv_id}", row=e,
            template_id="po_mismatch_en",
            destination="in_app", run_date="compare", purpose="invoice-po-draft",
            templates={"po_mismatch_en": body_line}, format_fields={})
        (skipped if res.get("skipped") else drafted).append(f"invoice:{inv_id}")
    seq += 1
    _node_record(db, run.id, seq, "compare:drafts", "passed",
                 {"drafted": drafted}, None, None)
    db.commit()

    seq += 1
    _node_record(db, run.id, seq, "compare:notify", "passed", {"notified": True}, None, None)
    db.commit()
    run.status = "passed"
    run.ended_at = datetime.now(timezone.utc)
    db.commit()
    audit_mod.append(db, "run.completed",
                     {"run_id": run.id, "status": "passed", "workflow": "invoice-po-compare",
                      "matched": len(enriched) - len(mismatches),
                      "updated": updated, "drafted": drafted, "skipped": skipped})
    db.commit()
    return {"run_id": run.id, "status": "passed",
            "matched": len(enriched) - len(mismatches),
            "mismatched": len(mismatches), "updated": updated,
            "drafted": drafted, "skipped": skipped}


def _compare_version_id(db: Session) -> str:
    """A stable pseudo-version for compare runs (keeps runs.version_id satisfied)."""
    from backend.models import Workflow, WorkflowVersion
    wf = db.get(Workflow, "wf_invoice_po_compare")
    if wf is None:
        wf = Workflow(id="wf_invoice_po_compare", name="Invoice/PO comparison", demo=False)
        db.add(wf)
        db.commit()
    version = (db.query(WorkflowVersion)
               .filter(WorkflowVersion.workflow_id == "wf_invoice_po_compare")
               .order_by(WorkflowVersion.version.desc()).first())
    if version is None:
        version = WorkflowVersion(id=str(uuid.uuid4()), workflow_id="wf_invoice_po_compare",
                                  version=1, graph_json=json.dumps({"kind": "compare"}),
                                  artifact_sha256="compare", changelog="phase 8 second workflow")
        db.add(version)
        db.commit()
    return version.id
