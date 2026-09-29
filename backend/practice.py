"""Practice workspace: a real folder with one blank-history sheet that the user edits.

Nothing here is replayed or pre-recorded. Every event comes from comparing the saved
file before and after the user's own edit (the same watcher as any folder), plus an
explicit "done with this row" marker, because detection otherwise waits for 10 quiet
minutes before it trusts that a routine on a row is finished.
"""
from __future__ import annotations

import csv
import io
import json
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import Candidate, Event
from backend.security import safeio
from backend.security.tokens import require_token, require_writer
from backend.spike_config import DATA_DIR

router = APIRouter(prefix="/api/practice")

FOLDER = DATA_DIR / "practice-workspace"
FILENAME = "practice_invoices.csv"
STEM = FILENAME.rsplit(".", 1)[0]
RESOURCE = f"watched/{STEM}"
ID_COLUMN = "Invoice No"
HEADER = ["Invoice No", "Vendor", "Amount (AED)", "Due Date", "Status", "Checked By", "Payment Requested"]
STARTER = [
    ["INV-2001", "Desert Line Logistics", "4,250.00", "2026-10-05", "Received", "", "No"],
    ["INV-2002", "Palm Office Supplies", "1,180.50", "2026-10-06", "Received", "", "No"],
    ["INV-2003", "Gulf Print House", "2,960.00", "2026-10-07", "Received", "", "No"],
    ["INV-2004", "Marina Catering LLC", "3,400.00", "2026-10-08", "Received", "", "No"],
    ["INV-2005", "Creek IT Services", "7,815.25", "2026-10-09", "Received", "", "No"],
    ["INV-2006", "Oasis Cleaning Co", "950.00", "2026-10-10", "Received", "", "No"],
    ["INV-2007", "Falcon Courier", "610.75", "2026-10-11", "Received", "", "No"],
    ["INV-2008", "Dune Stationers", "1,425.00", "2026-10-12", "Received", "", "No"],
]
MAX_ROWS = 200
MAX_CELL = 120
STATUS_HINT = ("status", "stage", "state")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _app():
    from backend import app as app_mod  # lazy: app imports this router
    return app_mod


def _write(header: list[str], body: list[list[str]]) -> None:
    out = io.StringIO()
    csv.writer(out).writerows([header, *body])
    safeio.write_resource("watched", FILENAME, out.getvalue().encode("utf-8"), backup=False)


def _read() -> tuple[list[str], list[dict]]:
    from backend.capture import sheets
    header, rows, _ = sheets.read_table(safeio.resolve_resource("watched", FILENAME))
    return header, rows


def _is_active() -> bool:
    from backend.capture import config as capture_config
    try:
        return capture_config.folder().resolve() == FOLDER.resolve() and (FOLDER / FILENAME).is_file()
    except OSError:
        return False


def _rebaseline() -> None:
    """Take the file as it is now as the new 'before' (no events), e.g. after an
    automation run changed it, so the app's own writes are never learned as user work."""
    w = _app()._capture_watcher()
    w.state.pop(f"{w.alias}:{FILENAME}", None)
    w._stat_cache.pop(f"stat:{w.alias}:{FILENAME}", None)
    w.poll()


def _candidates(db: Session) -> list[dict]:
    out = []
    for c in db.query(Candidate).all():
        pattern = json.loads(c.pattern_json)
        if pattern.get("resource") != RESOURCE:
            continue
        out.append({"id": c.id, "status": c.status, "occurrences": c.occurrences,
                    "pattern": pattern, "evidence": json.loads(c.evidence_json)})
    return out


def _progress(db: Session) -> dict:
    """How far the user's own routine is from the detection rule (3 done, 2+ rows)."""
    from backend.detection import sequences
    from backend.detection.service import _event_dict
    events = [_event_dict(e) for e in db.query(Event).filter(Event.resource == RESOURCE)
              .order_by(Event.captured_at).all()]
    done = [i for i in sequences.build_instances(events) if i["status"] == "ok"]
    by_seq = Counter(tuple(i["sequence"]) for i in done)
    best = by_seq.most_common(1)[0] if by_seq else ((), 0)
    rows_done = sorted({i["stream"].split(":", 1)[-1] for i in done if tuple(i["sequence"]) == best[0]})
    return {"completed_rows": rows_done, "repeats": best[1], "needed": sequences.THRESHOLD_OCCURRENCES}


