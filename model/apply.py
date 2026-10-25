#!/usr/bin/env python3
"""Apply model/model.json to a wasichai Core (catastro-backend).

Reads a JSON metadata model (objects, fields, relationships, enums), checks it
against Core's rules (--validate-only stops there) and creates it in Core via
the REST API, in file order (so relationship targets already exist), marking
each required relationship's field required (an optional one is left optional), and last the object-level
rules model.json declares (indexes, appendOnly, apiOnly). Today that is 11 objects and 5 relationships, none
append-only and one api-only (decision_brecha):
"done: 16 created, 7 updated" on an empty Core (the updates are the 7 objects with indexes), "16 skipped" on a second
run.

On a Core that already has the model it syncs instead: it adds the fields and
the ENUM options model.json has and Core lacks, drops the ENUM options it no
longer lists and no record uses (a list it changes takes model.json's order, the
options kept for being in use last), relaxes a field model.json no longer
requires and relabels one labelled differently. It never renames, retypes, makes
required or removes a field or an option in use, so imported records stay
valid. An object's indexes and appendOnly are model.json's: what differs is
set, an index only Core has is dropped. --drop switches those rules off and
tears everything down in reverse order (data included).

--dry-run prints model.json's payloads and asks Core nothing. --diff logs in
and reads the real Core, writes nothing, and prints each write the real run
would send ("would PUT /api/objects/... {...}"), then "diff: nothing pending"
or how many are: the evidence asked for before applying to a shared Core.

GEOMETRY fields (the lotes' polygons) are wasichai-gis's:
catastro-backend installs it, on PostGIS. Adapted from wasichai's
examples/gis-sample/perene/apply.py. Stdlib only. See README.md.
"""
import argparse
import json
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
# under python3 -I, as the importers run, neither the cwd nor the script's directory is on sys.path: put
# back only the latter, for core_client
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core_client import Client, CoreError  # noqa: E402

# Keyword list copied verbatim from
# wasichai-core/src/main/kotlin/wasichai/core/platform/SqlIdentifier.kt (SQL_KEYWORDS).
SQL_KEYWORDS = frozenset({
    "all", "alter", "and", "any", "array", "as", "asc", "begin", "between",
    "by", "case", "cast", "check", "column", "commit", "constraint",
    "create", "cross", "current_date", "current_time", "current_timestamp",
    "current_user", "default", "delete", "desc", "distinct", "do", "drop",
    "else", "end", "except", "exists", "false", "fetch", "for", "foreign",
    "from", "full", "grant", "group", "having", "in", "index", "inner",
    "insert", "intersect", "into", "is", "join", "key", "left", "like",
    "limit", "not", "null", "offset", "on", "or", "order", "outer",
    "primary", "references", "returning", "right", "rollback", "select",
    "session_user", "set", "some", "table", "then", "to", "true", "union",
    "unique", "update", "user", "using", "values", "view", "when", "where",
    "with",
})

# Field names Core reserves: system columns + query-param names used on list endpoints. count and after are
# SystemColumns.RESERVED since core 0.3 (keyset paging, ADR-031 D22)
RESERVED_FIELD_NAMES = frozenset({
    "id", "organization_id", "created_at", "updated_at", "created_by",
    "updated_by", "workflow_state", "version",
    "page", "size", "sort", "dir", "q", "bbox", "geometry", "limit",
    "count", "after",
})

VALID_NAME = re.compile(r"^[a-z][a-z0-9_]{0,48}$")

# Mirror Core's ENUM option regex (metadata/MetadataService.kt):
# ^[\p{L}0-9 _.-]{1,64}$ -- Unicode letters, ASCII digits, space, `_`, `.`, `-`.
# Checked per character: Python's `\w` tricks also match non-letter "word" characters.
ENUM_OPTION_EXTRA_CHARS = re.compile(r"[0-9 _.\-]")


def enum_option_valid(opt):
    if not isinstance(opt, str) or not (1 <= len(opt) <= 64):
        return False
    return all(c.isalpha() or ENUM_OPTION_EXTRA_CHARS.fullmatch(c) for c in opt)


MAX_OBJECT_NAME = 39
MAX_FIELD_NAME = 49
MAX_RELATIONSHIP_NAME = 35

