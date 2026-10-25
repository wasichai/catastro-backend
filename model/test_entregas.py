"""Tests for entregas.py: the plan of an entrega, comparing a file with Core's records. Pure: no server.

Run: cd model && python3 -m unittest -v test_entregas
"""
import hashlib
import os
import tempfile
import unittest

import entregas as ent

HERE = os.path.dirname(os.path.abspath(__file__))
TYPES = ent.field_types(os.path.join(HERE, "model.json"))
PISO_FIELDS = {"piso", "seccion", "area_construida", "anio_construccion", "material"}
OBRA_FIELDS = {"codigo_vu", "cantidad", "anio_construccion", "material"}
TITULAR_FIELDS = {"codigo_municipal", "tipo_documento", "numero_documento", "nombre", "porcentaje", "condicion"}


def rec(codigo, **attrs):
    return {"id": f"p-{codigo}", "attributes": {"codigo_municipal": codigo, **attrs}}


def piso_rec(codigo, piso, seccion=None, **attrs):
    return {"id": f"c-{codigo}-{piso}-{seccion or 1}",
            "attributes": {"predio": f"p-{codigo}", "piso": piso, "seccion": seccion, **attrs}}


def obra_rec(codigo, codigo_vu, anio, **attrs):
    return {"id": f"o-{codigo}-{codigo_vu}-{anio}",
            "attributes": {"predio": f"p-{codigo}", "codigo_vu": codigo_vu, "anio_construccion": anio, **attrs}}


def titular_rec(codigo, numero_documento, nombre, **attrs):
    return {"id": f"t-{codigo}-{numero_documento}-{nombre}",
            "attributes": {"predio": f"p-{codigo}", "numero_documento": numero_documento, "nombre": nombre, **attrs}}


def state(predios=(), construcciones=(), obras=(), titulares=()):
    return ent.CoreState(list(predios), list(construcciones), list(obras), list(titulares))


def ficha(codigo, fila=2, **attrs):
    return fila, {"codigo_municipal": codigo, **attrs}


def piso(codigo, numero, seccion=None, fila=2, **attrs):
    return fila, codigo, {"piso": numero, "seccion": seccion, **attrs}


def obra(codigo, codigo_vu, anio, fila=2, **attrs):
    return fila, codigo, {"codigo_vu": codigo_vu, "anio_construccion": anio, **attrs}


def titular(codigo, numero_documento, nombre, fila=2, **attrs):
    return fila, codigo, {"numero_documento": numero_documento, "nombre": nombre, **attrs}


def plan_of(core, fichas=(), pisos=(), obras=(), titulares=None, present=(), with_pisos=True, piso_fields=PISO_FIELDS,
            obra_fields=OBRA_FIELDS, titular_fields=TITULAR_FIELDS, **flags):
    present = ent.Present(set(present) | {"codigo_municipal"}, set(piso_fields), set(obra_fields) if obras else set(),
                          set(titular_fields) if titulares is not None else set())
    return ent.plan_entrega(core, list(fichas), list(pisos), list(obras), present, TYPES, codigo="E-1",
                            with_pisos=with_pisos, titulares=list(titulares) if titulares is not None else None,
                            **flags)


class CodigoAndShaTests(unittest.TestCase):
    def test_a_codigo_travels_in_a_header(self):
        self.assertIsNone(ent.check_codigo("BARRIDO-2026.10:a_1"))
        for bad in ("E 1", "entrega-ñ", "", "x" * 65):
            self.assertIsNotNone(ent.check_codigo(bad), bad)

    def test_sha256_covers_every_file_in_order(self):
        paths = []
        for text in (b"fichas", b"pisos"):
            with tempfile.NamedTemporaryFile(delete=False) as f:
                f.write(text)
            self.addCleanup(os.unlink, f.name)
            paths.append(f.name)
        one = ent.sha256_of(paths)
        self.assertEqual(len(one), 64)
        self.assertEqual(ent.sha256_of(paths), one)
        self.assertNotEqual(ent.sha256_of(list(reversed(paths))), one)
        # one file: the same as sha256sum prints
        self.assertEqual(ent.sha256_of(paths[:1]), hashlib.sha256(b"fichas").hexdigest())


