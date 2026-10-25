#!/usr/bin/env python3
"""Loads lot polygons from a GeoJSON FeatureCollection (EPSG:4326) into predio_catastral.lote_geom.

Each feature is matched to an existing predio by codigo_municipal (property `codigo_municipal`) or, when the feature
has none, by codigo_cpu (property `codigo_cpu`); --map field=property renames them (repeatable). A one-part
MultiPolygon is taken as its Polygon. Only updates predios Core already has: a feature that matches none is counted
and left out, never created. A predio that already carries a lote_geom is skipped, so a second run changes nothing,
unless --actualizar-geometria asks to replace one whose polygon changed (ring count, vertex count, or any vertex
farther than 1e-6 degrees, ~10 cm: Core stores EPSG:32718 and answers EPSG:4326, so exact equality never holds).

Without --actualizar-geometria and without --entrega, a geometry write is a PUT like before (today's behaviour).
With either flag, every geometry write (new or replaced) is instead a PATCH of `geometries` (plus `attributes.entrega`
when --entrega is given) with the entrega's code as X-Change-Reason, same as import_fichas.py --entrega
(README «Entregas», ADR-013): the entrega_catastral record is created by the first run that writes, with
{altas: 0, cambios: <replaced>, sin_cambio: <skipped>} (ausentes stays empty: a lote with no predio is `not_found`,
not an ausente); a run with nothing to write writes nothing, not even the entrega.

The gdb's CF_LOTES_POL_18 has neither code, so join the predio's code to its features first. To make the GeoJSON:
  ogr2ogr -f GeoJSON -t_srs EPSG:4326 lotes.geojson 120302_MD_Perene_ECF.gdb CF_LOTES_POL_18

Run: python3 -I import_lotes.py --geojson lotes.geojson [--map codigo_municipal=COD_PRE] [--dry-run]
     python3 -I import_lotes.py --geojson lotes.geojson --actualizar-geometria [--entrega CODIGO --fecha-corte
             AAAA-MM-DD --fuente BARRIDO] [--dry-run]
Exit: 0 ok, 1 Core refused something, 2 the file has features that do not fit (every one is listed, nothing is sent),
      the --entrega flags do not fit, or the entrega's code already names other files.
"""
import argparse
import datetime
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
# under python3 -I (the files it reads are untrusted) neither the cwd nor the script's directory is on sys.path: put
# back only the latter, for core_client, entregas and tabular
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core_client import Client, CoreError  # noqa: E402
from entregas import (EntregaError, check_codigo, check_same_files, ensure_entrega, find_entrega,  # noqa: E402
                      sha256_of)
from tabular import (INPUT_ERRORS, LoadError, code_text, enum_option, load_enums, parse_map, payload,  # noqa: E402
                     report_problems)

PROPERTIES = {"codigo_municipal": "codigo_municipal", "codigo_cpu": "codigo_cpu"}
GEOMETRY = "lote_geom"
# the only shape --fecha-corte accepts (contexto-comun.md); same pattern as import_fichas._flag_problems
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def polygon_of(geometry):
    """The lote's Polygon, or None when the geometry is not one (a MultiPolygon of one part counts)."""
    if not geometry:
        return None
    if geometry.get("type") == "Polygon":
        return geometry
    if geometry.get("type") == "MultiPolygon" and len(geometry.get("coordinates") or []) == 1:
        return {"type": "Polygon", "coordinates": geometry["coordinates"][0]}
    return None


def lotes_from(collection, mapping):
    """(lotes, problems). A lote is (feature number, codigo_municipal, codigo_cpu, polygon)."""
    lotes, problems, seen = [], [], {}
    for n, feature in enumerate(collection.get("features") or [], start=1):
        props = feature.get("properties") or {}
        codigo = code_text(props.get(mapping["codigo_municipal"]))
        cpu = code_text(props.get(mapping["codigo_cpu"]))
        key = ("codigo_municipal", codigo) if codigo else ("codigo_cpu", cpu)
        if not codigo and not cpu:
            problems.append(f"feature {n}: no {mapping['codigo_municipal']} nor {mapping['codigo_cpu']}")
            continue
        if key in seen:
            problems.append(f"feature {n}: {key[0]} {key[1]} repeated, first at feature {seen[key]}")
            continue
        seen[key] = n
        polygon = polygon_of(feature.get("geometry"))
        if polygon is None:
            problems.append(f"feature {n} ({key[1]}): geometry is not a Polygon")
            continue
        lotes.append((n, codigo, cpu, polygon))
    return lotes, problems


