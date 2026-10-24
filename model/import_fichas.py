#!/usr/bin/env python3
"""Loads the catastro levantamiento's fichas into predio_catastral, construccion and obra_complementaria.

Three inputs, csv or xlsx (the stdlib reader of import_predios.py in srtm-backend); the header is matched
case-insensitively and lines starting with # are skipped:
  --fichas  one row per predio (predio_catastral)
  --pisos   one row per piso of a predio (construccion), linked to its ficha by codigo_municipal
  --obras   one row per obra complementaria (obra_complementaria), same link. Optional.

Default columns follow the MEF carga masiva contract (kamayuk ContratoDeImportacion, docs/40-datos/mapeo-del-modelo-del-mef.md):
  fichas: cod_pre -> codigo_municipal, cod_cpu, cod_sect -> sector, cod_mzn -> manzana, cod_lote -> lote, id_aranc,
          cod_via, cuadra, lado, uso, area_terreno, longitud_frente, anio_levantamiento, es_edificio, and the
          levantamiento's own estado_levantamiento (the model's enum) and fecha_levantamiento (YYYY-MM-DD or an
          xlsx serial day number)
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
--map, --map-pisos and --map-obras field=column override those defaults (repeatable). material and
estado_conservacion take the model's options in any case, with _ for a space (MUY_BUENO).

Idempotent by codigo_municipal: a predio Core already has is skipped. Pisos and obras are idempotent by their own key,
(predio, piso, seccion) and (predio, codigo_vu, anio_construccion), a piso without seccion being seccion 1: only the
ones Core lacks are created, so a run that failed half way is completed by running again. A key repeated in the file is
an error. Exit: 0 ok, 1 Core refused something, 2 the files do not fit the model (every bad row is listed, nothing is
sent).

Run: python3 -I import_fichas.py --fichas fichas.csv --pisos pisos.csv [--obras obras.csv] [--dry-run]
"""
import argparse
import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# under python3 -I (the files it reads are untrusted) neither the cwd nor the script's directory is on sys.path: put
# back only the latter, for core_client and tabular
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core_client import Client, CoreError  # noqa: E402
from tabular import (INPUT_ERRORS, LoadError, clean_text, code_text, column_for, enum_option, load_enums,  # noqa: E402
                     missing_columns, parse_decimal, parse_int, parse_map, post_all, read_table, report_problems)

CATEGORIAS = ["muros_columnas", "techos", "pisos", "puertas_ventanas", "revestimientos", "banos", "instalaciones"]

FICHA_COLUMNS = {
    "codigo_municipal": "cod_pre", "codigo_cpu": "cod_cpu", "sector": "cod_sect", "manzana": "cod_mzn", "lote": "cod_lote",
    "id_aranc": "id_aranc", "cod_via": "cod_via", "cuadra": "cuadra", "lado": "lado", "uso": "uso",
    "area_terreno": "area_terreno", "longitud_frente": "longitud_frente", "anio_levantamiento": "anio_levantamiento",
    "es_edificio": "es_edificio", "estado_levantamiento": "estado_levantamiento", "fecha_levantamiento": "fecha_levantamiento",
}
FICHA_TEXT = ["codigo_cpu", "sector", "manzana", "lote", "id_aranc", "cod_via", "cuadra", "lado", "uso"]
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

TRUE = {"true", "t", "si", "sí", "s", "yes", "y", "1", "x"}
FALSE = {"false", "f", "no", "n", "0"}
CATEGORIA = re.compile(r"[A-J]")
# the RNT's table number (1-4 or 01-04): model.json lists the enum clasificacion in the order of the tables, which
# test_model.py pins and Valorizacion.TABLA_POR_CLASIFICACION checks against the same file
TABLA_RNT = re.compile(r"0?([1-4])")
# an xlsx serial day number, integer or as the float text an xlsx cell sends (46000.0)
SERIAL_DAYS = re.compile(r"\d+(\.0+)?")
XLSX_EPOCH = datetime.date(1899, 12, 30)


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
    try:
        return datetime.date.fromisoformat(text).isoformat(), None
    except ValueError:
        pass
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


def relation_id(value):
    """The id a RELATION reads back as. srtm's importers compare str(attributes["predio"]) with an id, so Core lists a
    bare id; an object with an id is accepted too, in case a version embeds it."""
    if isinstance(value, dict):
        value = value.get("id")
    return None if value is None else str(value)


