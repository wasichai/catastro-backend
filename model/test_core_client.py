"""Tests for core_client.py's writes (POST/PATCH/DELETE with X-Change-Reason) and tabular.write_all.

Run: cd model && python3 -m unittest -v test_core_client
"""
import unittest

from core_client import Client, CoreError
from fake_core import FakeCore
from tabular import LoadError, write_all


class ClientWriteTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.stop)
        self.client = Client(self.core.base_url)

    def test_patch_merges_and_null_clears(self):
        r = self.core.add_record("predio_catastral", {"codigo_municipal": "A", "uso": "010101", "lote": "1"})
        self.client.patch(f"/api/objects/predio_catastral/records/{r['id']}", {"attributes": {"uso": None, "lote": "2"}})
        self.assertEqual(r["attributes"], {"codigo_municipal": "A", "lote": "2"})

    def test_patch_merges_geometries(self):
        r = self.core.add_record("predio_catastral", {"codigo_municipal": "A"}, geometries={"predio_geom": {"type": "Point"}})
        polygon = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
        self.client.patch(f"/api/objects/predio_catastral/records/{r['id']}", {"geometries": {"lote_geom": polygon}})
        self.assertEqual(r["geometries"], {"predio_geom": {"type": "Point"}, "lote_geom": polygon})

    def test_patch_unknown_id_is_404(self):
        missing = "00000000-0000-0000-0000-000000000000"
        with self.assertRaises(CoreError) as ctx:
            self.client.patch(f"/api/objects/predio_catastral/records/{missing}", {"attributes": {"uso": "1"}})
        self.assertEqual(ctx.exception.status, 404)

    def test_patch_fail_on_update_is_400(self):
        r = self.core.add_record("predio_catastral", {"codigo_municipal": "A"})
        self.core.fail_on_update = "predio_catastral"
        with self.assertRaises(CoreError) as ctx:
            self.client.patch(f"/api/objects/predio_catastral/records/{r['id']}", {"attributes": {"uso": "1"}})
        self.assertEqual(ctx.exception.status, 400)

    def test_the_reason_travels_in_its_header(self):
        self.client.post("/api/objects/predio_catastral/records", {"attributes": {"codigo_municipal": "B"}}, reason="E-1")
        self.assertEqual(self.core.reasons[-1], ("POST", "/api/objects/predio_catastral/records", "E-1"))

    def test_no_reason_sends_no_header(self):
        self.client.post("/api/objects/predio_catastral/records", {"attributes": {"codigo_municipal": "C"}})
        self.assertIsNone(self.core.reasons[-1][2])

    def test_delete_sends_the_reason_too(self):
        r = self.core.add_record("predio_catastral", {"codigo_municipal": "D"})
        path = f"/api/objects/predio_catastral/records/{r['id']}"
        self.client.delete(path, reason="E-2")
        self.assertEqual(self.core.reasons[-1], ("DELETE", path, "E-2"))


class WriteAllTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.stop)
        self.client = Client(self.core.base_url)

    def test_write_all_posts_patches_and_deletes_with_the_reason(self):
        a = self.core.add_record("predio_catastral", {"codigo_municipal": "A", "uso": "010101"})
        b = self.core.add_record("predio_catastral", {"codigo_municipal": "B"})
        ops = [
            ("new", 1, "POST", "predio_catastral", None, {"codigo_municipal": "C"}),
            ("a", 2, "PATCH", "predio_catastral", a["id"], {"uso": None}),
            ("b", 3, "DELETE", "predio_catastral", b["id"], None),
        ]
        ids = write_all(self.client, ops, workers=2, reason="E-1")
        created = next(r for r in self.core.records["predio_catastral"] if r["attributes"].get("codigo_municipal") == "C")
        self.assertEqual(ids, {"new": created["id"]})
        self.assertEqual(a["attributes"], {"codigo_municipal": "A"})  # uso cleared by the PATCH
        self.assertEqual([r["id"] for r in self.core.records["predio_catastral"]], [a["id"], created["id"]])  # b deleted
        reasons = [r for r in self.core.reasons if r[2] == "E-1"]
        self.assertEqual(len(reasons), 3)
        self.assertEqual({r[0] for r in reasons}, {"POST", "PATCH", "DELETE"})

    def test_write_all_stops_at_the_first_refusal(self):
        self.core.fail_on_update = "predio_catastral"
        a = self.core.add_record("predio_catastral", {"codigo_municipal": "A"})
        ops = [("a", 7, "PATCH", "predio_catastral", a["id"], {"uso": "1"})]
        with self.assertRaises(LoadError) as ctx:
            write_all(self.client, ops, workers=1, reason="E-1")
        self.assertEqual((ctx.exception.object_name, ctx.exception.fila), ("predio_catastral", 7))


if __name__ == "__main__":
    unittest.main()
