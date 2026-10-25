"""The plan of an entrega: what a levantamiento file changes in Core's catastro (ADR-013), and how it is written.

The plan is pure except read_core: it compares the parsed fichas, pisos and obras (import_fichas' tuples) with Core's
records and returns a Plan, the report lines and the write_all ops (tabular.py) that would bring Core to the file. The
rules (contexto-comun.md):
  - only the columns the file has are compared; an empty cell in one clears the field, a missing column is untouched
  - values compare by their model.json type, so Core's 180.5 is the file's 180.50
  - a ficha Core has and the file lacks is `ausente` and kept; so are a ficha's pisos and obras the file lacks, unless
    --reemplazar-pisos / --reemplazar-obras ask to delete them (only in the fichas the file brings)
find_entrega, ensure_entrega and apply_plan write it through the record API, every write with the entrega's code as
X-Change-Reason, so wasichai's audit_log holds each ficha's history. The entrega_catastral record is created once, by
the first run that writes, with that run's summary, and never updated: a re-run with the same files completes a run that
failed half way and leaves the summary as first recorded; the same code with other files is refused (EntregaError).
Stdlib only, and no import of import_fichas (which imports the keys from here); import_lotes uses these too.
"""
import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from tabular import write_all

# the code travels as X-Change-Reason, a header: ASCII only
CODIGO = re.compile(r"[A-Za-z0-9._:-]{1,64}")

PREDIO, PISO, OBRA = "predio_catastral", "construccion", "obra_complementaria"
ENTREGA = "entrega_catastral"
SUMMARY = ("altas", "cambios", "sin_cambio", "ausentes")
TRUE = {"true", "t", "1", "si", "sí"}
FALSE = {"false", "f", "0", "no"}
EMPTY = "vacío"


def check_codigo(codigo):
    """None when the code can be an entrega's, else the error text."""
    if codigo is not None and CODIGO.fullmatch(codigo):
        return None
    return f"entrega '{codigo}': expected 1 to 64 characters among A-Z a-z 0-9 . _ : -"


def sha256_of(paths):
    """Sha256 of the bytes of every file, in the given order (the CLI's); for one file, what sha256sum prints."""
    digest = hashlib.sha256()
    for path in paths:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 16), b""):
                digest.update(block)
    return digest.hexdigest()


def field_types(model_path):
    """object -> field -> model.json type (TEXT, DECIMAL, INTEGER, BOOLEAN, DATE, ENUM...)."""
    with open(model_path, encoding="utf-8") as f:
        objects = json.load(f)["objects"]
    return {o["name"]: {field["name"]: field["type"] for field in o["fields"]} for o in objects}


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


def _normal(value, ftype):
    """A value as its type compares: Decimal, int, bool, ISO date text or text; None (or blank) for no value."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        if ftype == "DECIMAL":
            return Decimal(str(value))
        if ftype == "INTEGER":
            number = Decimal(str(value))
            return int(number) if number == number.to_integral_value() else number
    except InvalidOperation:
        return str(value)
    if ftype == "BOOLEAN":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        return True if text in TRUE else False if text in FALSE else text
    if ftype == "DATE":
        return str(value)[:10]
    return str(value)


def same(a, b, ftype):
    return _normal(a, ftype) == _normal(b, ftype)


def show(value, ftype):
    """A value as a report line prints it."""
    value = _normal(value, ftype)
    if value is None:
        return EMPTY
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def diff(core_attrs, wanted, present, types):
    """field -> (antes, después) for the fields in `present` whose values differ, in the model's order. `types` is
    the object's field -> type; a present field missing from `wanted` is None (it clears)."""
    return {field: (core_attrs.get(field), wanted.get(field)) for field, ftype in types.items()
            if field in present and not same(core_attrs.get(field), wanted.get(field), ftype)}


@dataclass
class CoreState:
    predios: list
    construcciones: list
    obras: list
    titulares: list


def read_core(client, titulares=False):
    """Every predio, construccion and obra in Core. Titulares are not read yet (titular_catastral comes later)."""
    return CoreState(client.list_all(PREDIO), client.list_all(PISO), client.list_all(OBRA), [])


@dataclass
class Present:
    """The fields whose column each file brings (import_fichas.present_fields)."""
    fichas: set
    pisos: set
    obras: set
    titulares: set


@dataclass
class Plan:
    """Report lines, counts per ficha, and write_all ops. A predio op's key is its codigo; a child op's key is its
    natural key with the codigo first, and a child POST lacks `predio`, which the apply fills from the predio ids.
    `touched` are the codes of the altas and cambios (own fields or children); `predios` are Core's predio records by
    codigo, as read for the plan."""
    lines: list
    counts: dict
    predio_ops: list
    child_ops: list
    touched: set
    predios: dict = dataclasses.field(default_factory=dict)

    @property
    def writes(self):
        return len(self.predio_ops) + len(self.child_ops)


