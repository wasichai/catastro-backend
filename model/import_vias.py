#!/usr/bin/env python3
"""Loads the eje vial of a GeoPackage into tramo_via, each frente with the SAT code of its arancel (id_aranc).

Reads, with sqlite3 and without GDAL, three layers of --gpkg: cf_eje_vial (fid, geom, cod_via, tip_via, abr_tvia,
nom_via, ubigeo, fuente; LineString or MultiLineString), cf_lotes_pol (id_lote_p, geom; Polygon or MultiPolygon) and
padron_predial (cod_predio, id_lote_p_vinculado), all in EPSG:32718. From the sheet `padron` of --padron-xlsx it reads
only codigo_predio, codigo_de_via, nombre_de_la_via and tipo_predio, and keeps the urbanos (tipo_predio 1).

Each tramo of the eje gets its code like this (the plano predial values a vía by frente, notes 2 and 3):
  1. its nom_via, normalized (no accents, no leading type such as CA. AV. JR. PJE., spaces collapsed), names a single
     SAT code of the padrón, and no other cod_via of the eje has that name: NOMBRE_UNICO, one row AMBOS;
  2. otherwise the lotes of the predios of each code with that name (padron_predial.cod_predio ->
     id_lote_p_vinculado -> cf_lotes_pol) are placed on the left or the right of the tramo (the sign of the cross
     product with its nearest segment; a lote beyond either end of the tramo does not count). Each side takes the
     code whose lote centroid is closest, within --distancia metres (30): CERCANIA. Both sides the same code, or only
     one side with lotes: one row AMBOS; two codes: two rows, IZQUIERDO and DERECHO;
  3. nothing found, a «SIN NOMBRE» or a name with no code: SIN_ARANCEL, one row AMBOS without id_aranc.
cuadra stays empty: the eje has no such column. The geometry goes to Core as GeoJSON in EPSG:4326 (wasichai-gis
transforms it back to the column's 32718), as a MultiLineString; utm_to_wgs84 is the inverse transverse Mercator of
UTM 18S, so no proj is needed.

Idempotent upsert by tramo_via.clave = "<fid>|<lado>": a row Core lacks is created, one whose attributes or geometry
(beyond 1e-6 degrees, ~10 cm) differ is updated (PATCH), and a row of a fid in the file whose lado is no longer
produced (AMBOS that is now IZQUIERDO and DERECHO, or the other way) is deleted. A row of a fid the file does not have
is left as it is and counted. Only counts are printed; --revision writes cod_via_eje, fid_eje, lado, id_aranc and
asignacion of every row to a csv outside the repository (no personal data). --org refuses to write unless the account
of --email belongs to that organization (its id). --dry-run reads Core and says what it would write, writing nothing.

Run: python3 -I import_vias.py --gpkg ica.gpkg --padron-xlsx PADRON.xlsx [--revision /tmp/revision.csv]
             [--org <organization id>] [--distancia 30] [--dry-run] [--workers 4]
Exit: 0 ok, 1 Core refused something, 2 the files do not fit (every problem is listed, nothing is sent), --org is
      another organization, or --revision points into the repository.
"""
import argparse
import csv
import math
import os
import sqlite3
import struct
import sys
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
# under python3 -I (the files it reads are untrusted) neither the cwd nor the script's directory is on sys.path: put
# back only the latter, for core_client and tabular
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core_client import Client, CoreError  # noqa: E402
from tabular import INPUT_ERRORS, LoadError, clean_text, code_text, payload, read_table, report_problems  # noqa: E402

