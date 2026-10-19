"""Tests for import_fichas.py: column mapping, validation, csv and xlsx input, and an idempotent load.

Run: cd model && python3 -m unittest -v
"""
import os
import unittest

import import_fichas as imf
from fake_core import FakeCore
from helpers import run, write_csv, write_xlsx
from tabular import load_enums, parse_map, read_table

HERE = os.path.dirname(os.path.abspath(__file__))
ENUMS = load_enums(os.path.join(HERE, "model.json"))

FICHAS = """# demo comment line
cod_pre,cod_cpu,cod_sect,cod_mzn,cod_lote,id_aranc,uso,area_terreno,longitud_frente,anio_levantamiento,es_edificio
120302-0001,CPU-1,01,002,003,1331,010100,180.50,9,2026,no
120302-0002,CPU-2,01,002,004,1331,020100,200,10,2026,si
"""
PISOS = """cod_pre,piso,area_construida,anio_construccion,material,estado_conservacion,categorias
120302-0001,1,120.4,1998,LADRILLO,BUENO,CCDCCDC
120302-0001,2,86,2010,ladrillo,muy_bueno,BBCBBCB
120302-0002,1,50,2015,CONCRETO,REGULAR,AABAABA
"""
OBRAS = """cod_pre,codigo_vu,cantidad,anio_construccion,material,estado_conservacion
120302-0001,CERCOS METALICOS|88,42,1998,METAL,REGULAR
"""


