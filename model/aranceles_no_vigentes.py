#!/usr/bin/env python3
"""The fichas whose id_aranc is not a vigente arancel for a year, and their correction by an entrega
(wasichai/catastro-backend#48).

Vigente for --anio means an arancel record with that id_aranc and anio in catastro: catastro keeps only the copy of
srtm's vigentes (ADR-012). Reads predio_catastral and arancel from Core; with --padron, also the SAT's padrón (xlsx or
csv; sheet "PREDIO URBANO", columns "Código Predio" = codigo_municipal and "Codigo de via"; whitespace removed, empty
values skipped). A ficha's codes are the Counter of its via codes over every padrón row of its codigo.

Motives (a ficha may have several, each counted):
  id_aranc_vacio                     id_aranc is empty
  clave_inexistente                  id_aranc has no arancel for --anio
  clave_provisional                  id_aranc is not a via code (^\\d{10}-\\d{2}$), e.g. R<valor>
  varios_codigos_alguno_no_vigente   (--padron) two or more codes, some vigente and some not
  varios_codigos_valores_distintos   (--padron) two or more codes, all vigente, with distinct valor_m2
  codigo_sin_arancel_vigente         (--padron) the ficha has codes and none is vigente
plus sin_padron (fichas without a padrón row), and the correction's counts: corregibles, ya_apunta and
sin_levantar_no_se_corrige.

The padrón holds personal data (Ley 29733): only codigo_municipal and via codes ever reach the output. --reporte
writes the CSV codigo_municipal,id_aranc,estado_levantamiento,motivo,codigos_padron, one row per (ficha, motivo);
stdout has the counts, each motive and sin_padron split as (levantadas N, sin levantar M).
Without --entrega nothing is written to Core.

--entrega CODIGO (needs --padron and --fecha-corte): a ficha whose codes all have a vigente arancel of one same
valor_m2 gets the most frequent code (a tie: the lowest code); a ficha already pointing there, or SIN_LEVANTAR, is
left. The CSV cod_pre,id_aranc (--csv, default a new temp dir) is loaded with import_fichas.py --entrega CODIGO
--fuente OTRA, which compares only the columns the file brings: only id_aranc changes. Repeatable: once corrected,
a new run finds nothing to change and does not call import_fichas.

Exit: 0 ok, 1 Core refused something, 2 the flags or the padrón do not fit (or import_fichas' own 2).

Run: python3 -I aranceles_no_vigentes.py --anio 2026 [--padron padron.xlsx] [--reporte reporte.csv]
     python3 -I aranceles_no_vigentes.py --anio 2026 --padron padron.xlsx --entrega ICA-ARANCEL-2026-11 \\
             --fecha-corte 2026-11-01 [--descripcion TEXT] [--csv fichas.csv] [--dry-run]
"""
import argparse
import csv
import os
import re
import sys
import tempfile
from collections import Counter, namedtuple
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

HERE = os.path.dirname(os.path.abspath(__file__))
# under python3 -I (the padrón is untrusted) neither the cwd nor the script's directory is on sys.path: put back only
# the latter, for core_client, tabular and import_fichas
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import import_fichas  # noqa: E402
from core_client import Client, CoreError  # noqa: E402
from entregas import check_codigo  # noqa: E402
from tabular import INPUT_ERRORS, missing_columns, read_table  # noqa: E402

PREDIO, ARANCEL = "predio_catastral", "arancel"
VIA_CODE = re.compile(r"\d{10}-\d{2}")
MOTIVOS = ("id_aranc_vacio", "clave_inexistente", "clave_provisional", "varios_codigos_alguno_no_vigente",
           "varios_codigos_valores_distintos", "codigo_sin_arancel_vigente")
PADRON_MOTIVOS = MOTIVOS[3:]
COUNTS = (*MOTIVOS, "sin_padron", "corregibles", "ya_apunta", "sin_levantar_no_se_corrige")
SIN_LEVANTAR = "SIN_LEVANTAR"

Row = namedtuple("Row", "codigo_municipal id_aranc estado_levantamiento motivo codigos_padron")
# the counts printed with their levantadas / sin levantar split
SPLIT = (*MOTIVOS, "sin_padron")