# core's scalar types, plus GEOMETRY from wasichai-gis (catastro-backend installs it: the lotes)
FIELD_TYPES = frozenset({
    "TEXT", "LONG_TEXT", "INTEGER", "DECIMAL", "BOOLEAN", "DATE", "DATETIME",
    "ENUM", "EMAIL", "URL", "UUID", "GEOMETRY",
})

# an object's rules model.json declares and apply keeps in sync after the relationships: composite indexes
# (ADR-036) and append-only (ADR-040). left out of an object, they are none
RULE_KEYS = ("indexes", "appendOnly", "apiOnly")
RULES_OFF = {"indexes": [], "appendOnly": False, "apiOnly": False}

# what Core's object PUT overwrites, not leaves alone, when missing (MetadataService.updateObject: description goes
# null, pluralLabel becomes the label, enabled true). a rule PUT sends them back as Core has them, so it touches only
# the rules: an admin's description, plural or disabled object survives
OBJECT_KEYS = ("label", "pluralLabel", "description", "enabled")

# what Core does not index (FieldSets.requireIndexable): long text, and a geometry (wasichai-gis refuses to sort by one)
UNINDEXABLE_TYPES = frozenset({"LONG_TEXT", "GEOMETRY"})

# mirror wasichai-gis's GeometryFieldType: a geometry names its shape; srid 1..999999 (default 4326), 2d or 3d
GEOMETRY_TYPES = frozenset({"POINT", "LINESTRING", "POLYGON", "MULTIPOINT", "MULTILINESTRING", "MULTIPOLYGON"})


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def _check_identifier(name, kind, maxlen, label):
    """Mirror SqlIdentifier.requireValidName: shape, length, not a keyword."""
    errors = []
    if not isinstance(name, str) or not name:
        return [f"{label}: {kind} name is missing"]
    if len(name) > maxlen:
        errors.append(f"{label}: {kind} name '{name}' exceeds {maxlen} characters")
    if not VALID_NAME.fullmatch(name):
        errors.append(
            f"{label}: {kind} name '{name}' must match ^[a-z][a-z0-9_]{{0,48}}$"
        )
    if name in SQL_KEYWORDS:
        errors.append(f"{label}: {kind} name '{name}' is a reserved SQL keyword")
    return errors


def _check_rules(obj, field_types, relation_fields):
    """Mirror Core's checks of an object's rules (FieldSets.normalize): appendOnly a boolean; indexes a list of non-empty
    lists, each naming fields of the object (a relation's fieldName counts) once, none a LONG_TEXT or a GEOMETRY."""
    label = f"object {obj.get('name', '')}"
    errors = []
    for key in ("appendOnly", "apiOnly"):
        if key in obj and not isinstance(obj[key], bool):
            errors.append(f"{label}: {key} must be true or false")
    indexes = obj.get("indexes", [])
    if not isinstance(indexes, list) or not all(isinstance(i, list) and all(isinstance(f, str) for f in i) for i in indexes):
        return errors + [f"{label}: indexes must be a list of lists of field names"]
    seen = []
    for index in indexes:
        if not index:
            errors.append(f"{label}: an entry of indexes is empty")
            continue
        shown = f"index ({', '.join(index)})"
        for name in dict.fromkeys(index):
            if index.count(name) > 1:
                errors.append(f"{label}: {shown} names '{name}' twice")
            if name in field_types and field_types[name] in UNINDEXABLE_TYPES:
                errors.append(f"{label}: {shown} names '{name}', a {field_types[name]}, which Core does not index")
            elif name not in field_types and name not in relation_fields:
                errors.append(f"{label}: {shown} names '{name}', not a field of the object")
        if index in seen:
            errors.append(f"{label}: {shown} is repeated")
        seen.append(index)
    return errors


