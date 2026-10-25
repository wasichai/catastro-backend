---
name: run-catastro
description: Levantar catastro-backend (Spring, puerto 8091) y catastro-ui (Vite, puerto 5181) en local contra el PostGIS que corre en el VPS, y comprobar que responden.
---

# Levantar backend y frontend

Docker no es local: `DOCKER_HOST=unix:///tmp/docker.sock` es el socket del VPS (`vmd194233.contaboserver.net`) reenviado
por SSH. `docker compose up -d` crea el contenedor allá, y el `127.0.0.1:5434` del `compose.yml` es el loopback del VPS,
no el de la Mac. Sin un túnel para el 5434, `bootRun` falla con `Connection to localhost:5434 refused` (Flyway, bean
`wasichaiMigrations`), aunque `docker ps` muestre el contenedor `healthy`.

## 1. Base de datos

```sh
docker compose up -d   # catastro-postgres; si ya dice Running, está bien
nc -z localhost 5434 || /usr/bin/ssh -fN -i ~/.ssh/vps_jorge -o IdentitiesOnly=yes -o BatchMode=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
  -L 5434:localhost:5434 jorge@vmd194233.contaboserver.net
nc -z localhost 5434   # tiene que conectar antes de seguir
```

Si `DOCKER_HOST` no está definido (Docker local de verdad), el túnel sobra: el 5434 ya está en la Mac.

## 2. Backend y frontend

Los dos en background, con el log en un archivo:

```sh
./gradlew bootRun > backend.log 2>&1                 # desde catastro-backend
(cd ../catastro-ui && yarn dev > frontend.log 2>&1)  # Vite en 5181, proxy de /api al 8091 (WASICHAI_API_URL)
```

El backend está listo cuando `backend.log` tiene `Started CatastroApplicationKt`; si dice `Application run failed`,
mira el primer `Caused by`. Vite está listo con `ready in` y `Local: http://localhost:5181/`.

## 3. Comprobar

```sh
curl -s http://localhost:8091/actuator/health                  # {"status":"UP",...}
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5181/      # 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5181/api/  # 401: el proxy llega al backend, sin sesión
```

Usuario de desarrollo: `admin@wasichai.local` / `admin` (seed con `WASICHAI_SEED_DEV=true`, el valor por defecto).
