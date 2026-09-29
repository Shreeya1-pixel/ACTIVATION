"""Phase 4 detector: real positives trigger, the plan's negative examples never do."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.detection import sequences as det  # noqa: E402


def ev(event_id, action, captured_at, record_key="sample:C001", source="watcher",
       outcome="success", resource="sample-tracking-file"):
    return {"event_id": event_id, "action": action, "captured_at": captured_at,
            "record_key": record_key, "source": source, "outcome": outcome,
            "resource": resource}


BASE = datetime.fromisoformat("2026-09-21T09:00:00+00:00")


def t(minutes: float) -> str:
    return (BASE + timedelta(minutes=minutes)).isoformat()


def qualifying(cands):
    return [c for c in cands if c["qualifies"]]


def three_instances_two_clients(action_a="file.open", action_b="file.save", **overrides):
    """Six events: three completed instances (>=10 min apart), two clients alternating."""
    events = []
    for k, minute in enumerate([0, 1, 15, 16, 30, 31]):
        client = "sample:C001" if k % 2 == 0 else "sample:C002"
        kwargs = {"record_key": client, "source": "watcher", "outcome": "success"}
        kwargs.update(overrides)
        events.append(ev(f"e{k}", action_a, t(minute), **kwargs))
        events.append(ev(f"e{k}b", action_b, t(minute + 0.5), **kwargs))
    return events


def test_positive_three_instances_two_clients_qualifies():
    # now far out: each client's trailing instance becomes incomplete (silence proven),
    # leaving 2 countable instances per client = 4 total across 2 clients → qualifies.
    cands = det.detect_candidates(three_instances_two_clients(), now=t(120))
    q = qualifying(cands)
    assert len(q) == 1
    c = q[0]
    assert c["sequence"] == ["file.open", "file.save"]
    assert c["occurrences"] == 4
    assert c["record_keys"] == ["sample:C001", "sample:C002"]
    assert c["evidence"]["steps"] == ["file.open", "file.save"]
    assert c["evidence"]["distinct_clients"] == 2
    assert c["evidence"]["instances"] == 4
    assert c["evidence"]["per_client"] == {"sample:C001": 2, "sample:C002": 2}


def test_no_now_means_trailing_work_never_counts():
    # One instance per client, nothing follows: both are trailing → "open" without
    # proven silence → ZERO countable instances → no candidate can exist yet.
    events = []
    for k, client in enumerate(["sample:C001", "sample:C002"]):
        events.append(ev(f"o{k}", "file.open", t(k * 15), record_key=client))
        events.append(ev(f"o{k}b", "file.save", t(k * 15 + 0.5), record_key=client))
    assert qualifying(det.detect_candidates(events)) == []
    assert qualifying(det.detect_candidates(events, now=t(120))) == []  # incomplete ≠ ok
    # But the moment a follow-up instance exists in that client's stream, the earlier
    # one counts as closed ("ok"):
    events.append(ev("o2", "file.open", t(30), record_key="sample:C001"))
    events.append(ev("o2b", "file.save", t(30.5), record_key="sample:C001"))
    cands = det.detect_candidates(events)
    assert [c["occurrences"] for c in cands] == [1]  # only C001's first instance counts
    assert all(not c["qualifies"] for c in cands)


def test_negative_autostack_events_never_qualify():
    cands = det.detect_candidates(three_instances_two_clients(source="autostack"))
    assert qualifying(cands) == []


def test_negative_failed_actions_break_instances():
    cands = det.detect_candidates(three_instances_two_clients(outcome="error"))
    assert qualifying(cands) == []


def test_negative_single_client_never_qualifies():
    events = []
    for minute in [0, 1, 15, 16, 30, 31]:
        events.append(ev(f"m{minute}", "file.open", t(minute), record_key="sample:C001"))
        events.append(ev(f"m{minute}b", "file.save", t(minute + 0.5), record_key="sample:C001"))
    assert qualifying(det.detect_candidates(events)) == []


def test_negative_two_instances_below_threshold():
    events = three_instances_two_clients()[:8]  # only 2 full instances
    assert qualifying(det.detect_candidates(events)) == []


def test_gap_closed_trailing_instance_is_incomplete():
    events = [ev("g1", "file.open", t(0)), ev("g2", "file.save", t(0.5)),
              ev("g3", "file.open", t(45))]  # >10 min gap closes; trailing open is incomplete
    instances = det.build_instances(events, now=t(60))
    assert [i["status"] for i in instances] == ["ok", "incomplete"]


def test_trailing_instance_is_open_until_silence_proven():
    events = [ev("g1", "file.open", t(0)), ev("g2", "file.save", t(0.5)),
              ev("g3", "file.open", t(45))]
    # No `now`: the trailing instance is open (not yet countable), never assumed complete.
    instances = det.build_instances(events)
    assert [i["status"] for i in instances] == ["ok", "open"]
    # Silence proven only 4 minutes after the last event: still open (under 10).
    instances = det.build_instances(events, now=t(49))
    assert [i["status"] for i in instances] == ["ok", "open"]


def test_no_fabricated_confidence_in_evidence():
    blob = repr(det.detect_candidates(three_instances_two_clients()))
    for banned in ("confidence", "jaccard", "percent", "%"):
        assert banned not in blob.lower()


def test_duplicate_group_suppression():
    cands = det.detect_candidates(three_instances_two_clients())
    keys = [(tuple(c["sequence"]), c["resource"]) for c in cands]
    assert len(keys) == len(set(keys))
