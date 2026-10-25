# ADR-013: El levantamiento llega por entregas, se carga solo por la API y no guarda estimaciones

**Estado**: aceptada · 2026-10-25 · enmienda [ADR-008](0008-modelo-y-cargadores-en-python-stdlib.md) (con `--entrega`,
los cargadores actualizan, no solo crean)

## Contexto

El levantamiento catastral cambia: hay barridos de campo, inspecciones de fiscalización, licencias, y el GIS de la
municipalidad se corrige. Pero los cargadores solo crean. `import_fichas.py` salta un predio que el Core ya tiene y no
toca sus pisos ni sus obras, e `import_lotes.py` salta un predio que ya tiene `lote_geom`. Una entrega nueva no tiene
cómo entrar, ni una ficha corregida cómo recargarse.

Tampoco se sabía si una ficha se levantó. En Ica, el libro de comparación trae unas 9 800 fichas vacías: sin titular,
construcción ni urbanización, y con área 0. Son lotes cartografiados que nadie levantó. Cuando se cargaron con el área
de rentas, como en la prueba del VPS, la brecha las contó como «coincide»: comparaba rentas consigo misma.

## Alternativas

- **Cargar las entregas por SQL**: se salta los permisos de wasichai y su `audit_log`, y con ellos la historia de cada
  ficha.
- **Llenar los huecos con lo que declara rentas** (área, arancel o uso): la brecha compararía rentas consigo misma, y
  una ficha sin levantar se vería levantada.
- **Borrar solas las fichas ausentes**: una entrega parcial (un sector, una inspección) borraría el resto del catastro.

## Decisión

- El levantamiento llega por entregas (`entrega_catastral`: código, fecha de corte, fuente, sha256 de los archivos y
  resumen) y se carga solo por la API, nunca por SQL. `import_fichas.py --entrega` hace upsert por
  `codigo_municipal`: escribe solo lo que cambió, con `PATCH` de los campos cambiados, y compara solo las columnas que
  el archivo trae.
- El catastro no guarda estimaciones sacadas de rentas (área, arancel o uso). Las estimaciones son escenarios del
  análisis, no datos del catastro: una ficha sin levantar queda `SIN_LEVANTAR`, y el motor da un motivo, no un valor
  ([ADR-005](0005-el-motor-es-una-funcion-pura.md)). Una celda vacía en una columna que la entrega trae borra el campo,
  así que una entrega quita las estimaciones que se hubieran cargado.
- El `reason` (`X-Change-Reason`) de cada escritura es el código de la entrega, y cada predio apunta a la última entrega
  que lo cambió a él o a sus pisos u obras.

## Consecuencias

- La historia de cada ficha vive en el `audit_log` de wasichai: qué entrega cambió qué campo, y cuándo. El catastro no
  guarda versiones propias.
- Una ficha ausente (en el Core y no en la entrega) se lista y se queda; borrarla es una decisión a mano. Los pisos y
  obras que una ficha ya no trae se borran solo con `--reemplazar-pisos` / `--reemplazar-obras`.
- La entrega se registra una vez, con el resumen de la primera corrida que escribe; volver a cargarla con los mismos
  archivos completa una carga que falló a medias y no cambia nada más, y el mismo código con otros archivos se rechaza.
- Las estimaciones a partir de rentas se hacen en el análisis, como escenarios (srtm-backend#205), nunca dentro del
  catastro.
