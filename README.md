# catastro-backend

Valorización catastral de los predios de una municipalidad (hoy Perené, ubigeo 120302, en la selva; Ica, en la
costa), sobre el framework [wasichai](https://github.com/wasichai/wasichai) 1.2.0.

Valoriza cada predio del levantamiento catastral (autoavalúo por predio y año) con aranceles, valores unitarios y
depreciación, para que srtm-backend calcule la brecha de recaudación contra el padrón declarado. **No calcula
impuestos**: el impuesto predial es de srtm-backend.

## Requisitos

- JDK 25
- Docker (PostGIS para la base y para las pruebas de integración)
- Node 26 y yarn (solo para prettier y commitlint)

## Cómo correrlo

```sh
docker compose up -d      # postgis en 127.0.0.1:5434 (CATASTRO_PG_PORT)
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
srtm-backend. Cinco objetos: `predio_catastral` (llave `codigo_municipal`, igual a `predio.codigo` de srtm),
`construccion` y `obra_complementaria` (cuelgan de un predio), `arancel` y `configuracion_catastro` (la región de la
organización, ver abajo). wasichai no tiene únicos compuestos, así que
`arancel.clave` (`id_aranc|anio`) garantiza el par único. `codigo_vu` de una obra es `TIPO DE OBRA|número`, como
`obra_categoria` de srtm (`model/data/obras_complementarias.csv`).

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

**Fichas** (`import_fichas.py`): `--fichas` (un predio por fila), `--pisos` (un piso por fila, ligado por
`codigo_municipal`) y `--obras` (opcional), en csv o xlsx. Las columnas por defecto salen del contrato de carga masiva
del MEF (`cod_pre`, `cod_cpu`, `cod_sect`, `cod_mzn`, `cod_lote`, `id_aranc`, `area_terreno`, `longitud_frente`...);
`--map`, `--map-pisos` y `--map-obras` `campo=columna` las cambian. Las siete categorías van en una columna
`categorias` (`CCDCCDC`: muros y columnas, techos, pisos, puertas y ventanas, revestimientos, baños, instalaciones) o en
siete columnas con el nombre del campo. La columna opcional `techo_incluido` (`SI`/`NO`, `S`/`N`, `TRUE`/`FALSE`,
`1`/`0`, sin distinguir mayúsculas; vacía no se envía) marca los muros D de drywall que incluyen el techo (llamada 5 del
Anexo I.4, ver D4); un valor que no se lee es un error de validación (código 2). Un predio que el Core ya tiene se
salta; los pisos (llave predio y piso) y las obras (llave predio, `codigo_vu` y año de construcción) se crean solo si
faltan, así que una carga que falló a medias se completa volviendo a correrla. Un piso que el Core ya tiene no se
actualiza: para cambiarle `techo_incluido` hay que editarlo en el Core. Una llave repetida en el archivo es un error.

```sh
python3 import_fichas.py --fichas fichas.csv --pisos pisos.csv --obras obras.csv --dry-run
```

**Aranceles** (`import_aranceles.py`): dos csv sacados de la geodatabase (solo lectura) y unidos por `ID_ARANC`.
`VAL_ACT` 0 se carga tal cual (el motor reporta un `motivo`); `VAL_ACT` vacío no tiene valor y se omite (el comando
dice cuántos). `--anio` filtra un año (por defecto todos).

```sh
ogr2ogr -f CSV frentes.csv 120302_MD_Perene_ECF.gdb CF_ARANCEL_18 -select ID_ARANC,COD_VIA,CUADRA,LADO
ogr2ogr -f CSV valores.csv 120302_MD_Perene_ECF.gdb TB_VALORACION_HIST -select ID_ARANC,ANO_EJEC,VAL_ACT
python3 import_aranceles.py --frentes frentes.csv --valores valores.csv --anio 2026 --dry-run
```

**Lotes** (`import_lotes.py`): polígonos de un GeoJSON en EPSG:4326 hacia `predio_catastral.lote_geom`. Solo actualiza
los predios que ya existen (por `codigo_municipal`, y si el lote no lo trae, por `codigo_cpu`); `--map` indica la
propiedad. `CF_LOTES_POL_18` no trae esos códigos: hay que cruzarlos antes.

```sh
ogr2ogr -f GeoJSON -t_srs EPSG:4326 lotes.geojson 120302_MD_Perene_ECF.gdb CF_LOTES_POL_18
python3 import_lotes.py --geojson lotes.geojson --map codigo_municipal=COD_PRE --dry-run
```

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
| `obras-complementarias-costa-2026.csv` | **Aún no está**: se transcribe del Anexo III.2 y entra al repositorio cuando una persona lo verifica. Mientras tanto un predio de la costa con obras sale `OBRAS_SIN_CUADRO:COSTA`. Mismas llaves que el de la selva | R.M. N.° 277-2025-VIVIENDA, Anexo III.2 Costa (`s3://sgtm-fuentes-normativas/fuentes-normativas/valores-unitarios/200105/2026-08-28T23-43-56Z__iii-2-obras-complem-costa-2026.pdf`) |
| `uso-tabla-depreciacion.csv` | prefijo del código de `usos_predio` de srtm → tabla del RNT; gana el prefijo más largo. Editable | decisión D1 (ver Decisiones normativas) |
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
  sótano `S1` no sube), × (1 − depreciación) × área construida;
