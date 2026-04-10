# Step 9: Test count regression guard (A4)

## Milestone
M3: Safety Guards

## Purpose
Create a reusable script that detects when a builder removes existing tests. The script captures test names before and after builder work, and exits non-zero if any tests were removed. Designed as an opt-in auto_verify command for routine authors.

## Prerequisites / Dependencies
- Step 1 (auto_verify timing fix) should be complete so that auto_verify commands execute at the right time. However, the script itself can be developed independently.

## Functional Contract

### Inputs
- Working directory containing a Python project with pytest
- Environment: the script runs as an auto_verify command during the BUILDING->VERIFYING transition
- Implicitly relies on a "before" snapshot captured at task start

### Outputs
- **Exit 0:** No tests were removed (additions are fine)
- **Exit non-zero:** One or more tests were removed; stderr contains the list of removed test names

### Errors
- Non-zero exit with descriptive message listing removed tests
- If `pytest --collect-only` itself fails, exit non-zero with the pytest error

### Limitations
- Not suitable for tasks that intentionally rename or reorganize tests
- Routine authors should document this as opt-in, not default

## Files Created
- `scripts/check_test_count.sh` — the reusable script
- Documentation for routine authors on how to use it as an auto_verify command

## Verification Strategy
- **Script test:** Run against a repo with known test list, remove a test file, verify non-zero exit and correct removed test listed.
- **Script test:** Run against a repo, add a test, verify zero exit.
- **Script test:** Run against a repo with no changes, verify zero exit.
- **Edge case:** Run against a project with no tests -> handle gracefully.
