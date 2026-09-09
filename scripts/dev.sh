#!/usr/bin/env bash
# Starts the API and the web app together, and stops both on Ctrl-C.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/uvicorn ] || [ ! -d frontend/node_modules ]; then
  echo "Dependencies are missing. Run: make install" >&2
  exit 1
fi

cleanup() {
  trap - EXIT INT TERM
  [ -n "${api_pid:-}" ] && kill "$api_pid" 2>/dev/null || true
  [ -n "${web_pid:-}" ] && kill "$web_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

.venv/bin/uvicorn app.main:app \
  --app-dir backend --host 127.0.0.1 --port 8000 --reload &
api_pid=$!

npm --prefix frontend run dev &
web_pid=$!

echo
echo "  CompanyCue"
echo "  app  http://localhost:5173"
echo "  api  http://localhost:8000/docs"
echo

while kill -0 "$api_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 1
done
