# Slice 3E implementation ledger

This ledger records the Slice 3E work on top of the intentionally preserved
recovery-stabilization worktree. Existing recovery review artifacts and the
prior Slice 3B–3D ledger are unchanged.

## Requirements covered

- Add the canonical correction decision family with no_gap,
  corrective_work, plan_revision, and escalate dispositions.
- Resolve exact failed verification/check evidence, scope, accepted plan,
  plan verification, requirements, horizon, and frozen patch budget from the
  graph projection.
- Persist the typed answer and classified-gap record together; compile
  corrective work, conservative plan amendments, or the existing human gate.
- Keep correction topology bounded to the failed declared batch and accepted
  baseline, reject unknown evidence and stale baselines, and retain duplicate
  delivery compatibility through the existing durable submission path.
- Keep executor-local _accepted_gap_planner_patch_had_ops inference on the
  legacy path only; decision-v1 gap planners use the durable answer.

## Source identity after implementation

SHA-256 hashes were captured from the worktree after the Slice 3E edits:

| Source | SHA-256 |
|---|---|
| src/orchestrator/graph/_commands.py | a94840b104d713ede40813b93676e91180c1aadd742bdd00c0ce8623ae5c47c8 |
| src/orchestrator/graph/decisions.py | 4966d8611b6ecce13214406e49da172756346327a32eeabe81e63c535785e4f5 |
| src/orchestrator/graph/models.py | 0abdfbaa38ea04a4cf2db1a1aa0606ee1cde4edf884fe7318077ee9a76016138 |
| src/orchestrator/graph/contracts.py | a52fd09b9cf88ecc53f90626bd97e9b09db56b045123efe485e9a15c6d4d9c91 |
| src/orchestrator/graph/macros.py | 8243d1b5e4cf8723b60a885715dc75040c1e95bfba2b7afa690b7419daabd494 |
| src/orchestrator/graph/commands/boundary.py | fd8fc216032573867772aa53bb5e08d30d8629d660d582cb9b9f95dd538a2028 |
| src/orchestrator/graph_runtime/dispatch.py | a4095678842108e1c0f7d8f0d22121e21f18a70cc68a34a4b90f0624de1c87d2 |
| src/orchestrator/graph_runtime/prompts.py | ccefe8981159fa7feb01baa781eb712ef39b542ad6379e30cdb6a46ca3943837 |
| src/orchestrator/graph/__init__.py | 39987d5ab0d5e5374aa38fbb88042892f7f0dc207ddbf648075421d9f1fab4f0 |
| tests/unit/test_gap_correction_decision.py | 2d32a0ab365505d8adce5a8b288c0255da15eafb51ed31cf72bb473d9b00309d |

## Verification record

Expected-failure check before implementation:

    pytest tests/unit/test_gap_correction_decision.py
    ImportError: resolve_correction_decision_context was not exported

Focused implementation checks:

    UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/unit/test_gap_correction_decision.py --override-ini='addopts='
    8 passed

    UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/unit/test_graph_decisions.py tests/unit/test_successor_amendment_decision.py tests/unit/test_gap_correction_decision.py --override-ini='addopts='
    101 passed

    UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 tests/unit/test_gap_correction_decision.py tests/integration/test_graph_decision_runtime.py --override-ini='addopts='
    21 passed

    UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check src/orchestrator/graph/decisions.py src/orchestrator/graph/models.py src/orchestrator/graph/contracts.py src/orchestrator/graph/macros.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/prompts.py src/orchestrator/graph/commands/boundary.py tests/unit/test_gap_correction_decision.py
    All checks passed!

    UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright src/orchestrator/graph/decisions.py src/orchestrator/graph/macros.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/prompts.py src/orchestrator/graph/commands/boundary.py
    0 errors, 0 warnings, 0 informations

Pre-existing focused baseline before Slice 3E edits: 106 passed across the
three decision unit/integration targets. The permanent graph boundary check
also ran on each pytest invocation and passed.

## Review notes

- Correction patch identity uses the active execution lease when available,
  yielding classified-gap-{execution_id}. This matches the existing
  execution-promised classification admission rule and makes the patch
  validator able to validate edges before finalization publishes output
  records.
- Corrective evidence provenance cites the exact failed report and checks.
- Existing legacy gap-planner patch inference remains available for legacy
  interaction contracts; it is not consulted by decision-v1 compilation or
  prompt routing.
- The full repository gate remains intentionally deferred until the complete
  recovery change is integrated and reviewed, per the target instructions.
