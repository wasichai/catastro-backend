#!/usr/bin/env python3
"""Loads lot polygons from a GeoJSON FeatureCollection (EPSG:4326) into predio_catastral.lote_geom.

Each feature is matched to an existing predio by codigo_municipal (property `codigo_municipal`) or, when the feature
has none, by codigo_cpu (property `codigo_cpu`); --map field=property renames them (repeatable). A one-part
MultiPolygon is taken as its Polygon. Only updates predios Core already has: a feature that matches none is counted
and left out, never created. A predio that already carries a lote_geom is skipped, so a second run changes nothing.

The gdb's CF_LOTES_POL_18 has neither code, so join the predio's code to its features first. To make the GeoJSON:
  ogr2ogr -f GeoJSON -t_srs EPSG:4326 lotes.geojson 120302_MD_Perene_ECF.gdb CF_LOTES_POL_18

Run: python3 import_lotes.py --geojson lotes.geojson [--map codigo_municipal=COD_PRE] [--dry-run]
Exit: 0 ok, 1 Core refused something, 2 the file has features that do not fit (every one is listed, nothing is sent).
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from core_client import Client, CoreError
from tabular import INPUT_ERRORS, LoadError, code_text, parse_map, payload, report_problems

PROPERTIES = {"codigo_municipal": "codigo_municipal", "codigo_cpu": "codigo_cpu"}
GEOMETRY = "lote_geom"


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


def load(client, lotes, workers):
    """Sets lote_geom on the predios that lack it. Returns (updated, already, not_found)."""
    records = client.list_all("predio_catastral")
    by_codigo = {r["attributes"].get("codigo_municipal"): r for r in records}
    by_cpu = {r["attributes"].get("codigo_cpu"): r for r in records if r["attributes"].get("codigo_cpu")}
    todo, already, not_found = [], 0, 0
    for n, codigo, cpu, polygon in lotes:
        record = by_codigo.get(codigo) if codigo else by_cpu.get(cpu)
        if record is None:
            not_found += 1
        elif (record.get("geometries") or {}).get(GEOMETRY):
            already += 1
        else:
            todo.append((record, n, polygon))

    def one(item):
        record, n, polygon = item
        # a PUT replaces the record: send its attributes back with the polygon
        body = {**payload(record["attributes"]), "geometries": {GEOMETRY: polygon}}
        try:
            client.put(f"/api/objects/predio_catastral/records/{record['id']}", body)
        except CoreError as e:
            raise LoadError("predio_catastral", n, e)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, item) for item in todo]
        try:
            for future in as_completed(futures):
                future.result()
        except LoadError:
            for future in futures:
                future.cancel()
            raise
    return len(todo), already, not_found


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Load lot polygons (GeoJSON) into predio_catastral.lote_geom.")
    p.add_argument("--geojson", required=True, help="FeatureCollection in EPSG:4326")
    p.add_argument("--map", action="append", default=[], metavar="FIELD=PROPERTY", help="property that carries a code")
    p.add_argument("--core", default=os.environ.get("WASICHAI_CORE", "http://localhost:8091"))
    p.add_argument("--email", default=os.environ.get("WASICHAI_EMAIL", "admin@wasichai.local"))
    p.add_argument("--password", default=os.environ.get("WASICHAI_PASSWORD", "admin"))
    p.add_argument("--dry-run", action="store_true", help="read and check only; call nothing")
    p.add_argument("--workers", type=int, default=4, help="parallel PUTs (default 4)")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        mapping = parse_map(args.map, PROPERTIES)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    try:
        with open(args.geojson, encoding="utf-8") as f:
            collection = json.load(f)
        lotes, problems = lotes_from(collection, mapping)
    except INPUT_ERRORS as e:
        print(f"input: {e}", file=sys.stderr)
        return 2
    print(f"lotes: {len(lotes)}")
    if problems:
        report_problems(problems)
        return 2
    if args.dry_run:
        return 0
    client = Client(args.core)
    try:
        client.login(args.email, args.password)
        updated, already, not_found = load(client, lotes, args.workers)
    except LoadError as e:
        print(f"error PUT /api/objects/predio_catastral/records (feature {e.fila}) -> {e.error.status}\n{e.error.body}", file=sys.stderr)
        return 1
    except CoreError as e:
        print(f"error -> {e.status}\n{e.body}", file=sys.stderr)
        return 1
    print(f"done: {updated} updated, {already} skipped, {not_found} without predio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
