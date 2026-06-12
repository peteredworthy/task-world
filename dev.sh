#!/usr/bin/env bash
set -e

# Start both backend and frontend dev servers with hot-reload.
# Press Ctrl-C to stop both.

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_ROOT="${TASK_WORLD_LOG_DIR:-$ROOT/.orchestrator/logs/dev}"
RUN_LOG_DIR="$LOG_ROOT/$(date +%Y%m%d-%H%M%S)"
COMBINED_LOG="$RUN_LOG_DIR/dev.log"
BACKEND_LOG="$RUN_LOG_DIR/backend.log"
FRONTEND_LOG="$RUN_LOG_DIR/frontend.log"
SCRIPT_LOG="$RUN_LOG_DIR/script.log"

mkdir -p "$RUN_LOG_DIR"
ln -sfn "$RUN_LOG_DIR" "$LOG_ROOT/latest"

write_log_line() {
  local line="$1"
  local component_log="${2:-}"

  printf '%s\n' "$line"
  printf '%s\n' "$line" >> "$COMBINED_LOG"
  if [ -n "$component_log" ]; then
    printf '%s\n' "$line" >> "$component_log"
  fi
}

log() {
  write_log_line "[$(date '+%Y-%m-%dT%H:%M:%S%z')] [dev] $*" "$SCRIPT_LOG"
}

timestamp_stream() {
  local component="$1"
  local component_log="$2"
  local line

  while IFS= read -r line; do
    write_log_line "[$(date '+%Y-%m-%dT%H:%M:%S%z')] [$component] $line" "$component_log"
  done
}

log "Writing dev logs to $RUN_LOG_DIR"

# --- Worktree startup guard ---
# If .git is a file (not a directory), we're in a worktree — refuse to run dev.sh
if [ -f "$ROOT/.git" ]; then
    echo ""
    echo "  ERROR: dev.sh must not be run from a worktree."
        echo "  This directory ($ROOT) is a git worktree, not the main repo."
    if [ -f "$ROOT/.worktree-manifest.json" ]; then
        ASSIGNED_PORT=$(uv run python -c "import json; print(json.load(open('$ROOT/.worktree-manifest.json')).get('assigned_port','?'))" 2>/dev/null || echo "?")
        MAIN_URL=$(uv run python -c "import json; print(json.load(open('$ROOT/.worktree-manifest.json')).get('main_server_url','?'))" 2>/dev/null || echo "?")
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
  trap - EXIT INT TERM
  log "Shutting down..."
  if [ -n "${FRONTEND_SUPERVISOR_PID:-}" ]; then
    log "Stopping frontend supervisor PID $FRONTEND_SUPERVISOR_PID"
    kill "$FRONTEND_SUPERVISOR_PID" 2>/dev/null || true
  fi
  if [ -n "${BACKEND_PID:-}" ]; then
    log "Stopping backend PID $BACKEND_PID"
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
  log "Shutdown complete"
}
trap cleanup EXIT INT TERM

run_frontend_supervisor() {
  local frontend_pid=""

  shutdown_frontend() {
    if [ -n "$frontend_pid" ]; then
      kill "$frontend_pid" 2>/dev/null || true
      wait "$frontend_pid" 2>/dev/null || true
    fi
    exit 0
  }

  trap shutdown_frontend INT TERM

  while true; do
    log "Starting frontend on http://localhost:5173 ..."
    (
      cd "$ROOT/ui"
      npm run dev
    ) > >(timestamp_stream "frontend" "$FRONTEND_LOG") 2>&1 &
    frontend_pid=$!
    log "Frontend PID $frontend_pid"

    set +e
    wait "$frontend_pid"
    local status=$?
    set -e
    frontend_pid=""

    log "Frontend exited with status $status; restarting in 2 seconds..."
    sleep 2
  done
}

wait_for_backend() {
  local deadline=$((SECONDS + 60))
  log "Waiting for backend health check..."
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
      log "Backend is ready."
      return 0
    fi
    sleep 0.5
  done

  log "Backend did not become healthy within 60 seconds."
  return 1
}

# --- Kill stale uvicorn processes on port 8000 ---
# Two uvicorn processes sharing the same DB cause executor death loops:
# requests get load-balanced between them, and one has no executor for the run.
STALE_PIDS=$(lsof -ti :8000 2>/dev/null || true)
if [ -n "$STALE_PIDS" ]; then
  log "Found existing process(es) on port 8000 (PIDs: $(echo $STALE_PIDS | tr '\n' ' '))"
  log "Killing to prevent duplicate-server executor death loop..."
  echo "$STALE_PIDS" | xargs kill 2>/dev/null || true
  # Wait briefly for processes to exit
  sleep 1
  # Force-kill any that didn't respond to SIGTERM
  REMAINING=$(lsof -ti :8000 2>/dev/null || true)
  if [ -n "$REMAINING" ]; then
    log "Force-killing remaining processes: $REMAINING"
    echo "$REMAINING" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
  log "Port 8000 cleared."
fi

# --- Kill stale Vite processes on port 5173 ---
# Same issue: orphaned Vite processes hold the port, then die, leaving the UI unreachable.
STALE_VITE=$(lsof -ti :5173 2>/dev/null || true)
if [ -n "$STALE_VITE" ]; then
  log "Found existing process(es) on port 5173 (PIDs: $(echo $STALE_VITE | tr '\n' ' '))"
  log "Killing stale Vite processes..."
  echo "$STALE_VITE" | xargs kill 2>/dev/null || true
  sleep 1
  REMAINING_VITE=$(lsof -ti :5173 2>/dev/null || true)
  if [ -n "$REMAINING_VITE" ]; then
    log "Force-killing remaining: $REMAINING_VITE"
    echo "$REMAINING_VITE" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
  log "Port 5173 cleared."
fi

# Backend (FastAPI + uvicorn --reload)
log "Starting backend on http://localhost:8000 ..."
(
  cd "$ROOT"
  ORCHESTRATOR_SKIP_STALE_PORT_KILL=1 uv run orchestrator serve --reload
) > >(timestamp_stream "backend" "$BACKEND_LOG") 2>&1 &
BACKEND_PID=$!
log "Backend PID $BACKEND_PID"

if ! wait_for_backend; then
  cleanup
  exit 1
fi

# Frontend (Vite HMR, restarted if it exits unexpectedly)
run_frontend_supervisor &
FRONTEND_SUPERVISOR_PID=$!
log "Frontend supervisor PID $FRONTEND_SUPERVISOR_PID"

set +e
wait "$BACKEND_PID"
BACKEND_STATUS=$?
set -e

log "Backend exited with status $BACKEND_STATUS."
cleanup
exit "$BACKEND_STATUS"