class SameTests(unittest.TestCase):
    def test_values_compare_by_their_model_type(self):
        self.assertTrue(ent.same(180.5, "180.50", "DECIMAL"))
        self.assertTrue(ent.same(86.0, "86", "DECIMAL"))
        self.assertTrue(ent.same("86", 86.0, "DECIMAL"))
        self.assertFalse(ent.same(86, "90", "DECIMAL"))
        self.assertTrue(ent.same(1998.0, 1998, "INTEGER"))
        self.assertTrue(ent.same("true", True, "BOOLEAN"))
        self.assertFalse(ent.same(False, True, "BOOLEAN"))
        self.assertTrue(ent.same("2026-10-01", "2026-10-01", "DATE"))
        self.assertTrue(ent.same(None, None, "TEXT"))
        self.assertFalse(ent.same("010101", None, "TEXT"))
        self.assertFalse(ent.same("01", "1", "TEXT"))

    def test_diff_only_over_present(self):
        core = {"uso": "010101", "lote": "003", "area_terreno": 180.5}
        wanted = {"uso": "020100", "lote": None, "area_terreno": "180.50"}
        self.assertEqual(ent.diff(core, wanted, {"uso", "area_terreno"}, TYPES["predio_catastral"]),
                         {"uso": ("010101", "020100")})


