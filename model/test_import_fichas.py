"""Tests for import_fichas.py: column mapping, validation, csv and xlsx input, and an idempotent load.

Run: cd model && python3 -m unittest -v
"""
import os
import unittest

import entregas as ent
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
TITULARES = ("cod_pre,tipo_documento,numero_documento,nombre,porcentaje,condicion\n"
            "120302-0001,DNI,00412345,ANA PEREZ QUISPE,50,PROPIETARIO\n"
            "120302-0001,DNI,00412345,ana  perez quispe,50,PROPIETARIO\n"
            "120302-0002,DNI,000000000,LUIS ROJAS,,POSEEDOR\n")


class ParseTests(unittest.TestCase):
    def test_fichas_map_and_types(self):
        path_rows = read_table(write_csv(self, FICHAS))
        fichas, problems = imf.fichas_from(path_rows, parse_map([], imf.FICHA_COLUMNS), ENUMS)
        self.assertEqual(problems, [])
        self.assertEqual(fichas[0][1]["codigo_municipal"], "120302-0001")
        self.assertEqual(fichas[0][1]["sector"], "01")
        self.assertEqual(fichas[0][1]["area_terreno"], "180.5")
        self.assertEqual(fichas[0][1]["anio_levantamiento"], 2026)
        self.assertEqual([f[1]["es_edificio"] for f in fichas], [False, True])

    def test_map_override(self):
        rows = read_table(write_csv(self, "CPM,cod_sect\nA-1,01\n"))
        fichas, problems = imf.fichas_from(rows, parse_map(["codigo_municipal=CPM"], imf.FICHA_COLUMNS), ENUMS)
        self.assertEqual((problems, fichas[0][1]["codigo_municipal"]), ([], "A-1"))
        with self.assertRaises(ValueError):
            parse_map(["color=COLOR"], imf.FICHA_COLUMNS)

    def test_bad_fichas_are_all_listed(self):
        rows = read_table(write_csv(self, "cod_pre,area_terreno,anio_levantamiento,es_edificio\n"
                                         "A,abc,2026,no\nA,1,2026,no\n,1,2026,no\nB,1,20.5,quizas\nC,-4,,\n"))
        _, problems = imf.fichas_from(rows, parse_map([], imf.FICHA_COLUMNS), ENUMS)
        self.assertEqual(len(problems), 6, problems)  # one row can have several

    def test_missing_column_is_a_problem(self):
        _, problems = imf.fichas_from(read_table(write_csv(self, "x\n1\n")), parse_map([], imf.FICHA_COLUMNS), ENUMS)
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

    def test_a_numeric_xlsx_clasificacion_is_its_table(self):
        # an xlsx number comes as 3.0 (tabular.code_text)
        path = write_xlsx(self, ["COD_PRE", "PISO", "CLASIFICACION", "SECCION"], [["A", "1", "3.0", "2.0"]])
        pisos, problems = imf.pisos_from(read_table(path), parse_map([], imf.PISO_COLUMNS), ENUMS, {"A"})
        self.assertEqual(problems, [])
        self.assertEqual((pisos[0][2]["clasificacion"], pisos[0][2]["seccion"]), ("EDIFICIO-OFICINAS", 2))

    def test_a_bad_seccion_is_one_problem_not_also_a_repeated_piso(self):
        rows = read_table(write_csv(self, "cod_pre,piso,seccion\nA,1,\nA,1,0\n"))
        _, problems = imf.pisos_from(rows, parse_map([], imf.PISO_COLUMNS), ENUMS, {"A"})
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("seccion", problems[0])

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
        fichas, problems = imf.fichas_from(read_table(path), parse_map([], imf.FICHA_COLUMNS), ENUMS)
        self.assertEqual(problems, [])
        self.assertEqual((fichas[0][1]["sector"], fichas[0][1]["area_terreno"]), ("1", "100.5"))

    def test_estado_and_fecha_levantamiento(self):
        rows = read_table(write_csv(self, "cod_pre,estado_levantamiento,fecha_levantamiento\nA,sin_levantar,2026-09-30\n"
                                          "B,,46000\nC,LEVANTADO,30/09/2026\n"))
        fichas, problems = imf.fichas_from(rows, parse_map([], imf.FICHA_COLUMNS), ENUMS)
        self.assertEqual(fichas[0][1]["estado_levantamiento"], "SIN_LEVANTAR")
        self.assertEqual(fichas[0][1]["fecha_levantamiento"], "2026-09-30")
        self.assertEqual(fichas[1][1]["fecha_levantamiento"], "2025-12-09")   # xlsx serial 46000
        self.assertIsNone(fichas[1][1]["estado_levantamiento"])               # no default
        self.assertEqual(len(problems), 2, problems)                          # C: estado and fecha

    def test_parse_date_accepts_only_iso_or_a_serial(self):
        # Python 3.11+'s fromisoformat also reads "20260930" and ISO week dates like "2026-W01-2": neither is one
        # of the two documented forms, so only a strict YYYY-MM-DD shape goes to fromisoformat
        self.assertEqual(imf.parse_date("2026-09-30"), ("2026-09-30", None))
        self.assertEqual(imf.parse_date("46000"), ("2025-12-09", None))
        self.assertEqual(imf.parse_date("46000.0"), ("2025-12-09", None))
        self.assertIsNone(imf.parse_date(None)[0])
        for bad in ("2026-W01-2", "2026-13-45", "30/09/2026"):
            self.assertIsNotNone(imf.parse_date(bad)[1], bad)

    def test_parse_date_a_serial_out_of_range_is_a_problem_not_an_overflowerror(self):
        # "20260930" reads as a serial (all digits, no dashes): both it and a huge serial overflow
        # datetime.date's range; parse_date must report a problem, never raise
        for bad in ("20260930", "2958466", str(10 ** 9)):
            value, error = imf.parse_date(bad)
            self.assertIsNone(value, bad)
            self.assertIsNotNone(error, bad)

    def test_vinculo_columns(self):
        rows = read_table(write_csv(self, "cod_pre,vinculo_metodo,vinculo_revisado,cuc,codigo_referencia_catastral\n"
                                          "A,llave_hu_mz_lote,si,0001,110101-01-001-001\n"
                                          "B,VECINO,quizas,,\n"))
        fichas, problems = imf.fichas_from(rows, parse_map([], imf.FICHA_COLUMNS), ENUMS)
        self.assertEqual([fichas[0][1][k] for k in ("vinculo_metodo", "vinculo_revisado", "cuc")],
                         ["LLAVE_HU_MZ_LOTE", True, "0001"])
        self.assertEqual(fichas[0][1]["codigo_referencia_catastral"], "110101-01-001-001")
        self.assertEqual(len(problems), 2, problems)

    def test_tipo_predio_column(self):
        rows = read_table(write_csv(self, "cod_pre,tipo_predio\nA,rustico\nB,\nC,AGRICOLA\n"))
        fichas, problems = imf.fichas_from(rows, parse_map([], imf.FICHA_COLUMNS), ENUMS)
        self.assertEqual(fichas[0][1]["tipo_predio"], "RUSTICO")
        self.assertIsNone(fichas[1][1]["tipo_predio"])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("tipo_predio", problems[0])

    def test_present_fields_reads_the_header(self):
        rows = read_table(write_csv(self, "cod_pre,uso\nA,\n"))
        self.assertEqual(imf.present_fields(rows, parse_map([], imf.FICHA_COLUMNS), ["uso", "lote"]), {"uso"})


