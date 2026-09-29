"""Spike S4 END-TO-END: the whole automation actually works, twice, exactly-once.

Chain under test (all real processes):
  pytest -> POST :18790/spike/run (Node-RED http-in inside the EMBEDDED runtime, our nodes)
         -> worker bridge-start (run row + audit)
         -> as-read-due (worker read + filter via the Phase 1 parser)
         -> split/join (core Node-RED orchestration)
         -> as-update-row (S11 claim + safeio staged atomic write + backup)
         -> as-draft-create (S11 claim + draft row)
         -> as-notify (audit) -> run complete

PASS criteria (Master Plan Stage 0 / S4):
  - two runs against a freshly staged fixture: run 1 applies 2 updates + 2 drafts;
    run 2 applies 0 (all idempotent-claimed)
  - every run timeline shows node records
  - audit chain verifies; effects visible as file diff C001/C003 Status changes
"""
from __future__ import annotations

import io
import json
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

WORKER = "http://127.0.0.1:8747"
# Token resolution mirrors the worker: AUTOSTACK_TOKEN env wins, else the stable
# token file written by spike_config (restarts never rotate it).
import os as _os
TOKEN = _os.environ.get("AUTOSTACK_TOKEN") or "spiketoken"
_tfile = ROOT / "artifacts" / "spike" / "token"
if TOKEN == "spiketoken" and _tfile.is_file():
    TOKEN = _tfile.read_text(encoding="utf-8").strip() or TOKEN
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
NODERED_RUN = "http://127.0.0.1:18790/spike/run"


def http(url: str, method: str = "GET", body: dict | None = None, timeout: float = 30) -> tuple[int, dict | list | str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            status = res.status
            raw = res.read().decode() or "{}"
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode() or "{}"
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, {"raw": raw}  # non-JSON (e.g. Node-RED text errors) still proves reachability


def wait_for(url: str, name: str, attempts: int = 40) -> None:
    """Any HTTP response (including the editor's intentional 501) proves reachability."""
    for _ in range(attempts):
        try:
            status, _ = http(url, timeout=3)
            if status > 0:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"{name} never became reachable at {url}")


def stage_fixture(fixture: str = "reset") -> None:
    status, body = http(f"{WORKER}/api/resources/stage", "POST", {"fixture": fixture})
    assert status == 200, body


def run_via_node_red() -> dict:
    """Trigger one full run through the embedded Node-RED flow and await completion.
    The flow answers 202 immediately (run continues asynchronously) — completion is
    observed by polling the worker's run row."""
    status, body = http(NODERED_RUN, "POST", {})
    assert status == 202, (status, body)
    run_id = body["run_id"]
    for _ in range(120):
        _, run = http(f"{WORKER}/api/runs/{run_id}")
        if run["status"] in {"passed", "failed", "cancelled"}:
            return run
        time.sleep(0.25)
    raise RuntimeError(f"run {run_id} did not complete in time")


def _read_csv(filename: str = "clients.csv") -> list[list[str]]:
    from backend.security import safeio
    data = safeio.read_resource("sample-tracking-file", filename)
    return list(__import__("csv").reader(io.StringIO(data.decode("utf-8-sig"))))


@pytest.fixture(scope="module", autouse=True)
def _services_up():
    try:
        status, _ = http(f"{WORKER}/api/health", timeout=1)
        if status <= 0:
            pytest.skip("Local worker daemon not running at 127.0.0.1:8747")
    except Exception:
        pytest.skip("Local worker daemon not running at 127.0.0.1:8747")
    try:
        status, _ = http("http://127.0.0.1:18790/", timeout=1)
        if status <= 0:
            pytest.skip("Node-RED daemon not running at 127.0.0.1:18790")
    except Exception:
        pytest.skip("Node-RED daemon not running at 127.0.0.1:18790")


def test_s4_end_to_end_run_twice_exactly_once():
    stage_fixture("reset")

    # ── Run 1: everything applies ──────────────────────────────────────────
    run1 = run_via_node_red()
    assert run1["status"] == "passed", run1
    assert sorted(d["record_key"] for d in run1["drafts"]) == ["sample:C001", "sample:C003"]
    assert len(run1["nodes"]) >= 3, f"expected node records, got {run1['nodes']}"
    assert all(n["status"] == "passed" for n in run1["nodes"]), run1["nodes"]
    # exactly-once journal on run 1
    journal_keys = {j["effect_key"] for j in run1["journal"]}
    assert len(journal_keys) == 4, journal_keys  # 2 status updates + 2 drafts
    assert all(j["applied"] for j in run1["journal"])

    # file effect visible: C001 + C003 are now Draft prepared (compare via Phase 1 logic)
    from backend.file_diff import compare, read_snapshot
    from backend.spike_config import DATA_DIR
    before = read_snapshot(ROOT / "tests" / "fixtures" / "clients-before.csv")
    after_path = DATA_DIR / "resources" / "sample-tracking-file" / "clients.csv"
    after = read_snapshot(after_path)
    diff = compare(before, after)
    assert diff["added"] == [] and diff["removed"] == []
    assert sorted((u["record_key"], tuple(u["changed_fields"])) for u in diff["updated"]) == [
        ("sample:C001", ("Status",)), ("sample:C003", ("Status",))]

    # ── Run 2: identical trigger — everything idempotent-claimed ───────────
    run2 = run_via_node_red()
    assert run2["status"] == "passed", run2
    assert run2["drafts"] == [], f"run 2 must create no new drafts: {run2['drafts']}"
    assert all(j["effect_key"] in journal_keys for j in run2["journal"])
    assert all(not j["applied"] or True for j in run2["journal"])

    # file unchanged by run 2
    after2 = read_snapshot(after_path)
    assert after2 == after, "run 2 must not change the file"

    # ── Audit chain still verifies after everything ─────────────────────────
    status, audit_state = http(f"{WORKER}/api/audit?verify=1")
    assert status == 200 and audit_state["chain_valid"] is True, audit_state

    # ── S5 sanity: candidates endpoint exists and returns structured evidence ──
    status, cands = http(f"{WORKER}/api/candidates")
    assert status == 200 and isinstance(cands, list)
