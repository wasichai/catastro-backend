#!/usr/bin/env bash
# levanta y prueba catastro-backend + catastro-ui. se corre desde catastro-backend:
#   driver.sh up        postgis (+ túnel si docker es remoto), bootRun y yarn dev en background; espera a los dos
#   driver.sh smoke     health, ui, login por el proxy, permisos y objetos con el token
#   driver.sh ui [Link] login en el navegador y capturas (inicio + el link del menú, Mapas por defecto)
#   driver.sh down      para backend y frontend (deja postgis y el túnel)
set -euo pipefail

UI_DIR=${UI_DIR:-../catastro-ui}
RUN=${RUN:-/tmp/catastro-run}
VPS=${VPS:-jorge@vmd194233.contaboserver.net}
VPS_KEY=${VPS_KEY:-$HOME/.ssh/vps_jorge}
PG_PORT=${CATASTRO_PG_PORT:-5434}
API=http://localhost:8091
UI=http://localhost:5181
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$RUN/shots"

listening() { lsof -ti "tcp:$1" -sTCP:LISTEN >/dev/null 2>&1; }

wait_for() { # $1 label, $2 log, $3 ready regex, $4 fail regex
  for _ in $(seq 1 240); do
    if grep -qE "$3" "$2"; then echo "ok $1"; return; fi
    if grep -qE "$4" "$2"; then echo "FAIL $1, see $2:"; grep -m3 -E 'Caused by|error' "$2"; exit 1; fi
    sleep 1
  done
  echo "FAIL $1: timeout, see $2"; exit 1
}

up() {
  docker compose up -d
  # DOCKER_HOST is the vps socket over ssh: compose's 127.0.0.1:5434 is the vps loopback, not ours
  if ! nc -z localhost "$PG_PORT" 2>/dev/null; then
    [ -n "${DOCKER_HOST:-}" ] || { echo "FAIL postgis is not on localhost:$PG_PORT"; exit 1; }
    ssh -fN -i "$VPS_KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o ServerAliveInterval=30 \
      -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -L "$PG_PORT:localhost:$PG_PORT" "$VPS"
  fi
  nc -z localhost "$PG_PORT" && echo "ok postgis localhost:$PG_PORT"

  # rm, not truncate: a gradle killed by down keeps its fd and would write its BUILD FAILED into the new log
  if listening 8091; then echo "ok backend already up"; else
    rm -f "$RUN/backend.log"
    nohup ./gradlew bootRun >"$RUN/backend.log" 2>&1 &
    wait_for backend "$RUN/backend.log" 'Started CatastroApplicationKt' 'Application run failed|BUILD FAILED'
  fi
  if listening 5181; then echo "ok frontend already up"; else
    rm -f "$RUN/frontend.log"
    (cd "$UI_DIR" && nohup yarn dev >"$RUN/frontend.log" 2>&1 &)
    wait_for frontend "$RUN/frontend.log" 'ready in' 'error|Port 5181 is in use'
  fi
}

check() { # $1 label, $2 expected code, rest curl args
  local label=$1 want=$2; shift 2
  local got; got=$(curl -s -o "$RUN/last.json" -w '%{http_code}' "$@")
  if [ "$got" = "$want" ]; then echo "ok $label ($got)"; else echo "FAIL $label: $got, want $want"; head -c 300 "$RUN/last.json"; echo; exit 1; fi
}

smoke() {
  check health 200 "$API/actuator/health"
  check ui 200 "$UI/"
  check 'api without session' 401 "$UI/api/objects"
  check login 200 -X POST "$UI/api/auth/login" -H 'Content-Type: application/json' \
    -d '{"email":"admin@wasichai.local","password":"admin"}'
  local token; token=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "$RUN/last.json")
  check permissions 200 -H "Authorization: Bearer $token" "$UI/api/auth/me/permissions"
  check objects 200 -H "Authorization: Bearer $token" "$UI/api/objects"
  python3 -c 'import json,sys; print("   objects:", ", ".join(o["name"] for o in json.load(open(sys.argv[1]))))' "$RUN/last.json"
}

ui() {
  # playwright from the npx cache; the script is cjs so NODE_PATH reaches it
  SHOTS="$RUN/shots" npx -y -p playwright@1.60.0 sh -c 'NODE_PATH="$(dirname "$(dirname "$(command -v playwright)")")" node "$0" "$@"' \
    "$HERE/ui.cjs" "${1:-Mapas}"
}

down() {
  for port in 8091 5181; do lsof -ti "tcp:$port" -sTCP:LISTEN | xargs kill 2>/dev/null || true; done
  for _ in $(seq 1 30); do listening 8091 || listening 5181 || break; sleep 1; done
  echo "ok stopped 8091 and 5181"
}

"${1:?usage: driver.sh up|smoke|ui [Link]|down}" "${@:2}"
