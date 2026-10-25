"""Tests for convertir_comparacion_ica.py: the fichas, pisos and titulares it turns Ica's comparison workbook into.

Synthetic workbook only (codes like S-0001, made-up names).
Run: cd model && python3 -m unittest -v test_convertir_comparacion_ica
"""
import csv
import os
import re
import tempfile
import unittest

import convertir_comparacion_ica as cv
import import_fichas as imf
from fake_core import FakeCore
from helpers import run, write_csv, write_xlsx_sheets
from import_fichas import CATEGORIAS
from tabular import load_enums, parse_map, read_table

HERE = os.path.dirname(os.path.abspath(__file__))
ENUMS = load_enums(os.path.join(HERE, "model.json"))

UNIDAD = "11-01-01-02-015-007-01-01-01-001"
PREDIO_HEADER = ["cod_predio_rentas", "codigo_unidad_catastro", "area_terreno_catastro", "urbanizacion_catastro",
                 "cuc_catastro"]
CONSTRUCCION_HEADER = ["cod_predio", "nivel_catastro", "ano_catastro", "area_construida_nivel_catastro",
                       "material_catastro", "estado_conservacion_catastro", "muros_catastro", "techos_catastro",
                       "pisos_catastro", "puertas_catastro", "revestimientos_catastro", "banos_catastro",
                       "instalaciones_catastro"]
FICHAS_CSV = ["cod_pre", "cod_sect", "cod_mzn", "cod_lote", "area_terreno", "uso", "id_aranc", "estado_levantamiento",
              "vinculo_metodo", "codigo_referencia_catastral", "cuc"]
FICHAS_CONTEOS = {"predios_sin_vinculo", "fichas", "fichas_repetidas", "fichas_sin_levantar", "fichas_parciales",
                  "fichas_area_vacia"}
PISOS_CONTEOS = {"pisos", "pisos_de_predios_sin_ficha", "pisos_nivel_71_81", "niveles_sin_numero",
                 "pisos_en_seccion_2_o_mas", "anios_vaciados", "areas_construidas_vaciadas", "letras_vaciadas",
                 "materiales_vaciados", "estados_vaciados"}


TITULARES_HEADER = ["cod_predio", "tipo_documento_catastro", "nro_documento_catastro", "nombre_catastro",
                    "porcentaje", "condicion_catastro"]
# the libro v3's titulares_catastro: no condicion of the titular; `estado` is the comparison's, never a condicion
TITULARES_HEADER_V3 = ["cod_predio", "tipo_documento_catastro", "nro_documento_catastro", "nombre_catastro",
                       "porcentaje", "estado"]
TITULARES_CSV = ["cod_pre", "tipo_documento", "numero_documento", "nombre", "porcentaje", "condicion"]
# made-up personal data that must never reach stdout or stderr
NOMBRE, DOCUMENTO = "ROSA QUISPE SINTETICA", "00412345"


def predio(cod="S-0001", unidad=UNIDAD, area="150.50", urbanizacion="URB SINTETICA", cuc=None):
    return [cod, unidad, area, urbanizacion, cuc]


def construccion(cod="S-0001", nivel="NIVEL 01", anio="1998", area="80", material="2", estado="2", letras="CCDCCDC"):
    return [cod, nivel, anio, area, material, estado, *letras]


def titular(cod="S-0001", tipo="DNI", numero=DOCUMENTO, nombre=NOMBRE, porcentaje="100", condicion="PROPIETARIO"):
    return [cod, tipo, numero, nombre, porcentaje, condicion]


