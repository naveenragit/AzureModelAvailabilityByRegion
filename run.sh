#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8765}"
VENV=".venv"

if [ ! -d "$VENV" ]; then
  echo "Creating virtualenv at $VENV"
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --upgrade pip >/dev/null
pip install -r backend/requirements.txt

echo ""
echo "Make sure you've run 'az login' so DefaultAzureCredential can pick up your account."
echo "Starting on http://localhost:$PORT"

(sleep 1 && (xdg-open "http://localhost:$PORT" 2>/dev/null || open "http://localhost:$PORT" 2>/dev/null || true)) &
exec python -m uvicorn backend.main:app --host 127.0.0.1 --port "$PORT"
