"""Pruebas de configurar_region.py contra un FakeCore.

Correr: cd model && python3 -m unittest -v
"""
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

import configurar_region
from fake_core import FakeCore

OBJETO = "configuracion_catastro"


class ConfigurarRegionTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.stop)

    def run_cli(self, extra=()):
        args = ["--core", self.core.base_url, "--email", "admin@wasichai.local", "--password", "admin", *extra]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = configurar_region.main(args)
        return code, out.getvalue(), err.getvalue()

    def writes(self):
        return [(m, p.split("?")[0], b) for m, p, _, b in self.core.requests if m in ("POST", "PUT") and p != "/api/auth/login"]

    def test_crea_la_configuracion_con_la_region(self):
        code, out, err = self.run_cli(["--region", "SELVA"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.writes(), [("POST", f"/api/objects/{OBJETO}/records", {"attributes": {"region": "SELVA"}})])
        self.assertIn("create configuracion_catastro region=SELVA", out)

    def test_la_segunda_corrida_no_escribe(self):
        self.run_cli(["--region", "COSTA"])
        self.core.requests.clear()
        code, out, err = self.run_cli(["--region", "COSTA"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.writes(), [])
        self.assertIn("skip", out)

    def test_cambia_la_region_si_es_otra(self):
        registro = self.core.add_record(OBJETO, {"region": "SELVA"})
        code, out, err = self.run_cli(["--region", "COSTA"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.writes(), [("PUT", f"/api/objects/{OBJETO}/records/{registro['id']}", {"attributes": {"region": "COSTA"}})])
        self.assertIn("update configuracion_catastro region SELVA -> COSTA", out)

    def test_dos_configuraciones_salen_con_2_sin_escribir(self):
        self.core.add_record(OBJETO, {"region": "SELVA"})
        self.core.add_record(OBJETO, {"region": "COSTA"})
        code, out, err = self.run_cli(["--region", "COSTA"])
        self.assertEqual(code, 2)
        self.assertIn("2 registros", err)
        self.assertEqual(self.writes(), [])

    def test_una_region_que_el_modelo_no_tiene_sale_con_2_sin_llamar_a_core(self):
        code, out, err = self.run_cli(["--region", "SIERRA"])
        self.assertEqual(code, 2)
        self.assertEqual(self.core.requests, [])

    def test_la_region_es_obligatoria(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            configurar_region.main(["--core", self.core.base_url])

    def test_dry_run_no_llama_a_core(self):
        code, out, err = self.run_cli(["--region", "selva", "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.core.requests, [])
        self.assertIn('"SELVA"', out)

    def test_un_rechazo_de_core_sale_con_1(self):
        self.core.fail_on_record = OBJETO
        code, out, err = self.run_cli(["--region", "SELVA"])
        self.assertEqual(code, 1)
        self.assertIn(f"error POST /api/objects/{OBJETO}/records", err)


if __name__ == "__main__":
    unittest.main()
