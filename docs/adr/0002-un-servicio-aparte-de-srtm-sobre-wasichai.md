# ADR-002: catastro-backend es un servicio aparte de srtm-backend, sobre wasichai, que no calcula impuestos

**Estado**: aceptada · 2026-10-19

## Contexto

srtm-backend es el sistema de rentas municipales: padrón declarado, declaraciones juradas, impuesto predial, arbitrios.
Para calcular la **brecha de recaudación** necesita el autoavalúo que el catastro le daría a cada predio, para
compararlo con el declarado. Ese autoavalúo sale del levantamiento catastral (fichas, pisos, obras, aranceles, lotes),
que es otro dato, de otra área de la municipalidad, con otro ciclo de carga.

## Alternativas

- **Un módulo más de srtm-backend**: una sola base y un solo despliegue, pero mezcla el padrón declarado con el
  levantamiento, y un catastro no podría servir a otro sistema de rentas ni desplegarse por municipalidad.
- **Que el catastro calcule también el impuesto**: duplicaría la liquidación (UIT, tramos, mínimo) que ya es de srtm.

## Decisión

Un servicio propio, `catastro-backend`, sobre el mismo framework que srtm (wasichai 1.2.0: core y gis), con su propia
base (PostGIS en 5434) y su propio puerto (8091). Valoriza cada predio del levantamiento —terreno, construcción y
obras, con aranceles, valores unitarios y depreciación— y **no calcula impuestos**: el impuesto predial y la brecha son
de srtm-backend. Comparte con srtm la forma del proyecto (Gradle, CI, release-please, `model/` en Python) y las llaves
de cruce (D7: `codigo_municipal` = `predio.codigo` de srtm).

## Consecuencias

- Hay un catastro por municipalidad (o por organización), y srtm lee el de cada una (srtm-backend#130).
- La interfaz entre los dos es una sola API de lectura ([ADR-007](0007-srtm-lee-con-una-cuenta-de-servicio.md)).
- Un cambio en el modelo de srtm que afecte la llave de cruce o los catálogos compartidos (`usos_predio`, obras) se
  coordina entre los dos repositorios.
- La forma del repositorio sigue a srtm-backend: lo que se mejora en uno (CI, docs, releases) se lleva al otro.
