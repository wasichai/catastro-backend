"""Pruebas de importar_corte_brecha.py contra un FakeCore, con un corte ficticio que se arma aquí con duckdb.

Correr: cd model && python3 -m unittest -v (con duckdb: python3 -m pip install -r requirements-corte.txt). Sin duckdb
estas pruebas se saltan, salvo con REQUIERE_DUCKDB=1, como en el CI, donde fallan.
"""
import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest

import importar_corte_brecha as corte
from fake_core import FakeCore
from helpers import run

try:
    import duckdb
except ImportError:  # pragma: no cover - the CI installs it
    duckdb = None
    if os.environ.get("REQUIERE_DUCKDB") == "1":
        raise

ORG, FECHA, CORRIDA = "ica-prueba", "2026-10-25", "c0rr1da-0000-0000-0000-000000000001"

# srtm_brecha_predio's columns and types (srtm-backend docs/informes/brecha/herramientas/tablas.py)
DECIMAL = "DECIMAL(38,10)"
COLUMNAS_PREDIO = [
    ("id", "VARCHAR"), ("corrida", "VARCHAR"), ("predio", "VARCHAR"), ("codigo_catastro", "VARCHAR"),
    ("codigo_predio", "VARCHAR"), ("categoria", "VARCHAR"), ("sector", "VARCHAR"), ("manzana", "VARCHAR"),
    ("lote", "VARCHAR"), ("uso", "VARCHAR"), ("autoavaluo_declarado", DECIMAL), ("autoavaluo_catastro", DECIMAL),
    ("delta_autoavaluo", DECIMAL), ("impuesto_declarado", DECIMAL), ("impuesto_catastro", DECIMAL),
    ("delta_impuesto", DECIMAL), ("delta_arbitrios", DECIMAL), ("estimado", "BOOLEAN"), ("motivo", "VARCHAR"),
    ("confianza", "VARCHAR"), ("confianza_motivo", "VARCHAR"), ("orden", "BIGINT")]
COLUMNAS_CORRIDA = [
    ("id", "VARCHAR"), ("anio", "BIGINT"), ("estado", "VARCHAR"), ("version_catastro", "VARCHAR"),
    ("iniciado", "TIMESTAMPTZ"), ("terminado", "TIMESTAMPTZ"), ("total_predios", "BIGINT"), ("declarado", DECIMAL),
    ("catastro", DECIMAL), ("delta_impuesto", DECIMAL), ("delta_arbitrios", DECIMAL), ("origen", "VARCHAR"),
    ("predios_confiable", "BIGINT"), ("predios_dudoso", "BIGINT"), ("predios_sin_levantar", "BIGINT"),
    ("delta_impuesto_confiable", DECIMAL), ("delta_impuesto_dudoso", DECIMAL), ("delta_impuesto_sin_levantar", DECIMAL)]
COLUMNAS_PARAMETRO = [
    ("id", "VARCHAR"), ("tipo", "VARCHAR"), ("clave", "VARCHAR"), ("vigencia_desde", "DATE"),
    ("vigencia_hasta", "DATE"), ("valor_numerico", DECIMAL), ("texto", "VARCHAR"), ("norma", "VARCHAR"),
    ("estado", "VARCHAR")]


def fila(n, codigo, categoria, delta_autoavaluo, delta_impuesto, confianza="CONFIABLE", **otros):
    return {"id": f"bp-{n}", "corrida": CORRIDA, "predio": f"p-{n}", "codigo_catastro": codigo,
            "codigo_predio": f"PR-{n}", "categoria": categoria, "sector": "01", "manzana": "02", "lote": str(n),
            "uso": "010101", "autoavaluo_declarado": "1000", "autoavaluo_catastro": "1000",
            "delta_autoavaluo": delta_autoavaluo, "impuesto_declarado": "10", "impuesto_catastro": "10",
            "delta_impuesto": delta_impuesto, "delta_arbitrios": "1.5", "estimado": categoria == "OMISO",
            "motivo": None, "confianza": confianza, "confianza_motivo": "ficha completa", "orden": n, **otros}


