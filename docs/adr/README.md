# Registros de decisiones (ADRs)

Un archivo por decisión, numerado en orden. Cómo se escriben y cuándo hace falta uno:
[ADR-001](0001-registrar-las-decisiones-en-adrs.md). Una decisión nunca se edita para cambiarla: un ADR posterior la
enmienda o la reemplaza, y lo dice en su línea de estado. Las de wasichai, el framework, están en
[wasichai/docs/adr](https://github.com/wasichai/wasichai/tree/main/docs/adr).

- [ADR-001: Las decisiones se registran en ADRs](0001-registrar-las-decisiones-en-adrs.md)
- [ADR-002: catastro-backend es un servicio aparte de srtm-backend, sobre wasichai, que no calcula
  impuestos](0002-un-servicio-aparte-de-srtm-sobre-wasichai.md)
- [ADR-003: Se valoriza al vuelo, sin guardar, y la respuesta dice la versión del
  motor](0003-valorizar-al-vuelo-sin-guardar.md)
- [ADR-004: Las tablas normativas son CSV versionados en el jar, citan su fuente y nunca convierten un hueco en
  cero](0004-tablas-normativas-como-csv-versionados.md)
- [ADR-005: El motor es una función pura, y un dato que falta da un motivo, nunca un
  cero](0005-el-motor-es-una-funcion-pura.md)
- [ADR-006: La región es de la organización, y no hay región por omisión](0006-la-region-es-de-la-organizacion.md)
- [ADR-007: srtm lee las valuaciones con una cuenta de servicio de solo lectura, por páginas
  estables](0007-srtm-lee-con-una-cuenta-de-servicio.md)
- [ADR-008: El modelo y los cargadores son Python con la biblioteca estándar, idempotentes y
  aislados](0008-modelo-y-cargadores-en-python-stdlib.md)
- [ADR-009: Decisiones normativas de la valorización (D1 a D12)](0009-decisiones-normativas-de-la-valorizacion.md)
- [ADR-010: La clasificación de cada construcción manda sobre el uso, y la costa redondea el VU al céntimo
  (valuacion-v2)](0010-la-clasificacion-manda-y-la-costa-redondea.md)
- [ADR-011: srtm valúa insumos sueltos con el mismo motor, sin guardar, y esa respuesta trae el
  detalle](0011-srtm-valua-insumos-sueltos-con-el-mismo-motor.md)
- [ADR-012: Los aranceles son de srtm, y su cuenta de servicio escribe la copia con que valúa el
  catastro](0012-los-aranceles-son-de-srtm-y-catastro-guarda-la-copia.md)
- [ADR-013: El levantamiento llega por entregas, se carga solo por la API y no guarda
  estimaciones](0013-el-levantamiento-llega-por-entregas.md)

## Plantilla

```markdown
# ADR-NNN: Título que dice la decisión

**Estado**: propuesta | aceptada · AAAA-MM-DD [· enmienda / reemplaza a ADR-NNN]

## Contexto

Qué problema hay y qué lo hace necesario ahora.

## Alternativas

- **Opción**: por qué no.

## Decisión

Qué se hace, en presente.

## Consecuencias

- Lo que cambia, lo que cuesta y lo que queda abierto.
```