def same_polygon(a, b, tolerance=1e-6):
    """Whether two Polygon geometries are the same lot: same ring count, same vertex count in each ring, and no
    vertex farther than `tolerance` degrees (~10 cm) on either axis. Core stores EPSG:32718 and answers EPSG:4326,
    so exact equality never holds (contexto-comun.md): a sub-tolerance survey correction counts as unchanged."""
    rings_a, rings_b = a.get("coordinates") or [], b.get("coordinates") or []
    if len(rings_a) != len(rings_b):
        return False
    for ring_a, ring_b in zip(rings_a, rings_b):
        if len(ring_a) != len(ring_b):
            return False
        for (xa, ya), (xb, yb) in zip(ring_a, ring_b):
            if abs(xa - xb) > tolerance or abs(ya - yb) > tolerance:
                return False
    return True


def _match(client, lotes, actualizar):
    """(todo, already, not_found). `todo` is [(record, n, polygon)]: the lotes whose geometry must be written,
    either because the predio has none yet, or (with `actualizar`) because its polygon changed beyond
    same_polygon's tolerance."""
    records = client.list_all("predio_catastral")
    by_codigo = {r["attributes"].get("codigo_municipal"): r for r in records}
    by_cpu = {r["attributes"].get("codigo_cpu"): r for r in records if r["attributes"].get("codigo_cpu")}
    todo, already, not_found = [], 0, 0
    for n, codigo, cpu, polygon in lotes:
        record = by_codigo.get(codigo) if codigo else by_cpu.get(cpu)
        if record is None:
            not_found += 1
            continue
        existing = (record.get("geometries") or {}).get(GEOMETRY)
        if existing is None or (actualizar and not same_polygon(existing, polygon)):
            todo.append((record, n, polygon))
        else:
            already += 1
    return todo, already, not_found


def _write_one(client, record, n, polygon, actualizar, entrega_id, reason):
    try:
        if actualizar or entrega_id is not None:
            # with either flag, only geometries (and the entrega) move; a PUT today sends attributes back untouched
            body = {"geometries": {GEOMETRY: polygon}}
            if entrega_id is not None:
                body = {"attributes": {"entrega": entrega_id}, **body}
            client.patch(f"/api/objects/predio_catastral/records/{record['id']}", body, reason=reason)
        else:
            body = {**payload(record["attributes"]), "geometries": {GEOMETRY: polygon}}
            client.put(f"/api/objects/predio_catastral/records/{record['id']}", body)
    except CoreError as e:
        raise LoadError("predio_catastral", n, e)


def _write_all(client, todo, workers, actualizar, entrega_id, reason):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_write_one, client, record, n, polygon, actualizar, entrega_id, reason)
                  for record, n, polygon in todo]
        try:
            for future in as_completed(futures):
                future.result()
        except LoadError:
            for future in futures:
                future.cancel()
            raise


