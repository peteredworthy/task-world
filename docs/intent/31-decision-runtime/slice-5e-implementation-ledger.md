# Slice 5E implementation ledger

Status: implemented; correction-focused crash and recovery matrix passed.

Scope: exercise the decision-v1 crash matrix through disposable production
dispatch and recovery. No live server, activation, paid model execution,
historical resume, database deletion, or commit is authorized.

| ID | Required behavior | Acceptance evidence | Status | Remaining gap |
|---|---|---|---|---|
| S5E-1 | A pre-stage crash is recovered without a staged answer, graph effects, duplicate answer attempt, or incorrect completion. | `test_decision_v1_crash_matrix_replays_without_duplicate_effects[pre_stage]` crashes after the durable baseline, then uses fresh `recover`/`reconcile_runtime` and asserts no staged/finalized/effect records and a failed node. | validated | None. |
| S5E-2 | Post-stage and post-witness crashes preserve the staged answer and exact owner facts, but do not publish an un-witnessed or un-finalized answer; restart/recovery is idempotent. | The same production matrix covers `[after_staging_pre_witness]` and `[after_witness_pre_finalization]`; post-stage recovers without effects, while post-witness finalizes exactly once from the witness. The generic real Git/SQLite barrier suite covers all durable boundary states. | validated | None. |
| S5E-3 | A post-commit/pre-ack crash or lost acknowledgement replays the durable finalization without duplicate effects, lost decision, or incorrect completion. | `test_decision_v1_crash_matrix_replays_without_duplicate_effects[after_commit_pre_ack]` crashes after `finalize_runner_execution` commits and before dispatch acknowledgement; recovery redelivery is suppressed by the durable attempt and leaves one decision, one patch and one finalization. | validated | None. |
| S5E-4 | Cancellation, repeated restart, attempt/rejection budgets, exact ownership, and failure next actions remain correct across the bounded matrix. | Each of the four crash points now survives three fresh recovery/reconcile passes with stable event counts, one execution identity, stable lease generation and no active lease. A two-case cancellation bridge proves exact-owner cleanup leaves an unrelated snapshot-ref canary intact. A production dispatch bridge joins D1, same-delivery redelivery, a fresh-controller restart, a new-identical D2, terminal recovery, one execution, no third callback, protected receipt replay and a pre-runner retry preflight. Product tests assert the public next action for stale binding, candidate check, environment blockage, runner death and budget exhaustion. | complete | No Cartesian expansion is claimed; the bounded bridge composes the required invariants without multiplying equivalent cases. |

## Starting evidence

- Previous implementation: `slice-5d-implementation-ledger.md`.
- Prior slice-2 decision staging/finalization tests cover in-process boundary
  pauses, but do not cover a process-loss/recovery matrix for decision-v1.
- The explicit operator-authorized crash seam now also names `pre_stage` and
  `after_commit_pre_ack`; schema-2 two-slot plans remain compatible and ignore
  those additional points.
- Baseline command and result:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q \
  tests/integration/test_graph_decision_runtime.py::test_decision_dispatch_stages_cas_then_atomically_finalizes \
  tests/integration/test_graph_crash_barriers.py \
  tests/integration/test_decision_answer_replay.py --override-ini='addopts=' --tb=short
12 passed, 1 failed in 37.64s
```

The pre-existing failure is recorded rather than attributed to this slice
until its cause is isolated:
`test_schema_two_survives_checkpointed_two_process_dispatch_recovery` expects
the legacy worker retry flag after slot-1 recovery, but observed
`retry_scheduled=False`.

The legacy retry expectation was restored as part of this slice's regression
closure; the decision-v1 matrix is terminal on infrastructure recovery and
never uses the legacy accepted-patch shortcut.

## Starting source hashes

Captured before Slice 5E edits:

```text
273ba01120ded2d739fb9670274641253bf151e82d1405ff4ce45082e4e720ea  src/orchestrator/graph_runtime/crash_barrier.py
cd9623b0296f4bc849fdec26c6c3249e9d31d781f49901080eb585fb942f41a6  src/orchestrator/graph_runtime/dispatch.py
fd2f3b65a94fd41c7b943e81613592b4b12b90c3834aae738c13f61537607662  src/orchestrator/graph/commands/boundary.py
e1cc9c73cfbac930f1bbb55245a33a3dd9e7fc7bd24a1c3d38eaada0c307bf37  src/orchestrator/graph_runtime/controller.py
6295eb90e5e5a3e2f73f1e9b8f777ff4d13792cc95d634083b6621cd488570dc  tests/integration/test_graph_crash_barriers.py
72d3fd55b55469b9b64a8303bd5a07b33704faa7c3bff0de53129fa8e315e8d8  tests/integration/test_graph_decision_runtime.py
8bc78e14f9e702b809e91d53e4fc6a5f123df3b4873814e87b156e2fcc6e81ff  tests/unit/test_graph_crash_barrier.py