class PlanTests(unittest.TestCase):
    def test_a_new_ficha_is_an_alta(self):
        plan = plan_of(state(), fichas=[ficha("A", uso="010101", lote=None)], present={"uso", "lote"})
        self.assertEqual(plan.lines, ["alta A", "entrega E-1: 1 altas, 0 cambios, 0 sin cambio, 0 ausentes"])
        self.assertEqual(plan.predio_ops,
                         [("A", 2, "POST", "predio_catastral", None, {"codigo_municipal": "A", "uso": "010101"})])
        self.assertEqual((plan.counts["altas"], plan.touched, plan.writes), (1, {"A"}, 1))

    def test_an_alta_brings_its_pisos_and_obras_without_predio(self):
        plan = plan_of(state(), fichas=[ficha("A")], pisos=[piso("A", "1", area_construida="50")],
                       obras=[obra("A", "CERCOS|88", 1998, cantidad="4")])
        self.assertEqual(plan.child_ops, [
            (("A", "1", 1), 2, "POST", "construccion", None, {"piso": "1", "area_construida": "50"}),
            (("A", "CERCOS|88", "1998"), 2, "POST", "obra_complementaria", None,
             {"codigo_vu": "CERCOS|88", "anio_construccion": 1998, "cantidad": "4"}),
        ])

    def test_another_decimal_spelling_is_sin_cambio(self):
        core = state(predios=[rec("A", area_terreno=180.5)])
        plan = plan_of(core, fichas=[ficha("A", area_terreno="180.50")], present={"area_terreno"})
        self.assertIn("sin cambio A", plan.lines)
        self.assertEqual(plan.writes, 0)

    def test_another_piso_number_spelling_is_sin_cambio(self):
        core = state(predios=[rec("A")], construcciones=[piso_rec("A", "2", area_construida=86.0)])
        plan = plan_of(core, fichas=[ficha("A")], pisos=[piso("A", "2", area_construida="86")])
        self.assertEqual((plan.lines[0], plan.writes, plan.touched), ("sin cambio A", 0, set()))

    def test_a_changed_field_reports_antes_and_despues(self):
        core = state(predios=[rec("A", uso="010101", area_terreno=180.5)])
        plan = plan_of(core, fichas=[ficha("A", uso="020100", area_terreno="180.5")], present={"uso", "area_terreno"})
        self.assertIn("cambio A: uso 010101 → 020100", plan.lines)
        self.assertEqual(plan.predio_ops, [("A", 2, "PATCH", "predio_catastral", "p-A", {"uso": "020100"})])

    def test_an_absent_column_is_untouched_an_empty_cell_clears(self):
        core = state(predios=[rec("A", uso="010101", lote="003")])
        plan = plan_of(core, fichas=[ficha("A", uso=None, lote=None)], present={"uso"})
        self.assertIn("cambio A: uso 010101 → vacío", plan.lines)
        self.assertEqual(plan.predio_ops[0][5], {"uso": None})

    def test_a_later_entrega_without_the_column_leaves_the_field(self):
        core = state(predios=[rec("A", uso="010101", area_terreno=200)])
        plan = plan_of(core, fichas=[ficha("A", area_terreno="200")], present={"area_terreno"})
        self.assertEqual((plan.lines[0], plan.writes), ("sin cambio A", 0))

    def test_a_ficha_core_has_and_the_file_lacks_is_ausente_and_kept(self):
        core = state(predios=[rec("A"), rec("Z")], construcciones=[piso_rec("Z", "1")])
        plan = plan_of(core, fichas=[ficha("A")], reemplazar_pisos=True)
        self.assertIn("ausente Z", plan.lines)
        self.assertEqual(plan.counts["ausentes"], 1)
        self.assertFalse(any(op[2] == "DELETE" for op in plan.child_ops + plan.predio_ops))

    def test_a_corrected_piso_is_a_patch_by_its_key(self):
        core = state(predios=[rec("A")], construcciones=[piso_rec("A", "2", area_construida=86)])
        plan = plan_of(core, fichas=[ficha("A")], pisos=[piso("A", "2", fila=5, area_construida="90")])
        self.assertIn("cambio A piso 2/1: area_construida 86 → 90", plan.lines)
        self.assertEqual(plan.child_ops,
                         [(("A", "2", 1), 5, "PATCH", "construccion", "c-A-2-1", {"area_construida": "90"})])

    def test_a_new_seccion_is_a_post_and_a_missing_piso_is_listed(self):
        core = state(predios=[rec("A")], construcciones=[piso_rec("A", "1"), piso_rec("A", "3")])
        plan = plan_of(core, fichas=[ficha("A")], pisos=[piso("A", "1"), piso("A", "1", seccion=2)])
        self.assertEqual(plan.lines[:3], ["cambio A piso 1/2: alta", "ausente A piso 3/1",
                                          "entrega E-1: 0 altas, 1 cambios, 0 sin cambio, 0 ausentes"])
        self.assertEqual([(op[0], op[2]) for op in plan.child_ops], [(("A", "1", 2), "POST")])

    def test_reemplazar_pisos_deletes_only_in_fichas_the_file_brings(self):
        core = state(predios=[rec("A"), rec("Z")],
                     construcciones=[piso_rec("A", "1"), piso_rec("A", "2"), piso_rec("Z", "1")])
        plan = plan_of(core, fichas=[ficha("A")], reemplazar_pisos=True)
        self.assertEqual([(op[2], op[4]) for op in plan.child_ops], [("DELETE", "c-A-1-1"), ("DELETE", "c-A-2-1")])
        self.assertIn("cambio A piso 1/1: baja", plan.lines)
        self.assertEqual(plan.touched, {"A"})

    def test_reemplazar_obras_deletes_an_obra_whose_year_changed(self):
        core = state(predios=[rec("A")], obras=[obra_rec("A", "CERCOS|88", 1998, cantidad=4)])
        file_obras = [obra("A", "CERCOS|88", 1999, cantidad="4")]
        plan = plan_of(core, fichas=[ficha("A")], obras=file_obras, reemplazar_obras=True)
        self.assertEqual([(op[0], op[2]) for op in plan.child_ops],
                         [(("A", "CERCOS|88", "1999"), "POST"), (("A", "CERCOS|88", "1998"), "DELETE")])
        self.assertIn("cambio A obra CERCOS|88/1999: alta", plan.lines)
        self.assertIn("cambio A obra CERCOS|88/1998: baja", plan.lines)
        without = plan_of(core, fichas=[ficha("A")], obras=file_obras)
        self.assertIn("ausente A obra CERCOS|88/1998", without.lines)
        self.assertFalse(any(op[2] == "DELETE" for op in without.child_ops))

    def test_a_ficha_whose_only_change_is_a_piso_is_a_cambio_and_touched(self):
        core = state(predios=[rec("A", uso="010101")], construcciones=[piso_rec("A", "2", area_construida=86)])
        plan = plan_of(core, fichas=[ficha("A", uso="010101")], pisos=[piso("A", "2", area_construida="90")],
                       present={"uso"})
        self.assertEqual((plan.counts["cambios"], plan.touched), (1, {"A"}))
        self.assertEqual(plan.predio_ops, [])

    def test_without_pisos_file_pisos_are_not_compared(self):
        core = state(predios=[rec("A")], construcciones=[piso_rec("A", "2", area_construida=86)])
        plan = plan_of(core, fichas=[ficha("A")], with_pisos=False, piso_fields=set())
        self.assertEqual((plan.lines[0], plan.child_ops), ("sin cambio A", []))

    def test_a_column_the_pisos_file_lacks_is_not_compared(self):
        core = state(predios=[rec("A")], construcciones=[piso_rec("A", "2", material="ADOBE", area_construida=86)])
        plan = plan_of(core, fichas=[ficha("A")], pisos=[piso("A", "2", area_construida="86")],
                       piso_fields={"piso", "area_construida"})
        self.assertEqual(plan.writes, 0)

    def test_a_changed_vinculo_is_a_cambio(self):
        core = state(predios=[rec("A", vinculo_revisado=False)])
        plan = plan_of(core, fichas=[ficha("A", vinculo_revisado=True)], present={"vinculo_revisado"})
        self.assertIn("cambio A: vinculo_revisado False → True", plan.lines)

    def test_the_summary_line(self):
        core = state(predios=[rec("B", uso="010101"), rec("C", uso="010101"), rec("Z")])
        plan = plan_of(core, fichas=[ficha("A", 2), ficha("B", 3, uso="020100"), ficha("C", 4, uso="010101")],
                       present={"uso"})
        self.assertEqual(plan.lines, ["alta A", "cambio B: uso 010101 → 020100", "sin cambio C", "ausente Z",
                                      "entrega E-1: 1 altas, 1 cambios, 1 sin cambio, 1 ausentes"])
        self.assertEqual(plan.counts, {"altas": 1, "cambios": 1, "sin_cambio": 1, "ausentes": 1})
        self.assertEqual(plan.touched, {"A", "B"})


