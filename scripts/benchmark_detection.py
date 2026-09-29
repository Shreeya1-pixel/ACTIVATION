"""Detection benchmark on synthetic workspaces with known answers.

Each workspace plants:
  - real patterns: the same ordered edits, completed >=3 times across >=2 records
  - near-misses: repeated, but only 2 completed times, or only ever on one record
  - noise: one-off edits on random records at unrelated times
  - interleaving: several records worked on the same day, steps 1-9 minutes apart

It then scores the detector against the planted truth. This measures the
implementation against the specified rule under messy timing and noise; it is not a
claim about accuracy on any particular office's real data.

    python scripts/benchmark_detection.py [--workspaces 500] [--seed 7]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.detection import sequences  # noqa: E402

COLUMNS = ["Status", "Amount", "Invoice No", "Due Date", "TRN Check", "Remarks", "Owner",
           "Paid On", "Reminder Count", "Net Pay", "Days Present", "OT Hours", "Notes",
           "Approved By", "Category", "Priority"]
BASE = datetime(2026, 6, 1, tzinfo=timezone.utc)
SLOW_RATE = 0.0  # share of steps where the user pauses longer than the 10-minute gap


def _event(rid: str, fields: list[str], at: datetime, resource: str) -> dict:
    return {"record_key": rid, "resource": resource, "action": "row.updated",
            "changed_fields": fields, "outcome": "success", "source": "saved_file_comparison",
            "captured_at": at.isoformat()}


def _steps(rng: random.Random, used: set) -> tuple:
    while True:
        n = rng.randint(2, 4)
        seq = tuple(tuple(sorted(rng.sample(COLUMNS, rng.randint(1, 2)))) for _ in range(n))
        if seq not in used and len(set(seq)) == len(seq):
            used.add(seq)
            return seq


def _plant(rng, events, steps, records, per_record, resource, day0):
    """Work `records` through `steps`, `per_record` times each, on separate days."""
    for rep in range(per_record):
        day = BASE + timedelta(days=day0 + rep * 7)
        for i, rid in enumerate(records):
            t = day + timedelta(hours=9, minutes=rng.randint(0, 50) + i * 3)
            for s in steps:
                events.append(_event(rid, list(s), t, resource))
                slow = rng.random() < SLOW_RATE
                t += timedelta(minutes=rng.randint(11, 25) if slow else rng.randint(1, 9))


def workspace(rng: random.Random, idx: int) -> tuple[list[dict], set, int]:
    events: list[dict] = []
    truth: set = set()
    used: set = set()
    resource = f"watched/sheet{idx}"
    rid = iter(f"R{idx}-{n}" for n in range(10_000))
    near_misses = 0

    for p in range(rng.randint(1, 3)):                       # real patterns
        steps = _steps(rng, used)
        recs = [next(rid) for _ in range(rng.randint(2, 4))]
        per_record = rng.randint(3, 5)                      # trailing one stays open
        _plant(rng, events, steps, recs, per_record, resource, day0=p)
        completed = len(recs) * (per_record - 1)
        if completed >= 3:
            truth.add(tuple(f"row.updated[{','.join(s)}]" for s in steps))

    for p in range(rng.randint(1, 3)):                       # near-misses
        steps = _steps(rng, used)
        near_misses += 1
        if rng.random() < 0.5:                               # one record only
            _plant(rng, events, steps, [next(rid)], rng.randint(4, 6), resource, day0=3 + p)
        else:                                                # only 2 completed
            _plant(rng, events, steps, [next(rid), next(rid)], 2, resource, day0=3 + p)

    noise_cols = iter(f"Noise{idx}-{n}" for n in range(10_000))
    for _ in range(rng.randint(5, 25)):                      # one-off edits
        at = BASE + timedelta(days=rng.randint(0, 40), hours=rng.choice([7, 13, 19]),
                              minutes=rng.randint(0, 59))
        events.append(_event(next(rid), [next(noise_cols)], at, resource))

    rng.shuffle(events)                                      # arrival order is not time order
    return events, truth, near_misses


def run(n_workspaces: int, seed: int, slow_rate: float = 0.0) -> dict:
    global SLOW_RATE
    SLOW_RATE = slow_rate
    rng = random.Random(seed)
    tp = fp = fn = 0
    near_total = 0
    n_events = 0
    elapsed = 0.0
    for i in range(n_workspaces):
        events, truth, near = workspace(rng, i)
        near_total += near
        n_events += len(events)
        t0 = time.perf_counter()
        found = {tuple(c["sequence"]) for c in sequences.detect_candidates(events) if c.get("qualifies")}
        elapsed += time.perf_counter() - t0
        tp += len(found & truth)
        fp += len(found - truth)
        fn += len(truth - found)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {
        "workspaces": n_workspaces, "seed": seed, "slow_step_rate": slow_rate, "events": n_events,
        "planted_patterns": tp + fn, "near_misses": near_total,
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "near_miss_false_alarms": fp,
        "ms_per_1000_events": round(elapsed / max(n_events, 1) * 1_000_000, 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspaces", type=int, default=500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "docs" / "detection-benchmark.json"))
    args = ap.parse_args()
    results = {"clean": run(args.workspaces, args.seed),
               "slow_users_5pct": run(args.workspaces, args.seed, 0.05),
               "slow_users_15pct": run(args.workspaces, args.seed, 0.15)}
    Path(args.out).write_text(json.dumps(results, indent=2) + "\n")
    for name, r in results.items():
        print(f"{name:>18}: precision {r['precision']}  recall {r['recall']}  "
              f"false alarms {r['false_positives']}  patterns {r['planted_patterns']}  "
              f"near-misses {r['near_misses']}  events {r['events']}  "
              f"{r['ms_per_1000_events']} ms/1k events")


if __name__ == "__main__":
    main()
