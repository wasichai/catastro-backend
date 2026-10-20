# ADR-010: La clasificación de cada construcción manda sobre el uso, y la costa redondea el VU al céntimo (valuacion-v2)

**Estado**: aceptada · 2026-10-20 · enmienda D1 del [ADR-009](0009-decisiones-normativas-de-la-valorizacion.md)

## Contexto

Con Ica (costa) llegó un padrón que clasifica cada nivel (`clasificacion_construccion` 1 a 4 = tablas 01 a 04 del RNT)
y que redondea al céntimo en dos pasos: su `incremento_5` es round(VU × 5 %) y su `valor_total_nivel` es
round((VU + incremento_5) × (1 − dep)) × área. Con `valuacion-v1` (depreciación siempre por el uso del predio, D1, y
sin redondeos intermedios), el motor daba exactamente el `valor_total_nivel` de Ica en 682 de 3755 niveles.

Las cifras de Perené (selva) se verificaron con el motor de kamayuk, sin redondeos intermedios, y no deben cambiar.

## Alternativas

- **Mantener D1 para todos**: ignora un dato del levantamiento más fino que el uso del predio.
- **Redondear igual en todas las regiones**: cambiaría las cifras ya verificadas de Perené.
- **Hacer el redondeo configurable por organización**: es una propiedad de cómo se valoriza en la región, no de cada
  municipalidad, y no hay un segundo caso que lo pida.

## Decisión

- Una construcción con `clasificacion` (cargada por `import_fichas.py`, como opción del enum o como número 1 a 4) se
  deprecia con esa tabla; el uso del predio (D1) decide solo las construcciones sin ella y las obras. Una clasificación
  que el motor no conoce deja al predio sin valor (`CLASIFICACION_DESCONOCIDA:<valor>`).
- Cada sección de un piso (`seccion`) es una construcción más, con el mismo número de piso.
- El redondeo del VU es de la región (`Region.redondeaValorUnitario`): `COSTA` redondea el VU con el +5 % y el VU
  depreciado al céntimo, HALF_UP, antes de multiplicar por el área; `SELVA` no redondea en el medio. Las obras no se
  redondean en ninguna región (ningún padrón ha mostrado cómo lo hace).
- El motor pasa a `valuacion-v2` ([ADR-003](0003-valorizar-al-vuelo-sin-guardar.md)).

## Consecuencias

- Contra el padrón de Ica, el motor da exactamente su `valor_total_nivel` en 3688 de 3755 niveles; los 67 restantes
  están explicados en el README («Contra el padrón de Ica»).
- Un predio de la selva sin `clasificacion`, como los de Perené, da la misma cifra que en v1.
- Una región nueva declara su regla de redondeo en `catastro.tablas.Region`
  ([ADR-006](0006-la-region-es-de-la-organizacion.md)).
- srtm ve el cambio de `version`: las corridas de la brecha anteriores a v2 no se comparan cifra a cifra con las nuevas.
