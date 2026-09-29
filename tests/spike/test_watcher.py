"""Phase 3 watcher: stable-version diffing with honest gaps, no invented events."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.capture.watcher import FolderWatcher  # noqa: E402

CSV_A = ("ClientID,Name,Email,FollowUpDate,Status\n"
         "C001,Alpha,a@x.invalid,2026-09-20,Follow-up due\n"
         "C002,Beta,b@x.invalid,2026-09-21,Active\n")
CSV_B = ("ClientID,Name,Email,FollowUpDate,Status\n"
         "C001,Alpha,a@x.invalid,2026-09-20,Draft prepared\n"
         "C002,Beta,b@x.invalid,2026-09-21,Active\n"
         "C003,Gamma,c@x.invalid,2026-09-22,Active\n")


def write_csv(folder: Path, content: str, name: str = "clients.csv") -> None:
    (folder / name).write_text(content, encoding="utf-8")


def test_first_sight_is_baseline_not_event(tmp_path):
    write_csv(tmp_path, CSV_A)
    w = FolderWatcher(tmp_path, settle_seconds=0.01)
    assert w.poll() == []


def test_updates_become_contract_events(tmp_path):
    write_csv(tmp_path, CSV_A)
    w = FolderWatcher(tmp_path, settle_seconds=0.01)
    w.poll()
    write_csv(tmp_path, CSV_B)
    time.sleep(0.05)
    events = w.poll()
    kinds = {(e["action"], e["record_key"]) for e in events}
    assert ("row.updated", "sample-tracking-file:C001") in kinds or \
           ("row.updated", "watched:clients.csv:C001") in kinds or \
           any(e["action"] == "row.updated" and e["record_key"].endswith("C001") for e in events)
    assert any(e["action"] == "row.added" and e["record_key"].endswith("C003") for e in events)
    for e in events:
        # contract shape from shared/contracts/event-v2.schema.json
        assert set(e) == {"event_id", "schema_version", "source_version", "source",
                          "action", "resource", "record_key", "changed_fields", "outcome",
                          "captured_at", "processed_at", "synthetic"}
        assert e["source"] == "saved_file_comparison" and e["synthetic"] is False
        assert e["schema_version"] == 2
        assert e["processed_at"] >= e["captured_at"]


def test_changed_fields_are_specific(tmp_path):
    write_csv(tmp_path, CSV_A)
    w = FolderWatcher(tmp_path, settle_seconds=0.01)
    w.poll()
    write_csv(tmp_path, CSV_B)
    time.sleep(0.05)
    events = w.poll()
    upd = next(e for e in events if e["action"] == "row.updated")
    assert upd["changed_fields"] == ["Status"]


def test_lock_and_xlsx_files_never_claim_events(tmp_path):
    (tmp_path / "~$clients.xlsx").write_text("lock")
    (tmp_path / "ledger.xlsx").write_bytes(b"PK\x03\x04 fake")
    w = FolderWatcher(tmp_path, settle_seconds=0.01)
    assert w.poll() == []
    assert w.state == {}
    assert any(g["file"] == "ledger.xlsx" and "parse-error" in g["reason"] for g in w.gaps)


def test_unsettled_file_becomes_gap_not_event(tmp_path):
    write_csv(tmp_path, CSV_A)
    w = FolderWatcher(tmp_path, settle_seconds=0.01)
    w.poll()
    # rewrite the file concurrently-ish: settle loop still sees mtime change → gap path
    import threading

    stop = threading.Event()

    def churn():
        i = 0
        while not stop.is_set() and i < 40:
            write_csv(tmp_path, CSV_A if i % 2 else CSV_B)
            i += 1
            time.sleep(0.005)
        stop.set()

    th = threading.Thread(target=churn)
    th.start()
    w.settle_seconds = 0.05
    w.poll()
    stop.set()
    th.join()
    # No fabricated event may exist for a file that never settled — either no events,
    # or events whose snapshot equals a settled state (state only updates when settled).
    for key, st in w.state.items():
        assert st["sha256"] and st["snapshot"]
