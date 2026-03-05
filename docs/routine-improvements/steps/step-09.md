# Step 9: Test count regression guard (A4)

**Milestone:** M3 — Safety Guards
**Plan:** [step-09-plan.md](../step-09-plan.md)
**Architecture:** [architecture.md](../architecture.md) — New Files table
**Intent:** [intent.md](../intent.md) — Completion Criteria #6

## Tasks

### Task 9.1: Create check_test_count.sh script

Create `scripts/check_test_count.sh` that:
1. Captures test names via `pytest --collect-only -q` before builder starts
2. Compares test list after builder finishes
3. Exits non-zero if any tests were removed, listing them on stderr

Handle edge cases: `pytest --collect-only` failure, no tests found.

**Files:** `scripts/check_test_count.sh`
**LOC estimate:** ~60
**Verify:** Script tests — remove a test → non-zero exit with removed test
listed; add a test → zero exit; no changes → zero exit; no tests → graceful
handling.

### Task 9.2: Document test regression guard for routine authors

Add documentation explaining how to use `check_test_count.sh` as an opt-in
`auto_verify` command. Note limitations (not suitable for test rename/reorg
tasks).

**Files:** `docs/` (documentation file)
**LOC estimate:** ~30
**Verify:** Manual review — documentation is clear and includes usage example.
