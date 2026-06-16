#!/usr/bin/env bash
# Provision a fresh, isolated desktop-test working copy for one arm.
# Usage: provision.sh <arm-name>
set -euo pipefail
ARM="$1"
SRC="/Users/peter/code/desktop-test"
DEST="/Users/peter/code/comparison-arms/$ARM"

rm -rf "$DEST"
mkdir -p "$DEST"
# source only — no .git, no stale .venv, no old routines/metadata
cp "$SRC/main.py" "$DEST/"
cp "$SRC/pyproject.toml" "$DEST/"
cp "$SRC/README.md" "$DEST/" 2>/dev/null || true
cp "$SRC/.gitignore" "$DEST/" 2>/dev/null || true
cp -R "$SRC/static" "$DEST/static"

# clean seed filesystem (matches the acceptance harness seed)
mkdir -p "$DEST/desktop_fs/Documents" "$DEST/desktop_fs/Pictures"
printf 'root readme contents\n' > "$DEST/desktop_fs/readme.txt"
printf 'alpha beta gamma\n' > "$DEST/desktop_fs/Documents/notes.txt"
printf 'welcome to the desktop\n' > "$DEST/desktop_fs/Documents/welcome.txt"

# spec is the only requirements doc the arm receives
cp "/Users/peter/code/task-world/docs/graph-approach/big-comparison/spec.md" "$DEST/SPEC.md"

cd "$DEST"
git init -q
git add -A && git -c user.email=exp@local -c user.name=exp commit -qm "baseline desktop-test + SPEC" >/dev/null
# working env with test deps
uv venv -q >/dev/null 2>&1
uv pip install -q "fastapi[standard]>=0.115.0" pytest httpx >/dev/null 2>&1
echo "provisioned $DEST"
