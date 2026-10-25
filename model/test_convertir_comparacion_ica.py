"""Tests for convertir_comparacion_ica.py: the fichas and pisos it turns Ica's comparison workbook into.

Synthetic workbook only (codes like S-0001, no names). Run: cd model && python3 -m unittest -v test_convertir_comparacion_ica
"""
import os
import unittest

import convertir_comparacion_ica as cv
from helpers import write_xlsx_sheets
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


def predio(cod="S-0001", unidad=UNIDAD, area="150.50", urbanizacion="URB SINTETICA", cuc=None):
    return [cod, unidad, area, urbanizacion, cuc]


def construccion(cod="S-0001", nivel="NIVEL 01", anio="1998", area="80", material="2", estado="2", letras="CCDCCDC"):
    return [cod, nivel, anio, area, material, estado, *letras]


def libro(testcase, predios, construcciones=(), predio_header=PREDIO_HEADER):
    """The workbook's catastro sheets as read_table reads them; a rentas sheet comes first, as in the real one."""
    path = write_xlsx_sheets(testcase, {
        "predio_rentas": (["cod_predio", "area_terreno"], [["S-0001", "999"]]),
        "predio_catastro": (predio_header, predios),
        "construccion_catastro": (CONSTRUCCION_HEADER, list(construcciones)),
    })
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


if __name__ == "__main__":
    unittest.main()
