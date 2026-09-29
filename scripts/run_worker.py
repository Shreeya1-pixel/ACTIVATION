"""Spike worker launcher: starts uvicorn + the in-process trigger loop (B3).

Token precedence is handled by backend.spike_config: env AUTOSTACK_TOKEN wins,
otherwise the persisted artifacts/spike/token is reused (or created). No hardcoded
default credential is injected here.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import uvicorn  # noqa: E402

from backend.app import app  # noqa: E402
from backend.roadmap_routes import start_trigger_loop_if_needed  # noqa: E402
from backend.spike_config import DATA_DIR, FIXTURES_DIR  # noqa: E402

# Ensure sample tracking CSV is present so demo workflows work out-of-the-box
_sample_target = DATA_DIR / "resources" / "sample-tracking-file" / "clients.csv"
if not _sample_target.is_file() and (FIXTURES_DIR / "clients-before.csv").is_file():
    _sample_target.parent.mkdir(parents=True, exist_ok=True)
    _sample_target.write_bytes((FIXTURES_DIR / "clients-before.csv").read_bytes())

start_trigger_loop_if_needed()

if __name__ == "__main__":
    # Loopback by default; containers set AUTOSTACK_HOST=0.0.0.0 and the platform sets PORT.
    uvicorn.run(app, host=os.environ.get("AUTOSTACK_HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8747")), log_level="info")