- obras: VU de la partida × cantidad × factor de oficialización × (1 − depreciación), con la tabla del uso del predio y
  el material, estado y antigüedad de la obra (si la obra no dice material, el de su partida);
- autoavalúo = (terreno + construcción + obras) × (1 + % de actualización). Cada cifra con 2 decimales, HALF_UP.

Un dato que falta no es cero: el predio sale sin valor, con un `motivo` para leer y una `llave` para contar (por
ejemplo `ARANCEL_FALTANTE`, `VU_SIN_VALOR:TECHOS:I`, `TABLA_DE_DEPRECIACION:990000`,
`PARAMETRO_FALTANTE:FACTOR_OFICIALIZACION:2025`, `OBRAS_SIN_CUADRO:COSTA`); el motivo nombra el cuadro de la región. Gana
el primero, en el orden del motor de kamayuk: terreno, arancel, parámetros del año, casillas del cuadro de cada piso,
tabla de depreciación del uso, depreciación y obras.

**Contra el padrón de Ica** (`ValorizacionCostaTest`): con muros C, techos C y puertas F el VU es 387.43 + 285.80 +
90.81 = 764.04, el del padrón, y cinco niveles reales dan exactamente su `valor_total_nivel`. Leídos sus códigos contra
el RNT (`clasificacion_construccion` 1 a 4 = tabla 01 a 04; material 1 concreto, 2 ladrillo, 3 adobe; estado 1 a 4 = muy
bueno a malo; antigüedad 2026 − año), la depreciación implícita en su total es la del RNT en 3742 de 3755 niveles (las
celdas `*` como D3); su columna `depreciacion` no coincide en 1078 (casi siempre va un tramo atrás) y no se usa.
**Abierto:** el padrón redondea a 2 decimales el VU depreciado antes de multiplicar por el área (así cuadran 3696 de sus
3755 totales) y el motor no, para que Perené no cambie: la diferencia es de céntimos por nivel, muy por debajo de D10.

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
  "version": "valuacion-v1",
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
      "loteGeom": { "type": "Polygon", "coordinates": [[[-75.22, -10.95], [-75.2195, -10.95], [-75.2195, -10.9495], [-75.22, -10.9495], [-75.22, -10.95]]] }
    }
  ]
}
```

Cada ítem trae siempre todas sus llaves. Sin valor, `terreno`, `construccion`, `obras` y `autoavaluo` son `null` y
`motivo` (para leer) y `llave` (para agrupar) dicen por qué. `areaConstruida` es la suma de las áreas declaradas de los
pisos (0 sin pisos). `loteGeom` es el polígono del lote como geometría GeoJSON en EPSG:4326 (se guarda en 32718), o
`null`. El código del lote es `lote`, por eso la geometría se llama `loteGeom`. `version` cambia cuando cambia la
aritmética del motor.

**Puesta en marcha** (contra el Core del catastro, como admin):

```sh
cd model
python3 apply_roles.py           # crea o sincroniza SRTM_LECTOR (model/roles.json): READ sobre los cinco objetos
python3 configurar_region.py --region SELVA   # la región de la organización (Perené); COSTA para Ica
python3 crear_cuenta_srtm.py     # crea la cuenta de servicio `srtm` con SRTM_LECTOR e imprime clientId y clientSecret
```

`crear_cuenta_srtm.py` imprime el `clientSecret` **una sola vez**: guárdalo en el entorno de srtm-backend como
`SRTM_CATASTRO_CLIENT_ID` y `SRTM_CATASTRO_CLIENT_SECRET`. Es idempotente: si la cuenta ya existe solo le agrega el rol
si le falta y dice su `clientId`; un secreto nuevo se pide con `POST /api/service-accounts/{id}/secret` (anula el
anterior). srtm pide su token con `POST /api/auth/token {"clientId", "clientSecret"}` → `{"token", "expiresAt",
"serviceAccount"}` y lo renueva al vencer. `apply_roles.py` deja el rol exactamente con los permisos de `roles.json`
(un permiso dado a mano en el admin se pierde); los dos aceptan `--dry-run`, `--core`, `--email` y `--password`.

## Decisiones normativas

Confirmadas por la municipalidad el 2026-10-19, salvo lo que se dice abierto. D1 y D4 se investigaron el 2026-10-20.

- **D1** uso a tabla de depreciación, por prefijo del código de `usos_predio` de srtm (`uso-tabla-depreciacion.csv`, con
  la fuente de cada fila). Ninguna norma asigna usos a tablas: el RNT solo da los títulos de las Tablas 01 a 04 y dice
  «en función de su uso» (art. 13.4). Residencial a 01; comercio, depósitos, recreación e **institucional** a 02 (el
  título de la Tabla 02 dice «instituciones», y así lo tiene el padrón de Perené); oficinas, administración pública,
  financieras y gobierno extranjero a 03; salud, educación, cines, teatros, industria y talleres a 04; terreno,
  desocupado, garage y bienes comunes sin subclase a 01. Cubre los 324 códigos. **Abierto**, para la administración
  tributaria con catastro: institucional en 02 o 03, hoteles (020503), consultorios médicos (03 o 04), servicios que
  pueden ser taller u oficina, conventos y asilos. Conviene pedir el parámetro «Uso Predio – Depreciación» del SRTM del
  MEF (Exportar a Excel) y cotejarlo.
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