@dataclass
class Result:
    rows: list = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)
    sin_levantar: Counter = field(default_factory=Counter)  # the part of each count that is SIN_LEVANTAR
    candidates: list = field(default_factory=list)  # (codigo_municipal, target id_aranc), by codigo


def _code(value):
    """A code without any whitespace; None when empty."""
    text = "".join(str(value).split()) if value is not None else ""
    return text or None


def padron_codes(rows, codigo_column, via_column):
    """codigo_municipal -> Counter of its via codes over the padrón rows (headers matched lower-cased)."""
    codes = {}
    for row in rows:
        codigo, via = _code(row.get(codigo_column.lower())), _code(row.get(via_column.lower()))
        if codigo and via:
            codes.setdefault(codigo, Counter())[via] += 1
    return codes


def _year(value):
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def vigentes(aranceles, anio):
    """id_aranc -> valor_m2 (Decimal, None when it does not read) of the arancel records of `anio`."""
    result = {}
    for record in aranceles:
        a = record["attributes"]
        if _year(a.get("anio")) == anio and _code(a.get("id_aranc")):
            try:
                result[_code(a["id_aranc"])] = Decimal(str(a.get("valor_m2")))
            except InvalidOperation:
                result[_code(a["id_aranc"])] = None
    return result


def target(codes, vig):
    """The code a ficha with padrón `codes` (a Counter) should point to: all vigente and of one valor_m2 -> the most
    frequent, a tie the lowest; else None."""
    if not codes or any(c not in vig for c in codes) or len({vig[c] for c in codes}) > 1:
        return None
    return min(codes, key=lambda c: (-codes[c], c))


def analyze(fichas, vig, padron=None):
    """The Result of the fichas' attributes against the vigente aranceles `vig` and, unless None, the padrón codes."""
    result = Result(counts=Counter(dict.fromkeys(COUNTS if padron is not None else MOTIVOS[:3], 0)))
    for a in sorted(fichas, key=lambda a: a["codigo_municipal"]):
        codigo, id_aranc = a["codigo_municipal"], _code(a.get("id_aranc"))
        estado = a.get("estado_levantamiento") or ""
        codes = (padron or {}).get(_code(codigo), Counter())
        motivos = []
        if id_aranc is None:
            motivos.append("id_aranc_vacio")
        else:
            if id_aranc not in vig:
                motivos.append("clave_inexistente")
            if not VIA_CODE.fullmatch(id_aranc):
                motivos.append("clave_provisional")
        if padron is not None:
            con = [c for c in codes if c in vig]
            if len(codes) >= 2 and con and len(con) < len(codes):
                motivos.append("varios_codigos_alguno_no_vigente")
            if len(codes) >= 2 and len(con) == len(codes) and len({vig[c] for c in con}) > 1:
                motivos.append("varios_codigos_valores_distintos")
            if codes and not con:
                motivos.append("codigo_sin_arancel_vigente")
            if not codes:
                result.counts["sin_padron"] += 1
                result.sin_levantar["sin_padron"] += estado == SIN_LEVANTAR
            via = target(codes, vig)
            if via is not None:
                if via == id_aranc:
                    result.counts["ya_apunta"] += 1
                elif estado == SIN_LEVANTAR:
                    result.counts["sin_levantar_no_se_corrige"] += 1
                else:
                    result.counts["corregibles"] += 1
                    result.candidates.append((codigo, via))
        joined = ";".join(sorted(codes))
        for motivo in motivos:
            result.counts[motivo] += 1
            result.sin_levantar[motivo] += estado == SIN_LEVANTAR
            result.rows.append(Row(codigo, id_aranc or "", estado, motivo, joined))
    return result


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Report the fichas without a vigente arancel and correct them by an entrega.")
    p.add_argument("--anio", type=int, required=True, help="the year whose aranceles are vigentes")
    p.add_argument("--padron", help="the SAT padrón, xlsx or csv: the via codes of each codigo_municipal")
    p.add_argument("--hoja", default="PREDIO URBANO", help="the padrón's xlsx sheet (default PREDIO URBANO)")
    p.add_argument("--columna-codigo", default="Código Predio", help="the padrón's codigo_municipal column")
    p.add_argument("--columna-via", default="Codigo de via", help="the padrón's via code column")
    p.add_argument("--reporte", metavar="PATH",
                   help="CSV codigo_municipal,id_aranc,estado_levantamiento,motivo,codigos_padron")
    p.add_argument("--model", default=os.path.join(HERE, "model.json"))
    p.add_argument("--core", default=os.environ.get("WASICHAI_CORE", "http://localhost:8091"))
    p.add_argument("--email", default=os.environ.get("WASICHAI_EMAIL", "admin@wasichai.local"))
    p.add_argument("--password", default=os.environ.get("WASICHAI_PASSWORD", "admin"))
    e = p.add_argument_group("corrección (import_fichas.py --entrega --fuente OTRA)")
    e.add_argument("--entrega", metavar="CODIGO", help="the entrega's code; needs --padron and --fecha-corte")
    e.add_argument("--fecha-corte", metavar="YYYY-MM-DD")
    e.add_argument("--descripcion", metavar="TEXT")
    e.add_argument("--csv", metavar="PATH", help="the cod_pre,id_aranc file (default: a new temp dir)")
    e.add_argument("--workers", type=int, default=4, help="parallel writes (default 4)")
    e.add_argument("--dry-run", action="store_true", help="import_fichas reports the entrega and writes nothing")
    return p.parse_args(argv)


