"""Folder capture watcher — bounded polling, settling, honest events.

Rules:
  - Watches one configured folder by polling (no filesystem hooks that could claim
    live Excel edits or clipboard content — the watcher only ever reads STABLE files).
  - Settling: a file is only parsed once its size+mtime have been unchanged for
    `settle_seconds`; otherwise the poll records a gap (no invented events).
  - Any CSV/XLSX layout: the ID column and tracked columns come from per-file settings
    (auto-suggested ID when unset). Added/removed/updated rows become contract events.
  - Redaction by default: record_keys are `<file>:<ID>` tokens and only column NAMES are
    recorded; no cell contents are copied into events.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from backend.capture import sheets


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_settings(_name: str) -> dict:
    return {"id_column": None, "columns": None, "sheet": None}


class FolderWatcher:
    """Polls a folder and emits events for stable CSV/XLSX changes."""

    def __init__(self, folder: Path, alias: str = "watched", settle_seconds: float = 5.0,
                 max_file_bytes: int = 5_000_000, max_poll_files: int = 50,
                 settings: Callable[[str], dict] | None = None):
        self.folder = Path(folder)
        self.alias = alias
        self.settle_seconds = settle_seconds
        self.max_file_bytes = max_file_bytes
        self.max_poll_files = max_poll_files
        self.settings = settings or _default_settings
        self.state: dict[str, dict] = {}   # key -> {"sha256", "snapshot", "settings"}
        self._stat_cache: dict[str, dict] = {}
        self.gaps: list[dict] = []
        self.MAX_GAPS = 100

    def _list_candidate_files(self) -> list[Path]:
        if not self.folder.is_dir():
            return []
        files = [p for p in self.folder.iterdir()
                 if p.is_file() and p.suffix.lower() in (".csv", ".xlsx")
                 and not p.name.startswith(("~$", "."))  # office lock files / hidden files
                 and p.stat().st_size <= self.max_file_bytes]
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:self.max_poll_files]

    def _gap(self, name: str, reason: str) -> None:
        self.gaps.append({"file": name, "reason": reason, "at": _now_iso()})
        if len(self.gaps) > self.MAX_GAPS:
            del self.gaps[:-self.MAX_GAPS]

    def _settled(self, path: Path) -> bool:
        try:
            st1 = path.stat()
        except OSError:
            return False
        time.sleep(self.settle_seconds)
        try:
            st2 = path.stat()
        except OSError:
            return False
        return (st1.st_size, st1.st_mtime_ns) == (st2.st_size, st2.st_mtime_ns)

    def poll(self) -> list[dict]:
        events: list[dict] = []
        for path in self._list_candidate_files():
            name = path.name
            settings = self.settings(name)
            try:
                st_now = path.stat()
                key_stat = f"stat:{self.alias}:{name}"
                prev_stat = self._stat_cache.get(key_stat)
                unchanged_stat = (prev_stat is not None and prev_stat["size"] == st_now.st_size
                                  and prev_stat["mtime"] == st_now.st_mtime_ns)
                if not unchanged_stat:
                    if not self._settled(path):
                        self._gap(name, "unsettled")
                        continue
                    try:
                        st_after = path.stat()
                    except OSError:
                        st_after = st_now
                    self._stat_cache[key_stat] = {"size": st_after.st_size, "mtime": st_after.st_mtime_ns}
                payload = path.read_bytes()
                key = f"{self.alias}:{name}"
                prev = self.state.get(key)
                digest = hashlib.sha256(payload).hexdigest()
                if prev is not None and prev["sha256"] == digest and prev["settings"] == settings:
                    continue
                sheet = sheets.read_sheet(path, settings["id_column"], settings["sheet"])
            except Exception as exc:  # noqa: BLE001 - parser errors become gaps, never events
                self._gap(name, f"parse-error: {exc}"[:160])
                continue
            if prev is None or prev["settings"] != settings or prev["snapshot"].id_column != sheet.id_column:
                self.state[key] = {"sha256": digest, "snapshot": sheet, "settings": settings}
                continue  # first sight (or re-configured) = baseline, not an event
            now = _now_iso()
            events.extend(diff_events(prev["snapshot"], sheet, settings["columns"],
                                      resource=f"{self.alias}/{path.stem}"[:120],
                                      file_label=path.stem, captured_at=now))
            self.state[key] = {"sha256": digest, "snapshot": sheet, "settings": settings}
        return events


def diff_events(before: sheets.Sheet, after: sheets.Sheet, columns: list[str] | None, *,
                resource: str, file_label: str, captured_at: str,
                source: str = "saved_file_comparison") -> list[dict]:
    diff = sheets.compare(before, after, columns)
    out = []
    for rid in diff["added"]:
        out.append(make_event("row.added", f"{file_label}:{rid}", resource, captured_at, source=source))
    for rid in diff["removed"]:
        out.append(make_event("row.removed", f"{file_label}:{rid}", resource, captured_at, source=source))
    for upd in diff["updated"]:
        out.append(make_event("row.updated", f"{file_label}:{upd['id']}", resource, captured_at,
                              changed_fields=upd["changed_fields"][:32], source=source))
    return out


def make_event(action: str, record_key: str, resource: str, captured_at: str, *,
               changed_fields=None, source: str = "saved_file_comparison",
               event_id: str | None = None) -> dict:
    # v2 contract: the concrete file path stays out of the event (private-path hygiene).
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "schema_version": 2,
        "source_version": "capture-sheets-0.2.0",
        "source": source,
        "action": action,
        "resource": resource,
        "record_key": record_key[:160],
        "changed_fields": [f[:64] for f in (changed_fields or [])],
        "outcome": "success",
        "captured_at": captured_at,
        "processed_at": max(captured_at, _now_iso()),
        "synthetic": False,
    }
