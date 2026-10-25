# ADR-003: Se valoriza al vuelo, sin guardar, y la respuesta dice la versión del motor

**Estado**: aceptada · 2026-10-19 · ampliada por [ADR-011](0011-srtm-valua-insumos-sueltos-con-el-mismo-motor.md)
· enmendada por [ADR-014](0014-srtm-sigue-los-cambios-por-un-cursor.md) (srtm vuelve a valuar solo si hubo cambios)

## Contexto

srtm pide las valuaciones de un año para una corrida de la brecha. El levantamiento cambia (se cargan fichas, se
corrige un piso, se suma la clasificación de cada nivel) y la aritmética también (D4, el redondeo de la costa). Si el
catastro guardara el autoavalúo, habría que recalcularlo en cada cambio y saber cuál está vencido.

## Alternativas

- **Guardar el autoavalúo por predio y año**: lecturas más baratas, pero un cálculo guardado puede quedar viejo
  respecto de la ficha o del motor, y hace falta un proceso de recálculo.
- **Un job que valorice y publique un archivo**: otra pieza que operar, y srtm leería una foto que no sabe de cuándo es.

## Decisión

`GET /api/catastro/valuaciones?anio=` valoriza cada página en el momento, desde los registros del Core y las tablas en
memoria. No se guarda nada. Cada respuesta lleva `version` (`ValuacionesService.VERSION`, `valuacion-vN`), que cambia
**solo** cuando cambia la aritmética del motor, y `region`, la de los cuadros con que se valorizó.

## Consecuencias

- La cifra siempre es la de los datos de ahora; no hay recálculo ni caché que invalidar.
- srtm guarda la `version` con cada corrida: dos corridas con versiones distintas no son comparables cifra a cifra.
- Un cambio de aritmética sube la versión y suma una fila a la tabla «Versión del motor» del README (`valuacion-v1`,
  `valuacion-v2`...), en el mismo PR. Ver [releases](../develop/releasing.md).
- Cada página cuesta un cálculo; con `size` hasta 500 y una función pura
  ([ADR-005](0005-el-motor-es-una-funcion-pura.md)) es barato frente a la lectura de la base.
