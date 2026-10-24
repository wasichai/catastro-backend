"""What the importers share: reading a table (csv or xlsx), cleaning values, and posting records.

Stdlib only. The xlsx reader is import_predios.py's of srtm-backend.
"""
import csv
import json
import os
import re
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from core_client import CoreError

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRESS_EVERY = 500
# what a missing or unreadable input raises: reported with exit 2, not as a traceback
INPUT_ERRORS = (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError, UnicodeDecodeError)

XLSX_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
XLSX_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
XLSX_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _cell_value(cell, shared):
    kind = cell.get("t")
    if kind == "inlineStr":
        node = cell.find(f"{XLSX_MAIN}is")
        return "".join(t.text or "" for t in node.iter(f"{XLSX_MAIN}t")) if node is not None else None
    v = cell.find(f"{XLSX_MAIN}v")
    if v is None or v.text is None:
        return None
    if kind == "s":
        return shared[int(v.text)]
    return v.text


def read_xlsx(path, sheet=None):
    """Rows of one sheet as dicts keyed by the header row, plus `_fila` (the Excel row number).

    Stdlib only: an xlsx is a zip of xml. The first sheet unless `sheet` names another.
    """
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{XLSX_MAIN}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{XLSX_MAIN}t")))
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(f"{XLSX_PKG_REL}Relationship")}
        sheets = workbook.find(f"{XLSX_MAIN}sheets")
        chosen = next((s for s in sheets if sheet is None or s.get("name") == sheet), None)
        if chosen is None:
            raise ValueError(f"sheet '{sheet}' not found in {path}")
        target = rels[chosen.get(f"{XLSX_REL}id")]
        sheet_path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"

        header = None
        rows = []
        with z.open(sheet_path) as f:
            for _, el in ET.iterparse(f):
                if el.tag != f"{XLSX_MAIN}row":
                    continue
                values = {}
                for cell in el.findall(f"{XLSX_MAIN}c"):
                    column = re.match(r"[A-Z]+", cell.get("r")).group()
                    values[column] = _cell_value(cell, shared)
                number = int(el.get("r"))
                el.clear()
                if header is None:
                    header = {col: (name or "").strip() for col, name in values.items() if name}
                    continue
                if not any(v not in (None, "") for v in values.values()):
                    continue
                row = {name: values.get(col) for col, name in header.items()}
                row["_fila"] = number
                rows.append(row)
        return rows


def read_table(path, sheet=None):
    """Rows of a csv or xlsx as dicts keyed by the lower-cased header, plus `_fila` (the file's line or Excel row).

    A csv skips lines starting with # (the MEF demo files carry comments) and reads utf-8 with or without a BOM.
    """
    if path.lower().endswith((".xlsx", ".xlsm")):
        raw = read_xlsx(path, sheet)
        return [{(k.strip().lower() if k != "_fila" else k): v for k, v in row.items()} for row in raw]
    with open(path, encoding="utf-8-sig", newline="") as f:
        lines = [(n, line) for n, line in enumerate(f, start=1) if not line.lstrip().startswith("#") and line.strip()]
    if not lines:
        return []
    rows = csv.reader(line for _, line in lines)
    header = [h.strip().lower() for h in next(rows)]
    result = []
    for (n, _), values in zip(lines[1:], rows):
        row = dict(zip(header, values))
        if any((v or "").strip() for v in values):
            row["_fila"] = n
            result.append(row)
    return result


