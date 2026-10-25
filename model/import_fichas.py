#!/usr/bin/env python3
"""Loads the catastro levantamiento's fichas into predio_catastral, construccion, obra_complementaria and
titular_catastral.

Four inputs, csv or xlsx (the stdlib reader of import_predios.py in srtm-backend); the header is matched
case-insensitively and lines starting with # are skipped:
  --fichas     one row per predio (predio_catastral)
  --pisos      one row per piso of a predio (construccion), linked to its ficha by codigo_municipal
  --obras      one row per obra complementaria (obra_complementaria), same link. Optional.
  --titulares  one row per titular of a predio (titular_catastral), same link. Optional. Datos personales (Ley
               29733): no title, document or name ever reaches stdout or stderr, only codigo_municipal and the row.

Default columns follow the MEF carga masiva contract (kamayuk ContratoDeImportacion, docs/40-datos/mapeo-del-modelo-del-mef.md):
  fichas: cod_pre -> codigo_municipal, cod_cpu, cod_sect -> sector, cod_mzn -> manzana, cod_lote -> lote, id_aranc,
          cod_via, cuadra, lado, uso, area_terreno, longitud_frente, anio_levantamiento, es_edificio, and the
          levantamiento's own estado_levantamiento (the model's enum) and fecha_levantamiento (YYYY-MM-DD or an
          xlsx serial day number). Four more optional columns for the vínculo with rentas and the SNIC codes (Ley
          28294): vinculo_metodo (the model's enum), vinculo_revisado (SI/NO), cuc and codigo_referencia_catastral
  pisos:  cod_pre -> codigo_municipal, piso, area_construida, anio_construccion, material, estado_conservacion, and
          the seven categories either as one 7-letter text in `categorias` (e.g. CCDCCDC, in the order muros_columnas,
          techos, pisos, puertas_ventanas, revestimientos, banos, instalaciones) or in seven columns named as the fields,
          and optionally techo_incluido (SI/NO, S/N, TRUE/FALSE, 1/0; empty = not sent): the muros D are drywall that
          includes the techo (llamada 5 of every regional cuadro, Anexos I.1-I.4), so the valuation leaves the techos
          category out. Two more optional columns: clasificacion, the RNT depreciation table of that construction (an
          option of the model's enum clasificacion, srtm's same four, or the table number 1-4; empty = the predio's
          uso table, not sent), and seccion, an integer >= 1 for the parts of one piso that differ (empty = 1, not
          sent); the piso stays the floor number, so the edificio increment still reaches it
  obras:  cod_pre -> codigo_municipal, codigo_vu (TIPO DE OBRA|numero, as obra_categoria in srtm), cantidad,
          anio_construccion, material, estado_conservacion
  titulares: cod_pre -> codigo_municipal, tipo_documento, numero_documento (as it comes), nombre, porcentaje,
          condicion. A filler document (000000000, RELLENO = ^0+$ only) is sent empty and reported by codigo and row,
          never the value. A titular's key is (predio, numero_documento or "", nombre collapsed and upper-cased); a
          key repeated in the file loads once and is a warning, not an error. A predio whose titulares' porcentaje
          (as the file brings them, before the repeated-key collapse) sum to other than 100% ± 0.01 is reported by
          codigo, unless every one of its titulares lacks porcentaje.
--map, --map-pisos, --map-obras and --map-titulares field=column override those defaults (repeatable). material and
estado_conservacion take the model's options in any case, with _ for a space (MUY_BUENO).

Without --entrega it only creates. Idempotent by codigo_municipal: a predio Core already has is skipped. Pisos, obras
and titulares are idempotent by their own key, (predio, piso, seccion), (predio, codigo_vu, anio_construccion) and
(predio, numero_documento or "", nombre), a piso without seccion being seccion 1: only the ones Core lacks are
created, so a run that failed half way is completed by running again. A key repeated in the file is an error for
pisos and obras, a warning for titulares (see above).

With --entrega CODIGO (plus --fecha-corte and --fuente; README «Entregas», ADR-013) it is an upsert: every ficha is
reported as alta, cambio (campo antes → después), sin cambio or ausente, and only what changed is written, through the
API with the code as X-Change-Reason; the entrega_catastral record is created by the first run that writes. --pisos
becomes optional; --reemplazar-pisos / --reemplazar-obras delete the children the entrega no longer brings in the fichas
it brings. Ausentes are never deleted; neither is a titular ever deleted, with or without --entrega, and a changed
titular's tipo_documento, porcentaje or condicion is reported only by codigo, row and field name, never a value.
--dry-run then logs in and reads Core to report, and writes nothing.

Exit: 0 ok (titulares' warnings included), 1 Core refused something, 2 the files or flags do not fit (every bad row is
listed, nothing is sent), or the entrega's code already names other files.

Run: python3 -I import_fichas.py --fichas fichas.csv --pisos pisos.csv [--obras obras.csv] [--titulares titulares.csv] [--dry-run]
     python3 -I import_fichas.py --fichas fichas.csv [--pisos pisos.csv] [--obras obras.csv] [--titulares titulares.csv]
             --entrega E-2026-10 --fecha-corte 2026-10-01 --fuente BARRIDO [--reemplazar-pisos] [--reemplazar-obras] [--dry-run]
"""
import argparse
import datetime
import os
import re
import sys
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
# under python3 -I (the files it reads are untrusted) neither the cwd nor the script's directory is on sys.path: put
# back only the latter, for core_client and tabular
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core_client import Client, CoreError  # noqa: E402
from entregas import (TITULAR, EntregaError, Present, apply_plan, check_codigo, check_same_files,  # noqa: E402
                      ensure_entrega, field_types, find_entrega, obra_key, piso_key, plan_entrega, read_core,
                      relation_id, sha256_of, titular_key)
