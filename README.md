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
