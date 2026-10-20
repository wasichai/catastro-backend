# ADR-008: El modelo y los cargadores son Python con la biblioteca estándar, idempotentes y aislados

**Estado**: aceptada · 2026-10-19 · enmendada el 2026-10-20 (`python3 -I`)

## Contexto

El modelo del catastro (objetos, campos, relaciones) se crea en el Core de wasichai por su API, y el levantamiento
llega en archivos de afuera (csv, xlsx, GeoJSON sacado de la geodatabase con `ogr2ogr`) que traen datos personales.
srtm-backend ya resolvió lo mismo con `model/` en Python.

## Alternativas

- **Migraciones Flyway propias**: wasichai crea las tablas físicas a partir de los metadatos; escribirlas a mano
  saltaría su modelo.
- **Cargadores en Kotlin dentro del servidor**: cada carga sería un endpoint y un release.
- **Python con dependencias (pandas, openpyxl)**: un `pip install` en cada máquina y en el CI, y más superficie.

## Decisión

- `model/model.json` declara el modelo; `apply.py` lo aplica (`--validate-only` sin red, `--diff` sin escribir).
- Los cargadores (`import_fichas.py`, `import_aranceles.py`, `import_lotes.py`) y las tareas de puesta en marcha
  (`apply_roles.py`, `configurar_region.py`, `crear_cuenta_srtm.py`) son Python 3.11+ **solo con la biblioteca
  estándar** (el xlsx se lee como zip, `tabular.py`), con la forma de los de srtm-backend.
- Todos aceptan `--core`, `--email`, `--password` (o `WASICHAI_*`) y `--dry-run`, y son **idempotentes**: solo crean
  lo que falta, por llave natural.
- Si una fila no encaja salen con código 2, listan todas las filas malas y no envían nada; un rechazo del Core sale
  con 1.
- Se corren con `python3 -I`, porque leen archivos de afuera: ni el directorio actual ni `PYTHONPATH` entran al
  `sys.path`; cada comando vuelve a poner solo `model/` (`test_isolated.py` lo prueba).
- Se prueban contra `fake_core.py`, sin red, en el job *Model and importer* del CI.

## Consecuencias

- Una carga que falló a medias se completa volviendo a correrla.
- Un piso que el Core ya tiene no se actualiza: cambiarlo es editarlo en el Core.
- Los archivos de origen y `model/reports/` no se versionan (`.gitignore`): traen datos personales.
