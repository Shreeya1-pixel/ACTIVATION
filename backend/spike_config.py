"""Stage 0 spike configuration. Loopback-only, token-authenticated.

Production hardening (keyring storage, rotate-on-start, scopes) lands in Milestone A;
these constants exist so the spike never depends on machine-specific state.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# AUTOSTACK_DATA_DIR overrides the default local path.
# In container deployments (Railway) set this to a writable path such as /data.
_env_data = os.environ.get("AUTOSTACK_DATA_DIR", "").strip()
DATA_DIR: Path = Path(_env_data) if _env_data else REPO_ROOT / "artifacts" / "spike"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "spike.db"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

WORKER_HOST = "127.0.0.1"
WORKER_PORT = 8747
WORKER_URL = f"http://{WORKER_HOST}:{WORKER_PORT}"

NODERED_HOST = "127.0.0.1"
NODERED_PORT = 18790
NODERED_URL = f"http://{NODERED_HOST}:{NODERED_PORT}"

# Session token with STABLE persistence (QA round-2 finding): env wins for
# tests/explicit runs; otherwise the token is reused from artifacts/spike/token
# (gitignored) so restarts never silently 401 the whole stack.
def new_token() -> str:
    return secrets.token_urlsafe(32)


def _load_or_persist_token() -> str:
    env = os.environ.get("AUTOSTACK_TOKEN")
    if env:
        return env
    token_file = DATA_DIR / "token"
    if token_file.is_file():
        value = token_file.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = new_token()
    token_file.write_text(value, encoding="utf-8")
    try:
        token_file.chmod(0o600)
    except OSError:
        pass
    return value


SPIKE_TOKEN = _load_or_persist_token()

# Fixture aliases used by the spike workflow.
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
BEFORE_CSV = FIXTURES_DIR / "clients-before.csv"
AFTER_CSV = FIXTURES_DIR / "clients-after.csv"
RUN_DATE = "2026-09-20"  # C001 and C003 are due on/before this date (expected: 2 drafts)