def validate(model):
    """Pure structural + Core-mirroring validation. Returns a list of error strings."""
    errors = []

    enums = model.get("enums")
    if not isinstance(enums, dict):
        errors.append("enums must be an object")
        enums = {}
    else:
        for ename, opts in enums.items():
            if not isinstance(opts, list) or not opts or not all(isinstance(o, str) for o in opts):
                errors.append(f"enum {ename}: must be a non-empty list of strings")
                continue
            seen_opts = set()
            for opt in opts:
                if not enum_option_valid(opt):
                    errors.append(f"enum {ename}: option '{opt}' has invalid characters or length")
                if opt in seen_opts:
                    errors.append(f"enum {ename}: duplicate option '{opt}'")
                seen_opts.add(opt)

    objects = model.get("objects")
    if not isinstance(objects, list) or not objects:
        errors.append("objects must be a non-empty list")
        objects = []

    relationships = model.get("relationships")
    if not isinstance(relationships, list):
        errors.append("relationships must be a list")
        relationships = []

    seen_objects = set()
    fields_by_object = {}

    for obj in objects:
        oname = obj.get("name", "")
        label = f"object {oname}"
        if oname in seen_objects:
            errors.append(f"{label}: duplicate object name")
        seen_objects.add(oname)
        errors.extend(_check_identifier(oname, "object", MAX_OBJECT_NAME, label))

        field_names = set()
        for field in obj.get("fields", []):
            fname = field.get("name", "")
            ftype = field.get("type")
            flabel = f"{label} field {fname}"
            if fname in field_names:
                errors.append(f"{flabel}: duplicate field name")
            field_names.add(fname)

            errors.extend(_check_identifier(fname, "field", MAX_FIELD_NAME, flabel))
            if fname in RESERVED_FIELD_NAMES:
                errors.append(f"{flabel}: field name is reserved by Core")

            if ftype == "RELATION":
                errors.append(f"{flabel}: type RELATION is not allowed here (relationships create it)")
            elif ftype not in FIELD_TYPES:
                errors.append(f"{flabel}: unknown type '{ftype}'")

            if ftype == "GEOMETRY":
                if str(field.get("geometryType", "")).upper() not in GEOMETRY_TYPES:
                    errors.append(f"{flabel}: geometryType must be one of {', '.join(sorted(GEOMETRY_TYPES))}")
                srid = field.get("srid", 4326)
                if not isinstance(srid, int) or not 1 <= srid <= 999999:
                    errors.append(f"{flabel}: srid must be an integer between 1 and 999999")
                if field.get("dimension", 2) not in (2, 3):
                    errors.append(f"{flabel}: dimension must be 2 or 3")
                if field.get("unique") or field.get("required"):
                    errors.append(f"{flabel}: a geometry can be neither unique nor required here")

            if ftype == "ENUM":
                enum_name = field.get("enum")
                if not enum_name or enum_name not in enums:
                    errors.append(f"{flabel}: enum '{enum_name}' is not defined in enums")

        fields_by_object[oname] = field_names

    rel_names = set()
    seen_source_field_names = set()
    for rel in relationships:
        rname = rel.get("name", "")
        label = f"relationship {rname}"
        if rname in rel_names:
            errors.append(f"{label}: duplicate relationship name")
        rel_names.add(rname)
        errors.extend(_check_identifier(rname, "relationship", MAX_RELATIONSHIP_NAME, label))

        source = rel.get("source")
        target = rel.get("target")
        if source not in seen_objects:
            errors.append(f"{label}: source '{source}' is not a known object")
        if target not in seen_objects:
            errors.append(f"{label}: target '{target}' is not a known object")

        if source == target:
            errors.append(f"{label}: self-references are not allowed")
        # no ordering is required between source and target in objects: do_apply creates every object
        # (phase 1) before any relationship (phase 2), and --drop deletes every relationship before any
        # object, so neither phase depends on where source or target sits in the file.

        field_name = rel.get("fieldName")
        errors.extend(_check_identifier(field_name, "field", MAX_FIELD_NAME, label))
        if field_name in RESERVED_FIELD_NAMES:
            errors.append(f"{label}: fieldName '{field_name}' is reserved by Core")
        if source in fields_by_object and field_name in fields_by_object[source]:
            errors.append(f"{label}: fieldName '{field_name}' collides with an existing field of {source}")

        source_field_key = (source, field_name)
        if source_field_key in seen_source_field_names:
            errors.append(
                f"{label}: fieldName '{field_name}' duplicates another relationship from {source}"
            )
        seen_source_field_names.add(source_field_key)

    relation_fields = {}
    for rel in relationships:
        relation_fields.setdefault(rel.get("source"), set()).add(rel.get("fieldName"))
    for obj in objects:
        field_types = {f.get("name"): f.get("type") for f in obj.get("fields", [])}
        errors.extend(_check_rules(obj, field_types, relation_fields.get(obj.get("name"), set())))

    return errors