OBJECT = "tramo_via"
GEOMETRY = "geom"
SRID = 32718
EJE, LOTES, PADRON_PREDIAL = "cf_eje_vial", "cf_lotes_pol", "padron_predial"
EJE_COLUMNS = ["fid", "cod_via", "tip_via", "nom_via", "ubigeo", "fuente"]
PADRON_COLUMNS = ["codigo_predio", "codigo_de_via", "nombre_de_la_via", "tipo_predio"]
PADRON_SHEET = "padron"
URBANO = "1"
AMBOS, IZQUIERDO, DERECHO = "AMBOS", "IZQUIERDO", "DERECHO"
NOMBRE_UNICO, CERCANIA, SIN_ARANCEL = "NOMBRE_UNICO", "CERCANIA", "SIN_ARANCEL"
ASIGNACIONES = [NOMBRE_UNICO, CERCANIA, SIN_ARANCEL]
DISTANCIA = 30.0
# a geometry Core answers in 4326 after storing it in 32718 never comes back equal: within this it is the same
TOLERANCE = 1e-6
# the leading type of a vía's name; PROL. stays, a prolongación is another vía
TIPOS = {"CA", "CALLE", "CAL", "AV", "AVDA", "AVENIDA", "JR", "JIRON", "PJE", "PSJE", "PJ", "PASAJE", "ALAMEDA",
         "MALECON", "CARRETERA", "CARR", "OVALO", "PLAZA", "PZA", "PARQUE", "BOULEVARD", "BLVD", "CALLEJON", "VIA",
         "TRAVESIA", "TR"}
SIN_NOMBRE = {"SIN NOMBRE", "S N", "SN", "SIN NOMBRE S N"}
REVISION_COLUMNS = ["cod_via_eje", "fid_eje", "lado", "id_aranc", "asignacion"]


class GpkgError(ValueError):
    pass


# ---- GeoPackage and WKB ----

def gpkg_wkb(blob):
    """The standard WKB inside a GeoPackage geometry blob, or None for an empty one. The header is "GP", a version
    byte, a flags byte (bit 0 the byte order of the header, bits 1-3 the envelope: none, xy, xyz, xym or xyzm, bit 4
    empty), the srs_id (int32) and the envelope's doubles."""
    if blob is None:
        return None
    blob = bytes(blob)
    if len(blob) < 8 or blob[:2] != b"GP":
        raise GpkgError("not a GeoPackage geometry (no GP header)")
    flags = blob[3]
    envelope = (flags >> 1) & 0b111
    if envelope > 4:
        raise GpkgError(f"envelope indicator {envelope} is not 0 to 4")
    if flags & 0b10000:
        return None
    return blob[8 + (0, 32, 48, 48, 64)[envelope]:]


def parse_wkb(data):
    """A WKB (ISO, or EWKB with its Z, M and SRID flags) as a GeoJSON-like dict of x, y only."""
    geometry, _ = _wkb(data, 0)
    return geometry


def _wkb(data, at):
    if data[at] not in (0, 1):
        raise GpkgError(f"bad WKB byte order {data[at]}")
    order = "<" if data[at] == 1 else ">"
    (kind,) = struct.unpack_from(order + "I", data, at + 1)
    at += 5
    z, m = bool(kind & 0x80000000), bool(kind & 0x40000000)
    if kind & 0x20000000:
        at += 4
    kind &= 0x0FFFFFFF
    if kind >= 1000:
        z, m = z or kind // 1000 in (1, 3), m or kind // 1000 in (2, 3)
        kind %= 1000
    dims = 2 + z + m

    def points(at):
        (n,) = struct.unpack_from(order + "I", data, at)
        at += 4
        values = struct.unpack_from(order + "d" * (n * dims), data, at)
        return [[values[i * dims], values[i * dims + 1]] for i in range(n)], at + 8 * n * dims

    if kind == 1:
        x, y = struct.unpack_from(order + "dd", data, at)
        return {"type": "Point", "coordinates": [x, y]}, at + 8 * dims
    if kind == 2:
        coordinates, at = points(at)
        return {"type": "LineString", "coordinates": coordinates}, at
    if kind == 3:
        (n,) = struct.unpack_from(order + "I", data, at)
        at += 4
        rings = []
        for _ in range(n):
            ring, at = points(at)
            rings.append(ring)
        return {"type": "Polygon", "coordinates": rings}, at
    if kind in (4, 5, 6):
        (n,) = struct.unpack_from(order + "I", data, at)
        at += 4
        parts = []
        for _ in range(n):
            part, at = _wkb(data, at)
            parts.append(part["coordinates"])
        return {"type": ("MultiPoint", "MultiLineString", "MultiPolygon")[kind - 4], "coordinates": parts}, at
    raise GpkgError(f"WKB geometry type {kind} is not supported")