# five ficticious rows: one matches by its codigo municipal written with leading zeros, one by its CPU, one has no
# ficha, one is a SIN_CATASTRO without codigo_catastro, one OMISO above 5 UIT (5 x 5500 = 27500)
FILAS = [
    fila(1, "1-2-3", "SUBVALUADO", "30000", "120.50"),
    fila(2, "CPU-0077", "SOBREVALUADO", "-500", "-3.25", confianza="DUDOSO"),
    fila(3, "9-9-9", "COINCIDE", "0", "0"),
    fila(4, None, "SIN_CATASTRO", None, None, confianza="SIN_LEVANTAR"),
    fila(5, "01-02-0005", "OMISO", "-28000", "80", confianza=None),
]
UIT = [{"id": "u1", "tipo": "UIT", "clave": "", "vigencia_desde": "2026-01-01", "vigencia_hasta": "2026-12-31",
        "valor_numerico": "5500", "texto": None, "norma": "DS", "estado": "VIGENTE"},
       {"id": "u0", "tipo": "UIT", "clave": "", "vigencia_desde": "2025-01-01", "vigencia_hasta": "2025-12-31",
        "valor_numerico": "5350", "texto": None, "norma": "DS", "estado": "VIGENTE"}]


def corrida(**otros):
    return {"id": CORRIDA, "anio": 2026, "estado": "TERMINADA", "version_catastro": "valuacion-v3",
            "iniciado": "2026-10-25 10:00:00+00", "terminado": "2026-10-25 10:05:00+00", "total_predios": 5,
            "declarado": "50", "catastro": "247.25", "delta_impuesto": "197.25", "delta_arbitrios": "7.5",
            "origen": "MANUAL", "predios_confiable": 2, "predios_dudoso": 1, "predios_sin_levantar": 1,
            "delta_impuesto_confiable": "120.5", "delta_impuesto_dudoso": "-3.25", "delta_impuesto_sin_levantar": "0",
            **otros}


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def escribir_parquet(con, ruta, columnas, filas):
    nombres = ", ".join(f'"{c}" {t}' for c, t in columnas)
    con.execute(f"CREATE OR REPLACE TABLE t ({nombres})")
    for f in filas:
        con.execute(f"INSERT INTO t VALUES ({', '.join('?' for _ in columnas)})", [f.get(c) for c, _ in columnas])
    con.execute(f"COPY t TO '{ruta}' (FORMAT parquet)")


def armar_corte(testcase, filas=FILAS, parametros=UIT, la_corrida=None):
    """A corte <org>/<fecha>/ as srtm's make corte writes it: the Parquet and a manifiesto.json with their sha256."""
    raiz = tempfile.TemporaryDirectory()
    testcase.addCleanup(raiz.cleanup)
    carpeta = os.path.join(raiz.name, ORG, FECHA)
    os.makedirs(carpeta)
    con = duckdb.connect()
    tablas = {"srtm_brecha_corrida.parquet": (COLUMNAS_CORRIDA, [la_corrida or corrida()]),
              "srtm_brecha_predio.parquet": (COLUMNAS_PREDIO, filas),
              "srtm_parametro.parquet": (COLUMNAS_PARAMETRO, parametros)}
    archivos = []
    for nombre, (columnas, contenido) in tablas.items():
        ruta = os.path.join(carpeta, nombre)
        escribir_parquet(con, ruta, columnas, contenido)
        archivos.append({"archivo": nombre, "bytes": os.path.getsize(ruta), "sha256": _sha(ruta),
                         "filas": len(contenido), "tabla": nombre[:-8]})
    con.close()
    manifiesto = {"formato": 1, "organizacion": ORG, "fecha_corte": FECHA, "tipo": "mensual", "anio": 2026,
                  "leido_en": "2026-10-25T15:00:00Z", "motor": {"version": "valuacion-v3", "region": "COSTA"},
                  "brecha_corrida": {"id": CORRIDA, "terminado": "2026-10-25T10:05:00Z",
                                     "version_catastro": "valuacion-v3"},
                  "backends": {"srtm": {"url": "http://srtm", "version": "2.1.0"},
                               "catastro": {"url": "http://catastro", "version": "0.9.0"}},
                  "archivos": sorted(archivos, key=lambda a: a["archivo"])}
    with open(os.path.join(carpeta, "manifiesto.json"), "w", encoding="utf-8") as f:
        json.dump(manifiesto, f)
    return carpeta


