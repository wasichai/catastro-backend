"""Tests for model.json: it validates, and it declares what the valuation engine reads.

Run: cd model && python3 -m unittest -v
"""
import copy
import json
import os
import unittest

from apply import validate

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.json")
CATEGORIAS = ["muros_columnas", "techos", "pisos", "puertas_ventanas", "revestimientos", "banos", "instalaciones"]
# srtm-backend's enum clasificacion, the same four strings, in the order of the RNT's tables 01 to 04
CLASIFICACION = ["CASA HABITACION Y DEPARTAMENTOS PARA VIVIENDA",
                 "TIENDAS DEPOSITOS CENTROS DE RECREACION CLUBES E INSTITUCIONES", "EDIFICIO-OFICINAS",
                 "CLINICAS HOSPITALES CINES INDUSTRIAS COLEGIOS TALLERES"]

# object -> (its fields in order, the required ones, the unique ones)
OBJETOS = {
    "predio_catastral": (
        ["codigo_municipal", "codigo_cpu", "sector", "manzana", "lote", "id_aranc", "cod_via", "cuadra", "lado", "uso",
         "area_terreno", "longitud_frente", "anio_levantamiento", "es_edificio", "lote_geom", "fecha_levantamiento",
         "estado_levantamiento", "vinculo_metodo", "vinculo_revisado", "cuc", "codigo_referencia_catastral",
         "tipo_predio"],
        {"codigo_municipal"}, {"codigo_municipal"}),
    "construccion": (["piso", "area_construida", "anio_construccion", "material", "estado_conservacion", *CATEGORIAS,
                      "techo_incluido", "clasificacion", "seccion"], set(), set()),
    "obra_complementaria": (["codigo_vu", "cantidad", "anio_construccion", "material", "estado_conservacion"], set(), set()),
    "arancel": (["clave", "id_aranc", "anio", "valor_m2", "cod_via", "cuadra", "lado"],
                {"clave", "id_aranc", "anio", "valor_m2"}, {"clave"}),
    "configuracion_catastro": (["region"], {"region"}, set()),
    "entrega_catastral": (
        ["codigo", "fecha_corte", "fuente", "archivo_sha256", "descripcion", "altas", "cambios", "sin_cambio",
         "ausentes"],
        {"codigo", "fecha_corte"}, {"codigo"}),
    "titular_catastral": (
        ["codigo_municipal", "tipo_documento", "numero_documento", "nombre", "porcentaje", "condicion"],
        {"codigo_municipal"}, set()),
    "tramo_via": (
        ["clave", "fid_eje", "cod_via_eje", "tip_via", "nom_via", "ubigeo", "fuente", "cuadra", "lado", "id_aranc",
         "asignacion", "geom"],
        {"clave", "fid_eje", "lado", "asignacion"}, {"clave"}),
    "corte_brecha": (
        ["clave", "org_slug", "fecha", "corrida", "anio", "manifiesto_sha256", "version_srtm", "version_catastro",
         "cargado_en", "total_fichas", "declarado", "catastro", "delta_impuesto", "delta_arbitrios",
         "delta_impuesto_confiable", "delta_impuesto_dudoso", "delta_impuesto_sin_levantar", "omisos_estimado"],
        {"clave", "org_slug", "fecha", "anio"}, {"clave"}),
    "brecha_ficha": (
        ["clave", "codigo_catastro", "codigo_municipal", "codigo_predio", "categoria", "confianza", "confianza_motivo",
         "sector", "manzana", "lote", "uso", "autoavaluo_declarado", "autoavaluo_catastro", "delta_autoavaluo",
         "impuesto_declarado", "impuesto_catastro", "delta_impuesto", "delta_arbitrios", "estimado", "motivo",
         "supera_5_uit"],
        {"clave", "categoria"}, {"clave"}),
    "decision_brecha": (
        ["clave", "codigo_municipal", "anio", "estado", "responsable", "nota", "motivo_descarte", "decidido_en",
         "corte_origen"],
        {"clave", "codigo_municipal", "anio", "estado"}, {"clave"}),
}