def _flag_problems(args):
    if args.entrega is None:
        return [f"{flag} needs --entrega" for flag, value in (
            ("--fecha-corte", args.fecha_corte), ("--descripcion", args.descripcion), ("--csv", args.csv),
            ("--dry-run", args.dry_run)) if value]
    problems = []
    error = check_codigo(args.entrega)
    if error:
        problems.append(error)
    if args.padron is None:
        problems.append("--entrega needs --padron")
    if args.fecha_corte is None:
        problems.append("--fecha-corte is required with --entrega")
    return problems


def _write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _correct(args, candidates):
    """Loads the candidates with import_fichas --entrega; its exit code."""
    path = args.csv or os.path.join(tempfile.mkdtemp(prefix="aranceles-"), "fichas_arancel.csv")
    _write_csv(path, ["cod_pre", "id_aranc"], candidates)
    print(f"csv: {path}", flush=True)
    argv = ["--fichas", path, "--entrega", args.entrega, "--fuente", "OTRA", "--fecha-corte", args.fecha_corte,
            "--model", args.model, "--core", args.core, "--email", args.email, "--password", args.password,
            "--workers", str(args.workers)]
    if args.descripcion is not None:
        argv += ["--descripcion", args.descripcion]
    if args.dry_run:
        argv.append("--dry-run")
    return import_fichas.main(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    problems = _flag_problems(args)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 2
    padron = None
    if args.padron:
        try:
            rows = read_table(args.padron, args.hoja if args.padron.lower().endswith((".xlsx", ".xlsm")) else None)
        except INPUT_ERRORS as e:
            print(f"input: {e}", file=sys.stderr)
            return 2
        missing = missing_columns(rows, {"codigo": args.columna_codigo, "via": args.columna_via}, ["codigo", "via"])
        if missing or not rows:
            for problem in missing or ["the padrón has no rows"]:
                print(f"padrón: {problem}", file=sys.stderr)
            return 2
        padron = padron_codes(rows, args.columna_codigo, args.columna_via)
    client = Client(args.core)
    try:
        client.login(args.email, args.password)
        fichas = [r["attributes"] for r in client.list_all(PREDIO)]
        vig = vigentes(client.list_all(ARANCEL), args.anio)
    except CoreError as e:
        print(f"error -> {e.status}\n{e.body}", file=sys.stderr)
        return 1
    result = analyze(fichas, vig, padron)
    if args.reporte:
        _write_csv(args.reporte, Row._fields, result.rows)
    print(f"fichas: {len(fichas)}\naranceles vigentes {args.anio}: {len(vig)}")
    for name, n in result.counts.items():
        if name in SPLIT:
            sin = result.sin_levantar[name]
            print(f"{name}: {n} (levantadas {n - sin}, sin levantar {sin})")
        else:
            print(f"{name}: {n}")
    if args.entrega is None:
        return 0
    if not result.candidates:
        print("nada que corregir: import_fichas no se llama")
        return 0
    return _correct(args, result.candidates)


if __name__ == "__main__":
    sys.exit(main())
