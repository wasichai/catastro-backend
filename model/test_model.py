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

# object -> (its fields in order, the required ones, the unique ones)
OBJETOS = {
    "predio_catastral": (
        ["codigo_municipal", "codigo_cpu", "sector", "manzana", "lote", "id_aranc", "cod_via", "cuadra", "lado", "uso",
         "area_terreno", "longitud_frente", "anio_levantamiento", "es_edificio", "lote_geom"],
        {"codigo_municipal"}, {"codigo_municipal"}),
    "construccion": (["piso", "area_construida", "anio_construccion", "material", "estado_conservacion", *CATEGORIAS], set(), set()),
    "obra_complementaria": (["codigo_vu", "cantidad", "anio_construccion", "material", "estado_conservacion"], set(), set()),
    "arancel": (["clave", "id_aranc", "anio", "valor_m2", "cod_via", "cuadra", "lado"],
                {"clave", "id_aranc", "anio", "valor_m2"}, {"clave"}),
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

    def test_the_four_objects_and_their_fields(self):
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

    def test_children_hang_from_a_required_predio(self):
        relations = {r["name"]: r for r in self.model["relationships"]}
        self.assertEqual(set(relations), {"construccion_predio", "obra_complementaria_predio"})
        for relation in relations.values():
            self.assertEqual((relation["target"], relation["fieldName"], relation["required"]),
                             ("predio_catastral", "predio", True))

    def test_arancel_pair_is_indexed(self):
        self.assertEqual(self.objects["arancel"]["indexes"], [["id_aranc", "anio"]])


if __name__ == "__main__":
    unittest.main()
