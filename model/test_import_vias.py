"""Tests for import_vias.py: the GeoPackage reader (header and WKB by hand), UTM 18S to WGS84, the assignment by name
and by closeness per side, and the idempotent upsert into tramo_via. Every fixture is made up here: a small gpkg and
a padrón xlsx written in a temp dir.

Run: cd model && python3 -m unittest -v
"""
import csv
import os
import sqlite3
import struct
import tempfile
import unittest

import import_vias as iv
from fake_core import FakeCore
from helpers import run, write_xlsx_sheets

# ---- fixture writers ----


def wkb_line(coords, little=True, z=False):
    o = "<" if little else ">"
    points = b"".join(struct.pack(o + ("ddd" if z else "dd"), *((x, y, 7.0) if z else (x, y))) for x, y in coords)
    return bytes([1 if little else 0]) + struct.pack(o + "II", 1002 if z else 2, len(coords)) + points


def wkb_multi(kind, parts, little=True):
    o = "<" if little else ">"
    return bytes([1 if little else 0]) + struct.pack(o + "II", kind, len(parts)) + b"".join(parts)


def wkb_polygon(rings, little=True):
    o = "<" if little else ">"
    body = b"".join(struct.pack(o + "I", len(r)) + b"".join(struct.pack(o + "dd", x, y) for x, y in r) for r in rings)
    return bytes([1 if little else 0]) + struct.pack(o + "II", 3, len(rings)) + body


def gp(wkb, envelope=1, little=True, srs=32718, empty=False):
    o = "<" if little else ">"
    flags = (1 if little else 0) | (envelope << 1) | (0x10 if empty else 0)
    doubles = (0, 4, 6, 6, 8)[envelope]
    return b"GP" + bytes([0, flags]) + struct.pack(o + "i", srs) + struct.pack(o + "d" * doubles, *[0.0] * doubles) + wkb


def square(cx, cy, half=5.0):
    return [[(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half),
             (cx - half, cy - half)]]


def eje(fid, nom_via, cod_via, blob, tip_via="01", abr_tvia="CA."):
    return {"fid": fid, "geom": blob, "id_via": f"V{fid}", "ubigeo": "110101", "cod_via": cod_via, "tip_via": tip_via,
            "abr_tvia": abr_tvia, "nom_via": nom_via, "nom_alt": None, "con_den": None, "fuente": "PRUEBA"}


def east(k, length=100.0):
    """A tramo going east, 1 km apart from the others so their lotes never meet."""
    x = 420000.0 + 1000 * k
    return [(x, 8445000.0), (x + length, 8445000.0)]


def x_of(k, dx):
    return 420000.0 + 1000 * k + dx


EJES = [
    eje(1, "CA. LOS ALAMOS", "001", gp(wkb_line(east(0)))),
    # big-endian, an xyz envelope, as a MultiLineString of one part
    eje(2, "AV. GRAU", "002", gp(wkb_multi(5, [wkb_line(east(1), little=False)], little=False), envelope=2,
                                 little=False), abr_tvia="AV."),
    eje(3, "JR. LIMA", "003", gp(wkb_line(east(2)), envelope=0)),
    eje(4, "SIN NOMBRE", "004", gp(wkb_line(east(3)))),
    eje(5, "CA. DESCONOCIDA", "005", gp(wkb_line(east(4)))),
    eje(6, "JR. LIMA", "006", gp(wkb_line(east(5)))),
    # an ISO LineString Z with an xyzm envelope
    eje(7, "CA. SAN JUAN", "007", gp(wkb_line(east(6), z=True), envelope=4)),
    eje(8, "CA. SAN JUAN", "008", gp(wkb_line(east(7)))),
]
# lote id -> its centroid (a 10 m square around it). north of an eastward tramo is its left
LOTES = {
    "LG1": (x_of(1, 50), 8445015.0), "LG2": (x_of(1, 50), 8444985.0),
    "LL1a": (x_of(2, 30), 8445012.0), "LL1b": (x_of(2, 70), 8444988.0), "LL2": (x_of(2, 50), 8445200.0),
    "LSJ": (x_of(6, 50), 8445010.0),
}
PADRON_PREDIAL = [("PG1", "LG1"), ("PG2", "LG2"), ("PL1a", "LL1a"), ("PL1b", "LL1b"), ("PL2", "LL2"), ("PSJ", "LSJ")]
PADRON_HEADER = ["codigo_predio", "codigo_de_via", "nombre_de_la_via", "tipo_predio", "arancel"]
PADRON = [
    ["PA1", "A-1", "CALLE LOS ÁLAMOS", "1", "10"],
    # a rústico of the same name does not make it ambiguous
    ["PR1", "R-1", "LOS ALAMOS", "2", "0"],
    ["PG1", "G-01", "AV. GRAU", "1", "20"],
    ["PG2", "G-02", "AV. GRAU", "1.0", "21"],
    ["PL1a", "L-1", "JR LIMA", "1", "30"],
    ["PL1b", "L-1", "JR LIMA", "1", "30"],
    ["PL2", "L-2", "JR.  LIMA", "1", "31"],
    ["PSJ", "SJ", "CA. SAN JUAN", "1", "40"],
    ["PN", "NADA", "CA. NINGUNA", "1", "50"],
]


