#!/usr/bin/env bash
# One-time setup: Python venv, backend deps, frontend deps, and a .env to fill in.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"

[ -d .venv ] || "$PYTHON" -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e './backend[test]'

npm --prefix frontend install

if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo "Created .env — add GROQ_API_KEY and SERPAPI_API_KEY,"
  echo "or set MOCK_PROVIDERS=true to run without any keys."
fi

echo
echo "Setup complete. Start the app with: ./scripts/dev.sh"