class ParseTests(unittest.TestCase):
    def test_fichas_map_and_types(self):
        path_rows = read_table(write_csv(self, FICHAS))
        fichas, problems = imf.fichas_from(path_rows, parse_map([], imf.FICHA_COLUMNS))
        self.assertEqual(problems, [])
        self.assertEqual(fichas[0][1]["codigo_municipal"], "120302-0001")
        self.assertEqual(fichas[0][1]["sector"], "01")
        self.assertEqual(fichas[0][1]["area_terreno"], "180.5")
        self.assertEqual(fichas[0][1]["anio_levantamiento"], 2026)
        self.assertEqual([f[1]["es_edificio"] for f in fichas], [False, True])

    def test_map_override(self):
        rows = read_table(write_csv(self, "CPM,cod_sect\nA-1,01\n"))
        fichas, problems = imf.fichas_from(rows, parse_map(["codigo_municipal=CPM"], imf.FICHA_COLUMNS))
        self.assertEqual((problems, fichas[0][1]["codigo_municipal"]), ([], "A-1"))
        with self.assertRaises(ValueError):
            parse_map(["color=COLOR"], imf.FICHA_COLUMNS)

    def test_bad_fichas_are_all_listed(self):
        rows = read_table(write_csv(self, "cod_pre,area_terreno,anio_levantamiento,es_edificio\n"
                                         "A,abc,2026,no\nA,1,2026,no\n,1,2026,no\nB,1,20.5,quizas\nC,-4,,\n"))
        _, problems = imf.fichas_from(rows, parse_map([], imf.FICHA_COLUMNS))
        self.assertEqual(len(problems), 6, problems)  # one row can have several

    def test_missing_column_is_a_problem(self):
        _, problems = imf.fichas_from(read_table(write_csv(self, "x\n1\n")), parse_map([], imf.FICHA_COLUMNS))
        self.assertEqual(len(problems), 1)

    def test_categorias_as_text_or_seven_columns(self):
        pm = parse_map([], imf.PISO_COLUMNS)
        rows = read_table(write_csv(self, "cod_pre,piso,categorias,muros_columnas,techos,pisos,puertas_ventanas,"
                                          "revestimientos,banos,instalaciones\n"
                                          "A,1,cc dccdc,,,,,,,\nA,2,,a,b,c,d,e,f,j\n"))
        pisos, problems = imf.pisos_from(rows, pm, ENUMS, {"A"})
        self.assertEqual(problems, [])
        self.assertEqual([pisos[0][2][c] for c in imf.CATEGORIAS], list("CCDCCDC"))
        self.assertEqual([pisos[1][2][c] for c in imf.CATEGORIAS], list("ABCDEFJ"))

    def test_bad_pisos(self):
        pm = parse_map([], imf.PISO_COLUMNS)
        rows = read_table(write_csv(self, "cod_pre,piso,area_construida,material,estado_conservacion,categorias\n"
                                          "A,1,10,PLASTICO,BUENO,CCDCCDC\n"        # material
                                          "A,2,10,ADOBE,PESIMO,CCDCCDC\n"          # estado
                                          "A,3,10,ADOBE,BUENO,CCDCCDK\n"           # letter
                                          "A,4,10,ADOBE,BUENO,CCD\n"               # length
                                          "A,4,x,ADOBE,BUENO,CCDCCDC\n"            # repeated piso + number
                                          "Z,1,10,ADOBE,BUENO,CCDCCDC\n"))         # orphan
        _, problems = imf.pisos_from(rows, pm, ENUMS, {"A"})
        self.assertEqual(len(problems), 7, problems)

    def test_techo_incluido_accepts_the_usual_yes_no_spellings(self):
        pm = parse_map([], imf.PISO_COLUMNS)
        values = ["SI", "no", "S", "n", "TRUE", "False", "1", "0", ""]
        rows = read_table(write_csv(self, "cod_pre,piso,categorias,techo_incluido\n" +
                                    "".join(f"A,{i},DCDCCDC,{v}\n" for i, v in enumerate(values))))
        pisos, problems = imf.pisos_from(rows, pm, ENUMS, {"A"})
        self.assertEqual(problems, [])
        self.assertEqual([p[2]["techo_incluido"] for p in pisos],
                         [True, False, True, False, True, False, True, False, None])

    def test_techo_incluido_is_optional(self):
        rows = read_table(write_csv(self, "cod_pre,piso,categorias\nA,1,DCDCCDC\n"))
        pisos, problems = imf.pisos_from(rows, parse_map([], imf.PISO_COLUMNS), ENUMS, {"A"})
        self.assertEqual(problems, [])
        self.assertIsNone(pisos[0][2]["techo_incluido"])

    def test_an_unreadable_techo_incluido_is_a_problem(self):
        rows = read_table(write_csv(self, "cod_pre,piso,categorias,techo_incluido\nA,1,DCDCCDC,quizas\n"))
        _, problems = imf.pisos_from(rows, parse_map([], imf.PISO_COLUMNS), ENUMS, {"A"})
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("techo_incluido", problems[0])

    def test_techo_incluido_column_can_be_remapped(self):
        pm = parse_map(["techo_incluido=INCLUYE_TECHO"], imf.PISO_COLUMNS)
        rows = read_table(write_csv(self, "cod_pre,piso,categorias,INCLUYE_TECHO\nA,1,DCDCCDC,si\n"))
        pisos, problems = imf.pisos_from(rows, pm, ENUMS, {"A"})
        self.assertEqual((problems, pisos[0][2]["techo_incluido"]), ([], True))

    def test_clasificacion_is_an_option_or_its_rnt_table_number(self):
        pm = parse_map([], imf.PISO_COLUMNS)
        values = ["edificio-oficinas", "CASA HABITACION Y DEPARTAMENTOS PARA VIVIENDA", "2", "04", ""]
        rows = read_table(write_csv(self, "cod_pre,piso,categorias,clasificacion\n" +
                                    "".join(f"A,{i},CCDCCDC,{v}\n" for i, v in enumerate(values))))
        pisos, problems = imf.pisos_from(rows, pm, ENUMS, {"A"})
        self.assertEqual(problems, [])
        opciones = ENUMS["clasificacion"]
        self.assertEqual([p[2]["clasificacion"] for p in pisos], [opciones[2], opciones[0], opciones[1], opciones[3], None])

    def test_an_unknown_clasificacion_is_a_problem(self):
        rows = read_table(write_csv(self, "cod_pre,piso,clasificacion\nA,1,MUSEOS\nA,2,0\nA,3,5\n"))
        _, problems = imf.pisos_from(rows, parse_map([], imf.PISO_COLUMNS), ENUMS, {"A"})
        self.assertEqual(len(problems), 3, problems)
        self.assertTrue(all("clasificacion" in p for p in problems), problems)

    def test_a_model_without_clasificacion_only_refuses_a_filled_one(self):
        viejo = {k: v for k, v in ENUMS.items() if k != "clasificacion"}
        rows = read_table(write_csv(self, "cod_pre,piso,clasificacion\nA,1,\nA,2,1\n"))
        _, problems = imf.pisos_from(rows, parse_map([], imf.PISO_COLUMNS), viejo, {"A"})
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("clasificacion", problems[0])

    def test_seccion_is_optional_and_a_positive_integer(self):
        rows = read_table(write_csv(self, "cod_pre,piso,seccion\nA,1,\nA,2,2\nA,3,0\nA,4,1.5\nA,5,dos\n"))
        pisos, problems = imf.pisos_from(rows, parse_map([], imf.PISO_COLUMNS), ENUMS, {"A"})
        self.assertEqual(len(problems), 3, problems)
        self.assertTrue(all("seccion" in p for p in problems), problems)
        self.assertEqual([p[2]["seccion"] for p in pisos[:2]], [None, 2])

    def test_the_same_piso_in_two_secciones_is_not_repeated_the_same_seccion_is(self):
        pm = parse_map([], imf.PISO_COLUMNS)
        rows = read_table(write_csv(self, "cod_pre,piso,seccion\nA,5,\nA,5,2\nA,5,1\nA,6,2\nA,6,2\n"))
        _, problems = imf.pisos_from(rows, pm, ENUMS, {"A"})
        # a blank seccion is 1: rows 2 and 4 are the same piso 5 seccion 1; rows 5 and 6 the same piso 6 seccion 2
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(all("repeated" in p for p in problems), problems)

    def test_clasificacion_and_seccion_columns_can_be_remapped(self):
        pm = parse_map(["clasificacion=CLAS", "seccion=SEC"], imf.PISO_COLUMNS)
        rows = read_table(write_csv(self, "cod_pre,piso,CLAS,SEC\nA,1,3,2\n"))
        pisos, problems = imf.pisos_from(rows, pm, ENUMS, {"A"})
        self.assertEqual(problems, [])
        self.assertEqual((pisos[0][2]["clasificacion"], pisos[0][2]["seccion"]), ("EDIFICIO-OFICINAS", 2))

    def test_obras_and_orphans(self):
        om = parse_map([], imf.OBRA_COLUMNS)
        rows = read_table(write_csv(self, OBRAS + "Z,X|1,1,2000,METAL,BUENO\nA,X|1,uno,2000,METAL,BUENO\n"))
        obras, problems = imf.obras_from(rows, om, ENUMS, {"120302-0001", "A"})
        self.assertEqual(len(obras), 3)
        self.assertEqual(len(problems), 2, problems)

    def test_xlsx_input_with_float_codes(self):
        path = write_xlsx(self, ["COD_PRE", "COD_SECT", "AREA_TERRENO"], [["77", "1.0", "100.50"]])
        fichas, problems = imf.fichas_from(read_table(path), parse_map([], imf.FICHA_COLUMNS))
        self.assertEqual(problems, [])
        self.assertEqual((fichas[0][1]["sector"], fichas[0][1]["area_terreno"]), ("1", "100.5"))


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.stop)
        self.fichas = write_csv(self, FICHAS)
        self.pisos = write_csv(self, PISOS)
        self.obras = write_csv(self, OBRAS)

    def cli(self, *extra, fichas=None, pisos=None):
        return run(imf.main, ["--fichas", fichas or self.fichas, "--pisos", pisos or self.pisos, "--core", self.core.base_url,
                              *extra])

    def posts(self):
        return [r for r in self.core.requests if r[0] == "POST" and "records" in r[1]]

    def test_creates_predios_with_their_children(self):
        code, out, err = self.cli("--obras", self.obras)
        self.assertEqual(code, 0, err)
        self.assertIn("done: 2 created, 0 skipped (3 construcciones, 1 obras)", out)
        predios = {r["attributes"]["codigo_municipal"]: r for r in self.core.records["predio_catastral"]}
        piso = next(r for r in self.core.records["construccion"] if r["attributes"]["piso"] == "2")
        self.assertEqual(piso["attributes"]["predio"], predios["120302-0001"]["id"])
        self.assertEqual(piso["attributes"]["material"], "LADRILLO")
        self.assertEqual(piso["attributes"]["estado_conservacion"], "MUY BUENO")
        self.assertEqual(piso["attributes"]["muros_columnas"], "B")
        self.assertEqual(self.core.records["obra_complementaria"][0]["attributes"]["predio"], predios["120302-0001"]["id"])

    def test_techo_incluido_reaches_core_and_is_omitted_when_empty(self):
        pisos = write_csv(self, "cod_pre,piso,categorias,techo_incluido\n120302-0001,1,DCDCCDC,si\n120302-0001,2,DCDCCDC,\n")
        code, _, err = self.cli(pisos=pisos)
        self.assertEqual(code, 0, err)
        by_piso = {r["attributes"]["piso"]: r["attributes"] for r in self.core.records["construccion"]}
        self.assertIs(by_piso["1"]["techo_incluido"], True)
        self.assertNotIn("techo_incluido", by_piso["2"])

    def test_clasificacion_and_seccion_reach_core_and_are_omitted_when_empty(self):
        pisos = write_csv(self, "cod_pre,piso,categorias,clasificacion,seccion\n120302-0001,5,CCDCCDC,1,\n"
                                "120302-0001,5,CCDCCDC,,2\n")
        code, out, err = self.cli(pisos=pisos)
        self.assertEqual(code, 0, err)
        self.assertIn("(2 construcciones, 0 obras)", out)
        primera, segunda = sorted((r["attributes"] for r in self.core.records["construccion"]),
                                  key=lambda a: a.get("seccion", 1))
        self.assertEqual((primera["piso"], primera["clasificacion"]), ("5", ENUMS["clasificacion"][0]))
        self.assertNotIn("seccion", primera)
        self.assertEqual((segunda["piso"], segunda["seccion"]), ("5", 2))
        self.assertNotIn("clasificacion", segunda)
        code, out, _ = self.cli(pisos=pisos)
        self.assertIn("(0 construcciones, 0 obras)", out)
        self.assertEqual(len(self.core.records["construccion"]), 2)

    def test_a_piso_core_has_without_seccion_is_seccion_1(self):
        # perené's pisos were loaded before seccion existed: a second section of the same piso is new, the first is not
        first = self.core.add_record("predio_catastral", {"codigo_municipal": "120302-0001"})
        self.core.add_record("construccion", {"piso": "1", "predio": first["id"]})
        pisos = write_csv(self, "cod_pre,piso,seccion\n120302-0001,1,1\n120302-0001,1,2\n")
        code, out, err = self.cli(pisos=pisos)
        self.assertEqual(code, 0, err)
        self.assertIn("(1 construcciones, 0 obras)", out)
        self.assertEqual(sorted(r["attributes"].get("seccion", 1) for r in self.core.records["construccion"]), [1, 2])

    def test_second_run_creates_nothing(self):
        self.cli("--obras", self.obras)
        before = len(self.posts())
        code, out, _ = self.cli("--obras", self.obras)
        self.assertEqual(code, 0)
        self.assertIn("done: 0 created, 2 skipped (0 construcciones, 0 obras)", out)
        self.assertEqual(len(self.posts()), before)

    def test_an_existing_predio_without_children_gets_them(self):
        self.core.add_record("predio_catastral", {"codigo_municipal": "120302-0001"})
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        self.assertIn("done: 1 created, 1 skipped (3 construcciones, 0 obras)", out)

    def test_a_failing_obras_step_is_completed_by_the_second_run(self):
        self.core.fail_on_record = "obra_complementaria"
        code, _, _ = self.cli("--obras", self.obras)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.core.records["predio_catastral"]), 2)
        self.assertEqual(len(self.core.records["construccion"]), 3)
        self.core.fail_on_record = None
        code, out, err = self.cli("--obras", self.obras)
        self.assertEqual(code, 0, err)
        self.assertIn("done: 0 created, 2 skipped (0 construcciones, 1 obras)", out)
        self.assertEqual(len(self.core.records["construccion"]), 3)
        self.assertEqual(len(self.core.records["obra_complementaria"]), 1)
        code, out, _ = self.cli("--obras", self.obras)
        self.assertIn("(0 construcciones, 0 obras)", out)
        self.assertEqual(len(self.core.records["obra_complementaria"]), 1)

    def test_a_pisos_step_failing_half_way_is_completed_by_the_second_run(self):
        self.core.fail_record_after = {"construccion": 1}
        code, _, _ = self.cli("--obras", self.obras)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.core.records["construccion"]), 1)
        self.core.fail_record_after = {}
        code, out, err = self.cli("--obras", self.obras)
        self.assertEqual(code, 0, err)
        self.assertIn("(2 construcciones, 1 obras)", out)
        keys = [(r["attributes"]["predio"], r["attributes"]["piso"]) for r in self.core.records["construccion"]]
        self.assertEqual(len(keys), 3)
        self.assertEqual(len(set(keys)), 3)  # no duplicates
        code, out, _ = self.cli("--obras", self.obras)
        self.assertIn("(0 construcciones, 0 obras)", out)
        self.assertEqual(len(self.core.records["construccion"]), 3)

    def test_only_the_missing_children_of_an_existing_predio_are_created(self):
        first = self.core.add_record("predio_catastral", {"codigo_municipal": "120302-0001"})
        self.core.add_record("construccion", {"piso": "1", "predio": first["id"]})
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        self.assertIn("done: 1 created, 1 skipped (2 construcciones, 0 obras)", out)  # piso 2 here, piso 1 of the new one
        self.assertEqual(len(self.core.records["construccion"]), 3)

    def test_a_relation_read_back_as_an_object_still_matches(self):
        first = self.core.add_record("predio_catastral", {"codigo_municipal": "120302-0001"})
        self.core.add_record("construccion", {"piso": "1", "predio": {"id": first["id"]}})
        code, out, _ = self.cli()
        self.assertIn("(2 construcciones, 0 obras)", out)

    def test_a_repeated_obra_key_is_a_problem(self):
        dup = write_csv(self, OBRAS + OBRAS.split("\n", 1)[1])
        code, _, err = run(imf.main, ["--fichas", self.fichas, "--pisos", self.pisos, "--obras", dup,
                                      "--core", self.core.base_url])
        self.assertEqual(code, 2)
        self.assertIn("repeated", err)
        self.assertEqual(self.core.requests, [])

    def test_every_problem_is_listed(self):
        rows = "".join(f"A{n},1,x\n" for n in range(60))
        bad = write_csv(self, "cod_pre,piso,area_construida\n" + rows)
        code, _, err = self.cli(pisos=bad)
        self.assertEqual(code, 2)
        self.assertEqual(err.count("problem: "), 120)  # 60 orphans and 60 bad areas

    def test_unreadable_input_exits_2(self):
        code, _, err = self.cli(fichas="/nonexistent/fichas.csv")
        self.assertEqual(code, 2)
        self.assertIn("input:", err)
        xlsx = write_xlsx(self, ["cod_pre"], [["1"]])
        code, _, err = self.cli("--sheet", "NoHay", fichas=xlsx)
        self.assertEqual(code, 2)
        self.assertIn("input:", err)
        self.assertEqual(self.core.requests, [])

    def test_dry_run_sends_nothing(self):
        code, out, _ = self.cli("--dry-run")
        self.assertEqual((code, self.core.requests), (0, []))
        self.assertIn("fichas: 2", out)

    def test_bad_rows_exit_2_and_send_nothing(self):
        bad = write_csv(self, "cod_pre,piso,material\n120302-0001,1,PLASTICO\n999,1,ADOBE\n")
        code, _, err = self.cli(pisos=bad)
        self.assertEqual(code, 2)
        self.assertIn("2 problems: nothing was sent to Core", err)
        self.assertEqual(self.core.requests, [])

    def test_core_refusal_exits_1(self):
        self.core.fail_on_record = "predio_catastral"
        code, _, err = self.cli()
        self.assertEqual(code, 1)
        self.assertIn("-> 400", err)


if __name__ == "__main__":
    unittest.main()
