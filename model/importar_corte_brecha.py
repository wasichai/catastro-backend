#!/usr/bin/env python3
"""Loads a corte analítico of srtm's brecha (srtm-backend docs/informes/brecha) into corte_brecha and brecha_ficha.

A corte is a folder <org>/<fecha>/ with manifiesto.json and one Parquet per table; --corte names the folder, --s3 its
S3 prefix (s3://…/analitica/<org>/<fecha>, copied with `aws s3 cp --recursive` into a temporary folder that is removed
at the end). Before anything is read, every file the manifest lists is checked against its bytes and sha256: one
missing or different, or a manifest without srtm_brecha_corrida.parquet and srtm_brecha_predio.parquet, exits 2.

It reads, with duckdb (requirements-corte.txt, the same pin as the corte's own venv), the corte's brecha_corrida
(the manifest's brecha_corrida.id) and its srtm_brecha_predio rows, and the UIT of the year from srtm_parametro
(tipo UIT, VIGENTE or blank, in force on 1 January of the corrida's year); a corte without it takes --uit, and with
neither supera_5_uit stays empty. Each row is matched to its ficha (predio_catastral) by Brecha.llave() of srtm:
trimmed, upper case, and every run of digits without its leading zeros, so 01-01-0006 is 1-1-6. codigo_catastro is
srtm's code of the catastro item (its código municipal, else its CPU, else sector-manzana-lote), so it is looked up
first among the fichas' codigo_municipal, then among their codigo_cpu, then their sector|manzana|lote; a key two
fichas share matches neither.

The copies for the map view (model/vistas_de_mapa.py) and the WMS layer of brecha_ficha: every ficha gets the estado
of its decision_brecha (codigo_municipal|anio of the corte; PENDIENTE without one), and, when the corte is the most
recent of the organization (by fecha, then clave), the lote_geom of its matched predio_catastral, so the map draws the
fichas without a join. Then the fichas of the other cortes lose their lote_geom (--sin-geometria-anterior, the
default; --con-geometria-anterior keeps it), so the map view shows only the latest corte. A corte loaded after a more
recent one gets no lote at all. These copies leave GET /api/catastro/cambios as it was: it lists only predios,
construcciones, obras and titulares.

Idempotent upsert by clave: corte_brecha by <org>|<fecha>, brecha_ficha by <id of the corte>|<codigo_catastro>
(<id of the corte>|id:<srtm's row id> when the row has no codigo_catastro, or shares it with another row of the
corte). A row Core lacks is created, one that differs is updated (PATCH, a None clears), and an equal corte writes
nothing, not even cargado_en. cargado_en is written last, after every ficha: the API shows only cortes that have it,
so a corte is never seen half loaded (a reload clears it first). Fichas of the stored corte the corte no longer has
stop the load (exit 2, nothing written) unless --reemplazar, which deletes them. Every write carries X-Change-Reason corte-brecha:<org>:<fecha>. Only counts are printed: no
code, no amount of a predio. --org refuses to write unless the account of --email belongs to that organization (its
id, as import_vias.py). --dry-run reads Core and says what it would write, writing nothing.

Run: python3 -I importar_corte_brecha.py (--corte DIR | --s3 s3://…/<org>/<fecha>) [--org <organization id>]
             [--uit 5500] [--reemplazar] [--sin-geometria-anterior | --con-geometria-anterior] [--dry-run]
             [--workers 4]
Exit: 0 ok, 1 Core refused something (only the status and the fields it names are printed), 2 the corte does not fit
      (format, sha256, extra or missing files, row counts, corrida, rows), fichas absent without --reemplazar, duckdb is missing,
      the S3 copy failed or --org is another organization.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

HERE = os.path.dirname(os.path.abspath(__file__))
# under python3 -I (the corte comes from outside) neither the cwd nor the script's directory is on sys.path: put back
# only the latter, for core_client and tabular
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core_client import Client, CoreError  # noqa: E402
from tabular import LoadError, clean_text, load_enums, write_all  # noqa: E402

CORTE, FICHA, PREDIO, DECISION = "corte_brecha", "brecha_ficha", "predio_catastral", "decision_brecha"
# the ficha's copy of its predio's lote (POLYGON, the srid of predio_catastral.lote_geom)
LOTE = "lote_geom"
PENDIENTE = "PENDIENTE"
# a lote Core answers in 4326 after storing it in 32718 never comes back equal: within this it is the same
TOLERANCIA = 1e-6
MANIFIESTO = "manifiesto.json"
# the manifest format srtm writes (herramientas/manifiesto.py FORMATO)
FORMATO = 1
CORRIDA_PARQUET, PREDIO_PARQUET, PARAMETRO_PARQUET = (
    "srtm_brecha_corrida.parquet", "srtm_brecha_predio.parquet", "srtm_parametro.parquet")
MODEL_PATH = os.path.join(HERE, "model.json")
# the S3 CLI; a test points it at a fake
AWS = "aws"
CINCO = Decimal(5)
# ASCII digits only, as Kotlin's \\d in Brecha.llave() (python's \d also takes other scripts' digits)
DIGITOS = re.compile(r"\d+", re.ASCII)

DECIMALES_FICHA = ("autoavaluo_declarado", "autoavaluo_catastro", "delta_autoavaluo", "impuesto_declarado",
                   "impuesto_catastro", "delta_impuesto", "delta_arbitrios")
TEXTOS_FICHA = ("codigo_predio", "confianza_motivo", "sector", "manzana", "lote", "uso", "motivo")
# the columns read (srtm-backend docs/informes/brecha/herramientas/srtm.py): never SELECT *, so a column the corte adds
# later, or its instants (duckdb would need pytz for them), stay out
COLUMNAS_CORRIDA = ("id", "anio", "version_catastro", "declarado", "catastro", "delta_impuesto", "delta_arbitrios",
                    "delta_impuesto_confiable", "delta_impuesto_dudoso", "delta_impuesto_sin_levantar")
COLUMNAS_PREDIO = ("id", "codigo_catastro", "categoria", "confianza", "estimado", "orden") + DECIMALES_FICHA + TEXTOS_FICHA
# the corrida's totals copied as they are; the three by confianza are summed from the rows when the corte predates
# srtm-backend#204 and leaves them empty
TOTALES = ("declarado", "catastro", "delta_impuesto", "delta_arbitrios")
POR_CONFIANZA = {"delta_impuesto_confiable": "CONFIABLE", "delta_impuesto_dudoso": "DUDOSO",
                 "delta_impuesto_sin_levantar": "SIN_LEVANTAR"}


# a published layer keeps the classes of its publish (its SLD is a snapshot): after new data it is published again
RECORDATORIO = ("siguiente paso: python3 -I vistas_de_mapa.py, que vuelve a publicar las capas con las clases de"
                " estos datos (README, «Vistas de mapa»)")


class CorteError(ValueError):
    """The corte does not fit: exit 2, one line, nothing sent."""


# ---- the corte ----

def llave(codigo):
    """srtm's Brecha.llave(): trimmed, upper case, every run of digits without its leading zeros; blank is None."""
    if codigo is None:
        return None
    texto = str(codigo).strip().upper()
    if not texto:
        return None
    return DIGITOS.sub(lambda d: d.group(0).lstrip("0") or "0", texto)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def verificar(carpeta):
    """The manifest of `carpeta`, and its own sha256, once it is of FORMATO, every file it lists is there with its bytes
    and sha256, no other file is, and the two brecha tables are among them; a CorteError naming every problem
    otherwise. The row counts are checked by leer, with duckdb."""
    ruta = os.path.join(carpeta, MANIFIESTO)
    if not os.path.isfile(ruta):
        raise CorteError(f"falta {MANIFIESTO} en {carpeta}")
    try:
        with open(ruta, encoding="utf-8") as f:
            manifiesto = json.load(f)
    except ValueError:
        raise CorteError(f"{MANIFIESTO} ilegible: no es JSON en UTF-8") from None
    archivos = manifiesto.get("archivos") if isinstance(manifiesto, dict) else None
    if not isinstance(archivos, list) or not all(isinstance(a, dict) and "archivo" in a and "sha256" in a
                                                 for a in archivos):
        raise CorteError(f"{MANIFIESTO} sin la lista de archivos con su sha256")
    if manifiesto.get("formato") != FORMATO:
        raise CorteError(f"{MANIFIESTO} de formato {manifiesto.get('formato')!r}: se espera {FORMATO}")
    problemas = []
    listados = {a["archivo"] for a in archivos}
    # as srtm's manifiesto.verificar_corte: a file the manifest does not list is never read
    sobrantes = sorted(set(os.listdir(carpeta)) - listados - {MANIFIESTO})
    if sobrantes:
        problemas.append(f"sobran {', '.join(sobrantes)}")
    for necesario in (CORRIDA_PARQUET, PREDIO_PARQUET):
        if necesario not in listados:
            problemas.append(f"el manifiesto no lista {necesario}")
    for entrada in archivos:
        nombre = os.path.basename(str(entrada["archivo"]))
        archivo = os.path.join(carpeta, nombre)
        if nombre != entrada["archivo"] or not os.path.isfile(archivo):
            problemas.append(f"falta {entrada['archivo']}")
        elif ("bytes" in entrada and os.path.getsize(archivo) != entrada["bytes"]) or sha256(archivo) != entrada["sha256"]:
            problemas.append(f"{nombre} no coincide con su sha256")
    if problemas:
        raise CorteError("el corte no coincide con su manifiesto: " + "; ".join(problemas))
    return manifiesto, sha256(ruta)


