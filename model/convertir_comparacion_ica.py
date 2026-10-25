#!/usr/bin/env python3
"""Turns Ica's comparison workbook (libro de comparación v3) into the fichas, pisos and titulares csv of
`import_fichas.py --entrega`.

Only the catastro side is read (the sheets predio_catastro, construccion_catastro and titulares_catastro); the rentas
side is the srtm padrón, never the catastro. The vínculo with rentas comes from the lotes gpkg exported to csv
(`ogr2ogr -f CSV vinculos.csv <lotes>.gpkg <capa>`), one row per lote with cod_predio_rentas and vinculo_metodo.
Rules (wasichai/catastro-backend#10, contexto-comun.md «Ruling (#10)»):
  fichas: a predio without codigo_unidad_catastro (or, given the vínculos, without a vínculo row) is not loaded; a
          repeated cod_predio_rentas keeps its first ficha. sector, manzana and lote are parts 3, 4 and 5 (0-based) of the
          unidad catastral split on '-', which also goes as it comes to codigo_referencia_catastral. An area of 0 or
          less goes empty (never the rentas area). estado_levantamiento: SIN_LEVANTAR when the area is empty and the
          predio has no construccion, no titular and (when the column exists) no urbanización; PARCIAL when the area
          is empty but one of those exists; COMPLETO otherwise. uso and id_aranc go as present, empty columns, so an
          upsert clears earlier estimates (ADR-013).
  pisos:  only the pisos of a loaded ficha; a construccion shared by several predios goes to each. The nivel's first
          digits are the piso; a nivel without digits and NIVEL 71/81 (unknown codes) are dropped. A repeated piso of
          a predio becomes secciones 1..n in sheet order. A year outside 1900-2026, an area of 0 or less and a letter
          outside A-J go empty; material 1/2/3 and estado 1-4 are Ica's codes for the model's options, which also pass
          as they are; anything else goes empty.
  titulares: only those of a loaded ficha, every value as it comes (a filler document such as 000000000 included:
          import_fichas.py empties it). Datos personales (Ley 29733): the output goes outside the repository, and
          nothing a titular brings ever reaches stdout or stderr.
  vínculos: vinculo_metodo matches the model's enum in any case (with _ or a space) or through --metodo TEXTO=ENUM;
          any other text exits 2. A row without cod_predio_rentas links nothing; an empty method links the code with
          an empty vinculo_metodo; a repeated code keeps its first row. Without --vinculos every ficha is loaded and
          fichas.csv leaves the vinculo_metodo column out (ruling R11), so the upsert does not clear it.
Every rule that drops or empties something is counted, so the operator sees what the delivery lost.

The default columns are the libro's; --map-predio, --map-construccion, --map-titulares and --map-vinculos
field=column override them (repeatable). Every column is required (exit 2 naming it) except cuc_catastro and
urbanizacion_catastro; without cuc_catastro, fichas.csv leaves its cuc column out, so an upsert does not clear it.

Writes fichas.csv, pisos.csv and titulares.csv in --salida, which must be outside the repository, and prints only
`<clave>: <n>` lines. Exit: 0 ok, 2 a missing sheet or column, an unknown vínculo method or a bad flag (nothing is
written).

Run: python3 -I convertir_comparacion_ica.py --libro comparacion.xlsx --vinculos vinculos.csv --salida ~/ica/entrega
"""
import argparse
import csv
import os
import re
import sys
from collections import Counter
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
# under python3 -I (the files it reads are untrusted) neither the cwd nor the script's directory is on sys.path: put
# back only the latter, for tabular and import_fichas
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from import_fichas import CATEGORIAS  # noqa: E402
from tabular import (INPUT_ERRORS, clean_text, code_text, column_for, enum_option, load_enums,  # noqa: E402
                     missing_columns, parse_decimal, parse_int, parse_map, read_table)

REPOSITORIO = os.path.dirname(HERE)
HOJA_PREDIO, HOJA_CONSTRUCCION, HOJA_TITULARES = "predio_catastro", "construccion_catastro", "titulares_catastro"