def escribir_libro(testcase, predios, construcciones=(), titulares=(), predio_header=PREDIO_HEADER,
                   construccion_header=CONSTRUCCION_HEADER, titulares_header=TITULARES_HEADER, sin=()):
    """The workbook: a rentas sheet first, as in the real one, then the three catastro sheets, less those in `sin`."""
    hojas = {
        "predio_rentas": (["cod_predio", "area_terreno"], [["S-0001", "999"]]),
        "predio_catastro": (predio_header, predios),
        "construccion_catastro": (construccion_header, list(construcciones)),
        "titulares_rentas": (["cod_predio", "nombre"], [["S-0001", "OTRO NOMBRE RENTAS"]]),
        "titulares_catastro": (titulares_header, list(titulares)),
    }
    return write_xlsx_sheets(testcase, {k: v for k, v in hojas.items() if k not in sin})


def libro(testcase, predios, construcciones=(), predio_header=PREDIO_HEADER):
    """The workbook's catastro sheets as read_table reads them."""
    path = escribir_libro(testcase, predios, construcciones, predio_header=predio_header)
    return read_table(path, "predio_catastro"), read_table(path, "construccion_catastro")


def convertir_fichas(testcase, predios, con_pisos=(), con_titulares=(), vinculos=None, predio_header=PREDIO_HEADER):
    filas, _ = libro(testcase, predios, predio_header=predio_header)
    return cv.fichas_de(filas, set(con_pisos), set(con_titulares), vinculos, parse_map([], cv.PREDIO_COLUMNS))


def convertir_pisos(testcase, construcciones, codigos=("S-0001",), **kwargs):
    _, filas = libro(testcase, [predio()], construcciones)
    return cv.pisos_de(filas, set(codigos), parse_map([], cv.CONSTRUCCION_COLUMNS), ENUMS, **kwargs)