# ---------------------------------------------------------------------------
# payload builders (pure)
# ---------------------------------------------------------------------------

def field_payload(model, f):
    field = {
        "name": f["name"],
        "label": f["label"],
        "type": f["type"],
        "required": f.get("required", False),
        "unique": f.get("unique", False),
    }
    if "description" in f:
        field["description"] = f["description"]
    if f["type"] == "ENUM":
        field["enumOptions"] = model["enums"][f["enum"]]
    if f["type"] == "GEOMETRY":
        field["geometryType"] = f["geometryType"].upper()
        field["srid"] = f.get("srid", 4326)
        field["dimension"] = f.get("dimension", 2)
    return field


def object_payload(model, obj):
    return {
        "name": obj["name"],
        "label": obj["label"],
        "pluralLabel": obj["pluralLabel"],
        "description": obj.get("description", ""),
        "fields": [field_payload(model, f) for f in obj["fields"]],
    }


def missing_options(model, field, existing):
    """Options of an ENUM field in model.json that Core does not have yet, in model order."""
    if field["type"] != "ENUM":
        return []
    have = set(existing.get("enumOptions") or [])
    return [o for o in model["enums"][field["enum"]] if o not in have]


def dropped_options(model, field, existing):
    """Options Core has for an ENUM field that model.json no longer lists, in Core's order."""
    if field["type"] != "ENUM":
        return []
    keep = set(model["enums"][field["enum"]])
    return [o for o in existing.get("enumOptions") or [] if o not in keep]


def _records_using(client, object_name, field_name, option):
    """How many records of the object store the option in the field. An answer without that count (a 404, another
    shape) is an error, not a zero: the option is never dropped on a guess."""
    query = urllib.parse.urlencode({"page": 0, "size": 1, field_name: option})
    data = client.get(f"/api/objects/{object_name}/records?{query}")
    total = data.get("totalElements") if isinstance(data, dict) else None
    if not isinstance(total, int):
        raise CoreError("no record count", json.dumps(data))
    return total


def relationship_payload(rel):
    return {
        "name": rel["name"],
        "label": rel["label"],
        "inverseLabel": rel["inverseLabel"],
        "type": "MANY_TO_ONE",
        "source": rel["source"],
        "target": rel["target"],
        "fieldName": rel["fieldName"],
    }


def rule_changes(obj, current):
    """The object-level rules model.json declares and Core lacks: indexes (ADR-036), appendOnly (ADR-040). They go
    after the relationships, since an index can name a relation field. Only what differs is sent. Compared as Core
    stores them: field names trimmed and lower-cased, in their order; appendOnly left out is false. model.json is the
    source of the indexes: one only Core has is dropped."""
    changes = {}
    want_indexes = [[f.strip().lower() for f in s] for s in obj.get("indexes", [])]
    if want_indexes != (current.get("indexes") or []):
        changes["indexes"] = want_indexes
    # appendOnly (ADR-040): never changed or deleted; apiOnly (ADR-040): written only in-process, by the app, never
    # through the generic record api (wasichai-ui shows it read-only). left out, either is false
    for key in ("appendOnly", "apiOnly"):
        if bool(obj.get(key)) != bool(current.get(key)):
            changes[key] = bool(obj.get(key))
    return changes


def declared_rules(obj):
    """The rules model.json declares for an object, as a PUT of it sends them: what an empty Core gets."""
    return rule_changes(obj, {})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _existing_names(data):
    if isinstance(data, dict):
        data = data.get("items", data.get("content", []))
    return {o["name"] for o in (data or [])}


def _fatal(method, path, err):
    print(f"error {method} {path} -> {err.status}\n{err.body}", file=sys.stderr)


def _apply_required_put(client, rel):
    """Returns True to keep going, False if this was fatal (caller must stop and exit 1).

    Unlike object/relationship POSTs (which tolerate 409 "ya existe"), this PUT tolerates
    nothing: every non-2xx response is fatal.
    """
    if not rel.get("required"):
        return True
    path = f"/api/metadata/objects/{rel['source']}/fields/{rel['fieldName']}"
    try:
        client.put(path, {"required": True})
    except CoreError as e:
        _fatal("PUT", path, e)
        return False
    return True