from tabular import (INPUT_ERRORS, LoadError, clean_text, code_text, column_for, enum_option, load_enums,  # noqa: E402
                     missing_columns, parse_decimal, parse_int, parse_map, post_all, read_table, report_problems)

CATEGORIAS = ["muros_columnas", "techos", "pisos", "puertas_ventanas", "revestimientos", "banos", "instalaciones"]

FICHA_COLUMNS = {
    "codigo_municipal": "cod_pre", "codigo_cpu": "cod_cpu", "sector": "cod_sect", "manzana": "cod_mzn", "lote": "cod_lote",
    "id_aranc": "id_aranc", "cod_via": "cod_via", "cuadra": "cuadra", "lado": "lado", "uso": "uso",
    "area_terreno": "area_terreno", "longitud_frente": "longitud_frente", "anio_levantamiento": "anio_levantamiento",
    "es_edificio": "es_edificio", "estado_levantamiento": "estado_levantamiento", "fecha_levantamiento": "fecha_levantamiento",
    "vinculo_metodo": "vinculo_metodo", "vinculo_revisado": "vinculo_revisado", "cuc": "cuc",
    "codigo_referencia_catastral": "codigo_referencia_catastral",
}
FICHA_TEXT = ["codigo_cpu", "sector", "manzana", "lote", "id_aranc", "cod_via", "cuadra", "lado", "uso", "cuc",
             "codigo_referencia_catastral"]
FICHA_DECIMAL = ["area_terreno", "longitud_frente"]

PISO_COLUMNS = {
    "codigo_municipal": "cod_pre", "piso": "piso", "area_construida": "area_construida",
    "anio_construccion": "anio_construccion", "material": "material", "estado_conservacion": "estado_conservacion",
    "categorias": "categorias", **{c: c for c in CATEGORIAS}, "techo_incluido": "techo_incluido",
    "clasificacion": "clasificacion", "seccion": "seccion",
}
OBRA_COLUMNS = {
    "codigo_municipal": "cod_pre", "codigo_vu": "codigo_vu", "cantidad": "cantidad",
    "anio_construccion": "anio_construccion", "material": "material", "estado_conservacion": "estado_conservacion",
}
TITULAR_COLUMNS = {
    "codigo_municipal": "cod_pre", "tipo_documento": "tipo_documento", "numero_documento": "numero_documento",
    "nombre": "nombre", "porcentaje": "porcentaje", "condicion": "condicion",
}

