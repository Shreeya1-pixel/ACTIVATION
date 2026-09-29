"""Detection quality: stitching of interrupted routines, fragment folding, and the
synthetic benchmark held to measured thresholds."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.detection import sequences  # noqa: E402
from scripts import benchmark_detection as bench  # noqa: E402

T0 = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)


def ev(rid, field, at):
    return {"record_key": rid, "resource": "watched/s", "action": "row.updated",
            "changed_fields": [field], "outcome": "success", "source": "saved_file_comparison",
            "captured_at": at.isoformat()}


def routine(rid, day, pauses):
    """Steps A, B, C with the given pauses (minutes) between them."""
    t = T0 + timedelta(days=day)
    out = [ev(rid, "A", t)]
    for field, gap in zip(("B", "C"), pauses):
        t += timedelta(minutes=gap)
        out.append(ev(rid, field, t))
    return out


FULL = ["row.updated[A]", "row.updated[B]", "row.updated[C]"]


def qualifying(events):
    return [c["sequence"] for c in sequences.detect_candidates(events) if c["qualifies"]]


def test_interrupted_routine_is_stitched_back_together():
    events = []
    for rid in ("R1", "R2"):
        for day in range(4):
            events += routine(rid, day * 7, (3, 20 if day % 2 else 4))  # every other time: a 20-min pause
    assert qualifying(events) == [FULL]


def test_one_slow_day_does_not_invent_a_routine():
    events = routine("R1", 0, (20, 20)) + routine("R1", 7, (3, 3))
    assert qualifying(events) == []


def test_pauses_beyond_stitch_window_stay_separate():
    events = []
    for rid in ("R1", "R2"):
        for day in range(4):
            events += routine(rid, day * 7, (3, 90))
    seqs = qualifying(events)
    assert FULL not in seqs


def test_fragment_of_a_qualifying_routine_is_folded():
    cands = [{"sequence": FULL, "resource": "r", "qualifies": True, "record_keys": ["R1", "R2"]},
             {"sequence": FULL[1:], "resource": "r", "qualifies": True, "record_keys": ["R1"]}]
    sequences._fold_fragments(cands)
    assert cands[0]["qualifies"] and not cands[1]["qualifies"]
    assert cands[1]["folded_into"] == FULL


def test_benchmark_clean_is_exact():
    r = bench.run(60, seed=11)
    assert r["precision"] == 1.0 and r["recall"] == 1.0 and r["near_misses"] > 0


def test_benchmark_with_interrupted_users_stays_strong():
    r = bench.run(60, seed=11, slow_rate=0.05)
    assert r["precision"] >= 0.98 and r["recall"] >= 0.98
    r = bench.run(60, seed=11, slow_rate=0.15)
    assert r["precision"] >= 0.9 and r["recall"] >= 0.97
