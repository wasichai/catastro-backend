# ADR-011: srtm valúa insumos sueltos con el mismo motor, sin guardar, y esa respuesta trae el detalle

**Estado**: aceptada · 2026-10-20 · amplía [ADR-003](0003-valorizar-al-vuelo-sin-guardar.md) y
[ADR-007](0007-srtm-lee-con-una-cuenta-de-servicio.md)

## Contexto

srtm necesita valuar predios que no están en el levantamiento, o que están con otros datos: la declaración jurada de un
contribuyente, un predio del padrón externo (srtm-backend#126). Con `GET /api/catastro/valuaciones` solo puede leer los
predios del catastro. Para comparar, el valor tiene que salir con las mismas tablas, la misma región y la misma
aritmética que el catastro, y quien revisa la cifra necesita ver cómo se llegó a ella.

## Alternativas

- **Que srtm copie el motor**: dos implementaciones de D1 a D12 que divergen con el primer cambio, y las tablas
  normativas en dos repositorios.
- **Cargar la DJ como una ficha más del catastro y valorizarla con el GET**: mezcla lo declarado con lo levantado, que
  es justo lo que la brecha compara ([ADR-002](0002-un-servicio-aparte-de-srtm-sobre-wasichai.md)).
- **Agregar el detalle también al GET**: cambia un contrato que srtm ya consume, y multiplica el tamaño de cada página.

## Decisión

- `POST /api/catastro/valuacion` recibe los insumos de un predio con la forma de `Insumos` (año, terreno, `arancelM2`,
  uso, `esEdificio`, construcciones y obras, con los nombres y los enums del modelo) y los valúa con
  `Valorizacion.valorizar` y las tablas de la región de la organización. **No se guarda nada**, como en el
  [ADR-003](0003-valorizar-al-vuelo-sin-guardar.md).
- Solo `anio` es obligatorio (y `piso` en cada construcción). Lo que no viene queda sin declarar y da un `motivo`,
  nunca un cero ([ADR-005](0005-el-motor-es-una-funcion-pura.md)). Un campo de más o de otro tipo es un 422 que lo
  nombra.
- Sin `arancelM2` y con `codigoMunicipal`, se toma el arancel del año de esa ficha (`origenArancel` = `FICHA`). Solo
  el arancel: lo demás es del cuerpo.
- Un año sin tablas sale sin valor (`PARAMETRO_FALTANTE:...`): no se valúa con las de otro año.
- La respuesta trae `detalle` por piso y por obra (VU del cuadro, incremento, tabla, antigüedad, % de depreciación, VU
  depreciado y valor), en el orden del cuerpo. `GET /valuaciones` no lo trae: su contrato no cambia.
- El permiso es el mismo que el del GET: `READ` del rol `SRTM_LECTOR`, 401/403/409 iguales.
- El área común no se valúa: el motor no tiene ese insumo.

## Consecuencias

- Hay un solo motor para lo levantado y lo declarado; un cambio de aritmética sube la `version` de las dos respuestas.
- El cuerpo es un contrato más con srtm-backend: un campo nuevo es opcional; uno que cambia de sentido se coordina.
- El detalle es lo que explica una cifra en el portal de srtm; `DetalleTest` fija cada paso (incremento, tabla,
  redondeo de la costa, celdas `*`).
- Valuar el área común queda abierto hasta que el motor la tenga como insumo.