TRUE = {"true", "t", "si", "sí", "s", "yes", "y", "1", "x"}
FALSE = {"false", "f", "no", "n", "0"}
CATEGORIA = re.compile(r"[A-J]")
# a filler document, like Ica's 000000000: sent empty and reported (Ley 29733); 99999999 is not one
RELLENO = re.compile(r"0+")
# the RNT's table number (1-4 or 01-04): model.json lists the enum clasificacion in the order of the tables, which
# test_model.py pins and Valorizacion.TABLA_POR_CLASIFICACION checks against the same file
TABLA_RNT = re.compile(r"0?([1-4])")
# an xlsx serial day number, integer or as the float text an xlsx cell sends (46000.0)
SERIAL_DAYS = re.compile(r"\d+(\.0+)?")
XLSX_EPOCH = datetime.date(1899, 12, 30)
# the only shape fromisoformat may see: Python 3.11+ also accepts "20260930" or "2026-W01-2", which are not one of
# the two documented forms (contexto-comun.md)
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_bool(value):
    text = clean_text(value)
    if text is None:
        return None, None
    if text.lower() in TRUE:
        return True, None
    if text.lower() in FALSE:
        return False, None
    return None, f"'{text}' is not a yes/no"


def parse_clasificacion(value, options):
    """(option, error): an option of the enum clasificacion, or the number of its RNT table (an xlsx 3.0 is 3)."""
    text = code_text(value)
    if text is None:
        return None, None
    if not options:
        return None, f"'{text}': the model file (--model) has no enum clasificacion"
    tabla = TABLA_RNT.fullmatch(text)
    if tabla:
        return options[int(tabla.group(1)) - 1], None
    option, error = enum_option(text, options)
    if error:
        return None, f"'{text}' is neither an RNT table 1-4 nor one of {', '.join(options)}"
    return option, None


def parse_date(value):
    """(iso text, error). YYYY-MM-DD, or an xlsx serial day number (integer, or N.0 as an xlsx cell sends it),
    counted as days after 1899-12-30. Anything else is a problem (contexto-comun.md)."""
    text = clean_text(value)
    if text is None:
        return None, None
    if ISO_DATE.fullmatch(text):
        try:
            return datetime.date.fromisoformat(text).isoformat(), None
        except ValueError:
            return None, f"'{text}' is not a date (YYYY-MM-DD or an xlsx serial)"
    if SERIAL_DAYS.fullmatch(text):
        serial = int(text.split(".")[0])
        return (XLSX_EPOCH + datetime.timedelta(days=serial)).isoformat(), None
    return None, f"'{text}' is not a date (YYYY-MM-DD or an xlsx serial)"


def parse_seccion(value):
    seccion, error = parse_int(value)
    if error is None and seccion is not None and seccion < 1:
        return None, f"'{seccion}' is not 1 or more"
    return seccion, error


def _where(row):
    return f"row {row['_fila']}"