PREDIO_COLUMNS = {
    "codigo_municipal": "cod_predio_rentas", "unidad_catastral": "codigo_unidad_catastro",
    "area_terreno": "area_terreno_catastro", "cuc": "cuc_catastro", "urbanizacion": "urbanizacion_catastro",
}
CONSTRUCCION_COLUMNS = {
    "codigo_municipal": "cod_predio", "nivel": "nivel_catastro", "anio_construccion": "ano_catastro",
    "area_construida": "area_construida_nivel_catastro", "material": "material_catastro",
    "estado_conservacion": "estado_conservacion_catastro", "muros_columnas": "muros_catastro",
    "techos": "techos_catastro", "pisos": "pisos_catastro", "puertas_ventanas": "puertas_catastro",
    "revestimientos": "revestimientos_catastro", "banos": "banos_catastro", "instalaciones": "instalaciones_catastro",
}
TITULAR_COLUMNS = {
    "codigo_municipal": "cod_predio", "tipo_documento": "tipo_documento_catastro",
    "numero_documento": "numero_documento_catastro", "nombre": "nombre_catastro", "porcentaje": "porcentaje_catastro",
    "condicion": "condicion_catastro",
}
VINCULO_COLUMNS = {"codigo_municipal": "cod_predio_rentas", "metodo": "vinculo_metodo"}
# the predio columns the libro may lack; every other mapped column is required
PREDIO_OPCIONALES = {"cuc", "urbanizacion"}
FICHAS_CSV = ["cod_pre", "cod_sect", "cod_mzn", "cod_lote", "area_terreno", "uso", "id_aranc", "estado_levantamiento",
              "vinculo_metodo", "codigo_referencia_catastral", "cuc"]
PISOS_CSV = ["cod_pre", "piso", "seccion", "area_construida", "anio_construccion", "material", "estado_conservacion",
             *CATEGORIAS]
TITULARES_CSV = ["cod_pre", "tipo_documento", "numero_documento", "nombre", "porcentaje", "condicion"]

# Ica's codes (README's reading of the libro); the model's own options pass as they are
MATERIAL_CODES = {"1": "CONCRETO", "2": "LADRILLO", "3": "ADOBE"}
ESTADO_CODES = {"1": "MUY BUENO", "2": "BUENO", "3": "REGULAR", "4": "MALO"}
# niveles of unknown meaning in the libro: not loaded
NIVELES_FUERA = {71, 81}
ANIO_MINIMO = 1900
ANIO_MAXIMO = 2026
# sector, manzana and lote: 0-based parts of the unidad catastral split on '-' (the old convertir_catastro.py)
PARTES_SECTOR_MANZANA_LOTE = (3, 4, 5)

CONTEOS_FICHAS = ["predios_sin_vinculo", "fichas", "fichas_repetidas", "fichas_sin_levantar", "fichas_parciales",
                  "fichas_area_vacia"]
CONTEOS_PISOS = ["pisos", "pisos_de_predios_sin_ficha", "pisos_nivel_71_81", "niveles_sin_numero",
                 "pisos_en_seccion_2_o_mas", "anios_vaciados", "areas_construidas_vaciadas", "letras_vaciadas",
                 "materiales_vaciados", "estados_vaciados"]
CONTEOS_TITULARES = ["titulares", "titulares_de_predios_sin_ficha"]
CATEGORIA = re.compile(r"[A-J]")
DIGITOS = re.compile(r"\d+")


def _positive(value):
    """(text, emptied): the number as plain text when above 0; emptied when the cell had something else."""
    text, error = parse_decimal(value)
    if text is not None and Decimal(text) > 0:
        return text, False
    return "", error is not None or text is not None


def _optional(row, mapping, field):
    """The cell of a column the sheet may lack (None then)."""
    return row.get(mapping[field].lower())


def codigos_con_piso(filas, mapa):
    """Codes with at least one construccion row whose nivel loads a piso (what pisos_de keeps): a row dropped for
    lacking a digit or for being NIVEL 71/81 does not count towards PARCIAL/SIN_LEVANTAR."""
    codigos = set()
    for row in filas:
        codigo = code_text(column_for(row, mapa, "codigo_municipal"))
        if not codigo:
            continue
        digitos = DIGITOS.search(clean_text(column_for(row, mapa, "nivel")) or "")
        if digitos is None or int(digitos.group()) in NIVELES_FUERA:
            continue
        codigos.add(codigo)
    return codigos