@dataclass
class _Children:
    object_name: str
    key: object
    label: object
    in_file: dict      # codigo -> [(fila, attributes)] in file order
    in_core: dict      # codigo -> [record] in Core's order
    present: set
    reemplazar: bool
    keys: set          # the natural key's fields: equal by the key, never compared


def _piso_label(a):
    return f"piso {a['piso']}/{a.get('seccion') or 1}"


def _obra_label(a):
    return f"obra {a['codigo_vu']}/{show(a.get('anio_construccion'), 'INTEGER')}"


def _children(object_name, key, label, keys, rows, records, present, reemplazar, codigo_of):
    in_file, in_core = {}, {}
    for fila, codigo, a in rows:
        in_file.setdefault(codigo, []).append((fila, a))
    for record in records:
        codigo = codigo_of.get(relation_id(record["attributes"].get("predio")))
        if codigo is not None:
            in_core.setdefault(codigo, []).append(record)
    return _Children(object_name, key, label, in_file, in_core, present, reemplazar, keys)


def _change_lines(prefix, changes, types):
    return [f"{prefix}: {field} {show(antes, types.get(field))} → {show(despues, types.get(field))}"
            for field, (antes, despues) in changes.items()]


def _compare_children(group, codigo, ficha_fila, types):
    """(lines, ops) of one existing ficha's children of one kind."""
    lines, ops, used = [], [], set()
    have = {}
    for record in group.in_core.get(codigo, []):
        have.setdefault(group.key(codigo, record["attributes"]), record)
    compared = group.present - group.keys
    for fila, a in group.in_file.get(codigo, []):
        key = group.key(codigo, a)
        record = have.get(key)
        prefix = f"cambio {codigo} {group.label(a)}"
        if record is None:
            ops.append((key, fila, "POST", group.object_name, None, {k: v for k, v in a.items() if v is not None}))
            lines.append(f"{prefix}: alta")
            continue
        used.add(record["id"])
        changes = diff(record["attributes"], a, compared, types)
        if changes:
            ops.append((key, fila, "PATCH", group.object_name, record["id"], {f: d for f, (_, d) in changes.items()}))
            lines.extend(_change_lines(prefix, changes, types))
    for record in group.in_core.get(codigo, []):
        if record["id"] in used:
            continue
        a = record["attributes"]
        if group.reemplazar:
            ops.append((group.key(codigo, a), ficha_fila, "DELETE", group.object_name, record["id"], None))
            lines.append(f"cambio {codigo} {group.label(a)}: baja")
        else:
            lines.append(f"ausente {codigo} {group.label(a)}")
    return lines, ops


def plan_entrega(core, fichas, pisos, obras, present, types, *, codigo, with_pisos, reemplazar_pisos=False,
                 reemplazar_obras=False):
    """The Plan of an entrega named `codigo`. Pisos are compared when `with_pisos` (a pisos file was given); obras
    when the obras file brought columns or `reemplazar_obras` asks to replace them. Lines go in the fichas' file
    order, each ficha's children right after it, then the ausentes, then the summary."""
    predios = {r["attributes"]["codigo_municipal"]: r for r in core.predios}
    plan = Plan([], dict.fromkeys(SUMMARY, 0), [], [], set(), predios)
    codigo_of = {str(r["id"]): c for c, r in predios.items()}
    groups = []
    if with_pisos:
        groups.append(_children(PISO, piso_key, _piso_label, {"piso", "seccion"}, pisos, core.construcciones,
                                present.pisos, reemplazar_pisos, codigo_of))
    if present.obras or reemplazar_obras:
        groups.append(_children(OBRA, obra_key, _obra_label, {"codigo_vu", "anio_construccion"}, obras, core.obras,
                                present.obras, reemplazar_obras, codigo_of))
    in_file = set()
    for fila, a in fichas:
        cod = a["codigo_municipal"]
        in_file.add(cod)
        record = predios.get(cod)
        if record is None:
            attributes = {k: v for k, v in a.items() if (k in present.fichas or k == "codigo_municipal") and v is not None}
            plan.predio_ops.append((cod, fila, "POST", PREDIO, None, attributes))
            for group in groups:
                plan.child_ops.extend((group.key(cod, c), c_fila, "POST", group.object_name, None,
                                       {k: v for k, v in c.items() if v is not None})
                                      for c_fila, c in group.in_file.get(cod, []))
            plan.lines.append(f"alta {cod}")
            plan.counts["altas"] += 1
            plan.touched.add(cod)
            continue
        changes = diff(record["attributes"], a, present.fichas - {"codigo_municipal"}, types[PREDIO])
        if changes:
            plan.predio_ops.append((cod, fila, "PATCH", PREDIO, record["id"], {f: d for f, (_, d) in changes.items()}))
        child_lines, child_ops = [], []
        for group in groups:
            lines, ops = _compare_children(group, cod, fila, types[group.object_name])
            child_lines += lines
            child_ops += ops
        plan.child_ops += child_ops
        if changes or child_ops:
            plan.lines += _change_lines(f"cambio {cod}", changes, types[PREDIO]) + child_lines
            plan.counts["cambios"] += 1
            plan.touched.add(cod)
        else:
            plan.lines += [f"sin cambio {cod}"] + child_lines
            plan.counts["sin_cambio"] += 1
    for cod in predios:
        if cod not in in_file:
            plan.lines.append(f"ausente {cod}")
            plan.counts["ausentes"] += 1
    c = plan.counts
    plan.lines.append(f"entrega {codigo}: {c['altas']} altas, {c['cambios']} cambios, {c['sin_cambio']} sin cambio, "
                      f"{c['ausentes']} ausentes")
    return plan