def lines_of(geometry):
    """The parts of a LineString or MultiLineString (each at least two points), or None for any other shape."""
    if geometry is None:
        return None
    if geometry["type"] == "LineString":
        parts = [geometry["coordinates"]]
    elif geometry["type"] == "MultiLineString":
        parts = geometry["coordinates"]
    else:
        return None
    parts = [p for p in parts if len(p) >= 2]
    return parts or None


def _ring_centroid(ring):
    """(abs area, cx, cy) of a ring (shoelace); a degenerate ring weighs 0 with its vertices' mean."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if a == 0:
        return 0.0, sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
    return abs(a) / 2, cx / (3 * a), cy / (3 * a)


def centroid(geometry):
    """The area-weighted centroid of a Polygon or MultiPolygon (holes subtracted), or None for another shape."""
    if geometry is None or geometry["type"] not in ("Polygon", "MultiPolygon"):
        return None
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    total = sx = sy = 0.0
    fallback = None
    for rings in polygons:
        rings = [r for r in rings if r]
        if not rings:
            continue
        for n, ring in enumerate(rings):
            area, cx, cy = _ring_centroid(ring)
            sign = 1 if n == 0 else -1
            total += sign * area
            sx += sign * area * cx
            sy += sign * area * cy
            if fallback is None:
                fallback = (cx, cy)
    if total <= 0:
        return fallback
    return sx / total, sy / total


# ---- UTM 18S to WGS84 ----

_A, _F = 6378137.0, 1 / 298.257223563
_N = _F / (2 - _F)
_RECTIFYING = _A / (1 + _N) * (1 + _N ** 2 / 4 + _N ** 4 / 64)
_BETA = (_N / 2 - 2 * _N ** 2 / 3 + 37 * _N ** 3 / 96 - _N ** 4 / 360,
         _N ** 2 / 48 + _N ** 3 / 15 - 437 * _N ** 4 / 1440,
         17 * _N ** 3 / 480 - 37 * _N ** 4 / 840,
         4397 * _N ** 4 / 161280)
_DELTA = (2 * _N - 2 * _N ** 2 / 3 - 2 * _N ** 3 + 116 * _N ** 4 / 45,
          7 * _N ** 2 / 3 - 8 * _N ** 3 / 5 - 227 * _N ** 4 / 45,
          56 * _N ** 3 / 15 - 136 * _N ** 4 / 35,
          4279 * _N ** 4 / 630)
_K0, _E0, _N0, _LON0 = 0.9996, 500000.0, 10000000.0, math.radians(-75.0)


def utm_to_wgs84(x, y):
    """(lon, lat) in degrees of an EPSG:32718 point: Krüger's series to n^4, well under a millimetre in the zone."""
    xi = (y - _N0) / (_K0 * _RECTIFYING)
    eta = (x - _E0) / (_K0 * _RECTIFYING)
    xi1, eta1 = xi, eta
    for j, b in enumerate(_BETA, start=1):
        xi1 -= b * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
        eta1 -= b * math.cos(2 * j * xi) * math.sinh(2 * j * eta)
    chi = math.asin(math.sin(xi1) / math.cosh(eta1))
    lat = chi + sum(d * math.sin(2 * j * chi) for j, d in enumerate(_DELTA, start=1))
    lon = _LON0 + math.atan2(math.sinh(eta1), math.cos(xi1))
    return math.degrees(lon), math.degrees(lat)


def to_wgs84(parts):
    """A MultiLineString GeoJSON in EPSG:4326 of the parts (EPSG:32718)."""
    return {"type": "MultiLineString", "coordinates": [[list(utm_to_wgs84(x, y)) for x, y in part] for part in parts]}


# ---- reading ----

def _columns(con, table):
    return [row[1].lower() for row in con.execute(f'PRAGMA table_info("{table}")')]