def _duckdb():
    try:
        import duckdb
    except ImportError:
        raise CorteError("falta duckdb: python3 -m pip install -r model/requirements-corte.txt") from None
    return duckdb


def _filas(con, archivo, sql, parametros=()):
    cursor = con.execute(sql.format(tabla="read_parquet(?)"), [archivo, *parametros])
    columnas = [d[0] for d in cursor.description]
    return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]


def _vigente(parametro, primero_enero):
    if parametro.get("estado") not in (None, "", "VIGENTE") or parametro.get("valor_numerico") is None:
        return False
    desde, hasta = parametro.get("vigencia_desde"), parametro.get("vigencia_hasta")
    return (desde is None or desde <= primero_enero) and (hasta is None or hasta >= primero_enero)


def leer(carpeta, manifiesto):
    """(corrida, rows, uit or None) of the corte: the manifest's brecha_corrida and its rows of srtm_brecha_predio."""
    elegida = manifiesto.get("brecha_corrida")
    if not isinstance(elegida, dict) or not elegida.get("id"):
        raise CorteError("el corte no trae brecha_corrida: srtm no tenía una corrida TERMINADA ese año")
    duckdb = _duckdb()
    con = duckdb.connect()
    try:
        distintos = [e["archivo"] for e in manifiesto["archivos"] if "filas" in e and e["archivo"].endswith(".parquet")
                     and con.execute("SELECT count(*) FROM read_parquet(?)", [os.path.join(carpeta, e["archivo"])])
                     .fetchone()[0] != e["filas"]]
        if distintos:
            raise CorteError(f"el corte no coincide con su manifiesto: filas de {', '.join(distintos)}")
        corridas = _filas(con, os.path.join(carpeta, CORRIDA_PARQUET),
                          f"SELECT {', '.join(COLUMNAS_CORRIDA)} FROM {{tabla}} WHERE id = ?", [elegida["id"]])
        if len(corridas) != 1:
            raise CorteError(f"{CORRIDA_PARQUET} no trae la corrida {elegida['id']} del manifiesto")
        filas = _filas(con, os.path.join(carpeta, PREDIO_PARQUET),
                       f"SELECT {', '.join(COLUMNAS_PREDIO)} FROM {{tabla}} WHERE corrida = ? ORDER BY orden, id",
                       [elegida["id"]])
        uit = None
        anio = corridas[0].get("anio") or manifiesto.get("anio")
        parametros = os.path.join(carpeta, PARAMETRO_PARQUET)
        listado = any(e["archivo"] == PARAMETRO_PARQUET for e in manifiesto["archivos"])
        if anio is not None and listado and os.path.isfile(parametros):
            primero_enero = date(int(anio), 1, 1)
            uits = [p for p in _filas(con, parametros, "SELECT vigencia_desde, vigencia_hasta, valor_numerico, estado"
                                                       " FROM {tabla} WHERE tipo = 'UIT'")
                    if _vigente(p, primero_enero)]
            if uits:
                uit = Decimal(max(uits, key=lambda p: p.get("vigencia_desde") or date.min)["valor_numerico"])
    except duckdb.Error as e:
        raise CorteError(f"no se pudo leer el corte con duckdb: {e}") from None
    finally:
        con.close()
    return corridas[0], filas, uit