class FichasTests(unittest.TestCase):
    def ficha_de(self, con_pisos=(), con_titulares=(), **kwargs):
        fichas, _ = convertir_fichas(self, [predio(**kwargs)], con_pisos, con_titulares)
        self.assertEqual(len(fichas), 1)
        return fichas[0]

    def test_sector_manzana_lote_and_the_reference_code_come_from_the_unidad_catastral(self):
        f = self.ficha_de(unidad="11-01-01-02-015-007-01-01-01-001")
        self.assertEqual((f["cod_sect"], f["cod_mzn"], f["cod_lote"]), ("02", "015", "007"))
        self.assertEqual(f["codigo_referencia_catastral"], "11-01-01-02-015-007-01-01-01-001")
        self.assertEqual(f["cod_pre"], "S-0001")

    def test_a_ficha_without_unidad_catastral_is_not_loaded(self):
        fichas, n = convertir_fichas(self, [predio(cod="S-0001", unidad=None), predio(cod="S-0002")])
        self.assertEqual([f["cod_pre"] for f in fichas], ["S-0002"])
        self.assertEqual((n["predios_sin_vinculo"], n["fichas"]), (1, 1))

    def test_with_vinculos_a_ficha_without_a_vinculo_row_is_not_loaded_and_the_others_carry_the_metodo(self):
        fichas, n = convertir_fichas(self, [predio(cod="S-0001"), predio(cod="S-0002")],
                                     vinculos={"S-0002": "GEOMETRICO"})
        self.assertEqual([(f["cod_pre"], f["vinculo_metodo"]) for f in fichas], [("S-0002", "GEOMETRICO")])
        self.assertEqual(n["predios_sin_vinculo"], 1)

    def test_without_vinculos_the_metodo_is_empty(self):
        self.assertEqual(self.ficha_de()["vinculo_metodo"], "")

    def test_an_empty_ficha_is_sin_levantar_without_the_rentas_area(self):
        fichas, n = convertir_fichas(self, [predio(area="0", urbanizacion=None)])
        f = fichas[0]
        self.assertEqual((f["estado_levantamiento"], f["area_terreno"]), ("SIN_LEVANTAR", ""))
        self.assertEqual((n["fichas_sin_levantar"], n["fichas_area_vacia"], n["fichas_parciales"]), (1, 1, 0))

    def test_without_the_urbanizacion_column_an_empty_ficha_is_still_sin_levantar(self):
        header = PREDIO_HEADER[:3]
        fichas, _ = convertir_fichas(self, [["S-0001", UNIDAD, None]], predio_header=header)
        self.assertEqual((fichas[0]["estado_levantamiento"], fichas[0]["cuc"]), ("SIN_LEVANTAR", ""))

    def test_area_zero_with_pisos_is_parcial(self):
        f = self.ficha_de(area="0", urbanizacion=None, con_pisos={"S-0001"})
        self.assertEqual((f["estado_levantamiento"], f["area_terreno"]), ("PARCIAL", ""))

    def test_area_empty_with_titulares_or_urbanizacion_is_parcial(self):
        fichas, n = convertir_fichas(self, [predio(cod="S-0001", area=None, urbanizacion=None),
                                            predio(cod="S-0002", area="-3", urbanizacion="URB SINTETICA")],
                                     con_titulares={"S-0001"})
        self.assertEqual([(f["estado_levantamiento"], f["area_terreno"]) for f in fichas],
                         [("PARCIAL", ""), ("PARCIAL", "")])
        self.assertEqual((n["fichas_parciales"], n["fichas_area_vacia"]), (2, 2))

    def test_an_area_above_zero_is_completo_even_on_a_bare_lot(self):
        f = self.ficha_de(area="150.50", urbanizacion=None)
        self.assertEqual((f["estado_levantamiento"], f["area_terreno"]), ("COMPLETO", "150.5"))

    def test_uso_and_id_aranc_are_present_and_empty(self):
        f = self.ficha_de()
        self.assertEqual((f["uso"], f["id_aranc"]), ("", ""))
        self.assertEqual(list(f), FICHAS_CSV)
        self.assertEqual(cv.FICHAS_CSV, FICHAS_CSV)

    def test_the_cuc_comes_from_its_column(self):
        self.assertEqual(self.ficha_de(cuc="12345678")["cuc"], "12345678")

    def test_a_repeated_codigo_keeps_the_first_ficha(self):
        fichas, n = convertir_fichas(self, [predio(cod="S-0001", area="100"), predio(cod="S-0001", area="200")])
        self.assertEqual([f["area_terreno"] for f in fichas], ["100"])
        self.assertEqual((n["fichas"], n["fichas_repetidas"]), (1, 1))

    def test_numeric_xlsx_codes_are_text(self):
        self.assertEqual(self.ficha_de(cod="1234.0")["cod_pre"], "1234")
        pisos, _ = convertir_pisos(self, [construccion(cod="1234.0", nivel="1.0", material="1.0")], codigos={"1234"})
        self.assertEqual([(p["cod_pre"], p["piso"], p["material"]) for p in pisos], [("1234", "1", "CONCRETO")])

    def test_every_count_is_reported_even_at_zero(self):
        _, n = convertir_fichas(self, [predio()])
        self.assertEqual(set(n), FICHAS_CONTEOS)
        _, n = convertir_pisos(self, [construccion()])
        self.assertEqual(set(n), PISOS_CONTEOS)


