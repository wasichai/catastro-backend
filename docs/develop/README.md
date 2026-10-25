# Desarrollo local

Cómo preparar, iniciar y probar catastro-backend en una máquina de desarrollo. La descripción del proyecto, el modelo,
el motor y la API están en el [README principal](../../README.md); las decisiones, en los [ADRs](../adr/README.md).

## 1. Requisitos

| Herramienta | Versión | Para |
|---|---|---|
| JDK | 25 | el servidor (toolchain de Gradle) |
| Docker | cualquiera reciente | PostgreSQL con PostGIS (`compose.yml`) y los tests de integración |
| Python | 3.11+ | `model/` (solo stdlib, sin `pip install`) |
| Node y yarn | >= 26 | prettier y commitlint (`yarn install` instala el hook de husky) |
| GDAL (`ogr2ogr`) | cualquiera | solo para sacar aranceles y lotes de la geodatabase del catastro |

Las librerías de wasichai (`wasichai:wasichai-bom:1.3.0` y sus starters) se resuelven así, en este orden:

1. **GitHub Packages**. Pide un token aunque sea para leer. En `~/.gradle/gradle.properties`:
   ```properties
   gpr.user=<usuario de github>
   gpr.key=<PAT con read:packages>
   ```
   También sirven `GITHUB_ACTOR` / `GITHUB_TOKEN` en `develop/.env`.