def descargar(uri, destino):
    """`aws s3 cp --recursive uri destino`; a CorteError when it fails."""
    if not uri.startswith("s3://"):
        raise CorteError(f"--s3 {uri}: se espera s3://…/<org>/<fecha>")
    try:
        resultado = subprocess.run([AWS, "s3", "cp", "--recursive", "--only-show-errors", uri.rstrip("/") + "/", destino],
                                   capture_output=True, text=True, check=False)
    except OSError as e:
        raise CorteError(f"no se pudo correr {AWS}: {e}") from None
    if resultado.returncode != 0:
        raise CorteError(f"aws s3 cp {uri} salió con {resultado.returncode}: {resultado.stderr.strip()[:300]}")


# ---- the plan ----

def _decimal(valor):
    if valor is None:
        return None
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        return None
    return numero if numero.is_finite() else None


def _texto_decimal(numero):
    """A Decimal as Core takes it: plain text without trailing zeros (12.50 as 12.5, 100 as 100)."""
    if numero is None:
        return None
    texto = format(numero.normalize(), "f")
    return "0" if texto in ("-0", "") else texto


def indice_de_fichas(predios):
    """llave -> codigo_municipal, by codigo_municipal, by codigo_cpu and by sector-manzana-lote, in that order of
    strength. Each layer is built over every ficha, also those without codigo_municipal: srtm writes a CPU or an S-M-L
    as codigo_catastro only for an item without one, so a key shared with a ficha that has no codigo_municipal is that
    ficha's, and matching it to another one would put the row on the wrong predio. A key with two owners, or with an
    owner without codigo_municipal, matches nothing (and the ones with two or more owners are counted)."""
    capas, ambiguas = [], 0
    for clave_de in (lambda a: llave(a.get("codigo_municipal")),
                     lambda a: llave(a.get("codigo_cpu")),
                     lambda a: _sml(a)):
        duenos = {}
        for predio in predios:
            atributos = predio.get("attributes") or {}
            clave = clave_de(atributos)
            if clave is None:
                continue
            codigo = atributos.get("codigo_municipal")
            duenos.setdefault(clave, set()).add(codigo if codigo is not None else ("sin codigo", predio.get("id")))
        ambiguas += sum(1 for d in duenos.values() if len(d) > 1)
        capas.append({clave: next(iter(d)) for clave, d in duenos.items() if len(d) == 1 and isinstance(next(iter(d)), str)})
    return capas, ambiguas