def _geometry_column(con, table, problems):
    row = con.execute("SELECT column_name, srs_id FROM gpkg_geometry_columns WHERE lower(table_name) = ?",
                      (table.lower(),)).fetchone()
    if row is None:
        problems.append(f"{table}: no geometry column in gpkg_geometry_columns")
        return None
    if row[1] != SRID:
        problems.append(f"{table}: srs {row[1]}, expected {SRID}")
        return None
    return row[0]


def _geometry(blob):
    return parse_wkb(gpkg_wkb(blob)) if blob is not None and gpkg_wkb(blob) is not None else None


def read_gpkg(path):
    """(ejes, lote centroids by id_lote_p, id_lote_p by cod_predio, problems). An eje is a dict of EJE_COLUMNS plus
    abr_tvia, nom_alt and `parts` (its lines in 32718)."""
    problems = []
    uri = "file:" + urllib.request.pathname2url(os.path.abspath(path)) + "?mode=ro"
    if not os.path.isfile(path):
        raise OSError(f"{path}: no such file")
    con = sqlite3.connect(uri, uri=True)
    try:
        tables = {r[0].lower() for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
        for table in (EJE, LOTES, PADRON_PREDIAL, "gpkg_geometry_columns"):
            if table not in tables:
                problems.append(f"{path}: no table {table}")
        if problems:
            return [], {}, {}, problems
        wanted = {EJE: EJE_COLUMNS, LOTES: ["id_lote_p"], PADRON_PREDIAL: ["cod_predio", "id_lote_p_vinculado"]}
        for table, columns in wanted.items():
            have = _columns(con, table)
            problems += [f"{table}: no column {c}" for c in columns if c not in have]
        eje_geom = _geometry_column(con, EJE, problems)
        lote_geom = _geometry_column(con, LOTES, problems)
        if problems:
            return [], {}, {}, problems
        eje_columns = _columns(con, EJE)
        extra = [c for c in ("abr_tvia", "nom_alt") if c in eje_columns]
        select = ", ".join(f'"{c}"' for c in EJE_COLUMNS + extra)
        ejes = []
        for row in con.execute(f'SELECT {select}, "{eje_geom}" FROM "{EJE}" ORDER BY fid'):
            eje = dict(zip(EJE_COLUMNS + extra, row[:-1]))
            try:
                parts = lines_of(_geometry(row[-1]))
            except (GpkgError, struct.error) as e:
                problems.append(f"{EJE} fid {eje['fid']}: {e}")
                continue
            if parts is None:
                problems.append(f"{EJE} fid {eje['fid']}: geometry is not a LineString or MultiLineString")
                continue
            eje["parts"] = parts
            ejes.append(eje)
        centroids = {}
        for id_lote, blob in con.execute(f'SELECT id_lote_p, "{lote_geom}" FROM "{LOTES}"'):
            key = code_text(id_lote)
            try:
                point = centroid(_geometry(blob))
            except (GpkgError, struct.error) as e:
                problems.append(f"{LOTES} {key}: {e}")
                continue
            if key and point is not None:
                centroids[key] = point
        lote_of = {}
        for cod_predio, id_lote in con.execute(f'SELECT cod_predio, id_lote_p_vinculado FROM "{PADRON_PREDIAL}"'):
            if code_text(cod_predio) and code_text(id_lote):
                lote_of[code_text(cod_predio)] = code_text(id_lote)
        return ejes, centroids, lote_of, problems
    finally:
        con.close()


def normalize(name):
    """A vía's name to compare: no accents, upper case, only letters and digits, no leading type, spaces collapsed.
    None for an empty name or a «SIN NOMBRE»."""
    text = clean_text(name)
    if text is None:
        return None
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).upper()
    words = "".join(c if c.isalnum() else " " for c in text).split()
    while len(words) > 1 and words[0] in TIPOS:
        words = words[1:]
    text = " ".join(words)
    return None if not text or text in SIN_NOMBRE else text