def fichas_de(predios, con_pisos, con_titulares, vinculos, mapa):
    """(fichas, counts) from the predio_catastro rows. `con_pisos` / `con_titulares` are the codes with a construccion /
    titular row; `vinculos` maps a code to its vinculo_metodo, or is None when no vínculo file is given."""
    n = Counter(dict.fromkeys(CONTEOS_FICHAS, 0))
    fichas, vistos = [], set()
    for row in predios:
        codigo = code_text(column_for(row, mapa, "codigo_municipal"))
        unidad = clean_text(column_for(row, mapa, "unidad_catastral"))
        if not codigo or not unidad or (vinculos is not None and codigo not in vinculos):
            n["predios_sin_vinculo"] += 1
            continue
        if codigo in vistos:
            n["fichas_repetidas"] += 1
            continue
        vistos.add(codigo)
        partes = unidad.split("-")
        sector, manzana, lote = (partes[i] if i < len(partes) else "" for i in PARTES_SECTOR_MANZANA_LOTE)
        area, _ = _positive(column_for(row, mapa, "area_terreno"))
        if not area:
            n["fichas_area_vacia"] += 1
            levantado = (codigo in con_pisos or codigo in con_titulares
                         or clean_text(_optional(row, mapa, "urbanizacion")) is not None)
            estado = "PARCIAL" if levantado else "SIN_LEVANTAR"
            n["fichas_parciales" if levantado else "fichas_sin_levantar"] += 1
        else:
            estado = "COMPLETO"
        fichas.append({
            "cod_pre": codigo, "cod_sect": sector, "cod_mzn": manzana, "cod_lote": lote, "area_terreno": area,
            "uso": "", "id_aranc": "", "estado_levantamiento": estado,
            "vinculo_metodo": vinculos[codigo] if vinculos is not None else "",
            "codigo_referencia_catastral": unidad, "cuc": code_text(_optional(row, mapa, "cuc")) or "",
        })
    n["fichas"] = len(fichas)
    return fichas, n


def _option(value, codes, options):
    """(model option or "", emptied): Ica's code or the option itself; anything else goes empty."""
    text = code_text(value)
    if text is None:
        return "", False
    if text in codes:
        return codes[text], False
    option, _ = enum_option(text, options)
    return (option, False) if option else ("", True)


def pisos_de(filas, codigos, mapa, enums, anio_maximo=ANIO_MAXIMO):
    """(pisos, counts) from the construccion_catastro rows; `codigos` are the loaded fichas' codes."""
    n = Counter(dict.fromkeys(CONTEOS_PISOS, 0))
    pisos, secciones = [], Counter()
    for row in filas:
        codigo = code_text(column_for(row, mapa, "codigo_municipal"))
        if codigo not in codigos:
            n["pisos_de_predios_sin_ficha"] += 1
            continue
        digitos = DIGITOS.search(clean_text(column_for(row, mapa, "nivel")) or "")
        if digitos is None:
            n["niveles_sin_numero"] += 1
            continue
        piso = int(digitos.group())
        if piso in NIVELES_FUERA:
            n["pisos_nivel_71_81"] += 1
            continue
        secciones[codigo, piso] += 1
        seccion = secciones[codigo, piso]
        if seccion > 1:
            n["pisos_en_seccion_2_o_mas"] += 1

        anio, error = parse_int(column_for(row, mapa, "anio_construccion"))
        if anio is not None and ANIO_MINIMO <= anio <= anio_maximo:
            anio_texto = str(anio)
        else:
            anio_texto = ""
            if anio is not None or error:
                n["anios_vaciados"] += 1
        area, vaciada = _positive(column_for(row, mapa, "area_construida"))
        n["areas_construidas_vaciadas"] += vaciada
        material, vaciado = _option(column_for(row, mapa, "material"), MATERIAL_CODES, enums["material"])
        n["materiales_vaciados"] += vaciado
        estado, vaciado = _option(column_for(row, mapa, "estado_conservacion"), ESTADO_CODES,
                                  enums["estado_conservacion"])
        n["estados_vaciados"] += vaciado

        piso_fila = {
            "cod_pre": codigo, "piso": str(piso), "seccion": seccion, "area_construida": area,
            "anio_construccion": anio_texto, "material": material, "estado_conservacion": estado,
        }
        for campo in CATEGORIAS:
            letra = (clean_text(column_for(row, mapa, campo)) or "").upper()
            if letra and not CATEGORIA.fullmatch(letra):
                n["letras_vaciadas"] += 1
                letra = ""
            piso_fila[campo] = letra
        pisos.append(piso_fila)
    n["pisos"] = len(pisos)
    return pisos, n


