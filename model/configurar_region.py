#!/usr/bin/env python3
"""Fija la región de la organización en un wasichai Core del catastro: el registro único de configuracion_catastro.

El motor de valuación usa las tablas de esa región (valores unitarios y obras complementarias de la R.M.
277-2025-VIVIENDA) y no tiene región por omisión: sin este registro, o con dos, GET /api/catastro/valuaciones falla
con 409. La organización es la del usuario con que se entra (--email). Perené es SELVA; Ica, COSTA.

Es idempotente: crea el registro si falta, lo cambia si dice otra región y no escribe si ya dice la pedida. Con dos o
más registros no elige uno: sale con 2 y hay que borrar los sobrantes en el admin de core.

Correr: python3 configurar_region.py --region SELVA [--dry-run] [--core URL] [--email E] [--password P]
Salida: 0 si va bien, 1 si core rechaza algo o no responde, 2 si la región no es del modelo o hay más de un registro.
"""
import argparse
import json
import os
import sys

from core_client import Client, CoreError

OBJETO = "configuracion_catastro"
MODELO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.json")


def regiones():
    """Las opciones del enum region_catastro de model.json."""
    with open(MODELO, encoding="utf-8") as f:
        return json.load(f)["enums"]["region_catastro"]


def _fatal(method, path, err):
    print(f"error {method} {path} -> {err.status}\n{err.body}", file=sys.stderr)


def configurar(client, region, out=None):
    """Deja un solo registro con la región. 0, 1 (core) o 2 (más de un registro)."""
    out = out or sys.stdout
    path = f"/api/objects/{OBJETO}/records"
    try:
        registros = client.list_all(OBJETO)
    except CoreError as e:
        _fatal("GET", path, e)
        return 1
    if len(registros) > 1:
        print(f"error: la organización tiene {len(registros)} registros de {OBJETO}; debe tener uno solo. "
              "Borra los sobrantes en el admin de core y vuelve a correr esto.", file=sys.stderr)
        return 2
    if not registros:
        try:
            client.post(path, {"attributes": {"region": region}})
        except CoreError as e:
            _fatal("POST", path, e)
            return 1
        print(f"create {OBJETO} region={region}", file=out)
        return 0
    registro = registros[0]
    actual = (registro.get("attributes") or {}).get("region")
    if actual == region:
        print(f"skip   {OBJETO} (ya dice region={region})", file=out)
        return 0
    path = f"{path}/{registro['id']}"
    try:
        client.put(path, {"attributes": {"region": region}})
    except CoreError as e:
        _fatal("PUT", path, e)
        return 1
    print(f"update {OBJETO} region {actual} -> {region}", file=out)
    return 0


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Fija la región (configuracion_catastro) de la organización en wasichai Core.")
    p.add_argument("--region", required=True, help="una opción de region_catastro en model.json: " + ", ".join(regiones()))
    p.add_argument("--core", default=os.environ.get("WASICHAI_CORE", "http://localhost:8091"))
    p.add_argument("--email", default=os.environ.get("WASICHAI_EMAIL", "admin@wasichai.local"))
    p.add_argument("--password", default=os.environ.get("WASICHAI_PASSWORD", "admin"))
    p.add_argument("--dry-run", action="store_true", help="imprime lo que mandaría a un core vacío; no llama a core")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    region = args.region.strip().upper()
    if region not in regiones():
        print(f"error: la región '{region}' no está en region_catastro de model.json ({', '.join(regiones())})", file=sys.stderr)
        return 2
    if args.dry_run:
        print(f"# POST /api/objects/{OBJETO}/records (si la organización aún no tiene uno)")
        print(json.dumps({"attributes": {"region": region}}, indent=2, ensure_ascii=False))
        return 0
    client = Client(args.core)
    try:
        client.login(args.email, args.password)
    except CoreError as e:
        _fatal("POST", "/api/auth/login", e)
        return 1
    return configurar(client, region)


if __name__ == "__main__":
    sys.exit(main())
