#!/usr/bin/env bash
# post-deploy checks of the protected WMS, against the public origin of catastro-ui (README, «WMS protegido»).
# exits 0 when every check gives its status, 1 otherwise. the tokens go to curl through stdin, never in argv, and are
# never printed.
#
#   docs/deploy/smoke-wms.sh <base-url> <own-layer> <other-org-layer>
#   WMS_BASE_URL=https://catastro.example WMS_CAPA_PROPIA=catastro:tramo_via__7c45fb26__geom \
#     WMS_CAPA_AJENA=catastro:tramo_via__0a1b2c3d__geom docs/deploy/smoke-wms.sh
#
# tokens, in the environment only: WMS_TOKEN_PROPIO (a user of the layer's organization with READ on it) and
# WMS_TOKEN_AJENO (a user of the other organization). get one with POST /api/auth/login, for example
#   read -rs WMS_TOKEN_PROPIO; export WMS_TOKEN_PROPIO
# optional: WMS_WORKSPACE (catastro), WMS_BBOX (EPSG:3857, Perené by default)
set -uo pipefail

base=${1:-${WMS_BASE_URL:-}}
propia=${2:-${WMS_CAPA_PROPIA:-}}
ajena=${3:-${WMS_CAPA_AJENA:-}}
workspace=${WMS_WORKSPACE:-catastro}
bbox=${WMS_BBOX:--8430000,-1240000,-8420000,-1230000}
if [[ -z $base || -z $propia || -z $ajena || -z ${WMS_TOKEN_PROPIO:-} || -z ${WMS_TOKEN_AJENO:-} ]]; then
  echo "uso: WMS_TOKEN_PROPIO=... WMS_TOKEN_AJENO=... $0 <base-url> <capa-propia> <capa-ajena>" >&2
  exit 2
fi
base=${base%/}
wms="$base/geoserver/$workspace/wms"

getmap() {
  echo "$wms?service=WMS&version=1.1.1&request=GetMap&styles=&layers=$1&bbox=$bbox&width=256&height=256&srs=EPSG:3857&format=image/png&transparent=true"
}

fallos=0
# $1 what is checked, $2 the expected "status" or "status content-type", $3 the token's variable name (or -), $4...
# curl's own arguments. the Authorization header goes in a curl config read from stdin
revisar() {
  local que=$1 esperado=$2 token=$3
  shift 3
  local config=""
  [[ $token != - ]] && config="header = \"Authorization: Bearer ${!token}\""
  local obtenido
  obtenido=$(printf '%s\n' "$config" | curl -sS -K - -o /dev/null --max-time 30 -w '%{http_code} %{content_type}' "$@" 2>/dev/null)
  obtenido=${obtenido:-sin respuesta}
  # "200 image/png" compares the status and the type (without its parameters), "403" the status alone
  local visto=${obtenido%% *}
  [[ $esperado == *" "* ]] && visto=${obtenido%%;*}
  if [[ $visto == "$esperado" ]]; then
    echo "ok     $que: $obtenido"
  else
    echo "FALLA  $que: se esperaba $esperado, llegó $obtenido"
    fallos=$((fallos + 1))
  fi
}

revisar "GetMap de su capa" "200 image/png" WMS_TOKEN_PROPIO "$(getmap "$propia")"
revisar "sin token" 401 - "$(getmap "$propia")"
revisar "capa de otra organización" 403 WMS_TOKEN_PROPIO "$(getmap "$ajena")"
revisar "lista con una capa de otra organización" 403 WMS_TOKEN_PROPIO "$(getmap "$propia,$ajena")"
revisar "la otra organización, esta capa" 403 WMS_TOKEN_AJENO "$(getmap "$propia")"
revisar "GetCapabilities" 403 WMS_TOKEN_PROPIO "$wms?service=WMS&request=GetCapabilities"
revisar "POST" 403 WMS_TOKEN_PROPIO -X POST "$(getmap "$propia")"
revisar "/geoserver/rest" 404 WMS_TOKEN_PROPIO "$base/geoserver/rest/about/version.json"
revisar "/geoserver/web" 404 WMS_TOKEN_PROPIO "$base/geoserver/web/"
revisar "/geoserver/wfs" 404 WMS_TOKEN_PROPIO "$base/geoserver/wfs?service=WFS&request=GetCapabilities"

if ((fallos > 0)); then
  echo "$fallos revisiones fallaron"
  exit 1
fi
echo "todas las revisiones pasaron"