def read_padron(rows):
    """(codes by normalized name, predios by code, urban codes, problems) of the urbanos of the padrón."""
    problems = [f"sheet {PADRON_SHEET}: no column {c}" for c in PADRON_COLUMNS if rows and c not in rows[0]]
    if problems:
        return {}, {}, set(), problems
    by_name, predios, codes = {}, {}, set()
    for row in rows:
        if code_text(row.get("tipo_predio")) != URBANO:
            continue
        code = code_text(row.get("codigo_de_via"))
        if not code:
            continue
        codes.add(code)
        predio = code_text(row.get("codigo_predio"))
        if predio:
            predios.setdefault(code, set()).add(predio)
        name = normalize(row.get("nombre_de_la_via"))
        if name:
            by_name.setdefault(name, set()).add(code)
    return by_name, predios, codes, problems


# ---- assignment ----

def side_and_distance(parts, point):
    """(distance, IZQUIERDO or DERECHO) of a point to the tramo, by its nearest segment and the sign of the cross
    product with it (left is counter-clockwise of the line's direction). None when the nearest point is an end of the
    tramo (the point lies beyond it) or the point is on the line."""
    px, py = point
    best = None
    for part in parts:
        last = len(part) - 2
        for i, ((ax, ay), (bx, by)) in enumerate(zip(part, part[1:])):
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy
            if length2 == 0:
                continue
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
            d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if best is None or d < best[0]:
                beyond = (t == 0.0 and i == 0) or (t == 1.0 and i == last)
                best = (d, dx * (py - ay) - dy * (px - ax), beyond)
    if best is None or best[2] or best[1] == 0:
        return None
    return best[0], IZQUIERDO if best[1] > 0 else DERECHO


def _bbox(parts, margin):
    xs = [x for part in parts for x, _ in part]
    ys = [y for part in parts for _, y in part]
    return min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin


def nearest_by_side(parts, candidates, lotes_of_code, distancia):
    """{side: code} with the closest lote of each side within `distancia`; ties go to the smaller code."""
    x0, y0, x1, y1 = _bbox(parts, distancia)
    best = {}
    for code in sorted(candidates):
        for point in lotes_of_code.get(code, ()):
            if not (x0 <= point[0] <= x1 and y0 <= point[1] <= y1):
                continue
            found = side_and_distance(parts, point)
            if found is None or found[0] > distancia:
                continue
            d, side = found
            if side not in best or (d, code) < best[side]:
                best[side] = (d, code)
    return {side: code for side, (_, code) in best.items()}


def assign(ejes, by_name, predios, centroids, lote_of, distancia=DISTANCIA):
    """(rows, stats). A row is (attributes, parts) of one frente; stats carries the counts the run prints."""
    lotes_of_code = {}
    for code, codes_predios in predios.items():
        points = {centroids[lote_of[p]] for p in codes_predios if p in lote_of and lote_of[p] in centroids}
        if points:
            lotes_of_code[code] = sorted(points)
    names = [normalize(e["nom_via"]) for e in ejes]
    vias_of_name = {}
    for eje, name in zip(ejes, names):
        if name:
            vias_of_name.setdefault(name, set()).add(code_text(eje["cod_via"]))
    rows, near, tried, split = [], set(), set(), 0
    for eje, name in zip(ejes, names):
        candidates = by_name.get(name, set()) if name else set()
        sides = {}
        if len(candidates) == 1 and len(vias_of_name[name]) == 1:
            sides, how = {AMBOS: next(iter(candidates))}, NOMBRE_UNICO
        elif candidates:
            tried |= candidates
            found = nearest_by_side(eje["parts"], candidates, lotes_of_code, distancia)
            near |= set(found.values())
            how = CERCANIA
            if len(set(found.values())) == 2:
                sides = found
                split += 1
            elif found:
                sides = {AMBOS: next(iter(found.values()))}
        if not sides:
            sides, how = {AMBOS: None}, SIN_ARANCEL
        for lado, code in sides.items():
            rows.append((_attributes(eje, lado, code, how), eje["parts"]))
    assigned = {a["id_aranc"] for a, _ in rows if a["id_aranc"]}
    codes = {c for cs in by_name.values() for c in cs} | set(predios)
    stats = {
        "ejes": len(ejes),
        "por_asignacion": {how: sum(1 for a, _ in rows if a["asignacion"] == how) for how in ASIGNACIONES},
        "partidos": split,
        "sin_tramo": len(codes - assigned),
        "sin_lotes": len(codes - set(lotes_of_code)),
        "lejanos": len((tried & set(lotes_of_code)) - near - assigned),
    }
    return rows, stats


