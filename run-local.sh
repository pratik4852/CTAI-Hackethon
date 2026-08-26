#!/usr/bin/env bash
# MEPIQ — start the API and the web app locally (macOS / Linux).
#
#   ./run-local.sh                first run: installs dependencies, then starts
#   SKIP_INSTALL=1 ./run-local.sh subsequent runs
#
# API -> http://localhost:8000   (docs at /docs)
# Web -> http://localhost:5173

set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }
command -v npm     >/dev/null || { echo "npm not found";     exit 1; }

venv="$root/backend/.venv"
py="$venv/bin/python"

if [ "${SKIP_INSTALL:-0}" != "1" ]; then
  [ -x "$py" ] || { echo "Creating virtual environment…"; python3 -m venv "$venv"; }
  echo "Installing backend dependencies…"
  "$py" -m pip install --upgrade pip --quiet
  "$py" -m pip install -r "$root/backend/requirements.txt" --quiet
  echo "Installing frontend dependencies…"
  (cd "$root/frontend" && npm install --no-audit --no-fund)
fi

# Load .env so OPENAI_API_KEY and friends reach the API process.
if [ -f "$root/.env" ]; then
  set -a; . "$root/.env"; set +a
  echo "Loaded .env"
fi
export MEPIQ_DATA_DIR="${MEPIQ_DATA_DIR:-$root/data}"

echo
echo "Starting MEPIQ"
echo "  API  http://localhost:8000  (docs at /docs)"
echo "  Web  http://localhost:5173"
echo "  Data $MEPIQ_DATA_DIR"
echo

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd "$root/backend" && "$py" -m uvicorn app.main:app --reload --port 8000) &
sleep 3
(cd "$root/frontend" && npm run dev) &

wait