def load(client, lotes, workers, *, actualizar=False, entrega_id=None, reason=None):
    """Sets lote_geom on the predios that lack it, and (with `actualizar`) replaces one whose polygon changed.
    Without --actualizar-geometria and without an entrega (both default False/None), a geometry write is a PUT like
    today; with either, it is a PATCH of `geometries` (plus `attributes.entrega` when `entrega_id` is given) with
    `reason` as X-Change-Reason. Returns (updated, already, not_found)."""
    todo, already, not_found = _match(client, lotes, actualizar)
    _write_all(client, todo, workers, actualizar, entrega_id, reason)
    return len(todo), already, not_found


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Load lot polygons (GeoJSON) into predio_catastral.lote_geom.")
    p.add_argument("--geojson", required=True, help="FeatureCollection in EPSG:4326")
    p.add_argument("--map", action="append", default=[], metavar="FIELD=PROPERTY", help="property that carries a code")
    p.add_argument("--actualizar-geometria", action="store_true",
                   help="replace a predio's polygon when it changed beyond ~10 cm (tolerance 1e-6 degrees)")
    p.add_argument("--model", default=os.path.join(HERE, "model.json"))
    p.add_argument("--core", default=os.environ.get("WASICHAI_CORE", "http://localhost:8091"))
    p.add_argument("--email", default=os.environ.get("WASICHAI_EMAIL", "admin@wasichai.local"))
    p.add_argument("--password", default=os.environ.get("WASICHAI_PASSWORD", "admin"))
    p.add_argument("--dry-run", action="store_true",
                   help="read and check only; call nothing (with --entrega: log in and read Core to report, write nothing)")
    p.add_argument("--workers", type=int, default=4, help="parallel writes (default 4)")
    e = p.add_argument_group("entrega (PATCH with X-Change-Reason, README «Entregas»)")
    e.add_argument("--entrega", metavar="CODIGO", help="the entrega's code, 1 to 64 of A-Z a-z 0-9 . _ : -")
    e.add_argument("--fecha-corte", metavar="YYYY-MM-DD", help="the date the entrega's data is about (required with --entrega)")
    e.add_argument("--fuente", help="an option of the enum fuente_entrega: BARRIDO, INSPECCION, LICENCIA, GIS, OTRA (required)")
    return p.parse_args(argv)


def _is_date(text):
    try:
        datetime.date.fromisoformat(text)
        return True
    except ValueError:
        return False


def _flag_problems(args, enums):
    """What is wrong with the --entrega flags (exit 2); with --entrega, also normalizes args.fuente to its option.
    Same validation behaviour and messages as import_fichas._flag_problems (--pisos/--reemplazar do not apply here)."""
    problems = []
    if args.entrega is None:
        problems += [f"{flag} needs --entrega" for flag, value in (
            ("--fecha-corte", args.fecha_corte), ("--fuente", args.fuente)) if value]
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
    return problems


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        mapping = parse_map(args.map, PROPERTIES)
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
        with open(args.geojson, encoding="utf-8") as f:
            collection = json.load(f)
    except INPUT_ERRORS as e:
        print(f"input: {e}", file=sys.stderr)
        return 2
    lotes, problems = lotes_from(collection, mapping)
    print(f"lotes: {len(lotes)}")
    if problems:
        report_problems(problems)
        return 2
    if args.dry_run and args.entrega is None:
        return 0
    client = Client(args.core)
    try:
        client.login(args.email, args.password)
        if args.entrega is not None:
            sha = sha256_of([args.geojson])
            check_same_files(find_entrega(client, args.entrega), sha)
            todo, already, not_found = _match(client, lotes, args.actualizar_geometria)
            if args.dry_run:
                print(f"{len(todo)} to update, {already} skipped, {not_found} without predio")
                return 0
            if todo:
                entrega_id = ensure_entrega(client, args.entrega, fecha_corte=args.fecha_corte, fuente=args.fuente,
                                            descripcion=None, sha=sha,
                                            counts={"altas": 0, "cambios": len(todo), "sin_cambio": already})
                _write_all(client, todo, args.workers, args.actualizar_geometria, entrega_id, args.entrega)
            updated = len(todo)
        else:
            updated, already, not_found = load(client, lotes, args.workers, actualizar=args.actualizar_geometria)
    except EntregaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except LoadError as e:
        print(f"error /api/objects/predio_catastral/records (feature {e.fila}) -> {e.error.status}\n{e.error.body}", file=sys.stderr)
        return 1
    except CoreError as e:
        print(f"error -> {e.status}\n{e.body}", file=sys.stderr)
        return 1
    print(f"done: {updated} updated, {already} skipped, {not_found} without predio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
