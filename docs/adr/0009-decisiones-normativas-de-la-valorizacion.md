# ADR-009: Decisiones normativas de la valorización (D1 a D12)

**Estado**: aceptada · 2026-10-19 · D1 y D4 investigadas el 2026-10-20 · D1 enmendada por
[ADR-010](0010-la-clasificacion-manda-y-la-costa-redondea.md) · D1 y D8 tienen partes abiertas

## Contexto

La norma (R.M. N.° 277-2025-VIVIENDA, el Reglamento Nacional de Tasaciones) deja huecos y erratas que el motor tiene
que resolver de una sola manera: qué tabla de depreciación toca a cada uso, cómo se suman las partidas del cuadro, qué
hacer con una casilla vacía. Cada una cambia el autoavalúo de muchos predios, así que se le preguntó a la
municipalidad, que las confirmó el 2026-10-19. D1 y D4 se investigaron el 2026-10-20.

Hasta el [ADR-001](0001-registrar-las-decisiones-en-adrs.md) vivían en la sección «Decisiones normativas» del README;
se trasladan aquí tal como estaban. Una decisión de esta lista que cambie (por ejemplo, la parte abierta de D1) es un
ADR nuevo que nombra la Dn que enmienda.

## Alternativas

Cada Dn descarta la lectura contraria, que se cita en su texto cuando hubo duda (D1: institucional en 02 o 03; D4:
«una de las 3 columnas» frente a sumar las tres).

## Decisión

- **D1** uso a tabla de depreciación, por prefijo del código de `usos_predio` de srtm (`uso-tabla-depreciacion.csv`, con
  la fuente de cada fila). Ninguna norma asigna usos a tablas: el RNT solo da los títulos de las Tablas 01 a 04 y dice
  «en función de su uso» (art. 13.4). Residencial a 01; comercio, depósitos, recreación e **institucional** a 02 (el
  título de la Tabla 02 dice «instituciones», y así lo tiene el padrón de Perené); oficinas, administración pública,
  financieras y gobierno extranjero a 03; salud, educación, cines, teatros, industria y talleres a 04; terreno,
  desocupado, garage y bienes comunes sin subclase a 01. Cubre los 324 códigos. **Abierto**, para la administración
  tributaria con catastro: institucional en 02 o 03, hoteles (020503), consultorios médicos (03 o 04), servicios que
  pueden ser taller u oficina, conventos y asilos. Conviene pedir el parámetro «Uso Predio – Depreciación» del SRTM del
  MEF (Exportar a Excel) y cotejarlo. Cuando el levantamiento clasifica cada construcción (`construccion.clasificacion`,
  como Ica, que lo hace por nivel), esa clasificación manda y el uso solo decide las construcciones sin ella y las obras.
- **D2** material: CONCRETO a Concreto, LADRILLO a Ladrillo, todo lo demás a la columna `Liviano/Adobe`.
- **D3** estado MUY MALO se trata como Malo; las celdas `*` (ausentes en `depreciacion.csv`) toman el último
  porcentaje publicado de su fila.
- **D4** se suman las 3 partidas (muros y columnas, techos, puertas y ventanas), cada una con su categoría. La nota del
  Anexo I.4 dice «UNA DE LAS 3 COLUMNAS», sin «CADA»: es una errata que la Selva arrastra desde los cuadros de 7
  columnas (la Sierra se corrigió), y el propio cuadro solo tiene sentido sumando. Con **muros A** no se considera
  techos (nota de la casilla: «NO SE CONSIDERA LOS VALORES DE LA COLUMNA N° 2»). Los muros D «drywall o similar incluye
  techo» (llamada 5) tampoco suman techos, pero la letra D sola no los distingue del ladrillo, que también es D: lo
  resuelve el campo `techo_incluido` de la ficha del piso. Sin él (o en falso), D suma techos, que es el caso del
  ladrillo. Marcarlo con muros que no sean A ni D es un error de captura: el predio queda sin valorizar con la llave
  `TECHO_INCLUIDO_INVALIDO:<letra>`.
- **D5** las celdas `.....` no son cero: el predio recibe un `motivo` (sin valor).
- **D6** porcentaje de actualización 2026 = 0.
- **D7** llave de cruce catastro y srtm: código municipal (= `predio.codigo` de srtm), luego `codigo_cpu`, luego
  (sector, manzana, lote).
- **D8** deducción Amazonía: no aplica a Perené hoy. **Abierta** para cuando se cargue una municipalidad de la
  Amazonía (parámetro anual en srtm; antes, revisar si la deducción del padrón ya la incluye).
- **D9** obras complementarias: VU × cantidad × 0.68 × (1 − dep%), con la tabla del predio y el material, estado y
  antigüedad propios de la obra.
- **D10** COINCIDE cuando |Δ autoavalúo| <= 5 %.
- **D11** solo el año 2026.
- **D12** varias secuencias de uso: el valor del catastro se reparte proporcional al autoavalúo declarado de cada una
  (si no hay, por área construida).

Además: +5 % al VU por piso cuando piso >= 5 (documento de VU, §1.6), aplicado antes de la depreciación.

## Consecuencias

- El motor ([ADR-005](0005-el-motor-es-una-funcion-pura.md)) implementa cada Dn con su prueba; un predio que una Dn
  deja sin valor sale con su llave (`TECHO_INCLUIDO_INVALIDO:<letra>` por D4, `VU_SIN_VALOR:<partida>:<letra>` por D5).
- `uso-tabla-depreciacion.csv` (D1) es editable y cita la fuente de cada fila; cambiarlo es un PR con un ADR que
  enmiende D1.
- Lo abierto (D1: institucional, hoteles, consultorios, talleres, conventos y asilos; D8: deducción Amazonía) se cierra
  con un ADR nuevo cuando la administración tributaria responda.
