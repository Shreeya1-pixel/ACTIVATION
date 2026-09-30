"""Holes found by scripts/sandbox_attacks.py stay closed: the static check enforces the module
allowlist by parsing, and the sandbox enforces it again at run time."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.engine import runner  # noqa: E402
from backend.engine.generation import static_check  # noqa: E402


@pytest.mark.parametrize("module", ["ctypes", "pickle", "multiprocessing", "builtins", "pty", "ssl"])
def test_static_check_refuses_imports_outside_the_allowlist(module):
    code = f"import {module}\ndef run(rows, ctx):\n    return []\n"
    assert any(module in v for v in static_check(code))


def test_static_check_refuses_class_introspection():
    code = "def run(rows, ctx):\n    x = ''.__class__.__mro__\n    return []\n"
    assert any("dunder escape" in v for v in static_check(code))


def test_allowed_modules_still_pass():
    code = "import csv, io, datetime, re, json\ndef run(rows, ctx):\n    return []\n"
    assert static_check(code) == []


def _sandbox_only(code, monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "static_check", lambda _c: [])
    return runner.run_isolated_test(code, [{"id": "r1"}], ctx={}, key_field="id", timeout_s=5)


@pytest.mark.parametrize("module", ["os", "ctypes", "pickle", "importlib"])
def test_sandbox_blocks_imports_even_if_the_static_check_is_bypassed(module, monkeypatch, tmp_path):
    rep = _sandbox_only(f"import {module}\ndef run(rows, ctx):\n    return [{{'id': 'x'}}]\n", monkeypatch, tmp_path)
    assert rep["status"] == "failed" and "blocked in the sandbox" in (rep["error"] or "")


def test_sandbox_io_has_no_file_access(monkeypatch, tmp_path):
    target = tmp_path / "pwned"
    code = f"import io\ndef run(rows, ctx):\n    io.open({str(target)!r}, 'w').write('x')\n    return []\n"
    rep = _sandbox_only(code, monkeypatch, tmp_path)
    assert rep["status"] == "failed" and not target.exists()
    ok = _sandbox_only("import io\ndef run(rows, ctx):\n    io.StringIO('a')\n    return [{'id': 'r1'}]\n",
                       monkeypatch, tmp_path)
    assert ok["status"] == "passed"
