#!/usr/bin/env python3
"""Loads the catastro levantamiento's fichas into predio_catastral, construccion and obra_complementaria.

Three inputs, csv or xlsx (the stdlib reader of import_predios.py in srtm-backend); the header is matched
case-insensitively and lines starting with # are skipped:
  --fichas  one row per predio (predio_catastral)
  --pisos   one row per piso of a predio (construccion), linked to its ficha by codigo_municipal
  --obras   one row per obra complementaria (obra_complementaria), same link. Optional.

Default columns follow the MEF carga masiva contract (kamayuk ContratoDeImportacion, docs/40-datos/mapeo-del-modelo-del-mef.md):
  fichas: cod_pre -> codigo_municipal, cod_cpu, cod_sect -> sector, cod_mzn -> manzana, cod_lote -> lote, id_aranc,
          cod_via, cuadra, lado, uso, area_terreno, longitud_frente, anio_levantamiento, es_edificio
  pisos:  cod_pre -> codigo_municipal, piso, area_construida, anio_construccion, material, estado_conservacion, and
          the seven categories either as one 7-letter text in `categorias` (e.g. CCDCCDC, in the order muros_columnas,
          techos, pisos, puertas_ventanas, revestimientos, banos, instalaciones) or in seven columns named as the fields
  obras:  cod_pre -> codigo_municipal, codigo_vu (TIPO DE OBRA|numero, as obra_categoria in srtm), cantidad,
          anio_construccion, material, estado_conservacion
--map, --map-pisos and --map-obras field=column override those defaults (repeatable). material and
estado_conservacion take the model's options in any case, with _ for a space (MUY_BUENO).

Idempotent by codigo_municipal: a predio Core already has is skipped. Its pisos and obras are created with a new predio,
or for an existing predio that has none (so a run that failed half way is repaired by running again); a predio that
has any is never touched. Exit: 0 ok, 1 Core refused something, 2 the files do not fit the model (every bad row is listed, nothing
is sent).

Run: python3 import_fichas.py --fichas fichas.csv --pisos pisos.csv [--obras obras.csv] [--dry-run]
"""
import argparse
import os
import re
import sys

from core_client import Client, CoreError
from tabular import (HERE, INPUT_ERRORS, LoadError, clean_text, code_text, column_for, enum_option, load_enums, missing_columns, parse_decimal,
                     parse_int, parse_map, post_all, read_table, report_problems)

CATEGORIAS = ["muros_columnas", "techos", "pisos", "puertas_ventanas", "revestimientos", "banos", "instalaciones"]

FICHA_COLUMNS = {
    "codigo_municipal": "cod_pre", "codigo_cpu": "cod_cpu", "sector": "cod_sect", "manzana": "cod_mzn", "lote": "cod_lote",
    "id_aranc": "id_aranc", "cod_via": "cod_via", "cuadra": "cuadra", "lado": "lado", "uso": "uso",
    "area_terreno": "area_terreno", "longitud_frente": "longitud_frente", "anio_levantamiento": "anio_levantamiento",
    "es_edificio": "es_edificio",
}
FICHA_TEXT = ["codigo_cpu", "sector", "manzana", "lote", "id_aranc", "cod_via", "cuadra", "lado", "uso"]
FICHA_DECIMAL = ["area_terreno", "longitud_frente"]

PISO_COLUMNS = {
    "codigo_municipal": "cod_pre", "piso": "piso", "area_construida": "area_construida",
    "anio_construccion": "anio_construccion", "material": "material", "estado_conservacion": "estado_conservacion",
    "categorias": "categorias", **{c: c for c in CATEGORIAS},
}
OBRA_COLUMNS = {
    "codigo_municipal": "cod_pre", "codigo_vu": "codigo_vu", "cantidad": "cantidad",
    "anio_construccion": "anio_construccion", "material": "material", "estado_conservacion": "estado_conservacion",
}

TRUE = {"true", "t", "si", "sí", "s", "yes", "y", "1", "x"}
FALSE = {"false", "f", "no", "n", "0"}
CATEGORIA = re.compile(r"[A-J]")


def parse_bool(value):
    text = clean_text(value)
    if text is None:
        return None, None
    if text.lower() in TRUE:
        return True, None
    if text.lower() in FALSE:
        return False, None
    return None, f"'{text}' is not a yes/no"


def _where(row):
    return f"row {row['_fila']}"


def fichas_from(rows, mapping):
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
        problems.extend(f"fichas {where} ({codigo}): {f}" for f in found)
        fichas.append((row["_fila"], attributes))
    return fichas, problems


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
        if (codigo, piso) in seen:
            found.append(f"piso {piso} repeated, first at row {seen[(codigo, piso)]}")
        seen.setdefault((codigo, piso), row["_fila"])
        attributes = {"piso": piso, **_material_estado(row, mapping, enums, found)}
        attributes["area_construida"], error = parse_decimal(column_for(row, mapping, "area_construida"))
        if error:
            found.append(f"area_construida {error}")
        letters, error = categorias_of(row, mapping)
        if error:
            found.append(error)
        attributes.update(letters)
        problems.extend(f"pisos {where} ({codigo}): {f}" for f in found)
        pisos.append((row["_fila"], codigo, attributes))
    return pisos, problems


def obras_from(rows, mapping, enums, codigos):
    """(obras, problems). An obra is (row number, codigo_municipal, attributes)."""
    problems = missing_columns(rows, mapping, ["codigo_municipal", "codigo_vu"])
    if problems:
        return [], problems
    obras = []
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
        attributes["cantidad"], error = parse_decimal(column_for(row, mapping, "cantidad"))
        if error:
            found.append(f"cantidad {error}")
        problems.extend(f"obras {where} ({codigo}): {f}" for f in found)
        obras.append((row["_fila"], codigo, attributes))
    return obras, problems


def load(client, fichas, pisos, obras, workers):
    """Creates the predios Core lacks, then the pisos and obras of the new predios and of the existing ones that have
    none (a run that failed half way is repaired by running again). A predio that has any child is never touched.
    Returns (created, skipped, construcciones, obras)."""
    existing = {r["attributes"]["codigo_municipal"]: r["id"] for r in client.list_all("predio_catastral")}
    with_children = {r["attributes"].get("predio") for name in ("construccion", "obra_complementaria")
                     for r in client.list_all(name)}
    todo = [(a["codigo_municipal"], fila, a) for fila, a in fichas if a["codigo_municipal"] not in existing]
    ids = post_all(client, "predio_catastral", todo, workers)
    # predio ids that take children: the new ones, and the existing ones still without any
    open_ids = {**{c: i for c, i in existing.items() if i not in with_children}, **ids}
    created = {}
    for object_name, children in (("construccion", pisos), ("obra_complementaria", obras)):
        items = [((i, codigo), fila, {**a, "predio": open_ids[codigo]}) for i, (fila, codigo, a) in enumerate(children)
                 if codigo in open_ids]
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
        fichas, problems = fichas_from(read_table(args.fichas, args.sheet), ficha_map)
        codigos = {a["codigo_municipal"] for _, a in fichas}
        pisos, found = pisos_from(read_table(args.pisos, args.sheet), piso_map, enums, codigos)
        problems += found
        obras = []
        if args.obras:
            obras, found = obras_from(read_table(args.obras, args.sheet), obra_map, enums, codigos)
            problems += found
    except INPUT_ERRORS as e:
        print(f"input: {e}", file=sys.stderr)
        return 2
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
