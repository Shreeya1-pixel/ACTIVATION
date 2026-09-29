"""One-shot dev-DB hygiene: soft-delete historical test junk workflows.

Junk classes (all created by earlier test/dev phases, none by users):
  - wf-<8hex>            (old automated test-runner ids)
  - wf-stale-*           (stale-queue test fixtures)
  - wf-hook-*/wf-sched-*/wf-br-*/wf-gate-* with generic names
    ("hook wf", "sched wf", "branch", "gated")
  - wf-roundN-*          (probe round fixtures)

Real workflows (wf_client_followup, wf_lifecycle, wf_invoice_po_compare, and
anything else) are NEVER touched. Soft delete only: sets deleted_at via the
product's own model semantics; runs/versions/audit stay intact; reversible by
clearing deleted_at.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.db import SessionLocal
from backend.models import Trigger, Workflow

JUNK_NAMES = {"hook wf", "sched wf", "branch", "gated", "rb", "bad", "ids", "conc", "inj", "g"}
PREFIXED = ("wf-hook-", "wf-sched-", "wf-br-", "wf-gate-", "wf-stale-", "wf-round",
            "wf-rb-", "wf-hard-", "wf-conc-", "wf-inj-", "wf-dbg-")
HEX8 = re.compile(r"^wf-[0-9a-f]{8}$")

PROTECTED = {"wf_client_followup", "wf_lifecycle", "wf_invoice_po_compare"}


def is_junk(wf: Workflow) -> bool:
    if wf.id in PROTECTED or wf.deleted_at is not None:
        return False
    if HEX8.match(wf.id):
        return True
    if any(wf.id.startswith(p) for p in PREFIXED):
        if wf.id.startswith(("wf-stale-", "wf-round", "wf-dbg-")):
            return True
        return wf.name in JUNK_NAMES
    return False


def main(apply: bool) -> None:
    with SessionLocal() as db:
        rows = [w for w in db.query(Workflow).all() if is_junk(w)]
        total = db.query(Workflow).filter(Workflow.deleted_at.is_(None)).count()
        print(f"active workflows: {total}; junk matches: {len(rows)}")
        for w in rows[:12]:
            print(f"  - {w.id}  ({w.name!r})")
        if len(rows) > 12:
            print(f"  ... and {len(rows) - 12} more")
        if not apply:
            print("DRY RUN — rerun with --apply to soft-delete these.")
            return
        n = 0
        for w in rows:
            w.deleted_at = datetime.now(timezone.utc)
            for t in db.query(Trigger).filter(Trigger.workflow_id == w.id).all():
                t.enabled = False
            n += 1
        db.commit()
        print(f"soft-deleted {n} junk workflows (history retained); "
              f"active now: {db.query(Workflow).filter(Workflow.deleted_at.is_(None)).count()}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