def piso_key(predio_id, a):
    # a piso Core has without seccion (loaded before it existed) is seccion 1
    return predio_id, str(a["piso"]), int(a.get("seccion") or 1)


def obra_key(predio_id, a):
    return predio_id, str(a["codigo_vu"]), str(a.get("anio_construccion"))


def load(client, fichas, pisos, obras, workers):
    """Creates the predios Core lacks, then every piso and obra Core lacks, by natural key: a piso is (predio, piso,
    seccion), an obra (predio, codigo_vu, anio_construccion). A run that failed half way is completed by running again,
    and a child Core has is never touched or duplicated. Returns (created, skipped, construcciones, obras)."""
    existing = {r["attributes"]["codigo_municipal"]: r["id"] for r in client.list_all("predio_catastral")}
    todo = [(a["codigo_municipal"], fila, a) for fila, a in fichas if a["codigo_municipal"] not in existing]
    ids = {**existing, **post_all(client, "predio_catastral", todo, workers)}
    created = {}
    for object_name, children, key in (("construccion", pisos, piso_key), ("obra_complementaria", obras, obra_key)):
        have = {(relation_id(r["attributes"].get("predio")), *key(None, r["attributes"])[1:])
                for r in client.list_all(object_name)}
        items = [((i, codigo), fila, {**a, "predio": ids[codigo]}) for i, (fila, codigo, a) in enumerate(children)
                 if codigo in ids and key(ids[codigo], a) not in have]
        post_all(client, object_name, items, workers)
        created[object_name] = len(items)
    return len(todo), len(fichas) - len(todo), created["construccion"], created["obra_complementaria"]


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Load the levantamiento's fichas, pisos and obras into wasichai Core.")
    p.add_argument("--fichas", required=True, help="csv or xlsx, one row per predio")
    p.add_argument("--pisos", required=True, help="csv or xlsx, one row per piso")
    p.add_argument("--obras", help="csv or xlsx, one row per obra complementaria (optional)")
    for name in ("map", "map-pisos", "map-obras"):
        p.add_argument(f"--{name}", action="append", default=[], metavar="FIELD=COLUMN", help="column that fills a field")
    p.add_argument("--sheet", help="xlsx sheet name (the first by default), for the three files")
    p.add_argument("--model", default=os.path.join(HERE, "model.json"))
    p.add_argument("--core", default=os.environ.get("WASICHAI_CORE", "http://localhost:8091"))
    p.add_argument("--email", default=os.environ.get("WASICHAI_EMAIL", "admin@wasichai.local"))
    p.add_argument("--password", default=os.environ.get("WASICHAI_PASSWORD", "admin"))
    p.add_argument("--dry-run", action="store_true", help="read and check only; call nothing")
    p.add_argument("--workers", type=int, default=4, help="parallel POSTs (default 4)")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        ficha_map = parse_map(args.map, FICHA_COLUMNS)
        piso_map = parse_map(args.map_pisos, PISO_COLUMNS)
        obra_map = parse_map(args.map_obras, OBRA_COLUMNS)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    try:
        enums = load_enums(args.model)
        ficha_rows = read_table(args.fichas, args.sheet)
        piso_rows = read_table(args.pisos, args.sheet)
        obra_rows = read_table(args.obras, args.sheet) if args.obras else []
    except INPUT_ERRORS as e:
        print(f"input: {e}", file=sys.stderr)
        return 2
    fichas, problems = fichas_from(ficha_rows, ficha_map, enums)
    codigos = {a["codigo_municipal"] for _, a in fichas}
    pisos, found = pisos_from(piso_rows, piso_map, enums, codigos)
    obras, more = obras_from(obra_rows, obra_map, enums, codigos)
    problems += found + more
    print(f"fichas: {len(fichas)}\npisos: {len(pisos)}\nobras: {len(obras)}")
    if problems:
        report_problems(problems)
        return 2
    if args.dry_run:
        return 0
    client = Client(args.core)
    try:
        client.login(args.email, args.password)
        created, skipped, n_pisos, n_obras = load(client, fichas, pisos, obras, args.workers)
    except LoadError as e:
        print(f"error POST /api/objects/{e.object_name}/records (fila {e.fila}) -> {e.error.status}\n{e.error.body}", file=sys.stderr)
        return 1
    except CoreError as e:
        print(f"error -> {e.status}\n{e.body}", file=sys.stderr)
        return 1
    print(f"done: {created} created, {skipped} skipped ({n_pisos} construcciones, {n_obras} obras)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