The new matrix test had no starting hash because it was created in this slice.

## Implementation record and final hashes

Changed implementation:

- `crash_barrier.py` adds explicit pre-stage and post-commit/pre-ack points
  while preserving schema-2 plans.
- `dispatch.py` invokes those points, stages decision-v1 answers at the same
  post-stage boundary as legacy submissions, restores legacy restart retry
  semantics, and refuses redelivery for a durable recovered/finalized attempt.
- `boundary.py` keeps the legacy accepted-patch/retry behavior while ensuring
  decision-v1 infrastructure recovery cannot use it.
- `test_decision_recovery_crash_matrix.py` is the decision-v1 production
  Git/SQLite crash matrix; the existing barrier suites gain the two outer
  boundary controls.

Final hashes:

```text
ff8bbd4ca3b3f084bf635d1e68a2d0798359c1bf3ff98495bd7a5d1e7e7cdc4d  src/orchestrator/graph_runtime/crash_barrier.py
903507f083d44fee62d257f0b2145cf5637949ace19435977d7e8fc9be7d3884  src/orchestrator/graph_runtime/dispatch.py
803763b7dc2a88bb56943ec62827e97e74cae96b3788754d211a58aac15054aa  src/orchestrator/graph/commands/boundary.py
e1cc9c73cfbac930f1bbb55245a33a3dd9e7fc7bd24a1c3d38eaada0c307bf37  src/orchestrator/graph_runtime/controller.py
00c5f6570653b20ca40383ae44b56fc3d961f99dc767fc663d2fa536141839a6  tests/integration/test_graph_crash_barriers.py
72d3fd55b55469b9b64a8303bd5a07b33704faa7c3bff0de53129fa8e315e8d8  tests/integration/test_graph_decision_runtime.py
c68beaed07dff53d563f982de272690ccebb6ac3193f29cfcc58f6731d8ddaa1  tests/integration/test_decision_recovery_crash_matrix.py
c3f7c4c5295dc407bfa4a17032985c36d7549f7ee923ffa766a815a466fa0849  tests/unit/test_graph_crash_barrier.py
```

## Validation

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q tests/integration/test_decision_recovery_crash_matrix.py --override-ini='addopts=' --tb=short
4 passed in 9.02s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q tests/integration/test_graph_crash_barriers.py tests/unit/test_graph_crash_barrier.py tests/unit/test_graph_runner_boundary_commands.py --override-ini='addopts=' --tb=short
65 passed, 1 warning in 12.50s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q tests/integration/test_decision_recovery_crash_matrix.py tests/integration/test_decision_answer_replay.py tests/integration/test_graph_runner_recovery_dispatch.py tests/integration/test_graph_startup_recovery.py tests/unit/test_graph_recovery_selection.py tests/unit/test_startup_recovery.py --override-ini='addopts=' --tb=short
19 passed, 18 skipped in 11.86s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q tests/integration/test_graph_decision_runtime.py --override-ini='addopts=' --tb=short
73 passed, 9 warnings in 280.73s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pyright src/orchestrator/graph_runtime/crash_barrier.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph/commands/boundary.py
0 errors, 0 warnings, 0 informations

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ruff check src/orchestrator/graph_runtime/crash_barrier.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph/commands/boundary.py tests/integration/test_decision_recovery_crash_matrix.py tests/integration/test_graph_crash_barriers.py tests/unit/test_graph_crash_barrier.py
All checks passed!

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python scripts/check_graph_projection_boundaries.py
passed

git diff --check
passed
```

No live server, activation, paid execution, historical-run resume, or commit
was performed. The full repository gate remains reserved for Slice 6F.

## Merge-blocker correction pass

`test_noncorrectable_decision_rejection_enters_and_completes_recovery` extends
the production matrix with both environment-stop and runner-death outcomes.
The four-point test performs repeated fresh reconstruction, and the cancellation
test carries an exact-owner canary in both cancellation phases. The rejection
budget bridge exercises production scheduling/dispatch/ingress/recovery and
replays the two event-owned receipts into empty databases. This deliberately
closes S5E-4 with a bounded composition rather than a redundant Cartesian test
explosion.

### Builder pass-2 validation

```text
# Expected baseline exposing the FastMCP wire incompatibility
tests/integration/test_graph_decision_runtime.py
15 failed, 58 passed, 6 warnings in 246.02s

