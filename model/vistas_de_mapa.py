#!/usr/bin/env python3
"""Creates or updates the saved map views of wasichai-gis (ADR-072 of wasichai) for «Aranceles por vía» and «Brechas»,
and publishes their two GeoServer layers with the style of their view (an SLD).

Views (GET/POST /api/gis/objects/{object}/map-views, PUT .../map-views/{name}; MANAGE_METADATA):
  aranceles_valor       tramo_via.geom          by valor_m2, 5 quantiles (catastro-ui's PALETA)
  aranceles_asignacion  tramo_via.geom          by asignacion, categories
  brechas_categoria     brecha_ficha.lote_geom  by categoria, categories (catastro-ui's COLOR_CATEGORIA)
  brechas_estado        brecha_ficha.lote_geom  by estado, categories (catastro-ui's COLOR_ESTADO)
  brechas_delta         brecha_ficha.lote_geom  by delta_impuesto, 5 quantiles
A view Core lacks is created (POST), one whose label, geometry or style differ is updated (PUT), an equal one is left.

Layers (POST /api/gis/layers/{object}/{geometry} with {"style"}): tramo_via.geom with the style of aranceles_valor and
brecha_ficha.lote_geom with that of brechas_categoria. Every run publishes both again, even when nothing else changed:
GeoServer keeps the classes of the publish (the SLD is a snapshot of the quantiles), and in wasichai 1.5.0 republishing
is how the style is refreshed (the style is replaced, the layer kept). So run it again after every
importar_corte_brecha.py and after every POST /api/catastro/vias/valores (README, «Vistas de mapa»). --sin-capas
leaves the layers alone (GeoServer off).

Run: python3 -I vistas_de_mapa.py [--org <organization id>] [--sin-capas] [--dry-run] [--core URL]
Exit: 0 ok, 1 Core refused something (status and body), 2 --org is another organization.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core_client import Client, CoreError  # noqa: E402

GRIS = "#9ca3af"
# catastro-ui src/comun/colores.ts PALETA, light to dark = cheaper to dearer
PALETA = ["#fee391", "#fec44f", "#fe9929", "#d95f0e", "#993404"]
# catastro-ui src/brechas/colores.ts, in the order of the model's enums (categories follow the ENUM's options)
COLOR_CATEGORIA = {"OMISO": "#e15759", "SIN_CATASTRO": "#b07aa1", "SIN_VALOR": "#edc948", "SUBVALUADO": "#f28e2b",
                   "SOBREVALUADO": "#4e79a7", "COINCIDE": "#76b7b2", "SIN_LEVANTAR": GRIS}
COLOR_ESTADO = {"PENDIENTE": "#76b7b2", "A_INSPECCIONAR": "#f28e2b", "INSPECCIONADO": "#4e79a7",
                "A_FISCALIZAR": "#e15759", "DESCARTADO": GRIS}
COLOR_ASIGNACION = {"NOMBRE_UNICO": "#4e79a7", "CERCANIA": "#76b7b2", "LOTES": "#f28e2b", "SIN_ARANCEL": GRIS}
MODEL_PATH = os.path.join(HERE, "model.json")

VISTAS = [
    {"name": "aranceles_valor", "label": "Aranceles: valor por m² del año", "object": "tramo_via", "geometryName": "geom",
     "style": {"by": "valor_m2", "type": "quantiles", "classes": 5, "palette": PALETA}},
    {"name": "aranceles_asignacion", "label": "Aranceles: cómo se asignó el código", "object": "tramo_via",
     "geometryName": "geom", "style": {"by": "asignacion", "type": "categories", "palette": "asignacion_tramo"}},
    {"name": "brechas_categoria", "label": "Brechas: categoría", "object": "brecha_ficha", "geometryName": "lote_geom",
     "style": {"by": "categoria", "type": "categories", "palette": "categoria_brecha"}},
    {"name": "brechas_estado", "label": "Brechas: estado de la decisión", "object": "brecha_ficha",
     "geometryName": "lote_geom", "style": {"by": "estado", "type": "categories", "palette": "estado_decision"}},
    {"name": "brechas_delta", "label": "Brechas: Δ impuesto (catastro − declarado)", "object": "brecha_ficha",
     "geometryName": "lote_geom", "style": {"by": "delta_impuesto", "type": "quantiles", "classes": 5}},
]
COLORES = {"asignacion_tramo": COLOR_ASIGNACION, "categoria_brecha": COLOR_CATEGORIA, "estado_decision": COLOR_ESTADO}
# object, geometry, the view whose style the layer takes
CAPAS = [("tramo_via", "geom", "aranceles_valor"), ("brecha_ficha", "lote_geom", "brechas_categoria")]


def vistas(enums):
    """VISTAS with every categorical palette in the order of its enum's options, as the server classes them."""
    resultado = []
    for vista in VISTAS:
        estilo = dict(vista["style"])
        if isinstance(estilo.get("palette"), str):
            colores = COLORES[estilo["palette"]]
            opciones = enums[estilo["palette"]]
            if set(opciones) != set(colores):
                raise ValueError(f"{vista['name']}: the colours do not cover the options of {estilo['palette']}")
            estilo["palette"] = [colores[o] for o in opciones]
        resultado.append({**vista, "style": estilo})
    return resultado