def fichas_from(rows, mapping, enums):
    """(fichas, problems). A ficha is (row number, attributes)."""
    problems = missing_columns(rows, mapping, ["codigo_municipal"])
    if problems:
        return [], problems
    fichas, seen = [], {}
    for row in rows:
        where, found = _where(row), []
        codigo = code_text(column_for(row, mapping, "codigo_municipal"))
        if not codigo:
            problems.append(f"fichas {where}: no codigo_municipal (column {mapping['codigo_municipal']})")
            continue
        if codigo in seen:
            problems.append(f"fichas {where} ({codigo}): codigo_municipal repeated, first at row {seen[codigo]}")
            continue
        seen[codigo] = row["_fila"]
        attributes = {"codigo_municipal": codigo}
        for field in FICHA_TEXT:
            attributes[field] = code_text(column_for(row, mapping, field))
        for field in FICHA_DECIMAL:
            attributes[field], error = parse_decimal(column_for(row, mapping, field))
            if error:
                found.append(f"{field} {error}")
        attributes["anio_levantamiento"], error = parse_int(column_for(row, mapping, "anio_levantamiento"))
        if error:
            found.append(f"anio_levantamiento {error}")
        attributes["es_edificio"], error = parse_bool(column_for(row, mapping, "es_edificio"))
        if error:
            found.append(f"es_edificio {error}")
        attributes["estado_levantamiento"], error = enum_option(column_for(row, mapping, "estado_levantamiento"),
                                                                 enums["estado_levantamiento"])
        if error:
            found.append(f"estado_levantamiento {error}")
        attributes["fecha_levantamiento"], error = parse_date(column_for(row, mapping, "fecha_levantamiento"))
        if error:
            found.append(f"fecha_levantamiento {error}")
        attributes["vinculo_metodo"], error = enum_option(column_for(row, mapping, "vinculo_metodo"), enums["vinculo_metodo"])
        if error:
            found.append(f"vinculo_metodo {error}")
        attributes["vinculo_revisado"], error = parse_bool(column_for(row, mapping, "vinculo_revisado"))
        if error:
            found.append(f"vinculo_revisado {error}")
        problems.extend(f"fichas {where} ({codigo}): {f}" for f in found)
        fichas.append((row["_fila"], attributes))
    return fichas, problems


def present_fields(rows, mapping, fields):
    """The fields whose mapped column is in the header (`rows[0]`); empty set when there are no rows. Used to
    compare only the columns a file brings (the entrega diff of Task 4)."""
    if not rows:
        return set()
    return {field for field in fields if mapping[field].lower() in rows[0]}


def categorias_of(row, mapping):
    """(seven letters by field, error). The 7-letter text wins over the seven columns."""
    text = clean_text(column_for(row, mapping, "categorias"))
    if text is not None:
        letters = text.upper().replace(" ", "")
        if len(letters) != 7 or not all(CATEGORIA.fullmatch(c) for c in letters):
            return {}, f"categorias '{text}' is not 7 letters A-J"
        return dict(zip(CATEGORIAS, letters)), None
    result, errors = {}, []
    for field in CATEGORIAS:
        value = clean_text(column_for(row, mapping, field))
        if value is None:
            result[field] = None
        elif not CATEGORIA.fullmatch(value.upper()):
            errors.append(f"{field} '{value}' is not a letter A-J")
        else:
            result[field] = value.upper()
    return result, "; ".join(errors) or None


def _material_estado(row, mapping, enums, found):
    out = {}
    for field in ("material", "estado_conservacion"):
        out[field], error = enum_option(column_for(row, mapping, field), enums[field])
        if error:
            found.append(f"{field} {error}")
    out["anio_construccion"], error = parse_int(column_for(row, mapping, "anio_construccion"))
    if error:
        found.append(f"anio_construccion {error}")
    return out


