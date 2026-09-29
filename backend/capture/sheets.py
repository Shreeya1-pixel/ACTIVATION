"""Generic saved-sheet reader for capture (CSV and XLSX).

Unlike backend.file_diff (the fixed runtime fixture contract), this reads the sheets
offices actually keep: any header, any ID column, blank rows, ragged rows, mixed date
formats and "AED 12,500.00"-style amounts. Only field NAMES and record IDs ever leave this
module; cell values are used for comparison and then dropped.

Rules that stay strict:
  - the ID column must exist, and IDs must be unique (duplicates are rejected);
  - bounded size, rows, columns and cell length;
  - XLSX goes through the same archive safety checks as the runtime parser
    (no macros, external links, encrypted or path-escaping entries).
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

MAX_BYTES = 5_000_000
MAX_ROWS = 5_000
MAX_COLS = 64
MAX_CELL_CHARS = 1_024
MAX_ID_CHARS = 120

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y",
                 "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%b-%y", "%b %d, %Y", "%B %d, %Y",
                 "%Y/%m/%d")
_CURRENCY = r"(?:aed|dhs?\.?|د\.إ|usd|us\$|\$|eur|€|gbp|£|inr|rs\.?|₹)"
_AMOUNT = re.compile(rf"^{_CURRENCY}?\s*-?[\d,]+(?:\.\d+)?\s*{_CURRENCY}?$", re.IGNORECASE)
_ID_HINT = re.compile(r"(?:^|[^a-z])(id|code|no|num|number|ref)(?:[^a-z]|$)|id$", re.IGNORECASE)


class InvalidSheet(ValueError):
    """The file cannot be read as a sheet under the capture limits."""


@dataclass
class Sheet:
    header: list[str]
    id_column: str
    rows: dict[str, dict[str, str]]
    skipped_blank_ids: int = 0
    skipped_blank_rows: int = 0
    notes: list[str] = field(default_factory=list)


def normalize(value: str) -> str:
    """Comparison form of a cell: trimmed, whitespace collapsed, dates as ISO,
    amounts without currency/commas. Reformatting a cell is not an edit."""
    v = " ".join(str(value).split())
    if not v:
        return ""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue
    if _AMOUNT.match(v):
        num = re.sub(rf"^{_CURRENCY}\s*|\s*{_CURRENCY}$", "", v, flags=re.IGNORECASE).replace(",", "")
        try:
            f = float(num)
            return str(int(f)) if f == int(f) else f"{f:.2f}".rstrip("0").rstrip(".")
        except ValueError:
            pass
    return v


def _cell_text(value) -> str:  # noqa: ANN001
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _csv_rows(payload: bytes) -> list[list[str]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = payload.decode("cp1252", errors="strict") if _cp1252_ok(payload) else None
        if text is None:
            raise InvalidSheet("CSV must be UTF-8 or Windows-1252 text")
    try:
        return list(csv.reader(io.StringIO(text), strict=True))
    except csv.Error as exc:
        raise InvalidSheet(f"malformed CSV: {exc}") from exc


def _cp1252_ok(payload: bytes) -> bool:
    try:
        payload.decode("cp1252")
        return True
    except UnicodeDecodeError:
        return False


def _xlsx_rows(payload: bytes, sheet_name: str | None) -> list[list[str]]:
    from backend.file_diff import InvalidFixture, _xlsx_archive_check
    try:
        _xlsx_archive_check(payload)
    except InvalidFixture as exc:
        raise InvalidSheet(str(exc)) from exc
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(payload), read_only=True, data_only=True, keep_links=False)
    except Exception as exc:  # noqa: BLE001 - any openpyxl failure is an unreadable workbook
        raise InvalidSheet("unsupported workbook structure") from exc
    try:
        name = sheet_name or wb.sheetnames[0]
        if name not in wb.sheetnames:
            raise InvalidSheet(f"worksheet {name!r} not found")
        ws = wb[name]
        if (ws.max_row or 0) > MAX_ROWS + 1 or (ws.max_column or 0) > MAX_COLS:
            raise InvalidSheet("workbook exceeds capture limits")
        return [[_cell_text(v) for v in row] for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _raw_rows(path: Path, sheet_name: str | None) -> list[list[str]]:
    suffix = path.suffix.lower()
    if suffix not in (".csv", ".xlsx"):
        raise InvalidSheet("only .csv and .xlsx files are read")
    with path.open("rb") as stream:
        payload = stream.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise InvalidSheet("file exceeds capture size limit")
    return _csv_rows(payload) if suffix == ".csv" else _xlsx_rows(payload, sheet_name)


def _clean_header(raw: list[str], width: int, body: list[list[str]]) -> tuple[list[str], list[int]]:
    """Header names + the column indexes to keep. Blank header over a blank column is
    dropped; blank header over data becomes 'Column N'. Duplicates are rejected."""
    names: list[str] = []
    keep: list[int] = []
    for i in range(width):
        name = " ".join(str(raw[i]).split()) if i < len(raw) else ""
        has_data = any(i < len(r) and str(r[i]).strip() for r in body)
        if not name and not has_data:
            continue
        names.append(name or f"Column {i + 1}")
        keep.append(i)
    if len(names) > MAX_COLS:
        raise InvalidSheet("too many columns")
    lowered = [n.lower() for n in names]
    dupes = sorted({n for n in names if lowered.count(n.lower()) > 1})
    if dupes:
        raise InvalidSheet(f"duplicate column names: {', '.join(dupes)}")
    return names, keep


def read_table(path: Path, sheet_name: str | None = None) -> tuple[list[str], list[dict[str, str]], int]:
    """Header + non-blank rows (as dicts) + count of fully blank rows skipped."""
    raw = _raw_rows(path, sheet_name)
    while raw and not any(str(c).strip() for c in raw[0]):
        raw.pop(0)
    if not raw:
        raise InvalidSheet("file has no header row")
    body = raw[1:]
    if len(body) > MAX_ROWS:
        raise InvalidSheet("too many rows")
    width = max(len(r) for r in raw)
    header, keep = _clean_header(raw[0], width, body)
    rows: list[dict[str, str]] = []
    blank = 0
    for r in body:
        if not any(str(c).strip() for c in r):
            blank += 1
            continue
        values = [str(r[i]) if i < len(r) else "" for i in keep]
        if any(len(v) > MAX_CELL_CHARS for v in values):
            raise InvalidSheet("a cell exceeds the length limit")
        rows.append(dict(zip(header, values)))
    return header, rows, blank


def suggest_id_column(header: list[str], rows: list[dict[str, str]]) -> str | None:
    """Pick the column most likely to be a record ID: every non-blank value unique, few
    blanks, and a name like 'Vendor Code' / 'EmpID' / 'Invoice No' wins."""
    best, best_score = None, -1.0
    n = len(rows) or 1
    for pos, col in enumerate(header):
        vals = [" ".join(r.get(col, "").split()) for r in rows]
        filled = [v for v in vals if v]
        hinted = bool(_ID_HINT.search(col))
        allowed_blanks = max(1, int(n * (0.25 if hinted else 0.10)))
        if not filled or len(set(filled)) != len(filled) or n - len(filled) > allowed_blanks:
            continue
        score = (2.0 if hinted else 0.0) + (1.0 - pos / max(len(header), 1))
        if score > best_score:
            best, best_score = col, score
    return best


def read_sheet(path: Path, id_column: str | None = None, sheet_name: str | None = None) -> Sheet:
    header, table, blank = read_table(path, sheet_name)
    chosen = id_column or suggest_id_column(header, table)
    if not chosen:
        raise InvalidSheet("no column has unique values to use as the record ID; pick one")
    if chosen not in header:
        raise InvalidSheet(f"ID column {chosen!r} is not in this file")
    result: dict[str, dict[str, str]] = {}
    skipped_ids = 0
    for row in table:
        key = " ".join(row.get(chosen, "").split())
        if not key:
            skipped_ids += 1
            continue
        if len(key) > MAX_ID_CHARS or any(ch in key for ch in "\r\n\t"):
            raise InvalidSheet("an ID value is too long or contains control characters")
        if key in result:
            raise InvalidSheet(f"duplicate ID in column {chosen!r}")
        result[key] = row
    sheet = Sheet(header=header, id_column=chosen, rows=result,
                  skipped_blank_ids=skipped_ids, skipped_blank_rows=blank)
    if skipped_ids:
        sheet.notes.append(f"{skipped_ids} row(s) without an ID were skipped")
    return sheet


def compare(before: Sheet, after: Sheet, columns: list[str] | None = None) -> dict:
    """Added / removed IDs and, for kept IDs, the NAMES of tracked columns whose
    normalized value changed. Never returns cell contents."""
    tracked = [c for c in (columns or after.header) if c != after.id_column]
    updated = []
    for key in sorted(before.rows.keys() & after.rows.keys()):
        b, a = before.rows[key], after.rows[key]
        changed = [c for c in tracked if normalize(b.get(c, "")) != normalize(a.get(c, ""))]
        if changed:
            updated.append({"id": key, "changed_fields": changed})
    return {"added": sorted(after.rows.keys() - before.rows.keys()),
            "removed": sorted(before.rows.keys() - after.rows.keys()),
            "updated": updated}
