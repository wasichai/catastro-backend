"""Pruebas de vistas_de_mapa.py contra FakeCore: las vistas de mapa guardadas y la publicación de las capas con estilo.

Correr: cd model && python3 -m unittest -v
"""
import json
import os
import unittest

import vistas_de_mapa as vm
from fake_core import FakeCore
from helpers import run

with open(os.path.join(os.path.dirname(__file__), "model.json"), encoding="utf-8") as f:
    MODEL = json.load(f)
ENUMS = MODEL["enums"]
CAMPOS = {o["name"]: {c["name"]: c for c in o["fields"]} for o in MODEL["objects"]}


class VistasTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore(login_response={"token": "t", "user": {"organizationId": "org-ica"}})
        self.addCleanup(self.core.stop)
        # a feature type published from now on has every column of the model
        self.core.columns = {o: [c for c, f in campos.items() if f["type"] != "GEOMETRY"] for o, campos in CAMPOS.items()}

    def cli(self, *extra):
        return run(vm.main, ["--core", self.core.base_url, *extra])

    def escrituras(self):
        return [(m, p) for m, p, _, _ in self.core.requests if m in ("POST", "PUT", "DELETE") and p != "/api/auth/login"]

    def test_crea_las_cuatro_vistas_y_publica_las_dos_capas_con_su_estilo(self):
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        vistas = self.core.map_views
        self.assertEqual(set(vistas), {("tramo_via", "aranceles_valor"), ("tramo_via", "aranceles_asignacion"),
                                       ("brecha_ficha", "brechas_categoria"), ("brecha_ficha", "brechas_estado")})
        valor = vistas[("tramo_via", "aranceles_valor")]
        self.assertEqual((valor["geometryName"], valor["style"]["by"], valor["style"]["type"], valor["style"]["classes"]),
                         ("geom", "valor_m2", "quantiles", 5))
        self.assertEqual(valor["label"], "Aranceles: valor por m² del año")
        self.assertEqual(vistas[("tramo_via", "aranceles_asignacion")]["style"]["type"], "categories")
        categoria = vistas[("brecha_ficha", "brechas_categoria")]
        self.assertEqual((categoria["geometryName"], categoria["style"]["by"]), ("lote_geom", "categoria"))
        # catastro-ui's COLOR_CATEGORIA, in the order of the enum's options (how the server classes an ENUM)
        self.assertEqual(categoria["style"]["palette"],
                         ["#e15759", "#b07aa1", "#edc948", "#f28e2b", "#4e79a7", "#76b7b2", "#9ca3af"])
        self.assertEqual(ENUMS["categoria_brecha"],
                         ["OMISO", "SIN_CATASTRO", "SIN_VALOR", "SUBVALUADO", "SOBREVALUADO", "COINCIDE", "SIN_LEVANTAR"])
        self.assertEqual(vistas[("brecha_ficha", "brechas_estado")]["style"]["palette"],
                         ["#76b7b2", "#f28e2b", "#4e79a7", "#e15759", "#9ca3af"])
        self.assertEqual([(o, g, s["by"]) for o, g, s in self.core.layers],
                         [("tramo_via", "geom", "valor_m2"), ("brecha_ficha", "lote_geom", "categoria")])
        self.assertEqual(self.core.layers[1][2], categoria["style"])
        self.assertIn("vista brechas_categoria: create", out)
        self.assertIn("capa brecha_ficha.lote_geom: publish with the style of brechas_categoria", out)

    def test_cada_vista_colorea_por_un_campo_de_su_objeto_con_su_tipo(self):
        # what wasichai-gis's AttributeStyle.validate asks: quantiles of a number, categories of an enum
        for vista in vm.vistas(ENUMS):
            campos = CAMPOS[vista["object"]]
            self.assertEqual(campos[vista["geometryName"]]["type"], "GEOMETRY", vista["name"])
            campo = campos[vista["style"]["by"]]
            tipos = {"quantiles": ("INTEGER", "DECIMAL"), "categories": ("ENUM", "TEXT", "BOOLEAN")}
            self.assertIn(campo["type"], tipos[vista["style"]["type"]], vista["name"])
            for color in vista["style"].get("palette") or []:
                self.assertRegex(color, r"^#[0-9a-f]{6}$")

    def test_la_segunda_corrida_no_toca_las_vistas_pero_vuelve_a_publicar_las_capas(self):
        self.assertEqual(self.cli()[0], 0)
        self.core.requests.clear()
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        # the SLD is a snapshot of the classes: every run republishes, so a run after new data refreshes it
        self.assertEqual(self.escrituras(), [("POST", "/api/gis/layers/tramo_via/geom"),
                                             ("POST", "/api/gis/layers/brecha_ficha/lote_geom")])
        self.assertEqual(self.core.unpublished, [])
        self.assertIn("vista aranceles_valor: unchanged", out)
        self.assertEqual(len(self.core.layers), 4)

    def test_una_vista_cambiada_a_mano_vuelve_a_su_estilo(self):
        self.assertEqual(self.cli()[0], 0)
        vista = self.core.map_views[("brecha_ficha", "brechas_categoria")]
        vista["style"] = {"by": "confianza", "type": "categories", "classes": None, "palette": None}
        # an answer with null keys is the same style
        self.core.map_views[("tramo_via", "aranceles_valor")]["style"]["unknown"] = None
        self.core.requests.clear()
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        puts = [p for m, p in self.escrituras() if m == "PUT"]
        self.assertEqual(puts, ["/api/gis/objects/brecha_ficha/map-views/brechas_categoria"])
        self.assertEqual(self.core.map_views[("brecha_ficha", "brechas_categoria")]["style"]["by"], "categoria")
        self.assertIn("vista brechas_categoria: update", out)

    def test_dry_run_no_escribe(self):
        code, out, err = self.cli("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.escrituras(), [])
        self.assertIn("vista aranceles_valor: to create", out)
        self.assertIn("capa tramo_via.geom: to publish with the style of aranceles_valor", out)

    def test_sin_capas_no_publica(self):
        code, out, err = self.cli("--sin-capas")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.core.layers, [])
        self.assertEqual(len(self.core.map_views), 4)

    def test_otra_organizacion_no_escribe(self):
        code, _, err = self.cli("--org", "org-otra")
        self.assertEqual(code, 2)
        self.assertIn("is of the organization org-ica, not org-otra", err)
        self.assertEqual(self.escrituras(), [])
        self.assertEqual(self.cli("--org", "org-ica")[0], 0)

    def test_un_rechazo_de_core_sale_con_1(self):
        self.core.fail_on_layer = 502
        code, _, err = self.cli()
        self.assertEqual(code, 1)
        self.assertIn("error -> 502", err)

    def test_una_capa_publicada_sin_el_campo_del_estilo_se_despublica_y_se_vuelve_a_publicar(self):
        # tramo_via.geom published before valor_m2 existed: GeoServer's feature type lacks it, a republish keeps that
        self.core.layer_attributes[("tramo_via", "geom")] = ["clave", "id_aranc", "asignacion"]
        self.core.layer_attributes[("brecha_ficha", "lote_geom")] = ["clave", "categoria", "estado"]
        code, out, err = self.cli("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("capa tramo_via.geom: to unpublish, to rebuild its columns", out)
        self.assertEqual(self.escrituras(), [])
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.core.unpublished, [("tramo_via", "geom")])
        capas = [(m, p) for m, p in self.escrituras() if "/layers/" in p]
        self.assertEqual(capas, [("DELETE", "/api/gis/layers/tramo_via/geom"), ("POST", "/api/gis/layers/tramo_via/geom"),
                                 ("POST", "/api/gis/layers/brecha_ficha/lote_geom")])
        self.assertIn("valor_m2", self.core.layer_attributes[("tramo_via", "geom")])
        # rebuilt: the next run only republishes
        self.core.unpublished.clear()
        self.assertEqual(self.cli()[0], 0)
        self.assertEqual(self.core.unpublished, [])

    def test_recrear_capas_las_rehace_aunque_el_wfs_no_responda(self):
        self.core.layer_attributes[("tramo_via", "geom")] = ["clave"]
        self.core.layer_attributes[("brecha_ficha", "lote_geom")] = ["clave", "categoria"]
        self.core.wfs_reachable = False
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        # without the WFS nothing is unpublished, and the run says what to do
        self.assertEqual(self.core.unpublished, [])
        self.assertIn("capa tramo_via.geom: warning: its WFS could not be read; if it was published before valor_m2"
                      " existed, run again with --recrear-capas", out)
        code, out, err = self.cli("--recrear-capas")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.core.unpublished, [("tramo_via", "geom"), ("brecha_ficha", "lote_geom")])
        # a layer not published yet is only published
        self.core.unpublished.clear()
        self.core.layer_attributes.clear()
        self.assertEqual(self.cli("--recrear-capas")[0], 0)
        self.assertEqual(self.core.unpublished, [])

    def test_la_vista_del_delta_de_una_version_anterior_se_borra(self):
        self.core.map_views[("brecha_ficha", "brechas_delta")] = {"name": "brechas_delta", "label": "x",
                                                                  "objectName": "brecha_ficha",
                                                                  "geometryName": "lote_geom", "style": None}
        code, out, err = self.cli("--dry-run")
        self.assertIn("vista brechas_delta: to delete (retirada)", out)
        self.assertIn(("brecha_ficha", "brechas_delta"), self.core.map_views)
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        self.assertNotIn(("brecha_ficha", "brechas_delta"), self.core.map_views)
        self.assertIn("vista brechas_delta: delete (retirada)", out)

    def test_una_paleta_que_no_cubre_su_enum_es_un_error(self):
        with self.assertRaises(ValueError):
            vm.vistas({**ENUMS, "estado_decision": [*ENUMS["estado_decision"], "OTRO"]})


if __name__ == "__main__":
    unittest.main()