def pisos_from(rows, mapping, enums, codigos):
    """(pisos, problems). A piso is (row number, codigo_municipal, attributes); `codigos` are the fichas' codes."""
    problems = missing_columns(rows, mapping, ["codigo_municipal", "piso"])
    if problems:
        return [], problems
    pisos, seen = [], {}
    for row in rows:
        where, found = _where(row), []
        codigo = code_text(column_for(row, mapping, "codigo_municipal"))
        piso = code_text(column_for(row, mapping, "piso"))
        if not codigo or not piso:
            problems.append(f"pisos {where}: no codigo_municipal or piso")
            continue
        if codigo not in codigos:
            found.append("codigo_municipal is not in the fichas")
        seccion, error = parse_seccion(column_for(row, mapping, "seccion"))
        if error:
            found.append(f"seccion {error}")
        key = (codigo, piso, seccion or 1)
        # an unreadable seccion is its own problem, not also a repeated seccion 1
        if error is None and key in seen:
            found.append(f"piso {piso} seccion {seccion or 1} repeated, first at row {seen[key]}")
        if error is None:
            seen.setdefault(key, row["_fila"])
        attributes = {"piso": piso, "seccion": seccion, **_material_estado(row, mapping, enums, found)}
        attributes["area_construida"], error = parse_decimal(column_for(row, mapping, "area_construida"))
        if error:
            found.append(f"area_construida {error}")
        letters, error = categorias_of(row, mapping)
        if error:
            found.append(error)
        attributes.update(letters)
        attributes["techo_incluido"], error = parse_bool(column_for(row, mapping, "techo_incluido"))
        if error:
            found.append(f"techo_incluido {error}")
        attributes["clasificacion"], error = parse_clasificacion(column_for(row, mapping, "clasificacion"),
                                                                 enums.get("clasificacion"))
        if error:
            found.append(f"clasificacion {error}")
        problems.extend(f"pisos {where} ({codigo}): {f}" for f in found)
        pisos.append((row["_fila"], codigo, attributes))
    return pisos, problems


def obras_from(rows, mapping, enums, codigos):
    """(obras, problems). An obra is (row number, codigo_municipal, attributes)."""
    problems = missing_columns(rows, mapping, ["codigo_municipal", "codigo_vu"])
    if problems:
        return [], problems
    obras, seen = [], {}
    for row in rows:
        where, found = _where(row), []
        codigo = code_text(column_for(row, mapping, "codigo_municipal"))
        codigo_vu = clean_text(column_for(row, mapping, "codigo_vu"))
        if not codigo or not codigo_vu:
            problems.append(f"obras {where}: no codigo_municipal or codigo_vu")
            continue
        if codigo not in codigos:
            found.append("codigo_municipal is not in the fichas")
        attributes = {"codigo_vu": codigo_vu, **_material_estado(row, mapping, enums, found)}
        key = obra_key(codigo, attributes)
        if key in seen:
            found.append(f"obra {codigo_vu} of {attributes['anio_construccion']} repeated, first at row {seen[key]}")
        seen.setdefault(key, row["_fila"])
        attributes["cantidad"], error = parse_decimal(column_for(row, mapping, "cantidad"))
        if error:
            found.append(f"cantidad {error}")
        problems.extend(f"obras {where} ({codigo}): {f}" for f in found)
        obras.append((row["_fila"], codigo, attributes))
    return obras, problems