class ReadCoreTests(unittest.TestCase):
    def test_read_core_lists_the_three_objects(self):
        class Client:
            def list_all(self, name):
                return [{"id": name, "attributes": {}}]
        core = ent.read_core(Client())
        self.assertEqual(([r["id"] for r in core.predios], [r["id"] for r in core.construcciones],
                          [r["id"] for r in core.obras], core.titulares),
                         (["predio_catastral"], ["construccion"], ["obra_complementaria"], []))

    def test_read_core_lists_titulares_only_when_asked(self):
        class Client:
            def list_all(self, name):
                return [{"id": name, "attributes": {}}]
        self.assertEqual(ent.read_core(Client(), titulares=True).titulares, [{"id": "titular_catastral", "attributes": {}}])
        self.assertEqual(ent.read_core(Client(), titulares=False).titulares, [])


class TitularKeyTests(unittest.TestCase):
    def test_the_key_is_predio_document_or_empty_and_collapsed_upper_cased_name(self):
        self.assertEqual(ent.titular_key("p-1", {"numero_documento": "00412345", "nombre": "ana  perez"}),
                         ("p-1", "00412345", "ANA PEREZ"))
        self.assertEqual(ent.titular_key("p-1", {"numero_documento": None, "nombre": "Luis Rojas"}),
                         ("p-1", "", "LUIS ROJAS"))


