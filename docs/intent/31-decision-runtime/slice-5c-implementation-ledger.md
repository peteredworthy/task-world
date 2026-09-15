# Slice 5C implementation ledger

Status: implemented and validated.

Scope: deterministic recovery and exact-owner cleanup for decision-runtime
executions. Existing reviewed Slice 1–5B changes are preserved in this
worktree; this ledger records only Slice 5C work. No live server, database,
activation, paid model execution, or commit is authorized.

| ID | Required behavior | Acceptance evidence | Status | Remaining gap |
|---|---|---|---|---|
| S5C-1 | Infrastructure/process failure enters bounded deterministic recovery and cleanup. | Recovery-dispatch and managed-cleanup integration suites pass with real Git/SQLite, covering restoration, lease closure, retry, terminal failure, restart and at-least-once cleanup. | complete | None. |
| S5C-2 | Semantic correction is allowed only with diagnostic evidence, applicable inputs, and remaining allowance. | Recovery tests reject evidence-free and exhausted corrections; a bound candidate with diagnostic evidence retains its snapshot and schedules only the permitted legacy retry. Decision-v1 corrections fail closed after the execution returns. | complete | None. |
| S5C-3 | Exhaustion stops dispatch; runner/model changes require explicit selection. | Exhausted recovery emits terminal failure without `runtime_retry_scheduled`; decision-v1 runner/recovery paths do not automatically redispatch or substitute a runner/model. | complete | None. |
| S5C-4 | Last accepted baseline is restored while rejected candidates remain inspectable. | Real Git/SQLite recovery tests verify baseline restoration, retained staged/recovery snapshot evidence, and the decision-v1 candidate-check path never completes through `accepted_graph_patch_before_agent_death`. | complete | None. |
| S5C-5 | Repeated restart preserves ownership, counters, evidence, and exact-owner cleanup. | Recovery-dispatch and managed-cleanup suites cover redelivery/restart idempotency, stable attempt state and evidence, process/worktree lock ownership, and expected-ref/tree/commit owner checks. | complete | None. |

Malformed decision applicability is treated as decision-owned for recovery
purposes: it cannot enable the legacy accepted-patch shortcut or automatic
retry. Likewise, `invalid_planner_proposal` with a retry flag but without a
diagnostic and retained candidate now terminates failed. The correction
regressions passed in the focused `50 passed` suite.

## Starting evidence

- Baseline validation: `docs/reviews/recovery-successor-validation-result.json`.
- Slice 5B ledger: `slice-5b-implementation-ledger.md`.
- Baseline focused command: `UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q tests/integration/test_graph_runner_recovery_dispatch.py tests/integration/test_graph_startup_recovery.py tests/unit/test_graph_recovery_selection.py tests/unit/test_startup_recovery.py --override-ini='addopts=' --tb=short`.
- Baseline result: `12 passed, 15 skipped in 1.47s`.

## Implementation and validation manifest