def titulares_from(rows, mapping, codigos):
    """(titulares, problems, avisos). A titular is (row number, codigo, attributes), with codigo_municipal set from
    its predio's code. Never a problem or an aviso names a document or a name (Ley 29733): only codigo and row.

    problems (exit 2): a bad codigo_municipal, a titular of a code outside the fichas, or an unreadable porcentaje.
    avisos (exit 0): a filler document (RELLENO, sent empty), a repeated key (titular_key; loaded once), and a predio
    whose porcentajes (summed as the file brings them, before the repeated-key load-once) differ from 100% by more
    than 0.01, skipped when every one of its titulares lacks porcentaje.
    """
    problems = missing_columns(rows, mapping, ["codigo_municipal"])
    if problems:
        return [], problems, []
    titulares, avisos, seen, sumas = [], [], {}, {}
    for row in rows:
        where, found = _where(row), []
        codigo = code_text(column_for(row, mapping, "codigo_municipal"))
        if not codigo:
            problems.append(f"titulares {where}: no codigo_municipal (column {mapping['codigo_municipal']})")
            continue
        if codigo not in codigos:
            found.append("codigo_municipal is not in the fichas")
        attributes = {"codigo_municipal": codigo, "tipo_documento": clean_text(column_for(row, mapping, "tipo_documento")),
                     "condicion": clean_text(column_for(row, mapping, "condicion")),
                     "nombre": clean_text(column_for(row, mapping, "nombre"))}
        numero = code_text(column_for(row, mapping, "numero_documento"))
        if numero is not None and RELLENO.fullmatch(numero):
            avisos.append(f"titulares {codigo} fila {row['_fila']}: documento de relleno, queda vacío")
            numero = None
        attributes["numero_documento"] = numero
        attributes["porcentaje"], error = parse_decimal(column_for(row, mapping, "porcentaje"))
        if error:
            found.append(f"porcentaje {error}")
        problems.extend(f"titulares {where} ({codigo}): {f}" for f in found)
        if found:
            continue
        sumas.setdefault(codigo, []).append(attributes["porcentaje"])
        key = (codigo, titular_key(codigo, attributes))
        if key in seen:
            avisos.append(f"titulares {codigo} fila {row['_fila']}: repetido, se carga una vez")
            continue
        seen[key] = row["_fila"]
        titulares.append((row["_fila"], codigo, attributes))
    for codigo, porcentajes in sumas.items():
        if all(p is None for p in porcentajes):
            continue
        suma = sum((Decimal(p) for p in porcentajes if p is not None), Decimal(0))
        if abs(suma - 100) > Decimal("0.01"):
            avisos.append(f"titulares {codigo}: suman {format(suma.normalize(), 'f')} %")
    return titulares, problems, avisos


def load(client, fichas, pisos, obras, titulares, workers):
    """Creates the predios Core lacks, then every piso, obra and titular Core lacks, by natural key: a piso is
    (predio, piso, seccion), an obra (predio, codigo_vu, anio_construccion), a titular (predio, numero_documento or
    "", nombre collapsed and upper-cased); Ley 29733: a titular's key is only ever compared, never logged. A run that
    failed half way is completed by running again, and a child Core has is never touched, updated or duplicated.
    Returns (created, skipped, construcciones, obras, titulares)."""
    existing = {r["attributes"]["codigo_municipal"]: r["id"] for r in client.list_all("predio_catastral")}
    todo = [(a["codigo_municipal"], fila, a) for fila, a in fichas if a["codigo_municipal"] not in existing]
    ids = {**existing, **post_all(client, "predio_catastral", todo, workers)}
    created = {}
    for object_name, children, key in (("construccion", pisos, piso_key), ("obra_complementaria", obras, obra_key),
                                       ("titular_catastral", titulares, titular_key)):
        have = {(relation_id(r["attributes"].get("predio")), *key(None, r["attributes"])[1:])
                for r in client.list_all(object_name)}
        items = [((i, codigo), fila, {**a, "predio": ids[codigo]}) for i, (fila, codigo, a) in enumerate(children)
                 if codigo in ids and key(ids[codigo], a) not in have]
        post_all(client, object_name, items, workers)
        created[object_name] = len(items)
    return (len(todo), len(fichas) - len(todo), created["construccion"], created["obra_complementaria"],
           created["titular_catastral"])


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Load the levantamiento's fichas, pisos and obras into wasichai Core.")
    p.add_argument("--fichas", required=True, help="csv or xlsx, one row per predio")
    p.add_argument("--pisos", help="csv or xlsx, one row per piso (required without --entrega)")
    p.add_argument("--obras", help="csv or xlsx, one row per obra complementaria (optional)")
    p.add_argument("--titulares", help="csv or xlsx, one row per titular of a predio, linked by codigo_municipal (optional)")
    for name in ("map", "map-pisos", "map-obras", "map-titulares"):
        p.add_argument(f"--{name}", action="append", default=[], metavar="FIELD=COLUMN", help="column that fills a field")
    p.add_argument("--sheet", help="xlsx sheet name (the first by default), for the four files")
    p.add_argument("--model", default=os.path.join(HERE, "model.json"))
    p.add_argument("--core", default=os.environ.get("WASICHAI_CORE", "http://localhost:8091"))
    p.add_argument("--email", default=os.environ.get("WASICHAI_EMAIL", "admin@wasichai.local"))
    p.add_argument("--password", default=os.environ.get("WASICHAI_PASSWORD", "admin"))
    p.add_argument("--dry-run", action="store_true",
                   help="read and check only; call nothing (with --entrega: log in and read Core to report, write nothing)")
    p.add_argument("--workers", type=int, default=4, help="parallel writes (default 4)")
    e = p.add_argument_group("entrega (upsert, README «Entregas»)")
    e.add_argument("--entrega", metavar="CODIGO", help="the entrega's code, 1 to 64 of A-Z a-z 0-9 . _ : -")
    e.add_argument("--fecha-corte", metavar="YYYY-MM-DD", help="the date the entrega's data is about (required)")
    e.add_argument("--fuente", help="an option of the enum fuente_entrega: BARRIDO, INSPECCION, LICENCIA, GIS, OTRA (required)")
    e.add_argument("--descripcion", metavar="TEXT")
    e.add_argument("--reemplazar-pisos", action="store_true",
                   help="delete the pisos Core has and the --pisos file lacks, in the fichas the file brings")
    e.add_argument("--reemplazar-obras", action="store_true",
                   help="delete the obras Core has and the --obras file lacks, in the fichas the file brings")
    return p.parse_args(argv)


