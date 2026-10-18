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

    def test_core_refusal_exits_1(self):
        self.core.fail_on_update = "predio_catastral"
        code, _, err = self.cli({"features": [feature({"codigo_municipal": "A"})]})
        self.assertEqual(code, 1)
        self.assertIn("-> 400", err)


if __name__ == "__main__":
    unittest.main()
