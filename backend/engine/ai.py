"""AI draft-generation adapter (Spike S7).

Provider pattern so the rest of the engine never touches a vendor SDK:
  - provider "mock": deterministic offline generation (hash-seeded, no network).
    Guarantees identical output for identical context — CI/test safe.
  - provider "gemini": Google Gemini REST API (generativelanguage.googleapis.com),
    enabled only when settings expose an API key. Milestone C adds keyring storage.

Fail-closed rule: an AI provider error NEVER corrupts a run — callers get
GenerationError and the run path can fall back to the static template pack.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request

from backend.security import pii

GEMINI_MODEL = os.environ.get("AUTOSTACK_GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
TIMEOUT_S = 20


class GenerationError(RuntimeError):
    """Raised when the selected provider cannot produce text (fail-closed)."""


def _mock_text(prompt: str, context: dict) -> str:
    """Deterministic stand-in generation: stable hash of (prompt, context).

    Mirrors the shape of a real completion (header + referenced fields) so
    downstream rendering code is exercised identically in tests and offline demos.
    """
    seed = hashlib.sha256(
        (prompt + "\n\x00\n" + json.dumps(context, sort_keys=True, default=str)).encode()
    ).hexdigest()
    fields = ", ".join(f"{k}={context[k]}" for k in sorted(context)) or "no fields"
    return (
        f"[mock:{seed[:12]}] Draft generated for context: {fields}. "
        f"This offline output is deterministic and safe for the judge demo; "
        f"configure a Gemini key in Settings to switch to live generation."
    )


def _synth_code(context: dict) -> str:
    """Deterministic code synthesis from the plan rules (mock provider, Phase 5).

    The generated function is REAL: it applies exactly the rules the user confirmed —
    eligibility from ctx (set by the runner from the plan), action, and destinations —
    reading nothing else. No network, no filesystem, only builtins; passes static_check.
    Different plans produce different code (field names/action branch on plan content).
    """
    id_field = context.get("client_id_field", "ClientID")
    action = context.get("action", "create_draft")
    if action not in ("create_draft", "update_status"):
        action = "create_draft"  # ALLOWED_ACTIONS gate already blocked others upstream
    elig = context.get("eligibility") or {}
    date_field = elig.get("date_field") or "FollowUpDate"
    status_field = elig.get("status_field") or "Status"
    return (
        "def run(rows, ctx):\n"
        "    out = []\n"
        "    status = ctx.get('eligibility_status')\n"
        "    run_date = ctx.get('eligibility_date')\n"
        f"    id_field = {id_field!r}\n"
        "    for row in rows:\n"
        f"        if status is not None and row.get({status_field!r}) != status:\n"
        "            continue\n"
        "        if run_date is not None:\n"
        f"            due = row.get({date_field!r})\n"
        "            if due is None or str(due) > str(run_date):\n"
        "                continue\n"
        f"        if {action!r} == 'update_status':\n"
        f"            out.append({{{id_field!r}: row.get(id_field), 'effect': 'update_status'}})\n"
        "        else:\n"
        f"            out.append({{{id_field!r}: row.get(id_field), 'effect': 'create_draft'}})\n"
        "    return out\n"
    )


def _gemini_text(prompt: str, context: dict, api_key: str) -> str:
    payload = {
        "contents": [{
            "parts": [{"text": prompt + "\n\nCONTEXT: " + json.dumps(context, sort_keys=True, default=str)}],
        }],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096},
    }
    req = urllib.request.Request(
        GEMINI_ENDPOINT.format(model=GEMINI_MODEL, key=api_key),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:
            data = json.loads(res.read().decode())
    except Exception as exc:  # network, HTTP, JSON — all fail closed
        raise GenerationError(f"gemini request failed: {exc}") from exc
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text:
            raise KeyError("no text parts")
        return text
    except (KeyError, IndexError, TypeError) as exc:
        raise GenerationError(f"gemini response malformed: {json.dumps(data)[:200]}") from exc


def model_label() -> str:
    """What actually writes the code right now, as shown to the user."""
    if os.environ.get("AUTOSTACK_AI_PROVIDER", "mock") == "gemini" and os.environ.get("AUTOSTACK_GEMINI_KEY"):
        return GEMINI_MODEL
    return "offline generator (no LLM call)"


def generate_text(prompt: str, context: dict | None = None, *, provider: str | None = None,
                  api_key: str | None = None) -> str:
    """Generate text through the configured provider. Never raises besides GenerationError."""
    context = context or {}
    provider = provider or os.environ.get("AUTOSTACK_AI_PROVIDER", "mock")
    if provider == "mock":
        if context.get("mode") == "code":
            return "```python\n" + _synth_code(context) + "```\n"
        return _mock_text(prompt, context)
    if provider == "gemini":
        key = api_key or os.environ.get("AUTOSTACK_GEMINI_KEY", "")
        if not key:
            raise GenerationError("provider gemini selected but no API key configured")
        safe_prompt, safe_ctx, tokens = pii.tokenize(prompt, context)
        return tokens.detokenize(_gemini_text(safe_prompt, safe_ctx, key))
    raise GenerationError(f"unknown AI provider: {provider}")