def titulares_de(filas, codigos, mapa):
    """(titulares, counts) from the titulares_catastro rows of the loaded fichas' `codigos`, every value as it comes:
    a filler document stays (import_fichas.py empties it and reports it by codigo and row)."""
    n = Counter(dict.fromkeys(CONTEOS_TITULARES, 0))
    titulares = []
    for row in filas:
        codigo = code_text(column_for(row, mapa, "codigo_municipal"))
        if codigo not in codigos:
            n["titulares_de_predios_sin_ficha"] += 1
            continue
        titulares.append({
            "cod_pre": codigo,
            "tipo_documento": code_text(column_for(row, mapa, "tipo_documento")) or "",
            "numero_documento": code_text(column_for(row, mapa, "numero_documento")) or "",
            "nombre": clean_text(column_for(row, mapa, "nombre")) or "",
            "porcentaje": clean_text(column_for(row, mapa, "porcentaje")) or "",
            "condicion": clean_text(column_for(row, mapa, "condicion")) or "",
        })
    n["titulares"] = len(titulares)
    return titulares, n


def _texto_de_metodo(value):
    """The method text as it is compared with an alias: collapsed and upper-cased."""
    return (clean_text(value) or "").upper()


def vinculos_de(filas, mapa, alias, opciones):
    """(code -> vinculo_metodo, problems) from the vínculos csv rows. `alias` maps a method text (as
    _texto_de_metodo leaves it) to an enum option. Each unknown text is one problem, with its row count."""
    vinculos, desconocidos = {}, Counter()
    for row in filas:
        codigo = code_text(column_for(row, mapa, "codigo_municipal"))
        texto = clean_text(column_for(row, mapa, "metodo"))
        if not codigo:
            continue
        if texto is None:
            metodo = ""
        else:
            metodo = alias.get(_texto_de_metodo(texto)) or enum_option(texto, opciones)[0]
            if metodo is None:
                desconocidos[texto.upper()] += 1
                continue
        vinculos.setdefault(codigo, metodo)
    problems = [f"vinculo_metodo '{texto}' ({veces} rows) is not one of {', '.join(opciones)}: map it with "
                f"--metodo '{texto}=<option>'" for texto, veces in desconocidos.items()]
    return vinculos, problems


def _alias(pares, opciones):
    """(alias, problems) from the --metodo TEXTO=ENUM flags."""
    alias, problems = {}, []
    for par in pares:
        texto, _, opcion = par.partition("=")
        metodo, _ = enum_option(opcion, opciones)
        if not _texto_de_metodo(texto) or metodo is None:
            problems.append(f"--metodo {par}: expected TEXTO=<option>, option one of {', '.join(opciones)}")
            continue
        alias[_texto_de_metodo(texto)] = metodo
    return alias, problems


def _dentro_del_repositorio(path):
    real, repo = os.path.realpath(path), os.path.realpath(REPOSITORIO)
    return os.path.commonpath([real, repo]) == repo


