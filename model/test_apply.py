"""End-to-end tests for apply.py's CLI against a fake Core.

Run: cd model && python3 -m unittest -v
"""
import io
import json
import os
import socket
import unittest
from contextlib import redirect_stderr, redirect_stdout

import apply
from fake_core import FakeCore

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.json")
OBJECT_ORDER = ["predio_catastral", "construccion", "obra_complementaria", "arancel", "configuracion_catastro",
                "entrega_catastral", "titular_catastral", "tramo_via", "corte_brecha", "brecha_ficha",
                "brecha_nivel_ficha", "decision_brecha"]
RELATIONSHIP_ORDER = ["construccion_predio", "obra_complementaria_predio", "predio_catastral_entrega",
                      "titular_catastral_predio", "brecha_ficha_corte", "brecha_nivel_ficha_ficha",
                      "brecha_nivel_ficha_corte"]


def load_model():
    with open(MODEL_PATH, encoding="utf-8") as f:
        return json.load(f)


def core_fields(model, obj_name):
    """What Core answers for an object that has model.json's fields."""
    obj = next(o for o in model["objects"] if o["name"] == obj_name)
    fields = []
    for f in obj["fields"]:
        field = {"name": f["name"], "label": f["label"], "type": f["type"]}
        if f["type"] == "ENUM":
            field["enumOptions"] = model["enums"][f["enum"]]
        fields.append(field)
    return fields


class ApplyCliTestCase(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.stop)

    def run_cli(self, extra_args):
        args = ["--model", MODEL_PATH, "--core", self.core.base_url, "--email", "admin@wasichai.local",
                "--password", "admin", *extra_args]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = apply.main(args)
        return code, out.getvalue(), err.getvalue()


class DryRunTests(ApplyCliTestCase):
    def test_dry_run_makes_no_requests(self):
        code, out, _ = self.run_cli(["--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(self.core.requests, [])
        self.assertEqual(out.count("# POST /api/objects"), len(OBJECT_ORDER))
        self.assertEqual(out.count("# POST /api/relationships"), len(RELATIONSHIP_ORDER))


class HappyPathTests(ApplyCliTestCase):
    def test_creates_everything_in_order(self):
        code, out, err = self.run_cli([])
        self.assertEqual(code, 0, msg=err)
        object_posts = [r[3]["name"] for r in self.core.requests if r[1] == "/api/objects" and r[0] == "POST"]
        self.assertEqual(object_posts, OBJECT_ORDER)
        rel_posts = [r[3]["name"] for r in self.core.requests if r[1] == "/api/relationships" and r[0] == "POST"]
        self.assertEqual(rel_posts, RELATIONSHIP_ORDER)
        puts = [(r[1], r[3]) for r in self.core.requests if r[0] == "PUT" and "/fields/" in r[1]]
        self.assertEqual(puts, [
            ("/api/metadata/objects/construccion/fields/predio", {"required": True}),
            ("/api/metadata/objects/obra_complementaria/fields/predio", {"required": True}),
            ("/api/metadata/objects/titular_catastral/fields/predio", {"required": True}),
            ("/api/metadata/objects/brecha_ficha/fields/corte", {"required": True}),
            ("/api/metadata/objects/brecha_nivel_ficha/fields/ficha", {"required": True}),
            ("/api/metadata/objects/brecha_nivel_ficha/fields/corte", {"required": True}),
        ])
        self.assertIn("done: 19 created, 8 updated, 0 skipped", out)

    def test_the_two_composite_indexes_are_declared(self):
        self.run_cli([])
        puts = {r[1]: r[3] for r in self.core.requests if r[0] == "PUT" and r[1].startswith("/api/objects/")}
        self.assertEqual(puts["/api/objects/arancel"]["indexes"], [["id_aranc", "anio"]])

    def test_decision_brecha_is_written_only_by_the_app(self):
        # apiOnly (ADR-040): the generic record api refuses it and wasichai-ui shows it read-only; it goes with the
        # indexes in the object's PUT, and only there
        self.run_cli([])
        puts = {r[1]: r[3] for r in self.core.requests if r[0] == "PUT" and r[1].startswith("/api/objects/")}
        self.assertIs(puts["/api/objects/decision_brecha"]["apiOnly"], True)
        self.assertTrue(all("apiOnly" not in b for p, b in puts.items() if p != "/api/objects/decision_brecha"))


class IdempotencyTests(ApplyCliTestCase):
    def test_everything_skips(self):
        model = load_model()
        self.core = FakeCore(
            existing_objects=OBJECT_ORDER, existing_relationships=RELATIONSHIP_ORDER,
            object_rules={o["name"]: {k: o[k] for k in ("indexes", "apiOnly") if k in o} for o in model["objects"]},
            existing_fields={n: core_fields(model, n) for n in OBJECT_ORDER},
        )
        self.addCleanup(self.core.stop)
        code, out, err = self.run_cli([])
        self.assertEqual(code, 0, msg=err)
        # each relationship is POSTed and answered 409; the two required ones have their field re-marked
        # required; no object or field is written
        posts = [r[1] for r in self.core.requests if r[0] == "POST" and "login" not in r[1]]
        self.assertEqual(posts, ["/api/relationships"] * len(RELATIONSHIP_ORDER))
        self.assertIn("done: 0 created, 0 updated, 19 skipped", out)


class FailureTests(ApplyCliTestCase):
    def test_500_on_second_object_aborts(self):
        self.core = FakeCore(fail_on_post_object="construccion")
        self.addCleanup(self.core.stop)
        code, _, err = self.run_cli([])
        self.assertEqual(code, 1)
        self.assertIn("/api/objects", err)

    def test_409_on_required_put_aborts(self):
        self.core = FakeCore(fail_put=True, fail_put_status=409)
        self.addCleanup(self.core.stop)
        code, _, err = self.run_cli([])
        self.assertEqual(code, 1)
        self.assertIn("/api/metadata/objects/construccion/fields/predio", err)

    def test_closed_port_is_fatal_with_no_traceback(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = apply.main(["--model", MODEL_PATH, "--core", f"http://127.0.0.1:{port}"])
        self.assertEqual(code, 1)
        self.assertIn("connection failed", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_login_without_token_is_fatal(self):
        self.core = FakeCore(login_response={})
        self.addCleanup(self.core.stop)
        code, _, err = self.run_cli([])
        self.assertEqual(code, 1)
        self.assertIn("no token in response", err)


class DropTests(ApplyCliTestCase):
    def test_drop_deletes_relationships_then_objects_in_reverse(self):
        code, out, err = self.run_cli(["--drop"])
        self.assertEqual(code, 0, msg=err)
        deletes = [r[1] for r in self.core.requests if r[0] == "DELETE"]
        self.assertEqual(deletes, [f"/api/relationships/{n}" for n in reversed(RELATIONSHIP_ORDER)]
                         + [f"/api/objects/{n}" for n in reversed(OBJECT_ORDER)])


class ValidateOnlyTests(ApplyCliTestCase):
    def test_validate_only_makes_no_requests(self):
        code, _, err = self.run_cli(["--validate-only"])
        self.assertEqual((code, self.core.requests), (0, []), msg=err)


if __name__ == "__main__":
    unittest.main()
