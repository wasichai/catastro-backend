# catastro-backend

Valorización catastral de los predios de la Municipalidad Distrital de Perené (ubigeo 120302), sobre el framework
[wasichai](https://github.com/wasichai/wasichai) 1.2.0.

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
srtm-backend. Cuatro objetos: `predio_catastral` (llave `codigo_municipal`, igual a `predio.codigo` de srtm),
`construccion` y `obra_complementaria` (cuelgan de un predio) y `arancel`. wasichai no tiene únicos compuestos, así que
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
siete columnas con el nombre del campo. Un predio que el Core ya tiene se salta; los pisos (llave predio y piso) y las obras
(llave predio, `codigo_vu` y año de construcción) se crean solo si faltan, así que una carga que falló a medias se
completa volviendo a correrla. Una llave repetida en el archivo es un error.

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

## Tablas normativas

Las tablas con que se valoriza viven en `src/main/resources/tablas/` y se cargan una vez al arrancar
(`catastro.tablas.Tablas`, bean de `TablasConfig`); un archivo mal formado hace fallar el arranque. Cada archivo abre con
líneas `#` que citan su fuente; las filas van tal como en la fuente. Las rutas de normativa son relativas a
`normativa/docs/10-negocio/valores-normativos/`.

| Archivo | Contenido | Fuente |
|---|---|---|
| `valores-unitarios-selva-2026.csv` | 30 celdas: 3 partidas × categorías A a J, en S/ por m² techado. `valor_m2` vacío es una celda `.....` (sin valor, no cero) | R.M. N.° 277-2025-VIVIENDA, Anexo I.4 Selva (`valores-unitarios-2026.md` §1.5.3) |
| `depreciacion-rnt-2016.csv` | 492 filas de las tablas 01 a 04, copia exacta (sha256 verificado en las pruebas). Las 36 celdas `*` no tienen fila; `antiguedad_hasta` vacío es «más de 50» | Reglamento Nacional de Tasaciones, Anexo I (`fuentes/depreciacion-rnt-2016/depreciacion.csv`) |
| `obras-complementarias-selva-2026.csv` | 96 partidas a costo directo, copia exacta de `model/data/obras_complementarias.csv` de srtm-backend. Llave `TIPO DE OBRA\|número`, la de `obra_complementaria.codigo_vu` | R.M. N.° 277-2025-VIVIENDA, Anexo III.4 Selva |
| `uso-tabla-depreciacion.csv` | prefijo del código de `usos_predio` de srtm → tabla del RNT; gana el prefijo más largo. Editable | decisión D1 (por confirmar) |
| `parametros.csv` | `FACTOR_OFICIALIZACION` 0.68, `PORCENTAJE_ACTUALIZACION` 0, `INCREMENTO_PISO_DESDE` 5 y `INCREMENTO_PISO_PORCENTAJE` 5, de 2026, cada uno con su fuente | `obras-complementarias-y-oficializacion-2026.md` §1.2, `predial-porcentaje-de-actualizacion.md` §1.6, `valores-unitarios-2026.md` §1.3 y §1.6 |

`Tablas` responde con el vocabulario de la fuente (material `Concreto`, `Ladrillo`, `Liviano/Adobe`; estado `Muy Bueno`,
`Bueno`, `Regular`, `Malo`): llevar a él los enums del catastro (D2, D3) es cosa del motor de valorización. Una celda
`.....` o `*` devuelve nulo, nunca cero. Los códigos de clase `090000`, `100000` y `100400` de `usos_predio` no tienen
tabla (son agrupadores sin uso concreto).

## Decisiones normativas por confirmar

Valores por defecto adoptados hasta que la municipalidad los confirme. Todas están por confirmar.

- **D1** uso a tabla de depreciación, por prefijo del código de `usos_predio` de srtm: residencial a 01, comercio y
  depósitos a 02, oficinas a 03, salud, educación, industria y talleres a 04. CSV editable.
- **D2** material: CONCRETO a Concreto, LADRILLO a Ladrillo, todo lo demás a la columna Adobe/Liviano.
- **D3** estado MUY MALO se trata como Malo; las celdas `*` (ausentes en `depreciacion.csv`) toman el último
  porcentaje publicado de su fila.
- **D4** se suman las 3 partidas de Selva (muros y columnas, techos, puertas y ventanas).
- **D5** las celdas `.....` no son cero: el predio recibe un `motivo` (sin valor).
- **D6** porcentaje de actualización 2026 = 0.
- **D7** llave de cruce catastro y srtm: código municipal (= `predio.codigo` de srtm), luego `codigo_cpu`, luego
  (sector, manzana, lote).
- **D8** deducción Amazonía: parámetro anual de srtm; no se aplica por defecto (primero se revisa la deducción del
  padrón).
- **D9** obras complementarias: VU × cantidad × 0.68 × (1 − dep%), con la tabla del predio y el material, estado y
  antigüedad propios de la obra.
- **D10** COINCIDE cuando |Δ autoavalúo| <= 5 %.
- **D11** solo el año 2026.
- **D12** varias secuencias de uso: el valor del catastro se reparte proporcional al autoavalúo declarado de cada una
  (si no hay, por área construida).

Además: +5 % al VU por piso cuando piso >= 5 (documento de VU, §1.6), aplicado antes de la depreciación.
