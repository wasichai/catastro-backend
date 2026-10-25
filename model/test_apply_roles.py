"""Pruebas de roles.json y de apply_roles.py contra un FakeCore.

Correr: cd model && python3 -m unittest -v
"""
import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import apply_roles
from fake_core import FakeCore

HERE = os.path.dirname(os.path.abspath(__file__))
ROLES_PATH = os.path.join(HERE, "roles.json")
MODEL_PATH = os.path.join(HERE, "model.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def permisos(rol):
    """Los permisos de un rol de roles.json como pares (objeto, acción)."""
    return {(objeto, accion) for objeto, acciones in rol["permisos"].items() for accion in acciones}


class RolesJsonTests(unittest.TestCase):
    def setUp(self):
        self.roles = {r["name"]: r for r in load(ROLES_PATH)["roles"]}
        self.objetos = [o["name"] for o in load(MODEL_PATH)["objects"]]

    def test_declara_solo_el_lector_de_srtm(self):
        self.assertEqual(list(self.roles), ["SRTM_LECTOR"])

    def test_valida_contra_el_modelo(self):
        self.assertEqual(apply_roles.validate(load(ROLES_PATH), load(MODEL_PATH)), [])

    def test_el_lector_de_srtm_lee_cada_objeto_del_modelo_y_solo_escribe_los_aranceles(self):
        # lo que GET /api/catastro/valuaciones lee: un objeto nuevo en model.json sin su READ hace fallar esta prueba. los
        # aranceles los manda srtm (su normativa los verifica) y los copia aquí: CREATE, UPDATE y DELETE solo sobre arancel
        escribe = {("arancel", a) for a in ("CREATE", "UPDATE", "DELETE")}
        self.assertEqual(permisos(self.roles["SRTM_LECTOR"]), {(o, "READ") for o in self.objetos} | escribe)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.roles = load(ROLES_PATH)
        self.model = load(MODEL_PATH)

    def mutate(self, fn):
        roles = copy.deepcopy(self.roles)
        fn(roles)
        return apply_roles.validate(roles, self.model)

    def test_un_objeto_que_el_modelo_no_tiene_se_rechaza(self):
        errors = self.mutate(lambda r: r["roles"][0]["permisos"].update({"predio": ["READ"]}))
        self.assertTrue(any("'predio'" in e for e in errors), errors)

    def test_una_accion_que_core_no_conoce_se_rechaza(self):
        errors = self.mutate(lambda r: r["roles"][0]["permisos"].update({"arancel": ["MANAGE_METADATA"]}))
        self.assertTrue(any("MANAGE_METADATA" in e for e in errors), errors)

    def test_un_nombre_que_core_no_acepta_se_rechaza(self):
        errors = self.mutate(lambda r: r["roles"][0].update({"name": "srtm_lector"}))
        self.assertTrue(any("srtm_lector" in e for e in errors), errors)

    def test_un_rol_repetido_se_rechaza(self):
        errors = self.mutate(lambda r: r["roles"].append(copy.deepcopy(r["roles"][0])))
        self.assertTrue(any("duplicate" in e for e in errors), errors)


class ApplyRolesTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.stop)
        self.roles_json = {r["name"]: r for r in load(ROLES_PATH)["roles"]}

    def run_cli(self, extra=(), roles_path=ROLES_PATH):
        args = ["--roles", roles_path, "--core", self.core.base_url, "--email", "admin@wasichai.local",
                "--password", "admin", *extra]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = apply_roles.main(args)
        return code, out.getvalue(), err.getvalue()

    def writes(self):
        return [(m, p, b) for m, p, _, b in self.core.requests if m in ("POST", "PUT") and p != "/api/auth/login"]

    def test_dry_run_no_llama_a_core_e_imprime_lo_que_mandaria(self):
        code, out, err = self.run_cli(["--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.core.requests, [])
        self.assertEqual(out.count("# POST /api/roles\n"), 1)
        self.assertIn("# PUT /api/roles/SRTM_LECTOR/permissions\n", out)

    def test_crea_el_rol_con_sus_permisos(self):
        code, out, err = self.run_cli()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.writes(), [
            ("POST", "/api/roles", {"name": "SRTM_LECTOR", "label": "Lector de srtm"}),
            ("PUT", "/api/roles/SRTM_LECTOR/permissions", {"permissions": [
                {"objectName": "predio_catastral", "action": "READ"},
                {"objectName": "construccion", "action": "READ"},
                {"objectName": "obra_complementaria", "action": "READ"},
                {"objectName": "arancel", "action": "READ"},
                {"objectName": "arancel", "action": "CREATE"},
                {"objectName": "arancel", "action": "UPDATE"},
                {"objectName": "arancel", "action": "DELETE"},
                {"objectName": "configuracion_catastro", "action": "READ"},
                {"objectName": "entrega_catastral", "action": "READ"},
                {"objectName": "titular_catastral", "action": "READ"},
                {"objectName": "tramo_via", "action": "READ"}]})])
        for method, path, auth, body in self.core.requests:
            self.assertEqual(auth, None if path == "/api/auth/login" else "Bearer t")
        self.assertIn("done: 1 created, 0 updated, 0 skipped", out)

    def test_la_segunda_corrida_no_escribe_nada(self):
        self.run_cli()
        self.core.requests.clear()
        code, out, err = self.run_cli()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.writes(), [])
        self.assertIn("done: 0 created, 0 updated, 1 skipped", out)

    def test_sincroniza_los_permisos_de_un_rol_que_ya_existe(self):
        # un SRTM_LECTOR al que en el admin le dieron UPDATE sobre construccion y que no lee obras: queda como dice roles.json
        self.core.roles["SRTM_LECTOR"] = {"name": "SRTM_LECTOR", "label": "Lector de srtm", "permissions": [
            {"objectName": "predio_catastral", "action": "READ", "allowed": True},
            {"objectName": "construccion", "action": "READ", "allowed": True},
            {"objectName": "arancel", "action": "READ", "allowed": True},
            {"objectName": "construccion", "action": "UPDATE", "allowed": True}]}
        code, out, err = self.run_cli()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.writes(), [("PUT", "/api/roles/SRTM_LECTOR/permissions",
                                          apply_roles.permissions_payload(self.roles_json["SRTM_LECTOR"]))])
        self.assertIn("done: 0 created, 1 updated, 0 skipped", out)

    def test_un_rechazo_de_core_sale_con_1(self):
        self.core.fail_on_role = "SRTM_LECTOR"
        code, out, err = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("error POST /api/roles", err)

    def test_un_roles_json_invalido_no_llama_a_core(self):
        roles = load(ROLES_PATH)
        roles["roles"][0]["permisos"]["predio"] = ["READ"]
        with tempfile.TemporaryDirectory() as carpeta:
            path = os.path.join(carpeta, "roles.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(roles, f)
            code, out, err = self.run_cli(roles_path=path)
        self.assertEqual(code, 2)
        self.assertIn("predio", out)
        self.assertEqual(self.core.requests, [])


if __name__ == "__main__":
    unittest.main()
