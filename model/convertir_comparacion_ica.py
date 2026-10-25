#!/usr/bin/env python3
"""Turns Ica's comparison workbook (libro de comparación v3) into the fichas and pisos csv of
`import_fichas.py --entrega`.

Only the catastro side is read (the `*_catastro` sheets); the rentas side is the srtm padrón, never the catastro.
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
Every rule that drops or empties something is counted, so the operator sees what the delivery lost.
"""
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
from tabular import clean_text, code_text, column_for, enum_option, parse_decimal, parse_int  # noqa: E402

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
FICHAS_CSV = ["cod_pre", "cod_sect", "cod_mzn", "cod_lote", "area_terreno", "uso", "id_aranc", "estado_levantamiento",
              "vinculo_metodo", "codigo_referencia_catastral", "cuc"]
PISOS_CSV = ["cod_pre", "piso", "seccion", "area_construida", "anio_construccion", "material", "estado_conservacion",
             *CATEGORIAS]

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