class EntregaError(Exception):
    """An entrega code already names a delivery of other files."""


def find_entrega(client, codigo):
    """The entrega_catastral record with that code, or None. Filtered by codigo, and checked here too."""
    return next((r for r in client.list_all(ENTREGA, codigo=codigo) if r["attributes"].get("codigo") == codigo), None)


def ensure_entrega(client, codigo, *, fecha_corte, fuente, descripcion, sha, counts):
    """The id of the entrega `codigo`: created (reason = codigo) with this run's summary when Core lacks it, kept as it
    is when its archivo_sha256 is `sha`. A count `counts` lacks is left empty."""
    record = find_entrega(client, codigo)
    if record is None:
        attributes = {"codigo": codigo, "fecha_corte": fecha_corte, "fuente": fuente, "descripcion": descripcion,
                      "archivo_sha256": sha, **{k: counts.get(k) for k in SUMMARY}}
        _, record = client.post(f"/api/objects/{ENTREGA}/records",
                                {"attributes": {k: v for k, v in attributes.items() if v is not None}}, reason=codigo)
        return record["id"]
    check_same_files(record, sha)
    return record["id"]


def check_same_files(record, sha):
    """Raises EntregaError when the entrega `record` (find_entrega's; None passes) was loaded from files other than
    the ones whose sha256 is `sha`. A loader checks it before reading Core, so even a dry-run is refused."""
    if record is not None and record["attributes"].get("archivo_sha256") != sha:
        a = record["attributes"]
        raise EntregaError(f"entrega {a.get('codigo')} was loaded from other files (sha256 {a.get('archivo_sha256')}, "
                           f"these are {sha}): a new delivery needs its own code")


def apply_plan(client, plan, entrega_id, reason, workers):
    """Writes the plan with X-Change-Reason `reason`: the predios first, each POST and PATCH pointing to the entrega;
    then a PATCH of `entrega` alone on every touched predio without its own op (a change in its children), unless it
    already points there (a re-run); then the children's DELETEs, then their POSTs (under the predio's id) and PATCHes.
    The first refusal raises tabular.LoadError, and running again completes it."""
    ops = [(key, fila, method, obj, rid, {**a, "entrega": entrega_id}) for key, fila, method, obj, rid, a in plan.predio_ops]
    ids = {cod: r["id"] for cod, r in plan.predios.items()}
    ids.update(write_all(client, ops, workers, reason))
    own = {op[0] for op in plan.predio_ops}
    fila_of = {}
    for op in plan.child_ops:
        fila_of.setdefault(op[0][0], op[1])
    pointing = [(cod, fila_of[cod], "PATCH", PREDIO, ids[cod], {"entrega": entrega_id}) for cod in sorted(plan.touched - own)
                if relation_id(plan.predios[cod]["attributes"].get("entrega")) != str(entrega_id)]
    write_all(client, pointing, workers, reason)
    write_all(client, [op for op in plan.child_ops if op[2] == "DELETE"], workers, reason)
    rest = [(key, fila, method, obj, rid, {**a, "predio": ids[key[0]]} if method == "POST" else a)
            for key, fila, method, obj, rid, a in plan.child_ops if method != "DELETE"]
    write_all(client, rest, workers, reason)
