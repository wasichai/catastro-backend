# ADR-005: El motor es una función pura, y un dato que falta da un motivo, nunca un cero

**Estado**: aceptada · 2026-10-19

## Contexto

El autoavalúo de un predio combina terreno, cada piso y cada obra, con muchas tablas. Las cifras tienen que coincidir
con las de un padrón real (Perené con el motor de kamayuk; Ica, `ValorizacionCostaTest`) hasta el céntimo, y cuando no
se puede valorizar, srtm necesita saber por qué para no contar ese predio como brecha.

## Alternativas

- **Calcular dentro del servicio, leyendo la base y el reloj**: difícil de probar contra un padrón sin levantar todo.
- **Tratar lo que falta como cero**: un predio sin arancel o con una casilla `.....` saldría con un autoavalúo bajo y
  parecería una brecha a favor del contribuyente.

## Decisión

`catastro.valuacion.Valorizacion.valorizar(insumos, tablas)` es una función pura: sin base, sin reloj, sin Spring.
Recibe la ficha del predio con sus pisos y obras, el año y las tablas de la región, y devuelve el autoavalúo o el
motivo por el que no lo tiene. `ValuacionesService` solo lee los registros, arma los insumos y pagina.

Un dato que falta **no es cero**: el predio sale sin valor (`terreno`, `construccion`, `obras` y `autoavaluo` en
`null`) con un `motivo` para leer y una `llave` para contar (`ARANCEL_FALTANTE`, `VU_SIN_VALOR:TECHOS:I`,
`TABLA_DE_DEPRECIACION:990000`, `OBRAS_SIN_CUADRO:<REGION>`...). Gana el primero, en el orden del motor de kamayuk.
Cada cifra va con 2 decimales, HALF_UP; los redondeos intermedios son de la región
([ADR-010](0010-la-clasificacion-manda-y-la-costa-redondea.md)).

## Consecuencias

- El motor se prueba sin base, con casos del padrón (`ValorizacionTest`, `ValorizacionCostaTest`, `PorSeccionTest`);
  una regla nueva entra primero como prueba ahí.
- srtm puede agrupar los predios sin valor por `llave` y mostrarlos aparte de la brecha.
- Una obra sin cuadro no se salta: deja al predio sin valor. Es más ruidoso, pero no esconde un error.
