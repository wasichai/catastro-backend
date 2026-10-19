#!/usr/bin/env python3
"""Loads the aranceles (S/ por m2 of a tramo de vía and year) of the Perené geodatabase into arancel.

Two csv files made from the gdb with ogr2ogr (read-only on the gdb), joined here by ID_ARANC:
  ogr2ogr -f CSV frentes.csv 120302_MD_Perene_ECF.gdb CF_ARANCEL_18 -select ID_ARANC,COD_VIA,CUADRA,LADO
  ogr2ogr -f CSV valores.csv 120302_MD_Perene_ECF.gdb TB_VALORACION_HIST -select ID_ARANC,ANO_EJEC,VAL_ACT
--frentes gives id_aranc, cod_via, cuadra and lado (the first row of an ID_ARANC wins); --valores gives id_aranc,
anio (ANO_EJEC) and valor_m2 (VAL_ACT). Both may also be xlsx. A VAL_ACT of 0 is loaded as it is (the valuation
engine reports a motivo for it); an empty VAL_ACT has no value and is left out, and the run says how many.
--anio keeps only that year (default: all). --map field=column renames a column (fields: id_aranc, anio, valor_m2,
cod_via, cuadra, lado).

Idempotent upsert by (id_aranc, anio), kept in arancel.clave = "id_aranc|anio": a record Core lacks is created, one
whose valor_m2, cod_via, cuadra or lado differ is updated, the rest are skipped. Exit: 0 ok, 1 Core refused something,
2 the files do not fit the model (every bad row is listed, nothing is sent).

Run: python3 -I import_aranceles.py --frentes frentes.csv --valores valores.csv [--anio 2026] [--dry-run]
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
# under python3 -I (the files it reads are untrusted) neither the cwd nor the script's directory is on sys.path: put
# back only the latter, for core_client and tabular
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core_client import Client, CoreError  # noqa: E402
from tabular import (INPUT_ERRORS, LoadError, code_text, column_for, missing_columns, parse_decimal,  # noqa: E402
                     parse_int, parse_map, payload, post_all, read_table, report_problems)

COLUMNS = {
    "id_aranc": "id_aranc", "anio": "ano_ejec", "valor_m2": "val_act", "cod_via": "cod_via", "cuadra": "cuadra",
    "lado": "lado",
}
FRENTE_FIELDS = ["cod_via", "cuadra", "lado"]
COMPARED = ["valor_m2", *FRENTE_FIELDS]


def frentes_from(rows, mapping):
    """(frentes by id_aranc, problems)."""
    problems = missing_columns(rows, mapping, ["id_aranc"])
    if problems:
        return {}, problems
    frentes = {}
    for row in rows:
        id_aranc = code_text(column_for(row, mapping, "id_aranc"))
        if not id_aranc:
            problems.append(f"frentes row {row['_fila']}: no id_aranc (column {mapping['id_aranc']})")
        elif id_aranc not in frentes:
            frentes[id_aranc] = {f: code_text(column_for(row, mapping, f)) for f in FRENTE_FIELDS}
    return frentes, problems


def aranceles_from(rows, mapping, frentes, anio=None):
    """(aranceles, empty, problems): aranceles by (id_aranc, anio) as attributes; `empty` counts rows without a value."""
    problems = missing_columns(rows, mapping, ["id_aranc", "anio", "valor_m2"])
    if problems:
        return {}, 0, problems
    aranceles, empty = {}, 0
    for row in rows:
        where = f"valores row {row['_fila']}"
        id_aranc = code_text(column_for(row, mapping, "id_aranc"))
        year, error = parse_int(column_for(row, mapping, "anio"))
        if not id_aranc or year is None or error:
            problems.append(f"{where}: no id_aranc or a bad anio ({error or 'empty'})")
            continue
        if anio is not None and year != anio:
            continue
        valor, error = parse_decimal(column_for(row, mapping, "valor_m2"))
        if error:
            problems.append(f"{where} ({id_aranc}, {year}): valor_m2 {error}")
            continue
        if valor is None:
            empty += 1
            continue
        key = (id_aranc, year)
        previous = aranceles.get(key)
        if previous is not None:
            if Decimal(previous["valor_m2"]) != Decimal(valor):
                problems.append(f"{where} ({id_aranc}, {year}): valor_m2 {valor} differs from {previous['valor_m2']} above")
            continue
        aranceles[key] = {"clave": f"{id_aranc}|{year}", "id_aranc": id_aranc, "anio": year, "valor_m2": valor,
                          **frentes.get(id_aranc, {f: None for f in FRENTE_FIELDS})}
    return aranceles, empty, problems


def differs(attributes, record):
    for field in COMPARED:
        old, new = record.get(field), attributes.get(field)
        if field == "valor_m2" and old is not None and new is not None:
            if Decimal(str(old)) != Decimal(new):
                return True
        elif old != new:
            return True
    return False


def load(client, aranceles, workers):
    """Creates what Core lacks and updates what differs. Returns (created, updated, skipped)."""
    existing = {r["attributes"].get("clave"): r for r in client.list_all("arancel")}
    create = [(key, i, a) for i, (key, a) in enumerate(aranceles.items(), start=1) if a["clave"] not in existing]
    update = [(existing[a["clave"]]["id"], i, a) for i, (key, a) in enumerate(aranceles.items(), start=1)
              if a["clave"] in existing and differs(a, existing[a["clave"]]["attributes"])]
    post_all(client, "arancel", create, workers)

    def put(item):
        record_id, i, attributes = item
        try:
            client.put(f"/api/objects/arancel/records/{record_id}", payload(attributes))
        except CoreError as e:
            raise LoadError("arancel", i, e)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(put, item) for item in update]):
            future.result()
    return len(create), len(update), len(aranceles) - len(create) - len(update)


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Load the Perené aranceles (ogr2ogr csv of the gdb) into wasichai Core.")
    p.add_argument("--frentes", required=True, help="CF_ARANCEL_18 as csv: ID_ARANC, COD_VIA, CUADRA, LADO")
    p.add_argument("--valores", required=True, help="TB_VALORACION_HIST as csv: ID_ARANC, ANO_EJEC, VAL_ACT")
    p.add_argument("--anio", type=int, help="load only this year (default: all)")
    p.add_argument("--map", action="append", default=[], metavar="FIELD=COLUMN", help="column that fills a field")
    p.add_argument("--core", default=os.environ.get("WASICHAI_CORE", "http://localhost:8091"))
    p.add_argument("--email", default=os.environ.get("WASICHAI_EMAIL", "admin@wasichai.local"))
    p.add_argument("--password", default=os.environ.get("WASICHAI_PASSWORD", "admin"))
    p.add_argument("--dry-run", action="store_true", help="read and check only; call nothing")
    p.add_argument("--workers", type=int, default=4, help="parallel requests (default 4)")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        mapping = parse_map(args.map, COLUMNS)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    try:
        frentes_rows = read_table(args.frentes)
        valores_rows = read_table(args.valores)
    except INPUT_ERRORS as e:
        print(f"input: {e}", file=sys.stderr)
        return 2
    frentes, problems = frentes_from(frentes_rows, mapping)
    aranceles, empty, found = aranceles_from(valores_rows, mapping, frentes, args.anio)
    problems += found
    print(f"frentes: {len(frentes)}\naranceles: {len(aranceles)}\nsin valor: {empty}")
    if problems:
        report_problems(problems)
        return 2
    if args.dry_run:
        return 0
    client = Client(args.core)
    try:
        client.login(args.email, args.password)
        created, updated, skipped = load(client, aranceles, args.workers)
    except LoadError as e:
        print(f"error {e.object_name} (row {e.fila}) -> {e.error.status}\n{e.error.body}", file=sys.stderr)
        return 1
    except CoreError as e:
        print(f"error -> {e.status}\n{e.body}", file=sys.stderr)
        return 1
    print(f"done: {created} created, {updated} updated, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
