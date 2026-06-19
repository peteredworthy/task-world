#!/usr/bin/env bash
# Grade one arm against the hidden acceptance oracle.
# Usage: grade.sh <armdir-abspath> [label]
set -uo pipefail
ARMDIR="$1"; LABEL="${2:-$(basename "$ARMDIR")}"
ORACLE="/Users/peter/code/task-world/docs/graph-approach/big-comparison/acceptance"
GDIR="$ARMDIR/_grade"
rm -rf "$GDIR"; mkdir -p "$GDIR"
cp "$ORACLE/conftest.py" "$ORACLE/test_acceptance.py" "$GDIR/"
cd "$ARMDIR"
# ensure pytest+httpx available in the arm env
uv pip install -q pytest httpx "fastapi[standard]>=0.115.0" >/dev/null 2>&1 || true
echo "=== GRADING $LABEL ==="
PYTHONPATH="$ARMDIR" uv run pytest "$GDIR" -q -p no:cacheprovider 2>&1 | tail -40