def _flag_problems(args, enums):
    """What is wrong with the flags (exit 2); with --entrega, also normalizes args.fuente to its option."""
    problems = []
    if args.entrega is None:
        if args.pisos is None:
            problems.append("--pisos is required without --entrega")
        problems += [f"{flag} needs --entrega" for flag, value in (
            ("--fecha-corte", args.fecha_corte), ("--fuente", args.fuente), ("--descripcion", args.descripcion),
            ("--reemplazar-pisos", args.reemplazar_pisos), ("--reemplazar-obras", args.reemplazar_obras)) if value]
        return problems
    error = check_codigo(args.entrega)
    if error:
        problems.append(error)
    if args.fecha_corte is None:
        problems.append("--fecha-corte is required with --entrega")
    elif not (ISO_DATE.fullmatch(args.fecha_corte) and _is_date(args.fecha_corte)):
        problems.append(f"--fecha-corte '{args.fecha_corte}' is not a date YYYY-MM-DD")
    if args.fuente is None:
        problems.append("--fuente is required with --entrega")
    else:
        args.fuente, error = enum_option(args.fuente, enums.get("fuente_entrega", []))
        if error:
            problems.append(f"--fuente {error}")
    if args.reemplazar_pisos and args.pisos is None:
        problems.append("--reemplazar-pisos needs a --pisos file")
    if args.reemplazar_obras and args.obras is None:
        problems.append("--reemplazar-obras needs an --obras file")
    return problems


def _is_date(text):
    try:
        datetime.date.fromisoformat(text)
        return True
    except ValueError:
        return False


def _present(args, ficha_rows, piso_rows, obra_rows, titular_rows, maps):
    """The fields each file brings a column for. The single `categorias` column stands for the seven letter fields;
    obras and titulares only from a file actually given (--obras, --titulares)."""
    ficha_map, piso_map, obra_map, titular_map = maps
    pisos = present_fields(piso_rows, piso_map, list(PISO_COLUMNS))
    if "categorias" in pisos:
        pisos |= set(CATEGORIAS)
    return Present(fichas=present_fields(ficha_rows, ficha_map, list(FICHA_COLUMNS)), pisos=pisos,
                   obras=present_fields(obra_rows, obra_map, list(OBRA_COLUMNS)) if args.obras else set(),
                   titulares=present_fields(titular_rows, titular_map, list(TITULAR_COLUMNS)) if args.titulares else set())