def _sml(atributos):
    partes = [llave(atributos.get(c)) for c in ("sector", "manzana", "lote")]
    return None if any(p is None for p in partes) else "-".join(partes)


def empatar(codigo_catastro, capas):
    clave = llave(codigo_catastro)
    if clave is None:
        return None
    for capa in capas:
        if clave in capa:
            return capa[clave]
    return None


def lotes_de(predios):
    """codigo_municipal -> the lote (a GeoJSON Polygon in 4326) of every predio that has both."""
    lotes = {}
    for predio in predios:
        codigo = (predio.get("attributes") or {}).get("codigo_municipal")
        lote = (predio.get("geometries") or {}).get(LOTE)
        if codigo is not None and lote:
            lotes[codigo] = lote
    return lotes


def estados_de(decisiones):
    """codigo_municipal -> the estado of its decision_brecha (those of one year)."""
    return {a.get("codigo_municipal"): a.get("estado") for a in ((d.get("attributes") or {}) for d in decisiones)
            if a.get("codigo_municipal") and a.get("estado")}


def mismo_lote(a, b, tolerancia=TOLERANCIA):
    """Whether two Polygon geometries (or two absent ones) are the same: same rings, same vertices within
    `tolerancia` degrees."""
    if not a or not b:
        return not a and not b
    if a.get("type") != b.get("type"):
        return False
    anillos_a, anillos_b = a.get("coordinates") or [], b.get("coordinates") or []
    if len(anillos_a) != len(anillos_b) or any(len(p) != len(q) for p, q in zip(anillos_a, anillos_b)):
        return False
    return all(abs(xa - xb) <= tolerancia and abs(ya - yb) <= tolerancia
               for p, q in zip(anillos_a, anillos_b) for (xa, ya, *_), (xb, yb, *_) in zip(p, q))


