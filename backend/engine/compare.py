"""Invoice/PO comparison engine (Phase 8 second workflow) — pure, bounded, honest.

Three-way scoped comparison (approved exports only): an invoice matches a purchase
order when the PO number exists AND the amounts agree within tolerance. Outcomes are
exact categories — `matched`, `amount_mismatch`, `missing_po` — never a similarity
score. The function is pure: same inputs always produce the same classification, and
the expected outputs in tests are computed independently (not by this module).
"""
from __future__ import annotations

import csv
import io

MAX_ROWS = 1000  # contracts.md parser budget


def parse_table(payload: bytes) -> list[dict]:
    """Bounded CSV parse; a resource file is a trusted-format export, still bounded."""
    text = payload.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    out = []
    for raw in rows[1:MAX_ROWS]:
        if not raw:
            continue
        out.append({header[i]: (raw[i] if i < len(raw) else "") for i in range(len(header))})
    return out


def _to_amount(value) -> float | None:
    try:
        return float(str(value).replace(",", "").replace("₹", "").replace("AED", "").replace("Dhs", "").strip())
    except (TypeError, ValueError):
        return None


def _within(inv_amount: float | None, po_amount: float | None, tolerance: float) -> bool:
    """Exact-cents comparison (float subtraction lies at the boundary:
    3200.00 - 3199.99 = 0.010000000000218 in binary floats)."""
    if inv_amount is None or po_amount is None:
        return False
    return abs(round(inv_amount * 100) - round(po_amount * 100)) <= round(tolerance * 100)


def compare_invoices(invoices: list[dict], purchase_orders: list[dict], *,
                     match_key: str = "PONumber", amount_field: str = "Amount",
                     tolerance: float = 0.0) -> list[dict]:
    """Enrich each invoice with po_match / po_amount. Pure; inputs are not mutated."""
    po_index: dict[str, dict] = {}
    for po in purchase_orders[:MAX_ROWS]:
        key = str(po.get(match_key, "")).strip()
        if key:
            po_index.setdefault(key, po)
    enriched: list[dict] = []
    for inv in invoices[:MAX_ROWS]:
        row = dict(inv)
        key = str(inv.get(match_key, "")).strip()
        po = po_index.get(key)
        inv_amount = _to_amount(inv.get(amount_field))
        if po is None:
            row["po_match"] = "missing_po"
            row["po_amount"] = ""
        else:
            po_amount = _to_amount(po.get(amount_field))
            row["po_amount"] = f"{po_amount:.2f}" if po_amount is not None else ""
            if not _within(inv_amount, po_amount, tolerance):
                row["po_match"] = "amount_mismatch"
            else:
                row["po_match"] = "matched"
        enriched.append(row)
    return enriched


def expected_matches(invoices: list[dict], purchase_orders: list[dict], *,
                     match_key: str = "PONumber", amount_field: str = "Amount",
                     tolerance: float = 0.0) -> dict[str, str]:
    """Independent oracle for tests: invoice id -> expected category, computed with
    a DIFFERENT algorithm (per-invoice linear scan) than compare_invoices' index."""
    expected: dict[str, str] = {}
    for inv in invoices:
        key = str(inv.get(match_key, "")).strip()
        inv_amount = _to_amount(inv.get(amount_field))
        category = "missing_po"
        for po in purchase_orders:
            if str(po.get(match_key, "")).strip() != key:
                continue
            po_amount = _to_amount(po.get(amount_field))
            if _within(inv_amount, po_amount, tolerance):
                category = "matched"
                break
            category = "amount_mismatch"
        inv_id = str(inv.get("InvoiceID", ""))
        expected[inv_id] = category
    return expected
