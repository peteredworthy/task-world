#!/usr/bin/env bash
set -e

# Start both backend and frontend dev servers with hot-reload.
# Press Ctrl-C to stop both.

ROOT="$(cd "$(dirname "$0")" && pwd)"

cleanup() {
  echo ""
  echo "Shutting down..."
  kill 0 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

# Backend (FastAPI + uvicorn --reload)
echo "Starting backend on http://localhost:8000 ..."
cd "$ROOT"
uv run uvicorn scripts.serve:app \
  --reload \
  --reload-dir "$ROOT/src" \
  --reload-dir "$ROOT/scripts" \
  --port 8000 &

# Frontend (Vite HMR)
echo "Starting frontend on http://localhost:5173 ..."
cd "$ROOT/ui"
npm run dev &

wait
