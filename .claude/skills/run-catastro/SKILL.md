---
name: run-catastro
description: Levantar, correr, parar y probar catastro-backend (Spring, 8091) junto con catastro-ui (Vite, 5181) en local, y sacar capturas de la UI con login. Usar cuando pidan iniciar/arrancar el backend o el front, hacer un smoke test de la API, entrar a la UI o tomar un screenshot.
---

# Correr catastro-backend + catastro-ui

Todo pasa por `.claude/skills/run-catastro/driver.sh` (las rutas son relativas a `catastro-backend/`): levanta PostGIS,
el backend y el front, prueba la API con `curl` y maneja la UI con Playwright sobre el Google Chrome instalado. La UI
está en `../catastro-ui`.

Login de desarrollo: `admin@wasichai.local` / `admin` (seed con `WASICHAI_SEED_DEV=true`, el valor por defecto).

## Run (agent path)

```sh
.claude/skills/run-catastro/driver.sh up       # postgis + túnel si hace falta, bootRun y yarn dev en background (~10 s)
.claude/skills/run-catastro/driver.sh smoke    # health, ui, 401 sin sesión, login, permisos y objetos con el token
.claude/skills/run-catastro/driver.sh ui       # login en el navegador, capturas de Inicio y de Mapas
.claude/skills/run-catastro/driver.sh ui Objetos   # otra pantalla: el texto del link en el menú
.claude/skills/run-catastro/driver.sh down     # para 8091 y 5181 (postgis y el túnel quedan)
```

Cada paso imprime `ok …` o `FAIL …` y sale con un código distinto de 0 si falla. `up` no relanza lo que ya escucha.

| qué      | dónde                                                                                 |
| -------- | ------------------------------------------------------------------------------------- |
| logs     | `/tmp/catastro-run/backend.log`, `/tmp/catastro-run/frontend.log`                     |
| capturas | `/tmp/catastro-run/shots/inicio.png` y `<link>.png`                                   |
| errores  | `ui` sale con 1 si hubo errores de consola, `pageerror` o respuestas ≥ 400 (con la url) |

`ui` usa `npx -y -p playwright@1.60.0` y `channel: 'chrome'`, así que no descarga Chromium. Mira las capturas: el
menú lateral con «Catastro Perené» y la tarjeta de 5 objetos indican que el login y la API funcionan.

## Run (human path)

```sh
docker compose up -d && ./gradlew bootRun        # http://localhost:8091
cd ../catastro-ui && yarn dev                    # http://localhost:5181, proxy de /api al 8091
```

Sin el túnel de abajo, `bootRun` no llega a la base.

## Gotchas

- **Docker está en el VPS, no en la Mac.** `DOCKER_HOST=unix:///tmp/docker.sock` es el socket de
  `vmd194233.contaboserver.net` reenviado por SSH. El `127.0.0.1:5434` de `compose.yml` es el loopback del VPS: `docker ps`
  muestra `catastro-postgres` como `healthy`, pero en la Mac nada escucha en el 5434. `up` abre
  `ssh -fN -L 5434:localhost:5434` con `~/.ssh/vps_jorge` (ese `ssh` no se reconecta; si se cae, `up` lo vuelve a abrir).
- **`down` y `up` seguidos.** El Gradle de un `bootRun` matado sigue vivo unos segundos y escribe `BUILD FAILED … exit
  value 143` en el log que tiene abierto. Si `up` solo truncara el log, leería ese fallo como propio; por eso lo borra
  antes de arrancar.
- **favicon.ico da 404**: la UI no tiene favicon y `ui` lo ignora. Chrome registra los 404 en la consola sin la url
  («Failed to load resource»), así que `ui` los reporta desde las respuestas.
- **El mapa muestra «0 entidades» y está centrado en Lima**: la base de desarrollo no tiene lotes cargados (ver
  `import_lotes.py` en el README).

## Troubleshooting

- **`Connection to localhost:5434 refused`** (Flyway, bean `wasichaiMigrations`, `Application run failed`): falta el
  túnel. `driver.sh up` lo abre; a mano, el `ssh -fN -L 5434:…` de arriba.
- **`FAIL backend` con `exit value 143`** en el log: es el `bootRun` anterior, que todavía estaba muriendo. Vuelve a
  correr `driver.sh up`.
