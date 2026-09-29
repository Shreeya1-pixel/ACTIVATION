"""Load the bundled SAMPLE workspace so detection can be seen without preparing files.

    python scripts/load_demo.py

Replays demo_data/timeline.json through the real sheet diff into the local database,
runs detection, and copies the sample sheets into the watched folder. Safe to re-run.
Works with or without the worker running (both use the same local database).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend import app as _app  # noqa: E402,F401  (runs schema creation + migrations)
from backend import demo  # noqa: E402
from backend.db import SessionLocal  # noqa: E402
from backend.security import audit as audit_mod  # noqa: E402


def main() -> int:
    with SessionLocal() as db:
        try:
            result = demo.load(db)
        except demo.DemoError as exc:
            print(f"demo load failed: {exc}")
            return 1
        audit_mod.append(db, "demo.loaded", {"events": result["events_new"], "files": result["files"]})
        db.commit()
    print("SAMPLE DATA loaded (invented companies and identifiers)")
    print(f"  sheets copied to: {result['folder']}")
    print(f"  saves replayed -> events: {result['events_replayed']} ({result['events_new']} new)")
    print("  detection results:")
    for c in result["candidates"]:
        flag = "DETECTED " if c["status"] == "suggested" else "not yet  "
        steps = " -> ".join(c["sequence"])
        print(f"   {flag} {c['occurrences']} instances / {c['distinct_clients']} records  "
              f"{c['resource']}: {steps}")
    print("Open the app: Discovery shows the detected patterns; Create > Plan turns one into an automation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