class PisosTests(unittest.TestCase):
    def test_a_piso_carries_the_model_columns(self):
        pisos, n = convertir_pisos(self, [construccion()])
        self.assertEqual(pisos, [{
            "cod_pre": "S-0001", "piso": "1", "seccion": 1, "area_construida": "80", "anio_construccion": "1998",
            "material": "LADRILLO", "estado_conservacion": "BUENO", **dict(zip(CATEGORIAS, "CCDCCDC")),
        }])
        self.assertEqual(list(pisos[0]), cv.PISOS_CSV)
        self.assertEqual(n["pisos"], 1)

    def test_pisos_of_predios_without_ficha_are_dropped(self):
        pisos, n = convertir_pisos(self, [construccion(cod="S-0001"), construccion(cod="S-0009")])
        self.assertEqual([p["cod_pre"] for p in pisos], ["S-0001"])
        self.assertEqual(n["pisos_de_predios_sin_ficha"], 1)

    def test_niveles_71_and_81_and_niveles_without_number_are_dropped(self):
        pisos, n = convertir_pisos(self, [construccion(nivel="NIVEL 71"), construccion(nivel="NIVEL 81"),
                                          construccion(nivel="SOTANO"), construccion(nivel=None),
                                          construccion(nivel="NIVEL 02")])
        self.assertEqual([p["piso"] for p in pisos], ["2"])
        self.assertEqual((n["pisos_nivel_71_81"], n["niveles_sin_numero"], n["pisos"]), (2, 2, 1))

    def test_a_repeated_nivel_becomes_secciones_in_sheet_order(self):
        pisos, n = convertir_pisos(self, [construccion(nivel="NIVEL 01", area="40"),
                                          construccion(nivel="NIVEL 01", area="60"),
                                          construccion(nivel="NIVEL 02", area="50")])
        self.assertEqual([(p["piso"], p["seccion"]) for p in pisos], [("1", 1), ("1", 2), ("2", 1)])
        self.assertEqual([p["area_construida"] for p in pisos], ["40", "60", "50"])
        self.assertEqual(n["pisos_en_seccion_2_o_mas"], 1)

    def test_years_outside_1900_2026_area_zero_and_letters_outside_a_j_go_empty(self):
        pisos, n = convertir_pisos(self, [
            construccion(nivel="NIVEL 01", anio="1899", area="0", letras="KCDCCDc"),
            construccion(nivel="NIVEL 02", anio="2027", area="abc", letras="CCDCCD9"),
            construccion(nivel="NIVEL 03", anio="1900", area="12.5", letras="CCDCCDC"),
            construccion(nivel="NIVEL 04", anio="2026", area=None, letras=[None] * 7),
            construccion(nivel="NIVEL 05", anio="viejo", area="10", letras="CCDCCDC"),
        ])
        self.assertEqual([p["anio_construccion"] for p in pisos], ["", "", "1900", "2026", ""])
        self.assertEqual([p["area_construida"] for p in pisos], ["", "", "12.5", "", "10"])
        self.assertEqual([p[c] for c in CATEGORIAS for p in pisos[:1]], ["", "C", "D", "C", "C", "D", "C"])
        self.assertEqual(pisos[1]["instalaciones"], "")
        self.assertEqual([p["muros_columnas"] for p in pisos[3:4]], [""])
        self.assertEqual((n["anios_vaciados"], n["areas_construidas_vaciadas"], n["letras_vaciadas"]), (3, 2, 2))

    def test_the_last_year_kept_can_be_moved(self):
        pisos, n = convertir_pisos(self, [construccion(anio="2027")], anio_maximo=2027)
        self.assertEqual((pisos[0]["anio_construccion"], n["anios_vaciados"]), ("2027", 0))

    def test_material_and_estado_codes_become_the_model_options(self):
        pisos, n = convertir_pisos(self, [
            construccion(nivel="NIVEL 01", material="1", estado="4"),
            construccion(nivel="NIVEL 02", material="3", estado="1"),
            construccion(nivel="NIVEL 03", material="quincha", estado="muy_bueno"),
            construccion(nivel="NIVEL 04", material="X", estado="9"),
            construccion(nivel="NIVEL 05", material=None, estado=None),
        ])
        self.assertEqual([(p["material"], p["estado_conservacion"]) for p in pisos], [
            ("CONCRETO", "MALO"), ("ADOBE", "MUY BUENO"), ("QUINCHA", "MUY BUENO"), ("", ""), ("", "")])
        self.assertEqual((n["materiales_vaciados"], n["estados_vaciados"]), (1, 1))

    def test_a_shared_construccion_goes_to_each_predio(self):
        pisos, n = convertir_pisos(self, [construccion(cod="S-0001", nivel="NIVEL 01"),
                                          construccion(cod="S-0002", nivel="NIVEL 01")],
                                   codigos={"S-0001", "S-0002"})
        self.assertEqual([(p["cod_pre"], p["piso"], p["seccion"]) for p in pisos],
                         [("S-0001", "1", 1), ("S-0002", "1", 1)])
        self.assertEqual(n["pisos_en_seccion_2_o_mas"], 0)



