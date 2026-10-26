#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
command -v docker >/dev/null 2>&1 || { echo "Docker es necesario." >&2; exit 1; }
docker compose version >/dev/null
docker info >/dev/null
if [ "${CODESPACES:-}" = "true" ] && [ -z "${APP_ORIGIN:-}" ]; then
  : "${CODESPACE_NAME:?Codespaces no ha definido CODESPACE_NAME.}"
  : "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:?Codespaces no ha definido el dominio de puertos.}"
  export APP_ORIGIN="https://${CODESPACE_NAME}-3000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
fi
if [ -z "${DEMO_USER_PASSWORD:-}" ]; then
  export DEMO_USER_PASSWORD='test1234$'
fi
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout "${STARTUP_TIMEOUT:-180}"
docker compose exec -T backend python /app/scripts/smoke.py
docker compose exec -T backend python -c 'from dsmora_python_hello_2.web_config import settings; print(f"Entorno disponible en {settings.origin}")'
echo "Los servicios siguen ejecutandose en segundo plano."
