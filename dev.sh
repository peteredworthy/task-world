#!/usr/bin/env bash
set -e

# Start both backend and frontend dev servers with hot-reload.
# Press Ctrl-C to stop both.

ROOT="$(cd "$(dirname "$0")" && pwd)"

# --- Worktree startup guard ---
# If .git is a file (not a directory), we're in a worktree — refuse to run dev.sh
if [ -f "$ROOT/.git" ]; then
    echo ""
    echo "  ERROR: dev.sh must not be run from a worktree."
    echo "  This directory ($ROOT) is a git worktree, not the main repo."
    if [ -f "$ROOT/.worktree-manifest.json" ]; then
        ASSIGNED_PORT=$(python3 -c "import json; print(json.load(open('$ROOT/.worktree-manifest.json')).get('assigned_port','?'))" 2>/dev/null || echo "?")
        MAIN_URL=$(python3 -c "import json; print(json.load(open('$ROOT/.worktree-manifest.json')).get('main_server_url','?'))" 2>/dev/null || echo "?")
        echo "  Main server: $MAIN_URL"
        echo "  Assigned port for this worktree: $ASSIGNED_PORT"
        echo ""
        echo "  If you need a server here, run:"
        echo "    uv run uvicorn scripts.serve:app --port $ASSIGNED_PORT"
    fi
    echo ""
    exit 1
fi

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
