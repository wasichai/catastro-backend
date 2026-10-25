"""Tests for import_lotes.py: polygons, matching by code, problems, and an idempotent update.

Run: cd model && python3 -m unittest -v
"""
import json
import unittest

import import_lotes as il
from fake_core import FakeCore
from helpers import run, write_csv

SQUARE = [[[-75.2250, -10.9480], [-75.2245, -10.9480], [-75.2245, -10.9475], [-75.2250, -10.9475], [-75.2250, -10.9480]]]


def feature(props, geometry=None):
    return {"type": "Feature", "properties": props, "geometry": geometry or {"type": "Polygon", "coordinates": SQUARE}}


class LotesFromTests(unittest.TestCase):
    def test_takes_a_one_part_multipolygon_and_either_code(self):
        collection = {"features": [
            feature({"codigo_municipal": "A"}),
            feature({"codigo_cpu": "CPU-B"}, {"type": "MultiPolygon", "coordinates": [SQUARE]}),
        ]}
        lotes, problems = il.lotes_from(collection, il.parse_map([], il.PROPERTIES))
        self.assertEqual(problems, [])
        self.assertEqual([(lote[1], lote[2]) for lote in lotes], [("A", None), (None, "CPU-B")])
        self.assertEqual(lotes[1][3], {"type": "Polygon", "coordinates": SQUARE})

    def test_problems(self):
        collection = {"features": [
            feature({}),
            feature({"codigo_municipal": "A"}),
            feature({"codigo_municipal": "A"}),
            feature({"codigo_municipal": "C"}, {"type": "Point", "coordinates": [-75.2, -10.9]}),
            feature({"codigo_municipal": "D"}, {"type": "MultiPolygon", "coordinates": [SQUARE, SQUARE]}),
        ]}
        _, problems = il.lotes_from(collection, il.parse_map([], il.PROPERTIES))
        self.assertEqual(len(problems), 4, problems)

    def test_map_override(self):
        lotes, problems = il.lotes_from({"features": [feature({"COD_PRE": "A"})]}, il.parse_map(["codigo_municipal=COD_PRE"], il.PROPERTIES))
        self.assertEqual((problems, lotes[0][1]), ([], "A"))
        with self.assertRaises(ValueError):
            il.parse_map(["color=X"], il.PROPERTIES)


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.stop)
        self.core.add_record("predio_catastral", {"codigo_municipal": "A", "sector": "01"})
        self.core.add_record("predio_catastral", {"codigo_municipal": "B", "codigo_cpu": "CPU-B"})

    def cli(self, collection, *extra):
        path = write_csv(self, json.dumps(collection), ".geojson")
        return run(il.main, ["--geojson", path, "--core", self.core.base_url, *extra])

    def puts(self):
        return [r for r in self.core.requests if r[0] == "PUT"]

    def test_sets_polygons_on_existing_predios_only(self):
        collection = {"features": [feature({"codigo_municipal": "A"}), feature({"codigo_cpu": "CPU-B"}),
                                   feature({"codigo_municipal": "ZZ"})]}
        code, out, err = self.cli(collection)
        self.assertEqual(code, 0, err)
        self.assertIn("done: 2 updated, 0 skipped, 1 without predio", out)
        self.assertEqual(len(self.core.records["predio_catastral"]), 2)  # none created
        a = self.core.records["predio_catastral"][0]
        self.assertEqual(a["attributes"], {"codigo_municipal": "A", "sector": "01"})  # the PUT sent them back
        self.assertEqual(a["geometries"]["lote_geom"]["type"], "Polygon")

    def test_second_run_updates_nothing(self):
        collection = {"features": [feature({"codigo_municipal": "A"})]}
        self.cli(collection)
        sent = len(self.puts())
        code, out, _ = self.cli(collection)
        self.assertIn("done: 0 updated, 1 skipped, 0 without predio", out)
        self.assertEqual(len(self.puts()), sent)

    def test_dry_run_and_problems_send_nothing(self):
        code, _, _ = self.cli({"features": [feature({"codigo_municipal": "A"})]}, "--dry-run")
        self.assertEqual((code, self.core.requests), (0, []))
        code, _, err = self.cli({"features": [feature({})]})
        self.assertEqual(code, 2)
        self.assertIn("nothing was sent", err)
        self.assertEqual(self.core.requests, [])

    def test_invalid_json_and_missing_file_exit_2(self):
        path = write_csv(self, "{not json", ".geojson")
        for geojson in (path, "/nonexistent/lotes.geojson"):
            code, _, err = run(il.main, ["--geojson", geojson, "--core", self.core.base_url])
            self.assertEqual(code, 2)
            self.assertIn("input:", err)
        self.assertEqual(self.core.requests, [])

    def test_core_refusal_exits_1(self):
        self.core.fail_on_update = "predio_catastral"
        code, _, err = self.cli({"features": [feature({"codigo_municipal": "A"})]})
        self.assertEqual(code, 1)
        self.assertIn("-> 400", err)


def shifted(coords, amount):
    return [[[x + amount, y + amount] for x, y in ring] for ring in coords]


