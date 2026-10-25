# ADR-014: srtm sigue los cambios del catastro por un cursor, y catastro los lee del audit log de wasichai

**Estado**: aceptada · 2026-10-25 · enmienda [ADR-003](0003-valorizar-al-vuelo-sin-guardar.md) y
[ADR-007](0007-srtm-lee-con-una-cuenta-de-servicio.md) (srtm sigue los cambios con la misma cuenta)

## Contexto

srtm no tiene cómo saber qué cambió en el catastro. En cada corrida trae todas las valuaciones del año
([ADR-003](0003-valorizar-al-vuelo-sin-guardar.md), [ADR-007](0007-srtm-lee-con-una-cuenta-de-servicio.md)), y no
sabe si algo cambió desde la anterior. Lo necesita para avisar a rentas de un cambio, como una ampliación levantada
en campo, y para volver a correr la brecha solo cuando hace falta.

wasichai ya guarda los cambios. Cada alta, cambio y baja queda en su `audit_log`, que es inmutable, y desde
[ADR-013](0013-el-levantamiento-llega-por-entregas.md) el `reason` de cada escritura de un cargador es el código de
la entrega. Pero el audit log va por id de registro y por nombre de objeto. Para leerlo, srtm tendría que conocer el
modelo del catastro y averiguar a qué predio pertenecía una construcción ya borrada.

## Alternativas

- **Una réplica o un FDW de la base del catastro**: wasichai guarda cada organización en sus propias tablas, con
  columnas calientes que cambian de forma, así que una réplica se rompe sola, y además salta los permisos de wasichai.
- **Webhooks de catastro a srtm**: sería una entrega más que hay que volver confiable, con reintentos, orden y un
  receptor siempre arriba.
- **Que srtm lea `GET /api/audit` de wasichai**: pide un `READ` sobre toda la organización (el de SRTM_LECTOR es por
  objeto), obliga a srtm a conocer el modelo del catastro y ordena del más nuevo al más viejo.
- **Una tabla de cambios propia del catastro**: sería una segunda historia junto al `audit_log`, que puede
  contradecirlo.

## Decisión

- `GET /api/catastro/cambios?desde=<cursor>&size=` (`size` de 1 a 500, 200 por omisión) devuelve, del más viejo al
  más nuevo, las altas, cambios y bajas (`CREATE`, `UPDATE`, `DELETE`) de `predio_catastral`, `construccion`,
  `obra_complementaria` y `titular_catastral`. Cada ítem trae `codigoMunicipal`, `objeto`, `operacion`, los nombres
  de los `campos` que cambiaron (nunca sus valores), `en` y `entrega`, que es el `reason` cuando coincide con el código
  de una `entrega_catastral`. El código de una construcción u obra es el de su predio, que se lee del último estado
  de ese predio en el audit log, así que sale aunque el predio esté borrado. Si no se puede resolver, es `null`.
- El cursor es opaco y estable. Las filas van por `(occurred_at, id)` ascendente, y cada página empieza justo después
  del cursor. Si no hay nada nuevo, devuelve el mismo cursor, `items` vacío y `hayMas = false`. Un `desde` que este
  endpoint no escribió da 422.
- Catastro lee `${schemas.metadata}.audit_log` dentro de su propio proceso, con `DatabaseClient`, después de verificar
  `READ` sobre cada uno de esos cuatro objetos y sobre `entrega_catastral` (`CurrentUser.requirePermission`). srtm no
  conoce ni el audit log ni el modelo.
- Se sigue valorizando al vuelo ([ADR-003](0003-valorizar-al-vuelo-sin-guardar.md)). srtm vuelve a pedir las
  valuaciones solo cuando hubo cambios. La cuenta de servicio de [ADR-007](0007-srtm-lee-con-una-cuenta-de-servicio.md)
  lee los cambios con el mismo rol, SRTM_LECTOR, sin permisos nuevos.

## Consecuencias

- **El feed puede perder un cambio.** `RecordChanges` de wasichai no guarda el registro y su fila de auditoría en una
  misma transacción, y `occurred_at` es el inicio de la transacción. Por eso una fila que se confirma tarde, con un
  `occurred_at` anterior a un cursor ya entregado, no se ve. srtm lo cubre con una corrida completa cada semana
  (wasichai/srtm-backend#203).
- Catastro queda atado a las columnas del `audit_log` de wasichai (`BitacoraDeCambios` es el único lugar que las
  conoce). Una versión de wasichai que toque el `audit_log` tiene que mantener verde `CambiosApiTest`.
- Si hace falta cerrar el hueco en el framework, eso se pide con un issue en wasichai, no se arregla en catastro.