class TitularesTests(unittest.TestCase):
    def titulares_de(self, filas, codigos=("S-0001",)):
        path = escribir_libro(self, [predio()], titulares=filas)
        return cv.titulares_de(read_table(path, "titulares_catastro"), set(codigos),
                               parse_map([], cv.TITULAR_COLUMNS))

    def test_titulares_pass_as_they_come(self):
        titulares, n = self.titulares_de([titular(numero="000123", porcentaje="50"),
                                          titular(numero="000000000", nombre="  LUIS   SINTETICO ", porcentaje="50.0"),
                                          titular(cod="S-0009")])
        self.assertEqual(titulares, [
            {"cod_pre": "S-0001", "tipo_documento": "DNI", "numero_documento": "000123", "nombre": NOMBRE,
             "porcentaje": "50", "condicion": "PROPIETARIO"},
            {"cod_pre": "S-0001", "tipo_documento": "DNI", "numero_documento": "000000000", "nombre": "LUIS SINTETICO",
             "porcentaje": "50.0", "condicion": "PROPIETARIO"},
        ])
        self.assertEqual(list(titulares[0]), TITULARES_CSV)
        self.assertEqual(cv.TITULARES_CSV, TITULARES_CSV)
        self.assertEqual((n["titulares"], n["titulares_de_predios_sin_ficha"]), (2, 1))

    def test_empty_cells_go_empty_and_xlsx_numbers_are_text(self):
        titulares, _ = self.titulares_de([titular(cod="1234.0", tipo=None, numero="412345.0", nombre=None,
                                                  porcentaje=None, condicion=None)], codigos={"1234"})
        self.assertEqual(titulares, [{"cod_pre": "1234", "tipo_documento": "", "numero_documento": "412345",
                                      "nombre": "", "porcentaje": "", "condicion": ""}])


class VinculosTests(unittest.TestCase):
    OPCIONES = ENUMS["vinculo_metodo"]

    def vinculos_de(self, texto, alias=None):
        return cv.vinculos_de(read_table(write_csv(self, texto)), parse_map([], cv.VINCULO_COLUMNS), alias or {},
                              self.OPCIONES)

    def test_the_method_matches_the_enum_in_any_case_or_through_an_alias(self):
        vinculos, problems = self.vinculos_de(
            "cod_predio_rentas,vinculo_metodo,fid\nS-0001,codigo_rentas,1\nS-0002,Llave hu mz lote,2\n"
            "S-0003,lote  vecino,3\nS-0004,,4\n,GEOMETRICO,5\n", alias={"LOTE VECINO": "GEOMETRICO"})
        self.assertEqual(problems, [])
        self.assertEqual(vinculos, {"S-0001": "CODIGO_RENTAS", "S-0002": "LLAVE_HU_MZ_LOTE", "S-0003": "GEOMETRICO",
                                    "S-0004": ""})

    def test_an_unknown_method_is_a_problem_named_once(self):
        _, problems = self.vinculos_de("cod_predio_rentas,vinculo_metodo\nS-0001,OTRO\nS-0002,otro\n")
        self.assertEqual(len(problems), 1)
        self.assertIn("'OTRO'", problems[0])