def es_el_mas_reciente(corte, cortes):
    """Whether no other stored corte is more recent than `corte` by (fecha, clave), the API's order."""
    propio = (str(corte["fecha"]), corte["clave"])
    otros = ((str(a.get("fecha")), a.get("clave")) for a in ((c.get("attributes") or {}) for c in cortes)
             if a.get("clave") != corte["clave"])
    return all(otro < propio for otro in otros)


def fichas(filas, corte_id, capas, uit, enums, estados=None):
    """The brecha_ficha attributes of every row, and the problems that keep them out (an unknown categoria).
    `estados`: codigo_municipal -> the estado of its decision of the corte's year (PENDIENTE without one)."""
    problemas = []
    repetidos = Counter(clean_text(f.get("codigo_catastro")) for f in filas)
    resultado = []
    for n, fila in enumerate(filas, start=1):
        codigo_catastro = clean_text(fila.get("codigo_catastro"))
        categoria, confianza = clean_text(fila.get("categoria")), clean_text(fila.get("confianza"))
        if categoria not in enums["categoria_brecha"]:
            problemas.append(f"fila {n}: categoria '{categoria}' no es de categoria_brecha")
            continue
        if confianza is not None and confianza not in enums["confianza_brecha"]:
            problemas.append(f"fila {n}: confianza '{confianza}' no es de confianza_brecha")
            continue
        sufijo = codigo_catastro if codigo_catastro and repetidos[codigo_catastro] == 1 else f"id:{fila.get('id')}"
        decimales = {c: _decimal(fila.get(c)) for c in DECIMALES_FICHA}
        delta = decimales["delta_autoavaluo"]
        atributos = {
            "clave": f"{corte_id}|{sufijo}",
            "corte": corte_id,
            "codigo_catastro": codigo_catastro,
            "codigo_municipal": empatar(codigo_catastro, capas),
            "categoria": categoria,
            "confianza": confianza,
            **{c: clean_text(fila.get(c)) for c in TEXTOS_FICHA},
            **{c: _texto_decimal(v) for c, v in decimales.items()},
            "estimado": None if fila.get("estimado") is None else bool(fila.get("estimado")),
            "supera_5_uit": None if uit is None or delta is None else abs(delta) > CINCO * uit,
        }
        atributos["estado"] = (estados or {}).get(atributos["codigo_municipal"]) or PENDIENTE
        resultado.append(atributos)
    return resultado, problemas


def _suma(valores):
    return sum((v for v in valores if v is not None), Decimal(0))


def atributos_del_corte(manifiesto, sha, corrida, filas):
    org, fecha = manifiesto.get("organizacion"), manifiesto.get("fecha_corte")
    if not org or not fecha:
        raise CorteError(f"{MANIFIESTO} sin organizacion o fecha_corte")
    anio = corrida.get("anio") or manifiesto.get("anio")
    deltas = [(clean_text(f.get("confianza")), clean_text(f.get("categoria")), _decimal(f.get("delta_impuesto")))
              for f in filas]
    atributos = {
        "clave": f"{org}|{fecha}",
        "org_slug": org,
        "fecha": fecha,
        "corrida": str(corrida["id"]),
        "anio": int(anio),
        "manifiesto_sha256": sha,
        "version_srtm": ((manifiesto.get("backends") or {}).get("srtm") or {}).get("version"),
        "version_catastro": corrida.get("version_catastro")
        or (manifiesto.get("brecha_corrida") or {}).get("version_catastro"),
        "total_fichas": len(filas),
        **{c: _texto_decimal(_decimal(corrida.get(c))) for c in TOTALES},
        "omisos_estimado": _texto_decimal(_suma(d for _, categoria, d in deltas if categoria == "OMISO")),
    }
    for campo, confianza in POR_CONFIANZA.items():
        valor = _decimal(corrida.get(campo))
        if valor is None:
            valor = _suma(d for c, _, d in deltas if c == confianza)
        atributos[campo] = _texto_decimal(valor)
    return atributos


