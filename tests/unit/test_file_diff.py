import csv
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl import Workbook
from backend.file_diff import FIELDS, MAX_BYTES, MAX_ROWS, InvalidFixture, compare, read_snapshot

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class SavedFileComparisonTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def csv_file(self, rows, header=FIELDS):
        path = self.root / "fixture.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows([header, *rows])
        return path

    def test_real_saved_differences_match_independent_expected_fixture(self):
        expected = json.loads((FIXTURES / "expected-diff.json").read_text())
        actual = compare(read_snapshot(FIXTURES / "clients-before.csv"), read_snapshot(FIXTURES / "clients-after.csv"))
        self.assertEqual(actual, expected)
        self.assertNotIn("example.invalid", json.dumps(actual))
        self.assertNotIn("Draft prepared", json.dumps(actual))

    def test_row_reordering_is_not_a_change(self):
        before = read_snapshot(FIXTURES / "clients-before.csv")
        self.assertEqual(compare(before, dict(reversed(list(before.items())))), {"added": [], "removed": [], "updated": []})

    def test_added_removed_are_not_claimed_as_cell_edits(self):
        before = read_snapshot(FIXTURES / "clients-before.csv")
        after = {"C004": dict(before["C001"], ClientID="C004")}
        self.assertEqual(compare(before, after), {"added": ["sample:C004"], "removed": ["sample:C001", "sample:C002", "sample:C003"], "updated": []})

    def test_duplicate_or_missing_ids_are_rejected(self):
        row = ["C001", "Sample", "test@example.invalid", "2026-09-20", "New"]
        for rows in ([row, row], [["", *row[1:]]]):
            with self.subTest(rows=rows), self.assertRaises(InvalidFixture):
                read_snapshot(self.csv_file(rows))

    def test_wrong_header_and_row_shape_are_rejected(self):
        for rows, header in (([], ["ClientID"]), ([["C001"]], FIELDS)):
            with self.subTest(header=header), self.assertRaises(InvalidFixture):
                read_snapshot(self.csv_file(rows, header))

    def test_formula_like_csv_is_rejected(self):
        for cell in ("=HYPERLINK(\"https://example.invalid\")", " @SUM(1)", "+1", "-1"):
            with self.subTest(cell=cell), self.assertRaises(InvalidFixture):
                read_snapshot(self.csv_file([["C001", cell, "a@example.invalid", "2026-09-20", "New"]]))

    def test_file_and_row_limits(self):
        path = self.root / "large.csv"
        path.write_bytes(b"x" * (MAX_BYTES + 1))
        with self.assertRaises(InvalidFixture):
            read_snapshot(path)
        rows = [[f"C{i % 1000:03d}", "N", "a@example.invalid", "2026-09-20", "New"] for i in range(MAX_ROWS + 1)]
        with self.assertRaises(InvalidFixture):
            read_snapshot(self.csv_file(rows))

    def test_xlsx_and_csv_compare_identically(self):
        workbook = Workbook()
        workbook.active.title = "Clients"
        with (FIXTURES / "clients-after.csv").open(newline="", encoding="utf-8") as stream:
            for row in csv.reader(stream):
                workbook.active.append(row)
        path = self.root / "sample.xlsx"
        workbook.save(path)
        self.assertEqual(read_snapshot(path), read_snapshot(FIXTURES / "clients-after.csv"))

    def test_xlsx_formula_is_rejected(self):
        workbook = Workbook()
        workbook.active.title = "Clients"
        workbook.active.append(FIELDS)
        workbook.active.append(["C001", "=1+1", "a@example.invalid", "2026-09-20", "New"])
        path = self.root / "formula.xlsx"
        workbook.save(path)
        with self.assertRaises(InvalidFixture):
            read_snapshot(path)

    def test_external_xml_and_oversized_archive_are_rejected_before_parsing(self):
        for payload in (b'<Relationship TargetMode="External"/>', b"<Relationship TargetMode = 'External'/>",
                        "<Relationship TargetMode='External'/>".encode("utf-16"),
                        b'<!DOCTYPE x [<!ENTITY a "x">]><x>&a;</x>', b"x" * 8_000_001):
            path = self.root / "bad.xlsx"
            with ZipFile(path, "w", ZIP_DEFLATED) as archive:
                archive.writestr("xl/unsafe.xml", payload)
            with self.assertRaises(InvalidFixture):
                read_snapshot(path)

    def test_malformed_workbook_is_reported_as_blocked(self):
        path = self.root / "incomplete.xlsx"
        with ZipFile(path, "w") as archive:
            archive.writestr("xl/worksheet.xml", "<worksheet/>")
        with self.assertRaises(InvalidFixture):
            read_snapshot(path)

    def test_unsupported_formats_are_rejected(self):
        with self.assertRaises(InvalidFixture):
            read_snapshot(self.root / "macros.xlsm")


if __name__ == "__main__":
    unittest.main()
