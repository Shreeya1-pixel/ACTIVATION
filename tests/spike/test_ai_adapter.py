"""Spike S7: AI adapter is deterministic offline (mock) and fail-closed (gemini without key)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.engine import ai  # noqa: E402


def test_mock_generation_is_deterministic():
    a = ai.generate_text("prompt one", {"Name": "Ravi", "FollowUpDate": "2026-09-20"})
    b = ai.generate_text("prompt one", {"Name": "Ravi", "FollowUpDate": "2026-09-20"})
    assert a == b
    assert a.startswith("[mock:")
    assert "Ravi" in a


def test_unknown_provider_fails_closed():
    import pytest
    with pytest.raises(ai.GenerationError):
        ai.generate_text("p", {}, provider="holo-deck")


def test_gemini_without_key_fails_closed():
    import pytest
    with pytest.raises(ai.GenerationError):
        ai.generate_text("p", {}, provider="gemini", api_key="")
