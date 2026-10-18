"""Tests for tabular.py: csv and xlsx reading and the value cleaners.

Run: cd model && python3 -m unittest -v
"""
import unittest

import tabular as t
from helpers import write_csv, write_xlsx


class ReadTableTests(unittest.TestCase):
    def test_csv_skips_comments_and_lowercases_the_header(self):
        rows = t.read_table(write_csv(self, "﻿# note\nCod_Pre,Piso\n1,A\n\n2,B\n"))
        self.assertEqual([(r["cod_pre"], r["piso"], r["_fila"]) for r in rows], [("1", "A", 3), ("2", "B", 5)])

    def test_xlsx_rows_by_header(self):
        rows = t.read_table(write_xlsx(self, ["COD_PRE", "Piso"], [["1", "S1"], ["2", None]]))
        self.assertEqual([(r["cod_pre"], r["piso"]) for r in rows], [("1", "S1"), ("2", None)])

    def test_empty_csv(self):
        self.assertEqual(t.read_table(write_csv(self, "# only a comment\n")), [])


class CleanTests(unittest.TestCase):
    def test_decimal_and_int(self):
        self.assertEqual(t.parse_decimal(" 12.50 "), ("12.5", None))
        self.assertEqual(t.parse_decimal("1,200.5"), ("1200.5", None))
        self.assertEqual(t.parse_decimal("1E+2"), ("100", None))
        self.assertEqual(t.parse_decimal(""), (None, None))
        self.assertIsNotNone(t.parse_decimal("x")[1])
        self.assertIsNotNone(t.parse_decimal("-1")[1])
        self.assertIsNotNone(t.parse_decimal("NaN")[1])
        self.assertEqual(t.parse_int("2026.0"), (2026, None))
        self.assertIsNotNone(t.parse_int("2026.5")[1])

    def test_code_text_and_enum_option(self):
        self.assertEqual(t.code_text("3.0"), "3")
        self.assertEqual(t.code_text(" 01 "), "01")
        self.assertEqual(t.enum_option("muy_malo", ["BUENO", "MUY MALO"]), ("MUY MALO", None))
        self.assertIsNotNone(t.enum_option("raro", ["BUENO"])[1])


if __name__ == "__main__":
    unittest.main()
