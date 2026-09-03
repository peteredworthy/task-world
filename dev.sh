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
    log "Stopping backend supervisor PID $BACKEND_PID"
    kill "$BACKEND_PID" 2>/dev/null || true
    local deadline=$((SECONDS + 30))
    while kill -0 "$BACKEND_PID" 2>/dev/null && [ "$SECONDS" -lt "$deadline" ]; do
      sleep 0.25
    done
    if kill -0 "$BACKEND_PID" 2>/dev/null; then
      log "Backend supervisor did not stop within 30 seconds; sending SIGKILL"
      kill -9 "$BACKEND_PID" 2>/dev/null || true
    fi
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

# Never infer ownership from a listening port and signal it. The supervised
# production-shaped launch can reclaim its own recorded child identities; this
# development launcher fails closed and asks the operator to resolve conflicts.
STALE_PIDS=$(lsof -ti :8000 2>/dev/null || true)
if [ -n "$STALE_PIDS" ]; then
  log "ERROR: Port 8000 is already owned by PID(s): $(echo $STALE_PIDS | tr '\n' ' ')"
  log "Refusing to signal processes whose identity this launcher cannot verify."
  exit 1
fi

STALE_VITE=$(lsof -ti :5173 2>/dev/null || true)
if [ -n "$STALE_VITE" ]; then
  log "ERROR: Port 5173 is already owned by PID(s): $(echo $STALE_VITE | tr '\n' ' ')"
  log "Refusing to signal processes whose identity this launcher cannot verify."
  exit 1
fi

# Backend development uses Uvicorn's reloader as its single restart owner.
# Production-shaped/manual launches omit --reload and retain durable supervision.
log "Starting development backend with reload on http://localhost:8000 ..."
(
  cd "$ROOT"
  uv run orchestrator serve --reload --no-supervisor
) > >(timestamp_stream "backend" "$BACKEND_LOG") 2>&1 &
BACKEND_PID=$!
log "Backend development reloader PID $BACKEND_PID"

# Compatibility pointers for existing debugging habits. Development output is
# captured by this script because reload deliberately bypasses the supervisor.
ln -sfn "$BACKEND_LOG" "$ROOT/server_output.log"
ln -sfn "$BACKEND_LOG" "$ROOT/server.log"

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