class TitularParseTests(unittest.TestCase):
    """titulares_from (Ley 29733): a problem or an aviso never names a document or a nombre, only codigo and row."""

    def pm(self):
        return parse_map([], imf.TITULAR_COLUMNS)

    def test_the_document_goes_as_it_comes_and_fillers_go_empty(self):
        rows = read_table(write_csv(self, TITULARES))
        t, problems, avisos = imf.titulares_from(rows, self.pm(), {"120302-0001", "120302-0002"})
        self.assertEqual(problems, [])
        self.assertEqual(t[0][2]["numero_documento"], "00412345")
        self.assertIsNone(t[-1][2]["numero_documento"])
        self.assertIn("titulares 120302-0002 fila 4: documento de relleno, queda vacío", avisos)

    def test_a_repeated_titular_loads_once_and_the_sum_is_reported(self):
        rows = read_table(write_csv(self, TITULARES))
        t, problems, avisos = imf.titulares_from(rows, self.pm(), {"120302-0001", "120302-0002"})
        self.assertEqual(len([x for x in t if x[1] == "120302-0001"]), 1)
        self.assertIn("titulares 120302-0001 fila 3: repetido, se carga una vez", avisos)
        # rows as given: 50 + 50 = 100, not flagged
        self.assertFalse([a for a in avisos if a.startswith("titulares 120302-0001: suman")])

    def test_a_predio_at_200_percent_is_reported(self):
        rows = read_table(write_csv(self, "cod_pre,numero_documento,nombre,porcentaje\n"
                                          "A,1,UNO,100\nA,2,DOS,100\n"))
        _, problems, avisos = imf.titulares_from(rows, self.pm(), {"A"})
        self.assertEqual(problems, [])
        self.assertIn("titulares A: suman 200 %", avisos)

    def test_a_predio_whose_titulares_all_lack_porcentaje_is_not_reported(self):
        rows = read_table(write_csv(self, "cod_pre,numero_documento,nombre\nA,1,UNO\nA,2,DOS\n"))
        _, problems, avisos = imf.titulares_from(rows, self.pm(), {"A"})
        self.assertEqual((problems, avisos), ([], []))

    def test_the_report_never_prints_names_or_documents(self):
        for text in (" ".join(imf.titulares_from(
                read_table(write_csv(self, TITULARES)), self.pm(), {"120302-0001", "120302-0002"})[1]),
                    " ".join(imf.titulares_from(
                read_table(write_csv(self, TITULARES)), self.pm(), {"120302-0001", "120302-0002"})[2])):
            for secreto in ("ANA", "PEREZ", "QUISPE", "00412345", "LUIS", "ROJAS"):
                self.assertNotIn(secreto, text)

    def test_a_titular_of_a_code_outside_the_fichas_is_a_problem(self):
        rows = read_table(write_csv(self, "cod_pre,numero_documento,nombre\nZ,1,UNO\n"))
        _, problems, _ = imf.titulares_from(rows, self.pm(), {"A"})
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("not in the fichas", problems[0])

    def test_an_unreadable_porcentaje_is_a_problem(self):
        rows = read_table(write_csv(self, "cod_pre,numero_documento,nombre,porcentaje\nA,1,UNO,abc\n"))
        _, problems, _ = imf.titulares_from(rows, self.pm(), {"A"})
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("porcentaje", problems[0])

    def test_missing_codigo_municipal_column_is_a_problem(self):
        _, problems, _ = imf.titulares_from(read_table(write_csv(self, "x\n1\n")), self.pm(), {"A"})
        self.assertEqual(len(problems), 1)


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
        self.assertIn("done: 2 created, 0 skipped (3 construcciones, 1 obras, 0 titulares)", out)
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
        self.assertIn("(2 construcciones, 0 obras, 0 titulares)", out)
        primera, segunda = sorted((r["attributes"] for r in self.core.records["construccion"]),
                                  key=lambda a: a.get("seccion", 1))
        self.assertEqual((primera["piso"], primera["clasificacion"]), ("5", ENUMS["clasificacion"][0]))
        self.assertNotIn("seccion", primera)
        self.assertEqual((segunda["piso"], segunda["seccion"]), ("5", 2))
        self.assertNotIn("clasificacion", segunda)
        code, out, _ = self.cli(pisos=pisos)
        self.assertIn("(0 construcciones, 0 obras, 0 titulares)", out)
        self.assertEqual(len(self.core.records["construccion"]), 2)

    def test_a_piso_core_has_without_seccion_is_seccion_1(self):
        # perené's pisos were loaded before seccion existed: a second section of the same piso is new, the first is not
        first = self.core.add_record("predio_catastral", {"codigo_municipal": "120302-0001"})
        self.core.add_record("construccion", {"piso": "1", "predio": first["id"]})
        pisos = write_csv(self, "cod_pre,piso,seccion\n120302-0001,1,1\n120302-0001,1,2\n")
        code, out, err = self.cli(pisos=pisos)
        self.assertEqual(code, 0, err)
        self.assertIn("(1 construcciones, 0 obras, 0 titulares)", out)
        self.assertEqual(sorted(r["attributes"].get("seccion", 1) for r in self.core.records["construccion"]), [1, 2])

    def test_second_run_creates_nothing(self):
        self.cli("--obras", self.obras)
        before = len(self.posts())
        code, out, _ = self.cli("--obras", self.obras)
        self.assertEqual(code, 0)
        self.assertIn("done: 0 created, 2 skipped (0 construcciones, 0 obras, 0 titulares)", out)
        self.assertEqual(len(self.posts()), before)

    def test_an_existing_predio_without_children_gets_them(self):
        self.core.add_record("predio_catastral", {"codigo_municipal": "120302-0001"})
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        self.assertIn("done: 1 created, 1 skipped (3 construcciones, 0 obras, 0 titulares)", out)

    def test_a_failing_obras_step_is_completed_by_the_second_run(self):
        self.core.fail_on_record = "obra_complementaria"
        code, _, _ = self.cli("--obras", self.obras)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.core.records["predio_catastral"]), 2)
        self.assertEqual(len(self.core.records["construccion"]), 3)
        self.core.fail_on_record = None
        code, out, err = self.cli("--obras", self.obras)
        self.assertEqual(code, 0, err)
        self.assertIn("done: 0 created, 2 skipped (0 construcciones, 1 obras, 0 titulares)", out)
        self.assertEqual(len(self.core.records["construccion"]), 3)
        self.assertEqual(len(self.core.records["obra_complementaria"]), 1)
        code, out, _ = self.cli("--obras", self.obras)
        self.assertIn("(0 construcciones, 0 obras, 0 titulares)", out)
        self.assertEqual(len(self.core.records["obra_complementaria"]), 1)

    def test_a_pisos_step_failing_half_way_is_completed_by_the_second_run(self):
        self.core.fail_record_after = {"construccion": 1}
        code, _, _ = self.cli("--obras", self.obras)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.core.records["construccion"]), 1)
        self.core.fail_record_after = {}
        code, out, err = self.cli("--obras", self.obras)
        self.assertEqual(code, 0, err)
        self.assertIn("(2 construcciones, 1 obras, 0 titulares)", out)
        keys = [(r["attributes"]["predio"], r["attributes"]["piso"]) for r in self.core.records["construccion"]]
        self.assertEqual(len(keys), 3)
        self.assertEqual(len(set(keys)), 3)  # no duplicates
        code, out, _ = self.cli("--obras", self.obras)
        self.assertIn("(0 construcciones, 0 obras, 0 titulares)", out)
        self.assertEqual(len(self.core.records["construccion"]), 3)

    def test_only_the_missing_children_of_an_existing_predio_are_created(self):
        first = self.core.add_record("predio_catastral", {"codigo_municipal": "120302-0001"})
        self.core.add_record("construccion", {"piso": "1", "predio": first["id"]})
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        self.assertIn("done: 1 created, 1 skipped (2 construcciones, 0 obras, 0 titulares)", out)  # piso 2 here, piso 1 of the new one
        self.assertEqual(len(self.core.records["construccion"]), 3)

    def test_a_relation_read_back_as_an_object_still_matches(self):
        first = self.core.add_record("predio_catastral", {"codigo_municipal": "120302-0001"})
        self.core.add_record("construccion", {"piso": "1", "predio": {"id": first["id"]}})
        code, out, _ = self.cli()
        self.assertIn("(2 construcciones, 0 obras, 0 titulares)", out)

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

    def test_pisos_is_required_without_entrega(self):
        code, _, err = run(imf.main, ["--fichas", self.fichas, "--core", self.core.base_url])
        self.assertEqual(code, 2)
        self.assertIn("--pisos", err)
        self.assertEqual(self.core.requests, [])

    def test_titulares_hang_from_their_predio_and_carry_its_code(self):
        titulares = write_csv(self, TITULARES)
        code, out, err = self.cli("--titulares", titulares)
        self.assertEqual(code, 0, err)
        self.assertIn("(3 construcciones, 0 obras, 2 titulares)", out)  # the repeated ANA loads once
        predio = next(r for r in self.core.records["predio_catastral"] if r["attributes"]["codigo_municipal"] == "120302-0001")
        titular = next(r for r in self.core.records["titular_catastral"] if r["attributes"]["predio"] == predio["id"])
        self.assertEqual(titular["attributes"]["codigo_municipal"], "120302-0001")

    def test_a_second_run_creates_no_titular_again(self):
        titulares = write_csv(self, TITULARES)
        self.cli("--titulares", titulares)
        before = len(self.core.records["titular_catastral"])
        code, out, _ = self.cli("--titulares", titulares)
        self.assertEqual(code, 0)
        self.assertIn("(0 construcciones, 0 obras, 0 titulares)", out)
        self.assertEqual(len(self.core.records["titular_catastral"]), before)

    def test_the_report_never_prints_names_or_documents(self):
        titulares = write_csv(self, TITULARES)
        code, out, err = self.cli("--titulares", titulares)
        self.assertEqual(code, 0, err)
        for secreto in ("ANA", "PEREZ", "QUISPE", "00412345", "LUIS", "ROJAS"):
            self.assertNotIn(secreto, out + err)

    def test_a_core_refusal_writing_a_titular_never_prints_its_body(self):
        # Core's own validation error can echo back a submitted value (Ley 29733): the body is never printed for a
        # titular_catastral write, even on a refusal.
        core = FakeCore(fail_on_record="titular_catastral",
                        fail_on_record_body={"detail": "Invalid option",
                                             "errors": [{"field": "numero_documento", "message": "SECRETO-00412345-ANA"}]})
        self.addCleanup(core.stop)
        titulares = write_csv(self, TITULARES)
        code, out, err = run(imf.main, ["--fichas", self.fichas, "--pisos", self.pisos, "--titulares", titulares,
                                        "--core", core.base_url])
        self.assertEqual(code, 1)
        self.assertIn("cuerpo omitido", err)
        self.assertNotIn("SECRETO", out + err)


