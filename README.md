# catastro-backend

Valorización catastral de los predios de una municipalidad (hoy Perené, ubigeo 120302, en la selva; Ica, en la
costa), sobre el framework [wasichai](https://github.com/wasichai/wasichai) 1.6.0.

Valoriza cada predio del levantamiento catastral (autoavalúo por predio y año) con aranceles, valores unitarios y
depreciación, para que srtm-backend calcule la brecha de recaudación contra el padrón declarado. **No calcula
impuestos**: el impuesto predial es de srtm-backend.

## Documentación

- [Desarrollo local](docs/develop/README.md): requisitos, variables de entorno, base, tests, CI y cómo trabajar.
- [Releases](docs/develop/releasing.md): release-please, el jar y la versión del motor.
- [Decisiones (ADRs)](docs/adr/README.md): por qué el sistema es como es, normativa incluida.

## Requisitos

- JDK 25
- Docker (PostGIS para la base y para las pruebas de integración)
- Node 26 y yarn (solo para prettier y commitlint)

## Cómo correrlo

```sh
cp develop/example.env develop/.env && set -a && source develop/.env && set +a   # opcional: los valores por defecto
docker compose up -d      # postgis en 127.0.0.1:5434 (CATASTRO_PG_PORT)
# GeoServer (solo para publicar capas WMS): compose.geoserver.yml, ver docs/develop/README.md 3.1
./gradlew bootRun         # http://localhost:8091
```

Usuario de desarrollo: `admin@wasichai.local` / `admin` (solo con `WASICHAI_SEED_DEV=true`, el valor por defecto).
Una instalación real define `WASICHAI_JWT_SECRET` (>= 32 bytes), desactiva el seed y activa
`WASICHAI_JWT_REVOCATION` y `WASICHAI_LOGIN_LIMIT`.

## Pruebas

```sh
./gradlew build            # ktlint + pruebas unitarias
./gradlew integrationTest  # arranca la app contra un contenedor postgis (testcontainers)
yarn install && yarn format:check
```

## Modelo y carga

El modelo (`model/model.json`) y los cargadores son Python solo con la biblioteca estándar, con la forma de los de
srtm-backend (salvo `importar_corte_brecha.py`, que lee Parquet con duckdb). Once objetos: `predio_catastral` (llave `codigo_municipal`, igual a `predio.codigo` de srtm),
`construccion`, `obra_complementaria` y `titular_catastral` (cuelgan de un predio; este último, datos personales de
Ley 29733, ver [Modelo y carga](#modelo-y-carga)), `arancel`, `configuracion_catastro` (la región de la organización, ver
abajo) y `entrega_catastral` (cada entrega del levantamiento, ver [Entregas](#entregas)) y `tramo_via` (un frente del eje vial con el código SAT
de su arancel, ver «Vías» abajo), más los tres del dashboard de brechas: `corte_brecha`, `brecha_ficha` y
`decision_brecha` (ver [Corte de brecha](#corte-de-brecha)). wasichai
no tiene únicos compuestos, así que `arancel.clave` (`id_aranc|anio`) garantiza el par único. `codigo_vu` de una obra
es `TIPO DE OBRA|número`, como `obra_categoria` de srtm (`model/data/obras_complementarias.csv`).

```sh
cd model
python3 apply.py --validate-only          # valida el modelo, sin red
python3 apply.py --diff                   # lo pendiente contra el Core (http://localhost:8091), sin escribir
python3 apply.py                          # crea el modelo
python3 -m unittest -v                    # pruebas contra fake_core
```

Todos los cargadores aceptan `--core`, `--email`, `--password` (o `WASICHAI_CORE`, `WASICHAI_EMAIL`,
`WASICHAI_PASSWORD`) y `--dry-run`. Si algo no encaja en el modelo salen con código 2, listan cada fila mala y no envían
nada; un rechazo del Core sale con 1. Son idempotentes: correrlos dos veces no cambia nada.
Se corren con `python3 -I`, porque leen archivos de afuera: así ni el directorio actual ni `PYTHONPATH` entran al
`sys.path`, y cada comando vuelve a poner solo su propio directorio (`model/`), así que corre desde cualquier lado.

**Fichas** (`import_fichas.py`): `--fichas` (un predio por fila), `--pisos` (un piso por fila, ligado por
`codigo_municipal`), `--obras` y `--titulares` (opcionales, mismo vínculo), en csv o xlsx. Las columnas por defecto
salen del contrato de carga masiva del MEF (`cod_pre`, `cod_cpu`, `cod_sect`, `cod_mzn`, `cod_lote`, `id_aranc`,
`area_terreno`, `longitud_frente`...); `--map`, `--map-pisos`, `--map-obras` y `--map-titulares` `campo=columna` las
cambian. Un archivo con la columna `codigo_municipal` y sin `cod_pre` se lee como si trajera `cod_pre` (alias, que se
detecta por el encabezado, la primera fila: si vienen las dos gana `cod_pre`, y un `--map codigo_municipal=...`
explícito manda). Cinco columnas opcionales más, las cinco vacías
no se envían: `vinculo_metodo` (una opción del enum `vinculo_metodo`, sin distinguir mayúsculas: `CODIGO_RENTAS`,
`LLAVE_HU_MZ_LOTE`, `GEOMETRICO` o `MANUAL`) dice cómo se vinculó la ficha con su predio de rentas; `vinculo_revisado`
(`SI`/`NO`, igual que `techo_incluido`) si una persona ya revisó ese vínculo; `cuc` y `codigo_referencia_catastral`
son los códigos del Sistema Nacional Integrado de Catastro (Ley 28294), tal cual vienen; `tipo_predio` (una opción
del enum `tipo_predio`, sin distinguir mayúsculas: `URBANO` o `RUSTICO`) dice si el predio es urbano o rústico.
Mientras no haya tablas rústicas, un predio `RUSTICO` sale `SinValorizar` con motivo `PREDIO_RUSTICO` (ADR-004,
ADR-005). Las siete categorías van en una columna
`categorias` (`CCDCCDC`: muros y columnas, techos, pisos, puertas y ventanas, revestimientos, baños, instalaciones) o en
siete columnas con el nombre del campo. La columna opcional `techo_incluido` (`SI`/`NO`, `S`/`N`, `TRUE`/`FALSE`,
`1`/`0`, sin distinguir mayúsculas; vacía no se envía) marca los muros D de drywall que incluyen el techo (llamada 5 del
Anexo I.4, ver D4); un valor que no se lee es un error de validación (código 2). Dos columnas opcionales más, las dos
vacías no se envían:

- `clasificacion`: la tabla de depreciación del RNT de esa construcción. Va como una opción del enum `clasificacion`
  (las mismas cuatro de srtm, sin distinguir mayúsculas), o como el número de la tabla, `1` a `4` o `01` a `04`. Si
  viene, manda sobre la del uso del predio (D1). Así un padrón que clasifica cada nivel, como el de Ica (su
  `clasificacion_construccion` 1 a 4 es la tabla 01 a 04), pasa tal cual.
- `seccion`: un entero desde 1 (vacía vale 1), para las partes de un mismo piso con características distintas. El piso
  sigue siendo solo su número (`5`, no `5-2`), así que el +5 % de edificio alcanza a cada sección.

`--titulares` trae `tipo_documento`, `numero_documento` (tal cual viene), `nombre`, `porcentaje` y `condicion` de cada
titular de un predio (`titular_catastral`). **Son datos personales (Ley 29733): ningún reporte de carga imprime un
documento ni un nombre**, en ningún modo ni con `--dry-run`; solo `codigo_municipal` y el número de fila. Un documento
de relleno (`000000000`, solo ceros) se carga vacío y se reporta por fila:

```text
titulares <codigo> fila <n>: documento de relleno, queda vacío
```

La llave de un titular es (predio, `numero_documento` tal cual viene o vacío, `nombre` con los espacios colapsados y en
mayúsculas): dos homónimos sin documento colapsan en uno. Una llave repetida en el archivo se carga una sola vez y es
una advertencia, no un error (sale con 0):

```text
titulares <codigo> fila <n>: repetido, se carga una vez
```

Por cada predio, si al menos uno de sus titulares trae `porcentaje`, la suma de los porcentajes tal como vienen en el
archivo (antes de colapsar una llave repetida) se compara con 100 %; una diferencia de más de 0.01 se reporta (también
advertencia, también sale con 0; un predio cuyos titulares no traen `porcentaje` ninguno no se revisa):

```text
titulares <codigo>: suman <s> %
```

Sin `--entrega`, el comando solo crea. Un predio que el Core ya tiene se salta; los pisos (llave predio, piso y
sección; un piso sin sección, como los que se cargaron antes, es la sección 1), las obras (llave predio, `codigo_vu`
y año de construcción) y los titulares (su llave de arriba) se crean solo si faltan, así que una carga que falló a
medias se completa volviendo a correrla. Un piso o un titular que el Core ya tiene no se actualiza: para cambiarle
`techo_incluido`/`clasificacion` a un piso o `tipo_documento`/`porcentaje`/`condicion` a un titular hay que editarlo en
el Core o cargarlo como una entrega ([Entregas](#entregas)); volver a correr la carga sin `--entrega` no los toca. Una
llave repetida en el archivo es un error para pisos y obras (para titulares es la advertencia de arriba), y también un
`clasificacion` que no se lee: el `0` de Ica (sin tabla) va vacío. Un titular nunca se borra, con o sin `--entrega`.

```sh
python3 -I import_fichas.py --fichas fichas.csv --pisos pisos.csv --obras obras.csv --titulares titulares.csv --dry-run
```

**Aranceles** (`import_aranceles.py`): dos csv sacados de la geodatabase (solo lectura) y unidos por `ID_ARANC`.
`VAL_ACT` 0 se carga tal cual (el motor reporta un `motivo`); `VAL_ACT` vacío no tiene valor y se omite (el comando
dice cuántos). `--anio` filtra un año (por defecto todos). Los aranceles son de srtm, que escribe aquí la copia con
que se valúa ([ADR-012](docs/adr/0012-los-aranceles-son-de-srtm-y-catastro-guarda-la-copia.md)); este comando carga un
catastro desde la geodatabase mientras srtm no los tenga.

```sh
ogr2ogr -f CSV frentes.csv 120302_MD_Perene_ECF.gdb CF_ARANCEL_18 -select ID_ARANC,COD_VIA,CUADRA,LADO
ogr2ogr -f CSV valores.csv 120302_MD_Perene_ECF.gdb TB_VALORACION_HIST -select ID_ARANC,ANO_EJEC,VAL_ACT
python3 -I import_aranceles.py --frentes frentes.csv --valores valores.csv --anio 2026 --dry-run
```

**Lotes** (`import_lotes.py`): polígonos de un GeoJSON en EPSG:4326 hacia `predio_catastral.lote_geom`. Solo actualiza
los predios que ya existen (por `codigo_municipal`, y si el lote no lo trae, por `codigo_cpu`); `--map` indica la
propiedad. `CF_LOTES_POL_18` no trae esos códigos: hay que cruzarlos antes. Un predio sin polígono siempre lo recibe;
uno que ya tiene uno se deja igual, salvo que `--actualizar-geometria` pida reemplazar el que cambió de verdad: mismo
número de anillos, mismo número de vértices y ningún vértice a más de 1e-6 grados (~10 cm) del que ya está (el Core
guarda en EPSG:32718 y responde en EPSG:4326, así que la igualdad exacta nunca se da). Sin `--actualizar-geometria` ni
`--entrega`, la escritura es un PUT como hasta ahora; con cualquiera de las dos, cada polígono (nuevo o reemplazado) se
escribe por `PATCH` de `geometries` (y de `attributes.entrega` con `--entrega`), con el código de la entrega como
`X-Change-Reason` — mismas banderas `--entrega`/`--fecha-corte`/`--fuente` y mismas reglas que «Entregas» más abajo,
salvo que aquí no hay `--pisos`/`--obras`/`--descripcion`: el resumen que queda en `entrega_catastral` cuenta los
reemplazos como `cambios` y los predios sin novedad como `sin_cambio`; `ausentes` queda vacío (un lote sin predio es
«sin predio», no un ausente) y una corrida sin nada que escribir no crea la entrega.

```sh
ogr2ogr -f GeoJSON -t_srs EPSG:4326 lotes.geojson 120302_MD_Perene_ECF.gdb CF_LOTES_POL_18
python3 -I import_lotes.py --geojson lotes.geojson --map codigo_municipal=COD_PRE --dry-run
python3 -I import_lotes.py --geojson lotes.geojson --actualizar-geometria --entrega GIS-2026-10 \
  --fecha-corte 2026-10-01 --fuente GIS
```

**Vías** (`import_vias.py`): el eje vial de un GeoPackage hacia `tramo_via`, cada frente con el código SAT de su
arancel (`id_aranc`, el `codigo_de_via` completo del padrón, por ejemplo `0010000401-01`). Lee con `sqlite3`, sin GDAL,
`cf_eje_vial`, `cf_lotes_pol` y `padron_predial` de `--gpkg` (las tres en EPSG:32718; el encabezado del GeoPackage y el
WKB se leen a mano), y de la hoja `padron` de `--padron-xlsx` solo `codigo_predio`, `codigo_de_via`,
`nombre_de_la_via` y `tipo_predio` (se quedan los urbanos, `tipo_predio` 1). Los predios de cada lote salen de dos
fuentes que se suman: `cf_lotes_pol.cod_predio_padron` (uno o más `codigo_predio` del padrón separados por comas, así
que un lote puede tener varios predios) y `padron_predial.cod_predio` → `id_lote_p_vinculado` (vacío en el gpkg de
Ica). Las columnas se detectan con `pragma table_info`: puede faltar cualquiera de las dos fuentes (la columna, o la
tabla `padron_predial`); si faltan las dos, el archivo no encaja y sale con 2. El gpkg se abre con
`mode=ro&immutable=1`, así que SQLite no crea `-shm` ni `-wal` junto al archivo. Un eje de varias partes se orienta
primero: las partes se encadenan por sus extremos comunes y la que corre al revés se invierte (una parte suelta sigue
el sentido de la primera), así la izquierda y la derecha son la misma acera en todo el tramo, y esa geometría
orientada es la que va al Core, para que el `line-offset` del mapa coincida. El plano predial fija el valor por frente
de vía (notas 2 y 3), así que cada tramo se asigna así:

1. su nombre normalizado (sin tildes, PROLONGACIÓN como PROL. y AVENIDA/AVDA. como AV., sin el tipo inicial CA., AV.,
   JR., PJE., etc., con los espacios colapsados) es de un solo código urbano del padrón: `NOMBRE_UNICO`, una fila
   `AMBOS`, en todos los tramos de ese nombre. No importa cuántos `cod_via` del eje lo compartan: en Ica el
   `cod_via` es uno por tramo, no uno por calle;
2. si el nombre tiene varios códigos urbanos, los lotes de los predios de cada código (por cualquiera de las dos
   fuentes) se ubican a la izquierda o a la derecha del tramo (el signo del producto cruz con su segmento más
   cercano; un lote más allá de un extremo no cuenta). Cada lado toma el código con más lotes a `--distancia` metros o
   menos (30), y un empate lo decide el lote más cercano: `CERCANIA`. Así un solo predio mal vinculado no le gana a
   una cuadra entera. Si los dos lados dan el mismo código, o solo un lado tiene lotes, queda
   una fila `AMBOS`; si dan dos códigos, dos filas, `IZQUIERDO` y `DERECHO` (según el sentido de la línea);
3. después, sobre los tramos que el nombre dejó sin código, la pasada por lotes (`--sin-lotes` la apaga): un **código
   de urbanización**, un código urbano ninguno de cuyos nombres normalizados es el de un eje, toma los tramos donde
   están sus lotes. Cada centroide de lote de esos códigos vota por su tramo más cercano a `--distancia` metros o
   menos (uno solo), del lado que da el producto cruz; cada lado toma el código con más votos, el lote más cercano
   desempata, y las filas salen como en `CERCANIA` (un código, o un solo lado con votos, `AMBOS`; dos, `IZQUIERDO` y
   `DERECHO`): `LOTES`. Un tramo que el nombre asignó nunca se cambia. Los tramos se buscan en una grilla de los
   segmentos, no recorriendo todos los ejes por cada lote;
4. si nada se cumple (varios códigos y ningún lote cerca, un nombre sin código o un tramo «SIN NOMBRE»):
   `SIN_ARANCEL`, una fila `AMBOS` sin `id_aranc`.

**Alias de nombres de vía** (`--proponer-alias`, `--alias`). Muchos nombres del padrón (`nombre_de_la_via`) no
coinciden con ningún nombre del eje por una errata o por otra grafía, y su código queda sin tramo (el informe lo cuenta
en «nombres del padron sin eje»). El flujo es en tres pasos, con una persona en medio:

1. `python3 -I import_vias.py --gpkg ica.gpkg --padron-xlsx PADRON.xlsx --proponer-alias /ruta/fuera/del/repo/propuestas.csv`
   escribe, para cada nombre urbano del padrón sin eje, el nombre de eje más parecido (`difflib.get_close_matches`,
   umbral 0,6) y su `similitud`. Corre sin conexión: no usa el Core ni escribe nada. La ruta debe quedar fuera del
   repositorio, como `--revision`. Las columnas son `nombre_sat`, `nombre_eje_propuesto`, `similitud`, `aceptar`
   (vacía) y `nombre_eje` (vacía);
2. la municipalidad revisa el csv y marca `aceptar` con `si`, `sí`, `s`, `x`, `1` o `true` (sin distinguir mayúsculas)
   en los que son la misma calle. Si la propuesta no sirve pero conoce el nombre correcto, lo escribe en `nombre_eje`,
   que gana sobre `nombre_eje_propuesto`. Las filas sin marcar se ignoran;
3. `python3 -I import_vias.py ... --alias propuestas.csv` lee solo las filas aceptadas y, antes de asignar, cambia el
   nombre del padrón por el del eje (ambos con la misma normalización de siempre). Vale para `NOMBRE_UNICO` y
   `CERCANIA`, y un código cuyo nombre se cambió deja de ser un código de urbanización para la pasada por lotes. Sale
   con 2, listando todo, si un nombre de eje no está en el gpkg o si un mismo nombre del SAT tiene dos destinos
   distintos. El informe suma «alias aceptados», «alias aplicados» (los que cambiaron alguna fila del padrón) y
   «nombres del padron sin eje», contado ya con los alias.

**Los alias no se aplican solos** porque la coincidencia aproximada se equivoca: medida con los datos de Ica,
aceptar todas las propuestas sin revisarlas bajó los códigos con tramo de 267 a 197. Un nombre parecido suele ser otra
calle (JR. LIMA y JR. LIMAC), y asignarla le pone a un predio el arancel de otra vía. Ver
[wasichai/catastro-backend#47](https://github.com/wasichai/catastro-backend/issues/47).

Cada fila lleva también `valor_m2` y `anio_valor`: el `valor_m2` del arancel de su `id_aranc` del año en curso
(America/Lima), vacíos los dos sin arancel ese año o sin `id_aranc`. Es una **copia** para la vista de mapa
`aranceles_valor` y la capa WMS (ver [Vistas de mapa](#vistas-de-mapa)); el mapa de catastro-ui sigue leyendo el valor
de cualquier año de `GET /api/catastro/vias/aranceles`. Después de la carga la mantiene el servidor, con
**`CopiasDelMapa`** (`catastro.copias`), que también mantiene `brecha_ficha.estado` (ver «Corte de brecha»):

- es trabajo de fondo como lo soporta wasichai (ADR-039): escribe con `RecordService` **como la plataforma**
  (`asPlatform`, fuente de auditoría `copia:mapa`, razón «Copia para el mapa»), así que cada copia queda en la
  auditoría, mueve la versión del registro (ADR-051: un `If-Match` leído antes ya no vale) y la ven los listeners.
  Nadie necesita `UPDATE` sobre `tramo_via` ni `brecha_ficha`; `GET /api/catastro/cambios` no la lista, porque solo
  sigue predios, construcciones, obras y titulares;
- corre **cada `catastro.copias.periodo`** (`PT5M` por defecto) sobre todas las organizaciones, bajo un
  `ClusterLock` (una réplica a la vez): cura cualquier copia perdida y hace sola el **cambio de año** el 1 de enero
  (America/Lima) en la primera corrida del año;
- y **`catastro.copias.espera`** (`PT2S`) después de un aviso, solo sobre las organizaciones avisadas. Avisa
  `AvisosDeCopias`, un `RecordChangeListener` de wasichai (el hook de después de escribir) que solo encola: un
  arancel del año en curso (alta, cambio o baja, también la sincronización de srtm), un tramo nuevo o con otro
  `id_aranc`, una decisión, un corte que se muestra o se borra, una ficha nueva o con otro `estado`. No escribe, no
  espera y no lanza, así que nunca falla ni retrasa la escritura que lo dispara; corre el último;
- lee solo las filas cuya copia difiere (un `RecordCriterion`, la comparación la hace la base), así que una corrida sin
  nada que hacer cuesta unas pocas lecturas por organización;
- **cada registro va por su cuenta:** un parche que falla (un registro borrado mientras tanto, una regla que rompe) se
  registra en el log con el objeto, el id y el tipo de error, nunca los valores, se cuenta en `fallidas` y la corrida
  sigue con los demás (y con las fichas aunque fallen los tramos); la siguiente lo reintenta;
- el aviso espera a que pasen `espera` segundos **sin avisos nuevos** (hasta un `periodo`), así una ráfaga de escrituras
  es una sola corrida. Una escritura dentro de una transacción larga (un lote) puede leerse antes de su commit: entonces
  la copia llega en la corrida periódica, a lo sumo un `periodo` después. Si el lock lo tiene otra réplica, reintenta
  con espera creciente, hasta un `periodo`.

**La primera corrida** en una base existente escribe muchas copias de una vez, cada una con su fila de auditoría (el
estado anterior y el nuevo del registro): todas las fichas del corte más reciente ya cargadas, que aún no tienen
`estado` (en Ica, unas 21 300), y cada tramo con arancel del año (unos miles). Con 4 escrituras a la vez toma algunos
minutos, durante los que `POST /api/catastro/vias/valores` espera. Una carga nueva de un corte ya trae el `estado`. Cada
**1 de enero** cada tramo con valor se escribe dos veces: la primera corrida del año lo vacía (no hay aranceles del año
nuevo todavía) y la sincronización de srtm lo vuelve a llenar.

**`POST /api/catastro/vias/valores`** (solo el admin de la organización, 403 a cualquier otro rol) pide una corrida para
su organización y la espera: responde `{"anio", "tramos", "fichas", "fallidas"}`, lo que escribió y lo que no pudo. Lo
contesta una corrida que empieza después del pedido; si no llega en `catastro.copias.limite` (`PT10M`) responde 503, y
las copias corren igual más tarde. No lleva parámetros (siempre el
año en curso: un `anio`, o cualquier otro, es un 400 que lo nombra). Sirve para no esperar la corrida periódica.

**Paso anual (1 de enero).** No hace falta nada para las copias: la primera corrida periódica del año pone el valor
del año nuevo (vacío hasta que srtm sincronice sus aranceles, que entran por el aviso). Sí hay que volver a publicar
las capas, porque el SLD guarda las clases de su publicación:

```sh
curl -X POST "localhost:8091/api/catastro/vias/valores" -H "Authorization: Bearer $TOKEN"   # opcional: la corrida ya
python3 -I vistas_de_mapa.py --org <id>    # republica las capas con las clases del año nuevo
```

Una escritura de un tramo responde con lo que se mandó: si mandó un `valor_m2` distinto, la copia lo corrige segundos
después. Son campos del servidor: el cargador los manda solo para que la primera carga ya los traiga.

**Por qué `LOTES`.** En Ica muchos `codigo_de_via` del SAT tienen por «nombre de la vía» el de una urbanización («SOL
DE ICA XXII ETAPA»): el SAT le da un código a las vías internas de una habilitación, y en el eje esas calles se llaman
«1», «B» o «SIN NOMBRE 021». Por el nombre nunca se encuentran, pero sus lotes sí están sobre esas calles. **`LOTES` es
menos confiable** que las otras dos: depende del vínculo lote → predio y de la cercanía, y un lote de esquina puede
votar por la calle de al lado. Sus tramos se revisan en el mapa (el reporte cuenta los lados que decidió un solo lote).

**Por qué una línea con lado.** El arancel urbano se fija por frente de vía (cuadra y lado), no por sector: así lo
aprueba la RM 514-2025-EF/15 en el plano predial, cuyas notas 2 y 3 dicen que el valor al centro de la calle rige
para los dos frentes y el que está dentro de la manzana solo para ese frente. Por eso la geometría de `tramo_via` es
una línea con su lado, y el código SAT del padrón (`0010000401-01`, `-02`) es uno por frente.

**Regla para varios códigos de vía.** Una ficha vinculada a varios `codigo_de_via` (uno por frente; la entrega que
reapunta el `id_aranc` de las fichas la aplica):

- si todos esos códigos tienen el mismo valor de arancel en el año, toma el código más frecuente;
- si sus valores difieren, la ficha queda sin cambio y se reporta para revisión.

`cuadra` queda vacía: el eje no la trae. La geometría va al Core en GeoJSON EPSG:4326, como `MultiLineString`
(wasichai-gis la guarda en la 32718 de la columna); la conversión desde UTM 18S es la serie de Krüger en Python, sin
proj. El comando es idempotente por `tramo_via.clave` = `<ubigeo>|<fid>|<lado>`: crea lo que falta, actualiza
(`PATCH`) lo que cambió (atributos, o un vértice a más de 1e-6 grados) y borra la fila de un eje cuyo lado ya no sale
(un `AMBOS` que ahora es `IZQUIERDO` y `DERECHO`, o al revés). Las filas de un ubigeo del archivo cuyo fid el archivo
ya no trae solo se cuentan; `--borrar-ausentes` las borra (el `--dry-run` dice cuántas). **Un eje reexportado o
editado (sus fid cambian) se carga con `--borrar-ausentes`**, primero en dry-run; si no, sus tramos viejos siguen en el
mapa. Las filas de otro ubigeo nunca se tocan. Solo imprime conteos: lotes vinculados a predios (en total y por
cada fuente, o «sin la columna»), tramos por asignación, ejes partidos por lado, ejes multiparte, partes invertidas,
lados decididos por un solo lote, códigos de urbanización, códigos asignados por `LOTES`, lados decididos por un
solo lote en `LOTES`, códigos sin tramo, sin lotes y con lotes lejanos, y nombres del padrón sin eje (un
nombre urbano que ningún tramo tiene: mide la cobertura del eje, o un nombre escrito de otra forma).
`--revision` escribe un csv con `cod_via_eje`, `fid_eje`, `lado`, `id_aranc` y `asignacion`, sin datos personales, y
se niega a escribirlo dentro del repositorio. `--org` espera el **id** (UUID) de la organización, no su slug: se niega
a escribir si la cuenta de `--email` es de otra, y el error dice el id de la organización de la cuenta. `--dry-run` lee el Core y dice cuánto crearía, actualizaría y borraría, sin escribir nada.

```sh
python3 -I import_vias.py --gpkg ica.gpkg --padron-xlsx PADRON_CONSTRUCCION.xlsx --revision /tmp/revision-vias.csv \
  --org <id de la organización> --dry-run
```

**Orden para poner las vías en un despliegue** (cada paso primero en dry-run, con el OK de quien opera la base):

1. `python3 apply.py --diff`, luego `python3 apply.py`: crea `tramo_via` (sin él, `import_vias.py` sale con 1 por el
   404 y el endpoint responde 404);
2. `python3 apply_roles.py --dry-run`, luego `python3 apply_roles.py`: el `READ` de `SRTM_LECTOR` sobre `tramo_via`
   (antes de `apply.py` nombraría un objeto que no existe);
3. el jar con `GET /api/catastro/vias/aranceles`;
4. `import_vias.py --dry-run`, luego sin `--dry-run`;
5. recién entonces catastro-ui con la página «Aranceles por vía» (antes del jar, la página da 404).

### Entregas

El levantamiento no se carga una vez: llega por **entregas** (un barrido de campo, una inspección de fiscalización, las
licencias del mes, el GIS de la municipalidad), y cada una corrige o completa lo que ya está
([ADR-013](docs/adr/0013-el-levantamiento-llega-por-entregas.md)). `import_fichas.py --entrega <codigo>` carga una
entrega por upsert: compara los archivos con el Core por `codigo_municipal` y escribe solo lo que cambió, siempre por la
API y con el código de la entrega como `X-Change-Reason`. Así el `audit_log` de wasichai guarda la historia de cada
ficha: qué entrega cambió qué campo y cuándo.

- `--entrega CODIGO`: de 1 a 64 caracteres entre `A-Z a-z 0-9 . _ : -` (viaja en una cabecera HTTP; un código con
  tildes o espacios sale con 2).
- `--fecha-corte AAAA-MM-DD` (obligatoria): la fecha a la que corresponde la información.
- `--fuente` (obligatoria): `BARRIDO`, `INSPECCION`, `LICENCIA`, `GIS` u `OTRA` (enum `fuente_entrega`).
- `--descripcion TEXTO` (opcional).
- `--pisos`, `--obras` y `--titulares` son opcionales: una entrega del GIS o una inspección puede traer solo fichas, y
  entonces los pisos, las obras y los titulares no se comparan.
- `--reemplazar-pisos` / `--reemplazar-obras`: borran los pisos (u obras) que el Core tiene y el archivo ya no trae,
  **solo en las fichas que la entrega trae**. Sin la bandera, se listan como ausentes y se quedan. Piden `--entrega` y
  su archivo (`--pisos` / `--obras`); si no, sale con 2. Una ficha que viene sin filas de pisos pierde todos sus pisos
  con `--reemplazar-pisos`: una demolición se carga con la bandera a propósito. Una obra con el año corregido tiene otra
  llave: sin `--reemplazar-obras` quedaría la vieja y se valoraría dos veces. No hay `--reemplazar-titulares`: un
  titular **nunca se borra**, con o sin `--entrega`.

Qué se compara:

- Las fichas por `codigo_municipal`, los pisos por (predio, piso, sección), las obras por (predio, `codigo_vu`, año de
  construcción) y los titulares por (predio, `numero_documento` o vacío, `nombre` colapsado y en mayúsculas). Una
  ficha nueva es un alta, con sus pisos, obras y titulares.
- Solo las columnas que el archivo trae: una columna que falta no se toca, y una celda vacía en una columna presente
  borra el campo. La entrega es la verdad de lo que trae (así una entrega quita las estimaciones que hubiera, ADR-013); el
  `--dry-run` lo muestra antes. La columna única `categorias` cuenta como las siete letras.
- Los valores, por su tipo del modelo: el Core responde `180.5` donde el archivo dice `180.50`, y es lo mismo.
- **Ausente** es una ficha que el Core tiene y la entrega no: se lista y **nunca se borra**. Borrarla es una decisión a
  mano; una entrega parcial (un sector, una inspección) no puede vaciar el catastro. Un titular que el Core tiene y el
  archivo ya no trae se queda y **no se lista** (sería imprimir su llave, dato personal, Ley 29733).

El reporte sale igual en el `--dry-run` y en la carga, una línea por hecho, en este orden (cada ficha seguida de las
líneas de sus pisos, obras y titulares, luego las ausentes y al final el resumen); `vacío` es un campo sin valor. Las
líneas de un titular **nunca llevan un documento o un nombre**, solo el número de fila y, al cambiar, el nombre del
campo (Ley 29733 y Review Focus de c3):

```text
alta <cod>
cambio <cod>: <campo> <antes> → <después>
cambio <cod> piso <p>/<s>: <campo> <antes> → <después>
cambio <cod> piso <p>/<s>: alta
cambio <cod> piso <p>/<s>: baja                         (solo con --reemplazar-pisos)
cambio <cod> obra <codigo_vu>/<año>: …                  (igual que los pisos: campo, alta o baja)
cambio <cod> titular fila <n>: alta
cambio <cod> titular fila <n>: <campos separados por coma>   (tipo_documento, porcentaje o condicion; nunca el valor)
sin cambio <cod>
ausente <cod> piso <p>/<s>                              (sin --reemplazar-pisos)
ausente <cod> obra <codigo_vu>/<año>                    (sin --reemplazar-obras)
ausente <cod>
entrega <codigo>: <a> altas, <c> cambios, <s> sin cambio, <z> ausentes
```

La carga termina con `done: entrega <codigo>: …`, el mismo resumen. Una ficha cuenta como cambio cuando cambió ella o
alguno de sus pisos, obras o titulares.

La entrega queda en `entrega_catastral`: código, fecha de corte, fuente, descripción, el sha256 de los bytes de los
archivos de entrada (fichas, pisos, obras y titulares, en ese orden) y el resumen. La crea la primera corrida que
escribe algo, con su resumen, y **no se actualiza nunca**. De ahí la regla de idempotencia:

- Cargar dos veces la misma entrega no cambia nada: la segunda corrida no encuentra nada que escribir y no escribe nada.
- Una carga que falló a medias (un rechazo del Core sale con 1) se completa volviendo a correrla con los mismos archivos:
  crea lo que falta, sin duplicar, y el resumen de la entrega queda como lo dejó la primera corrida.
- El mismo código con otros archivos (otro sha256, aunque sea un piso corregido) sale con 2 sin escribir: una entrega
  nueva lleva su propio código.
- Una corrida sin nada que escribir no crea la entrega.

Cada predio apunta (`entrega`) a la última entrega que lo cambió a él o a sus pisos u obras; una ficha sin cambio
conserva la que tenía. Con `--entrega`, el `--dry-run` necesita credenciales: entra al Core y solo lee (GET) para
reportar.

```sh
python3 -I import_fichas.py --fichas fichas.csv --pisos pisos.csv --obras obras.csv \
  --entrega BARRIDO-2026-10 --fecha-corte 2026-10-01 --fuente BARRIDO --descripcion "Barrido del sector 01" --dry-run
# revisado el reporte, la misma línea sin --dry-run
```

### Ica: el libro de comparación

Ica entregó su catastro como un **libro de comparación** (xlsx, versión 3): predio, construcción y titulares, cada uno
del lado de rentas y del lado de catastro, más un gpkg con los lotes. `convertir_comparacion_ica.py` lo convierte en los
tres archivos de una entrega (`fichas.csv`, `pisos.csv` y `titulares.csv`) para `import_fichas.py --entrega`. Solo lee
las hojas de catastro (`predio_catastro`, `construccion_catastro` y `titulares_catastro`): el lado de rentas es el
padrón de srtm, no el catastro. Las reglas son las de wasichai/catastro-backend#10:

- **Fichas.** Un predio sin `codigo_unidad_catastro` o sin `cod_predio_rentas` no se carga. Si `cod_predio_rentas` se
  repite, queda la primera ficha que se puede cargar. Sector, manzana y lote son las partes 4.ª, 5.ª y 6.ª de la unidad
  catastral partida en `-`, que también va tal cual a `codigo_referencia_catastral`; `cuc` sale de `cuc_catastro`. Un
  área de 0 o menos queda vacía, nunca con el área de rentas.
- **Estado del levantamiento.** `SIN_LEVANTAR` si el área queda vacía y el predio no tiene construcción, ni titular,
  ni urbanización (las fichas vacías del libro); `PARCIAL` si el área queda vacía pero tiene alguna de esas tres;
  `COMPLETO` si tiene área. `fecha_levantamiento` queda vacía: el libro no la trae.
- **Uso y arancel.** `uso` e `id_aranc` van como columnas presentes y vacías, así el upsert borra las estimaciones que
  hubiera ([Entregas](#entregas), ADR-013). El arancel es el de srtm (ADR-012) y una ficha sin uso queda sin uso: el
  motor da el motivo.
- **Pisos.** El primer número del nivel es el piso; un nivel sin número y los `NIVEL 71`/`81` no se cargan. Un nivel
  repetido en un predio se carga como secciones 1, 2… en el orden de la hoja, y una construcción compartida va a cada
  predio. Quedan vacíos los años fuera de 1900–2026 (`--anio-maximo` mueve el último), el área de 0 o menos, las
  letras fuera de A–J y un material o estado que no se lee; material `1`/`2`/`3` es `CONCRETO`/`LADRILLO`/`ADOBE` y
  estado `1` a `4` es `MUY BUENO`/`BUENO`/`REGULAR`/`MALO` (una opción del modelo también pasa).
- **Titulares.** Solo los de una ficha que se carga, con cada valor tal cual viene: el documento de relleno
  (`000000000`) lo vacía `import_fichas.py`, que lo reporta por fila.
- **Vínculo con rentas.** Sale del gpkg de lotes, exportado a csv con una fila por lote: `cod_predio_rentas` y
  `vinculo_metodo` (código de rentas en el lote, llave HU-Mz-Lote-vía o geometría). Con `--vinculos`, **un predio sin
  fila de vínculo no se carga**. El método se lee contra el enum `vinculo_metodo` sin distinguir mayúsculas
  (`CODIGO_RENTAS`, `LLAVE_HU_MZ_LOTE`, `GEOMETRICO`, `MANUAL`), o con `--metodo TEXTO=ENUM` (repetible) para el texto
  que use el gpkg; un texto que no se lee sale con 2 y lo nombra. Un método vacío vincula el predio con
  `vinculo_metodo` vacío. Sin `--vinculos` se cargan todas las fichas, y `fichas.csv` no lleva la columna
  `vinculo_metodo`: el convertidor nunca escribe vacía una columna que no leyó, así la entrega no borra el vínculo
  que ya tuviera el predio (regla R11).

Las columnas por defecto son las del libro; `--map-predio`, `--map-construccion`, `--map-titulares` y `--map-vinculos`
`campo=columna` las cambian; las de titulares son las del libro v3 (`nro_documento_catastro` y `porcentaje`). Todas son
obligatorias salvo `cuc_catastro`, `urbanizacion_catastro` y `condicion_catastro`: una hoja o una columna que falta sale
con 2 y la nombra, sin escribir nada. Sin `cuc_catastro`, `fichas.csv` no lleva la columna `cuc`, y la entrega no toca
el que hubiera. El libro v3 no trae la condición del titular (su `estado` es el de la comparación y nunca se lee
como condición): sin `condicion_catastro`, la `condicion` de `titulares.csv` queda vacía, el conteo
`titulares_sin_condicion` lo dice y stderr nombra la columna que falta, sin ningún dato del titular.

**La salida va fuera del repositorio.** Los titulares son datos personales (Ley 29733): `--salida` dentro del
repositorio (también por un enlace) sale con 2, y el comando solo imprime conteos, líneas `<clave>: <n>` con lo que
sale y con cada regla que descarta o vacía algo, nunca un nombre o un documento.

```sh
ogr2ogr -f CSV vinculos.csv <lotes>.gpkg <capa> -select cod_predio_rentas,vinculo_metodo
python3 -I convertir_comparacion_ica.py --libro comparacion_v3.xlsx --vinculos vinculos.csv --salida ~/ica/entrega
python3 -I import_fichas.py --fichas ~/ica/entrega/fichas.csv --pisos ~/ica/entrega/pisos.csv \
  --titulares ~/ica/entrega/titulares.csv --entrega ICA-2026-10 --fecha-corte 2026-10-24 --fuente BARRIDO --dry-run
# revisado el reporte, la misma línea sin --dry-run
```

Volver a cargar el VPS de pruebas de Ica con esta salida es una operación a mano, fuera de este repositorio.

### Aranceles de las fichas

El arancel de una ficha (`predio_catastral.id_aranc`) debe ser uno **vigente**: una clave `<id_aranc>|<año>` que existe
en `arancel` para el año, porque catastro guarda solo la copia de los aranceles vigentes de srtm (ADR-012).
`aranceles_no_vigentes.py --anio <año>` lee las fichas y los aranceles del Core y lista las que no lo cumplen, sin
escribir nada. Con `--padron` lee además el código de vía del padrón del SAT (xlsx o csv; hoja `PREDIO URBANO`,
columnas `Código Predio` y `Codigo de via`; `--hoja`, `--columna-codigo` y `--columna-via` las cambian). Los códigos
se leen sin espacios, una celda vacía no cuenta, y una ficha tiene los códigos de todas las filas del padrón con su
código, con su frecuencia.

Los motivos (una ficha puede tener varios, y cada uno cuenta):

- `id_aranc_vacio`: la ficha no tiene `id_aranc`;
- `clave_inexistente`: no hay arancel con ese `id_aranc` para el año;
- `clave_provisional`: el `id_aranc` no tiene el formato de código de vía (`^\d{10}-\d{2}$`), p. ej. `R<valor>`;
- `varios_codigos_alguno_no_vigente` (con `--padron`): dos o más códigos, y alguno sin arancel vigente (también
  cuando los códigos vigentes tienen valores distintos entre sí: cuenta aquí, no en el motivo siguiente);
- `varios_codigos_valores_distintos` (con `--padron`): dos o más códigos, todos vigentes, con `valor_m2` distintos;
- `codigo_sin_arancel_vigente` (con `--padron`): ninguno de sus códigos tiene arancel vigente.

Con `--padron` también cuenta `sin_padron` (fichas sin fila en el padrón) y lo que haría la corrección: `corregibles`,
`ya_apunta` y `sin_levantar_no_se_corrige`. Cada motivo y `sin_padron` salen con su parte por estado, p. ej.
`codigo_sin_arancel_vigente: 8488 (levantadas 5273, sin levantar 3215)`: las levantadas son las `COMPLETO` y
`PARCIAL` (y las sin estado), las otras las `SIN_LEVANTAR`, que la corrección no toca. `--reporte reporte.csv` escribe
una fila por ficha y motivo (`codigo_municipal,id_aranc,estado_levantamiento,motivo,codigos_padron`, los códigos
separados por `;`). El padrón trae datos personales (Ley 29733): de él solo salen el código del predio y los códigos de
vía.

**Corrección.** Con `--entrega <codigo> --fecha-corte AAAA-MM-DD` (y `--padron`), una ficha cuyos códigos tienen
**todos** arancel vigente y del **mismo** valor pasa a apuntar al código más frecuente (en un empate, el menor); si
algún código no tiene arancel vigente o los valores difieren, no se toca y queda en el reporte. No se estima nada. Se
dejan las fichas que ya apuntan a ese código y las `SIN_LEVANTAR`. El script escribe `cod_pre,id_aranc` (en `--csv`, o
en una carpeta temporal nueva) y lo carga con `import_fichas.py --entrega <codigo> --fuente OTRA` (más `--descripcion`
y `--dry-run` si se dan): la entrega compara solo las columnas que trae el archivo, así que solo cambia `id_aranc`
([Entregas](#entregas)). Sin nada que corregir, no llama a `import_fichas.py`.

Es repetible: se corre de nuevo cada vez que normativa publica aranceles nuevos (por ejemplo, al llegar el padrón
completo con todas las vías), con un código de entrega nuevo. Lo ya corregido no vuelve a salir.

```sh
python3 -I aranceles_no_vigentes.py --anio 2026 --padron padron_sat.xlsx --reporte ~/ica/aranceles.csv
python3 -I aranceles_no_vigentes.py --anio 2026 --padron padron_sat.xlsx \
  --entrega ICA-ARANCEL-VIA-2026-11 --fecha-corte 2026-11-01 --dry-run
# revisado el reporte, la misma línea sin --dry-run
```

### Corte de brecha

El dashboard de brechas de catastro-ui lee la brecha de recaudación de srtm desde el **corte analítico**
(srtm-backend `docs/informes/brecha`, `make corte`), no en vivo: una carpeta `<org>/<fecha>/` con `manifiesto.json` y
un Parquet por tabla, publicada en S3. `importar_corte_brecha.py` la carga en tres objetos:

- `corte_brecha`, uno por corte (`clave` `<org>|<fecha>`): la corrida de srtm, el sha256 del manifiesto, las versiones
  y los totales de la corrida (Δ impuesto, el confiable, el dudoso y el sin levantar, y el de los omisos estimado);
- `brecha_ficha`, una por fila de `srtm_brecha_predio` (`clave` `<id del corte>|<codigo_catastro>`, o
  `<id del corte>|id:<id de la fila en srtm>` si la fila no tiene `codigo_catastro` o lo comparte con otra), con
  `codigo_municipal` de la ficha que empata y `supera_5_uit`;
- `decision_brecha`, la bandeja (`clave` `<codigo_municipal>|<anio>`): no la toca la carga, la escribe la API, y así
  una decisión sobrevive a los cortes nuevos. Es `apiOnly` (ADR-040, `apply.py` lo sincroniza como `appendOnly`): la
  API genérica de registros no la escribe y wasichai-ui la muestra de solo lectura.

Antes de leer nada verifica el corte como `manifiesto.verificar_corte` de srtm: `formato` 1, cada archivo del
manifiesto con sus bytes, su sha256 y su número de filas, y ningún archivo que el manifiesto no liste. Un archivo que
falta, sobra o no coincide, o un manifiesto sin `srtm_brecha_corrida.parquet` y `srtm_brecha_predio.parquet`, sale
con 2 sin llamar al Core. Lee con
**duckdb** (`requirements-corte.txt`, la misma versión que el venv del corte: `python3 -m pip install -r
model/requirements-corte.txt`) la corrida del manifiesto y sus filas, y la UIT del año de `srtm_parametro` (tipo `UIT`,
vigente al 1 de enero); si el corte no la trae, `--uit`, y sin ninguna `supera_5_uit` queda vacío. `supera_5_uit` es
|Δ autoavalúo| > 5 UIT.

Cada fila empata con su ficha por la llave de `Brecha.llave()` de srtm: sin espacios, en mayúsculas y cada grupo de
dígitos sin ceros a la izquierda (`01-01-0006` es `1-1-6`). `codigo_catastro` es el código del ítem de catastro como lo
muestra srtm (su código municipal, si no su CPU, si no sector-manzana-lote), así que se busca primero entre los
`codigo_municipal` de las fichas, luego entre sus `codigo_cpu` y al final entre su sector-manzana-lote. Cada llave se
arma sobre **todas** las fichas: una llave que comparten dos fichas, o que tiene una ficha sin `codigo_municipal`
(srtm escribe la CPU o el S-M-L solo para un ítem sin código, así que la fila es de esa ficha), no empata con ninguna.

**Copias para el mapa** (ver [Vistas de mapa](#vistas-de-mapa)). Cada ficha lleva `estado`, el de su
`decision_brecha` del año del corte (`PENDIENTE` sin decisión), y, si el corte es el más reciente de la organización
(por `fecha` y luego `clave`, el orden de la API), `lote_geom`, el lote de su `predio_catastral` empatado (POLYGON, en
el srid de `predio_catastral.lote_geom`). Después **quita `lote_geom` de las fichas de los demás cortes**
(`--sin-geometria-anterior`, el comportamiento por defecto; `--con-geometria-anterior` las deja), así la vista de mapa y
la capa WMS de `brecha_ficha` muestran solo el último corte; las fichas con lote se buscan con un `bbox` alrededor de
los lotes (wasichai-gis), no leyendo toda la historia. Un corte cargado después de otro más reciente no lleva lotes (y
pierde los suyos, salvo con `--con-geometria-anterior`, que los deja como están). Un corte más nuevo que quedó a medio
cargar (sin `cargado_en`) no cuenta: la API tampoco lo muestra. Un `codigo_municipal` de dos o más predios no toma
lote (cuál sería arbitrario) y el resumen los cuenta. **Si se borra el corte más reciente**, el mapa queda sin lotes
hasta que se vuelve a cargar el anterior (`importar_corte_brecha.py` con su carpeta), que pasa a ser el más reciente.
El `estado` lo mantiene después `CopiasDelMapa` (ver «Vías»): una decisión tomada mientras corría la carga se corrige
sola. Un lote que vuelve del Core dentro de 1e-6 grados es el mismo y no se reescribe. El resumen dice cuántas fichas
llevan lote y cuántas de cortes anteriores lo perdieron. Ninguna de estas escrituras sale en
`GET /api/catastro/cambios`, que solo lista predios, construcciones, obras y titulares.

Es idempotente por `clave`: crea lo que falta, actualiza (`PATCH`) lo que cambió y un corte igual no escribe nada, ni
`cargado_en`. **`cargado_en` se escribe al final**, después de todas las fichas, y la API solo muestra los cortes que lo
tienen: un corte nunca se ve a medio cargar. Una recarga lo borra primero, y una carga que falla a la mitad deja el
corte oculto; la siguiente corrida la termina. Si el corte guardado tiene fichas que el corte ya no trae, la carga
sale con 2 sin escribir nada; `--reemplazar` las borra (nunca toca las de otro corte). Un rechazo del Core imprime
solo el estado y los campos que nombra. Cada escritura
lleva `X-Change-Reason` `corte-brecha:<org>:<fecha>`. Solo imprime conteos: filas, por categoría, empatadas con ficha,
sin ficha (con y sin código), llaves repetidas y cuántas superan 5 UIT; nunca un código ni un monto. `--org` espera el
id de la organización, como `import_vias.py`. `--s3` baja el corte con `aws s3 cp --recursive` a una carpeta temporal
que se borra al final.

```sh
python3 -I importar_corte_brecha.py --corte ~/cortes/analitica/ica/2026-10-25 --org <id de la organización> --dry-run
python3 -I importar_corte_brecha.py --s3 s3://<bucket>/analitica/ica/2026-10-25 --org <id> [--uit 5500] [--reemplazar] \
  [--workers 4]
```

**Orden** (cada paso primero en dry-run, con el OK de quien opera la base):

1. `python3 apply.py --diff`, luego `python3 apply.py`: crea los tres objetos y la relación `brecha_ficha_corte`;
2. `python3 apply_roles.py --dry-run`, luego `python3 apply_roles.py`: el `READ` de `CATASTRO_LECTOR` sobre los
   tres, el rol nuevo `CATASTRO_ANALISTA` (además `CREATE` y `UPDATE` sobre `decision_brecha`) y el `READ` de
   `SRTM_LECTOR` sobre `decision_brecha`;
3. en srtm-backend, `make corte ORG=<org>` (escribe y publica el corte);
4. `importar_corte_brecha.py --dry-run`, revisado el resumen, la misma línea sin `--dry-run`. Puede ir en el cron
   mensual, después de `make corte`;
5. `vistas_de_mapa.py --dry-run`, luego `vistas_de_mapa.py`: vuelve a publicar las capas con las clases de los datos
   nuevos (el resumen de la carga lo recuerda).

### Vistas de mapa

`vistas_de_mapa.py` crea o actualiza las **vistas de mapa** guardadas de wasichai-gis (`/api/gis/objects/{objeto}/
map-views`, ADR-072 de wasichai) y publica las dos **capas WMS** con el estilo de su vista (un SLD,
`POST /api/gis/layers/{objeto}/{geometría}` con `{"style"}`). Pide `MANAGE_METADATA` (el admin). Una vista que falta
se crea, una cuya etiqueta, geometría o estilo difieren se actualiza (`PUT`), una igual no se toca.

| Vista | Objeto y geometría | Estilo |
|---|---|---|
| `aranceles_valor` | `tramo_via.geom` | `valor_m2`, 5 cuantiles, la `PALETA` de catastro-ui |
| `aranceles_asignacion` | `tramo_via.geom` | `asignacion`, categorías |
| `brechas_categoria` | `brecha_ficha.lote_geom` | `categoria`, categorías con `COLOR_CATEGORIA` de catastro-ui |
| `brechas_estado` | `brecha_ficha.lote_geom` | `estado`, categorías con `COLOR_ESTADO` de catastro-ui |

No hay vista del Δ impuesto: es un valor con signo, los cuantiles de wasichai-gis no centran una escala en 0, y
catastro-ui conserva su propia escala divergente. Una `brechas_delta` de una versión anterior se borra.

Capas: `tramo_via.geom` con el estilo de `aranceles_valor` y `brecha_ficha.lote_geom` con el de `brechas_categoria`.

**El SLD guarda las clases de su publicación** (los cortes de los cuantiles se calculan al publicar, sobre todas las
filas de la organización). Por eso cada corrida vuelve a publicar las dos capas aunque nada más cambie (en wasichai
1.5.0 republicar es lo que reemplaza el estilo), y **se corre de nuevo cada vez que cambian los datos**:

1. después de cada `importar_corte_brecha.py`;
2. después del cambio de año (la primera corrida de `CopiasDelMapa` del 1 de enero) o de un `import_vias.py`.

**Una capa publicada antes de tener el campo de su estilo.** Republicar en wasichai 1.5.0 solo cambia el SLD: las
columnas de la capa en GeoServer son las de su primera publicación. Por eso, si `GET /api/gis/layers` dice que una capa
está publicada, el script lee su `DescribeFeatureType` del WFS, y si le falta el campo del estilo la retira
(`DELETE /api/gis/layers/...`) y la vuelve a publicar, lo que la rehace. `--recrear-capas` lo hace con las dos sin
mirar el WFS (cuando no se alcanza desde donde corre el script, avisa y sugiere ese flag).

**Paso único de esta versión.** `tramo_via.geom` ya estaba publicada en dev y en los VPS, sin `valor_m2`:

```sh
python3 -I apply.py && python3 -I vistas_de_mapa.py --org <id> --recrear-capas
```

```sh
python3 -I vistas_de_mapa.py --org <id de la organización> --dry-run
python3 -I vistas_de_mapa.py --org <id de la organización> [--sin-capas]   # --sin-capas: solo las vistas, sin GeoServer
```

Sale con 0, con 1 si el Core rechaza algo (GeoServer caído, por ejemplo) y con 2 si `--org` es otra organización.

### WMS protegido

GeoServer sirve el WMS sin autenticación y no sabe de organizaciones: entrega cualquier capa que se le pida. Por eso
**GeoServer nunca se expone** (sin puerto en el host, ni en `0.0.0.0` ni en `127.0.0.1` de un servidor): el navegador lo
alcanza solo por el nginx de catastro-ui, y ese nginx autoriza cada pedido con catastro-backend antes de pasarlo
(`auth_request`). La plantilla del nginx está en [docs/deploy/nginx-catastro-ui.conf](docs/deploy/nginx-catastro-ui.conf)
y es la única fuente: el README de catastro-ui apunta aquí.

Las url WMS que la API entrega al navegador (`/api/gis/services`, `/api/gis/layers`) salen de
`WASICHAI_GIS_GEOSERVER_PUBLIC_URL` (wasichai 1.6.0). En un despliegue va `/geoserver`, relativa: las teselas se
piden al origen de catastro-ui y pasan por este proxy. Sin ella serían la url interna de GeoServer, que el navegador
no alcanza. catastro-ui pone el token de la sesión en esas teselas (`gisModule({ wmsAuth: true })` para las páginas de
gis y `transformRequest` para sus mapas propios).

`GET /api/catastro/wms/autorizar` es el endpoint del `auth_request`. Lee el Bearer del navegador como cualquier otro
endpoint y la uri original del pedido en `X-Original-URI` (`$request_uri`). Deja pasar **solo lo que piden los mapas de
catastro-ui**, un `GetMap` ráster:

- la ruta es exactamente `/geoserver/catastro/wms` (el workspace de `WASICHAI_GEOSERVER_WORKSPACE`), con un único
  `service=WMS` y un único `request=GetMap`;
- `format` es uno solo de `image/png`, `image/png8`, `image/jpeg` o `image/webp`; `width` y `height` van de 1 a 2048;
  de `format_options` solo pasan `dpi` y `antialias`;
- nombra de 1 a 10 capas en `layers` (o `typeName`, `typeNames`), listas con comas, sin distinguir mayúsculas en el
  nombre del parámetro (`LAYERS`, `Layers`...); un parámetro repetido cuenta entero. Un estilo (`styles`) va vacío o es
  el de una de sus capas;
- cada capa es de la organización: su nombre, `<objeto>__<prefijo>__<geometría>` (con o sin `catastro:`), lleva como
  prefijo los 8 primeros dígitos hex del `organizationId` del usuario, y `<objeto>` es un objeto de esa organización con
  esa geometría;
- el usuario tiene READ sobre el objeto de cada capa **y lo lee entero**. Una tesela dibuja todas las filas de la capa y
  las colorea por un atributo, así que no puede respetar una regla que esconde filas o campos. Por eso un usuario con
  alguna de estas reglas no recibe teselas (403): un filtro de dueño (`ownRecordsOnly`), un alcance de lectura de la app
  (ADR-048 de wasichai), un campo del objeto que no puede leer, o una máscara de lectura (ADR-065). Ese usuario ve los
  lotes y los tramos por la API, en GeoJSON, que sí aplica sus reglas.

Responde **204** si todo eso se cumple, **401** sin token o con uno malo (lo responde core) y **403** en todo lo demás.
nginx convierte cualquier otro código en un 500, así que el endpoint solo responde esos tres. Todo lo que no está en la
lista es un 403:

- `GetCapabilities`: lista los nombres de las capas de todas las organizaciones del workspace, y con ellos los prefijos
  de sus `organizationId`;
- `GetFeatureInfo`, `GetLegendGraphic` y los formatos vectoriales o de texto (KML, UTFGrid, GeoRSS, SVG, PDF, HTML):
  devuelven los atributos de las filas sin los permisos por campo de core;
- `sld`, `sld_body` (un SLD nombra sus propias capas, y `sld=` hace que GeoServer lea una url), `cql_filter`, `filter`,
  `featureid` (un filtro CQL puede consultar otra capa), `feature_count`, `exceptions` y cualquier parámetro que no
  conozca;
- el WFS, el WCS, el WMTS, el GWC y los servicios globales (`/geoserver/wms`, `/geoserver/ows`).

La plantilla:

- solo deja pasar a GeoServer `location = /geoserver/catastro/wms`, y solo con `GET` (el endpoint lee la uri, no un
  cuerpo); el resto de `/geoserver/` (la administración web, REST, WFS, GWC) es un 404;
- borra el `Authorization`, las cookies y el cuerpo antes de GeoServer, que nunca ve el token, y esconde su
  `Set-Cookie`;
- le pide a GeoServer los errores dibujados en la imagen (`exceptions=application/vnd.ogc.se_inimage`), y lo que no sea
  una imagen sale como `application/octet-stream`, con `X-Content-Type-Options: nosniff` y un
  `Content-Security-Policy: sandbox`: nada de lo que conteste GeoServer corre en el origen de la UI;
- marca las teselas `Cache-Control: private, no-store` y esconde su `Expires`: ni el navegador ni una caché compartida
  las guardan, así que después de un logout, de un token vencido o de un permiso retirado no se ven desde una caché.
  Cada tesela vuelve a GeoServer (el GWC no está en el camino); si eso pesa, `private, max-age=60` deja al navegador
  repetir una tesela un minuto, a cambio de que se vea ese minuto después de perder el acceso;
- **recuerda la autorización 60 s**. Solo un 204, con la clave del token más la uri entera menos su `bbox`, que es lo
  único que cambia de una tesela a otra y lo único que la autorización no lee. Así un mapa cuesta una llamada al backend
  por capa y no una por tesela. El precio: **un token revocado, o un READ retirado, sigue recibiendo teselas hasta
  60 s**. Una capa más, un parámetro con otras mayúsculas u otro token son otra clave y otra llamada;
- corta la autorización a los 5 s (`proxy_read_timeout`): un backend colgado deja la tesela en blanco, no el mapa.

Cada tesela que no está en esa caché es una llamada al endpoint (la definición del objeto sale de la caché de metadatos
de core). catastro-ui manda el Bearer en cada tesela con el `transformRequest` de sus mapas. Las páginas propias de
`@wasichai/gis` (la vista previa de `/gis/layers`) no lo mandan, y sus teselas WMS salen 401 (ver el README de
catastro-ui).

**La red de GeoServer.** `compose.geoserver.yml` pone a GeoServer solo en la red interna `catastro-geoserver`
(`internal: true`: sin puerto en el host y sin salida). En un despliegue, a esa red se unen solo catastro-core (que
publica las capas por REST) y el nginx de catastro-ui; nada más (Metabase, srtm-backend, otro proxy) llega a GeoServer.
El perfil `geoserver-local` publica `127.0.0.1:8085` para un backend que corre en la máquina (`./gradlew bootRun`): es
**inseguro fuera de una máquina de desarrollo**, porque quien llegue a ese puerto lee las capas de todas las
organizaciones (docs/develop/README.md, 3.1). Sin `WASICHAI_GEOSERVER_PASSWORD` compose no arranca: GeoServer usaría su
clave pública por defecto (`admin`/`geoserver`), y con ella el REST y la administración.

**Endurecer GeoServer.** Además del proxy, en la administración web de GeoServer (`/geoserver/web`, alcanzable solo por
la red interna o por un túnel al contenedor), una vez, después de levantarlo:

1. **La clave del administrador.** *Seguridad → Usuarios, grupos, roles → Usuarios/Grupos* (*Security → Users, Groups, Roles*): `admin` con la clave de
   `WASICHAI_GEOSERVER_PASSWORD` (el contenedor la crea así la primera vez; si el volumen es de antes, cámbiala aquí).
   *Seguridad → Contraseñas* (*Passwords*): cambia la contraseña maestra, que por defecto es la de `admin` de fábrica. La clave es
   la misma que usa catastro-core y no se versiona.
2. **Apagar lo que nadie usa.** *Servicios → WFS*, *Servicios → WCS* y, si está instalado, *Servicios → WPS*: desmarca
   «Habilitar» (*Enable*) en cada uno y guarda. *Caché de teselas → Valores por defecto* (*Tile Caching → Caching Defaults*): desmarca los servicios WMTS, TMS y
   WMS-C. Si un workspace tiene servicios propios (*Espacios de trabajo → catastro → Servicios*), apágalos también ahí.
   Si hace falta el WFS para `vistas_de_mapa.py`, déjalo encendido pero restringido: *Seguridad → Servicios*, una
   regla `wfs.*` con el rol `ADMIN`, y el script con las credenciales del administrador.
3. **Límites del WMS.** *Servicios → WMS → Límites de consumo de recursos* (*Resource consumption limits*): memoria máxima de render (por ejemplo
   65536 KB), tiempo máximo de render (por ejemplo 30 s) y errores máximos de render (por ejemplo 1000).

**Después de cada despliegue**, [docs/deploy/smoke-wms.sh](docs/deploy/smoke-wms.sh) revisa el WMS desde el origen
público. Comprueba que un `GetMap` de una capa propia da 200 `image/png`, y que dan error:

- sin token, 401;
- una capa de otra organización (sola o en la lista), o la capa con el token de la otra organización, 403;
- `GetCapabilities` y `POST`, 403;
- `/geoserver/rest`, `/geoserver/web` y `/geoserver/wfs`, 404.

Los tokens van solo por el entorno y nunca se imprimen:

```sh
read -rs WMS_TOKEN_PROPIO; read -rs WMS_TOKEN_AJENO; export WMS_TOKEN_PROPIO WMS_TOKEN_AJENO
docs/deploy/smoke-wms.sh https://<origen de catastro-ui> catastro:tramo_via__<prefijo>__geom catastro:tramo_via__<otro>__geom
```

Sin puerto de GeoServer en el host, `vistas_de_mapa.py` no llega al WFS para revisar las columnas de una capa: avisa,
y `--recrear-capas` la rehace sin mirarlo (ver «Vistas de mapa»).

## Región de la organización

Los valores unitarios de edificación y de obras complementarias de la R.M. N.° 277-2025-VIVIENDA son distintos por
región (Anexos I.1 a I.4 y III.1 a III.4: Lima Metropolitana y Callao, Costa, Sierra, Selva). Cada organización dice la
suya en **un solo** registro de `configuracion_catastro`, con `region` = `COSTA` o `SELVA`; la demarcación es la nota de
cada cuadro (la Costa, por ejemplo, llega hasta la curva de 2000 m.s.n.m. de la vertiente occidental). **No hay región
por omisión**: sin ese registro, con más de uno, o con una región sin tablas en el motor,
`GET /api/catastro/valuaciones` responde **409** con `errors[0].field` = `configuracion_catastro.region` y no valoriza
nada. Perené es `SELVA` (sus valuaciones no cambian); Ica, `COSTA`.

```sh
cd model
python3 configurar_region.py --region SELVA --dry-run   # lo que mandaría, sin llamar a core
python3 configurar_region.py --region SELVA             # crea el registro, o lo cambia si dice otra región
```

Entra como `--email` / `--password` (o `WASICHAI_EMAIL`, `WASICHAI_PASSWORD`) y escribe en la organización de ese
usuario. Es idempotente; con dos o más registros sale con 2 sin elegir uno (se borran los sobrantes en el admin). La
cuenta de servicio de srtm lee la región con su rol `SRTM_LECTOR`.

**Agregar una región** (`SIERRA`, `LIMA_CALLAO`):

1. la opción en el enum `region_catastro` de `model/model.json` (y `python3 apply.py` contra el Core);
2. la constante en `catastro.tablas.Region`;
3. `src/main/resources/tablas/valores-unitarios-<region>-2026.csv` (`<region>` en minúsculas, `_` → `-`), derivado del
   corpus verificado de normativa (`valores-unitarios-2026.md` §1.5 trae las otras tres), con su prueba celda por celda
   en `TablasTest`;
4. `obras-complementarias-<region>-2026.csv`, transcrito de su Anexo III y verificado por una persona antes del commit.
   Sin ese archivo la región carga igual, pero un predio con obras sale sin valor (`OBRAS_SIN_CUADRO:<REGION>`): una
   obra no se salta.

El RNT, los usos y los parámetros son nacionales: los comparten todas las regiones.

## Tablas normativas

Las tablas con que se valoriza viven en `src/main/resources/tablas/` y se cargan una vez por región al arrancar
(`catastro.tablas.Tablas.de(region)`, bean `TablasPorRegion` de `TablasConfig`); un archivo mal formado hace fallar el
arranque. Cada archivo abre con
líneas `#` que citan su fuente; las filas van tal como en la fuente. Las rutas de normativa son relativas a
`normativa/docs/10-negocio/valores-normativos/`.

| Archivo | Contenido | Fuente |
|---|---|---|
| `valores-unitarios-costa-2026.csv` | 27 celdas: 3 partidas × categorías A a I. Las tres `.....` (muros H e I, techos I) van vacías; techos H y puertas I son `0.00` explícitos. **Derivado, no transcrito**: las 24 filas de `fuentes/valores-unitarios-2026/valores-unitarios-costa-2026.csv` (sha256 `0540c3af…`) con las partidas del motor. Su `anio_construccion_desde` 1990 es el piso del esquema de normativa, no de la norma: el cuadro no tiene dimensión de año | R.M. N.° 277-2025-VIVIENDA, Anexo I.2 Costa, excepto Lima Metropolitana y Callao (`valores-unitarios-2026.md` §1.1, VERIFICADO) |
| `valores-unitarios-selva-2026.csv` | 30 celdas: 3 partidas × categorías A a J, en S/ por m² techado. `valor_m2` vacío es una celda `.....` (sin valor, no cero) | R.M. N.° 277-2025-VIVIENDA, Anexo I.4 Selva (`valores-unitarios-2026.md` §1.5.3) |
| `depreciacion-rnt-2016.csv` | 492 filas de las tablas 01 a 04, copia exacta (sha256 verificado en las pruebas). Las 36 celdas `*` no tienen fila; `antiguedad_hasta` vacío es «más de 50» | Reglamento Nacional de Tasaciones, Anexo I (`fuentes/depreciacion-rnt-2016/depreciacion.csv`) |
| `obras-complementarias-selva-2026.csv` | 96 partidas a costo directo, copia exacta de `model/data/obras_complementarias.csv` de srtm-backend. Llave `TIPO DE OBRA\|número`, la de `obra_complementaria.codigo_vu` | R.M. N.° 277-2025-VIVIENDA, Anexo III.4 Selva |
| `obras-complementarias-costa-2026.csv` | 96 partidas a costo directo, transcritas del Anexo III.2 con dos métodos independientes (poppler y pdfplumber, idénticos) y verificadas por una persona contra el PDF. Mismas llaves que el de la selva: `tipo_obra` y `material` son los de la partida del mismo número | R.M. N.° 277-2025-VIVIENDA, Anexo III.2 Costa (`s3://sgtm-fuentes-normativas/fuentes-normativas/valores-unitarios/200105/2026-08-28T23-43-56Z__iii-2-obras-complem-costa-2026.pdf`) |
| `uso-tabla-depreciacion.csv` | prefijo del código de `usos_predio` de srtm → tabla del RNT; gana el prefijo más largo. Editable | decisión D1 ([ADR-009](docs/adr/0009-decisiones-normativas-de-la-valorizacion.md)) |
| `parametros.csv` | `FACTOR_OFICIALIZACION` 0.68, `PORCENTAJE_ACTUALIZACION` 0, `INCREMENTO_PISO_DESDE` 5 y `INCREMENTO_PISO_PORCENTAJE` 5, de 2026, cada uno con su fuente | `obras-complementarias-y-oficializacion-2026.md` §1.2, `predial-porcentaje-de-actualizacion.md` §1.6, `valores-unitarios-2026.md` §1.3 y §1.6 |

`Tablas` responde con el vocabulario de la fuente (material `Concreto`, `Ladrillo`, `Liviano/Adobe`; estado `Muy Bueno`,
`Bueno`, `Regular`, `Malo`): llevar a él los enums del catastro (D2, D3) es cosa del motor de valorización. Una celda
`.....` o `*` devuelve nulo, nunca cero. Los códigos de clase `090000`, `100000` y `100400` de `usos_predio` no tienen
tabla (son agrupadores sin uso concreto).

## Motor de valorización

`catastro.valuacion.Valorizacion.valorizar(insumos, tablas)` es una función pura (sin base ni reloj) que devuelve el
autoavalúo de un predio en un año, con las tablas de la región de su organización, o el motivo por el que no lo tiene:

- terreno = área de terreno × arancel por m²;
- construcción, por piso: VU = muros y columnas + techos + puertas y ventanas (D4; sin techos con muros A, o con
  muros D de techo incluido), +5 % si el predio es edificio y el piso es el 5.° o más (único, antes de depreciar; un
  sótano `S1` no sube), × (1 − depreciación) × área construida. Cada sección de un piso (`seccion`) es una
  construcción más, con el mismo piso. La depreciación es la de la tabla de la `clasificacion` de la construcción, si
  la tiene, y si no la del uso del predio (D1). El redondeo del VU depende de la región (ver abajo);
- obras: VU de la partida × cantidad × factor de oficialización × (1 − depreciación), con la tabla del uso del predio y
  el material, estado y antigüedad de la obra (si la obra no dice material, el de su partida);
- autoavalúo = (terreno + construcción + obras) × (1 + % de actualización). Cada cifra con 2 decimales, HALF_UP.

**Redondeo del VU por región** (`Region.redondeaValorUnitario`):

| Región | Construcción de un piso o sección | Fuente |
|---|---|---|
| `COSTA` | round(round(VU × 1.05) × (1 − dep)) × área: el VU con el +5 % de edificio (si aplica) y el VU depreciado van al céntimo, HALF_UP, antes de multiplicar por el área | práctica del padrón de Ica (`PADRON_CONSTRUCCION.xlsx`: su `incremento_5` es round(VU × 5 %) y su `valor_total_nivel` es round((VU + incremento_5) × (1 − dep)) × área); decisión del usuario 2026-10-20 |
| `SELVA` | VU × 1.05 × (1 − dep) × área, sin redondeos intermedios | el motor de kamayuk, con el que se verificaron las cifras de Perené (no cambian) |

Las obras no se redondean en ninguna región: ningún padrón ha mostrado cómo lo hace. Una región nueva declara su regla
en `catastro.tablas.Region`.

Un dato que falta no es cero: el predio sale sin valor, con un `motivo` para leer y una `llave` para contar (por
ejemplo `ARANCEL_FALTANTE`, `VU_SIN_VALOR:TECHOS:I`, `TABLA_DE_DEPRECIACION:990000`,
`PARAMETRO_FALTANTE:FACTOR_OFICIALIZACION:2025`, `OBRAS_SIN_CUADRO:<REGION>`); el motivo nombra el cuadro de la región. Gana
el primero, en el orden del motor de kamayuk: terreno, arancel, parámetros del año, casillas del cuadro de cada piso,
tabla de depreciación del uso (solo si algo la usa: una construcción sin `clasificacion` o una obra), la de cada
`clasificacion` (`CLASIFICACION_DESCONOCIDA:<valor>` si el motor no la conoce), depreciación y obras.

**Contra el padrón de Ica** (`ValorizacionCostaTest`): con muros C, techos C y puertas F el VU es 387.43 + 285.80 +
90.81 = 764.04, el del padrón, y cinco niveles reales dan exactamente su `valor_total_nivel`. Leídos sus códigos contra
el RNT (`clasificacion_construccion` 1 a 4 = tabla 01 a 04; material 1 concreto, 2 ladrillo, 3 adobe; estado 1 a 4 = muy
bueno a malo; antigüedad 2026 − año), la depreciación implícita en su total es la del RNT en 3742 de 3755 niveles (las
celdas `*` como D3); su columna `depreciacion` no coincide en 1078 (casi siempre va un tramo atrás) y no se usa. Con la
`clasificacion` de cada nivel y el redondeo de la costa, el motor da exactamente su `valor_total_nivel` en 3688 de esos
3755 niveles (sin el redondeo, en 682). De los 67 restantes, 5 no tienen valor (celdas `.....` y la categoría J), 26
difieren en S/ 1 o menos y el resto son los niveles cuya depreciación no es la del RNT o cuyo VU no es el del cuadro.

**Versión del motor** (`version` en la respuesta, `ValuacionesService.VERSION`; srtm la guarda con cada corrida):

| Versión | Qué cambia |
|---|---|
| `valuacion-v1` | Depreciación con la tabla del uso del predio (D1); VU sin redondeos intermedios en todas las regiones |
| `valuacion-v2` | La `clasificacion` de cada construcción manda sobre el uso, y la costa redondea el VU al céntimo (arriba). Un predio de la selva sin `clasificacion`, como los de Perené, da la misma cifra que en v1 |
| `valuacion-v3` | Un predio rústico (`tipo_predio`/`tipoPredio`) sale sin valor con `PREDIO_RUSTICO` hasta que haya aranceles rústicos; los urbanos no cambian |

## API para srtm

srtm-backend lee las valuaciones de un año, página por página, con una cuenta de servicio de wasichai, para calcular la
brecha de recaudación. Se valoriza al vuelo: no se guarda nada.

```
GET /api/catastro/valuaciones?anio=2026&page=0&size=200
Authorization: Bearer <token de POST /api/auth/token>
```

- `anio` es obligatorio; `page` desde 0 (por defecto 0); `size` de 1 a 500 (por defecto 200). Un parámetro que falta,
  sobra o se sale de rango es un **422** que lo nombra (`errors[0].field`).
- Sin token, **401**. Lee como quien llama: sin `READ` sobre los cinco objetos, **403** de core.
- Sin región de la organización (ver Región de la organización), **409** que nombra `configuracion_catastro.region`.
- Los predios van ordenados por `codigo_municipal`, así que las páginas son estables. `total` es la cantidad de
  predios que el llamador puede leer; se lee hasta que una página traiga menos de `size`.

```json
{
  "anio": 2026,
  "version": "valuacion-v3",
  "region": "SELVA",
  "page": 0,
  "size": 200,
  "total": 1,
  "items": [
    {
      "codigoMunicipal": "0101001",
      "codigoCpu": "12030200101001",
      "sector": "01",
      "manzana": "001",
      "lote": "001",
      "uso": "010101",
      "areaTerreno": 200.0,
      "areaConstruida": 100.0,
      "longitudFrente": 10.5,
      "terreno": 9100.0,
      "construccion": 78781.6,
      "obras": 8870.61,
      "autoavaluo": 96752.21,
      "motivo": null,
      "llave": null,
      "loteGeom": { "type": "Polygon", "coordinates": [[[-75.22, -10.95], [-75.2195, -10.95], [-75.2195, -10.9495], [-75.22, -10.9495], [-75.22, -10.95]]] },
      "estadoLevantamiento": null,
      "fechaLevantamiento": null,
      "entrega": null,
      "vinculoMetodo": null,
      "vinculoRevisado": null,
      "cuc": null,
      "codigoReferenciaCatastral": null,
      "construcciones": [
        { "piso": 1, "seccion": 1, "areaConstruida": 100.0 }
      ]
    }
  ]
}
```

Cada ítem trae siempre todas sus llaves. Sin valor, `terreno`, `construccion`, `obras` y `autoavaluo` son `null` y
`motivo` (para leer) y `llave` (para agrupar) dicen por qué. `areaConstruida` es la suma de las áreas declaradas de los
pisos (0 sin pisos). `loteGeom` es el polígono del lote como geometría GeoJSON en EPSG:4326 (se guarda en 32718), o
`null`. El código del lote es `lote`, por eso la geometría se llama `loteGeom`. `version` cambia cuando cambia la
aritmética del motor; `region` es la de la organización, la de los cuadros con que se valorizó la página.
`estadoLevantamiento` (`SIN_LEVANTAR`, `PARCIAL` o `COMPLETO`) y `fechaLevantamiento` son los de la ficha misma;
`entrega` es el código de la `entrega_catastral` que trajo el último cambio de la ficha (o de uno de sus hijos), no
el id de la relación. `vinculoMetodo` (`CODIGO_RENTAS`, `LLAVE_HU_MZ_LOTE`, `GEOMETRICO` o `MANUAL`) y
`vinculoRevisado` dicen cómo se vinculó la ficha con su predio de rentas y si una persona ya la revisó (quién y
cuándo, en el audit log); `cuc` y `codigoReferenciaCatastral` son los códigos del Sistema Nacional Integrado de
Catastro (Ley 28294). Las siete son `null` sin dato, nunca ausentes. Estas cuatro últimas son llaves nuevas: el
cambio es aditivo ([ADR-007](docs/adr/0007-srtm-lee-con-una-cuenta-de-servicio.md)). Una ficha `SIN_LEVANTAR` no se
valoriza: su `llave` y su `motivo` son `SIN_LEVANTAMIENTO` (ver Motivos), y no hace falta pedirle área, arancel ni
construcciones.

`construcciones` trae una entrada por cada construcción del predio (`[]` si no tiene), en el orden en que las lee el
motor: por piso y, dentro de un piso, por sección. `piso` es el número de piso, o `null` cuando el piso de la ficha
no es un número (`S1`, un sótano); srtm empareja los pisos por número. `seccion` vacía en la ficha vale `1`, como en
el motor. `areaConstruida` es la declarada, o `null` sin dato; la del ítem es la suma de estas. También es una llave
nueva y aditiva (ADR-007), para los reportes de áreas por nivel de srtm (wasichai/srtm-backend#247).

**Motivos** (`llave` de un predio sin valor; `motivo` es la misma frase para una persona, o el mismo código cuando el
motivo no es una frase fija). Varios llevan un sufijo dinámico (`:dato`) que no está en esta tabla:

| `llave` | Por qué |
|---|---|
| `SIN_LEVANTAMIENTO` | La ficha tiene `estado_levantamiento = SIN_LEVANTAR`: aún no se ha levantado en campo |
| `PREDIO_RUSTICO` | El predio es rústico (`tipo_predio`/`tipoPredio` = `RUSTICO`): aún no hay aranceles rústicos con que valorizarlo |
| `AREA_TERRENO_FALTANTE` | El predio no declara área de terreno |
| `ARANCEL_FALTANTE` | La vía del predio no tiene arancel por m² para el año |
| `PARAMETRO_FALTANTE:<clave>:<año>` | Las tablas no traen ese parámetro para ese año |
| `TABLA_DE_DEPRECIACION:<uso>` | No hay tabla de depreciación del RNT para ese uso (D1) |
| `AREA_CONSTRUIDA_FALTANTE` | Una construcción no declara área construida |
| `AREA_CONSTRUIDA_INVALIDA` | Una construcción declara un área construida negativa |
| `ANIO_CONSTRUCCION_FALTANTE` | Una construcción u obra no declara año de construcción |
| `ANTIGUEDAD_NEGATIVA` | El año de construcción es posterior al año de la valuación |
| `MATERIAL_FALTANTE` | Una construcción u obra no declara material |
| `ESTADO_FALTANTE` | Una construcción u obra no declara estado de conservación |
| `ESTADO_DESCONOCIDO:<estado>` | El RNT no conoce ese estado de conservación |
| `CATEGORIA_FALTANTE:<partida>` | Una construcción no declara la categoría (letra) de esa partida |
| `CATEGORIA_INVALIDA:<partida>:<categoria>` | La categoría declarada está fuera del rango del cuadro de la región |
| `VU_SIN_VALOR:<partida>:<categoria>` | La celda del cuadro para esa partida y categoría es «.....», no cero |
| `TECHO_INCLUIDO_INVALIDO:<muros>` | El indicador de techo incluido se marcó con muros que no son A ni D (drywall) |
| `CLASIFICACION_DESCONOCIDA:<clasificacion>` | La `clasificacion` de la construcción no tiene tabla del RNT en el motor |
| `DEPRECIACION_FALTANTE:<tabla>:<material>:<estado>` | El RNT no trae esa fila de depreciación |
| `OBRAS_SIN_CUADRO:<region>` | El predio declara obras y la región no tiene cuadro de obras complementarias |
| `OBRA_DESCONOCIDA:<codigoVu>` | El cuadro de obras complementarias de la región no tiene esa partida |
| `OBRA_CANTIDAD_FALTANTE` | Una obra no declara cantidad |
| `OBRA_CANTIDAD_INVALIDA` | Una obra declara una cantidad negativa |

**Valuar insumos sueltos.** srtm también valúa los datos de un predio que no están en el catastro (la DJ de un
contribuyente, por ejemplo), con el mismo motor y las tablas de la región de la organización. No se guarda nada:

```
POST /api/catastro/valuacion
Authorization: Bearer <token de POST /api/auth/token>
Content-Type: application/json
```

```json
{
  "anio": 2026,
  "areaTerreno": 200,
  "arancelM2": 45.5,
  "uso": "010101",
  "esEdificio": false,
  "construcciones": [
    { "piso": "1", "areaConstruida": 100, "anioConstruccion": 2016, "material": "CONCRETO", "estado": "BUENO",
      "muros": "C", "techos": "D", "puertas": "E", "techoIncluido": null, "clasificacion": null, "seccion": null }
  ],
  "obras": [
    { "codigoVu": "MUROS PERIMETRICOS O CERCOS|1", "cantidad": 30, "anioConstruccion": 2016, "material": "CONCRETO", "estado": "BUENO" }
  ],
  "codigoMunicipal": null,
  "tipoPredio": null
}
```

- Los campos son los de `Insumos`, con los nombres y la ortografía de los enums del modelo (material, estado y
  `clasificacion`). Solo `anio` (1900 a 2100) es obligatorio, y `piso` en cada construcción. Lo que falta o viene `null`
  queda sin declarar: el predio sale con su `motivo`, nunca con un cero. Las letras (`muros`, `techos`, `puertas`) son
  una sola mayúscula de la A a la J; `seccion`, un entero desde 1. `tipoPredio` es `URBANO` o `RUSTICO`; un predio
  `RUSTICO` sale con `PREDIO_RUSTICO` (ver Motivos), y un texto que no es ninguna de las dos es un **422** sobre
  `tipoPredio`. Un campo que sobra, o de otro tipo, es un **422** que lo nombra (`errors[0].field`, por ejemplo
  `construcciones[0].muros`).
- Sin `arancelM2`, con `codigoMunicipal`, toma el arancel del año de esa ficha del catastro (`origenArancel` =
  `FICHA`). Si la ficha no existe o no tiene arancel, `ARANCEL_FALTANTE`. Solo se toma el arancel; lo demás es del
  cuerpo.
- Mismo permiso que `GET /valuaciones` (SRTM_LECTOR basta): **401** sin token, **403** sin `READ` y **409** sin región.
- Un año sin tablas (hoy solo hay 2026) da `PARAMETRO_FALTANTE:PORCENTAJE_ACTUALIZACION:<año>`; no se valúa con
  otro año.
- **El área común no se valúa:** el motor no tiene ese insumo.

```json
{
  "anio": 2026,
  "version": "valuacion-v3",
  "region": "SELVA",
  "codigoMunicipal": null,
  "arancelM2": 45.5,
  "origenArancel": "CUERPO",
  "terreno": 9100.0,
  "construccion": 78781.6,
  "obras": 8870.61,
  "autoavaluo": 96752.21,
  "motivo": null,
  "llave": null,
  "detalle": {
    "pisos": [
      { "piso": "1", "seccion": null, "areaConstruida": 100, "valorUnitario": 829.28, "incremento": 0.0,
        "tablaDepreciacion": "01", "antiguedad": 10, "porcentajeDepreciacion": 5, "valorUnitarioDepreciado": 787.816,
        "valor": 78781.6 }
    ],
    "obras": [
      { "codigoVu": "MUROS PERIMETRICOS O CERCOS|1", "cantidad": 30, "valorUnitario": 457.72, "factorOficializacion": 0.68,
        "tablaDepreciacion": "01", "antiguedad": 10, "porcentajeDepreciacion": 5, "valor": 8870.61 }
    ]
  }
}
```

`detalle` muestra cómo se llegó a `construccion` y `obras` (la suma de sus `valor`), en el orden del cuerpo:
`incremento` es lo que suma el 5 % de edificio al VU (0 debajo del 5.° piso), y `valorUnitarioDepreciado` =
(`valorUnitario` + `incremento`) × (1 − `porcentajeDepreciacion` / 100), al céntimo en la costa. Sin valor, `terreno`,
`construccion`, `obras`, `autoavaluo` y `detalle` son `null`. `GET /valuaciones` no trae `detalle`: su contrato no
cambia.

**Titulares.** `GET /valuaciones` no trae los titulares de un predio (para que la respuesta siga liviana): srtm los
lee de un endpoint aparte, en vez de la API genérica de registros, porque esta solo da el uuid del predio y srtm
necesita su `codigoMunicipal`:

```
GET /api/catastro/titulares?page=0&size=200
Authorization: Bearer <token de POST /api/auth/token>
```

- `page` desde 0 (por defecto 0); `size` de 1 a 500 (por defecto 200). Un parámetro que falta, sobra o se sale de
  rango es un **422** que lo nombra (`errors[0].field`).
- Sin token, **401**. Lee como quien llama: sin `READ` sobre `titular_catastral`, **403** de core (SRTM_LECTOR lo
  tiene).
- Los titulares van ordenados por `codigo_municipal` y luego por su id (el único orden propio del objeto que core
  pagina sin repetir ni saltar filas). `total` es la cantidad de titulares que el llamador puede leer.

**Son datos personales (Ley 29733): SRTM_LECTOR es el único lector de `titular_catastral`**, y los reportes de carga
de `import_fichas.py --titulares` nunca imprimen documentos ni nombres (solo el código del predio y el número de
fila). Los valores de este ejemplo son sintéticos:

```json
{
  "page": 0,
  "size": 200,
  "total": 1,
  "items": [
    {
      "codigoMunicipal": "0101001",
      "tipoDocumento": "DNI",
      "numeroDocumento": "10000001",
      "nombre": "Titular Sintético Uno",
      "porcentaje": 100.0,
      "condicion": "PROPIETARIO"
    }
  ]
}
```

Cada ítem trae siempre sus seis llaves, `null` sin dato. `tipoDocumento` y `condicion` son texto libre, tal como los
escribe el padrón de origen (el vocabulario varía entre municipalidades); un documento de relleno (por ejemplo
`000000000`) se carga vacío (`numeroDocumento: null`) y se reporta por código de predio y fila, nunca por su valor.

**Cambios.** srtm sigue los cambios del catastro con un cursor, en vez de traer todas las valuaciones en cada corrida
para saber si algo cambió ([ADR-014](docs/adr/0014-srtm-sigue-los-cambios-por-un-cursor.md)). Así puede avisar a rentas
de una ampliación levantada en campo y volver a correr la brecha solo cuando hace falta:

```
GET /api/catastro/cambios?desde=<cursor>&size=200
Authorization: Bearer <token de POST /api/auth/token>
```

- Trae las altas, cambios y bajas (`CREATE`, `UPDATE`, `DELETE`) de `predio_catastral`, `construccion`,
  `obra_complementaria` y `titular_catastral`, del más viejo al más nuevo. Salen del `audit_log` de wasichai, que
  catastro lee por dentro.
- `desde` es opcional; sin él, empieza desde el principio. `size` va de 1 a 500 (por defecto 200). Un parámetro que
  sobra, un `size` fuera de rango o un `desde` que este endpoint no devolvió es un **422** que lo nombra
  (`errors[0].field`).
- Sin token, **401**. Sin `READ` sobre esos cuatro objetos y sobre `entrega_catastral`, **403** (SRTM_LECTOR los
  tiene).
- **El cursor es opaco.** Se guarda tal como llega y se pasa como `desde` la próxima vez; no se arma ni se interpreta.
  Se piden páginas mientras `hayMas` sea `true`. Si no hay nada nuevo, vuelve el mismo `cursor` con `items` vacío y
  `hayMas: false`. El `cursor` es `null` solo si no hay ningún cambio y no vino `desde`.

Ejemplo con valores sintéticos:

```json
{
  "items": [
    {
      "codigoMunicipal": "0101001",
      "objeto": "construccion",
      "operacion": "UPDATE",
      "campos": ["area_construida"],
      "en": "2026-10-25T14:03:12.481263Z",
      "entrega": "BARRIDO-2026-10"
    },
    {
      "codigoMunicipal": "0101001",
      "objeto": "obra_complementaria",
      "operacion": "DELETE",
      "campos": [],
      "en": "2026-10-25T14:03:12.902114Z",
      "entrega": "BARRIDO-2026-10"
    }
  ],
  "cursor": "YzEKMjAyNi0xMC0yNVQxNDowMzoxMi45MDIxMTRaCjNmMmM5YjRlLTdkMWEtNGU1Ni05YjBhLTJjOGQ0ZTZmMWEyMw",
  "hayMas": false
}
```

Cada ítem trae siempre sus seis llaves:

- `codigoMunicipal` es el del predio. Una construcción u obra lleva el de su predio, que se lee del audit log, así que
  sale aunque el predio ya se haya borrado. Es `null` si no se puede resolver, y srtm tiene que aceptarlo.
- `campos` son los nombres de lo que cambió, nunca sus valores: en un alta, los campos que se llenaron; en un cambio,
  los que cambiaron de valor; en una baja, ninguno. Un `UPDATE` de `predio_catastral` con `campos` vacío es un cambio
  solo de geometría (`import_lotes.py --actualizar-geometria`); sin `--entrega`, ese cambio trae `entrega: null`.
- `en` es el instante del cambio.
- `entrega` es el código de la `entrega_catastral` que lo cargó (el `X-Change-Reason` del cargador). Es `null` si el
  cambio se hizo a mano o si su motivo no es una entrega.

**El feed puede perder un cambio.** wasichai no guarda un registro y su fila de auditoría en una misma transacción
(`RecordChanges`), y `en` es el inicio de la transacción. Por eso un cambio que se confirma tarde, con un `en` anterior
a un cursor ya entregado, no aparece. srtm lo cubre con una corrida completa cada semana (wasichai/srtm-backend#203),
que lee todas las valuaciones sin mirar el feed.

**Puesta en marcha** (contra el Core del catastro, como admin):

```sh
cd model
python3 apply.py                 # el modelo, con configuracion_catastro
python3 apply_roles.py           # crea o sincroniza SRTM_LECTOR (READ sobre los ocho objetos y la escritura de arancel) y CATASTRO_LECTOR
python3 configurar_region.py --region SELVA   # la región de la organización (Perené); COSTA para Ica
python3 crear_cuenta_srtm.py --clave perene   # la cuenta `srtm` con SRTM_LECTOR; imprime clientId y clientSecret
```

`crear_cuenta_srtm.py` imprime el `clientSecret` **una sola vez**: guárdalo en el entorno de srtm-backend, que lee un
catastro por organización (srtm-backend#130), en la entrada de esta organización:

```sh
SRTM_CATASTRO_ORGANIZACIONES_PERENE_URL=http://catastro-perene:8091   # este catastro, visto desde srtm
SRTM_CATASTRO_ORGANIZACIONES_PERENE_CLIENT_ID=...
SRTM_CATASTRO_ORGANIZACIONES_PERENE_CLIENT_SECRET=...
# opcional: SRTM_CATASTRO_ORGANIZACIONES_PERENE_TIMEOUT=60s
```

La clave (`PERENE`, la de `--clave`, que solo pone el nombre en lo que imprime) es el slug de la organización en srtm.
srtm la recibe en minúsculas y no admite guiones ni guiones bajos: un id (UUID) o un slug que los lleve va en
`SRTM_CATASTRO_ORGANIZACIONES_<CLAVE>_ORGANIZACION`, bajo una clave cualquiera (por ejemplo `_ICA_ORGANIZACION=<id>`).
La forma de una sola organización (`SRTM_CATASTRO_URL`, `SRTM_CATASTRO_CLIENT_ID`, `SRTM_CATASTRO_CLIENT_SECRET` y
`SRTM_CATASTRO_ORGANIZACION`) sigue valiendo, como una entrada más. Es idempotente: si la cuenta ya existe solo le agrega el rol
si le falta y dice su `clientId`; un secreto nuevo se pide con `POST /api/service-accounts/{id}/secret` (anula el
anterior). srtm pide su token con `POST /api/auth/token {"clientId", "clientSecret"}` → `{"token", "expiresAt",
"serviceAccount"}` y lo renueva al vencer. `apply_roles.py` deja el rol exactamente con los permisos de `roles.json`
(un permiso dado a mano en el admin se pierde); los dos aceptan `--dry-run`, `--core`, `--email` y `--password`.

**Actualizar un despliegue que ya existe** a la versión con región por organización (Perené en dev, la organización
`demo`): con el jar viejo todavía corriendo, que ignora el objeto nuevo, y cada paso primero con `--dry-run`
(`apply.py --diff`) y el OK de quien opera la base:

1. `python3 apply.py` crea `configuracion_catastro` (sin él, core responde 404 a las valuaciones);
2. `python3 apply_roles.py` da a SRTM_LECTOR el `READ` sobre él (sin él, 403);
3. `python3 configurar_region.py --region SELVA` crea el registro (sin él, 409);
4. recién entonces se cambia el jar.

Si se cambia el jar antes, cada corrida de la brecha de srtm falla en la página 0 con uno de esos códigos, y srtm solo
muestra el código (no el cuerpo, que dice `configuracion_catastro.region`).

## API para catastro-ui: aranceles por vía

El mapa de catastro-ui pinta cada tramo de vía con su valor arancelario de un año.

```
GET /api/catastro/vias/aranceles?anio=2026
Authorization: Bearer <token>
```

- `anio` de 1900 a 2100; sin él, el año en curso (America/Lima). Un `anio` que no se lee, o un parámetro que sobra, es
  un **400** que lo nombra (`errors[0].field`): ese es el contrato con catastro-ui.
- Sin token, **401**. Lee como quien llama: sin `READ` sobre `tramo_via`, **403** de core. También lee `arancel`
  para el valor: sin `READ` sobre `arancel`, también **403**, así que quien use el mapa necesita `READ` sobre los
  dos. Para el personal municipal está el rol **`CATASTRO_LECTOR`** («Lector de catastro», `model/roles.json`): solo
  `READ` sobre las fichas (predios, construcciones, obras), las entregas, la región, los aranceles y los tramos de vía;
  no crea, no cambia ni borra nada, y no lee `titular_catastral` (datos personales, solo `SRTM_LECTOR`). **La página
  «Aranceles por vía» de catastro-ui necesita ese rol, o el admin.** `apply_roles.py` lo crea; se asigna a cada
  usuario en el admin de wasichai.
- Responde un `FeatureCollection` GeoJSON en EPSG:4326, un `Feature` por fila de `tramo_via` (las que no tienen
  geometría no se dibujan y no salen), ordenados por `clave`. `id` es el id del registro. Un `MultiLineString` de una
  parte sale como su `LineString`.
- `valor_m2` sale del `arancel` con clave `id_aranc|anio`, leído en un solo lote por `id_aranc` como lo leen las
  valuaciones, para cualquier año, así que un arancel que srtm sincroniza se ve en el mapa al momento. El
  `tramo_via.valor_m2` guardado es solo la copia del año en curso para la vista de mapa y la capa WMS (ver «Vías»).
  Es `null` si el tramo no tiene `id_aranc` o si su vía no tiene arancel ese año (nunca se toma el de otro año).

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "6c1f…",
      "geometry": { "type": "LineString", "coordinates": [[-75.7300, -14.0700], [-75.7290, -14.0700]] },
      "properties": {
        "cod_via_eje": "026220",
        "tip_via": "CA.",
        "nom_via": "CA. LOS ÁLAMOS",
        "cuadra": null,
        "lado": "AMBOS",
        "id_aranc": "0010000401-01",
        "asignacion": "NOMBRE_UNICO",
        "anio": 2026,
        "valor_m2": 356.0
      }
    }
  ]
}
```

## API para catastro-ui: brechas

El dashboard «Brechas» de catastro-ui muestra la brecha de recaudación de los cortes que cargó
`importar_corte_brecha.py` ([Corte de brecha](#corte-de-brecha)) y lleva la bandeja de decisiones. Todo va bajo
`/api/catastro/brechas`.

- **Permisos.** Sin token, **401**. Cada ruta exige `READ` sobre `brecha_ficha` (si no, **403**) y lee como quien
  llama, así que también necesita `READ` sobre `corte_brecha`, `decision_brecha` y `predio_catastral`. El rol
  `CATASTRO_LECTOR` alcanza para leer. `POST /decisiones` exige además `UPDATE` sobre `decision_brecha` (si no,
  **403**), y crear una decisión, `CREATE`: los da `CATASTRO_ANALISTA`. **Es la única puerta**: un
  `RecordWriteGuard` (`DecisionesSoloPorLaApi`) rechaza con 403 cualquier otra escritura de `decision_brecha` (la API
  genérica de registros, el admin, automatizaciones), así que `responsable`, `decidido_en`, `corte_origen` y el motivo
  de un descarte los pone siempre este endpoint. El endpoint marca sus escrituras con un elemento del contexto de la
  corrutina, el mecanismo de wasichai para las reglas propias de una app (ADR-040); `RecordService.asPlatform` no sirve
  aquí porque wasichai lo prohíbe dentro de una petición.
- **Cortes completos.** Solo se ven los cortes con `cargado_en`, que el cargador escribe al final: un corte a medio
  cargar no aparece en `/cortes` ni es el corte por omisión.
- **El corte.** `corte` es la clave del corte (`<org>|<fecha>`). Sin él, se usa el más reciente por fecha. Si no hay
  ningún corte, `/panel`, `/fichas`, `/lotes` y `/fichas.csv` responden **404**
  `{"message": "No hay cortes de brecha cargados"}`. Una clave que no existe también da 404, con su propio mensaje.
- **Parámetros.** Uno que la ruta no conoce, o que no se puede leer, es un **400** que lo nombra
  (`errors[0].field`), como en `/vias/aranceles`.

**Rutas:**
- `GET /cortes`: `[{clave, fecha, anio, corrida, total_fichas, delta_impuesto, cargado_en}]`, el más reciente
  primero.
- `GET /panel?corte=`:
  - `corte`: `{clave, fecha, anio, corrida}`;
  - `kpis`: `{fichas, delta_impuesto, delta_impuesto_confiable, omisos_estimado, supera_5_uit, pendientes,
    con_geometria, sin_ficha}`. `pendientes` y `por_estado` cuentan solo las fichas que se pueden decidir (con
    `codigo_municipal`); `sin_ficha`, las otras;
  - `por_categoria`, `por_confianza`: `[{clave, fichas, delta_impuesto}]`, una entrada por cada opción del modelo,
    incluso las que no tienen fichas. Las fichas sin confianza (un corte anterior a srtm-backend#204) van con
    `clave: null`;
  - `por_estado`: `[{clave, fichas}]`;
  - `top_sectores`: `[{sector, fichas, delta_impuesto}]`, los 10 sectores de mayor Δ impuesto.

  Todo se cuenta sobre todas las fichas del corte, sin filtros.
- `GET /fichas?corte&categoria&confianza&sector&estado&supera_5_uit&min_delta&orden&page&size`: una página
  `{content, page, size, totalElements, totalPages}`.
  - `categoria`, `confianza` y `estado` aceptan varias opciones separadas por comas. `estado` es el efectivo: una
    ficha sin decisión está `PENDIENTE`.
  - `min_delta` compara contra |Δ impuesto|, así que una ficha sin Δ no pasa.
  - `orden`: `delta_desc` (por omisión), `delta_asc` o `codigo`. Lo vacío va al final y el desempate es por código.
  - `size` va de 1 a 500 (50 por omisión).
  - Cada fila es `{id, codigo_catastro, codigo_municipal, codigo_predio, categoria, confianza, confianza_motivo,
    sector, manzana, lote, uso, autoavaluo_declarado, autoavaluo_catastro, delta_autoavaluo, impuesto_declarado,
    impuesto_catastro, delta_impuesto, delta_arbitrios, estimado, motivo, supera_5_uit, estado, responsable, nota,
    decidido_en, con_geometria}`. La decisión es la del año del corte.
- `GET /lotes?…`: los mismos filtros, sin `page` ni `size` (`orden` se acepta, pero no cambia nada). Responde un
  `FeatureCollection` en EPSG:4326 con un `Feature` por `codigo_municipal` (`id`):
  - el `lote_geom` de su ficha;
  - en `properties`: `codigo_municipal`, `codigo_catastro`, `categoria`, `confianza`, `delta_impuesto`, `estado`,
    `supera_5_uit` y `fichas` (cuántas fichas del corte comparten ese código; el Feature es el de la de mayor Δ).

  Solo entran las fichas empatadas que tienen lote. Las geometrías salen de la caché del corte.
- `GET /fichas.csv?…`: los mismos filtros y `orden`. Devuelve `text/csv` en UTF-8 con BOM, con las columnas de la fila
  en el mismo orden, en un archivo `brechas-<org>_<fecha>.csv` (`Content-Disposition`, también como `filename*`). No
  lleva datos personales: no lee `titular_catastral` y `responsable` va sin el dominio del correo. Un texto que empieza
  con `=`, `+`, `-`, `@`, tabulador o retorno va precedido de `'` (inyección en la hoja de cálculo); los números no.
- `POST /decisiones` con `{codigos: [codigo_municipal…], anio, estado, nota?, motivo_descarte?}` decide en lote, de 1
  a 500 códigos de hasta 64 caracteres, 8 a la vez. Por cada código crea o actualiza su `decision_brecha` (clave
  `<codigo>|<anio>`). `anio` tiene que ser el de un corte cargado, y `nota` y `motivo_descarte` no pasan de 2000
  caracteres (si no, 400 en el campo). Un rol con `UPDATE` pero sin `CREATE` recibe 403 antes de escribir nada.
  - Lo fija el servidor: `responsable` (el email de quien llama), `decidido_en` (ahora) y `corte_origen` (el corte
    más reciente del año de la decisión).
  - `DESCARTADO` sin `motivo_descarte` es un 400 con `field: motivo_descarte`; otro estado borra el motivo.
  - Sin `nota`, se conserva la que había.
  - Un código que no es de ninguna ficha, o que el Core rechaza, va a `errores` y el resto se escribe igual.
  - Responde `{actualizadas, creadas, errores: [{codigo, error}]}`.

**Cómo se lee un corte.** Un corte de Ica tiene unas 25 000 fichas, y los filtros (varias opciones, |Δ|, el estado de
otra tabla) no se pueden expresar con los filtros de igualdad del Core. Por eso se guarda en memoria, en dos partes que
cambian a ritmos distintos:

- **la base del corte**: sus fichas (una pasada keyset por `clave`) y el lote de cada una (lotes de 200 códigos, 4 a la
  vez), que da a la vez `con_geometria` y las geometrías de `/lotes`. Solo cambia cuando el corte se recarga, así que se
  guarda **5 minutos**, contados desde que termina de leerse, con la llave organización, roles de quien llama (un campo que un rol no puede leer nunca le
  llega a otro), id del corte y `cargado_en`;
- **las decisiones del año**: pocas filas, una pasada, guardadas **15 segundos** con la llave organización, roles, año
  y una generación que cada `POST /decisiones` avanza. Una decisión se ve al momento en esta instancia sin releer la
  base; una tomada en otra instancia, en 15 segundos como mucho.

Cada parte se lee una sola vez por llave aunque lleguen varias peticiones a la vez (la página pide `/panel`, `/fichas`
y `/lotes` juntas): la primera lanza la lectura y las demás la esperan. Cada petición une las dos partes en su vista
(una pasada sobre las fichas, sin leer nada) y `/panel` la cuenta en una sola pasada.

## Decisiones normativas

Las decisiones D1 a D12 (uso a tabla de depreciación, material, estado, suma de partidas, casillas `.....`, % de
actualización, llave de cruce con srtm, deducción Amazonía, obras, umbral de coincidencia, año y secuencias de uso),
confirmadas por la municipalidad el 2026-10-19, están en el
[ADR-009](docs/adr/0009-decisiones-normativas-de-la-valorizacion.md), con lo que sigue abierto. D1 la enmienda el
[ADR-010](docs/adr/0010-la-clasificacion-manda-y-la-costa-redondea.md) (la `clasificacion` de cada construcción
manda). Una decisión nueva o un cambio es un ADR nuevo ([índice](docs/adr/README.md)).
