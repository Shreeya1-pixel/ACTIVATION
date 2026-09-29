"""Ordered-sequence detection (Phase 4) — pure functions over event dicts.

Design rules from the plan (and README):
  - Evidence-based only: no fabricated confidence percentages, no similarity scores.
  - AutoStack-generated events (source == "autostack") NEVER qualify — the app must not
    detect patterns in its own runs.
  - Only completed, unambiguous instances count; a >=10-minute inactivity gap closes an
    instance (unfinished trailing work stays incomplete and is excluded).
  - A candidate = the same ordered action sequence completed >=3 times, spanning
    >=2 distinct record_keys (clients), on the same resource+compatible column set.
  - Duplicate suppression: identical (sequence, resource, record-scope) groups merge.

Pure module (no DB): app.py folds persisted events in, candidates out.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

GAP = timedelta(minutes=10)          # inactivity that closes an instance
STITCH = timedelta(minutes=45)       # a longer pause that may still be one routine
THRESHOLD_OCCURRENCES = 3            # completed instances needed
THRESHOLD_CLIENTS = 2                # distinct record_keys needed

DONE = "task.completed"             # explicit "finished this row" marker closes an instance
INCOMPLETE = "incomplete"
AMBIGUOUS = "ambiguous"


def _ts(ev: dict) -> datetime:
    return datetime.fromisoformat(ev["captured_at"].replace("Z", "+00:00"))


def eligible_events(events: list[dict]) -> list[dict]:
    """Ordered, qualifying events only: exclude our own runs and failed actions."""
    out = []
    for ev in events:
        if ev.get("source") == "autostack":
            continue
        if ev.get("outcome") != "success":
            continue
        out.append(ev)
    out.sort(key=_ts)
    return out


def build_instances(events: list[dict], now: str | None = None) -> list[dict]:
    """Group events into instances — one stream per record_key (clients working
    simultaneously are distinct instances, never one merged sequence).

    Closing semantics (README/plan): an instance FOLLOWED by another in its stream is
    complete ("ok"); the trailing instance is only closed by >=10 inactive minutes
    ("incomplete" when `now` proves the silence, otherwise "open" — not yet countable).
    Only "ok" instances count toward candidates: detection is honest and lags one
    instance rather than counting work that may still be in progress.
    """
    evs = eligible_events(events)
    if not evs:
        return []
    now_ts = _ts({"captured_at": now}) if now else None
    streams: dict[str, list[dict]] = defaultdict(list)
    for ev in evs:
        streams[ev.get("record_key") or ""].append(ev)
    instances: list[dict] = []
    for _, stream in sorted(streams.items()):
        chunks: list[list[dict]] = []
        closed: set[int] = set()
        current: list[dict] = []
        for ev in stream:
            if ev.get("action") == DONE:
                if current:
                    closed.add(len(chunks))
                    chunks.append(current)
                current = []
                continue
            if current and _ts(ev) - _ts(current[-1]) > GAP:
                chunks.append(current)
                current = []
            current.append(ev)
        if current:
            chunks.append(current)
        for idx, chunk in enumerate(chunks):
            last = idx == len(chunks) - 1 and idx not in closed
            gap_before = (_ts(chunk[0]) - _ts(chunks[idx - 1][-1])).total_seconds() if idx else None
            if last:
                if now_ts is not None and (now_ts - _ts(chunk[-1])) > GAP:
                    status = INCOMPLETE
                else:
                    status = "open"
                instances.append(_finish(chunk, status=status, gap_before=gap_before))
            else:
                instances.append(_finish(chunk, status="ok", gap_before=gap_before))
    return instances


def step_label(ev: dict) -> str:
    """A row update is identified by WHICH columns changed, so 'set Status' and
    'fill TRN' are different steps even though both are row.updated."""
    fields = ev.get("changed_fields") or []
    if ev.get("action") == "row.updated" and fields:
        return f"row.updated[{','.join(sorted(fields))}]"
    return ev["action"]


def _finish(events: list[dict], *, status: str, gap_before: float | None = None) -> dict:
    record_keys = sorted({e["record_key"] for e in events if e.get("record_key")})
    return {
        "stream": events[0].get("record_key") or "",
        "gap_before_s": gap_before,
        "events": events,
        "started_at": events[0]["captured_at"],
        "last_at": events[-1]["captured_at"],
        "duration_s": (_ts(events[-1]) - _ts(events[0])).total_seconds(),
        "record_keys": record_keys,
        "resource": events[0].get("resource", ""),
        "sequence": [step_label(e) for e in events],
        "status": status,
    }


def sequence_key(sequence: list[str]) -> tuple:
    return tuple(sequence)


def detect_candidates(events: list[dict], now: str | None = None) -> list[dict]:
    """Fold events into evidence-based candidates.

    Returns candidates sorted by occurrences desc: {sequence, resource, occurrences,
    record_keys, instance_ids, first_seen, last_seen, evidence {steps, per_client}}.
    """
    instances = _stitch([i for i in build_instances(events, now=now) if i["status"] == "ok"])
    groups: dict[tuple, dict] = {}
    for idx, inst in enumerate(instances):
        if len(inst["events"]) < 1:
            continue
        key = (sequence_key(inst["sequence"]), inst["resource"])
        g = groups.setdefault(key, {
            "sequence": inst["sequence"], "resource": inst["resource"],
            "occurrences": 0, "record_keys": set(), "instance_ids": [],
            "first_seen": inst["started_at"], "last_seen": inst["last_at"],
            "per_client": defaultdict(int),
        })
        g["occurrences"] += 1
        for rk in inst["record_keys"]:
            g["record_keys"].add(rk)
            g["per_client"][rk] += 1
        g["instance_ids"].append(idx)
        if inst["started_at"] < g["first_seen"]:
            g["first_seen"] = inst["started_at"]
        if inst["last_at"] > g["last_seen"]:
            g["last_seen"] = inst["last_at"]

    candidates = []
    for g in groups.values():
        qualifies = (g["occurrences"] >= THRESHOLD_OCCURRENCES
                     and len(g["record_keys"]) >= THRESHOLD_CLIENTS)
        candidates.append({
            "sequence": g["sequence"],
            "resource": g["resource"],
            "qualifies": qualifies,
            "occurrences": g["occurrences"],
            "record_keys": sorted(g["record_keys"]),
            "instance_ids": g["instance_ids"],
            "first_seen": g["first_seen"],
            "last_seen": g["last_seen"],
            "evidence": {
                "steps": g["sequence"],
                "instances": g["occurrences"],
                "distinct_clients": len(g["record_keys"]),
                "per_client": dict(g["per_client"]),
            },
        })
    _fold_fragments(candidates)
    candidates.sort(key=lambda c: (-c["occurrences"], c["first_seen"]))
    return candidates


def _merge(a: dict, b: dict) -> dict:
    return {**a, "events": a["events"] + b["events"], "last_at": b["last_at"],
            "duration_s": (_ts({"captured_at": b["last_at"]}) - _ts({"captured_at": a["started_at"]})).total_seconds(),
            "record_keys": sorted(set(a["record_keys"]) | set(b["record_keys"])),
            "sequence": a["sequence"] + b["sequence"], "stitched": True}


def _stitch(instances: list[dict], rounds: int = 3) -> list[dict]:
    """Rejoin routines split by a pause longer than GAP but within STITCH.

    Two consecutive completed instances on the same record are joined only when the
    joined sequence itself meets the candidate rule (>=3 occurrences across >=2 records,
    counting both stitched pairs and unbroken instances). One slow day never invents a
    routine; a routine that is regularly interrupted is recovered whole."""
    limit = STITCH.total_seconds()
    for _ in range(rounds):
        pairs: dict[tuple, list[tuple[int, int]]] = defaultdict(list)
        for i in range(len(instances) - 1):
            a, b = instances[i], instances[i + 1]
            if (a["stream"] == b["stream"] and a["resource"] == b["resource"]
                    and b["gap_before_s"] is not None and b["gap_before_s"] <= limit):
                pairs[tuple(a["sequence"] + b["sequence"])].append((i, i + 1))
        whole: dict[tuple, set] = defaultdict(set)
        counts: dict[tuple, int] = defaultdict(int)
        for inst in instances:
            whole[tuple(inst["sequence"])].add(inst["stream"])
            counts[tuple(inst["sequence"])] += 1
        used: set[int] = set()
        joins: dict[int, int] = {}
        for seq, ps in sorted(pairs.items(), key=lambda kv: (-len(kv[1]), -len(kv[0]))):
            ps = [p for p in ps if p[0] not in used and p[1] not in used]
            if not ps:
                continue
            records = {instances[i]["stream"] for i, _ in ps} | whole[seq]
            if len(ps) + counts[seq] >= THRESHOLD_OCCURRENCES and len(records) >= THRESHOLD_CLIENTS:
                for i, j in ps:
                    used.update((i, j))
                    joins[i] = j
        if not joins:
            break
        out, skip = [], set(joins.values())
        for i, inst in enumerate(instances):
            if i in skip:
                continue
            out.append(_merge(inst, instances[joins[i]]) if i in joins else inst)
        instances = out
    return instances


def _contains(longer: list[str], shorter: list[str]) -> bool:
    n = len(shorter)
    return any(longer[i:i + n] == shorter for i in range(len(longer) - n + 1))


def _fold_fragments(candidates: list[dict]) -> None:
    """A user who pauses longer than GAP mid-routine splits one instance in two, and the
    pieces can repeat often enough to qualify on their own. A qualifying candidate whose
    steps are a contiguous part of a longer qualifying candidate on the same resource and
    the same records is that fragment: it stops qualifying and points at the full routine."""
    winners = [c for c in candidates if c["qualifies"]]
    for c in winners:
        for full in winners:
            if (full is not c and full["resource"] == c["resource"]
                    and len(full["sequence"]) > len(c["sequence"])
                    and set(c["record_keys"]) <= set(full["record_keys"])
                    and _contains(full["sequence"], c["sequence"])):
                c["qualifies"] = False
                c["folded_into"] = full["sequence"]
                break