class TitularPlanTests(unittest.TestCase):
    """Titulares in the entrega plan: created and patched like any child, never deleted, and the lines never carry
    a name or a document (Ley 29733 and c3's Review Focus)."""

    def test_without_a_titulares_file_titulares_are_not_compared(self):
        core = state(predios=[rec("A")], titulares=[titular_rec("A", "1", "ANA")])
        plan = plan_of(core, fichas=[ficha("A")])
        self.assertEqual((plan.lines[0], plan.child_ops), ("sin cambio A", []))

    def test_a_missing_titular_of_an_existing_ficha_is_an_alta_without_a_value(self):
        core = state(predios=[rec("A")])
        plan = plan_of(core, fichas=[ficha("A")], titulares=[titular("A", "1", "ANA PEREZ", fila=7, condicion="PROPIETARIO")])
        self.assertIn("cambio A titular fila 7: alta", plan.lines)
        self.assertEqual([op[:4] for op in plan.child_ops], [(("A", "1", "ANA PEREZ"), 7, "POST", "titular_catastral")])
        self.assertNotIn("ANA", " ".join(plan.lines))

    def test_an_alta_ficha_brings_its_titulares_without_a_line(self):
        plan = plan_of(state(), fichas=[ficha("A")], titulares=[titular("A", "1", "ANA")])
        self.assertEqual(plan.lines, ["alta A", "entrega E-1: 1 altas, 0 cambios, 0 sin cambio, 0 ausentes"])
        self.assertEqual(len(plan.child_ops), 1)

    def test_a_changed_porcentaje_is_a_patch_naming_only_the_field(self):
        core = state(predios=[rec("A")], titulares=[titular_rec("A", "1", "ANA", porcentaje=50)])
        plan = plan_of(core, fichas=[ficha("A")], titulares=[titular("A", "1", "ANA", fila=9, porcentaje="100")])
        self.assertIn("cambio A titular fila 9: porcentaje", plan.lines)
        self.assertNotIn("50", " ".join(plan.lines))
        self.assertNotIn("100", " ".join(plan.lines))
        self.assertEqual(plan.child_ops, [(("A", "1", "ANA"), 9, "PATCH", "titular_catastral",
                                          "t-A-1-ANA", {"porcentaje": "100"})])

    def test_a_titular_core_has_and_the_file_lacks_is_kept_and_not_even_listed(self):
        core = state(predios=[rec("A")], titulares=[titular_rec("A", "1", "ANA")])
        plan = plan_of(core, fichas=[ficha("A")], titulares=[])
        self.assertEqual((plan.lines[0], plan.child_ops), ("sin cambio A", []))
        self.assertNotIn("ANA", " ".join(plan.lines))

    def test_an_unchanged_titular_patches_nothing(self):
        core = state(predios=[rec("A")], titulares=[titular_rec("A", "1", "ANA", condicion="PROPIETARIO")])
        plan = plan_of(core, fichas=[ficha("A")], titulares=[titular("A", "1", "ANA", condicion="PROPIETARIO")])
        self.assertEqual((plan.lines[0], plan.child_ops), ("sin cambio A", []))

    def test_a_titular_only_change_makes_the_ficha_a_cambio_and_touched(self):
        core = state(predios=[rec("A")], titulares=[titular_rec("A", "1", "ANA", porcentaje=50)])
        plan = plan_of(core, fichas=[ficha("A")], titulares=[titular("A", "1", "ANA", porcentaje="100")])
        self.assertEqual((plan.counts["cambios"], plan.touched), (1, {"A"}))


if __name__ == "__main__":
    unittest.main()