def write_gpkg(testcase, ejes=EJES, lotes=LOTES, padron_predial=PADRON_PREDIAL, eje_srs=32718, lote_blobs=None):
    fd, path = tempfile.mkstemp(suffix=".gpkg")
    os.close(fd)
    testcase.addCleanup(os.unlink, path)
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, geometry_type_name TEXT,
                                            srs_id INTEGER, z INTEGER, m INTEGER);
        CREATE TABLE cf_eje_vial (fid INTEGER PRIMARY KEY, geom BLOB, id_via TEXT, ubigeo TEXT, cod_via TEXT,
                                  tip_via TEXT, abr_tvia TEXT, nom_via TEXT, nom_alt TEXT, con_den TEXT, fuente TEXT);
        CREATE TABLE cf_lotes_pol (fid INTEGER PRIMARY KEY, geom BLOB, id_lote_p TEXT);
        CREATE TABLE padron_predial (fid INTEGER PRIMARY KEY, cod_predio TEXT, id_lote_p_vinculado TEXT);
    """)
    con.execute("INSERT INTO gpkg_geometry_columns VALUES ('cf_eje_vial', 'geom', 'MULTILINESTRING', ?, 0, 0)", (eje_srs,))
    con.execute("INSERT INTO gpkg_geometry_columns VALUES ('cf_lotes_pol', 'geom', 'MULTIPOLYGON', 32718, 0, 0)")
    columns = list(EJES[0])
    con.executemany(f"INSERT INTO cf_eje_vial ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                    [tuple(e[c] for c in columns) for e in ejes])
    blobs = lote_blobs or {k: gp(wkb_multi(6, [wkb_polygon(square(*c))])) for k, c in lotes.items()}
    con.executemany("INSERT INTO cf_lotes_pol (id_lote_p, geom) VALUES (?, ?)", [(k, b) for k, b in blobs.items()])
    con.executemany("INSERT INTO padron_predial (cod_predio, id_lote_p_vinculado) VALUES (?, ?)", padron_predial)
    con.commit()
    con.close()
    return path


def write_padron(testcase, rows=PADRON, header=PADRON_HEADER):
    return write_xlsx_sheets(testcase, {"resumen": (["x"], [["1"]]), "padron": (header, rows)})


# ---- units ----


class GpkgTests(unittest.TestCase):
    LINE = [(1.5, 2.5), (3.0, 4.0)]

    def test_each_envelope_size_and_byte_order(self):
        for envelope in range(5):
            for little in (True, False):
                blob = gp(wkb_line(self.LINE, little=little), envelope=envelope, little=little)
                self.assertEqual(iv.parse_wkb(iv.gpkg_wkb(blob)), {"type": "LineString", "coordinates": [[1.5, 2.5], [3.0, 4.0]]})

    def test_empty_and_bad_headers(self):
        self.assertIsNone(iv.gpkg_wkb(gp(b"", empty=True)))
        self.assertIsNone(iv.gpkg_wkb(None))
        with self.assertRaises(iv.GpkgError):
            iv.gpkg_wkb(b"XX\x00\x01\x00\x00\x00\x00")
        with self.assertRaises(iv.GpkgError):
            iv.gpkg_wkb(b"GP\x00" + bytes([5 << 1]) + b"\x00" * 4)

    def test_multilinestring_z_and_ewkb(self):
        multi = wkb_multi(5, [wkb_line(self.LINE, z=True), wkb_line(self.LINE, little=False)])
        self.assertEqual(iv.parse_wkb(multi)["coordinates"], [[[1.5, 2.5], [3.0, 4.0]]] * 2)
        # EWKB: a LineString with the Z and SRID flags, the srid before the points
        ewkb = (b"\x01" + struct.pack("<I", 2 | 0x80000000 | 0x20000000) + struct.pack("<i", 32718) +
                struct.pack("<I", 2) + struct.pack("<dddddd", 1.5, 2.5, 9, 3.0, 4.0, 9))
        self.assertEqual(iv.parse_wkb(ewkb)["coordinates"], [[1.5, 2.5], [3.0, 4.0]])

    def test_lines_of_only_takes_lines(self):
        self.assertEqual(iv.lines_of({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}), [[[0, 0], [1, 1]]])
        self.assertIsNone(iv.lines_of({"type": "Polygon", "coordinates": []}))
        self.assertIsNone(iv.lines_of({"type": "LineString", "coordinates": [[0, 0]]}))

    def test_centroid_of_a_square_with_a_hole_and_of_two_parts(self):
        holed = {"type": "Polygon", "coordinates": square(10, 20, 5) + square(12, 20, 1)}
        cx, cy = iv.centroid(holed)
        self.assertAlmostEqual(cx, (100 * 10 - 4 * 12) / 96)
        self.assertAlmostEqual(cy, 20)
        two = {"type": "MultiPolygon", "coordinates": [square(0, 0, 1), square(10, 0, 1)]}
        self.assertEqual(tuple(round(v, 9) for v in iv.centroid(two)), (5.0, 0.0))
        self.assertIsNone(iv.centroid({"type": "LineString", "coordinates": []}))


class ProjectionTests(unittest.TestCase):
    def test_utm_18s_matches_postgis(self):
        # ST_Transform(ST_SetSRID(ST_MakePoint(x, y), 32718), 4326) on PostGIS 3
        for (x, y), (lon, lat) in [((420000, 8445000), (-75.74099322028849, -14.064631781194889)),
                                   ((500000, 10000000), (-75.0, 0.0)),
                                   ((350123.45, 8200987.6), (-76.40258659033623, -16.26725910757533)),
                                   ((660000, 8900000), (-73.540467697997, -9.947861584432362))]:
            got = iv.utm_to_wgs84(x, y)
            self.assertAlmostEqual(got[0], lon, places=9)
            self.assertAlmostEqual(got[1], lat, places=9)


class NameTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(iv.normalize("CA. Los  Álamos"), "LOS ALAMOS")
        self.assertEqual(iv.normalize("AV. AVENIDA GRAU"), "GRAU")
        self.assertEqual(iv.normalize("JR.LIMA"), "LIMA")
        self.assertEqual(iv.normalize("PROL. GRAU"), "PROL GRAU")
        self.assertEqual(iv.normalize("Prolongación Grau"), "PROL GRAU")
        self.assertEqual(iv.normalize("AVENIDA GRAU"), iv.normalize("AVDA. GRAU"))
        self.assertEqual(iv.normalize("28 DE JULIO"), "28 DE JULIO")
        # a name that is only its type stays as it is
        self.assertEqual(iv.normalize("AV."), "AV")
        for empty in (None, "", "  ", "SIN NOMBRE", "S/N", "CA. S/N", "sin nombre"):
            self.assertIsNone(iv.normalize(empty), empty)


class SideTests(unittest.TestCase):
    LINE = [[(0.0, 0.0), (100.0, 0.0)]]

    def test_left_is_counter_clockwise_of_the_direction(self):
        self.assertEqual(iv.side_and_distance(self.LINE, (50, 10)), (10.0, iv.IZQUIERDO))
        self.assertEqual(iv.side_and_distance(self.LINE, (50, -12)), (12.0, iv.DERECHO))
        reverse = [[(100.0, 0.0), (0.0, 0.0)]]
        self.assertEqual(iv.side_and_distance(reverse, (50, 10))[1], iv.DERECHO)

    def test_beyond_an_end_or_on_the_line_does_not_count(self):
        self.assertIsNone(iv.side_and_distance(self.LINE, (-5, 10)))
        self.assertIsNone(iv.side_and_distance(self.LINE, (105, -10)))
        self.assertIsNone(iv.side_and_distance(self.LINE, (50, 0)))
        # past an inner vertex it is still the tramo
        bent = [[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]]
        self.assertEqual(iv.side_and_distance(bent, (110, -10))[1], iv.DERECHO)


# ---- the run ----


class AssignTests(unittest.TestCase):
    def setUp(self):
        ejes, centroids, lote_of, problems = iv.read_gpkg(write_gpkg(self))
        self.assertEqual(problems, [])
        from tabular import read_table
        by_name, predios, _, problems = iv.read_padron(read_table(write_padron(self), sheet="padron"))
        self.assertEqual(problems, [])
        self.rows, self.stats = iv.assign(ejes, by_name, predios, centroids, lote_of)
        self.by_clave = {a["clave"]: a for a, _ in self.rows}

    def test_each_tramo_and_side(self):
        got = {clave: (a["id_aranc"], a["asignacion"]) for clave, a in self.by_clave.items()}
        self.assertEqual(got, {
            "110101|1|AMBOS": ("A-1", "NOMBRE_UNICO"),
            "110101|2|IZQUIERDO": ("G-01", "CERCANIA"),
            "110101|2|DERECHO": ("G-02", "CERCANIA"),
            "110101|3|AMBOS": ("L-1", "CERCANIA"),
            "110101|4|AMBOS": (None, "SIN_ARANCEL"),
            "110101|5|AMBOS": (None, "SIN_ARANCEL"),
            "110101|6|AMBOS": (None, "SIN_ARANCEL"),
            "110101|7|AMBOS": ("SJ", "CERCANIA"),
            "110101|8|AMBOS": (None, "SIN_ARANCEL"),
        })

    def test_the_row_carries_the_eje(self):
        self.assertEqual(self.by_clave["110101|2|IZQUIERDO"], {
            "clave": "110101|2|IZQUIERDO", "fid_eje": 2, "cod_via_eje": "002", "tip_via": "AV.", "nom_via": "AV. GRAU",
            "ubigeo": "110101", "fuente": "PRUEBA", "cuadra": None, "lado": "IZQUIERDO", "id_aranc": "G-01",
            "asignacion": "CERCANIA"})

    def test_the_counts(self):
        self.assertEqual(self.stats, {
            "ejes": 8, "por_asignacion": {"NOMBRE_UNICO": 1, "CERCANIA": 4, "SIN_ARANCEL": 4}, "partidos": 1, "multiparte": 0, "invertidas": 0,
            "de_un_lote": 5,
            "sin_tramo": 2, "sin_lotes": 2, "lejanos": 1})

    def test_a_lote_farther_than_the_distance_does_not_count(self):
        ejes, centroids, lote_of, _ = iv.read_gpkg(write_gpkg(self))
        from tabular import read_table
        by_name, predios, _, _ = iv.read_padron(read_table(write_padron(self), sheet="padron"))
        rows, _ = iv.assign(ejes, by_name, predios, centroids, lote_of, distancia=11)
        got = {a["clave"]: a["id_aranc"] for a, _ in rows}
        # G-01 and G-02 are 15 m away: none counts; L-1's lotes are 12 m away; SJ's 10 m
        self.assertEqual((got["110101|2|AMBOS"], got["110101|3|AMBOS"], got["110101|7|AMBOS"]), (None, None, "SJ"))


class OrientTests(unittest.TestCase):
    def test_chained_parts_follow_the_first(self):
        parts = [[(0, 0), (100, 0)], [(200, 0), (100, 0)], [(200, 0), (300, 0)]]
        oriented, flipped = iv.orient(parts)
        self.assertEqual(oriented, [[(0, 0), (100, 0)], [(100, 0), (200, 0)], [(200, 0), (300, 0)]])
        self.assertEqual(flipped, 1)

    def test_a_disjoint_part_follows_the_first_parts_direction(self):
        oriented, flipped = iv.orient([[(0, 0), (100, 0)], [(300, 5), (200, 5)]])
        self.assertEqual((oriented[1], flipped), ([(200, 5), (300, 5)], 1))
        self.assertEqual(iv.orient([[(0, 0), (1, 0)]]), ([[(0, 0), (1, 0)]], 0))


class MultipartTests(unittest.TestCase):
    """An eje digitised in two parts that run against each other: north must be one side along the whole tramo."""

    def test_two_reversed_parts_give_one_left_and_one_right_and_core_gets_them_oriented(self):
        x = 420000.0
        parts = [wkb_line([(x, 8445000.0), (x + 100, 8445000.0)]),
                 wkb_line([(x + 200, 8445000.0), (x + 100, 8445000.0)])]
        lotes = {"N1": (x + 50, 8445012.0), "N2": (x + 150, 8445012.0), "S1": (x + 50, 8444988.0),
                 "S2": (x + 150, 8444988.0)}
        predial = [("PN1", "N1"), ("PN2", "N2"), ("PS1", "S1"), ("PS2", "S2")]
        padron = [["PN1", "N-01", "AV. GRAU", "1"], ["PN2", "N-01", "AV. GRAU", "1"],
                  ["PS1", "S-02", "AV. GRAU", "1"], ["PS2", "S-02", "AV. GRAU", "1"]]
        core = FakeCore()
        self.addCleanup(core.stop)
        gpkg = write_gpkg(self, ejes=[eje(1, "AV. GRAU", "002", gp(wkb_multi(5, parts)))], lotes=lotes,
                          padron_predial=predial)
        code, out, err = run(iv.main, ["--gpkg", gpkg, "--padron-xlsx", write_padron(self, rows=padron,
                                       header=PADRON_HEADER[:4]), "--core", core.base_url])
        self.assertEqual(code, 0, err)
        self.assertIn("ejes multiparte: 1\npartes invertidas: 1", out)
        tramos = {r["attributes"]["clave"]: r for r in core.records["tramo_via"]}
        self.assertEqual({k: r["attributes"]["id_aranc"] for k, r in tramos.items()},
                         {"110101|1|IZQUIERDO": "N-01", "110101|1|DERECHO": "S-02"})
        second = tramos["110101|1|IZQUIERDO"]["geometries"]["geom"]["coordinates"][1]
        # the second part now runs west to east, like the first
        self.assertLess(second[0][0], second[1][0])


class CercaniaTests(unittest.TestCase):
    LINE = [[(0.0, 0.0), (100.0, 0.0)]]

    def test_more_lotes_beat_one_nearer_lote(self):
        lotes = {"A": [(20, 12), (50, 14), (80, 15)], "B": [(50, 5)]}
        self.assertEqual(iv.nearest_by_side(self.LINE, {"A", "B"}, lotes, 30), {iv.IZQUIERDO: ("A", 3)})

    def test_a_tie_goes_to_the_nearest(self):
        lotes = {"A": [(20, 12)], "B": [(50, 5)]}
        self.assertEqual(iv.nearest_by_side(self.LINE, {"A", "B"}, lotes, 30), {iv.IZQUIERDO: ("B", 1)})

    def test_a_segment_without_cod_via_does_not_make_the_name_ambiguous(self):
        line = [[(0.0, 0.0), (100.0, 0.0)]]
        ejes = [{**eje(1, "CA. SOLA", "001", None), "parts": line}, {**eje(2, "CA. SOLA", None, None), "parts": line}]
        rows, _ = iv.assign(ejes, {"SOLA": {"S"}}, {}, {}, {})
        self.assertEqual({a["asignacion"] for a, _ in rows}, {"NOMBRE_UNICO"})


class CliTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.stop)
        self.gpkg = write_gpkg(self)
        self.padron = write_padron(self)

    def cli(self, *extra):
        return run(iv.main, ["--gpkg", self.gpkg, "--padron-xlsx", self.padron, "--core", self.core.base_url, *extra])

    def writes(self):
        return [r for r in self.core.requests if r[0] in ("POST", "PUT", "PATCH", "DELETE") and "records" in r[1]]

    def tramos(self):
        return {r["attributes"]["clave"]: r for r in self.core.records.get("tramo_via", [])}

    def test_creates_then_a_second_run_changes_nothing(self):
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        self.assertIn("tramos: 9 (NOMBRE_UNICO 1, CERCANIA 4, SIN_ARANCEL 4)", out)
        self.assertIn("codigos con lotes lejanos: 1", out)
        self.assertIn("done: 9 created, 0 updated, 0 deleted, 0 unchanged, 0 absent from the file kept (--borrar-ausentes deletes them),"
                      " 0 of another ubigeo kept", out)
        tramos = self.tramos()
        uno = tramos["110101|1|AMBOS"]
        # None is never sent: cuadra stays out
        self.assertEqual(uno["attributes"], {"clave": "110101|1|AMBOS", "fid_eje": 1, "cod_via_eje": "001", "tip_via": "CA.",
                                             "nom_via": "CA. LOS ALAMOS", "ubigeo": "110101", "fuente": "PRUEBA",
                                             "lado": "AMBOS", "id_aranc": "A-1", "asignacion": "NOMBRE_UNICO"})
        geom = uno["geometries"]["geom"]
        self.assertEqual(geom["type"], "MultiLineString")
        self.assertAlmostEqual(geom["coordinates"][0][0][0], -75.74099322028849, places=9)
        self.assertAlmostEqual(geom["coordinates"][0][0][1], -14.064631781194889, places=9)
        self.assertNotIn("id_aranc", tramos["110101|4|AMBOS"]["attributes"])
        before = len(self.writes())
        code, out, _ = self.cli()
        self.assertIn("done: 0 created, 0 updated, 0 deleted, 9 unchanged", out)
        self.assertEqual(len(self.writes()), before)

    def stored(self, clave, fid, ubigeo="110101"):
        attributes = {"clave": clave, "fid_eje": fid, "lado": "AMBOS", "asignacion": "SIN_ARANCEL"}
        return self.core.add_record("tramo_via", {**attributes, **({"ubigeo": ubigeo} if ubigeo else {})})

    def test_a_changed_row_is_patched_a_stale_lado_deleted_and_the_rest_kept(self):
        self.cli()
        tramos = self.tramos()
        tramos["110101|3|AMBOS"]["attributes"]["id_aranc"] = "OTRO"
        # moved by ~1 m: beyond the tolerance
        tramos["110101|7|AMBOS"]["geometries"]["geom"]["coordinates"][0][0][0] += 1e-5
        stale = self.stored("110101|2|AMBOS", 2)
        self.stored("110101|99|AMBOS", 99)
        # another ubigeo's fid 1 is another eje: never touched
        self.stored("110102|1|AMBOS", 1, ubigeo="110102")
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        self.assertIn("done: 0 created, 2 updated, 1 deleted, 7 unchanged, 1 absent from the file kept"
                      " (--borrar-ausentes deletes them), 1 of another ubigeo kept", out)
        tramos = self.tramos()
        self.assertEqual(tramos["110101|3|AMBOS"]["attributes"]["id_aranc"], "L-1")
        self.assertNotIn("110101|2|AMBOS", tramos)
        self.assertIn("110101|99|AMBOS", tramos)
        self.assertIn("110102|1|AMBOS", tramos)
        self.assertIn(("DELETE", f"/api/objects/tramo_via/records/{stale['id']}"),
                      [(m, p) for m, p, _, _ in self.writes()])

    def test_borrar_ausentes_deletes_the_ubigeos_rows_the_file_lacks_and_dry_run_says_so(self):
        self.cli()
        absent = self.stored("110101|99|AMBOS", 99)
        self.stored("110102|99|AMBOS", 99, ubigeo="110102")
        before = len(self.writes())
        code, out, err = self.cli("--borrar-ausentes", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("0 to create, 0 to update, 1 to delete, 9 unchanged, 1 absent from the file deleted,"
                      " 1 of another ubigeo kept", out)
        self.assertEqual(len(self.writes()), before)
        code, out, err = self.cli("--borrar-ausentes")
        self.assertEqual(code, 0, err)
        self.assertIn("done: 0 created, 0 updated, 1 deleted", out)
        self.assertNotIn("110101|99|AMBOS", self.tramos())
        self.assertIn("110102|99|AMBOS", self.tramos())
        self.assertEqual(self.writes()[-1][:2], ("DELETE", f"/api/objects/tramo_via/records/{absent['id']}"))

    def test_dry_run_reads_and_writes_nothing(self):
        code, out, err = self.cli("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("9 to create, 0 to update, 0 to delete, 0 unchanged, 0 absent", out)
        self.assertEqual(self.writes(), [])
        self.assertNotIn("tramo_via", self.core.records)

    def test_the_revision_csv_and_where_it_may_go(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "revision.csv")
            code, out, err = self.cli("--dry-run", "--revision", path)
            self.assertEqual(code, 0, err)
            with open(path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(list(rows[0]), ["cod_via_eje", "fid_eje", "lado", "id_aranc", "asignacion"])
        self.assertEqual(len(rows), 9)
        self.assertIn({"cod_via_eje": "002", "fid_eje": "2", "lado": "DERECHO", "id_aranc": "G-02",
                       "asignacion": "CERCANIA"}, rows)
        before = len(self.core.requests)
        inside = os.path.join(iv.HERE, "revision-no.csv")
        code, _, err = self.cli("--revision", inside)
        self.assertEqual(code, 2)
        self.assertIn("inside the repository", err)
        self.assertFalse(os.path.exists(inside))
        self.assertEqual(len(self.core.requests), before)

    def test_org_must_be_the_accounts(self):
        self.core.login_response = {"token": "t", "user": {"organizationId": "org-ica"}}
        code, _, err = self.cli("--org", "org-otra")
        self.assertEqual(code, 2)
        self.assertIn("--org expects the organization's id", err)
        self.assertIn("is of the organization org-ica, not org-otra", err)
        self.assertEqual(self.writes(), [])
        code, out, err = self.cli("--org", "org-ica")
        self.assertEqual(code, 0, err)
        self.assertIn("done: 9 created", out)

    def test_bad_inputs_exit_2_and_send_nothing(self):
        self.gpkg = write_gpkg(self, eje_srs=4326)
        code, _, err = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("cf_eje_vial: srs 4326, expected 32718", err)
        point = struct.pack("<BIdd", 1, 1, 1.0, 2.0)
        self.gpkg = write_gpkg(self, ejes=[eje(1, "CA. X", "001", gp(point))])
        code, _, err = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("cf_eje_vial fid 1: geometry is not a LineString or MultiLineString", err)
        self.gpkg = write_gpkg(self)
        self.padron = write_padron(self, header=["codigo_predio", "codigo_de_via", "tipo_predio"],
                                   rows=[["P", "C", "1"]])
        code, _, err = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("sheet padron: no column nombre_de_la_via", err)
        self.gpkg = "/nonexistent/ica.gpkg"
        code, _, err = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("input:", err)
        self.assertEqual(self.core.requests, [])

    def test_core_refusal_exits_1(self):
        self.core.fail_on_record = "tramo_via"
        code, _, err = self.cli()
        self.assertEqual(code, 1)
        self.assertIn("-> 400", err)


if __name__ == "__main__":
    unittest.main()
