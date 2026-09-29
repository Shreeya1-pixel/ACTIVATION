"""Spike S7 integration: ai:auto drafts flow through the same journal path as static templates."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.engine import rows as rows_mod  # noqa: E402
from backend.spike_config import RUN_DATE  # noqa: E402
from tests.spike.conftest import isolated_db  # noqa: E402,F401 (fixture import)


def test_ai_auto_draft_exactly_once(isolated_db):
    db = isolated_db()
    try:
        # Unique key per invocation: the spike DB persists between runs, and the journal
        # must keep prior claims (that IS exactly-once). A fresh key guarantees this test
        # exercises a fresh claim each time.
        record_key = f"sample:C888-{time.time_ns()}"
        row = {"ClientID": "C888", "Name": "AI Client", "FollowUpDate": RUN_DATE}
        first = rows_mod.create_draft(db, run_id="run-ai-1", record_key=record_key, row=row,
                                      template_id="ai:auto", destination="in_app", run_date=RUN_DATE)
        assert first["skipped"] is False
        assert first["body"].startswith("[mock:")
        second = rows_mod.create_draft(db, run_id="run-ai-2", record_key=record_key, row=row,
                                       template_id="ai:auto", destination="in_app", run_date=RUN_DATE)
        assert second["skipped"] is True
        assert second["reason"] == "idempotent-claimed"
    finally:
        db.close()


def test_ai_auto_draft_deterministic_body():
    # Same context → same body: the mock provider hash-seeds (prompt, context).
    from backend.engine import ai
    assert ai.generate_text("p", {"a": 1}) == ai.generate_text("p", {"a": 1})