def load_entrega(client, args, parsed, present):
    """The --entrega flow once the files parsed clean: prints the plan's lines, writes it unless --dry-run, and returns
    the done line (None on a dry-run). Raises EntregaError when the code already names other files."""
    fichas, pisos, obras, titulares = parsed
    sha = sha256_of([path for path in (args.fichas, args.pisos, args.obras, args.titulares) if path])
    check_same_files(find_entrega(client, args.entrega), sha)
    plan = plan_entrega(read_core(client, titulares=args.titulares is not None), fichas, pisos, obras, present,
                        field_types(args.model), codigo=args.entrega, with_pisos=args.pisos is not None,
                        reemplazar_pisos=args.reemplazar_pisos, reemplazar_obras=args.reemplazar_obras,
                        titulares=titulares if args.titulares is not None else None)
    print("\n".join(plan.lines), flush=True)
    if args.dry_run:
        return None
    if plan.writes:
        entrega_id = ensure_entrega(client, args.entrega, fecha_corte=args.fecha_corte, fuente=args.fuente,
                                    descripcion=args.descripcion, sha=sha, counts=plan.counts)
        apply_plan(client, plan, entrega_id, args.entrega, args.workers)
    return f"done: {plan.lines[-1]}"


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        ficha_map = parse_map(args.map, FICHA_COLUMNS)
        piso_map = parse_map(args.map_pisos, PISO_COLUMNS)
        obra_map = parse_map(args.map_obras, OBRA_COLUMNS)
        titular_map = parse_map(args.map_titulares, TITULAR_COLUMNS)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    try:
        enums = load_enums(args.model)
    except INPUT_ERRORS as e:
        print(f"input: {e}", file=sys.stderr)
        return 2
    flag_problems = _flag_problems(args, enums)
    if flag_problems:
        for problem in flag_problems:
            print(f"error: {problem}", file=sys.stderr)
        return 2
    try:
        ficha_rows = read_table(args.fichas, args.sheet)
        piso_rows = read_table(args.pisos, args.sheet) if args.pisos else []
        obra_rows = read_table(args.obras, args.sheet) if args.obras else []
        titular_rows = read_table(args.titulares, args.sheet) if args.titulares else []
    except INPUT_ERRORS as e:
        print(f"input: {e}", file=sys.stderr)
        return 2
    fichas, problems = fichas_from(ficha_rows, ficha_map, enums)
    codigos = {a["codigo_municipal"] for _, a in fichas}
    pisos, found = pisos_from(piso_rows, piso_map, enums, codigos)
    obras, more = obras_from(obra_rows, obra_map, enums, codigos)
    titulares, yet_more, avisos = titulares_from(titular_rows, titular_map, codigos)
    problems += found + more + yet_more
    print(f"fichas: {len(fichas)}\npisos: {len(pisos)}\nobras: {len(obras)}\ntitulares: {len(titulares)}")
    for aviso in avisos:
        print(aviso)
    if problems:
        report_problems(problems)
        return 2
    if args.dry_run and args.entrega is None:
        return 0
    client = Client(args.core)
    try:
        client.login(args.email, args.password)
        if args.entrega is not None:
            present = _present(args, ficha_rows, piso_rows, obra_rows, titular_rows,
                               (ficha_map, piso_map, obra_map, titular_map))
            done = load_entrega(client, args, (fichas, pisos, obras, titulares), present)
        else:
            created, skipped, n_pisos, n_obras, n_titulares = load(client, fichas, pisos, obras, titulares, args.workers)
            done = (f"done: {created} created, {skipped} skipped ({n_pisos} construcciones, {n_obras} obras, "
                   f"{n_titulares} titulares)")
    except EntregaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except LoadError as e:
        # a titular write's body can echo back a submitted document or name (Ley 29733): never printed
        body = "cuerpo omitido: datos personales" if e.object_name == TITULAR else e.error.body
        print(f"error /api/objects/{e.object_name}/records (fila {e.fila}) -> {e.error.status}\n{body}", file=sys.stderr)
        return 1
    except CoreError as e:
        print(f"error -> {e.status}\n{e.body}", file=sys.stderr)
        return 1
    if done:
        print(done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
