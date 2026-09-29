"""PII masking for anything that leaves the machine or lands in event logs.

Two tools:
  - mask_text(): irreversible redaction of known identifier formats (email, IBAN, UAE
    Emirates ID and TRN, other common tax / national ID formats, phone numbers) for
    logs and captured events.
  - tokenize()/detokenize(): reversible placeholders for external AI calls. Personal
    values are swapped for ⟦P1⟧-style tokens before the prompt is sent and swapped back
    locally in the reply, so the provider never sees the real value.

Formats outside these patterns (free-text names, addresses) are only caught when they
arrive under a personal field name; unclassified free text is not guaranteed masked.
"""
from __future__ import annotations

import hashlib
import hmac
import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")),
    ("EMIRATES_ID", re.compile(r"\b784-?\d{4}-?\d{7}-?\d\b")),
    ("TRN", re.compile(r"\b100\d{12}\b")),
    ("TAX_ID", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b|\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("NATIONAL_ID", re.compile(r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b")),
    ("PHONE", re.compile(r"(?<![\w-])(?:(?:\+|00)971[ -]?|0)5\d[ -]?\d{3}[ -]?\d{4}\b"
                         r"|(?<![\w-])\+\d{1,3}[ -]?\d{2,4}[ -]?\d{3,4}[ -]?\d{3,4}\b")),
]

PERSONAL_FIELDS = {"name", "fullname", "full_name", "clientname", "client_name", "contact",
                   "contactname", "email", "phone", "mobile", "address", "emiratesid",
                   "emirates_id", "passport", "passportno", "iban", "trn", "taxid", "tax_id",
                   "nationalid", "national_id", "pan", "aadhaar", "gstin"}


def _is_personal_field(name: str) -> bool:
    return name.replace(" ", "").replace("-", "_").lower() in PERSONAL_FIELDS


def mask_text(text: str) -> str:
    out = text
    for label, pat in PATTERNS:
        out = pat.sub(f"[{label}]", out)
    return out


def pseudonymize_text(text: str, key: bytes) -> str:
    """Like mask_text, but each distinct value maps to a stable keyed tag so two clients
    stay distinguishable (repeat detection needs that) without storing the value."""
    out = text
    for label, pat in PATTERNS:
        out = pat.sub(lambda m, lb=label: f"[{lb}:{hmac.new(key, m.group(0).encode(), hashlib.sha256).hexdigest()[:8]}]", out)
    return out


def contains_pii(text: str) -> bool:
    return any(p.search(text or "") for _, p in PATTERNS)


class TokenMap:
    def __init__(self) -> None:
        self.forward: dict[str, str] = {}
        self.reverse: dict[str, str] = {}

    def token_for(self, value: str) -> str:
        if value not in self.forward:
            tok = f"⟦P{len(self.forward) + 1}⟧"
            self.forward[value] = tok
            self.reverse[tok] = value
        return self.forward[value]

    def _tokenize_str(self, text: str) -> str:
        for _, pat in PATTERNS:
            text = pat.sub(lambda m: self.token_for(m.group(0)), text)
        return text

    def tokenize(self, obj, field: str = ""):  # noqa: ANN001
        if isinstance(obj, dict):
            return {k: self.tokenize(v, k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.tokenize(v, field) for v in obj]
        if isinstance(obj, str):
            if obj and _is_personal_field(field):
                return self.token_for(obj)
            return self._tokenize_str(obj)
        return obj

    def detokenize(self, text: str) -> str:
        for tok, value in self.reverse.items():
            text = text.replace(tok, value)
        return text


def tokenize(prompt: str, context: dict) -> tuple[str, dict, TokenMap]:
    tm = TokenMap()
    safe_ctx = tm.tokenize(context)
    return tm._tokenize_str(prompt), safe_ctx, tm
