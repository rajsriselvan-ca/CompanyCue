#!/usr/bin/env sh
set -eu

if [ ! -x .venv/bin/uvicorn ] || [ ! -d frontend/node_modules ]; then
  printf '%s\n' 'Dependencies are missing. Run: make install'
  exit 1
fi

cleanup() {
  kill "$api_pid" "$web_pid" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload &
api_pid=$!
npm --prefix frontend run dev &
web_pid=$!

wait "$api_pid" "$web_pid"