@router.post("/start", dependencies=[Depends(require_writer)])
def start(db: Session = Depends(get_db)):
    """Create (or reset) the practice folder, point capture at it, clear its history."""
    from backend.capture import config as capture_config
    previous = str(capture_config.folder())
    FOLDER.mkdir(parents=True, exist_ok=True)
    cfg = capture_config.load()
    files = dict(cfg.get("files") or {})
    files[FILENAME] = {"id_column": ID_COLUMN, "columns": None, "sheet": None}
    capture_config.save(str(FOLDER), files)
    _write(HEADER, [list(r) for r in STARTER])
    db.query(Event).filter(Event.resource == RESOURCE).delete()
    for c in db.query(Candidate).all():
        if json.loads(c.pattern_json).get("resource") == RESOURCE:
            db.delete(c)
    db.commit()
    _rebaseline()
    return {"folder": str(FOLDER), "file": FILENAME, "previous_folder": previous,
            "header": HEADER, "id_column": ID_COLUMN}


@router.get("/sheet", dependencies=[Depends(require_token)])
def sheet(db: Session = Depends(get_db)):
    if not _is_active():
        return {"active": False, "folder": str(FOLDER)}
    header, rows = _read()
    return {"active": True, "folder": str(FOLDER), "file": FILENAME, "id_column": ID_COLUMN,
            "header": header, "rows": rows, "progress": _progress(db), "candidates": _candidates(db)}


class SaveBody(BaseModel):
    rows: list[dict]


@router.post("/save", dependencies=[Depends(require_writer)])
def save(body: SaveBody, db: Session = Depends(get_db)):
    """Write the grid to the real file (like pressing Save in Excel), then run the
    normal watcher pass over the folder and report what it saw."""
    if not _is_active():
        raise HTTPException(status_code=409, detail={"error": "start the practice workspace first"})
    header, _ = _read()
    if not body.rows or len(body.rows) > MAX_ROWS:
        raise HTTPException(status_code=400, detail={"error": f"1 to {MAX_ROWS} rows required"})
    seen: set[str] = set()
    out_rows: list[list[str]] = []
    for r in body.rows:
        values = [str(r.get(col, "") if r.get(col) is not None else "") for col in header]
        if any(len(v) > MAX_CELL for v in values):
            raise HTTPException(status_code=400, detail={"error": f"cells are limited to {MAX_CELL} characters"})
        if any(v.lstrip().startswith(("=", "+", "@")) for v in values):
            raise HTTPException(status_code=400, detail={"error": "formulas are not supported in practice cells"})
        rid = values[header.index(ID_COLUMN)].strip()
        if not rid or rid in seen:
            raise HTTPException(status_code=400, detail={"error": f"each row needs a unique {ID_COLUMN}"})
        seen.add(rid)
        out_rows.append(values)
    _write(header, out_rows)
    polled = _app().capture_poll(db)
    changes = []
    for eid in polled.get("accepted", []):
        ev = db.query(Event).filter(Event.event_id == eid).first()
        if ev is not None:
            changes.append({"action": ev.action, "row": ev.record_key.split(":", 1)[-1],
                            "columns": json.loads(ev.changed_fields_json or "[]")})
    return {"events": polled.get("events", 0), "changes": changes, "gaps": polled.get("gaps", [])[-3:],
            "progress": _progress(db), "candidates": _candidates(db)}


class DoneBody(BaseModel):
    row_id: str


@router.post("/done", dependencies=[Depends(require_writer)])
def done(body: DoneBody, db: Session = Depends(get_db)):
    """The user says 'I've finished this row'. Closes the routine on that row now
    instead of waiting 10 quiet minutes."""
    from backend.capture.ingest import store_events
    from backend.capture.watcher import make_event
    from backend.detection.service import refresh_from_events
    if not _is_active():
        raise HTTPException(status_code=409, detail={"error": "start the practice workspace first"})
    _, rows = _read()
    if body.row_id not in {r.get(ID_COLUMN) for r in rows}:
        raise HTTPException(status_code=404, detail={"error": "row not found"})
    ev = make_event("task.completed", f"{STEM}:{body.row_id}", RESOURCE, _now(), source="practice_workspace")
    store_events(db, [ev])
    detection = refresh_from_events(db)
    return {"detection": detection, "progress": _progress(db), "candidates": _candidates(db)}


class OpenBody(BaseModel):
    target: str = "excel"


@router.post("/open", dependencies=[Depends(require_writer)])
def open_file(body: OpenBody):
    """Open the practice sheet in Excel (or reveal it) on the machine running the
    worker. Only for a worker on this computer; a hosted worker has no screen."""
    import os
    import subprocess
    import sys
    if not _is_active():
        raise HTTPException(status_code=409, detail={"error": "start the practice workspace first"})
    if os.environ.get("AUTOSTACK_HOST", "127.0.0.1") not in ("127.0.0.1", "localhost"):
        raise HTTPException(status_code=409, detail={"error": "opening files only works when AutoStack runs on your own computer"})
    path = str((FOLDER / FILENAME).resolve())
    if sys.platform == "darwin":
        if body.target == "finder":
            cmd = ["open", "-R", path]
        else:
            cmd = ["open", "-a", "Microsoft Excel", path]
        if subprocess.run(cmd, capture_output=True, timeout=10).returncode != 0:
            subprocess.run(["open", path], capture_output=True, timeout=10)
    elif sys.platform == "win32":
        if body.target == "finder":
            subprocess.run(["explorer", "/select,", path], timeout=10)
        else:
            os.startfile(path)  # noqa: S606 - fixed path inside the practice folder
    else:
        raise HTTPException(status_code=409, detail={"error": "opening files is supported on macOS and Windows"})
    return {"opened": f"opened {FILENAME} {'in Finder' if body.target == 'finder' else 'in Excel'}"}