# the fields compared as numbers: Core answers a DECIMAL as a JSON number, never as the text that was sent
NUMERICOS = frozenset(DECIMALES_FICHA + TOTALES + tuple(POR_CONFIANZA) + ("omisos_estimado", "anio", "total_fichas"))


def _igual(campo, nuevo, guardado):
    if nuevo is None or guardado is None:
        return nuevo is None and guardado is None
    if isinstance(nuevo, bool) or isinstance(guardado, bool):
        return nuevo is guardado
    if campo in NUMERICOS:
        return _decimal(nuevo) == _decimal(guardado)
    return str(nuevo) == str(guardado)


def cambios(nuevo, guardado):
    """The attributes of `nuevo` that differ from the stored record's (a None clears a stored value)."""
    return {k: v for k, v in nuevo.items() if not _igual(k, v, guardado.get(k))}


def plan_fichas(filas, existentes, reemplazar, lotes=None):
    """create [(n, attributes, geometries)], update [(id, n, changed attributes, geometries or None)], unchanged,
    absent (stored fichas the corte no longer has), the deletes (absent ones with --reemplazar). `lotes`: the lote of
    each of `filas`, in their order (None: none); a stored lote that differs is replaced, or cleared."""
    por_clave = {(r.get("attributes") or {}).get("clave"): r for r in existentes}
    crear, actualizar, iguales = [], [], 0
    for n, atributos in enumerate(filas, start=1):
        lote = lotes[n - 1] if lotes is not None else None
        record = por_clave.get(atributos["clave"])
        if record is None:
            crear.append((n, atributos, {LOTE: lote}))
            continue
        diferencia = cambios(atributos, record.get("attributes") or {})
        geometrias = None if mismo_lote(lote, (record.get("geometries") or {}).get(LOTE)) else {LOTE: lote}
        if diferencia or geometrias:
            actualizar.append((record["id"], n, diferencia, geometrias))
        else:
            iguales += 1
    claves = {a["clave"] for a in filas}
    ausentes = [r for c, r in por_clave.items() if c not in claves]
    return {"create": crear, "update": actualizar, "unchanged": iguales, "absent": ausentes,
            "delete": ausentes if reemplazar else []}


# ---- main ----

def _parse_args(argv):
    p = argparse.ArgumentParser(description="Load a corte analítico of srtm's brecha into corte_brecha and brecha_ficha.")
    fuente = p.add_mutually_exclusive_group(required=True)
    fuente.add_argument("--corte", help="the corte's folder <org>/<fecha>, with manifiesto.json and the Parquet")
    fuente.add_argument("--s3", help="the corte's S3 prefix, s3://…/analitica/<org>/<fecha>")
    p.add_argument("--org", help="the organization id the account must belong to, or nothing is written")
    p.add_argument("--uit", help="the UIT of the year (S/), when the corte does not bring it in srtm_parametro")
    p.add_argument("--reemplazar", action="store_true", help="delete the fichas of the corte the corte no longer has")
    anterior = p.add_mutually_exclusive_group()
    anterior.add_argument("--sin-geometria-anterior", dest="sin_geometria_anterior", action="store_true", default=True,
                          help="clear lote_geom on the fichas of the other cortes (the default): the map shows one corte")
    anterior.add_argument("--con-geometria-anterior", dest="sin_geometria_anterior", action="store_false",
                          help="leave lote_geom on the fichas of the other cortes")
    p.add_argument("--core", default=os.environ.get("WASICHAI_CORE", "http://localhost:8091"))
    p.add_argument("--email", default=os.environ.get("WASICHAI_EMAIL", "admin@wasichai.local"))
    p.add_argument("--password", default=os.environ.get("WASICHAI_PASSWORD", "admin"))
    p.add_argument("--dry-run", action="store_true", help="read Core and say what would change; write nothing")
    p.add_argument("--workers", type=int, default=4, help="parallel writes (default 4)")
    return p.parse_args(argv)