def _objects_by_name(data):
    if isinstance(data, dict):
        data = data.get("items", data.get("content", []))
    return {o["name"]: o for o in (data or [])}


def _put_rules(client, obj, current, changes):
    """PUT an object's rules: only the keys that change, with label, pluralLabel, description and enabled as Core has
    them (`current`, its GET /api/objects entry), which the PUT would otherwise reset. Returns False if Core refused
    (already reported)."""
    path = f"/api/objects/{obj['name']}"
    kept = {k: current[k] for k in OBJECT_KEYS if k in current}
    kept.setdefault("label", obj["label"])  # Core requires it
    try:
        client.put(path, {**kept, **changes})
    except CoreError as e:
        _fatal("PUT", path, e)
        return False
    print(f"update object {obj['name']} ({', '.join(sorted(changes))})")
    return True


def sync_object_rules(client, model):
    """Every object's rules as model.json declares them, after the relationships (an index can name a relation field).
    Returns how many objects changed, or None when Core refused (already reported)."""
    try:
        current_by_name = _objects_by_name(client.get("/api/objects"))
    except CoreError as e:
        _fatal("GET", "/api/objects", e)
        return None
    updated = 0
    for obj in model["objects"]:
        current = current_by_name.get(obj["name"], {})
        changes = rule_changes(obj, current)
        if changes:
            if not _put_rules(client, obj, current, changes):
                return None
            updated += 1
    return updated


def _fields_by_name(data):
    if isinstance(data, dict):
        data = data.get("items", data.get("content", []))
    return {f["name"]: f for f in (data or [])}


def sync_object(client, model, obj):
    """An object that already exists: add the fields model.json has and Core lacks, and the ENUM options
    it lacks, drop the ENUM options model.json no longer lists and no record uses, make optional what model.json no
    longer requires, and relabel what it labels differently. Nothing is renamed, retyped or made required, and no
    field or used option is removed, so imported records stay valid.
    Returns (added, updated), or None when Core refused (already reported)."""
    name = obj["name"]
    path = f"/api/metadata/objects/{name}/fields"
    try:
        existing = _fields_by_name(client.get(path))
    except CoreError as e:
        _fatal("GET", path, e)
        return None
    added = updated = 0
    for field in obj["fields"]:
        current = existing.get(field["name"])
        if current is None:
            try:
                status, _ = client.post(path, field_payload(model, field))
            except CoreError as e:
                _fatal("POST", path, e)
                return None
            print(f"add    field {name}.{field['name']} ({status})")
            added += 1
            continue
        extra = missing_options(model, field, current)
        dropped = []
        for option in dropped_options(model, field, current):
            try:
                using = _records_using(client, name, field["name"], option)
            except CoreError as e:
                _fatal("GET", f"/api/objects/{name}/records", e)
                return None
            if using:
                records = "1 record uses" if using == 1 else f"{using} records use"
                print(f"keep   option {name}.{field['name']} {option}: {records} it")
            else:
                dropped.append(option)
        if extra or dropped:
            # model.json's order (page 5 sorts the tipos de unidad urbana), then what it no longer lists and a record uses
            kept = [o for o in dropped_options(model, field, current) if o not in dropped]
            options = model["enums"][field["enum"]] + kept
            field_path = f"{path}/{field['name']}"
            try:
                client.put(field_path, {"enumOptions": options})
            except CoreError as e:
                _fatal("PUT", field_path, e)
                return None
            changes = ([f"+{', '.join(extra)}"] if extra else []) + ([f"-{', '.join(dropped)}"] if dropped else [])
            print(f"update field {name}.{field['name']} ({'; '.join(changes)})")
            updated += 1
        # a field model.json stopped requiring is relaxed (always safe); one it started requiring is left alone
        if current.get("required") and not field.get("required"):
            field_path = f"{path}/{field['name']}"
            try:
                client.put(field_path, {"required": False})
            except CoreError as e:
                _fatal("PUT", field_path, e)
                return None
            print(f"update field {name}.{field['name']} (optional)")
            updated += 1
        # a label is only what the admin shows: model.json's wins
        if current.get("label") != field["label"]:
            field_path = f"{path}/{field['name']}"
            try:
                client.put(field_path, {"label": field["label"]})
            except CoreError as e:
                _fatal("PUT", field_path, e)
                return None
            print(f"update field {name}.{field['name']} (label)")
            updated += 1
    return added, updated


