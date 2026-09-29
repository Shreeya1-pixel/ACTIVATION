"""Shared fixtures: per-test isolated SQLite DB so tests never pollute the dev DB.

Previously the roadmap/hardening fixtures ran against the live dev database
(`backend.db.engine`), which accumulated ~335 junk workflows and mutated real
workspace settings (bugs B4/B5 in docs/test-report-and-fix-plan.md). Every
TestClient test now gets a throwaway DB: identical schema, identical app code,
zero shared state.

The live-DB convention remains only for tests that deliberately exercise
persistence across processes (e.g. the S4 end-to-end spike), which use their
own explicit fixtures.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


def _install_isolated_db():
    """Create a throwaway SQLite engine and point the whole app at it.

    Returns (TestingSession, cleanup). Overrides the FastAPI `get_db`
    dependency (route sessions) and rebinds `SessionLocal` in every module
    that imported it directly, so background helpers and route handlers all
    share the same temporary DB.
    """
    from backend.db import Base, get_db
    from backend import db as db_mod
    from backend import roadmap_routes

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(
        f"sqlite:///{Path(tmp.name).as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    # 1) routes using Depends(get_db)
    app_mod = __import__("backend.app", fromlist=["app"])
    app_mod.app.dependency_overrides[get_db] = _override_get_db
    # 2) modules holding a module-level SessionLocal binding (imported at import time)
    # 3) security.tokens imports SessionLocal from backend.db at call time
    originals = []
    for mod in (roadmap_routes, db_mod):
        if hasattr(mod, "SessionLocal"):
            originals.append((mod, mod.SessionLocal))
            mod.SessionLocal = TestingSession

    def cleanup():
        app_mod.app.dependency_overrides.pop(get_db, None)
        for mod, original in originals:
            mod.SessionLocal = original
        engine.dispose()
        Path(tmp.name).unlink(missing_ok=True)

    return TestingSession, cleanup


def _active_sessionmaker():
    """The sessionmaker of the currently-active isolated DB.

    Stored on backend.db (single module object — never duplicated by pytest's
    conftest import styles) so plain helpers can find the active test DB.
    """
    from backend import db as db_mod
    return getattr(db_mod, "_TEST_SESSION", None)


def test_session():
    """A session on the currently-active isolated DB (for plain helper functions
    that cannot receive fixtures). Raises if no isolated DB is active."""
    maker = _active_sessionmaker()
    if maker is None:
        raise RuntimeError("no isolated DB active — use the isolated_db/isolated_db_module fixture")
    return maker()


@pytest.fixture()
def isolated_db(monkeypatch):
    """Function-scoped isolated DB (pairs with the `client` fixture)."""
    from backend import db as db_mod
    TestingSession, cleanup = _install_isolated_db()
    db_mod._TEST_SESSION = TestingSession
    yield TestingSession
    db_mod._TEST_SESSION = None
    cleanup()


@pytest.fixture(scope="module")
def isolated_db_module():
    """Module-scoped isolated DB for files that patch auth themselves."""
    from backend import db as db_mod
    TestingSession, cleanup = _install_isolated_db()
    db_mod._TEST_SESSION = TestingSession
    yield TestingSession
    db_mod._TEST_SESSION = None
    cleanup()


@pytest.fixture()
def client(monkeypatch, isolated_db):
    """TestClient with isolated DB + pinned spike token."""
    from backend import spike_config as cfg
    import backend.security.tokens as tok
    import backend.roadmap_routes as rr

    monkeypatch.setattr(cfg, "SPIKE_TOKEN", "spiketoken")
    monkeypatch.setattr(tok, "get_expected_token", lambda: "spiketoken")
    monkeypatch.setattr(rr, "get_expected_token", lambda: "spiketoken")
    with TestClient(__import__("backend.app", fromlist=["app"]).app) as c:
        yield c