def _attributes(eje, lado, code, how):
    fid = int(eje["fid"])
    return {
        "clave": f"{fid}|{lado}",
        "fid_eje": fid,
        "cod_via_eje": code_text(eje["cod_via"]),
        "tip_via": clean_text(eje.get("abr_tvia")) or clean_text(eje["tip_via"]),
        "nom_via": clean_text(eje["nom_via"]),
        "ubigeo": code_text(eje["ubigeo"]),
        "fuente": clean_text(eje["fuente"]),
        "cuadra": None,
        "lado": lado,
        "id_aranc": code,
        "asignacion": how,
    }


# ---- loading ----

def same_lines(a, b, tolerance=TOLERANCE):
    """Whether two MultiLineString geometries have the same parts and vertices, each within `tolerance` degrees."""
    if not a or not b or a.get("type") != b.get("type"):
        return False
    parts_a, parts_b = a.get("coordinates") or [], b.get("coordinates") or []
    if len(parts_a) != len(parts_b) or any(len(p) != len(q) for p, q in zip(parts_a, parts_b)):
        return False
    return all(abs(xa - xb) <= tolerance and abs(ya - yb) <= tolerance
               for p, q in zip(parts_a, parts_b) for (xa, ya), (xb, yb) in zip(p, q))


def _differs(attributes, geometry, record):
    stored = record.get("attributes") or {}
    if any(stored.get(k) != v for k, v in attributes.items()):
        return True
    return not same_lines((record.get("geometries") or {}).get(GEOMETRY), geometry)


def plan(records, rows):
    """(create, update, delete, unchanged, orphans): what makes Core's tramo_via equal to `rows`. create and update
    are [(record id or None, n, attributes, geometry)], delete the records of a fid in `rows` with a lado it no longer
    has; orphans counts the records of a fid `rows` does not have, which are kept."""
    existing = {(r.get("attributes") or {}).get("clave"): r for r in records}
    claves = {a["clave"] for a, _ in rows}
    fids = {a["fid_eje"] for a, _ in rows}
    create, update, unchanged = [], [], 0
    for n, (attributes, parts) in enumerate(rows, start=1):
        geometry = to_wgs84(parts)
        record = existing.get(attributes["clave"])
        if record is None:
            create.append((None, n, attributes, geometry))
        elif _differs(attributes, geometry, record):
            update.append((record["id"], n, attributes, geometry))
        else:
            unchanged += 1
    others = [r for clave, r in existing.items() if clave not in claves]
    delete = [r for r in others if _fid(r) in fids]
    return create, update, delete, unchanged, len(others) - len(delete)


def _fid(record):
    value = (record.get("attributes") or {}).get("fid_eje")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def write(client, create, update, delete, workers):
    """POSTs the new rows, PATCHes the changed ones (a None clears a field), then DELETEs the stale ones. The first
    refusal raises LoadError and cancels the rest."""
    path = f"/api/objects/{OBJECT}/records"

    def one(op):
        method, record_id, n, attributes, geometry = op
        try:
            if method == "POST":
                client.post(path, {**payload(attributes), "geometries": {GEOMETRY: geometry}})
            elif method == "PATCH":
                client.patch(f"{path}/{record_id}", {"attributes": attributes, "geometries": {GEOMETRY: geometry}})
            else:
                client.delete(f"{path}/{record_id}")
        except CoreError as e:
            raise LoadError(OBJECT, n, e)

    batches = [[("POST", *op) for op in create] + [("PATCH", *op) for op in update],
               [("DELETE", r["id"], _fid(r), None, None) for r in delete]]
    for batch in batches:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(one, op) for op in batch]
            try:
                for future in as_completed(futures):
                    future.result()
            except LoadError:
                for future in futures:
                    future.cancel()
                raise


