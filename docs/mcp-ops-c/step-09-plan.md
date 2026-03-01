# Step Plan: Final Validation

## Purpose

Perform final validation to ensure the entire implementation is correct, all tests pass, code quality checks are clean, and no regressions were introduced. This is the last gate before the feature is considered complete.

## Prerequisites

- **Steps 1–8** complete: All schema changes, agent implementations, and integration tests are done.

## Functional Contract

### Inputs

- Complete codebase with all changes from Steps 1–8
- Full test suite (unit, integration, frontend)
- Pre-commit hooks configuration

### Outputs

- All tests pass: `uv run pytest` (unit + integration)
- Pre-commit checks pass: `uv run pre-commit run --all-files`
- No type errors, no lint errors
- No regressions in existing functionality
- Confirmation that all implementation steps are complete and verified

### Error Cases

- Test failures → investigate and fix root cause in the relevant step
- Pre-commit failures → fix formatting, linting, or type issues
- Regression in existing tests → revert or fix the offending change

## Tasks

1. Run full test suite: `uv run pytest` — all unit and integration tests pass
2. Run pre-commit checks: `uv run pre-commit run --all-files` — all checks pass
3. Run TypeScript type check and ESLint on frontend (if UI changes were made)
4. Review test coverage summary for new code paths
5. Verify backward compatibility: existing routines work unchanged
6. Final review of all changed files for code quality and security

## Verification Approach

### Auto-Verify

- `uv run pytest` exits with code 0 (all tests pass)
- `uv run pre-commit run --all-files` exits with code 0
- No new test failures compared to baseline (see MEMORY.md for test counts)
- TypeScript build passes (if applicable): `cd ui && npm run build`

### Manual Verification

- Spot-check: create a run with a routine using `available_tools` and `mcp_servers`, verify it starts correctly
- Review git diff of all changes for completeness and quality
- Confirm no TODO/FIXME items left in new code
- Verify documentation in example routines is accurate

## Context & References

- Plan: `docs/mcp-ops-c/plan.md` — Milestone 4: Integration Testing & Polish, Step 9
- Test baseline: 330 unit tests, 235 integration tests, 221 frontend tests (from MEMORY.md)
- Security: Auth tokens never in YAML/prompts/logs (verify across all agent implementations)
- Architecture: `docs/mcp-ops-c/architecture.md` — Security Considerations, Performance Considerations
