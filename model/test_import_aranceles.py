"""Tests for import_aranceles.py: the join of the two ogr2ogr csv files, the year filter, and an idempotent upsert.

Run: cd model && python3 -m unittest -v
"""
import unittest

import import_aranceles as ia
from fake_core import FakeCore
from helpers import run, write_csv
from tabular import parse_map, read_table

FRENTES = "ID_ARANC,COD_VIA,CUADRA,LADO\n1331,100101,0001,A\n1332,,,\n"
VALORES = 'ID_ARANC,ANO_EJEC,VAL_ACT\n1331,"2026",120.5\n1331,"2025",100\n1332,"2026",0\n1332,"2025",\n9999,"2026",30\n'


class ParseTests(unittest.TestCase):
    def parse(self, valores, anio=None, frentes=FRENTES):
        mapping = parse_map([], ia.COLUMNS)
        fr, problems = ia.frentes_from(read_table(write_csv(self, frentes)), mapping)
        self.assertEqual(problems, [])
        return ia.aranceles_from(read_table(write_csv(self, valores)), mapping, fr, anio)

    def test_joins_keeps_zero_and_leaves_empty_out(self):
        aranceles, empty, problems = self.parse(VALORES)
        self.assertEqual(problems, [])
        self.assertEqual(empty, 1)
        self.assertEqual(aranceles[("1331", 2026)], {"clave": "1331|2026", "id_aranc": "1331", "anio": 2026,
                                                     "valor_m2": "120.5", "cod_via": "100101", "cuadra": "0001", "lado": "A"})
        self.assertEqual(aranceles[("1332", 2026)]["valor_m2"], "0")
        self.assertIsNone(aranceles[("9999", 2026)]["cod_via"])  # no frente: loaded as it is

    def test_year_filter(self):
        aranceles, _, _ = self.parse(VALORES, anio=2025)
        self.assertEqual(list(aranceles), [("1331", 2025)])

    def test_problems(self):
        _, _, problems = self.parse('ID_ARANC,ANO_EJEC,VAL_ACT\n1,2026,abc\n1,20x6,5\n,2026,5\n2,2026,5\n2,2026,6\n3,2026,-1\n')
        self.assertEqual(len(problems), 5, problems)

    def test_identical_duplicate_is_fine(self):
        aranceles, _, problems = self.parse("ID_ARANC,ANO_EJEC,VAL_ACT\n2,2026,5\n2,2026,5.0\n")
        self.assertEqual((problems, len(aranceles)), ([], 1))


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.stop)
        self.frentes = write_csv(self, FRENTES)
        self.valores = write_csv(self, VALORES)

    def cli(self, *extra):
        return run(ia.main, ["--frentes", self.frentes, "--valores", self.valores, "--core", self.core.base_url, *extra])

    def writes(self):
        return [r for r in self.core.requests if r[0] in ("POST", "PUT") and "records" in r[1]]

    def test_creates_then_a_second_run_changes_nothing(self):
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        self.assertIn("done: 4 created, 0 updated, 0 skipped", out)
        self.assertEqual(len(self.core.records["arancel"]), 4)
        before = len(self.writes())
        code, out, _ = self.cli()
        self.assertIn("done: 0 created, 0 updated, 4 skipped", out)
        self.assertEqual(len(self.writes()), before)

    def test_updates_a_changed_value(self):
        self.cli("--anio", "2026")
        record = next(r for r in self.core.records["arancel"] if r["attributes"]["clave"] == "1331|2026")
        record["attributes"]["valor_m2"] = 99
        code, out, _ = self.cli("--anio", "2026")
        self.assertIn("done: 0 created, 1 updated, 2 skipped", out)
        self.assertEqual(record["attributes"]["valor_m2"], "120.5")

    def test_dry_run_and_bad_files(self):
        code, out, _ = self.cli("--dry-run")
        self.assertEqual((code, self.core.requests), (0, []))
        self.assertIn("sin valor: 1", out)
        self.valores = write_csv(self, "ID_ARANC,ANO_EJEC,VAL_ACT\n1,2026,x\n")
        code, _, err = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("nothing was sent to Core", err)
        self.assertEqual(self.core.requests, [])

    def test_missing_file_exits_2(self):
        self.frentes = "/nonexistent/frentes.csv"
        code, _, err = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("input:", err)
        self.assertEqual(self.core.requests, [])

    def test_core_refusal_exits_1(self):
        self.core.fail_on_record = "arancel"
        code, _, err = self.cli()
        self.assertEqual(code, 1)
        self.assertIn("-> 400", err)


if __name__ == "__main__":
    unittest.main()
