#!/usr/bin/env bash
# Backend and frontend test suites. No network required.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== backend =="
(cd backend && ../.venv/bin/pytest -q)

echo
echo "== frontend =="
npm --prefix frontend test
