"""Pruebas de crear_cuenta_srtm.py contra un FakeCore.

Correr: cd model && python3 -m unittest -v
"""
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

import crear_cuenta_srtm
from fake_core import FakeCore


class CrearCuentaSrtmTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.stop)
        self.core.roles["SRTM_LECTOR"] = {"name": "SRTM_LECTOR", "label": "Lector de srtm", "permissions": []}

    def run_cli(self, extra=()):
        args = ["--core", self.core.base_url, "--email", "admin@wasichai.local", "--password", "admin", *extra]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = crear_cuenta_srtm.main(args)
        return code, out.getvalue(), err.getvalue()

    def writes(self):
        return [(m, p, b) for m, p, _, b in self.core.requests if m in ("POST", "PUT") and p != "/api/auth/login"]

    def test_crea_la_cuenta_con_el_rol_e_imprime_el_secreto_una_vez(self):
        code, out, err = self.run_cli()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.writes(), [("POST", "/api/service-accounts", {"name": "srtm", "roles": ["SRTM_LECTOR"]})])
        cuenta = next(iter(self.core.service_accounts.values()))
        self.assertIn(f"clientId:     {cuenta['clientId']}", out)
        self.assertEqual(out.count("secreto-srtm"), 1)
        self.assertIn("SRTM_CATASTRO_CLIENT_ID", out)
        self.assertIn("SRTM_CATASTRO_CLIENT_SECRET", out)
        for method, path, auth, body in self.core.requests:
            self.assertEqual(auth, None if path == "/api/auth/login" else "Bearer t")

    def test_la_segunda_corrida_no_escribe_ni_muestra_secreto(self):
        self.run_cli()
        self.core.requests.clear()
        code, out, err = self.run_cli()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.writes(), [])
        self.assertNotIn("secreto-srtm", out)
        cuenta = next(iter(self.core.service_accounts.values()))
        self.assertIn(cuenta["clientId"], out)
        self.assertIn(f"/api/service-accounts/{cuenta['id']}/secret", out)
        self.assertEqual(len(self.core.service_accounts), 1)

    def test_a_una_cuenta_que_existe_sin_el_rol_se_le_agrega(self):
        cuenta = self.core.add_service_account("srtm", ["OTRO"])
        code, out, err = self.run_cli()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.writes(), [("PUT", f"/api/service-accounts/{cuenta['id']}", {"roles": ["OTRO", "SRTM_LECTOR"]})])
        self.assertIn("update service account srtm", out)

    def test_otro_nombre(self):
        code, out, err = self.run_cli(["--nombre", "Srtm-Dev"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.writes()[0][2]["name"], "srtm-dev")

    def test_sin_el_rol_no_crea_nada_y_sale_con_2(self):
        del self.core.roles["SRTM_LECTOR"]
        code, out, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("apply_roles.py", err)
        self.assertEqual(self.writes(), [])

    def test_un_nombre_invalido_sale_con_2_sin_llamar_a_core(self):
        code, out, err = self.run_cli(["--nombre", "1srtm"])
        self.assertEqual(code, 2)
        self.assertEqual(self.core.requests, [])

    def test_un_rechazo_de_core_sale_con_1(self):
        self.core.fail_on_service_account = 500
        code, out, err = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("error POST /api/service-accounts", err)

    def test_dry_run_no_llama_a_core(self):
        code, out, err = self.run_cli(["--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.core.requests, [])
        self.assertIn('"SRTM_LECTOR"', out)


if __name__ == "__main__":
    unittest.main()