def _escribir(path, columnas, filas):
    """Writes the csv with mode 0o600: it holds datos personales (Ley 29733)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(filas)


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Turn Ica's comparison workbook into the csv of import_fichas.py --entrega.")
    p.add_argument("--libro", required=True, help="the comparison workbook (xlsx)")
    p.add_argument("--salida", required=True, help="the directory for fichas.csv, pisos.csv and titulares.csv, outside "
                                                  "the repository (datos personales)")
    p.add_argument("--vinculos", help="csv exported from the lotes gpkg (ogr2ogr -f CSV), one row per lote with "
                                      "cod_predio_rentas and vinculo_metodo; without it every ficha is loaded")
    for name in ("map-predio", "map-construccion", "map-titulares", "map-vinculos"):
        p.add_argument(f"--{name}", action="append", default=[], metavar="FIELD=COLUMN",
                       help="column that fills a field")
    p.add_argument("--metodo", action="append", default=[], metavar="TEXTO=ENUM",
                   help="a vínculo method text that means an option of the enum vinculo_metodo (repeatable)")
    p.add_argument("--anio-maximo", type=int, default=ANIO_MAXIMO,
                   help=f"the last year of construction kept (default {ANIO_MAXIMO})")
    p.add_argument("--model", default=os.path.join(HERE, "model.json"))
    return p.parse_args(argv)


def _error(problems):
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    return 2


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if _dentro_del_repositorio(args.salida):
        return _error([f"--salida {args.salida} is inside the repository: the output holds datos personales "
                       "(Ley 29733), write it outside"])
    try:
        mapas = {"predio": parse_map(args.map_predio, PREDIO_COLUMNS),
                 "construccion": parse_map(args.map_construccion, CONSTRUCCION_COLUMNS),
                 "titulares": parse_map(args.map_titulares, TITULAR_COLUMNS),
                 "vinculos": parse_map(args.map_vinculos, VINCULO_COLUMNS)}
        enums = load_enums(args.model)
    except INPUT_ERRORS as e:
        return _error([str(e)])
    alias, problems = _alias(args.metodo, enums["vinculo_metodo"])
    if problems:
        return _error(problems)
    try:
        predios = read_table(args.libro, HOJA_PREDIO)
        construcciones = read_table(args.libro, HOJA_CONSTRUCCION)
        titular_filas = read_table(args.libro, HOJA_TITULARES)
        vinculo_filas = read_table(args.vinculos) if args.vinculos else None
    except INPUT_ERRORS as e:
        return _error([f"input: {e}"])

    requeridas = [f for f in PREDIO_COLUMNS if f not in PREDIO_OPCIONALES]
    problems = [f"{HOJA_PREDIO}: {p}" for p in missing_columns(predios, mapas["predio"], requeridas)]
    problems += [f"{HOJA_CONSTRUCCION}: {p}"
                 for p in missing_columns(construcciones, mapas["construccion"], list(CONSTRUCCION_COLUMNS))]
    problems += [f"{HOJA_TITULARES}: {p}"
                 for p in missing_columns(titular_filas, mapas["titulares"], list(TITULAR_COLUMNS))]
    vinculos = None
    if vinculo_filas is not None:
        faltan = missing_columns(vinculo_filas, mapas["vinculos"], list(VINCULO_COLUMNS))
        problems += [f"--vinculos: {p}" for p in faltan]
        if not faltan:
            vinculos, more = vinculos_de(vinculo_filas, mapas["vinculos"], alias, enums["vinculo_metodo"])
            problems += more
    if problems:
        return _error(problems)

    def codigos_de(filas, mapa):
        return {c for c in (code_text(column_for(r, mapa, "codigo_municipal")) for r in filas) if c}

    fichas, n_fichas = fichas_de(predios, codigos_con_piso(construcciones, mapas["construccion"]),
                                 codigos_de(titular_filas, mapas["titulares"]), vinculos, mapas["predio"])
    codigos = {f["cod_pre"] for f in fichas}
    pisos, n_pisos = pisos_de(construcciones, codigos, mapas["construccion"], enums, args.anio_maximo)
    titulares, n_titulares = titulares_de(titular_filas, codigos, mapas["titulares"])

    # a column the libro lacks, or vinculo_metodo without --vinculos, is left out, so the upsert leaves that field as
    # it is (ruling R11, README «Entregas»)
    con_cuc = bool(predios) and mapas["predio"]["cuc"].lower() in predios[0]
    columnas_fichas = [c for c in FICHAS_CSV if (c != "cuc" or con_cuc) and (c != "vinculo_metodo" or vinculos is not None)]
    try:
        os.makedirs(args.salida, exist_ok=True)
        _escribir(os.path.join(args.salida, "fichas.csv"), columnas_fichas, fichas)
        _escribir(os.path.join(args.salida, "pisos.csv"), PISOS_CSV, pisos)
        _escribir(os.path.join(args.salida, "titulares.csv"), TITULARES_CSV, titulares)
    except OSError as e:
        return _error([f"output: {e}"])

    if vinculos is not None:
        print(f"vinculos: {len(vinculos)}")
    for conteos, n in ((CONTEOS_FICHAS, n_fichas), (CONTEOS_PISOS, n_pisos), (CONTEOS_TITULARES, n_titulares)):
        for clave in conteos:
            print(f"{clave}: {n[clave]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