```text
Changed implementation files:
- `src/orchestrator/graph/commands/boundary.py` — recovery disposition now
  requires diagnostic/candidate evidence for semantic correction and makes
  decision-v1 infrastructure recovery terminal; the existing legacy accepted
  patch shortcut remains limited to legacy applicability.
- `src/orchestrator/graph_runtime/dispatch.py` — decision-v1 rejection and
  cancellation paths never request automatic recovery redispatch; advisory and
  legacy submission repair remain unchanged.
- `tests/integration/test_graph_runner_recovery_dispatch.py` — evidence,
  allowance and exhaustion recovery cases.
- `tests/integration/test_graph_decision_runtime.py` — decision-v1 candidate
  rejection proves no automatic redispatch for Codex Server and CLI paths.

The Slice 5C change removes no prior recovery implementation or evidence. It
reuses the existing attempt identity, recovery snapshot, cleanup outbox and
legacy completion predicate rather than adding a second recovery mechanism.

VALIDATION
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest --run-slow -q tests/integration/test_graph_runner_recovery_dispatch.py --override-ini='addopts=' --tb=short
# 16 passed in 19.33s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q tests/integration/test_graph_decision_runtime.py tests/unit/test_failure_diagnostics.py --override-ini='addopts=' --tb=short
# 83 passed, 9 warnings in 266.15s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest --run-slow -q tests/integration/test_graph_managed_snapshot_cleanup.py --override-ini='addopts=' --tb=short
# 13 passed in 17.71s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q tests/integration/test_graph_startup_recovery.py tests/unit/test_graph_recovery_selection.py tests/unit/test_startup_recovery.py --override-ini='addopts=' --tb=short
# 12 passed, 2 skipped in 1.43s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q tests/unit/test_cli_agent_commit_retry.py tests/unit/test_codex_server_transport.py --override-ini='addopts=' --tb=short
# 52 passed, 1 skipped in 0.78s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check src/orchestrator/graph/commands/boundary.py src/orchestrator/graph_runtime/dispatch.py tests/integration/test_graph_runner_recovery_dispatch.py tests/integration/test_graph_decision_runtime.py tests/unit/test_failure_diagnostics.py
# All checks passed!

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright src/orchestrator/graph/commands/boundary.py src/orchestrator/graph_runtime/dispatch.py
# 0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python scripts/check_graph_projection_boundaries.py
# passed

git diff --check
# passed

SOURCE HASHES
START (Slice 5B reviewed finals)
a092a513d4564196d638393b65853119835d5f521d4ba85e92cab50c21ae4f8a  src/orchestrator/graph/commands/boundary.py
d4a6ae5660971a178d2c0c0b16fa0bc52d44f55852560a10630e4f215ffb874b  src/orchestrator/graph_runtime/dispatch.py
FINAL
6a04a42adc4fd0f2ed4457abb3f3dfd37d2dd621238c1f90d643d8f92fb62173  src/orchestrator/graph/commands/boundary.py
8b76b846ab72bf25c8ca4254fcbbf226308637e2b9cbd768220eb2de0d676bf8  src/orchestrator/graph_runtime/dispatch.py
a1405adc0ededacffbef6e55c9879ea7ba47a19b970c20a78965857edb55fc51  tests/integration/test_graph_runner_recovery_dispatch.py
f248ba84ee6a716527f2618986d65ddded54b5f6116598f3ab5a00a53f03806e  tests/integration/test_graph_decision_runtime.py
```

Correction-pass hashes:

```text
e8001f1f62fa4a358f285e0c4e103f0890c7ebf927314816d8de35339e15a717  src/orchestrator/graph/decisions.py
410274c3b9d7e6cdcffae24ae698ffd40abfdf4bb2f9d909cf9167eb6547411f  src/orchestrator/graph/commands/boundary.py
221d6e19958e5ec38c1fd4637bc878ce0ed91b6cadfe2ef884a9b7d8af2305af  tests/integration/test_graph_runner_recovery_dispatch.py
```

## Builder correction pass 2

- Decision-v1 runner death remains terminal under the one-execution contract;
  it cannot regain the legacy accepted-patch retry shortcut.
- The legacy `invalid_planner_proposal` retry-limit regression now supplies a
  valid explicit legacy routine snapshot/authority plus the required retained
  candidate and diagnostic evidence. Attempt 1 schedules the legacy retry;
  attempt 2 exhausts it.
- Each decision crash boundary now receives three fresh recovery/reconcile
  passes with stable execution identity, event counts, lease generation and
  terminal ownership. The two cancellation phases also preserve an unrelated
  snapshot-ref canary, proving cleanup is exact-owner rather than prefix-wide.

The corrected legacy attempt-1/attempt-2 cases and the schema-2 process crash
case report **3 passed**; the slow cancellation canary reports **2 passed**.
Current pass-2 hashes:

```text
410274c3b9d7e6cdcffae24ae698ffd40abfdf4bb2f9d909cf9167eb6547411f  src/orchestrator/graph/commands/boundary.py
ddd67d41a084a0097080405cc20476a8097a03d9b2d8fdef31f27ab3ae350fdd  src/orchestrator/graph_runtime/dispatch.py
ef47a843bfdec188cfce1d85efbc8a0955c0f1818b0e6aef2d0fbedf07286a7b  tests/unit/test_graph_runner_boundary_commands.py
00c5f6570653b20ca40383ae44b56fc3d961f99dc767fc663d2fa536141839a6  tests/integration/test_graph_crash_barriers.py
70a81833eaf728c4a8154494859dbfe9b3d45c66cdae76fb29c437946a4b57a9  tests/integration/test_decision_recovery_crash_matrix.py
5f8239170e664f630576ae49af1a611e068a3000235fd35c4948bc9d24c9df67  tests/integration/test_graph_managed_snapshot_cleanup.py
```
