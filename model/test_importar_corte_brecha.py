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
# srtm_brecha_nivel (srtm-backend#257)
COLUMNAS_NIVEL = [
    ("id", "VARCHAR"), ("corrida", "VARCHAR"), ("brecha_predio", "VARCHAR"), ("piso", "BIGINT"),
    ("area_rentas", DECIMAL), ("area_catastro", DECIMAL), ("estado", "VARCHAR")]
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


def nivel(n, predio, piso, area_rentas, area_catastro, estado):
    return {"id": f"bn-{n}", "corrida": CORRIDA, "brecha_predio": f"bp-{predio}", "piso": piso,
            "area_rentas": area_rentas, "area_catastro": area_catastro, "estado": estado}


# PR-1 with two pisos, the second only in catastro; PR-2 with one only in rentas; PR-4 (no codigo_catastro) one AMBIGUO
NIVELES = [
    nivel(1, 1, 1, "120.5", "120.5", "PAR"),
    nivel(2, 1, 2, None, "80", "SOLO_CATASTRO"),
    nivel(3, 2, 1, "60", None, "SOLO_RENTAS"),
    nivel(4, 4, 1, "50", "75.25", "AMBIGUO"),
]


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


def armar_corte(testcase, filas=FILAS, parametros=UIT, la_corrida=None, fecha=FECHA, listar_parametro=True,
                niveles=None):
    """A corte <org>/<fecha>/ as srtm's make corte writes it: the Parquet and a manifiesto.json with their sha256."""
    raiz = tempfile.TemporaryDirectory()
    testcase.addCleanup(raiz.cleanup)
    carpeta = os.path.join(raiz.name, ORG, fecha)
    os.makedirs(carpeta)
    con = duckdb.connect()
    tablas = {"srtm_brecha_corrida.parquet": (COLUMNAS_CORRIDA, [la_corrida or corrida()]),
              "srtm_brecha_predio.parquet": (COLUMNAS_PREDIO, filas),
              "srtm_parametro.parquet": (COLUMNAS_PARAMETRO, parametros)}
    if niveles is not None:
        tablas["srtm_brecha_nivel.parquet"] = (COLUMNAS_NIVEL, niveles)
    archivos = []
    for nombre, (columnas, contenido) in tablas.items():
        ruta = os.path.join(carpeta, nombre)
        escribir_parquet(con, ruta, columnas, contenido)
        if nombre == "srtm_parametro.parquet" and not listar_parametro:
            continue
        archivos.append({"archivo": nombre, "bytes": os.path.getsize(ruta), "sha256": _sha(ruta),
                         "filas": len(contenido), "tabla": nombre[:-8]})
    con.close()
    manifiesto = {"formato": 1, "organizacion": ORG, "fecha_corte": fecha, "tipo": "mensual", "anio": 2026,
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
        # the layers keep the classes of their publish: the summary says to publish them again
        self.assertIn("siguiente paso: python3 -I vistas_de_mapa.py", out)
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

    def test_una_fila_que_cambia_se_actualiza_y_una_que_falta_pide_reemplazar(self):
        self.assertEqual(self.cli(armar_corte(self))[0], 0)
        cambiadas = [fila(1, "1-2-3", "SUBVALUADO", "30000", "99.10")] + FILAS[1:4]
        self.core.requests.clear()
        # PR-5 no longer comes: without --reemplazar nothing is written, so the total and the fichas never disagree
        code, out, err = self.cli(armar_corte(self, filas=cambiadas))
        self.assertEqual(code, 2)
        self.assertIn("1 fichas del corte guardado ya no vienen en el corte: --reemplazar", err)
        self.assertIn("fichas: 0 to create, 1 to update, 0 to delete, 3 unchanged, 1 absent from the corte kept", out)
        self.assertEqual(self.escrituras(), [])
        self.assertEqual(self.fichas()["PR-1"]["delta_impuesto"], "120.5")
        code, out, err = self.cli(armar_corte(self, filas=cambiadas), "--reemplazar")
        self.assertEqual(code, 0, err)
        self.assertIn("fichas: 0 created, 1 updated, 1 deleted, 3 unchanged, 1 absent from the corte deleted", out)
        self.assertEqual(self.fichas()["PR-1"]["delta_impuesto"], "99.1")
        self.assertNotIn("PR-5", self.fichas())
        self.assertEqual(self.core.records["corte_brecha"][0]["attributes"]["total_fichas"], 4)
        self.assertEqual(len(self.core.records["corte_brecha"]), 1)

    def test_reemplazar_no_toca_las_fichas_de_otro_corte(self):
        self.assertEqual(self.cli(armar_corte(self))[0], 0)
        # another corte: another fecha, the same rows
        otro = armar_corte(self, fecha="2026-11-25")
        self.assertEqual(self.cli(otro, "--reemplazar")[0], 0)
        self.assertEqual(len(self.core.records["corte_brecha"]), 2)
        self.assertEqual(len(self.core.records["brecha_ficha"]), 10)
        code, out, err = self.cli(armar_corte(self, filas=FILAS[:1], fecha="2026-11-25"), "--reemplazar")
        self.assertEqual(code, 0, err)
        self.assertIn("4 deleted", out)
        por_corte = {}
        for r in self.core.records["brecha_ficha"]:
            por_corte[r["attributes"]["corte"]] = por_corte.get(r["attributes"]["corte"], 0) + 1
        self.assertEqual(sorted(por_corte.values()), [1, 5])

    def test_el_corte_se_hace_visible_al_final(self):
        # cargado_en (what the API needs to show a corte) goes in a last PATCH, after every ficha
        self.assertEqual(self.cli(armar_corte(self))[0], 0)
        escrituras = [(m, p, b) for m, p, _, b in self.core.requests if m in ("POST", "PATCH")
                      and p.startswith("/api/objects/")]
        crear = escrituras[0]
        self.assertEqual(crear[1], "/api/objects/corte_brecha/records")
        self.assertNotIn("cargado_en", crear[2]["attributes"])
        self.assertTrue(all(p == "/api/objects/brecha_ficha/records" for _, p, _ in escrituras[1:-1]))
        self.assertEqual(len(escrituras[1:-1]), 5)
        ultimo = escrituras[-1]
        self.assertTrue(ultimo[1].startswith("/api/objects/corte_brecha/records/"), ultimo)
        self.assertEqual(list(ultimo[2]["attributes"]), ["cargado_en"])
        # a reload hides it first, then shows it again at the end
        self.core.requests.clear()
        cambiadas = [fila(1, "1-2-3", "SUBVALUADO", "30000", "99.10")] + FILAS[1:]
        self.assertEqual(self.cli(armar_corte(self, filas=cambiadas))[0], 0)
        cortes = [b["attributes"] for m, p, _, b in self.core.requests if m == "PATCH" and "/corte_brecha/" in p]
        self.assertIsNone(cortes[0]["cargado_en"])
        self.assertEqual(list(cortes[-1]), ["cargado_en"])

    def test_una_carga_a_medias_queda_oculta_y_la_siguiente_la_termina(self):
        self.core.fail_record_after = {"brecha_ficha": 2}
        code, _, err = self.cli(armar_corte(self))
        self.assertEqual(code, 1)
        # only the status and the fields Core names, never its message
        self.assertIn("-> 400 (campos: piso)", err)
        self.assertNotIn("boom-after", err)
        self.assertNotIn("cargado_en", self.core.records["corte_brecha"][0]["attributes"])
        self.core.fail_record_after = {}
        code, out, err = self.cli(armar_corte(self))
        self.assertEqual(code, 0, err)
        self.assertIn("cargado_en", self.core.records["corte_brecha"][0]["attributes"])
        self.assertEqual(len(self.fichas()), 5)
        # all loaded but cargado_en: the next run only shows it
        del self.core.records["corte_brecha"][0]["attributes"]["cargado_en"]
        self.core.requests.clear()
        code, out, err = self.cli(armar_corte(self))
        self.assertEqual(code, 0, err)
        self.assertIn("cargado_en", self.core.records["corte_brecha"][0]["attributes"])
        self.assertEqual([m for m, p in self.escrituras()], ["PATCH", "PATCH"])

    def test_la_cpu_de_una_ficha_sin_codigo_no_empata_con_otra(self):
        # X has no codigo_municipal and CPU 123: srtm writes its row with codigo_catastro 123. Y (01-01-0006) shares
        # the CPU: matching the row to Y would put X's brecha on Y's predio. the same with sector-manzana-lote
        self.core.add_record("predio_catastral", {"codigo_cpu": "123", "sector": "5", "manzana": "5", "lote": "5"})
        self.core.add_record("predio_catastral", {"codigo_municipal": "01-01-0006", "codigo_cpu": "0123",
                                                  "sector": "05", "manzana": "05", "lote": "05"})
        filas = [fila(1, "123", "OMISO", "0", "0"), fila(2, "5-5-5", "OMISO", "0", "0"),
                 fila(3, "1-1-6", "COINCIDE", "0", "0")]
        code, out, err = self.cli(armar_corte(self, filas=filas))
        self.assertEqual(code, 0, err)
        f = self.fichas()
        self.assertNotIn("codigo_municipal", f["PR-1"])
        self.assertNotIn("codigo_municipal", f["PR-2"])
        self.assertEqual(f["PR-3"]["codigo_municipal"], "01-01-0006")

    def test_un_digito_que_no_es_ascii_no_se_normaliza(self):
        # as Kotlin's \\d in Brecha.llave(): only ASCII digits lose their zeros
        self.assertEqual(corte.llave("0\u0663"), "0\u0663")

    def test_un_archivo_que_el_manifiesto_no_lista_sale_con_2(self):
        carpeta = armar_corte(self)
        with open(os.path.join(carpeta, "otra.parquet"), "wb") as f:
            f.write(b"x")
        code, _, err = self.cli(carpeta)
        self.assertEqual(code, 2)
        self.assertIn("sobran otra.parquet", err)
        self.assertEqual(self.core.requests, [])

    def test_un_srtm_parametro_sin_listar_no_se_lee(self):
        carpeta = armar_corte(self, listar_parametro=False)
        code, _, err = self.cli(carpeta)
        self.assertEqual(code, 2)
        self.assertIn("sobran srtm_parametro.parquet", err)

    def test_otro_formato_o_filas_distintas_salen_con_2(self):
        carpeta = armar_corte(self)
        ruta = os.path.join(carpeta, "manifiesto.json")
        with open(ruta, encoding="utf-8") as f:
            manifiesto = json.load(f)
        manifiesto["formato"] = 2
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(manifiesto, f)
        code, _, err = self.cli(carpeta)
        self.assertEqual(code, 2)
        self.assertIn("de formato 2", err)
        manifiesto["formato"] = 1
        next(a for a in manifiesto["archivos"] if a["archivo"] == "srtm_brecha_predio.parquet")["filas"] = 9
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(manifiesto, f)
        code, _, err = self.cli(carpeta)
        self.assertEqual(code, 2)
        self.assertIn("filas de srtm_brecha_predio.parquet", err)
        self.assertEqual(self.core.requests, [])

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

    # ---- the copies for the map view: the decision's estado and the predio's lote ----

    def con_lotes(self):
        """01-02-0003 and 01-02-0005 get a lote; 01-02-0002 has none. A decision of 2026 for 01-02-0003."""
        for predio in self.core.records["predio_catastral"]:
            codigo = predio["attributes"].get("codigo_municipal")
            if codigo in ("01-02-0003", "01-02-0005"):
                predio["geometries"] = {"lote_geom": lote(codigo)}
        self.core.add_record("decision_brecha", {"clave": "01-02-0003|2026", "codigo_municipal": "01-02-0003",
                                                 "anio": 2026, "estado": "A_FISCALIZAR"})
        # another year's decision is not this corte's
        self.core.add_record("decision_brecha", {"clave": "01-02-0005|2025", "codigo_municipal": "01-02-0005",
                                                 "anio": 2025, "estado": "DESCARTADO"})

    def lotes_por_corte(self):
        """corte id -> {codigo_predio: its lote_geom or None}."""
        por_corte = {}
        for r in self.core.records.get("brecha_ficha", []):
            por_corte.setdefault(r["attributes"]["corte"], {})[r["attributes"]["codigo_predio"]] = \
                (r.get("geometries") or {}).get("lote_geom")
        return por_corte

    def corte_id(self, fecha):
        return next(c["id"] for c in self.core.records["corte_brecha"] if c["attributes"]["fecha"] == fecha)

    def test_cada_ficha_lleva_el_estado_de_su_decision_y_el_lote_de_su_predio(self):
        self.con_lotes()
        code, out, err = self.cli(armar_corte(self))
        self.assertEqual(code, 0, err)
        f = self.fichas()
        self.assertEqual({k: v["estado"] for k, v in f.items()},
                         {"PR-1": "A_FISCALIZAR", "PR-2": "PENDIENTE", "PR-3": "PENDIENTE", "PR-4": "PENDIENTE",
                          "PR-5": "PENDIENTE"})
        lotes = self.lotes_por_corte()[self.corte_id(FECHA)]
        self.assertEqual(lotes, {"PR-1": lote("01-02-0003"), "PR-2": None, "PR-3": None, "PR-4": None,
                                 "PR-5": lote("01-02-0005")})
        # a POST without a lote sends no geometries at all
        posts = [b for m, p, _, b in self.core.requests if m == "POST" and p == "/api/objects/brecha_ficha/records"]
        self.assertEqual(sorted("geometries" in b for b in posts), [False, False, False, True, True])
        self.assertIn("lotes: 2 fichas del corte con lote; 0 fichas de cortes anteriores con lote cleared", out)
        # a lote that comes back from Core within the tolerance is the same: nothing to write
        for r in self.core.records["brecha_ficha"]:
            g = (r.get("geometries") or {}).get("lote_geom")
            if g:
                g["coordinates"] = [[[x + 4e-7, y - 4e-7] for x, y in anillo] for anillo in g["coordinates"]]
        self.core.requests.clear()
        code, out, err = self.cli(armar_corte(self))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.escrituras(), [])
        # a decision taken since, and a lote that moved, are written on the next load
        self.core.records["decision_brecha"][0]["attributes"]["estado"] = "INSPECCIONADO"
        movido = lote("01-02-0005", dx=0.001)
        next(p for p in self.core.records["predio_catastral"]
             if p["attributes"].get("codigo_municipal") == "01-02-0005")["geometries"]["lote_geom"] = movido
        code, out, err = self.cli(armar_corte(self))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.fichas()["PR-1"]["estado"], "INSPECCIONADO")
        self.assertEqual(self.lotes_por_corte()[self.corte_id(FECHA)]["PR-5"], movido)
        self.assertIn("fichas: 0 created, 2 updated", out)

    def test_un_corte_nuevo_quita_el_lote_de_las_fichas_de_los_anteriores(self):
        self.con_lotes()
        self.assertEqual(self.cli(armar_corte(self))[0], 0)
        code, out, err = self.cli(armar_corte(self, fecha="2026-11-25"), "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("lotes: 2 fichas del corte con lote; 2 fichas de cortes anteriores con lote to clear", out)
        code, out, err = self.cli(armar_corte(self, fecha="2026-11-25"))
        self.assertEqual(code, 0, err)
        self.assertIn("2 fichas de cortes anteriores con lote cleared", out)
        por_corte = self.lotes_por_corte()
        self.assertEqual(set(por_corte[self.corte_id(FECHA)].values()), {None})
        self.assertEqual(sum(1 for g in por_corte[self.corte_id("2026-11-25")].values() if g), 2)
        # the clearing PATCHes send only the geometry, with the corte's reason
        limpiar = [(b, r) for (m, p, _, b), (_, _, r) in zip(self.core.requests, self.core.reasons)
                   if m == "PATCH" and "/brecha_ficha/" in p and b.get("geometries") == {"lote_geom": None}]
        self.assertEqual(len(limpiar), 2)
        self.assertTrue(all(b["attributes"] == {} and r == "corte-brecha:ica-prueba:2026-11-25" for b, r in limpiar))
        # --con-geometria-anterior keeps them
        code, out, err = self.cli(armar_corte(self, fecha="2026-12-25"), "--con-geometria-anterior")
        self.assertEqual(code, 0, err)
        self.assertEqual(sum(1 for g in self.lotes_por_corte()[self.corte_id("2026-11-25")].values() if g), 2)
        self.assertIn("0 fichas de cortes anteriores con lote cleared", out)

    def test_un_corte_anterior_cargado_despues_no_lleva_lote(self):
        self.con_lotes()
        self.assertEqual(self.cli(armar_corte(self, fecha="2026-11-25"))[0], 0)
        code, out, err = self.cli(armar_corte(self))
        self.assertEqual(code, 0, err)
        self.assertIn("lotes: 0 fichas del corte con lote (hay un corte más reciente: este no lleva lotes)", out)
        por_corte = self.lotes_por_corte()
        self.assertEqual(set(por_corte[self.corte_id(FECHA)].values()), {None})
        self.assertEqual(sum(1 for g in por_corte[self.corte_id("2026-11-25")].values() if g), 2)

    def test_con_geometria_anterior_un_corte_anterior_conserva_sus_lotes(self):
        self.con_lotes()
        self.assertEqual(self.cli(armar_corte(self))[0], 0)
        self.assertEqual(self.cli(armar_corte(self, fecha="2026-11-25"), "--con-geometria-anterior")[0], 0)
        # reloading the older corte, now not the latest, with --con-geometria-anterior: its lotes stay as they are
        self.core.requests.clear()
        code, out, err = self.cli(armar_corte(self), "--con-geometria-anterior")
        self.assertEqual(code, 0, err)
        self.assertEqual(sum(1 for g in self.lotes_por_corte()[self.corte_id(FECHA)].values() if g), 2)
        self.assertEqual(self.escrituras(), [])

    def test_un_corte_mas_nuevo_a_medio_cargar_no_le_quita_los_lotes_al_ultimo(self):
        self.con_lotes()
        self.assertEqual(self.cli(armar_corte(self))[0], 0)
        # a newer corte whose load crashed: no cargado_en, the API does not show it
        self.core.add_record("corte_brecha", {"clave": "ica-prueba|2026-12-01", "org_slug": ORG, "fecha": "2026-12-01",
                                              "anio": 2026})
        code, out, err = self.cli(armar_corte(self))
        self.assertEqual(code, 0, err)
        self.assertEqual(sum(1 for g in self.lotes_por_corte()[self.corte_id(FECHA)].values() if g), 2)

    def test_los_lotes_anteriores_se_buscan_con_un_bbox_en_el_servidor(self):
        self.con_lotes()
        self.assertEqual(self.cli(armar_corte(self))[0], 0)
        self.assertEqual(self.cli(armar_corte(self, fecha="2026-11-25"))[0], 0)
        [(objeto, caja, geometria)] = [q for q in self.core.bbox_queries]
        self.assertEqual((objeto, geometria), ("brecha_ficha", "lote_geom"))
        x0, y0, x1, y1 = (float(v) for v in caja.split(","))
        self.assertTrue(x0 < -75.73 < x1 and y0 < -14.07 < y1, caja)

    def test_un_codigo_de_dos_predios_no_toma_lote(self):
        self.con_lotes()
        self.core.add_record("predio_catastral", {"codigo_municipal": "01-02-0005"},
                             geometries={"lote_geom": lote("01-02-0005", dx=0.01)})
        code, out, err = self.cli(armar_corte(self))
        self.assertEqual(code, 0, err)
        self.assertIsNone(self.lotes_por_corte()[self.corte_id(FECHA)]["PR-5"])
        self.assertIn("lotes: 1 fichas del corte con lote, 1 códigos de dos o más predios sin lote", out)


def lote(codigo, dx=0.0):
    """A small fictitious square in Ica (EPSG:4326), a different one per code."""
    x, y = -75.73 + int(codigo[-1]) * 0.001 + dx, -14.07
    return {"type": "Polygon", "coordinates": [[[x, y], [x + 0.0001, y], [x + 0.0001, y + 0.0001], [x, y]]]}



@unittest.skipIf(duckdb is None, "duckdb no está instalado (requirements-corte.txt)")
class NivelesTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore(login_response={"token": "t", "user": {"organizationId": "org-ica"}})
        self.addCleanup(self.core.stop)
        for codigo, cpu in (("01-02-0003", None), ("01-02-0002", "CPU-77"), ("01-02-0005", None)):
            self.core.add_record("predio_catastral", {"codigo_municipal": codigo, "codigo_cpu": cpu})

    def cli(self, carpeta, *extra):
        return run(corte.main, ["--corte", carpeta, "--core", self.core.base_url, *extra])

    def escrituras(self):
        return [(m, p) for m, p, _, _ in self.core.requests if m in ("POST", "PATCH", "PUT", "DELETE")
                and p != "/api/auth/login"]

    def niveles(self):
        fichas = {r["id"]: r["attributes"]["codigo_predio"] for r in self.core.records.get("brecha_ficha", [])}
        return {(fichas[r["attributes"]["ficha"]], r["attributes"].get("piso")): r["attributes"]
                for r in self.core.records.get("brecha_nivel_ficha", [])}

    def test_cada_nivel_va_en_la_ficha_de_su_fila(self):
        code, out, err = self.cli(armar_corte(self, niveles=NIVELES))
        self.assertEqual(code, 0, err)
        [registro] = self.core.records["corte_brecha"]
        n = self.niveles()
        self.assertEqual(sorted(n), [("PR-1", 1), ("PR-1", 2), ("PR-2", 1), ("PR-4", 1)])
        ficha = {r["attributes"]["codigo_predio"]: r for r in self.core.records["brecha_ficha"]}
        self.assertEqual(n[("PR-1", 2)]["clave"], f"{ficha['PR-1']['attributes']['clave']}|2")
        self.assertEqual(n[("PR-4", 1)]["clave"], f"{registro['id']}|id:bp-4|1")
        self.assertTrue(all(a["corte"] == registro["id"] for a in n.values()))
        self.assertEqual((n[("PR-1", 2)]["estado"], n[("PR-1", 2)]["area_catastro"]), ("SOLO_CATASTRO", "80"))
        self.assertNotIn("area_rentas", n[("PR-1", 2)])
        self.assertEqual(n[("PR-4", 1)]["area_catastro"], "75.25")
        self.assertIn("niveles: 4, AMBIGUO 1, PAR 1, SOLO_CATASTRO 1, SOLO_RENTAS 1", out)
        self.assertIn("niveles: 4 created, 0 updated, 0 deleted, 0 unchanged", out)
        # cargado_en still goes last, after the niveles
        ultimo = [p for m, p, _, _ in self.core.requests if m in ("POST", "PATCH")][-1]
        self.assertTrue(ultimo.startswith("/api/objects/corte_brecha/records/"), ultimo)
        for dato in ("PR-1", "1-2-3", "120.5", "75.25"):
            self.assertNotIn(dato, out)

    def test_un_corte_sin_la_tabla_o_con_la_tabla_vacia_carga_sin_niveles(self):
        for niveles in (None, []):
            with self.subTest(niveles=niveles):
                code, out, err = self.cli(armar_corte(self, niveles=niveles))
                self.assertEqual(code, 0, err)
                self.assertEqual(self.core.records.get("brecha_nivel_ficha", []), [])
                self.assertIn("niveles: 0\n", out)

    def test_el_dry_run_dice_los_niveles_que_crearia(self):
        code, out, err = self.cli(armar_corte(self, niveles=NIVELES), "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.escrituras(), [])
        self.assertIn("niveles: 4 to create, 0 to update, 0 to delete, 0 unchanged", out)

    def test_la_recarga_del_mismo_corte_no_escribe_nada(self):
        carpeta = armar_corte(self, niveles=NIVELES)
        self.assertEqual(self.cli(carpeta)[0], 0)
        self.core.requests.clear()
        code, out, err = self.cli(carpeta)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.escrituras(), [])
        self.assertIn("niveles: 0 created, 0 updated, 0 deleted, 4 unchanged", out)

    def test_un_corte_ya_cargado_sin_niveles_los_gana_al_recargarlo(self):
        self.assertEqual(self.cli(armar_corte(self))[0], 0)
        code, out, err = self.cli(armar_corte(self, niveles=NIVELES))
        self.assertEqual(code, 0, err)
        self.assertIn("fichas: 0 created, 0 updated, 0 deleted, 5 unchanged", out)
        self.assertEqual(len(self.niveles()), 4)

    def test_un_nivel_que_cambia_se_actualiza_y_uno_que_falta_pide_reemplazar(self):
        self.assertEqual(self.cli(armar_corte(self, niveles=NIVELES))[0], 0)
        cambiados = [nivel(1, 1, 1, "120.5", "130", "PAR")] + NIVELES[1:3]
        self.core.requests.clear()
        code, out, err = self.cli(armar_corte(self, niveles=cambiados))
        self.assertEqual(code, 2)
        self.assertIn("1 niveles del corte guardado ya no vienen en el corte: --reemplazar", err)
        self.assertEqual(self.escrituras(), [])
        code, out, err = self.cli(armar_corte(self, niveles=cambiados), "--reemplazar")
        self.assertEqual(code, 0, err)
        self.assertIn("niveles: 0 created, 1 updated, 1 deleted, 2 unchanged, 1 absent from the corte deleted", out)
        n = self.niveles()
        self.assertEqual(sorted(n), [("PR-1", 1), ("PR-1", 2), ("PR-2", 1)])
        self.assertEqual(n[("PR-1", 1)]["area_catastro"], "130")

    def test_reemplazar_borra_los_niveles_antes_que_su_ficha(self):
        self.assertEqual(self.cli(armar_corte(self, niveles=NIVELES))[0], 0)
        self.core.requests.clear()
        # PR-4 and its AMBIGUO nivel no longer come
        code, out, err = self.cli(armar_corte(self, filas=FILAS[:3] + FILAS[4:], niveles=NIVELES[:3]), "--reemplazar")
        self.assertEqual(code, 0, err)
        borrados = [p.split("/")[3] for m, p, _, _ in self.core.requests if m == "DELETE"]
        self.assertEqual(borrados, ["brecha_nivel_ficha", "brecha_ficha"])
        self.assertEqual(sorted(self.niveles()), [("PR-1", 1), ("PR-1", 2), ("PR-2", 1)])

    def test_un_piso_repetido_en_la_ficha_lleva_la_clave_de_su_fila(self):
        repetidos = [nivel(1, 1, 1, "10", "10", "PAR"), nivel(2, 1, 1, "20", None, "SOLO_RENTAS")]
        code, _, err = self.cli(armar_corte(self, niveles=repetidos))
        self.assertEqual(code, 0, err)
        claves = sorted(r["attributes"]["clave"].split("|", 2)[-1] for r in self.core.records["brecha_nivel_ficha"])
        self.assertEqual(claves, ["id:bn-1", "id:bn-2"])

    def test_un_nivel_que_no_cabe_sale_con_2_sin_escribir(self):
        for malo, mensaje in ((nivel(9, 1, 3, "1", "1", "OTRO"), "estado 'OTRO' no es de estado_nivel"),
                              (nivel(9, 99, 1, "1", "1", "PAR"), "su brecha_predio no es una fila del corte")):
            with self.subTest(mensaje=mensaje):
                self.core.requests.clear()
                code, _, err = self.cli(armar_corte(self, niveles=NIVELES + [malo]))
                self.assertEqual(code, 2)
                self.assertIn(mensaje, err)
                self.assertEqual(self.escrituras(), [])
                self.assertNotIn("bp-99", err)


if __name__ == "__main__":
    unittest.main()