def do_apply(client, model):
    created = 0
    updated = 0
    skipped = 0

    existing = _existing_names(client.get("/api/objects"))
    for obj in model["objects"]:
        name = obj["name"]
        if name in existing:
            synced = sync_object(client, model, obj)
            if synced is None:
                return 1
            added, changed = synced
            created += added
            updated += changed
            if not added and not changed:
                print(f"skip   object {name} (exists)")
                skipped += 1
            continue
        try:
            status, _ = client.post("/api/objects", object_payload(model, obj))
            print(f"create object {name} ({status})")
            created += 1
        except CoreError as e:
            if e.status == 409:
                print(f"skip   object {name} (exists)")
                skipped += 1
            else:
                _fatal("POST", "/api/objects", e)
                return 1

    for rel in model["relationships"]:
        name = rel["name"]
        try:
            status, _ = client.post("/api/relationships", relationship_payload(rel))
            print(f"create relationship {name} ({status})")
            created += 1
        except CoreError as e:
            if e.status == 409:
                print(f"skip   relationship {name} (exists)")
                skipped += 1
            else:
                _fatal("POST", "/api/relationships", e)
                return 1
        if not _apply_required_put(client, rel):
            return 1

    ruled = sync_object_rules(client, model)
    if ruled is None:
        return 1
    updated += ruled

    print(f"done: {created} created, {updated} updated, {skipped} skipped")
    return 0


def _delete_one(client, label, path):
    """Delete one entity; print the result. Returns 'deleted', 'skipped', or None (fatal, already reported)."""
    try:
        status, _ = client.delete(path)
        print(f"delete {label} ({status})")
        return "deleted"
    except CoreError as e:
        if e.status == 404:
            print(f"skip   {label} (not found)")
            return "skipped"
        _fatal("DELETE", path, e)
        return None


def do_drop(client, model):
    deleted = 0
    skipped = 0

    # Core keeps an append-only object's table, columns and relationships, and the columns an index names, until
    # their rules are off (ADR-040, ADR-036): --drop is that deliberate step
    try:
        current_by_name = _objects_by_name(client.get("/api/objects"))
    except CoreError as e:
        _fatal("GET", "/api/objects", e)
        return 1
    for obj in reversed(model["objects"]):
        current = current_by_name.get(obj["name"])
        changes = {k: v for k, v in RULES_OFF.items() if current and current.get(k)}
        if changes and not _put_rules(client, obj, current, changes):
            return 1

    to_delete = [
        (f"relationship {rel['name']}", f"/api/relationships/{rel['name']}")
        for rel in reversed(model["relationships"])
    ] + [
        (f"object {obj['name']}", f"/api/objects/{obj['name']}")
        for obj in reversed(model["objects"])
    ]
    for label, path in to_delete:
        result = _delete_one(client, label, path)
        if result is None:
            return 1
        deleted += result == "deleted"
        skipped += result == "skipped"

    print(f"done: {deleted} deleted, {skipped} skipped")
    return 0


OBJECT_PATH = re.compile(r"^/api/objects/[a-z0-9_]+$")
FIELD_PATH = re.compile(r"^(/api/metadata/objects/[a-z0-9_]+/fields)/([a-z0-9_]+)$")