class LlaveTests(unittest.TestCase):
    def test_como_brecha_llave_de_srtm(self):
        self.assertEqual(corte.llave(" 01-01-0006 "), "1-1-6")
        self.assertEqual(corte.llave("a-08"), "A-8")
        self.assertEqual(corte.llave("000"), "0")
        self.assertEqual(corte.llave("CPU-0077"), "CPU-77")
        self.assertIsNone(corte.llave("  "))
        self.assertIsNone(corte.llave(None))


@unittest.skipIf(duckdb is None, "duckdb no está instalado (requirements-corte.txt)")
class ImportarCorteTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore(login_response={"token": "t", "user": {"organizationId": "org-ica"}})
        self.addCleanup(self.core.stop)
        # the fichas of catastro: 01-02-0003 is the row's 1-2-3; the CPU of 01-02-0002 is the row's CPU-0077;
        # 7-7-7 and 07-07-07 are the same key, so neither matches
        for codigo, cpu in (("01-02-0003", None), ("01-02-0002", "CPU-77"), ("01-02-0005", None),
                            ("7-7-7", None), ("07-07-07", None)):
            self.core.add_record("predio_catastral", {"codigo_municipal": codigo, "codigo_cpu": cpu})

    def cli(self, carpeta, *extra):
        return run(corte.main, ["--corte", carpeta, "--core", self.core.base_url, *extra])

    def escrituras(self):
        return [(m, p) for m, p, _, _ in self.core.requests if m in ("POST", "PATCH", "PUT", "DELETE")
                and p != "/api/auth/login"]

    def fichas(self):
        return {r["attributes"]["codigo_predio"]: r["attributes"] for r in self.core.records.get("brecha_ficha", [])}

    def test_carga_el_corte_y_sus_fichas(self):
        code, out, err = self.cli(armar_corte(self))
        self.assertEqual(code, 0, err)
        [registro] = self.core.records["corte_brecha"]
        c = registro["attributes"]
        self.assertEqual((c["clave"], c["org_slug"], c["fecha"], c["corrida"], c["anio"]),
                         (f"{ORG}|{FECHA}", ORG, FECHA, CORRIDA, 2026))
        self.assertEqual((c["version_srtm"], c["version_catastro"], c["total_fichas"]), ("2.1.0", "valuacion-v3", 5))
        self.assertEqual((c["delta_impuesto"], c["delta_impuesto_confiable"], c["omisos_estimado"]),
                         ("197.25", "120.5", "80"))
        self.assertEqual(len(c["manifiesto_sha256"]), 64)
        self.assertTrue(c["cargado_en"].endswith("Z"))
        f = self.fichas()
        self.assertEqual(len(f), 5)
        for atributos in f.values():
            self.assertEqual(atributos["corte"], registro["id"])
        # matched with leading zeros, by CPU, by the codigo municipal as is; no ficha; no code at all
        self.assertEqual(f["PR-1"]["codigo_municipal"], "01-02-0003")
        self.assertEqual(f["PR-2"]["codigo_municipal"], "01-02-0002")
        self.assertEqual(f["PR-5"]["codigo_municipal"], "01-02-0005")
        self.assertNotIn("codigo_municipal", f["PR-3"])
        self.assertNotIn("codigo_catastro", f["PR-4"])
        self.assertEqual(f["PR-1"]["clave"], f"{registro['id']}|1-2-3")
        self.assertEqual(f["PR-4"]["clave"], f"{registro['id']}|id:bp-4")
        # |Δ autoavalúo| > 5 UIT (27500): 30000 and -28000; without Δ autoavalúo, empty
        self.assertEqual({k: v.get("supera_5_uit") for k, v in f.items()},
                         {"PR-1": True, "PR-2": False, "PR-3": False, "PR-4": None, "PR-5": True})
        self.assertEqual((f["PR-1"]["delta_impuesto"], f["PR-1"]["categoria"], f["PR-1"]["confianza"]),
                         ("120.5", "SUBVALUADO", "CONFIABLE"))
        self.assertNotIn("confianza", f["PR-5"])
        self.assertIs(f["PR-5"]["estimado"], True)
        # every write says which corte it is
        reasons = {r for m, p, r in self.core.reasons if m in ("POST", "PATCH") and p.startswith("/api/objects/")}
        self.assertEqual(reasons, {f"corte-brecha:{ORG}:{FECHA}"})
        self.assertIn("filas: 5", out)
        self.assertIn("por categoria: COINCIDE 1, OMISO 1, SIN_CATASTRO 1, SOBREVALUADO 1, SUBVALUADO 1", out)
        self.assertIn("empatadas con ficha: 3", out)
        self.assertIn("sin ficha: 1 con codigo_catastro, 1 sin codigo", out)
        self.assertIn("supera 5 UIT: 2", out)
        self.assertIn("corte ica-prueba|2026-10-25: create; fichas: 5 created", out)
        # only counts: no code and no amount of a predio
        for dato in ("01-02-0003", "1-2-3", "PR-1", "120.5", "30000"):
            self.assertNotIn(dato, out)

    def test_las_llaves_repetidas_no_empatan(self):
        filas = [fila(1, "7-7-7", "COINCIDE", "0", "0")]
        code, out, err = self.cli(armar_corte(self, filas=filas))
        self.assertEqual(code, 0, err)
        self.assertNotIn("codigo_municipal", self.fichas()["PR-1"])
        self.assertIn("llaves de fichas repetidas (no empatan): 1", out)

    def test_un_sha_que_no_coincide_sale_con_2_sin_llamar_a_core(self):
        carpeta = armar_corte(self)
        with open(os.path.join(carpeta, "srtm_brecha_predio.parquet"), "ab") as f:
            f.write(b"x")
        code, _, err = self.cli(carpeta)
        self.assertEqual(code, 2)
        self.assertIn("srtm_brecha_predio.parquet no coincide con su sha256", err)
        self.assertEqual(self.core.requests, [])

    def test_un_archivo_que_falta_sale_con_2(self):
        carpeta = armar_corte(self)
        os.unlink(os.path.join(carpeta, "srtm_parametro.parquet"))
        code, _, err = self.cli(carpeta)
        self.assertEqual(code, 2)
        self.assertIn("falta srtm_parametro.parquet", err)

    def test_dry_run_no_escribe(self):
        code, out, err = self.cli(armar_corte(self), "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.escrituras(), [])
        self.assertIn("corte ica-prueba|2026-10-25: create; fichas: 5 to create, 0 to update, 0 to delete", out)

    def test_la_segunda_carga_del_mismo_corte_no_escribe_nada(self):
        carpeta = armar_corte(self)
        self.assertEqual(self.cli(carpeta)[0], 0)
        cargado = self.core.records["corte_brecha"][0]["attributes"]["cargado_en"]
        self.core.requests.clear()
        code, out, err = self.cli(carpeta)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.escrituras(), [])
        self.assertIn("corte ica-prueba|2026-10-25: unchanged; fichas: 0 created, 0 updated, 0 deleted, 5 unchanged", out)
        self.assertEqual(self.core.records["corte_brecha"][0]["attributes"]["cargado_en"], cargado)

    def test_una_fila_que_cambia_se_actualiza_y_la_que_falta_solo_con_reemplazar(self):
        self.assertEqual(self.cli(armar_corte(self))[0], 0)
        cambiadas = [fila(1, "1-2-3", "SUBVALUADO", "30000", "99.10")] + FILAS[1:4]
        self.core.requests.clear()
        code, out, err = self.cli(armar_corte(self, filas=cambiadas))
        self.assertEqual(code, 0, err)
        self.assertIn("fichas: 0 created, 1 updated, 0 deleted, 3 unchanged, 1 absent from the corte kept", out)
        self.assertEqual(self.fichas()["PR-1"]["delta_impuesto"], "99.1")
        self.assertIn("PR-5", self.fichas())
        # the corte's totals moved with it: 4 fichas, no omiso
        self.assertEqual(self.core.records["corte_brecha"][0]["attributes"]["total_fichas"], 4)
        code, out, err = self.cli(armar_corte(self, filas=cambiadas), "--reemplazar")
        self.assertEqual(code, 0, err)
        self.assertIn("fichas: 0 created, 0 updated, 1 deleted, 4 unchanged, 1 absent from the corte deleted", out)
        self.assertNotIn("PR-5", self.fichas())
        self.assertEqual(len(self.core.records["corte_brecha"]), 1)

    def test_sin_uit_en_el_corte_usa_la_de_la_opcion(self):
        carpeta = armar_corte(self, parametros=[])
        code, out, err = self.cli(carpeta, "--uit", "6000")
        self.assertEqual(code, 0, err)
        # 5 x 6000 = 30000: 30000 is not above it, -28000 neither
        self.assertEqual({k: v.get("supera_5_uit") for k, v in self.fichas().items()},
                         {"PR-1": False, "PR-2": False, "PR-3": False, "PR-4": None, "PR-5": False})

    def test_sin_uit_ninguna_supera_5_uit_queda_vacia(self):
        code, out, err = self.cli(armar_corte(self, parametros=[]))
        self.assertEqual(code, 0, err)
        self.assertTrue(all("supera_5_uit" not in a for a in self.fichas().values()))
        self.assertIn("supera 5 UIT: 0 (sin UIT)", out)

    def test_otra_organizacion_no_escribe(self):
        code, _, err = self.cli(armar_corte(self), "--org", "org-otra")
        self.assertEqual(code, 2)
        self.assertIn("is of the organization org-ica, not org-otra", err)
        self.assertEqual(self.escrituras(), [])
        self.assertEqual(self.cli(armar_corte(self), "--org", "org-ica")[0], 0)

    def test_una_categoria_que_el_modelo_no_tiene_sale_con_2(self):
        code, _, err = self.cli(armar_corte(self, filas=[fila(1, "1-2-3", "RARO", "0", "0")]))
        self.assertEqual(code, 2)
        self.assertIn("categoria 'RARO'", err)
        self.assertEqual(self.escrituras(), [])

    def test_el_corte_baja_de_s3(self):
        carpeta = armar_corte(self)
        # a fake aws: `aws s3 cp --recursive --only-show-errors <uri>/ <destino>` copies the corte's folder
        bin_ = tempfile.TemporaryDirectory()
        self.addCleanup(bin_.cleanup)
        falso = os.path.join(bin_.name, "aws")
        with open(falso, "w", encoding="utf-8") as f:
            f.write(f"#!{sys.executable}\nimport shutil, sys\n"
                    f"assert sys.argv[1:4] == ['s3', 'cp', '--recursive'], sys.argv\n"
                    f"assert sys.argv[-2] == 's3://bucket/analitica/{ORG}/{FECHA}/', sys.argv\n"
                    f"shutil.copytree({carpeta!r}, sys.argv[-1], dirs_exist_ok=True)\n")
        os.chmod(falso, os.stat(falso).st_mode | stat.S_IXUSR)
        self.addCleanup(setattr, corte, "AWS", corte.AWS)
        corte.AWS = falso
        code, out, err = run(corte.main, ["--s3", f"s3://bucket/analitica/{ORG}/{FECHA}", "--core", self.core.base_url])
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.fichas()), 5)

    def test_una_copia_de_s3_que_falla_sale_con_2(self):
        bin_ = tempfile.TemporaryDirectory()
        self.addCleanup(bin_.cleanup)
        falso = os.path.join(bin_.name, "aws")
        with open(falso, "w", encoding="utf-8") as f:
            f.write(f"#!{sys.executable}\nimport sys\nsys.exit('An error occurred (AccessDenied)')\n")
        os.chmod(falso, os.stat(falso).st_mode | stat.S_IXUSR)
        self.addCleanup(setattr, corte, "AWS", corte.AWS)
        corte.AWS = falso
        code, _, err = run(corte.main, ["--s3", "s3://bucket/x", "--core", self.core.base_url])
        self.assertEqual(code, 2)
        self.assertIn("aws s3 cp s3://bucket/x salió con 1: An error occurred (AccessDenied)", err)
        self.assertEqual(self.core.requests, [])


if __name__ == "__main__":
    unittest.main()