def _ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _report(fichas_, uit, ambiguas):
    por_categoria = Counter(f["categoria"] for f in fichas_)
    con_codigo = [f for f in fichas_ if f["codigo_catastro"]]
    empatadas = sum(1 for f in con_codigo if f["codigo_municipal"])
    print(f"filas: {len(fichas_)}")
    print("por categoria: " + ", ".join(f"{k} {por_categoria[k]}" for k in sorted(por_categoria)))
    print(f"empatadas con ficha: {empatadas}")
    print(f"sin ficha: {len(con_codigo) - empatadas} con codigo_catastro, {len(fichas_) - len(con_codigo)} sin codigo")
    print(f"llaves de fichas repetidas (no empatan): {ambiguas}")
    print(f"supera 5 UIT: {sum(1 for f in fichas_ if f['supera_5_uit'])}" + ("" if uit is not None else " (sin UIT)"))


def cargar(args, carpeta):
    manifiesto, sha = verificar(carpeta)
    corrida, filas, uit = leer(carpeta, manifiesto)
    if uit is None and args.uit is not None:
        uit = _decimal(args.uit)
        if uit is None or uit <= 0:
            raise CorteError(f"--uit {args.uit}: se espera un número positivo")
    corte = atributos_del_corte(manifiesto, sha, corrida, filas)
    enums = load_enums(MODEL_PATH)
    razon = f"corte-brecha:{corte['org_slug']}:{corte['fecha']}"[:64]

    client = Client(args.core)
    client.login(args.email, args.password)
    organization = (client.user or {}).get("organizationId")
    if args.org is not None and organization != args.org:
        raise CorteError(f"--org expects the organization's id, and the account {args.email} is of the organization"
                         f" {organization or '(Core did not say)'}, not {args.org}; nothing was written")
    predios = client.list_all(PREDIO)
    capas, ambiguas = indice_de_fichas(predios)
    cortes = client.list_all(CORTE)
    guardado = next((c for c in cortes if (c.get("attributes") or {}).get("clave") == corte["clave"]), None)
    corte_id = guardado["id"] if guardado else "<corte nuevo>"
    estados = estados_de(client.list_all(DECISION, anio=corte["anio"]))
    nuevas, problemas = fichas(filas, corte_id, capas, uit, enums, estados)
    if problemas:
        for problema in problemas:
            print(f"problem: {problema}", file=sys.stderr)
        raise CorteError(f"{len(problemas)} filas no caben en el modelo: nothing was sent to Core")
    _report(nuevas, uit, ambiguas)
    existentes = client.list_all(FICHA, corte=guardado["id"]) if guardado else []
    # the lotes go only on the most recent corte: the map view and the WMS layer draw one corte
    reciente = es_el_mas_reciente(corte, cortes)
    lotes = lotes_de(predios) if reciente else {}
    con_lote = [lotes.get(f["codigo_municipal"]) for f in nuevas]
    todo = plan_fichas(nuevas, existentes, args.reemplazar, con_lote)
    # the fichas of the other cortes that still carry a lote
    anteriores = ([r for c in cortes if c["id"] != corte_id for r in client.list_all(FICHA, corte=c["id"])
                   if (r.get("geometries") or {}).get(LOTE)]
                  if reciente and args.sin_geometria_anterior else [])
    cambio_corte = cambios(corte, guardado.get("attributes") or {}) if guardado else corte
    # a corte without cargado_en is one a load left half done: it is finished even if nothing else changed
    a_medias = guardado is not None and not (guardado.get("attributes") or {}).get("cargado_en")
    escribe = bool(cambio_corte or todo["create"] or todo["update"] or todo["delete"] or a_medias)
    accion = "create" if guardado is None else ("update" if escribe else "unchanged")
    resumen = (f"corte {corte['clave']}: {accion}; fichas: {len(todo['create'])} {{create}}, {len(todo['update'])}"
               f" {{update}}, {len(todo['delete'])} {{delete}}, {todo['unchanged']} unchanged, "
               + (f"{len(todo['absent'])} absent from the corte deleted" if args.reemplazar
                  else f"{len(todo['absent'])} absent from the corte kept (--reemplazar deletes them)"))
    if todo["absent"] and not args.reemplazar:
        # the same org|fecha is the same corte: fichas it no longer has would stay in the panel and its total would
        # not add up, so nothing is written until --reemplazar says to delete them
        print(resumen.format(create="to create", update="to update", delete="to delete"))
        raise CorteError(f"{len(todo['absent'])} fichas del corte guardado ya no vienen en el corte: --reemplazar las"
                         " borra; nothing was written")
    lotes_resumen = (f"lotes: {sum(1 for g in con_lote if g)} fichas del corte con lote"
                     + ("" if reciente else " (hay un corte más reciente: este no lleva lotes)")
                     + f"; {len(anteriores)} fichas de cortes anteriores con lote {{clear}}")
    if args.dry_run:
        print(resumen.format(create="to create", update="to update", delete="to delete"))
        print(lotes_resumen.format(clear="to clear"))
        return
    if escribe:
        # cargado_en goes last, after every ficha: until then the API does not show the corte, so a reader never sees
        # it half loaded, and a load that fails half way leaves it hidden (the next run finishes it)
        if guardado is None:
            corte_id = write_all(client, [("corte", 0, "POST", CORTE, None, cambio_corte)], 1, razon)["corte"]
            for atributos in nuevas:
                atributos["corte"] = corte_id
                atributos["clave"] = atributos["clave"].replace("<corte nuevo>", corte_id, 1)
        else:
            write_all(client, [("corte", 0, "PATCH", CORTE, corte_id, {**cambio_corte, "cargado_en": None})], 1, razon)
        ops = ([(n, n, "POST", FICHA, None, a, g) for n, a, g in todo["create"]]
               + [(n, n, "PATCH", FICHA, i, a, g) for i, n, a, g in todo["update"]]
               + [(f"d{r['id']}", 0, "DELETE", FICHA, r["id"], None) for r in todo["delete"]])
        write_all(client, ops, args.workers, razon)
        write_all(client, [("corte", 0, "PATCH", CORTE, corte_id, {"cargado_en": _ahora()})], 1, razon)
    # after the corte shows: the map is never left without a corte
    write_all(client, [(r["id"], 0, "PATCH", FICHA, r["id"], {}, {LOTE: None}) for r in anteriores], args.workers, razon)
    print("done: " + resumen.format(create="created", update="updated", delete="deleted"))
    print(lotes_resumen.format(clear="cleared"))
    print(RECORDATORIO)


def _campos(cuerpo):
    """Only the fields Core's refusal names, never its message: it may echo a value of the row (only counts leave)."""
    try:
        errores = json.loads(cuerpo).get("errors") or []
        nombres = sorted({str(e.get("field")) for e in errores if isinstance(e, dict) and e.get("field")})
    except (ValueError, AttributeError, TypeError):
        nombres = []
    return f" (campos: {', '.join(nombres)})" if nombres else ""


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    temporal = None
    try:
        carpeta = args.corte
        if args.s3:
            temporal = tempfile.mkdtemp(prefix="corte-brecha-")
            descargar(args.s3, temporal)
            carpeta = temporal
        cargar(args, carpeta)
    except CorteError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except LoadError as e:
        print(f"error /api/objects/{e.object_name}/records (row {e.fila}) -> {e.error.status}{_campos(e.error.body)}",
              file=sys.stderr)
        return 1
    except CoreError as e:
        print(f"error -> {e.status}{_campos(e.body)}", file=sys.stderr)
        return 1
    finally:
        if temporal:
            shutil.rmtree(temporal, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