class DiffClient:
    """--diff: the real Core is read, never written. A GET goes to Core; a write the real run would send is printed as
    "would <METHOD> <path> <summary>" and answered as Core would, so do_apply and do_drop run unchanged. What Core
    already has is no write: a relationship it has is the 409 apply skips, and a field PUT that changes nothing of what
    Core has (apply re-marks every required relationship's field on each run) is not printed."""

    def __init__(self, client):
        self.client = client
        self.pending = 0
        self._fields = {}
        self.relationships = {r["name"] for r in client.get("/api/relationships") or []}

    def get(self, path):
        return self.client.get(path)

    def post(self, path, body):
        if path == "/api/relationships" and body.get("name") in self.relationships:
            raise CoreError(409, "exists")
        self._would("POST", path, body)
        return 201, {"name": body.get("name")}

    def put(self, path, body):
        if self._unchanged(path, body):
            return 200, {}
        self._would("PUT", path, body)
        return 200, {}

    def delete(self, path):
        self._would("DELETE", path, None)
        return 204, None

    def _unchanged(self, path, body):
        field = FIELD_PATH.match(path)
        if not field:
            return False
        fields_path, name = field.groups()
        if fields_path not in self._fields:
            self._fields[fields_path] = _fields_by_name(self.client.get(fields_path))
        current = self._fields[fields_path].get(name)
        return current is not None and all(current.get(k) == v for k, v in body.items())

    def _would(self, method, path, body):
        self.pending += 1
        print(f"would {method} {path} {_summary(path, body)}".rstrip())

    def report(self):
        print("diff: nothing pending" if not self.pending else f"diff: {self.pending} writes pending, none sent")


def _summary(path, body):
    """A write's payload in one line: the name of what it creates, else what it changes (a rule PUT without the label,
    plural, description and enabled it sends back as Core has them)."""
    if body is None:
        return ""
    if "name" in body:
        return body["name"]
    if OBJECT_PATH.match(path):
        body = {k: v for k, v in body.items() if k not in OBJECT_KEYS}
    return json.dumps(body, ensure_ascii=False)


DRY_RUN_KEPT = "(plus label, pluralLabel, description and enabled as Core has them)"


def _print_dry_run(model):
    for obj in model["objects"]:
        print("# POST /api/objects")
        print(json.dumps(object_payload(model, obj), indent=2, ensure_ascii=False))
    for rel in model["relationships"]:
        print("# POST /api/relationships")
        print(json.dumps(relationship_payload(rel), indent=2, ensure_ascii=False))
    # what model.json declares (an empty Core gets it); on one that has the model, only what differs is sent
    for obj in model["objects"]:
        rules = declared_rules(obj)
        if rules:
            print(f"# PUT /api/objects/{obj['name']} {DRY_RUN_KEPT}")
            print(json.dumps(rules, indent=2, ensure_ascii=False))


def _print_drop_dry_run(model):
    # if Core has them on
    for obj in reversed(model["objects"]):
        rules = {k: RULES_OFF[k] for k in declared_rules(obj)}
        if rules:
            print(f"# PUT /api/objects/{obj['name']} {DRY_RUN_KEPT}")
            print(json.dumps(rules, indent=2, ensure_ascii=False))
    for rel in reversed(model["relationships"]):
        print(f"# DELETE /api/relationships/{rel['name']}")
    for obj in reversed(model["objects"]):
        print(f"# DELETE /api/objects/{obj['name']}")


def default_model_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.json")


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Apply catastro's model.json to a wasichai Core.")
    p.add_argument("--model", default=default_model_path())
    p.add_argument("--core", default=os.environ.get("WASICHAI_CORE", "http://localhost:8091"))
    p.add_argument("--email", default=os.environ.get("WASICHAI_EMAIL", "admin@wasichai.local"))
    p.add_argument("--password", default=os.environ.get("WASICHAI_PASSWORD", "admin"))
    # --dry-run prints model.json's payloads and asks Core nothing; --diff asks the real Core and prints what is pending
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--diff", action="store_true")
    p.add_argument("--drop", action="store_true")
    p.add_argument("--validate-only", action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    args = _parse_args(argv)

    with open(args.model, encoding="utf-8") as f:
        model = json.load(f)

    errors = validate(model)
    if errors:
        for e in errors:
            print(f"model: {args.model}: {e}")
        return 2
    if args.validate_only:
        return 0

    if args.dry_run:
        if args.drop:
            _print_drop_dry_run(model)
        else:
            _print_dry_run(model)
        return 0

    client = Client(args.core)
    try:
        client.login(args.email, args.password)
    except CoreError as e:
        _fatal("POST", "/api/auth/login", e)
        return 1

    if not args.diff:
        return do_drop(client, model) if args.drop else do_apply(client, model)
    try:
        diff = DiffClient(client)
    except CoreError as e:
        _fatal("GET", "/api/relationships", e)
        return 1
    code = do_drop(diff, model) if args.drop else do_apply(diff, model)
    if code == 0:
        diff.report()
    return code


if __name__ == "__main__":
    sys.exit(main())