def load():
    with open(MODEL_PATH, encoding="utf-8") as f:
        return json.load(f)


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.model = load()
        self.objects = {o["name"]: o for o in self.model["objects"]}

    def test_it_validates(self):
        self.assertEqual(validate(self.model), [])

    def test_a_broken_copy_does_not(self):
        broken = copy.deepcopy(self.model)
        broken["objects"][0]["fields"][0]["type"] = "NUMBER"
        self.assertNotEqual(validate(broken), [])

    def test_the_objects_and_their_fields(self):
        self.assertEqual(list(self.objects), list(OBJETOS))
        for name, (fields, required, unique) in OBJETOS.items():
            declared = self.objects[name]["fields"]
            self.assertEqual([f["name"] for f in declared], fields, name)
            self.assertEqual({f["name"] for f in declared if f.get("required")}, required, name)
            self.assertEqual({f["name"] for f in declared if f.get("unique")}, unique, name)

    def test_types(self):
        types = {f["name"]: f["type"] for f in self.objects["predio_catastral"]["fields"]}
        self.assertEqual(types["area_terreno"], "DECIMAL")
        self.assertEqual(types["anio_levantamiento"], "INTEGER")
        self.assertEqual(types["es_edificio"], "BOOLEAN")
        self.assertEqual(next(f["type"] for f in self.objects["construccion"]["fields"] if f["name"] == "techo_incluido"),
                         "BOOLEAN")
        geom = next(f for f in self.objects["predio_catastral"]["fields"] if f["name"] == "lote_geom")
        self.assertEqual((geom["type"], geom["geometryType"], geom["srid"]), ("GEOMETRY", "POLYGON", 32718))

    def test_enums_are_srtms(self):
        enums = self.model["enums"]
        self.assertEqual(enums["material"], ["CONCRETO", "LADRILLO", "ADOBE", "MADERA", "QUINCHA", "DRYWALL", "ESTERA", "METAL", "OTROS"])
        self.assertEqual(enums["estado_conservacion"], ["MUY BUENO", "BUENO", "REGULAR", "MALO", "MUY MALO"])
        self.assertEqual(enums["letra_categoria"], list("ABCDEFGHIJ"))
        for field in self.objects["construccion"]["fields"]:
            if field["name"] in CATEGORIAS:
                self.assertEqual(field["enum"], "letra_categoria")

    def test_a_construccion_names_its_rnt_table_and_its_seccion(self):
        self.assertEqual(self.model["enums"]["clasificacion"], CLASIFICACION)
        fields = {f["name"]: f for f in self.objects["construccion"]["fields"]}
        self.assertEqual((fields["clasificacion"]["type"], fields["clasificacion"]["enum"]), ("ENUM", "clasificacion"))
        self.assertEqual(fields["seccion"]["type"], "INTEGER")
        # piso stays text, so a seccion is never written into it ("5-2")
        self.assertEqual(fields["piso"]["type"], "TEXT")

    def test_children_hang_from_a_required_predio(self):
        relations = {r["name"]: r for r in self.model["relationships"]}
        for name in ("construccion_predio", "obra_complementaria_predio", "titular_catastral_predio"):
            relation = relations[name]
            self.assertEqual((relation["target"], relation["fieldName"], relation["required"]),
                             ("predio_catastral", "predio", True))

    def test_the_levantamiento_state_has_no_default(self):
        f = {x["name"]: x for x in self.objects["predio_catastral"]["fields"]}
        self.assertEqual(self.model["enums"]["estado_levantamiento"], ["SIN_LEVANTAR", "PARCIAL", "COMPLETO"])
        self.assertEqual((f["estado_levantamiento"]["type"], f["fecha_levantamiento"]["type"]), ("ENUM", "DATE"))
        self.assertNotIn("default", f["estado_levantamiento"])

    def test_a_predio_points_to_its_entrega(self):
        r = {x["name"]: x for x in self.model["relationships"]}["predio_catastral_entrega"]
        self.assertEqual((r["source"], r["target"], r["fieldName"], r.get("required", False)),
                         ("predio_catastral", "entrega_catastral", "entrega", False))

    def test_the_entrega_names_its_source_and_declares_its_summary(self):
        enums = self.model["enums"]
        self.assertEqual(enums["fuente_entrega"], ["BARRIDO", "INSPECCION", "LICENCIA", "GIS", "OTRA"])
        f = {x["name"]: x for x in self.objects["entrega_catastral"]["fields"]}
        self.assertEqual((f["fuente"]["type"], f["fuente"]["enum"]), ("ENUM", "fuente_entrega"))
        for name in ("altas", "cambios", "sin_cambio", "ausentes"):
            self.assertEqual(f[name]["type"], "INTEGER", name)

    def test_region_is_an_enum_of_the_engine_regions(self):
        # catastro.tablas.Region: an option here without its tables there is a 409 for that organization
        self.assertEqual(self.model["enums"]["region_catastro"], ["COSTA", "SELVA"])
        region = self.objects["configuracion_catastro"]["fields"][0]
        self.assertEqual((region["type"], region["enum"]), ("ENUM", "region_catastro"))

    def test_srtm_reads_the_region(self):
        with open(os.path.join(os.path.dirname(__file__), "roles.json"), encoding="utf-8") as f:
            permisos = json.load(f)["roles"][0]["permisos"]
        self.assertEqual(permisos["configuracion_catastro"], ["READ"])

    def test_arancel_pair_is_indexed(self):
        self.assertEqual(self.objects["arancel"]["indexes"], [["id_aranc", "anio"]])

    def test_the_vinculo_and_its_codes(self):
        self.assertEqual(self.model["enums"]["vinculo_metodo"],
                         ["CODIGO_RENTAS", "LLAVE_HU_MZ_LOTE", "GEOMETRICO", "MANUAL"])
        self.assertEqual(self.objects["predio_catastral"]["indexes"],
                         [["sector", "manzana", "lote"], ["codigo_cpu"], ["cuc"], ["codigo_referencia_catastral"]])

    def test_titulares_page_by_codigo_municipal(self):
        # contract 2 pages /titulares by codigo_municipal then id: Core orders by one field of the object itself
        self.assertEqual(self.objects["titular_catastral"]["indexes"], [["codigo_municipal"]])

    def test_tipo_predio_is_urbano_or_rustico(self):
        # contract 4: tipo_predio ENUM URBANO|RUSTICO, optional (valuacion-v3, ADR-004/005)
        self.assertEqual(self.model["enums"]["tipo_predio"], ["URBANO", "RUSTICO"])
        f = {x["name"]: x for x in self.objects["predio_catastral"]["fields"]}
        self.assertEqual((f["tipo_predio"]["type"], f["tipo_predio"]["enum"]), ("ENUM", "tipo_predio"))
        self.assertNotIn("required", f["tipo_predio"])

    def test_a_tramo_de_via_is_a_line_in_utm_with_its_frente_and_its_arancel(self):
        # the plano predial values a vía by frente (cuadra and lado): one tramo_via per frente, keyed by the eje's fid
        # and its lado (clave = fid|lado, import_vias.py); id_aranc is the SAT code, its valor_m2 is read per year
        f = {x["name"]: x for x in self.objects["tramo_via"]["fields"]}
        self.assertEqual((f["geom"]["type"], f["geom"]["geometryType"], f["geom"]["srid"]),
                         ("GEOMETRY", "MULTILINESTRING", 32718))
        self.assertEqual(self.model["enums"]["lado_tramo"], ["AMBOS", "IZQUIERDO", "DERECHO"])
        self.assertEqual(self.model["enums"]["asignacion_tramo"], ["NOMBRE_UNICO", "CERCANIA", "LOTES", "SIN_ARANCEL"])
        self.assertEqual((f["lado"]["type"], f["lado"]["enum"]), ("ENUM", "lado_tramo"))
        self.assertEqual((f["asignacion"]["type"], f["asignacion"]["enum"]), ("ENUM", "asignacion_tramo"))
        self.assertEqual((f["fid_eje"]["type"], f["id_aranc"]["type"]), ("INTEGER", "TEXT"))
        self.assertEqual(self.objects["tramo_via"]["indexes"], [["id_aranc"], ["cod_via_eje"]])

    def test_la_brecha_de_un_corte_y_su_bandeja(self):
        # the contract of the brechas dashboard (catastro-ui): a corte per org and fecha, its fichas hanging from it,
        # and the decisions by codigo_municipal|anio, so they outlive the corte
        enums = self.model["enums"]
        self.assertEqual(enums["categoria_brecha"],
                         ["OMISO", "SIN_CATASTRO", "SIN_VALOR", "SUBVALUADO", "SOBREVALUADO", "COINCIDE", "SIN_LEVANTAR"])
        self.assertEqual(enums["confianza_brecha"], ["CONFIABLE", "DUDOSO", "SIN_LEVANTAR"])
        self.assertEqual(enums["estado_decision"],
                         ["PENDIENTE", "A_INSPECCIONAR", "INSPECCIONADO", "A_FISCALIZAR", "DESCARTADO"])
        ficha = {x["name"]: x for x in self.objects["brecha_ficha"]["fields"]}
        self.assertEqual((ficha["categoria"]["enum"], ficha["confianza"]["enum"]), ("categoria_brecha", "confianza_brecha"))
        for name in ("autoavaluo_declarado", "delta_autoavaluo", "delta_impuesto", "delta_arbitrios"):
            self.assertEqual(ficha[name]["type"], "DECIMAL", name)
        self.assertEqual((ficha["estimado"]["type"], ficha["supera_5_uit"]["type"]), ("BOOLEAN", "BOOLEAN"))
        self.assertEqual(self.objects["brecha_ficha"]["indexes"],
                         [["corte", "categoria"], ["corte", "confianza"], ["corte", "sector"], ["codigo_municipal"]])
        corte = {x["name"]: x for x in self.objects["corte_brecha"]["fields"]}
        self.assertEqual((corte["fecha"]["type"], corte["anio"]["type"], corte["cargado_en"]["type"]),
                         ("DATE", "INTEGER", "DATETIME"))
        decision = {x["name"]: x for x in self.objects["decision_brecha"]["fields"]}
        self.assertEqual((decision["estado"]["enum"], decision["responsable"]["type"], decision["decidido_en"]["type"]),
                         ("estado_decision", "EMAIL", "DATETIME"))
        # the decisions are written only by POST /api/catastro/brechas/decisiones (apiOnly, ADR-040)
        self.assertIs(self.objects["decision_brecha"].get("apiOnly"), True)
        self.assertTrue(all(not o.get("apiOnly") for o in self.model["objects"] if o["name"] != "decision_brecha"))
        r = {x["name"]: x for x in self.model["relationships"]}["brecha_ficha_corte"]
        self.assertEqual((r["source"], r["target"], r["fieldName"], r["required"]),
                         ("brecha_ficha", "corte_brecha", "corte", True))


if __name__ == "__main__":
    unittest.main()
