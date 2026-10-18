#!/usr/bin/env python3
"""Crea en un wasichai Core la cuenta de servicio con la que srtm-backend lee las valuaciones del catastro.

La cuenta (`srtm` por defecto) lleva el rol SRTM_LECTOR de roles.json, que apply_roles.py crea antes: sin él la cuenta
no se crea. Core muestra el clientSecret una sola vez, al crearla (POST /api/service-accounts): este comando lo imprime
esa vez, con el clientId, para guardarlos en el entorno de srtm-backend (SRTM_CATASTRO_CLIENT_ID y
SRTM_CATASTRO_CLIENT_SECRET). No se guarda en ningún otro lado.

Es idempotente: si la cuenta ya existe no la toca más que para darle el rol si le falta, y dice su clientId; el secreto
ya no se puede leer. Uno nuevo se pide con POST /api/service-accounts/{id}/secret (anula el anterior).

Correr: python3 crear_cuenta_srtm.py [--dry-run] [--nombre srtm] [--core URL] [--email E] [--password P]
Salida: 0 si va bien, 1 si core rechaza algo o no responde, 2 si falta el rol o el nombre no es válido.
"""
import argparse
import json
import os
import re
import sys

from core_client import Client, CoreError

ROL = "SRTM_LECTOR"
# ServiceAccountService.NAME (core la pasa a minúsculas antes)
NOMBRE = re.compile(r"^[a-z][a-z0-9_-]{1,48}$")


def _fatal(method, path, err):
    print(f"error {method} {path} -> {err.status}\n{err.body}", file=sys.stderr)


def crear(client, nombre, out=None):
    """Crea la cuenta o la deja con el rol. 0, 1 (core) o 2 (falta el rol)."""
    out = out or sys.stdout
    try:
        roles = {r["name"] for r in client.get("/api/roles") or []}
    except CoreError as e:
        _fatal("GET", "/api/roles", e)
        return 1
    if ROL not in roles:
        print(f"error: core no tiene el rol {ROL}: corre antes python3 apply_roles.py", file=sys.stderr)
        return 2
    try:
        cuentas = client.get("/api/service-accounts") or []
    except CoreError as e:
        _fatal("GET", "/api/service-accounts", e)
        return 1
    cuenta = next((c for c in cuentas if c.get("name") == nombre), None)
    if cuenta is None:
        try:
            _, creada = client.post("/api/service-accounts", {"name": nombre, "roles": [ROL]})
        except CoreError as e:
            _fatal("POST", "/api/service-accounts", e)
            return 1
        print(f"create service account {nombre} ({ROL})", file=out)
        print(f"clientId:     {creada['clientId']}", file=out)
        print(f"clientSecret: {creada['clientSecret']}", file=out)
        print("GUÁRDALOS AHORA en el entorno de srtm-backend como SRTM_CATASTRO_CLIENT_ID y SRTM_CATASTRO_CLIENT_SECRET:"
              " core no vuelve a mostrar el secreto.", file=out)
        return 0
    roles_cuenta = list(cuenta.get("roles") or [])
    if ROL not in roles_cuenta:
        path = f"/api/service-accounts/{cuenta['id']}"
        try:
            client.put(path, {"roles": roles_cuenta + [ROL]})
        except CoreError as e:
            _fatal("PUT", path, e)
            return 1
        print(f"update service account {nombre} (+{ROL})", file=out)
    else:
        print(f"skip   service account {nombre} (ya existe con {ROL})", file=out)
    if cuenta.get("enabled") is False:
        print(f"aviso: la cuenta {nombre} está deshabilitada; se habilita en el admin de core", file=out)
    print(f"clientId: {cuenta['clientId']} (el secreto ya no se puede leer; uno nuevo: "
          f"POST /api/service-accounts/{cuenta['id']}/secret)", file=out)
    return 0


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Crea la cuenta de servicio de srtm-backend (rol SRTM_LECTOR) en wasichai Core.")
    p.add_argument("--nombre", default="srtm")
    p.add_argument("--core", default=os.environ.get("WASICHAI_CORE", "http://localhost:8091"))
    p.add_argument("--email", default=os.environ.get("WASICHAI_EMAIL", "admin@wasichai.local"))
    p.add_argument("--password", default=os.environ.get("WASICHAI_PASSWORD", "admin"))
    p.add_argument("--dry-run", action="store_true", help="imprime lo que mandaría a un core vacío; no llama a core")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    nombre = args.nombre.strip().lower()
    if not NOMBRE.fullmatch(nombre):
        print(f"error: el nombre '{nombre}' no cumple {NOMBRE.pattern}", file=sys.stderr)
        return 2
    if args.dry_run:
        print("# POST /api/service-accounts")
        print(json.dumps({"name": nombre, "roles": [ROL]}, indent=2, ensure_ascii=False))
        return 0
    client = Client(args.core)
    try:
        client.login(args.email, args.password)
    except CoreError as e:
        _fatal("POST", "/api/auth/login", e)
        return 1
    return crear(client, nombre)


if __name__ == "__main__":
    sys.exit(main())
