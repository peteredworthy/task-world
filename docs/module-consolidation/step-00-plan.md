# Step Plan: Resolve Couplings C1–C6

## Purpose

Fix all 6 anomalous cross-layer coupling violations by relocating type definitions and introducing protocol abstractions. This establishes clean layering (no upward imports) before any file moves, preventing couplings from being silently relocated in later phases.

## Prerequisites

- None — this is the first phase. Import fixes and type relocations only.

## Functional Contract

### Inputs

- `config/global_config.py` importing `NudgerConfig` from `runners.nudger` (C1)
- `git/diff_ops.py` importing `CommitInfo`, `FileStatus`, `ModifiedFile` from `review.models` (C2)
- `state/models.py` importing `ActionLog` from `runners.action_log` (C3)
- `state/models.py` importing `EnvFileSpec` from `envfiles.models` (C4)
- `workflow/service.py` importing `RecoverResponse` from `api/schemas/runs` (C5)
- `runners/agents/user_managed/agent.py` importing `WorkflowService` directly (C6)

### Outputs

- **C1:** `NudgerConfig` defined in `config/models.py`. `runners/nudger.py` and `config/global_config.py` import from `config.models`.
- **C2:** `CommitInfo`, `FileStatus`, `ModifiedFile` defined in new `git/diff_models.py`. `review/` consumers and `git/diff_ops.py` import from `git.diff_models`.
- **C3:** `ActionLog` defined in `state/models.py`. All former `runners.action_log` importers updated.
- **C4:** `EnvFileSpec` defined in `config/models.py`. `envfiles/models.py` and `state/models.py` import from `config.models`.
- **C5:** `RecoveryResult` dataclass defined in `workflow/service.py` (or `workflow/types.py`). API router translates `RecoveryResult` → `RecoverResponse`.
- **C6:** `TaskSubmitCallback` protocol defined in `runners/types.py`. `UserManagedAgent` depends on the protocol. Injection wired in `api/deps.py`.
- All imports updated across the codebase — zero references to old import paths for relocated types.

### Error Cases

- **Circular imports after type relocation:** Moving types between layers could create import cycles. Mitigation: types move downward in the dependency graph (to config/ and state/), which cannot cause cycles.
- **Missed import paths:** A consumer still imports from the old location. Mitigation: exhaustive `grep -r` after each fix.
- **C6 protocol incomplete:** `TaskSubmitCallback` protocol doesn't cover all `WorkflowService` methods used by `UserManagedAgent`. Mitigation: audit all method calls before defining the protocol.

## Tasks

1. **C1:** Move `NudgerConfig` Pydantic model from `runners/nudger.py` to `config/models.py`. Update imports in `global_config.py` and `runners/nudger.py`.
2. **C2:** Create `git/diff_models.py` with `CommitInfo`, `FileStatus`, `ModifiedFile`. Update imports in `review/models.py`, `git/diff_ops.py`, and all consumers.
3. **C3:** Move `ActionLog` class from `runners/action_log.py` to `state/models.py`. Update or delete `runners/action_log.py`. Update all importers.
4. **C4:** Move `EnvFileSpec` from `envfiles/models.py` to `config/models.py`. Update imports in `state/models.py`, `envfiles/models.py`, and consumers.
5. **C5:** Define `RecoveryResult` dataclass in `workflow/`. Update `workflow/service.py` to return it. Update `api/routers/runs.py` to translate `RecoveryResult` → `RecoverResponse`.
6. **C6:** Define `TaskSubmitCallback` protocol in `runners/types.py`. Refactor `UserManagedAgent` to depend on the protocol. Wire injection in `api/deps.py`.
7. Run full test suite. Fix any import errors or test failures.
8. Verify with `grep -r` that no imports reference old locations for all relocated types.

## Verification Approach

### Auto-Verify

- All backend tests pass (`uv run pytest tests/unit/ -v` and `uv run pytest tests/integration/ -v`)
- All frontend tests pass (`cd ui && npx vitest run`)
- `grep -r "from orchestrator.runners.nudger import NudgerConfig" src/` returns zero results
- `grep -r "from orchestrator.review.models import" src/orchestrator/git/` returns zero results
- `grep -r "from orchestrator.runners.action_log import ActionLog" src/` returns zero results
- `grep -r "from orchestrator.envfiles.models import EnvFileSpec" src/orchestrator/state/` returns zero results
- `grep -r "from orchestrator.api.schemas" src/orchestrator/workflow/` returns zero results
- `grep -r "from orchestrator.workflow.service import WorkflowService" src/orchestrator/runners/` returns zero results

### Manual Verification

- Inspect each moved type to confirm no logic changes (pure relocation)
- Confirm `UserManagedAgent` uses protocol, not concrete `WorkflowService`
- Review `api/deps.py` for correct protocol injection wiring

## Context & References

- Plan: `docs/module-consolidation/plan.md` — Phase 0 specification
- Architecture: `docs/module-consolidation/architecture.md` — Coupling Resolutions section (C1–C6)
- Layering rules: config/state (Foundation) → db/git/envfiles (Infrastructure) → workflow (Orchestration) → runners (Execution) → api/cli (Interface)