class SamePolygonTests(unittest.TestCase):
    def test_same_polygon_compares_rings_and_vertices(self):
        a = {"type": "Polygon", "coordinates": SQUARE}
        self.assertTrue(il.same_polygon(a, a))
        more_rings = {"type": "Polygon", "coordinates": SQUARE + SQUARE}
        self.assertFalse(il.same_polygon(a, more_rings))
        fewer_vertices = {"type": "Polygon", "coordinates": [SQUARE[0][:-1]]}
        self.assertFalse(il.same_polygon(a, fewer_vertices))
        moved = {"type": "Polygon", "coordinates": shifted(SQUARE, 1e-4)}
        self.assertFalse(il.same_polygon(a, moved))
        barely_moved = {"type": "Polygon", "coordinates": shifted(SQUARE, 1e-7)}
        self.assertTrue(il.same_polygon(a, barely_moved))


class ActualizarGeometriaTests(unittest.TestCase):
    """--actualizar-geometria replaces a polygon that changed beyond tolerance; --entrega makes the write a PATCH
    with the entrega's code as X-Change-Reason (contexto-comun.md, R1/R2)."""

    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.stop)

    def cli(self, collection, *extra):
        path = write_csv(self, json.dumps(collection), ".geojson")
        return run(il.main, ["--geojson", path, "--core", self.core.base_url, *extra])

    def patches(self):
        return [r for r in self.core.requests if r[0] == "PATCH"]

    def test_a_moved_polygon_is_replaced_only_with_the_flag(self):
        self.core.add_record("predio_catastral", {"codigo_municipal": "A"},
                             geometries={"lote_geom": {"type": "Polygon", "coordinates": SQUARE}})
        moved = shifted(SQUARE, 1e-4)
        collection = {"features": [feature({"codigo_municipal": "A"}, {"type": "Polygon", "coordinates": moved})]}
        code, out, err = self.cli(collection)
        self.assertEqual(code, 0, err)
        self.assertIn("done: 0 updated, 1 skipped, 0 without predio", out)
        self.assertEqual(self.patches(), [])
        code, out, err = self.cli(collection, "--actualizar-geometria", "--entrega", "E-1",
                                  "--fecha-corte", "2026-10-01", "--fuente", "BARRIDO")
        self.assertEqual(code, 0, err)
        self.assertIn("done: 1 updated, 0 skipped, 0 without predio", out)
        patches = self.patches()
        self.assertEqual(len(patches), 1)
        entrega_id = self.core.records["entrega_catastral"][0]["id"]
        self.assertEqual(patches[0][3], {"attributes": {"entrega": entrega_id},
                                         "geometries": {"lote_geom": {"type": "Polygon", "coordinates": moved}}})

    def test_a_polygon_within_tolerance_is_the_same(self):
        self.core.add_record("predio_catastral", {"codigo_municipal": "A"},
                             geometries={"lote_geom": {"type": "Polygon", "coordinates": SQUARE}})
        barely = shifted(SQUARE, 1e-7)
        collection = {"features": [feature({"codigo_municipal": "A"}, {"type": "Polygon", "coordinates": barely})]}
        code, out, err = self.cli(collection, "--actualizar-geometria")
        self.assertEqual(code, 0, err)
        self.assertIn("done: 0 updated, 1 skipped, 0 without predio", out)
        self.assertEqual(self.patches(), [])

    def test_the_entrega_is_the_reason_and_the_predio_points_to_it(self):
        self.core.add_record("predio_catastral", {"codigo_municipal": "A"})
        collection = {"features": [feature({"codigo_municipal": "A"})]}
        code, out, err = self.cli(collection, "--entrega", "E-1", "--fecha-corte", "2026-10-01", "--fuente", "BARRIDO")
        self.assertEqual(code, 0, err)
        entrega = self.core.records["entrega_catastral"][0]
        a = entrega["attributes"]
        self.assertEqual((a["altas"], a["cambios"], a["sin_cambio"]), (0, 1, 0))
        self.assertNotIn("ausentes", a)
        predio = self.core.records["predio_catastral"][0]
        self.assertEqual(predio["attributes"]["entrega"], entrega["id"])
        reasons = [r[2] for r in self.core.reasons if r[0] == "PATCH"]
        self.assertEqual(reasons, ["E-1"])

    def test_a_run_with_nothing_to_write_creates_no_entrega(self):
        self.core.add_record("predio_catastral", {"codigo_municipal": "A"},
                             geometries={"lote_geom": {"type": "Polygon", "coordinates": SQUARE}})
        collection = {"features": [feature({"codigo_municipal": "A"})]}
        code, out, err = self.cli(collection, "--entrega", "E-1", "--fecha-corte", "2026-10-01", "--fuente", "BARRIDO")
        self.assertEqual(code, 0, err)
        self.assertIn("done: 0 updated, 1 skipped, 0 without predio", out)
        self.assertEqual(self.core.records.get("entrega_catastral", []), [])

    def test_entrega_flags_are_validated_like_import_fichas(self):
        bad = [
            ["--entrega", "E 1", "--fecha-corte", "2026-10-01", "--fuente", "BARRIDO"],
            ["--entrega", "E-1", "--fecha-corte", "2026-10-01", "--fuente", "CENSO"],
            ["--entrega", "E-1", "--fuente", "BARRIDO"],
            ["--entrega", "E-1", "--fecha-corte", "2026-10-01"],
            ["--fecha-corte", "2026-10-01"],
        ]
        for extra in bad:
            code, _, err = self.cli({"features": []}, *extra)
            self.assertEqual(code, 2, extra)
            self.assertTrue(err, extra)
        self.assertEqual(self.core.requests, [])


if __name__ == "__main__":
    unittest.main()