def _estilo(estilo):
    """A style as compared: without empty keys (Core may answer classes or palette as null)."""
    return {k: v for k, v in (estilo or {}).items() if v is not None}


def difiere(vista, guardada):
    return (guardada.get("label") != vista["label"] or guardada.get("geometryName") != vista["geometryName"]
            or _estilo(guardada.get("style")) != _estilo(vista["style"]))


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Create the map views of aranceles and brechas and publish their layers.")
    p.add_argument("--org", help="the organization id the account must belong to, or nothing is written")
    p.add_argument("--sin-capas", action="store_true", help="do not publish the GeoServer layers")
    p.add_argument("--core", default=os.environ.get("WASICHAI_CORE", "http://localhost:8091"))
    p.add_argument("--email", default=os.environ.get("WASICHAI_EMAIL", "admin@wasichai.local"))
    p.add_argument("--password", default=os.environ.get("WASICHAI_PASSWORD", "admin"))
    p.add_argument("--dry-run", action="store_true", help="read Core and say what would change; write nothing")
    return p.parse_args(argv)


def main(argv=None):
    import json
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    with open(MODEL_PATH, encoding="utf-8") as f:
        todas = vistas(json.load(f)["enums"])
    verbo = "to " if args.dry_run else ""
    client = Client(args.core)
    try:
        client.login(args.email, args.password)
        organization = (client.user or {}).get("organizationId")
        if args.org is not None and organization != args.org:
            print(f"error: --org expects the organization's id, and the account {args.email} is of the organization"
                  f" {organization or '(Core did not say)'}, not {args.org}; nothing was written", file=sys.stderr)
            return 2
        for vista in todas:
            base = f"/api/gis/objects/{vista['object']}/map-views"
            guardada = client.get(f"{base}/{vista['name']}")
            cuerpo = {"label": vista["label"], "geometryName": vista["geometryName"], "style": vista["style"]}
            if guardada is None:
                accion = "create"
                if not args.dry_run:
                    client.post(base, {"name": vista["name"], **cuerpo})
            elif difiere(vista, guardada):
                accion = "update"
                if not args.dry_run:
                    client.put(f"{base}/{vista['name']}", cuerpo)
            else:
                accion = "unchanged"
            print(f"vista {vista['name']}: {verbo if accion != 'unchanged' else ''}{accion}")
        if args.sin_capas:
            print("capas: --sin-capas, not published")
        else:
            estilos = {v["name"]: v["style"] for v in todas}
            for objeto, geometria, vista in CAPAS:
                if not args.dry_run:
                    client.post(f"/api/gis/layers/{objeto}/{geometria}", {"style": estilos[vista]})
                print(f"capa {objeto}.{geometria}: {verbo}publish with the style of {vista}")
    except CoreError as e:
        print(f"error -> {e.status}\n{e.body}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
