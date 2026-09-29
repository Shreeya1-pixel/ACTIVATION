"""Load the bundled SAMPLE workspace (demo_data/) so detection can be seen in minutes.

demo_data/ holds three messy sample sheets and a timeline of saves. Each save is
written to disk and read back through the real capture parser and diff
(backend.capture.sheets), so the events are exactly what the watcher would have
produced had a clerk made those saves. Events are labelled source="sample_replay" and
timestamped over the 28 days before loading. Event IDs are deterministic, so loading
twice adds nothing.

All names, TRNs, licence numbers and emails in demo_data/ are invented.
"""
from __future__ import annotations

import csv
import io
import json
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from backend.capture import config as capture_config
from backend.capture import sheets
from backend.capture.ingest import store_events
from backend.capture.watcher import diff_events
from backend.detection.service import refresh_from_events
from backend.models import Candidate, Event

DEMO_DIR = Path(__file__).resolve().parents[1] / "demo_data"
_NS = uuid.UUID("6f1c7a52-3b1e-4c55-9d7e-0a5e1d2c9b40")
DAYS_BACK = 28


class DemoError(RuntimeError):
    pass


def _read_raw(path: Path) -> list[list[str]]:
    return list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))


def _write_raw(path: Path, raw: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(raw)


def _apply(raw: list[list[str]], id_col: str, rid: str, step: dict) -> None:
    header = raw[0]
    idx = {name.strip(): i for i, name in enumerate(header)}
    if "add" in step:
        row = [""] * len(header)
        row[idx[id_col]] = rid
        for col, val in step["add"].items():
            row[idx[col]] = val
        raw.append(row)
        return
    target = next((r for r in raw[1:] if len(r) > idx[id_col] and r[idx[id_col]].strip() == rid), None)
    if target is None:
        raise DemoError(f"timeline refers to unknown ID {rid}")
    for col, val in step["set"].items():
        if col not in idx:
            raise DemoError(f"timeline refers to unknown column {col!r}")
        while len(target) <= idx[col]:
            target.append("")
        target[idx[col]] = val


def replay(base_time: datetime | None = None) -> tuple[list[dict], dict[str, list[list[str]]], dict]:
    """Pure replay: returns (events, final raw sheets by filename, timeline)."""
    tl_path = DEMO_DIR / "timeline.json"
    if not tl_path.is_file():
        raise DemoError(f"demo timeline not found at {tl_path}")
    timeline = json.loads(tl_path.read_text(encoding="utf-8"))
    id_cols: dict[str, str] = timeline["id_columns"]
    base = base_time or (datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                         - timedelta(days=DAYS_BACK))
    raws = {name: _read_raw(DEMO_DIR / name) for name in id_cols}
    steps = []
    for ri, run in enumerate(timeline["runs"]):
        hh, mm = (int(x) for x in run["time"].split(":"))
        start = base + timedelta(days=run["day"], hours=hh, minutes=mm)
        for si, step in enumerate(run["steps"]):
            steps.append((start + timedelta(minutes=step["after_min"]), ri, si, run, step))
    steps.sort(key=lambda s: (s[0], s[1], s[2]))

    events: list[dict] = []
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        prev: dict[str, sheets.Sheet] = {}
        for name, raw in raws.items():
            _write_raw(tdir / name, raw)
            prev[name] = sheets.read_sheet(tdir / name, id_cols[name])
        for at, ri, si, run, step in steps:
            name = run["file"]
            _apply(raws[name], id_cols[name], run["id"], step)
            _write_raw(tdir / name, raws[name])
            now_sheet = sheets.read_sheet(tdir / name, id_cols[name])
            stem = Path(name).stem
            for k, ev in enumerate(diff_events(prev[name], now_sheet, None, resource=f"watched/{stem}",
                                               file_label=stem, captured_at=at.isoformat(),
                                               source="sample_replay")):
                ev["event_id"] = str(uuid.uuid5(_NS, f"{name}|{ri}|{si}|{k}|{ev['action']}|{ev['record_key']}"))
                events.append(ev)
            prev[name] = now_sheet
    return events, raws, timeline


def load(db: Session) -> dict:
    events, raws, timeline = replay()
    accepted = store_events(db, events)
    detection = refresh_from_events(db)

    folder = capture_config.folder()
    folder.mkdir(parents=True, exist_ok=True)
    for name, raw in raws.items():
        _write_raw(folder / name, raw)
    cfg = capture_config.load()
    files = dict(cfg.get("files") or {})
    for name, col in timeline["id_columns"].items():
        files.setdefault(name, {"id_column": col, "columns": None, "sheet": None})
    capture_config.save(None, files)

    resources = {f"watched/{Path(n).stem}" for n in raws}
    cands = []
    for c in db.query(Candidate).all():
        pattern = json.loads(c.pattern_json)
        if pattern.get("resource") in resources:
            ev = json.loads(c.evidence_json)
            cands.append({"resource": pattern["resource"], "sequence": pattern["sequence"],
                          "occurrences": c.occurrences, "distinct_clients": ev.get("distinct_clients"),
                          "status": c.status})
    cands.sort(key=lambda c: (c["status"] != "suggested", -c["occurrences"]))
    return {"files": sorted(raws), "folder": str(folder), "events_replayed": len(events),
            "events_new": len(accepted),
            "events_total": db.query(Event).filter(Event.source == "sample_replay").count(),
            "detection": detection, "candidates": cands,
            "note": "SAMPLE DATA: invented companies and identifiers, replayed through the real sheet diff"}