# Final complete decision-runtime regression
tests/integration/test_graph_decision_runtime.py
73 passed, 9 warnings in 300.92s

# Failure diagnostics, schemas/adapters, legacy authority, crash matrix and replay
tests/unit/test_failure_diagnostics.py
tests/unit/test_decision_schema_consumers.py
tests/unit/test_codex_server_transport.py
tests/unit/test_graph_runner_boundary_commands.py
tests/integration/test_decision_recovery_crash_matrix.py
tests/integration/test_decision_answer_replay.py
138 passed, 1 skipped, 1 warning in 22.13s

# Exact-owner cancellation canary, both phases
tests/integration/test_graph_managed_snapshot_cleanup.py::test_terminal_cancellation_before_recovery_request_converges_in_one_startup_reconcile
2 passed in 3.21s

# Obsolete expectation reconciliation: schema-2 process crash plus legacy attempts 1/2
tests/integration/test_graph_crash_barriers.py::test_schema_two_survives_checkpointed_two_process_dispatch_recovery
tests/unit/test_graph_runner_boundary_commands.py::test_invalid_planner_proposal_recovery_obeys_persisted_execution_limit
3 passed in 5.23s

# After the final public-import-only cleanup
tests/unit/test_failure_diagnostics.py
tests/unit/test_decision_schema_consumers.py
tests/unit/test_codex_server_transport.py
tests/integration/test_graph_decision_runtime.py::test_work_result_preserves_dispatch_authority[before-stage-bound-codex_server]
77 passed, 1 skipped in 3.40s

ruff check (focused): All checks passed
pyright (focused production files): 0 errors, 0 warnings
scripts/check_graph_projection_boundaries.py: passed
git diff --check: passed
```

No full repository/pre-commit gate, live server, live database, paid model,
commit or merge was run in this builder pass. Current pass-2 hashes:

```text
ff8bbd4ca3b3f084bf635d1e68a2d0798359c1bf3ff98495bd7a5d1e7e7cdc4d  src/orchestrator/graph_runtime/crash_barrier.py
ddd67d41a084a0097080405cc20476a8097a03d9b2d8fdef31f27ab3ae350fdd  src/orchestrator/graph_runtime/dispatch.py
70a81833eaf728c4a8154494859dbfe9b3d45c66cdae76fb29c437946a4b57a9  tests/integration/test_decision_recovery_crash_matrix.py
e731b07305d3cbd2e3bec948032b0aa9efead22c4f28dc1ddad820c5774e799c  tests/integration/test_decision_answer_replay.py
f1ed77d86477dddacbdb2cac8cc85f59ac0e08d5daf6a0b45a374ba1d72754da  tests/integration/test_graph_decision_runtime.py
5f8239170e664f630576ae49af1a611e068a3000235fd35c4948bc9d24c9df67  tests/integration/test_graph_managed_snapshot_cleanup.py
```

## Builder correction pass 3

The Slice 5D candidate-check replay correction preserves the Slice 5E
recovery and budget invariants. The crash/restart and D1/redelivery/restart/D2
receipt bridge passed inside the 146-test focused bundle, while both real
candidate-check recovery variants passed with no redispatch. The complete
decision-runtime integration remained green at 73 passed. Exact evidence and
hashes are recorded in the Slice 5D pass-3 ledger; the Slice 5E files changed
by that correction currently hash as follows:

```text
cdfafd64da14a37408e206db2b3e76944c3151257f12a5649908db5e65c84a83  src/orchestrator/graph_runtime/dispatch.py
f6bccf4b49696c99f4353c99920ffa6eb9a292b6bc4e578eeb2e7e90f2b6fbb6  tests/integration/test_decision_answer_replay.py
16f722e3117b89fe8c0d72fe360c7530fc87a86a73b1ecd75b92f6e881b6b973  tests/integration/test_graph_decision_runtime.py
```

## Builder formatting pass 4

Ruff formatting was applied only to the nine files identified by the
independent validator. No behavior was changed. Focused Ruff format/check,
Pyright, the graph-projection boundary check, and `git diff --check` pass. The
directly affected focused test run reports **287 passed, 1 failed**: the
existing decision-v1 recovery assertion in
`test_decision_stage_is_effect_free_and_finalization_is_terminal_and_atomic`
expects `runner_recovery_completed_retry_scheduled`, while the implementation
and the Slice 5C/5E terminal-recovery contract produce
`runner_recovery_terminal`. The isolated rerun reproduces the same failure.

Current hashes after formatting:

```text
720034dfe2e061ba9bdaf92d8bad300b3efbf3620ca9b2cd68fcd3bc43fab160  src/orchestrator/config/failures.py
a5ea719f7ad7bf941bb4ba70cc0396059961a6e0d449540ea3a913689a5d7a74  src/orchestrator/graph/commands/boundary.py
db580627d9ec0a16ceb591978af3ef5e362ca9e6345ae712e2577b2413e9cacc  src/orchestrator/graph/projections.py
d015a61a0ba31c6b2075e5369697bc101d57484b4c60e7b04aab1a33b3338a94  src/orchestrator/graph_runtime/graph_mcp_tools.py
566416ef3e321094fb3c2155092e1fddcee3cfa6151360e205d2f6d886c3365b  src/orchestrator/runners/agents/codex/agent.py
d6765c0cb640e1881347917a2b9f19fc705487ceb26b58b9f170f35c4491bd45  src/orchestrator/runners/types.py
879c9ac195d5a86ba3e5023c0903bb9adecdb6cf70ba23f342ec610374b180a8  tests/integration/test_decision_recovery_crash_matrix.py
bccd5afb2d98260ec680efd321b766de0fd47450bf10804622940930f744a24d  tests/unit/graph_projection_behavior_cases.py
2718b40f53e84313735007ef684cf8a09568d3b16ed0ceec1651824868ffa312  tests/unit/test_graph_decisions.py
```

## Builder correction pass 5

The obsolete decision-v1 unit expectation identified in pass 4 was reconciled
with the reviewed Slice 5C/5E contract. The renamed
`test_decision_stage_is_effect_free_finalization_atomic_and_recovery_terminal`
now proves that runner death after an accepted consequence patch is terminal
for decision-v1: recovery emits `runner_recovery_terminal`, fails the node,
revokes the exact lease, records a non-retryable infrastructure failure, and
does not schedule a runtime retry or duplicate the decision patch/answer.
Production behavior was not changed.

Validation:

```text
tests/unit/test_graph_decisions.py
107 passed in 3.70s

