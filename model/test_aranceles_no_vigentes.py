"""Tests for aranceles_no_vigentes.py: the motives of a ficha without a vigente arancel, the rule of several padrón
codes, and the --entrega correction through import_fichas. Synthetic data only, against fake_core.

Run: cd model && python3 -m unittest -v
"""
import csv
import os
import tempfile
import unittest
from collections import Counter
from decimal import Decimal

import aranceles_no_vigentes as anv
from fake_core import FakeCore
from helpers import run, write_csv, write_xlsx_sheets

ANIO = 2026
# via-code keys with a vigente arancel for 2026; 0020000101-01 only for 2025
VIGENTES = {"0010000101-01": "50", "0010000201-01": "50", "0010000301-01": "80.00", "0010000401-01": "80"}
PADRON_HEADER = ["Código Predio", "Codigo de via", "Contribuyente"]


def classify(id_aranc, codes=None, vigentes=None, estado="COMPLETO", with_padron=True):
    """The motives and the target of one ficha 'P-1'."""
    vig = {k: Decimal(v) for k, v in (VIGENTES if vigentes is None else vigentes).items()}
    padron = ({"P-1": Counter(codes)} if codes else {}) if with_padron else None
    ficha = {"codigo_municipal": "P-1", "id_aranc": id_aranc, "estado_levantamiento": estado}
    return anv.analyze([ficha], vig, padron)


class MotivoTests(unittest.TestCase):
    def motivos(self, *args, **kwargs):
        return sorted({r.motivo for r in classify(*args, **kwargs).rows})

    def test_a_vigente_via_code_without_padron_is_ok(self):
        self.assertEqual(self.motivos("0010000101-01", with_padron=False), [])

    def test_an_empty_id_aranc(self):
        self.assertEqual(self.motivos(None, with_padron=False), ["id_aranc_vacio"])
        self.assertEqual(self.motivos("  ", with_padron=False), ["id_aranc_vacio"])

    def test_a_key_without_arancel_for_the_year(self):
        self.assertEqual(self.motivos("0020000101-01", with_padron=False), ["clave_inexistente"])

    def test_a_provisional_key_is_also_inexistente(self):
        self.assertEqual(self.motivos("R50", with_padron=False), ["clave_inexistente", "clave_provisional"])

    def test_a_provisional_key_that_exists_is_only_provisional(self):
        self.assertEqual(self.motivos("R50", with_padron=False, vigentes={**VIGENTES, "R50": "50"}),
                         ["clave_provisional"])

    def test_several_codes_some_not_vigente(self):
        self.assertEqual(self.motivos("0010000101-01", {"0010000101-01": 2, "0020000101-01": 1}),
                         ["varios_codigos_alguno_no_vigente"])

    def test_several_vigente_codes_with_distinct_values(self):
        self.assertEqual(self.motivos("0010000101-01", {"0010000101-01": 1, "0010000301-01": 1}),
                         ["varios_codigos_valores_distintos"])

    def test_values_compare_as_decimals(self):
        self.assertEqual(self.motivos("0010000301-01", {"0010000301-01": 1, "0010000401-01": 1}), [])

    def test_no_padron_code_with_a_vigente_arancel(self):
        self.assertEqual(self.motivos("R50", {"0020000101-01": 3}),
                         ["clave_inexistente", "clave_provisional", "codigo_sin_arancel_vigente"])

    def test_a_ficha_without_padron_rows_is_counted_not_listed(self):
        result = classify("0010000101-01", None)
        self.assertEqual((result.rows, result.counts["sin_padron"]), ([], 1))

    def test_the_rows_carry_the_padron_codes(self):
        row = classify("R50", {"0020000101-01": 1, "0020000201-01": 2}).rows[-1]
        self.assertEqual((row.codigo_municipal, row.id_aranc, row.motivo, row.codigos_padron),
                         ("P-1", "R50", "codigo_sin_arancel_vigente", "0020000101-01;0020000201-01"))

    def test_counts_per_motive(self):
        result = classify("R50", {"0020000101-01": 1})
        self.assertEqual(result.counts["clave_provisional"], 1)
        self.assertEqual(result.counts["codigo_sin_arancel_vigente"], 1)
        self.assertEqual(result.counts["id_aranc_vacio"], 0)