class CliTests(unittest.TestCase):
    """The command: the libro (and the vínculos csv) in, fichas.csv, pisos.csv and titulares.csv out, counts only."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.salida = os.path.join(tmp.name, "salida")
        self.libro = escribir_libro(
            self, [predio(cod="S-0001"), predio(cod="S-0002"), predio(cod="S-0003", area="0", urbanizacion=None)],
            [construccion(cod="S-0001"), construccion(cod="S-0002", nivel="NIVEL 02")],
            [titular(cod="S-0001"), titular(cod="S-0002", numero="000000000", nombre="LUIS SINTETICO")])

    def convertir(self, *extra, libro=None):
        return run(cv.main, ["--libro", libro or self.libro, "--salida", self.salida, *extra])

    def leer(self, nombre):
        with open(os.path.join(self.salida, nombre), encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def vinculos(self, texto="cod_predio_rentas,vinculo_metodo\nS-0001,CODIGO_RENTAS\nS-0003,geometrico\n"):
        return write_csv(self, texto)

    def test_the_vinculo_comes_from_the_csv_and_unlinked_fichas_are_dropped(self):
        code, out, err = self.convertir("--vinculos", self.vinculos())
        self.assertEqual(code, 0, err)
        self.assertEqual([(f["cod_pre"], f["vinculo_metodo"]) for f in self.leer("fichas.csv")],
                         [("S-0001", "CODIGO_RENTAS"), ("S-0003", "GEOMETRICO")])
        self.assertEqual([p["cod_pre"] for p in self.leer("pisos.csv")], ["S-0001"])
        self.assertEqual([t["cod_pre"] for t in self.leer("titulares.csv")], ["S-0001"])
        self.assertIn("predios_sin_vinculo: 1", out.splitlines())
        self.assertIn("vinculos: 2", out.splitlines())

    def test_with_vinculos_a_row_with_an_empty_method_still_writes_an_empty_value(self):
        vinculos = self.vinculos("cod_predio_rentas,vinculo_metodo\nS-0001,\nS-0003,geometrico\n")
        code, _, err = self.convertir("--vinculos", vinculos)
        self.assertEqual(code, 0, err)
        fichas = self.leer("fichas.csv")
        self.assertIn("vinculo_metodo", fichas[0])
        self.assertEqual([(f["cod_pre"], f["vinculo_metodo"]) for f in fichas],
                         [("S-0001", ""), ("S-0003", "GEOMETRICO")])

    def test_a_ficha_whose_only_construccion_row_is_dropped_is_sin_levantar_not_parcial(self):
        libro = escribir_libro(
            self, [predio(cod="S-0004", area="0", urbanizacion=None)],
            [construccion(cod="S-0004", nivel="NIVEL 71")])
        code, _, err = self.convertir(libro=libro)
        self.assertEqual(code, 0, err)
        fichas = self.leer("fichas.csv")
        self.assertEqual(fichas[0]["estado_levantamiento"], "SIN_LEVANTAR")

    def test_without_vinculos_every_ficha_is_loaded_and_vinculo_metodo_is_left_out(self):
        code, _, err = self.convertir()
        self.assertEqual(code, 0, err)
        fichas = self.leer("fichas.csv")
        self.assertEqual([f["cod_pre"] for f in fichas], ["S-0001", "S-0002", "S-0003"])
        self.assertEqual(list(fichas[0]), [c for c in FICHAS_CSV if c != "vinculo_metodo"])
        self.assertEqual(fichas[2]["estado_levantamiento"], "SIN_LEVANTAR")

    def test_a_method_alias_and_an_unknown_method(self):
        vinculos = self.vinculos("cod_predio_rentas,vinculo_metodo\nS-0001,LOTE VECINO\n")
        code, _, err = self.convertir("--vinculos", vinculos)
        self.assertEqual(code, 2)
        self.assertIn("'LOTE VECINO'", err)
        self.assertFalse(os.path.exists(self.salida))

        code, _, err = self.convertir("--vinculos", vinculos, "--metodo", "LOTE VECINO=GEOMETRICO")
        self.assertEqual(code, 0, err)
        self.assertEqual([f["vinculo_metodo"] for f in self.leer("fichas.csv")], ["GEOMETRICO"])

        code, _, err = self.convertir("--vinculos", self.vinculos("cod_predio_rentas,vinculo_metodo\nS-0001,OTRO\n"),
                                      "--metodo", "LOTE VECINO=GEOMETRICO")
        self.assertEqual(code, 2)
        self.assertIn("'OTRO'", err)

        for alias in ("LOTE VECINO=NADA", "=GEOMETRICO", "LOTE VECINO"):
            with self.subTest(alias=alias):
                code, _, err = self.convertir("--vinculos", vinculos, "--metodo", alias)
                self.assertEqual(code, 2)
                self.assertIn("--metodo", err)

    def test_titulares_pass_as_they_come(self):
        code, _, err = self.convertir()
        self.assertEqual(code, 0, err)
        titulares = self.leer("titulares.csv")
        self.assertEqual([(t["cod_pre"], t["numero_documento"], t["nombre"]) for t in titulares],
                         [("S-0001", DOCUMENTO, NOMBRE), ("S-0002", "000000000", "LUIS SINTETICO")])
        self.assertEqual(list(titulares[0]), TITULARES_CSV)

    def test_titulares_csv_is_written_with_mode_0600(self):
        code, _, err = self.convertir()
        self.assertEqual(code, 0, err)
        modo = os.stat(os.path.join(self.salida, "titulares.csv")).st_mode
        self.assertEqual(modo & 0o777, 0o600)

    def test_the_v3_titulares_sheet_loads_with_the_default_columns_and_an_empty_condicion(self):
        v3 = [titular(condicion="IGUAL"), titular(cod="S-0002", numero="000000000", nombre="LUIS SINTETICO",
                                                  condicion="DIFERENTE")]
        libro = escribir_libro(self, [predio(cod="S-0001"), predio(cod="S-0002")], [construccion()], v3,
                               titulares_header=TITULARES_HEADER_V3)
        code, out, err = self.convertir(libro=libro)
        self.assertEqual(code, 0, err)
        titulares = self.leer("titulares.csv")
        self.assertEqual([(t["cod_pre"], t["numero_documento"], t["porcentaje"], t["condicion"]) for t in titulares],
                         [("S-0001", DOCUMENTO, "100", ""), ("S-0002", "000000000", "100", "")])
        self.assertIn("titulares_sin_condicion: 2", out.splitlines())
        self.assertIn("condicion_catastro", err)
        self.assertIn("titulares_sin_condicion: 0", self.convertir()[1].splitlines())
        for secreto in ("ROSA", DOCUMENTO, "LUIS", "IGUAL", "DIFERENTE"):
            self.assertNotIn(secreto, out + err)

    def test_the_columns_can_be_mapped(self):
        libro = escribir_libro(self, [predio()], [construccion()], [titular()],
                               titulares_header=["COD_PREDIO", "TIPO_DOC", *TITULARES_HEADER[2:]])
        code, _, err = self.convertir("--map-titulares", "tipo_documento=tipo_doc", libro=libro)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.leer("titulares.csv")[0]["tipo_documento"], "DNI")
        vinculos = self.vinculos("codigo,metodo\nS-0001,MANUAL\n")
        code, _, err = self.convertir("--map-titulares", "tipo_documento=tipo_doc", "--vinculos", vinculos,
                                      "--map-vinculos", "codigo_municipal=codigo", "--map-vinculos", "metodo=metodo",
                                      libro=libro)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.leer("fichas.csv")[0]["vinculo_metodo"], "MANUAL")

    def test_the_last_year_kept_can_be_moved(self):
        libro = escribir_libro(self, [predio()], [construccion(anio="2027")])
        code, _, err = self.convertir("--anio-maximo", "2027", libro=libro)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.leer("pisos.csv")[0]["anio_construccion"], "2027")

    def test_without_the_cuc_column_fichas_csv_leaves_cuc_out(self):
        libro = escribir_libro(self, [predio()[:4]], predio_header=PREDIO_HEADER[:4])
        code, _, err = self.convertir(libro=libro)
        self.assertEqual(code, 0, err)
        self.assertEqual(list(self.leer("fichas.csv")[0]), [c for c in FICHAS_CSV if c not in ("cuc", "vinculo_metodo")])

    def test_it_prints_counts_only(self):
        code, out, err = self.convertir("--vinculos", self.vinculos())
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertTrue(all(re.fullmatch(r"[a-z0-9_]+: \d+", line) for line in out.splitlines()), out)
        for secreto in ("ROSA", DOCUMENTO, "LUIS"):
            self.assertNotIn(secreto, out)
        claves = [line.split(":")[0] for line in out.splitlines()]
        self.assertIn("titulares_sin_condicion", cv.CONTEOS_TITULARES)
        self.assertEqual(claves, ["vinculos", *cv.CONTEOS_FICHAS, *cv.CONTEOS_PISOS, *cv.CONTEOS_TITULARES])

    def test_a_missing_sheet_or_column_exits_2_naming_it(self):
        sin_hoja = escribir_libro(self, [predio()], sin=("titulares_catastro",))
        sin_nivel = escribir_libro(self, [predio()], [construccion()[:1] + construccion()[2:]],
                                   construccion_header=[c for c in CONSTRUCCION_HEADER if c != "nivel_catastro"])
        sin_nombre = escribir_libro(self, [predio()], titulares=[titular()[:3]], titulares_header=TITULARES_HEADER[:3])
        sin_unidad = escribir_libro(self, [predio()[:1]], predio_header=PREDIO_HEADER[:1])
        for libro, nombre, extra in (
                (sin_hoja, "titulares_catastro", ()), (sin_nivel, "nivel_catastro", ()),
                (sin_nombre, "nombre_catastro", ()), (sin_unidad, "codigo_unidad_catastro", ()),
                (self.libro, "vinculo_metodo", ("--vinculos", self.vinculos("cod_predio_rentas\nS-0001\n")))):
            with self.subTest(nombre=nombre):
                code, out, err = self.convertir(*extra, libro=libro)
                self.assertEqual(code, 2)
                self.assertIn(nombre, err)
                self.assertEqual(out, "")
                self.assertFalse(os.path.exists(self.salida))

    def test_an_output_inside_the_repository_exits_2(self):
        repositorio = os.path.dirname(HERE)
        dentro = os.path.join(HERE, "salida-de-prueba-no-debe-existir")
        code, _, err = run(cv.main, ["--libro", self.libro, "--salida", dentro])
        self.assertEqual(code, 2)
        self.assertIn("repositor", err)
        self.assertFalse(os.path.exists(dentro))

        # a link from outside into the repository is still inside
        enlace = os.path.join(os.path.dirname(self.salida), "enlace")
        os.symlink(repositorio, enlace)
        code, _, _ = run(cv.main, ["--libro", self.libro, "--salida", os.path.join(enlace, "x")])
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(os.path.join(repositorio, "x")))

    def test_an_output_that_cannot_be_written_exits_2(self):
        with open(self.salida, "w", encoding="utf-8") as f:
            f.write("un archivo, no un directorio")
        code, out, err = self.convertir()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("output:", err)

    def test_its_output_is_a_valid_entrega(self):
        code, _, err = self.convertir("--vinculos", self.vinculos())
        self.assertEqual(code, 0, err)
        core = FakeCore()
        self.addCleanup(core.stop)
        archivo = lambda nombre: os.path.join(self.salida, nombre)  # noqa: E731
        code, out, err = run(imf.main, [
            "--entrega", "ICA-T", "--fecha-corte", "2026-10-24", "--fuente", "BARRIDO",
            "--fichas", archivo("fichas.csv"), "--pisos", archivo("pisos.csv"), "--titulares", archivo("titulares.csv"),
            "--core", core.base_url, "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("alta S-0001", out)
        self.assertIn("alta S-0003", out)
        for secreto in ("ROSA", DOCUMENTO):
            self.assertNotIn(secreto, out + err)


if __name__ == "__main__":
    unittest.main()