@router.post("/rebaseline", dependencies=[Depends(require_writer)])
def rebaseline():
    if not _is_active():
        raise HTTPException(status_code=409, detail={"error": "start the practice workspace first"})
    _rebaseline()
    return {"ok": True}


def _parse_step(step: str) -> list[str]:
    if "[" in step and step.endswith("]"):
        return [f.strip() for f in step[step.index("[") + 1:-1].split(",") if f.strip()]
    return []


class SuggestBody(BaseModel):
    candidate_id: str


@router.post("/suggest-plan", dependencies=[Depends(require_writer)])
def suggest_plan(body: SuggestBody, db: Session = Depends(get_db)):
    """Turn an identified routine into a plan by reading the sheet as it is now: the
    columns the routine changed, the value every processed row ended with, and the
    value the rows still waiting have. The user confirms it before any code exists."""
    from backend.capture import config as capture_config
    from backend.capture import sheets
    cand = db.get(Candidate, body.candidate_id)
    if cand is None:
        raise HTTPException(status_code=404, detail={"error": "candidate not found"})
    pattern, evidence = json.loads(cand.pattern_json), json.loads(cand.evidence_json)
    resource = pattern.get("resource", "")
    if not resource.startswith("watched/"):
        raise HTTPException(status_code=422, detail={"error": "only patterns from the watched folder can be automated here"})
    stem = resource.split("/", 1)[1]
    matches = [p for p in capture_config.folder().glob(f"{stem}.*") if p.is_file()]
    csv_file = next((p for p in matches if p.suffix.lower() == ".csv"), None)
    if csv_file is None:
        raise HTTPException(status_code=422, detail={"error": "automations can update CSV files only; save the sheet as CSV"})
    header, rows, _ = sheets.read_table(csv_file)
    settings = capture_config.file_settings(capture_config.load(), csv_file.name)
    id_col = settings.get("id_column") or sheets.suggest_id_column(header, rows)
    if not id_col or id_col not in header:
        raise HTTPException(status_code=422, detail={"error": "set the ID column for this file in Capture settings"})
    changed: list[str] = []
    for step in evidence.get("steps") or pattern.get("sequence") or []:
        for f in _parse_step(step):
            if f in header and f != id_col and f not in changed:
                changed.append(f)
    processed = {k.split(":", 1)[-1] for k in (evidence.get("per_client") or {})}
    done_rows = [r for r in rows if r.get(id_col) in processed]
    waiting = [r for r in rows if r.get(id_col) not in processed]
    set_fields: dict[str, str] = {}
    manual: list[str] = []
    for col in changed:
        values = {r.get(col, "") for r in done_rows}
        if len(values) == 1 and next(iter(values)) != "":
            set_fields[col] = next(iter(values))
        else:
            manual.append(col)
    if not set_fields:
        raise HTTPException(status_code=422, detail={"error": "your processed rows don't end with one shared value, so there is no single rule to automate"})
    status_col = next((c for c in set_fields if any(h in c.lower() for h in STATUS_HINT)), next(iter(set_fields)))
    before = Counter(r.get(status_col, "") for r in waiting if r.get(status_col, "") != set_fields[status_col])
    if not before:
        raise HTTPException(status_code=422, detail={"error": "every row is already processed; add or reset a row so there is work left to automate"})
    from_value = before.most_common(1)[0][0]
    from backend.engine.graph_build import safe_literal
    from backend.engine.generation import PlanError
    try:
        for v in [from_value, *set_fields.values()]:
            safe_literal(v)
    except PlanError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc)})
    plan = {
        "client_id_field": id_col,
        "field_mappings": {id_col: id_col},
        "eligibility": {"status_field": status_col, "status": from_value},
        "action": "update_status",
        "destinations": ["in_app"],
        "resource_alias": "watched",
        "resource_filename": csv_file.name,
        "set_fields": set_fields,
        "purpose": f"auto-{cand.id[:8]}",
    }
    would_match = [r.get(id_col) for r in rows if r.get(status_col) == from_value]
    return {"plan": plan, "file": csv_file.name, "learned_from": sorted(processed),
            "would_match_now": would_match, "left_manual": manual,
            "values": {c: sorted({r.get(c, "") for r in rows}) for c in [status_col, *set_fields]}}