class TargetTests(unittest.TestCase):
    def target(self, codes, **kwargs):
        result = classify("R50", codes, **kwargs)
        return dict(result.candidates).get("P-1")

    def test_one_vigente_code(self):
        self.assertEqual(self.target({"0010000101-01": 1}), "0010000101-01")

    def test_all_vigente_same_value_takes_the_most_frequent(self):
        self.assertEqual(self.target({"0010000101-01": 1, "0010000201-01": 3}), "0010000201-01")

    def test_a_tie_takes_the_lowest_code(self):
        self.assertEqual(self.target({"0010000201-01": 2, "0010000101-01": 2}), "0010000101-01")

    def test_one_code_not_vigente_is_untouched(self):
        self.assertIsNone(self.target({"0010000101-01": 5, "0020000101-01": 1}))

    def test_distinct_values_are_untouched(self):
        self.assertIsNone(self.target({"0010000101-01": 1, "0010000301-01": 1}))

    def test_a_ficha_already_pointing_to_the_target_is_not_a_candidate(self):
        result = classify("0010000201-01", {"0010000101-01": 1, "0010000201-01": 3})
        self.assertEqual((result.candidates, result.counts["ya_apunta"]), ([], 1))

    def test_sin_levantar_is_skipped_and_counted(self):
        result = classify("R50", {"0010000101-01": 1}, estado="SIN_LEVANTAR")
        self.assertEqual((result.candidates, result.counts["sin_levantar_no_se_corrige"]), ([], 1))


class PadronTests(unittest.TestCase):
    def test_codes_are_counted_without_whitespace_and_empties_skipped(self):
        rows = [{"código predio": " P-1 ", "codigo de via": "0010000101 -01"},
                {"código predio": "P-1", "codigo de via": "0010000101-01"},
                {"código predio": "P-1", "codigo de via": ""},
                {"código predio": "", "codigo de via": "0010000201-01"},
                {"código predio": "P-2", "codigo de via": None}]
        self.assertEqual(anv.padron_codes(rows, "Código Predio", "Codigo de via"),
                         {"P-1": Counter({"0010000101-01": 2})})


class CliTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.stop)
        for id_aranc, valor in VIGENTES.items():
            self.core.add_record("arancel", {"id_aranc": id_aranc, "anio": ANIO, "valor_m2": valor,
                                             "clave": f"{id_aranc}|{ANIO}"})
        self.core.add_record("arancel", {"id_aranc": "0020000101-01", "anio": 2025, "valor_m2": "40",
                                         "clave": "0020000101-01|2025"})
        fichas = [("P-1", "R50", "COMPLETO", "120.5"),            # one vigente code -> corrected
                  ("P-2", "R80", "COMPLETO", "90"),               # two codes, same value -> most frequent
                  ("P-3", "R50", "COMPLETO", "60"),               # one code not vigente -> untouched
                  ("P-4", "0010000101-01", "COMPLETO", "70"),     # distinct values -> untouched
                  ("P-5", "R50", "SIN_LEVANTAR", None),           # would be corrected, but sin levantar
                  ("P-6", None, "PARCIAL", "40"),                 # empty, no padrón row
                  ("P-7", "0010000101-01", "COMPLETO", "30")]     # ok
        for codigo, id_aranc, estado, area in fichas:
            attributes = {"codigo_municipal": codigo, "estado_levantamiento": estado, "uso": "010100"}
            if id_aranc:
                attributes["id_aranc"] = id_aranc
            if area:
                attributes["area_terreno"] = area
            self.core.add_record("predio_catastral", attributes)
        padron = [["P-1", "0010000101-01", "ANA SECRETA"],
                  ["P-2", "0010000301-01", "LUIS SECRETO"], ["P-2", "0010000401-01", "LUIS SECRETO"],
                  ["P-2", "0010000401 -01", "LUIS SECRETO"],
                  ["P-3", "0010000101-01", "X"], ["P-3", "0020000101-01", "X"],
                  ["P-4", "0010000101-01", "X"], ["P-4", "0010000301-01", "X"],
                  ["P-5", "0010000201-01", "X"],
                  ["P-7", "0010000101-01", "X"]]
        self.padron = write_xlsx_sheets(self, {"OTRA": (["a"], [["1"]]), "PREDIO URBANO": (PADRON_HEADER, padron)})
        self.out_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: [os.unlink(os.path.join(self.out_dir, f)) for f in os.listdir(self.out_dir)]
                        or os.rmdir(self.out_dir))

    def cli(self, *extra):
        return run(anv.main, ["--anio", str(ANIO), "--core", self.core.base_url, *extra])

    def entrega(self, *extra, codigo="ICA-ARANCEL-1"):
        return self.cli("--padron", self.padron, "--entrega", codigo, "--fecha-corte", "2026-10-25",
                        "--csv", os.path.join(self.out_dir, "fichas.csv"), *extra)

    def writes(self):
        return [r for r in self.core.requests if r[0] in ("POST", "PATCH", "PUT", "DELETE") and "records" in r[1]]

    def predio(self, codigo):
        return next(r for r in self.core.records["predio_catastral"] if r["attributes"]["codigo_municipal"] == codigo)

    def test_the_report_counts_each_motive_and_writes_nothing(self):
        report = os.path.join(self.out_dir, "reporte.csv")
        code, out, err = self.cli("--padron", self.padron, "--reporte", report)
        self.assertEqual(code, 0, err)
        for line in ["fichas: 7", "id_aranc_vacio: 1", "clave_inexistente: 4", "clave_provisional: 4",
                     "varios_codigos_alguno_no_vigente: 1", "varios_codigos_valores_distintos: 1",
                     "codigo_sin_arancel_vigente: 0", "sin_padron: 1", "corregibles: 2",
                     "sin_levantar_no_se_corrige: 1"]:
            self.assertIn(line, out.splitlines())
        self.assertEqual(self.writes(), [])
        with open(report, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(list(rows[0]), ["codigo_municipal", "id_aranc", "motivo", "codigos_padron"])
        self.assertIn({"codigo_municipal": "P-3", "id_aranc": "R50", "motivo": "varios_codigos_alguno_no_vigente",
                       "codigos_padron": "0010000101-01;0020000101-01"}, rows)
        self.assertNotIn("P-7", {r["codigo_municipal"] for r in rows})

    def test_without_padron_only_the_id_aranc_motives(self):
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        self.assertIn("clave_provisional: 4", out)
        self.assertNotIn("sin_padron", out)
        self.assertNotIn("varios_codigos", out)

    def test_no_personal_data_is_printed(self):
        report = os.path.join(self.out_dir, "reporte.csv")
        code, out, err = self.entrega("--dry-run", "--reporte", report)
        with open(report, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(code, 0, err)
        self.assertNotIn("SECRET", out + err + text)

    def test_the_dry_run_writes_nothing(self):
        code, out, err = self.entrega("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.writes(), [])
        self.assertIn("cambio P-1: id_aranc R50 → 0010000101-01", out)
        self.assertIn("cambio P-2: id_aranc R80 → 0010000401-01", out)
        with open(os.path.join(self.out_dir, "fichas.csv"), encoding="utf-8") as f:
            self.assertEqual(f.read().splitlines(), ["cod_pre,id_aranc", "P-1,0010000101-01", "P-2,0010000401-01"])

    def test_the_entrega_changes_only_id_aranc_of_the_candidates(self):
        before = {r["attributes"]["codigo_municipal"]: dict(r["attributes"])
                  for r in self.core.records["predio_catastral"]}
        code, out, err = self.entrega("--descripcion", "aranceles por vía")
        self.assertEqual(code, 0, err)
        entrega = self.core.records["entrega_catastral"][0]
        self.assertEqual((entrega["attributes"]["codigo"], entrega["attributes"]["fuente"],
                          entrega["attributes"]["fecha_corte"], entrega["attributes"]["descripcion"]),
                         ("ICA-ARANCEL-1", "OTRA", "2026-10-25", "aranceles por vía"))
        for codigo, target in (("P-1", "0010000101-01"), ("P-2", "0010000401-01")):
            expected = {**before[codigo], "id_aranc": target, "entrega": entrega["id"]}
            self.assertEqual(self.predio(codigo)["attributes"], expected)
        for codigo in ("P-3", "P-4", "P-5", "P-6", "P-7"):
            self.assertEqual(self.predio(codigo)["attributes"], before[codigo])

    def test_a_second_run_finds_nothing_to_change(self):
        self.assertEqual(self.entrega()[0], 0)
        before = len(self.writes())
        code, out, err = self.entrega(codigo="ICA-ARANCEL-2")
        self.assertEqual((code, len(self.writes())), (0, before), err)
        self.assertIn("corregibles: 0", out)
        self.assertIn("nada que corregir", out)
        self.assertNotIn("entrega ICA-ARANCEL-2", out)

    def test_entrega_needs_padron_and_fecha_corte(self):
        code, _, err = self.cli("--entrega", "E-1", "--fecha-corte", "2026-10-25")
        self.assertEqual(code, 2)
        self.assertIn("--padron", err)
        code, _, err = self.cli("--padron", self.padron, "--entrega", "E-1")
        self.assertEqual(code, 2)
        self.assertIn("--fecha-corte", err)

    def test_a_padron_without_the_columns_exits_2(self):
        code, _, err = self.cli("--padron", self.padron, "--hoja", "OTRA")
        self.assertEqual(code, 2)
        self.assertIn("Código Predio", err)

    def test_the_columns_can_be_renamed(self):
        padron = write_csv(self, "cod,via\nP-1,0010000101-01\n")
        code, out, err = self.cli("--padron", padron, "--columna-codigo", "COD", "--columna-via", "via")
        self.assertEqual(code, 0, err)
        self.assertIn("sin_padron: 6", out)
