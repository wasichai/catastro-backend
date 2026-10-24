# ADR-006: La región es de la organización, y no hay región por omisión

**Estado**: aceptada · 2026-10-20

## Contexto

Los valores unitarios de edificación y de obras complementarias son distintos por región (Lima Metropolitana y Callao,
Costa, Sierra, Selva). Perené está en la selva e Ica en la costa, y un mismo despliegue puede servir a más de una
organización de wasichai.

## Alternativas

- **Una región por despliegue (propiedad de Spring)**: un despliegue por municipalidad, y un error de configuración
  valorizaría con el cuadro equivocado sin decir nada.
- **Región por predio**: la demarcación de los cuadros es geográfica y una municipalidad cae entera en una región; la
  ficha no la trae.
- **Selva por omisión** (lo que había antes, con Perené sola): una organización nueva de la costa saldría con cifras
  de la selva.

## Decisión

Cada organización dice su región en **un solo** registro del objeto `configuracion_catastro` (`region` = `COSTA` o
`SELVA`; el enum `region_catastro`), escrito con `model/configurar_region.py`. Sin ese registro, con más de uno, o con
una región sin tablas en el motor, `GET /api/catastro/valuaciones` responde **409** con `errors[0].field` =
`configuracion_catastro.region` y no valoriza nada. La respuesta dice la `region` con que se valorizó.

Agregar una región es: la opción del enum en `model.json`, la constante en `catastro.tablas.Region` (con su regla de
redondeo), y sus CSV de valores unitarios y de obras ([ADR-004](0004-tablas-normativas-como-csv-versionados.md)). El
RNT, los usos y los parámetros son nacionales.

## Consecuencias

- Un catastro sin configurar falla en voz alta, en la primera página, en lugar de valorizar mal.
- La cuenta de servicio de srtm necesita `READ` sobre `configuracion_catastro` (`SRTM_LECTOR`).
- Actualizar un despliegue que ya existe tiene un orden: modelo, rol, región, y recién entonces el jar (README,
  «Actualizar un despliegue que ya existe»).
