#!/usr/bin/env bash
# check_test_count.sh - Detect removed tests between snapshots
#
# Usage for routine authors (opt-in auto_verify command):
#
#   1. Before the run starts, create a snapshot externally:
#        bash scripts/check_test_count.sh --snapshot /tmp/test_snapshot.txt
#
#   2. In your routine YAML, add an auto_verify item that compares:
#
#     auto_verify:
#       items:
#         - id: no-tests-removed
#           cmd: "bash scripts/check_test_count.sh --compare /tmp/test_snapshot.txt"
#           must: true
#
#   Exit codes:
#     0  - No tests removed (additions are fine)
#     1  - One or more tests were removed (removed names printed to stderr)
#     2  - pytest --collect-only failed (error output on stderr)
#
# Requirements:
#   - pytest must be available in the environment (e.g. via `uv run pytest`)
#   - The snapshot file path must be writable

set -euo pipefail

usage() {
    echo "Usage: $0 --snapshot <file>  # capture current test names to file" >&2
    echo "       $0 --compare <file>   # compare current tests with snapshot" >&2
    exit 1
}

collect_tests() {
    # Run pytest --collect-only and extract test node IDs
    # Output goes to stdout; errors to stderr
    if ! pytest --collect-only -q --no-header 2>&1 | grep '::' | sed 's/ (.*)//' | sort; then
        return 1
    fi
}

collect_tests_safe() {
    local tmpout
    tmpout=$(mktemp)
    local tmperr
    tmperr=$(mktemp)

    if ! pytest --collect-only -q --no-header >"$tmpout" 2>"$tmperr"; then
        echo "pytest --collect-only failed:" >&2
        cat "$tmperr" >&2
        cat "$tmpout" >&2
        rm -f "$tmpout" "$tmperr"
        exit 2
    fi

    # Extract lines containing '::' (test node IDs), strip trailing info like ' (fixtures used: ...)'
    grep '::' "$tmpout" | sed 's/ (.*)//' | sort
    rm -f "$tmpout" "$tmperr"
}

if [[ $# -ne 2 ]]; then
    usage
fi

MODE="$1"
FILE="$2"

case "$MODE" in
    --snapshot)
        collect_tests_safe > "$FILE"
        echo "Snapshot saved to $FILE ($(wc -l < "$FILE") tests)" >&2
        exit 0
        ;;

    --compare)
        if [[ ! -f "$FILE" ]]; then
            echo "Snapshot file not found: $FILE" >&2
            exit 2
        fi

        CURRENT=$(mktemp)
        collect_tests_safe > "$CURRENT"

        # Find tests in snapshot that are not in current (removed tests)
        REMOVED=$(comm -23 "$FILE" "$CURRENT")
        ADDED=$(comm -13 "$FILE" "$CURRENT")
        rm -f "$CURRENT"

        if [[ -n "$ADDED" ]]; then
            count=$(echo "$ADDED" | wc -l | tr -d ' ')
            echo "Tests added: $count" >&2
        fi

        if [[ -n "$REMOVED" ]]; then
            count=$(echo "$REMOVED" | wc -l | tr -d ' ')
            echo "ERROR: $count test(s) were removed:" >&2
            echo "$REMOVED" | sed 's/^/  - /' >&2
            exit 1
        fi

        echo "No tests removed." >&2
        exit 0
        ;;

    *)
        usage
        ;;
esac