2. **mavenLocal**, como respaldo mientras no haya una release publicada. En un checkout de
   [wasichai](https://github.com/wasichai/wasichai):
   ```bash
   cd ../wasichai && ./gradlew publishToMavenLocal -x test
   ```
   Hay que repetirlo cada vez que cambie wasichai.

## 2. Variables de entorno

```bash
cp develop/example.env develop/.env      # develop/.env está en .gitignore
```

Edita `develop/.env` si hace falta y cárgalo en el shell donde vayas a trabajar:

```bash
set -a; source develop/.env; set +a
```

| Variable | Ejemplo | Uso |
|---|---|---|
| `WASICHAI_DB_HOST` / `_PORT` / `_NAME` | `localhost` / `5434` / `catastro` | a qué PostgreSQL se conecta el servidor |
| `WASICHAI_DB_USERNAME` / `_PASSWORD` | `catastro` / `catastro` | credenciales de esa base |
| `CATASTRO_PG_PORT` | `5434` | puerto que publica `compose.yml` en `127.0.0.1`. Nunca 5432 (otra app) ni 5433 (srtm) |
| `WASICHAI_JWT_SECRET` | valor de desarrollo | firma de los tokens. Mínimo 32 bytes; en cualquier entorno real, uno propio |
| `WASICHAI_SEED_DEV` | `true` | crea el usuario `admin@wasichai.local` / `admin`. Apagarlo fuera de desarrollo |
| `WASICHAI_JWT_REVOCATION` / `WASICHAI_LOGIN_LIMIT` | comentadas (`false`) | encenderlas en un despliegue real |
| `WASICHAI_GEOSERVER_ENABLED` | `true` en el ejemplo (`false` sin variable) | solo para publicar capas WMS; los lotes salen de PostGIS sin él (ver 3.1) |
| `WASICHAI_GEOSERVER_URL` / `_USERNAME` / `_PASSWORD` | `http://localhost:8085/geoserver` / `admin` / la tuya | el REST de GeoServer y su administrador. La clave no tiene valor por defecto |
| `WASICHAI_GEOSERVER_WORKSPACE` | `catastro` | workspace de las capas (se crea solo) |
| `WASICHAI_GEOSERVER_DS_HOST` / `_PORT` / `_DATABASE` / `_USERNAME` / `_PASSWORD` | `postgres` / `5432` / `catastro` / `catastro` / `catastro` | cómo llega *GeoServer* a PostGIS (desde su contenedor, no desde tu máquina) |
| `CATASTRO_GEOSERVER_PORT` | `8085` | puerto que publica `compose.yml` para GeoServer, en `127.0.0.1` |
| `WASICHAI_CORE` | `http://localhost:8091` | URL que usan los scripts de `model/` |
| `WASICHAI_EMAIL` / `WASICHAI_PASSWORD` | el admin de desarrollo | login de esos scripts |
| `WASICHAI_TEST_DB_*` | comentadas | solo para tests de integración contra una base externa (ver 6) |

Todas tienen el mismo valor por defecto en `src/main/resources/application.yml`, así que con la base de `compose.yml`
el servidor arranca aunque no cargues nada. `develop/.env` sirve para cambiarlas sin tocar el yaml.

## 3. Base de datos

```bash
docker compose up -d          # postgis/postgis:18-3.6, contenedor catastro-postgres, 127.0.0.1:5434, base catastro
docker compose ps             # debe salir healthy
```

- Es PostgreSQL 18 con PostGIS 3.6: el módulo gis de wasichai guarda el polígono de cada lote
  (`predio_catastral.lote_geom`).
- Al arrancar, el servidor crea el esquema con las migraciones Flyway de wasichai. No hay migraciones propias: el
  modelo se crea con `model/apply.py` (ver 5).
- Para empezar de cero: `docker compose down -v`, que borra el volumen con todos los datos.

**Docker remoto.** Si `DOCKER_HOST` apunta a otro servidor, el contenedor corre allá y el puerto queda en el loopback
de ese servidor. Hace falta un túnel y dejarlo abierto:

```bash
ssh -N -L 5434:localhost:5434 <usuario>@<servidor>
```

### 3.1 GeoServer (opcional)

Publicar capas WMS (`/api/gis/layers`) necesita GeoServer; todo lo demás, incluidos los lotes, funciona sin él.

```bash
# en develop/.env: WASICHAI_GEOSERVER_ENABLED=true y WASICHAI_GEOSERVER_PASSWORD=<una clave tuya>
set -a; source develop/.env; set +a
docker compose --profile geoserver up -d         # postgis + docker.osgeo.org/geoserver:2.28.6 en 127.0.0.1:8085
docker compose ps                                # geoserver tarda ~1 min en salir healthy
curl -u "admin:$WASICHAI_GEOSERVER_PASSWORD" http://localhost:8085/geoserver/rest/about/version.json
```

- `docker compose up -d` a secas sigue levantando solo PostGIS: GeoServer va en el perfil `geoserver`.
- La clave sale de `develop/.env` y nunca se versiona. Con la variable vacía GeoServer usa su clave pública por
  defecto (`geoserver`): cárgala siempre antes de levantarlo. Sin datos de demostración (`SKIP_DEMO_DATA=true`).
- Los datos de GeoServer (workspaces, capas) viven en el volumen `geoserver-data`; `docker compose down -v` los borra.
- GeoServer llega a PostGIS por el nombre del servicio (`postgres:5432`), no por `localhost:5434`: por eso los
  `WASICHAI_GEOSERVER_DS_*` valen distinto de los `WASICHAI_DB_*`. En el CI y en otros despliegues se ajustan a
  donde corra esa base.
- Con un Docker remoto, el puerto 8085 queda en el loopback del servidor: otro túnel, `ssh -N -L 8085:localhost:8085`.

**Publicar las capas.** Con el backend corriendo (ver 4) y el modelo aplicado (ver 5). Publicar exige el permiso
`MANAGE_METADATA`; el admin de desarrollo lo tiene.

```bash
TOKEN=$(curl -s localhost:8091/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@wasichai.local","password":"admin"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -X POST localhost:8091/api/gis/layers/predio_catastral/lote_geom -H "Authorization: Bearer $TOKEN"
curl -X POST localhost:8091/api/gis/layers/tramo_via/geom             -H "Authorization: Bearer $TOKEN"
curl localhost:8091/api/gis/layers -H "Authorization: Bearer $TOKEN"       # published: true en ambas
```

También se hace desde la pantalla de administración de wasichai-ui, `/gis/layers`. Publicar crea el workspace y el
almacén PostGIS si faltan, y es idempotente. `DELETE /api/gis/layers/{objeto}/{geometría}` la retira.

**Qué devuelve `GET /api/gis/services`** (requiere READ): `enabled`, `url`, `workspace` y las tres URL base de OGC:
`wms` (`<url>/<workspace>/wms`), `wfs` (`<url>/<workspace>/wfs`) y `wmts` (`<url>/gwc/service/wmts`).

**Cómo arma un cliente las teselas WMS.** El nombre de la capa es `<workspace>:<tabla>__<columna>`
(`catastro:predio_catastral__lote_geom`, `catastro:tramo_via__geom`; `tabla` es la tabla física, que puede llevar
prefijo por organización: la lista de `/api/gis/layers` la da). Un mapa de teselas (Leaflet, OpenLayers, MapLibre)
pide por tesela, en EPSG:3857:

```
<wms>?service=WMS&version=1.3.0&request=GetMap&layers=catastro:predio_catastral__lote_geom
  &styles=&format=image/png&transparent=true&width=256&height=256&crs=EPSG:3857&bbox={bbox-epsg-3857}
```

El visor «Brechas» de catastro-ui es el consumidor: pinta las capas WMS como fuente ráster de MapLibre bajo los
lotes, con el `wmsTileUrl` de `@wasichai/gis` (la misma URL, en EPSG:3857). GeoServer corre en otro origen que el
backend, así que en un despliegue real va detrás del mismo proxy (o con CORS habilitado).

**Límite actual: sin estilo por atributo.** La capa sale con el estilo por defecto de GeoServer (un solo color).
Colorear por un atributo (la brecha, el arancel) todavía no es posible; está en
[wasichai-ui#86](https://github.com/wasichai/wasichai-ui/issues/86) y
[wasichai#134](https://github.com/wasichai/wasichai/issues/134). Mientras tanto, esos mapas usan GeoJSON.

## 4. Iniciar el backend

```bash
set -a; source develop/.env; set +a
./gradlew bootRun
curl http://localhost:8091/actuator/health       # {"status":"UP",...}
```

- El servidor escucha en `http://localhost:8091` (srtm-backend está en 8090). Se detiene con `Ctrl+C`.
- Para arrancarlo desde el IDE: la clase principal es `catastro.CatastroApplication`. Las variables de `develop/.env`
  van en la configuración de ejecución; en IntelliJ, con un plugin de EnvFile o pegándolas en *Environment variables*.
- Otra opción es el jar: `./gradlew bootJar && java -jar build/libs/app.jar`.

## 5. Modelo y datos

Con el servidor corriendo y `develop/.env` cargado. Los comandos van con `python3 -I` (ver
[ADR-008](../adr/0008-modelo-y-cargadores-en-python-stdlib.md)):

```bash
cd model
python3 -I apply.py                              # el modelo; idempotente (--diff muestra lo pendiente)
python3 -I apply_roles.py                        # SRTM_LECTOR, de roles.json
python3 -I configurar_region.py --region SELVA   # la región de la organización (Perené); COSTA para Ica
python3 -I import_fichas.py --fichas fichas.csv --pisos pisos.csv --obras obras.csv --dry-run
python3 -I import_aranceles.py --frentes frentes.csv --valores valores.csv --anio 2026 --dry-run
python3 -I import_lotes.py --geojson lotes.geojson --map codigo_municipal=COD_PRE --dry-run
python3 -I crear_cuenta_srtm.py --clave perene   # la cuenta de servicio de srtm; imprime el secreto una sola vez
```

- **Datos personales:** el levantamiento y `model/reports/` traen nombres y domicilios. No se copian al repo: `*.xlsx`,
  `*.xls` y `model/reports/` están en `.gitignore`.
- **Idempotencia:** se pueden volver a correr; solo crean lo que falta. Cada uno acepta `--dry-run`.
- Los detalles de cada cargador (columnas, mapeos, códigos de salida) están en el README, "Modelo y carga".

## 6. Tests

```bash
./gradlew build --no-daemon                  # ktlint + tests unitarios (excluye los de integración)
./gradlew ktlintFormat                       # formatea el Kotlin según .editorconfig
./gradlew compileTestKotlin                  # compila también los tests de integración, sin correrlos
./gradlew integrationTest                    # tests de integración: Testcontainers, necesita un Docker local
./gradlew integrationTest --tests 'catastro.valuacion.ValuacionesApiTest'   # una sola clase
cd model && python3 apply.py --validate-only && python3 -m unittest -v
yarn format:check                            # prettier: yaml y json, model.json incluido (yarn format lo arregla)
```

**Qué son los tests de integración.** Las clases que heredan de `WasichaiIntegrationTest` (hoy `CatastroSmokeTest` y,
a través de `CatastroApiTest`, `ValuacionesApiTest`, `TitularesApiTest` y `CambiosApiTest`), con el tag `integration`:
`build` las excluye y `integrationTest` las corre. Cada una levanta la app entera (`CatastroApplication`, en un puerto
aleatorio) contra un PostgreSQL con PostGIS (`postgis/postgis:18-3.6`, la propiedad `wasichai.test.db.image` de
`build.gradle.kts`) y la llama por HTTP, como lo hace srtm-backend.

- **`CatastroApiTest`** (`catastro`) es la base abstracta compartida de las pruebas de la API: aplica el modelo real
  (`model/model.json`, como `apply.py`) y el rol real (`model/roles.json`), deja la región en `SELVA` y da los
  ayudantes de HTTP y de registros (`registro`, `cuentaDeServicio`, `send`, `exchange`, `arbol`, `region`...) que
  cualquier prueba de la API de catastro necesita.
- **`ValuacionesApiTest`**, **`TitularesApiTest`** y **`CambiosApiTest`** heredan de `CatastroApiTest`; cada una crea
  su cuenta de servicio y llama al endpoint que prueba, con sus propios ayudantes de fichas (`predio`, `piso`,
  `leerTodo`...).
- **La base se comparte** entre todas las clases de una corrida y se conserva entre corridas: cada test crea sus
  propios registros, con códigos únicos, y no supone que la base está vacía.
- **El motor y las tablas** se prueban sin base (`ValorizacionTest`, `ValorizacionCostaTest`, `TablasTest`...), con la
  función pura del [ADR-005](../adr/0005-el-motor-es-una-funcion-pura.md). Una regla nueva del motor va primero ahí.

**En el CI.** `.github/workflows/ci.yml` corre en cada PR y en `main` cuatro jobs: *Build* (ktlint + unitarios),
*Integration tests*, *Model and importer (python)* y *Format (prettier)*. Si fallan los de Gradle, el job sube
`build/reports/tests/` como artefacto. `commits.yml` revisa con commitlint que los commits del PR sean Conventional
Commits.

**Por qué no corren en local con un Docker remoto.** Testcontainers crea el contenedor en el daemon al que apunta
`DOCKER_HOST`, pero lo busca en `localhost:<puerto publicado>`. Con un Docker remoto, el contenedor y sus puertos quedan
en ese servidor: ni Ryuk ni PostgreSQL responden en `localhost` y la suite falla al arrancar, aunque `docker info`
funcione. Entonces:

1. Lo habitual: compilarlos (`./gradlew compileTestKotlin`) y dejar que los corra el CI del PR.
2. O usar una base externa ya levantada en ese servidor y tunelizada. Descomenta `WASICHAI_TEST_DB_*` en
   `develop/.env`. Esa base debe tener PostGIS, y su nombre **debe terminar en `_test`**, porque la suite la limpia
   entera al empezar. Luego:

   ```bash
   set -a; source develop/.env; set +a
   ./gradlew integrationTest --rerun
   ```

   `--rerun` evita que la caché de Gradle devuelva un resultado verde viejo. Detalles en
   `wasichai/docs/development/getting-started.md#integration-tests`.
3. O, cuando ni siquiera hay Docker local disponible, un script de ayuda que corre gradle dentro de un contenedor de
   ese servidor, en la red de una base de pruebas ya levantada ahí, y copia el repo (sin `build/`, `.git/` ni
   `node_modules/`) hacia ese contenedor antes de cada corrida:

   ```bash
   export DOCKER_HOST=unix:///ruta/al/socket/docker.sock
   <script> <directorio-del-repo> <entorno-de-base> integrationTest --tests 'catastro.valuacion.ValuacionesApiTest'
   <script> <directorio-del-repo> <entorno-de-base> build   # build completo
   ```

   El script recibe el directorio del repo, el nombre de un entorno de base de pruebas (un archivo con las
   `WASICHAI_TEST_DB_*` de ese entorno) y los argumentos de `gradle`; no vive en este repo, cada quien lo mantiene
   junto con sus archivos de entorno.

## 7. Con srtm-backend (`../srtm-backend`)

srtm-backend lee las valuaciones de este servicio para calcular la brecha de recaudación (README, "API para srtm").
Para probarlo de punta a punta en local:

```bash
# terminal 1: este catastro, con el modelo, el rol, la región y la cuenta de srtm (ver 5)
set -a; source develop/.env; set +a
./gradlew bootRun

# terminal 2: srtm-backend, con la entrada de esta organización en su develop/.env
#   SRTM_CATASTRO_ENABLED=true
#   SRTM_CATASTRO_ORGANIZACIONES_PERENE_URL=http://localhost:8091
#   SRTM_CATASTRO_ORGANIZACIONES_PERENE_CLIENT_ID=<lo que imprimió crear_cuenta_srtm.py>
#   SRTM_CATASTRO_ORGANIZACIONES_PERENE_CLIENT_SECRET=<idem>
cd ../srtm-backend && set -a && source develop/.env && set +a && ./gradlew bootRun
```

Cada servicio tiene su propia base (`catastro` en 5434, `srtm` en 5433) y su propio admin de desarrollo.

## 8. Cómo trabajar

- **Ramas y PRs.** Una rama por cambio (`feat/...`, `fix/...`, `docs/...`) contra `main`; el PR pasa el CI antes de
  mergear.
- **Commits.** [Conventional Commits](https://www.conventionalcommits.org/) con un scope del área (`valuacion`,
  `tablas`, `model`, `api`), en castellano. El hook de husky (`yarn install`) y `commits.yml` los revisan; de ellos
  sale el CHANGELOG ([releases](releasing.md)).
- **Decisiones.** Una decisión de arquitectura o normativa nueva, o un cambio a una ya tomada, va en un ADR nuevo en
  [`docs/adr/`](../adr/README.md), en el mismo PR que la implementa.
- **Planes.** Los planes de implementación de un cambio grande van en `docs/superpowers/plans/AAAA-MM-DD-<tema>.md`,
  como en srtm-backend. `.superpowers/` (el estado local de la herramienta) no se versiona.
- **Tablas normativas.** Un archivo nuevo de `src/main/resources/tablas/` cita su fuente en las líneas `#` y lleva su
  prueba en `TablasTest` ([ADR-004](../adr/0004-tablas-normativas-como-csv-versionados.md)).
- **Motor.** Un cambio de aritmética sube `ValuacionesService.VERSION` y suma una fila a la tabla de versiones del
  README ([ADR-003](../adr/0003-valorizar-al-vuelo-sin-guardar.md)).

## Problemas comunes

| Síntoma | Causa probable |
|---|---|
| `Could not find wasichai:wasichai-spring-boot-starter…` | sin token de GitHub Packages y sin `publishToMavenLocal` (ver 1) |
| `Connection refused` a `localhost:5434` | `docker compose up -d` no corrió, o falta el túnel con Docker remoto |
| El servidor no arranca: falta `wasichai.security.jwt.secret` | `WASICHAI_JWT_SECRET` vacío en `develop/.env` |
| El servidor no arranca al cargar las tablas | un CSV de `src/main/resources/tablas/` mal formado (el error dice cuál y en qué fila) |
| `apply.py`: `connection failed` | el servidor no está en `WASICHAI_CORE` |
| `GET /api/catastro/valuaciones` responde 409 | la organización no tiene región: `configurar_region.py` ([ADR-006](../adr/0006-la-region-es-de-la-organizacion.md)) |
| Puerto 8091 ocupado | otro backend corriendo: `lsof -iTCP:8091 -sTCP:LISTEN` |
| `integrationTest` no arranca (Ryuk o PostgreSQL no responden) | un Docker remoto: Testcontainers no llega a sus puertos (ver 6) |