def clean_text(value):
    """Collapsed whitespace; empty or blank is None (Core answers 400 to "" on non-text fields)."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def code_text(value):
    """A code as text: an xlsx number comes as 3.0 and means 3."""
    text = clean_text(value)
    if text is not None and re.fullmatch(r"\d+\.0+", text):
        return text.split(".")[0]
    return text


def parse_decimal(value):
    """(text, None) with the number as plain text, (None, None) when empty, (None, error) when it is not a number."""
    text = clean_text(value)
    if text is None:
        return None, None
    try:
        number = Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None, f"'{text}' is not a number"
    if not number.is_finite() or number < 0:
        return None, f"'{text}' is not a non-negative number"
    return format(number.normalize(), "f"), None


def parse_int(value):
    text, error = parse_decimal(value)
    if error or text is None:
        return None, error
    if "." in text:
        return None, f"'{text}' is not an integer"
    return int(text), None


def column_for(row, mapping, field):
    """The cell of a field: the mapped column, looked up lower-cased."""
    return row.get(mapping[field].lower())


def parse_map(pairs, defaults):
    """The field -> column mapping: `defaults` with every --map field=column override applied."""
    mapping = dict(defaults)
    for pair in pairs:
        field, _, column = pair.partition("=")
        if field not in defaults or not column.strip():
            raise ValueError(f"--map {pair}: expected <field>=<column>, field one of {', '.join(defaults)}")
        mapping[field] = column.strip()
    return mapping


def missing_columns(rows, mapping, required):
    """The required fields whose mapped column the table lacks (checked once, on the first row)."""
    if not rows:
        return []
    return [f"column '{mapping[f]}' (field {f}) is missing" for f in required if mapping[f].lower() not in rows[0]]


def enum_option(value, options):
    """The model option a cell means: case and underscores do not matter (MUY_BUENO is MUY BUENO). None if unknown."""
    text = clean_text(value)
    if text is None:
        return None, None
    wanted = text.upper().replace("_", " ")
    for option in options:
        if option.upper() == wanted:
            return option, None
    return None, f"'{text}' is not one of {', '.join(options)}"


def load_enums(model_path):
    with open(model_path, encoding="utf-8") as f:
        return json.load(f)["enums"]


class LoadError(Exception):
    def __init__(self, object_name, fila, error):
        super().__init__(f"{object_name} fila {fila}: {error}")
        self.object_name = object_name
        self.fila = fila
        self.error = error


def payload(attributes):
    return {"attributes": {k: v for k, v in attributes.items() if v is not None}}


def post_all(client, object_name, items, workers):
    """POSTs (key, fila, attributes) items; returns key -> record id. The first refusal stops it all."""
    ids = {}
    if not items:
        return ids

    def one(item):
        key, fila, attributes = item
        try:
            _, record = client.post(f"/api/objects/{object_name}/records", payload(attributes))
        except CoreError as e:
            raise LoadError(object_name, fila, e)
        return key, record["id"]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, item) for item in items]
        try:
            for done, future in enumerate(as_completed(futures), start=1):
                key, record_id = future.result()
                ids[key] = record_id
                if done % PROGRESS_EVERY == 0:
                    print(f"  {object_name}: {done}/{len(items)}", flush=True)
        except LoadError:
            for future in futures:
                future.cancel()
            raise
    return ids


def write_all(client, ops, workers, reason):
    """Writes (key, fila, method, object_name, record_id, attributes) ops with X-Change-Reason `reason`.

    POST creates (attributes with None stripped, as `payload`); PATCH merges `attributes` as given, so a None clears
    a field; DELETE ignores `attributes`. Returns key -> new id (POST only). The first refusal raises LoadError and
    cancels the rest (as post_all).
    """
    ids = {}
    if not ops:
        return ids

    def one(op):
        key, fila, method, object_name, record_id, attributes = op
        path = f"/api/objects/{object_name}/records"
        try:
            if method == "POST":
                _, record = client.post(path, payload(attributes), reason=reason)
                return key, record["id"]
            if method == "PATCH":
                client.patch(f"{path}/{record_id}", {"attributes": attributes}, reason=reason)
            elif method == "DELETE":
                client.delete(f"{path}/{record_id}", reason=reason)
            else:
                raise ValueError(f"write_all: unknown method '{method}'")
        except CoreError as e:
            raise LoadError(object_name, fila, e)
        return key, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, op) for op in ops]
        try:
            for future in as_completed(futures):
                key, record_id = future.result()
                if record_id is not None:
                    ids[key] = record_id
        except LoadError:
            for future in futures:
                future.cancel()
            raise
    return ids


def report_problems(problems):
    for problem in problems:
        print(f"problem: {problem}", file=sys.stderr)
    print(f"{len(problems)} problems: nothing was sent to Core", file=sys.stderr)