class EntregaLoadTests(unittest.TestCase):
    """--entrega: an upsert through the API, every write with the entrega's code as X-Change-Reason (ADR-013)."""

    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.stop)
        self.fichas = write_csv(self, FICHAS)
        self.pisos = write_csv(self, PISOS)
        self.obras = write_csv(self, OBRAS)

    def cli(self, *extra, fichas=None, pisos=None):
        return run(imf.main, ["--fichas", fichas or self.fichas, "--pisos", pisos or self.pisos, "--core", self.core.base_url,
                              *extra])

    def entrega(self, *extra, codigo="E-1", fichas=None, pisos=None):
        return self.cli("--entrega", codigo, "--fecha-corte", "2026-10-01", "--fuente", "BARRIDO", *extra, fichas=fichas,
                        pisos=pisos)

    def writes(self):
        return [r for r in self.core.requests if r[0] in ("POST", "PATCH", "DELETE") and "records" in r[1]]

    def entregas(self):
        return {r["attributes"]["codigo"]: r for r in self.core.records.get("entrega_catastral", [])}

    def predio(self, codigo):
        return next(r for r in self.core.records["predio_catastral"] if r["attributes"]["codigo_municipal"] == codigo)

    def test_first_load_creates_the_fichas_and_the_entrega(self):
        code, out, err = self.entrega("--obras", self.obras, "--descripcion", "barrido de octubre")
        self.assertEqual(code, 0, err)
        e = self.core.records["entrega_catastral"][0]
        a = e["attributes"]
        self.assertEqual((a["codigo"], a["altas"], a["cambios"], a["sin_cambio"], a["ausentes"], a["fuente"]),
                         ("E-1", 2, 0, 0, 0, "BARRIDO"))
        self.assertEqual((a["fecha_corte"], a["descripcion"]), ("2026-10-01", "barrido de octubre"))
        self.assertEqual(a["archivo_sha256"], ent.sha256_of([self.fichas, self.pisos, self.obras]))
        self.assertTrue(all(p["attributes"]["entrega"] == e["id"] for p in self.core.records["predio_catastral"]))
        self.assertEqual(len(self.core.records["construccion"]), 3)
        self.assertEqual(self.core.records["obra_complementaria"][0]["attributes"]["predio"], self.predio("120302-0001")["id"])
        self.assertIn("alta 120302-0001", out)
        self.assertIn("done: entrega E-1: 2 altas, 0 cambios, 0 sin cambio, 0 ausentes", out)

    def test_the_same_entrega_twice_changes_nothing(self):
        self.entrega("--obras", self.obras)
        before = len(self.writes())
        code, out, err = self.entrega("--obras", self.obras)
        self.assertEqual((code, len(self.writes())), (0, before), err)
        self.assertIn("sin cambio 120302-0001", out)
        self.assertIn("done: entrega E-1: 0 altas, 0 cambios, 2 sin cambio, 0 ausentes", out)
        self.assertEqual(self.entregas()["E-1"]["attributes"]["altas"], 2)

    def test_a_later_entrega_with_nothing_new_writes_nothing_not_even_itself(self):
        self.entrega()
        before = len(self.writes())
        code, out, err = self.entrega(codigo="E-2")
        self.assertEqual((code, len(self.writes())), (0, before), err)
        self.assertNotIn("E-2", self.entregas())
        self.assertIn("done: entrega E-2: 0 altas, 0 cambios, 2 sin cambio, 0 ausentes", out)

    def test_a_corrected_piso_is_patched_and_reported(self):
        self.entrega()
        corrected = write_csv(self, PISOS.replace("120302-0001,2,86,", "120302-0001,2,90,"))
        code, out, err = self.entrega(codigo="E-2", pisos=corrected)
        self.assertEqual(code, 0, err)
        self.assertIn("cambio 120302-0001 piso 2/1: area_construida 86 → 90", out)
        self.assertIn("sin cambio 120302-0002", out)
        piso = next(r for r in self.core.records["construccion"] if r["attributes"]["piso"] == "2")
        patches = [r for r in self.core.requests if r[0] == "PATCH" and r[1].endswith(piso["id"])]
        self.assertEqual([r[3] for r in patches], [{"attributes": {"area_construida": "90"}}])
        e2 = self.entregas()["E-2"]
        self.assertEqual((e2["attributes"]["altas"], e2["attributes"]["cambios"], e2["attributes"]["sin_cambio"]), (0, 1, 1))
        # the predio points to the last entrega that changed it; the one without changes keeps E-1
        self.assertEqual(self.predio("120302-0001")["attributes"]["entrega"], e2["id"])
        self.assertEqual(self.predio("120302-0002")["attributes"]["entrega"], self.entregas()["E-1"]["id"])

    def test_a_changed_field_of_the_ficha_is_patched_with_the_entrega(self):
        self.entrega()
        changed = write_csv(self, FICHAS.replace("180.50,9", "175,9"))
        code, out, err = self.entrega(codigo="E-2", fichas=changed)
        self.assertEqual(code, 0, err)
        self.assertIn("cambio 120302-0001: area_terreno 180.5 → 175", out)
        p = self.predio("120302-0001")
        patches = [r[3] for r in self.core.requests if r[0] == "PATCH" and r[1].endswith(p["id"])]
        self.assertEqual(patches, [{"attributes": {"area_terreno": "175", "entrega": self.entregas()["E-2"]["id"]}}])

    def test_a_changed_category_letter_is_reported(self):
        # the single `categorias` column stands for the seven letter fields
        self.entrega()
        changed = write_csv(self, PISOS.replace("BBCBBCB", "BBCBBCA"))
        code, out, err = self.entrega(codigo="E-2", pisos=changed)
        self.assertEqual(code, 0, err)
        self.assertIn("cambio 120302-0001 piso 2/1: instalaciones B → A", out)

    def test_an_absent_ficha_is_listed_not_deleted(self):
        self.core.add_record("predio_catastral", {"codigo_municipal": "120302-0099"})
        code, out, err = self.entrega()
        self.assertEqual(code, 0, err)
        self.assertIn("ausente 120302-0099", out)
        self.assertEqual(len(self.core.records["predio_catastral"]), 3)
        self.assertEqual(self.entregas()["E-1"]["attributes"]["ausentes"], 1)
        self.assertNotIn("entrega", self.predio("120302-0099")["attributes"])

    def test_a_piso_the_entrega_no_longer_brings_is_listed_and_kept(self):
        self.entrega()
        fewer = write_csv(self, "\n".join(line for line in PISOS.splitlines() if ",2,86," not in line) + "\n")
        code, out, err = self.entrega(codigo="E-2", pisos=fewer)
        self.assertEqual(code, 0, err)
        self.assertIn("ausente 120302-0001 piso 2/1", out)
        self.assertEqual(len(self.core.records["construccion"]), 3)

    def test_reemplazar_pisos_deletes_the_pisos_the_entrega_no_longer_brings(self):
        self.entrega()
        fewer = write_csv(self, "\n".join(line for line in PISOS.splitlines() if ",2,86," not in line) + "\n")
        code, out, err = self.entrega("--reemplazar-pisos", codigo="E-2", pisos=fewer)
        self.assertEqual(code, 0, err)
        self.assertIn("cambio 120302-0001 piso 2/1: baja", out)
        self.assertEqual(sorted(r["attributes"]["piso"] for r in self.core.records["construccion"]), ["1", "1"])
        deletes = [r for r in self.core.reasons if r[0] == "DELETE"]
        self.assertEqual([r[2] for r in deletes], ["E-2"])
        self.assertEqual(self.predio("120302-0001")["attributes"]["entrega"], self.entregas()["E-2"]["id"])

    def test_reemplazar_obras_deletes_an_obra_whose_year_changed(self):
        self.entrega("--obras", self.obras)
        other_year = write_csv(self, OBRAS.replace(",42,1998,", ",42,1999,"))
        code, out, err = self.entrega("--obras", other_year, "--reemplazar-obras", codigo="E-2")
        self.assertEqual(code, 0, err)
        self.assertIn("cambio 120302-0001 obra CERCOS METALICOS|88/1999: alta", out)
        self.assertIn("cambio 120302-0001 obra CERCOS METALICOS|88/1998: baja", out)
        self.assertEqual([r["attributes"]["anio_construccion"] for r in self.core.records["obra_complementaria"]], [1999])

    def test_a_new_piso_of_an_existing_ficha_is_created_under_it(self):
        self.entrega()
        more = write_csv(self, PISOS + "120302-0002,2,30,2020,CONCRETO,BUENO,AABAABA\n")
        code, out, err = self.entrega(codigo="E-2", pisos=more)
        self.assertEqual(code, 0, err)
        self.assertIn("cambio 120302-0002 piso 2/1: alta", out)
        new = next(r for r in self.core.records["construccion"] if r["attributes"]["area_construida"] == "30")
        self.assertEqual(new["attributes"]["predio"], self.predio("120302-0002")["id"])

    def test_an_entrega_may_bring_only_fichas(self):
        self.entrega()
        code, out, err = run(imf.main, ["--fichas", self.fichas, "--core", self.core.base_url, "--entrega", "GIS-1",
                                        "--fecha-corte", "2026-10-02", "--fuente", "gis"])
        self.assertEqual(code, 0, err)
        self.assertIn("done: entrega GIS-1: 0 altas, 0 cambios, 2 sin cambio, 0 ausentes", out)
        self.assertNotIn("ausente 120302-0001 piso", out)
        self.assertEqual(len(self.core.records["construccion"]), 3)

    def test_every_write_carries_the_entrega_as_reason(self):
        self.entrega("--obras", self.obras)
        writes = [x for x in self.core.reasons if x[0] in ("POST", "PATCH", "DELETE") and "/records" in x[1]]
        self.assertTrue(writes)
        self.assertEqual({r for _, _, r in writes}, {"E-1"})

    def test_dry_run_reports_and_writes_nothing(self):
        code, out, err = self.entrega("--dry-run")
        self.assertEqual((code, self.writes()), (0, []), err)
        self.assertIn("alta 120302-0001", out)
        self.assertIn("entrega E-1: 2 altas, 0 cambios, 0 sin cambio, 0 ausentes", out)
        self.assertNotIn("done:", out)
        self.assertTrue(all(r[0] == "GET" for r in self.core.requests if r[1] != "/api/auth/login"))

    def test_same_codigo_another_file_exits_2(self):
        self.entrega()
        before = len(self.writes())
        corrected = write_csv(self, PISOS.replace("120302-0001,2,86,", "120302-0001,2,90,"))
        code, _, err = self.entrega(pisos=corrected)
        self.assertEqual((code, len(self.writes())), (2, before))
        self.assertIn("E-1", err)
        self.assertEqual(sorted(r["attributes"]["area_construida"] for r in self.core.records["construccion"]),
                         ["120.4", "50", "86"])

    def test_a_run_that_failed_half_way_is_completed_and_keeps_the_summary(self):
        self.core.fail_record_after = {"construccion": 1}
        self.assertEqual(self.entrega()[0], 1)
        self.core.fail_record_after = {}
        before = len(self.core.requests)
        code, _, err = self.entrega()
        self.assertEqual(code, 0, err)
        # the predios already point to E-1: no PATCH of their entrega again
        self.assertEqual([r for r in self.core.requests[before:] if r[0] == "PATCH"], [])
        self.assertEqual(len(self.core.records["construccion"]), 3)
        keys = {(r["attributes"]["predio"], r["attributes"]["piso"]) for r in self.core.records["construccion"]}
        self.assertEqual(len(keys), 3)
        self.assertEqual(len(self.core.records["predio_catastral"]), 2)
        self.assertEqual(len(self.core.records["entrega_catastral"]), 1)
        self.assertEqual(self.core.records["entrega_catastral"][0]["attributes"]["altas"], 2)
        # a third run finds nothing to do
        before = len(self.writes())
        self.assertEqual(self.entrega()[0], 0)
        self.assertEqual(len(self.writes()), before)

    def test_reemplazar_without_entrega_or_its_file_exits_2(self):
        self.assertEqual(self.cli("--reemplazar-pisos")[0], 2)
        self.assertEqual(self.cli("--obras", self.obras, "--reemplazar-obras")[0], 2)
        code, _, err = run(imf.main, ["--fichas", self.fichas, "--core", self.core.base_url, "--entrega", "E-1",
                                      "--fecha-corte", "2026-10-01", "--fuente", "BARRIDO", "--reemplazar-pisos"])
        self.assertEqual(code, 2)
        self.assertIn("--pisos", err)
        self.assertEqual(self.entrega("--reemplazar-obras")[0], 2)
        self.assertEqual(self.core.requests, [])

    def test_a_bad_codigo_fecha_or_fuente_exits_2(self):
        bad = [
            ["--entrega", "E 1", "--fecha-corte", "2026-10-01", "--fuente", "BARRIDO"],
            ["--entrega", "Entrega-ñ", "--fecha-corte", "2026-10-01", "--fuente", "BARRIDO"],
            ["--entrega", "E-1", "--fecha-corte", "2026-10-01", "--fuente", "CENSO"],
            ["--entrega", "E-1", "--fuente", "BARRIDO"],
            ["--entrega", "E-1", "--fecha-corte", "2026-10-01"],
            ["--entrega", "E-1", "--fecha-corte", "01/10/2026", "--fuente", "BARRIDO"],
            ["--fecha-corte", "2026-10-01"],
        ]
        for argv in bad:
            code, _, err = self.cli(*argv)
            self.assertEqual(code, 2, argv)
            self.assertTrue(err, argv)
        self.assertEqual(self.core.requests, [])

    def test_an_entrega_creates_titulares_then_patches_a_changed_one_and_deletes_none(self):
        titulares = write_csv(self, "cod_pre,numero_documento,nombre,porcentaje,condicion\n"
                                    "120302-0001,00412345,ANA PEREZ,50,PROPIETARIO\n")
        code, out, err = self.entrega("--titulares", titulares)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.core.records["titular_catastral"]), 1)
        changed = write_csv(self, "cod_pre,numero_documento,nombre,porcentaje,condicion\n"
                                  "120302-0001,00412345,ANA PEREZ,80,PROPIETARIO\n")
        code, out, err = self.cli("--titulares", changed, "--entrega", "E-2", "--fecha-corte", "2026-10-01",
                                  "--fuente", "BARRIDO")
        self.assertEqual(code, 0, err)
        self.assertIn("cambio 120302-0001 titular fila 2: porcentaje", out)
        titular = self.core.records["titular_catastral"][0]
        self.assertEqual(titular["attributes"]["porcentaje"], "80")
        self.assertEqual(len(self.core.records["titular_catastral"]), 1)  # patched, never deleted or duplicated
        self.assertEqual([r for r in self.core.reasons if r[0] == "DELETE"], [])

    def test_archivo_sha256_includes_the_titulares_file_last(self):
        titulares = write_csv(self, "cod_pre,numero_documento,nombre\n120302-0001,1,UNO\n")
        code, out, err = self.entrega("--obras", self.obras, "--titulares", titulares)
        self.assertEqual(code, 0, err)
        e = self.core.records["entrega_catastral"][0]
        self.assertEqual(e["attributes"]["archivo_sha256"],
                         ent.sha256_of([self.fichas, self.pisos, self.obras, titulares]))

    def test_the_entrega_report_never_prints_names_or_documents(self):
        titulares = write_csv(self, TITULARES)
        code, out, err = self.entrega("--titulares", titulares)
        self.assertEqual(code, 0, err)
        for secreto in ("ANA", "PEREZ", "QUISPE", "00412345", "LUIS", "ROJAS"):
            self.assertNotIn(secreto, out + err)


if __name__ == "__main__":
    unittest.main()
