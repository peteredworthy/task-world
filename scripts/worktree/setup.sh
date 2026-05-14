#!/usr/bin/env bash
# Worktree environment setup script.
# Runs automatically after the orchestrator creates or recreates a worktree.
# Called with: scripts/worktree/setup.sh <worktree-path> <main-repo-path>
#
# This script should be fast (< 10s) since it runs on every worktree creation.
# The npm cache is warm from the main repo, so npm ci --prefer-offline is ~3s.

set -euo pipefail

WORKTREE="$1"
MAIN_REPO="$2"

# Display manifest info if available
MANIFEST="$WORKTREE/.worktree-manifest.json"
if [ -f "$MANIFEST" ]; then
    MAIN_URL=$(python3 -c "import json; print(json.load(open('$MANIFEST')).get('main_server_url',''))" 2>/dev/null || true)
    ASSIGNED_PORT=$(python3 -c "import json; print(json.load(open('$MANIFEST')).get('assigned_port',''))" 2>/dev/null || true)
    if [ -n "$MAIN_URL" ]; then
        echo "Worktree setup: main server at $MAIN_URL, assigned port $ASSIGNED_PORT"
    fi
fi

# Install frontend dependencies (uses npm cache from main repo install)
if [ -f "$WORKTREE/ui/package-lock.json" ]; then
    npm ci --prefix "$WORKTREE/ui" --prefer-offline --loglevel=error
fi

# Copy graphify knowledge graph so agents can query it from the worktree.
# Only copies the essentials — skips the cache dir which can be hundreds of MB.
GRAPHIFY_SRC="$MAIN_REPO/graphify-out"
GRAPHIFY_DST="$WORKTREE/graphify-out"

if [ -d "$GRAPHIFY_SRC" ] && [ -f "$GRAPHIFY_SRC/graph.json" ]; then
    mkdir -p "$GRAPHIFY_DST"
    for f in graph.json GRAPH_REPORT.md manifest.json cost.json; do
        if [ -f "$GRAPHIFY_SRC/$f" ]; then
            cp "$GRAPHIFY_SRC/$f" "$GRAPHIFY_DST/$f"
        fi
    done
    # Re-detect Python interpreter — the worktree's venv may differ.
    GRAPHIFY_BIN=$(which graphify 2>/dev/null || true)
    if [ -n "$GRAPHIFY_BIN" ]; then
        PYTHON=$(head -1 "$GRAPHIFY_BIN" | tr -d '#!')
        case "$PYTHON" in
            *[!a-zA-Z0-9/_.-]*) PYTHON="python3" ;;
        esac
    else
        PYTHON="python3"
    fi
    "$PYTHON" -c "import sys; open('$GRAPHIFY_DST/.graphify_python', 'w').write(sys.executable)" 2>/dev/null \
        || echo "python3" > "$GRAPHIFY_DST/.graphify_python"
    echo "Worktree setup: graphify-out copied to $GRAPHIFY_DST"
else
    echo "Worktree setup: no graphify-out in main repo — agents will not have graph access"
fi
