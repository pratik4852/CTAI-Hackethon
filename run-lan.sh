#!/usr/bin/env bash
# MEPIQ — serve on this machine's LAN address so others can reach it.
#
#   ./run-lan.sh            start and print the shareable URL
#   ./run-lan.sh stop       stop the stack
#
# Docker already binds 0.0.0.0, and the frontend calls the API on whatever host
# the browser used, so nothing needs rebuilding when the address changes.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ "${1:-}" = "stop" ]; then
  docker compose down
  echo "Stopped. Uploads and results are preserved in the mepiq-data volume."
  exit 0
fi

command -v docker >/dev/null || { echo "Docker not found on PATH."; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker daemon is not running."; exit 1; }

[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example."; }

env_value() { grep -E "^\s*$1\s*=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' | xargs || true; }
WEB_PORT="$(env_value MEPIQ_WEB_PORT)"; WEB_PORT="${WEB_PORT:-8080}"
API_PORT="$(env_value MEPIQ_API_PORT)"; API_PORT="${API_PORT:-8000}"
BIND="$(env_value MEPIQ_BIND)";         BIND="${BIND:-0.0.0.0}"

[ "$BIND" = "127.0.0.1" ] && echo "WARNING: MEPIQ_BIND=127.0.0.1 — other machines will not be able to connect."

lan_ip() {
  if command -v ip >/dev/null 2>&1; then
    ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}'
  elif command -v ipconfig >/dev/null 2>&1; then
    ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null
  fi
}
IP="$(lan_ip)"; IP="${IP:-<this-machine-ip>}"

echo "Starting MEPIQ…"
docker compose up -d --build

printf "Waiting for the API"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${API_PORT}/api/health" >/dev/null 2>&1; then ok=1; break; fi
  printf "."; sleep 2
done
echo

if [ "${ok:-}" != "1" ]; then
  echo "The API did not report healthy. Check: docker compose logs -f api"
  exit 1
fi

HEALTH="$(curl -fsS "http://127.0.0.1:${API_PORT}/api/health")"
case "$HEALTH" in *'"llm_enabled":true'*) COPILOT="LLM copilot";; *) COPILOT="rule-based copilot (no OPENAI_API_KEY set)";; esac

cat <<EOF

  MEPIQ is running
  ----------------------------------------------------
  Share this with anyone on the same network:
     http://${IP}:${WEB_PORT}

  On this machine:  http://localhost:${WEB_PORT}
  API docs:         http://${IP}:${API_PORT}/docs
  Copilot:          ${COPILOT}
  ----------------------------------------------------

  Stop with:  ./run-lan.sh stop
  Logs with:  docker compose logs -f
EOF
