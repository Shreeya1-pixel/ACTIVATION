"""Generic capture: any ID column, messy sheets, XLSX, configurable folder, and the
bundled sample workspace that makes detection visible without preparing files."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.capture import config as capture_config  # noqa: E402
from backend.capture import sheets  # noqa: E402
from backend.capture.watcher import FolderWatcher  # noqa: E402
from tests.spike.conftest import isolated_db_module, test_session  # noqa: E402,F401 (fixture import)

client = TestClient(app)
H = {"Authorization": "Bearer testtoken"}

MESSY = (
    "Vendor Code,Vendor Name,Invoice Date,Amount (AED),Status,\n"
    "VND-1042,Al Noor Trading,28/08/2026,\"AED 48,500.00\",Pending,\n"
    ",Walk-in,03/09/2026,640,Paid,\n"
    ",,,,,\n"
    "VND-1057,Falcon Electricals,2026-08-27,112000,Verified\n"
)


def _w(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ── parser ───────────────────────────────────────────────────────────────────

def test_messy_sheet_reads_with_suggested_id(tmp_path):
    s = sheets.read_sheet(_w(tmp_path / "v.csv", MESSY))
    assert s.id_column == "Vendor Code"
    assert set(s.rows) == {"VND-1042", "VND-1057"}
    assert s.skipped_blank_ids == 1 and s.skipped_blank_rows == 1
    assert s.header == ["Vendor Code", "Vendor Name", "Invoice Date", "Amount (AED)", "Status"]


def test_any_id_format_is_accepted_but_duplicates_are_not(tmp_path):
    ok = sheets.read_sheet(_w(tmp_path / "a.csv", "Emp No,Name\n7,A\nX-99/b,B\n"), "Emp No")
    assert set(ok.rows) == {"7", "X-99/b"}
    with pytest.raises(sheets.InvalidSheet, match="duplicate ID"):
        sheets.read_sheet(_w(tmp_path / "b.csv", "Emp No,Name\n7,A\n7,B\n"), "Emp No")
    with pytest.raises(sheets.InvalidSheet, match="not in this file"):
        sheets.read_sheet(_w(tmp_path / "c.csv", "Emp No,Name\n7,A\n"), "Vendor Code")
    with pytest.raises(sheets.InvalidSheet, match="duplicate column"):
        sheets.read_sheet(_w(tmp_path / "d.csv", "ID,Name,name\n1,A,B\n"))


def test_reformatting_is_not_a_change_but_real_edits_are(tmp_path):
    before = sheets.read_sheet(_w(tmp_path / "v.csv", MESSY))
    after_text = (MESSY.replace("28/08/2026", "28 Aug 2026").replace("\"AED 48,500.00\"", "48500")
                  .replace("VND-1057,Falcon Electricals,2026-08-27,112000,Verified",
                           "VND-1057,Falcon Electricals,2026-08-27,112000,Paid"))
    after = sheets.read_sheet(_w(tmp_path / "v.csv", after_text))
    diff = sheets.compare(before, after)
    assert diff == {"added": [], "removed": [], "updated": [{"id": "VND-1057", "changed_fields": ["Status"]}]}
    assert sheets.compare(before, after, columns=["Invoice Date"])["updated"] == []


def test_normalize_handles_mixed_date_and_currency_formats():
    assert sheets.normalize("05/09/2026") == sheets.normalize("5 Sep 2026") == "2026-09-05"
    assert sheets.normalize("AED 112,000.00") == sheets.normalize("112000") == "112000"
    assert sheets.normalize("Dhs 3,250") == sheets.normalize("3250 AED") == "3250"
    assert sheets.normalize("₹1,12,000.00") == "112000"
    assert sheets.normalize("  Payment   requested ") == "Payment requested"


def test_xlsx_reads_like_csv(tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Vendors"
    ws.append(["Vendor Code", "Amount (AED)", "Invoice Date"])
    from datetime import datetime
    ws.append(["VND-1", 48500, datetime(2026, 8, 28)])
    ws.append(["VND-2", 1200.0, "03/09/2026"])
    wb.save(tmp_path / "v.xlsx")
    s = sheets.read_sheet(tmp_path / "v.xlsx")
    assert s.id_column == "Vendor Code"
    assert s.rows["VND-1"]["Amount (AED)"] == "48500"
    assert sheets.normalize(s.rows["VND-1"]["Invoice Date"]) == "2026-08-28"


# ── watcher with per-file settings ───────────────────────────────────────────

def test_watcher_uses_configured_id_and_columns(tmp_path):
    _w(tmp_path / "pay.csv", "Emp ID,Name,Days,Notes\nE1,A,5,x\nE2,B,6,y\n")
    w = FolderWatcher(tmp_path, settle_seconds=0.01,
                      settings=lambda n: {"id_column": "Emp ID", "columns": ["Days"], "sheet": None})
    assert w.poll() == []
    _w(tmp_path / "pay.csv", "Emp ID,Name,Days,Notes\nE1,A,6,changed\nE2,B,6,changed\n")
    time.sleep(0.05)
    events = w.poll()
    assert [(e["action"], e["record_key"], e["changed_fields"]) for e in events] == \
        [("row.updated", "pay:E1", ["Days"])]
    assert events[0]["resource"] == "watched/pay"


def test_watcher_reads_xlsx_changes(tmp_path):
    from openpyxl import Workbook

    def save(status):
        wb = Workbook()
        wb.active.append(["Invoice No", "Status"])
        wb.active.append(["INV-1", status])
        wb.save(tmp_path / "inv.xlsx")

    save("Overdue")
    w = FolderWatcher(tmp_path, settle_seconds=0.01)
    assert w.poll() == []
    time.sleep(0.05)
    save("Paid")
    events = w.poll()
    assert events and events[0]["changed_fields"] == ["Status"] and events[0]["record_key"] == "inv:INV-1"


# ── config ───────────────────────────────────────────────────────────────────

def test_folder_validation(tmp_path):
    assert capture_config.validate_folder(str(tmp_path)) == tmp_path.resolve()
    for bad in ("", "relative/dir", str(tmp_path / "missing"), "/", "/etc", str(Path.home())):
        with pytest.raises(capture_config.CaptureConfigError):
            capture_config.validate_folder(bad)


@pytest.fixture(scope="module", autouse=True)
def _auth(isolated_db_module):
    from backend import roadmap_routes
    from backend.security import tokens
    originals = (tokens.get_expected_token, roadmap_routes.get_expected_token)
    tokens.get_expected_token = roadmap_routes.get_expected_token = lambda: "testtoken"
    saved = capture_config.CONFIG_FILE.read_bytes() if capture_config.CONFIG_FILE.is_file() else None
    yield
    tokens.get_expected_token, roadmap_routes.get_expected_token = originals
    if saved is None:
        capture_config.CONFIG_FILE.unlink(missing_ok=True)
    else:
        capture_config.CONFIG_FILE.write_bytes(saved)


def test_config_endpoints_and_preview(tmp_path):
    _w(tmp_path / "v.csv", MESSY)
    bad = client.post("/api/capture/config", json={"folder": "/etc"}, headers=H)
    assert bad.status_code == 422
    ok = client.post("/api/capture/config", json={"folder": str(tmp_path),
                                                  "files": {"v.csv": {"id_column": "Vendor Code"}}}, headers=H)
    assert ok.status_code == 200, ok.text
    prev = client.get("/api/capture/preview", headers=H).json()
    entry = prev["files"][0]
    assert entry["ok"] and entry["id_column_in_use"] == "Vendor Code"
    assert entry["records"] == 2 and entry["rows_without_id"] == 1
    assert "Shubh" not in str(prev)  # column names only, never cell values
    assert client.post("/api/capture/config", json={"folder": ""}, headers=H).status_code == 200


# ── sample workspace ─────────────────────────────────────────────────────────

def test_demo_replay_detects_designed_patterns_only():
    from backend import demo
    from backend.detection import sequences
    events, _, _ = demo.replay()
    cands = sequences.detect_candidates(events)
    summary = {(c["resource"].split("/")[-1], c["qualifies"], c["occurrences"],
                c["evidence"]["distinct_clients"]) for c in cands}
    assert summary == {
        ("sample_vendor_followups", True, 9, 3),
        ("sample_payroll_collation", True, 6, 2),
        ("sample_vendor_followups", False, 3, 1),   # repeated, but one vendor only
        ("sample_invoice_status", False, 2, 2),     # two clients, too few repeats
    }
    assert not [e for e in events if e["record_key"].endswith("VND-1050")]  # re-typed date only


def test_demo_load_endpoint_is_idempotent(tmp_path):
    client.post("/api/capture/config", json={"folder": str(tmp_path)}, headers=H)
    first = client.post("/api/demo/load", headers=H)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["events_new"] == body["events_replayed"] > 0
    suggested = [c for c in body["candidates"] if c["status"] == "suggested"]
    assert len(suggested) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == body["files"]
    again = client.post("/api/demo/load", headers=H).json()
    assert again["events_new"] == 0
    cands = client.get("/api/candidates", headers=H).json()
    assert sum(1 for c in cands if c["status"] == "suggested") >= 2
    client.post("/api/capture/config", json={"folder": ""}, headers=H)
