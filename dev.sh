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

# --- Kill stale uvicorn processes on port 8000 ---
# Two uvicorn processes sharing the same DB cause executor death loops:
# requests get load-balanced between them, and one has no executor for the run.
STALE_PIDS=$(lsof -ti :8000 2>/dev/null || true)
if [ -n "$STALE_PIDS" ]; then
  echo "Found existing process(es) on port 8000 (PIDs: $(echo $STALE_PIDS | tr '\n' ' '))"
  echo "Killing to prevent duplicate-server executor death loop..."
  echo "$STALE_PIDS" | xargs kill 2>/dev/null || true
  # Wait briefly for processes to exit
  sleep 1
  # Force-kill any that didn't respond to SIGTERM
  REMAINING=$(lsof -ti :8000 2>/dev/null || true)
  if [ -n "$REMAINING" ]; then
    echo "Force-killing remaining processes: $REMAINING"
    echo "$REMAINING" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
  echo "Port 8000 cleared."
fi

# --- Kill stale Vite processes on port 5173 ---
# Same issue: orphaned Vite processes hold the port, then die, leaving the UI unreachable.
STALE_VITE=$(lsof -ti :5173 2>/dev/null || true)
if [ -n "$STALE_VITE" ]; then
  echo "Found existing process(es) on port 5173 (PIDs: $(echo $STALE_VITE | tr '\n' ' '))"
  echo "Killing stale Vite processes..."
  echo "$STALE_VITE" | xargs kill 2>/dev/null || true
  sleep 1
  REMAINING_VITE=$(lsof -ti :5173 2>/dev/null || true)
  if [ -n "$REMAINING_VITE" ]; then
    echo "Force-killing remaining: $REMAINING_VITE"
    echo "$REMAINING_VITE" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
  echo "Port 5173 cleared."
fi

# Backend (FastAPI + uvicorn --reload)
echo "Starting backend on http://localhost:8000 ..."
cd "$ROOT"
uv run uvicorn scripts.serve:app \
  --reload \
  --reload-dir "$ROOT/src" \
  --reload-dir "$ROOT/scripts" \
  --reload-exclude "$ROOT/scripts/experiments" \
  --port 8000 &

# Frontend (Vite HMR)
echo "Starting frontend on http://localhost:5173 ..."
cd "$ROOT/ui"
npm run dev &

wait
