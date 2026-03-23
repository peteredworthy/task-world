#!/usr/bin/env bash
# Run the orchestrator in isolation for temporal alignment development.
# Uses a separate DB and port 9100 to avoid interfering with production at localhost:8000.
#
# Usage:
#   ./scripts/dev_isolated.sh
#
# Frontend dev server (in a separate terminal):
#   cd ui && VITE_API_PORT=9100 npm run dev -- --port 9173

set -euo pipefail

cd "$(dirname "$0")/.."

export ORCHESTRATOR_DB=orchestrator_dev.db

exec uv run uvicorn scripts.serve:app \
  --reload \
  --reload-dir src \
  --reload-dir scripts \
  --port 9100 \
  --host 0.0.0.0
