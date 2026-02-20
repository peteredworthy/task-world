# Step 06 Plan: Tests, Documentation, and Release Hardening

## Purpose

Finalize verification coverage and documentation updates required to ship Codex server integration with explicit quality gates that require production readiness for both local and remote variants.

## Prerequisites

- Step 02 complete: detector/type surface finalized.
- Step 03 complete: local agent implementation complete.
- Step 04 complete: remote agent implementation complete.
- Step 05 complete: executor/monitor lifecycle integration complete.

## Functional Contract

### Inputs

- Implemented code from Steps 2-5.
- Existing test suites under `tests/unit`, `tests/integration`, and relevant E2E paths.
- Documentation targets:
  - `AGENTS.md`
  - `docs/ARCHITECTURE.md`
  - Codex-server planning docs in `docs/codex-server/`

### Outputs

- Extended automated test coverage for detector behavior, Codex agent execution contract, executor branching, and API agent listing.
- Focused integration evidence for builder and verifier callback flows with both variants.
- Updated architecture and module documentation reflecting new agent modules/config/options.
- Release-readiness checklist that blocks completion until both variants meet production quality bar.

### Errors

- Coverage gaps in one variant -> release gate remains failed.
- Docs drift from implementation (missing modules/routes/config fields) -> documentation verification failure.
- Flaky integration behavior in builder/verifier phases -> block release and require stabilization.

## Tasks

1. Add/extend unit and integration tests for all Codex-specific code paths and API exposure.
2. Execute focused validation scenarios for builder/verifier lifecycle and persisted metrics/action logs.
3. Update docs and ensure release gate criteria explicitly require readiness of both variants.

## Verification

### Auto-Verify

- [ ] Targeted unit/integration suites for Codex detector/agents/executor/API pass in CI.
- [ ] Full relevant test suite passes with no Codex regressions.
- [ ] Static checks (`ruff`, `pyright`) pass for changed code.

### Manual Verify

- [ ] Review `AGENTS.md` and `docs/ARCHITECTURE.md` for complete and accurate module/route/config updates.
- [ ] Confirm release checklist explicitly blocks shipping when either `codex_server` or `codex_server_remote` is below production readiness.

## Context & References

- `docs/codex-server/step-02-plan.md`
- `docs/codex-server/step-03-plan.md`
- `docs/codex-server/step-04-plan.md`
- `docs/codex-server/step-05-plan.md`
- `AGENTS.md`
- `docs/ARCHITECTURE.md`
