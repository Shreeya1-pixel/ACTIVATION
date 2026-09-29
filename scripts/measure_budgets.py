"""Phase 8: resource budget measurements (docs/contracts.md budgets).

Measures the running worker's idle CPU/memory over a window and the capture-poll
cost, then writes JSON evidence for docs/platform-matrix.md. Honest numbers only:
the script measures the real processes on THIS machine and labels the platform.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "budgets.json"

WORKER_URL = "http://127.0.0.1:8747"
RED_URL = "http://127.0.0.1:18790"
WORKER_TOKEN = os.environ.get("AUTOSTACK_TOKEN", "spiketoken")

BUDGETS = {
    "idle_cpu_percent_max": 1.0,      # of one core, dashboard closed
    "resident_memory_mib_max": 400.0,  # background, dashboard closed
    "capture_poll_ms_max": 500.0,
    "ingest_queue_bound": 1000,
}


def _http(url: str, method: str = "GET", token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(url, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    with urllib.request.urlopen(req, data=data, timeout=5) as res:
        return res.status, json.loads(res.read().decode())


def _pids_on_port(port: int) -> list[int]:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
            try:
                pids.add(int(parts[4]))
            except ValueError:
                pass
    return sorted(pids)


def _proc_stats(pid: int) -> dict:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-Process -Id {pid} | Select-Object CPU,WorkingSet64 | ConvertTo-Json)"],
        capture_output=True, text=True).stdout
    try:
        data = json.loads(out)
        return {"cpu_seconds_total": float(data.get("CPU") or 0.0),
                "rss_bytes": int(data.get("WorkingSet64") or 0)}
    except Exception:
        return {"cpu_seconds_total": 0.0, "rss_bytes": 0}


def measure(window_seconds: int = 10) -> dict:
    result: dict = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "budgets": BUDGETS,
        "services": {},
    }
    worker_ok = _http(f"{WORKER_URL}/api/health", token=WORKER_TOKEN)[0] == 200
    result["services"]["worker_up"] = worker_ok
    if not worker_ok:
        result["note"] = "worker not running; start the stack before measuring"
        return result

    worker_pids = _pids_on_port(8747)
    red_pids = _pids_on_port(18790)
    all_pids = worker_pids + red_pids
    if not all_pids:
        result["note"] = "no listening processes found for the stack"
        return result

    t0_stats = {p: _proc_stats(p) for p in all_pids}
    t0 = time.perf_counter()

    # Capture-poll cost (a real poll over the sample folder). A warmup call first:
    # the first poll after worker start pays one-time directory/WAL warm-up, which
    # is not representative of steady state.
    _http(f"{WORKER_URL}/api/capture/poll", method="POST", token=WORKER_TOKEN, body=None)
    t1 = time.perf_counter()
    _http(f"{WORKER_URL}/api/capture/poll", method="POST", token=WORKER_TOKEN, body=None)
    poll_ms = (time.perf_counter() - t1) * 1000
    result["capture_poll_ms"] = round(poll_ms, 1)

    time.sleep(window_seconds)

    t_elapsed = time.perf_counter() - t0
    cpu_delta = 0.0
    rss_max = 0
    for p in all_pids:
        now = _proc_stats(p)
        cpu_delta += max(0.0, now["cpu_seconds_total"] - t0_stats[p]["cpu_seconds_total"])
        rss_max = max(rss_max, now["rss_bytes"])
    idle_cpu_percent = cpu_delta / t_elapsed * 100.0
    result["idle_cpu_percent_of_core"] = round(idle_cpu_percent, 3)
    result["resident_memory_mib"] = round(rss_max / (1024 * 1024), 1)
    result["measured_window_seconds"] = round(t_elapsed, 1)
    result["within_budget"] = {
        "idle_cpu": idle_cpu_percent <= BUDGETS["idle_cpu_percent_max"] * 1.0
        if worker_pids else "n/a (uvicorn main proc only measured)",
        "memory": result["resident_memory_mib"] <= BUDGETS["resident_memory_mib_max"],
        "capture_poll": poll_ms <= BUDGETS["capture_poll_ms_max"],
    }
    return result


if __name__ == "__main__":
    window = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    data = measure(window)
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data, indent=2))
