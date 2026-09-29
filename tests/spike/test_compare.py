"""Phase 8 second workflow: invoice/PO comparison — pure engine + API effects.

The oracle (compare.expected_matches) uses a different algorithm (linear scan) than
the engine (hash index), so agreement is real evidence. API effects reuse the
exactly-once journal; a second run must change nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from tests.spike.conftest import isolated_db_module, test_session  # noqa: E402,F401 (fixture import)
from backend.engine import compare  # noqa: E402
from backend.models import Base, IdempotencyClaim  # noqa: E402
from backend.security import safeio  # noqa: E402

client = TestClient(app)
H = {"Authorization": "Bearer testtoken"}


@pytest.fixture(scope="module", autouse=True)
def _auth(isolated_db_module):
    from backend.security import tokens
    original = tokens.get_expected_token
    tokens.get_expected_token = lambda: "testtoken"
    pass  # schema created by isolated_db_module
    yield
    tokens.get_expected_token = original


INVOICES = [
    {"InvoiceID": "INV-001", "PONumber": "PO-100", "Amount": "12500.00"},
    {"InvoiceID": "INV-002", "PONumber": "PO-101", "Amount": "8400.50"},
    {"InvoiceID": "INV-003", "PONumber": "PO-999", "Amount": "1500.00"},
    {"InvoiceID": "INV-004", "PONumber": "PO-102", "Amount": "3200.00"},
]
POS = [
    {"PONumber": "PO-100", "Amount": "12500.00"},
    {"PONumber": "PO-101", "Amount": "8300.00"},
    {"PONumber": "PO-102", "Amount": "3199.99"},
]


def test_engine_matches_independent_oracle():
    enriched = compare.compare_invoices(INVOICES, POS, tolerance=0.01)
    oracle = compare.expected_matches(INVOICES, POS, tolerance=0.01)
    got = {e["InvoiceID"]: e["po_match"] for e in enriched}
    assert got == oracle
    assert oracle == {"INV-001": "matched", "INV-002": "amount_mismatch",
                      "INV-003": "missing_po", "INV-004": "matched"}


def test_tolerance_boundary_and_bad_amounts():
    # 0.01 difference is inside tolerance; 0.02 is not.
    tight = compare.compare_invoices(
        [{"InvoiceID": "A", "PONumber": "P1", "Amount": "10.01"}],
        [{"PONumber": "P1", "Amount": "10.00"}], tolerance=0.01)
    assert tight[0]["po_match"] == "matched"
    loose = compare.compare_invoices(
        [{"InvoiceID": "A", "PONumber": "P1", "Amount": "10.02"}],
        [{"PONumber": "P1", "Amount": "10.00"}], tolerance=0.01)
    assert loose[0]["po_match"] == "amount_mismatch"
    # Malformed amounts fail closed into amount_mismatch, never crash.
    bad = compare.compare_invoices(
        [{"InvoiceID": "B", "PONumber": "P1", "Amount": "N/A"}],
        [{"PONumber": "P1", "Amount": "10.00"}])
    assert bad[0]["po_match"] == "amount_mismatch"


def _reset_compare_state():
    db = test_session()
    try:
        for claim in db.query(IdempotencyClaim).all():
            if "invoice-po" in claim.effect_key:
                db.delete(claim)
        db.commit()
    finally:
        db.close()
    safeio.write_resource("invoice-register", "invoices.csv",
                          (ROOT / "tests" / "fixtures" / "invoices-before.csv").read_bytes(),
                          backup=False)


def test_compare_run_effects_exactly_once():
    _reset_compare_state()
    r1 = client.post("/api/compare/run", json=None, headers=H)
    assert r1.status_code == 200, r1.text
    body = r1.json()
    assert body["matched"] == 2 and body["mismatched"] == 2
    assert sorted(body["updated"]) == ["INV-002", "INV-003"]
    assert sorted(body["drafted"]) == ["invoice:INV-002", "invoice:INV-003"]

    after = compare.parse_table(safeio.read_resource("invoice-register", "invoices.csv"))
    statuses = {r["InvoiceID"]: r["POStatus"] for r in after}
    assert statuses["INV-001"] == ""          # matched rows untouched
    assert statuses["INV-002"] == "Mismatch"
    assert statuses["INV-003"] == "No PO"
    assert statuses["INV-004"] == ""          # tolerance-boundary match untouched

    r2 = client.post("/api/compare/run", json=None, headers=H)
    assert r2.status_code == 200
    assert r2.json()["updated"] == [] and r2.json()["skipped"]
    assert r2.json()["drafted"] == []