def write_revision(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        out = csv.writer(f)
        out.writerow(REVISION_COLUMNS)
        for attributes, _ in rows:
            out.writerow(["" if attributes[c] is None else attributes[c] for c in REVISION_COLUMNS])


def _inside_repo(path):
    repo = os.path.dirname(HERE)
    target = os.path.realpath(os.path.abspath(path))
    return os.path.commonpath([os.path.realpath(repo), target]) == os.path.realpath(repo)


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Load the eje vial (GeoPackage) into tramo_via with each frente's SAT code.")
    p.add_argument("--gpkg", required=True, help="GeoPackage with cf_eje_vial, cf_lotes_pol and padron_predial (32718)")
    p.add_argument("--padron-xlsx", required=True, help="the padrón: sheet padron, codigo_predio, codigo_de_via, ...")
    p.add_argument("--revision", help="csv of the rows (cod_via_eje, fid_eje, lado, id_aranc, asignacion), outside the repo")
    p.add_argument("--org", help="the organization id the account must belong to, or nothing is written")
    p.add_argument("--distancia", type=float, default=DISTANCIA, help="metres from a lote to its tramo (default 30)")
    p.add_argument("--core", default=os.environ.get("WASICHAI_CORE", "http://localhost:8091"))
    p.add_argument("--email", default=os.environ.get("WASICHAI_EMAIL", "admin@wasichai.local"))
    p.add_argument("--password", default=os.environ.get("WASICHAI_PASSWORD", "admin"))
    p.add_argument("--dry-run", action="store_true", help="read Core and say what would change; write nothing")
    p.add_argument("--workers", type=int, default=4, help="parallel writes (default 4)")
    return p.parse_args(argv)


def _report(stats):
    how = stats["por_asignacion"]
    print(f"ejes: {stats['ejes']}")
    print(f"tramos: {sum(how.values())} ({', '.join(f'{k} {v}' for k, v in how.items())})")
    print(f"ejes partidos por lado: {stats['partidos']}")
    print(f"codigos sin tramo: {stats['sin_tramo']}")
    print(f"codigos sin lotes: {stats['sin_lotes']}")
    print(f"codigos con lotes lejanos: {stats['lejanos']}")


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.revision and _inside_repo(args.revision):
        print(f"error: --revision {args.revision} is inside the repository; write it elsewhere", file=sys.stderr)
        return 2
    try:
        ejes, centroids, lote_of, problems = read_gpkg(args.gpkg)
        by_name, predios, _, found = read_padron(read_table(args.padron_xlsx, sheet=PADRON_SHEET))
    except (sqlite3.Error, *INPUT_ERRORS) as e:
        print(f"input: {e}", file=sys.stderr)
        return 2
    problems += found
    if problems:
        report_problems(problems)
        return 2
    rows, stats = assign(ejes, by_name, predios, centroids, lote_of, args.distancia)
    _report(stats)
    if args.revision:
        write_revision(args.revision, rows)
        print(f"revision: {len(rows)} rows")
    client = Client(args.core)
    try:
        client.login(args.email, args.password)
        if args.org is not None and (client.user or {}).get("organizationId") != args.org:
            print(f"error: the account {args.email} is not of the organization {args.org}; nothing was written",
                  file=sys.stderr)
            return 2
        create, update, delete, unchanged, orphans = plan(client.list_all(OBJECT), rows)
        if args.dry_run:
            print(f"{len(create)} to create, {len(update)} to update, {len(delete)} to delete, {unchanged} unchanged,"
                  f" {orphans} of another eje kept")
            return 0
        write(client, create, update, delete, args.workers)
    except LoadError as e:
        print(f"error /api/objects/{OBJECT}/records (row {e.fila}) -> {e.error.status}\n{e.error.body}", file=sys.stderr)
        return 1
    except CoreError as e:
        print(f"error -> {e.status}\n{e.body}", file=sys.stderr)
        return 1
    print(f"done: {len(create)} created, {len(update)} updated, {len(delete)} deleted, {unchanged} unchanged,"
          f" {orphans} of another eje kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