tests/unit/test_graph_runner_boundary_commands.py
tests/integration/test_decision_recovery_crash_matrix.py
tests/integration/test_graph_runner_recovery_dispatch.py
57 passed, 17 skipped, 1 warning in 15.93s

ruff format tests/unit/test_graph_decisions.py
1 file left unchanged

ruff check tests/unit/test_graph_decisions.py
All checks passed!

scripts/check_graph_projection_boundaries.py
passed

git diff --check
passed
```

Current corrected test hash:

```text
8e60e55ec53baf8cf3671d657794d6369ee91bdbe11a78c0a758b5e7ec5bdcfd  tests/unit/test_graph_decisions.py
```

## Builder dispatch-ordering correction pass 6

The full-suite regression in reliable-plan dispatch was caused by the new
durable redelivery check reading through the controller before the existing
selected-runner tool-catalog preflight. Dispatch now preserves that preflight
as the first runner-specific boundary, reads the durable attempt from the
already-current projection assembled into the dispatch context, and performs
rejected-answer receipt replay at the last safe point immediately before model
runner construction. Join and final-gate dispatch remain runner-free.

The focused regression adds a prior `decision_answer_rejected` fact without its
required protected receipt and proves dispatch rejects it with zero runner
creation calls. The production D1/redelivery/restart/D2 bridge still proves the
same no-paid-retry invariant through real scheduling, persistence, and receipt
authorization.

Validation:

```text
# Expected baseline
test_reliable_plan_dispatch_rejects_missing_registration_before_runner_creation
1 failed: controller read preceded selected-runner preflight

# Catalog ordering, receipt ordering, and runner-free node routing
test_reliable_plan_dispatch_rejects_missing_registration_before_runner_creation
test_decision_retry_missing_receipt_blocks_before_runner_creation
test_dispatch_routes_final_gate_without_agent
test_dispatch_routes_join_without_agent
4 passed in 0.38s

tests/unit/test_graph_dispatch_on_output.py
106 passed, 1 warning in 1.48s

test_rejection_budget_survives_redelivery_restart_recovery_and_replays_receipts
1 passed in 2.21s

ruff format --check (dispatch implementation and focused unit file): passed
ruff check (same files): passed
pyright (same files): 0 errors, 0 warnings
scripts/check_graph_projection_boundaries.py: passed
git diff --check and git diff --cached --check: passed
```

Current pass-6 hashes:

```text
77a11755ae66c020c972b9a83bbb96c9e0d0614e30623cb89feb2260d45eec99  src/orchestrator/graph_runtime/dispatch.py
1e4c9668b08b3ef7a4cd68aec60f06214b1259d591da8bdb1ff410c62912489c  tests/unit/test_graph_dispatch_on_output.py
```
