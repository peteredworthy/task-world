# Slice 4E implementation ledger

Status: implemented and validated.

Scope: close the verification-integration gap with disposable, production-path
evidence. Preserve the existing legacy joined qualification and the YAML custom
semantic-output behavior; decision-v1 coverage must be additive.

| ID | Required behavior | Acceptance evidence | Status | Remaining gap |
|---|---|---|---|---|
| S4E-1 | A correct neutral candidate completes through worker, mandatory check, typed verifier, and finalization. | `test_runtime_check_executes_once_before_typed_verifier_and_survives_restart[codex_server-passing-runtime-check]` and `test_work_result_worker_uses_real_checkout_and_runtime_owned_records[codex_server-ready-commits-candidate]` pass against disposable Git/SQLite. The assertions cover the real checkout commit, runtime-owned candidate/file-state records, exact check receipt, typed report, and drained leases/attempts. | complete | None. |
| S4E-2 | A defective neutral candidate cannot be falsely accepted and enters the existing bounded correction path. | The typed runtime-check failure case records `failed` for the exact candidate and produces no accepted report. `test_rejected_batch_dispatches_a_bounded_correction_decision` publishes one bounded correction decision from exact failure evidence. The joined legacy production qualification `test_api_correction_uses_exact_failure_evidence_then_completes_horizon_two` proves the existing corrective worker/verifier path and final completion after repair. | complete | None. |
| S4E-3 | Legacy grader adapters and YAML-authored custom semantic outputs retain behavior. | The joined legacy start and correction qualification tests pass. Typed custom semantic preservation and builtin-plan-shape rejection both pass, retaining YAML-authored semantic products without treating them as graph authority. | complete | None. |
| S4E-4 | Evidence is restart-safe and ownership is drained. | The typed pass/fail tests reconstruct a fresh `GraphController` after the mandatory check, assert one exact check receipt and no duplicate execution, then verify final records. They also assert no active leases and finalized attempts; post-answer mutation remains rejected. | complete | None. |

## Starting evidence

The preceding Slice 4A–4D ledgers are preserved. The current focused baseline
was one passing Codex Server runtime-check case:

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py \
  -k 'runtime_check_executes_once and passing-runtime-check and codex_server' \
  --override-ini='addopts=' --tb=short
# 1 passed, 70 deselected in 3.41s
```

The broad current-file baseline was attempted before this slice. It reported
63 passed and 8 failures in 445.81s; the failures were existing full-file
cleanup/timeout interactions (including CLI MCP cleanup and a direct correction
test) and are retained as baseline diagnostics, not credited to this slice.

## Source hashes at slice start

```text
35bf75d72b4894a73768e954712047b568e9cf5e7dd4de779cbc6a8d1e9d4966  tests/integration/test_graph_decision_runtime.py
443c91d69a2d75fdcdf3dd805425f0c35b2c424dde10aa611e7eea8e01828a8f  tests/integration/test_graph_sequential_product_path.py
fa01a141b6340183db801384d668d0a1149033c99dcbe3c7b3310da953b1d0dc  src/orchestrator/graph_runtime/dispatch.py
a9ee74e57dabcea7c0262ad9761184fdc91c3d701249ffec4ae0e3888772d9f3  src/orchestrator/graph/decisions.py
7b2d4f18a3f6c95fc20c1394828a9b146269ee6d894d1ac5cd9f818775905cbc  src/orchestrator/graph/macros.py
```

No live server, live history/database mutation, activation, paid execution, or
commit is authorized by this slice.

## Validation evidence

All commands below ran from `worktrees/recovery-stabilization` with disposable
temporary Git repositories and SQLite databases. The test harness uses the
production `GraphController`, `GraphDispatchExecutor`, runner adapters, graph
projection, event store, and finalization commands; no live server or model
transport was used.

```text
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  'tests/integration/test_graph_decision_runtime.py::test_runtime_check_executes_once_before_typed_verifier_and_survives_restart[codex_server-passing-runtime-check]' \
  'tests/integration/test_graph_decision_runtime.py::test_runtime_check_executes_once_before_typed_verifier_and_survives_restart[codex_server-failed-runtime-check]' \
  --override-ini='addopts=' --tb=short
# 2 passed in 6.61s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  'tests/integration/test_graph_decision_runtime.py::test_work_result_worker_uses_real_checkout_and_runtime_owned_records[codex_server-ready-commits-candidate]' \
  'tests/integration/test_graph_decision_runtime.py::test_work_result_worker_uses_real_checkout_and_runtime_owned_records[codex_server-missing-required-semantic-product-rejects]' \
  --override-ini='addopts=' --tb=short
# 2 passed in 3.05s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py::test_rejected_batch_dispatches_a_bounded_correction_decision \
  --override-ini='addopts=' --tb=short
# 1 passed in 2.25s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_decision_runtime.py::test_work_result_worker_uses_real_checkout_and_runtime_owned_records[codex_server-ready-preserves-semantic-product] \
  tests/integration/test_graph_decision_runtime.py::test_work_result_rejects_custom_product_with_builtin_plan_shape[codex_server] \
  --override-ini='addopts=' --tb=short
# 2 passed in 3.21s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_sequential_product_path.py::test_api_start_serializes_two_bounded_horizons_with_durable_signals \
  --override-ini='addopts=' --tb=short
# 1 passed in 72.66s

UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync pytest -q -n 0 \
  tests/integration/test_graph_sequential_product_path.py::test_api_correction_uses_exact_failure_evidence_then_completes_horizon_two \
  --override-ini='addopts=' --tb=short
# 1 passed in 113.59s
```

The attempted synthetic typed correction continuation was intentionally not
made part of the qualification: when its fixture lacked a durable rejected
candidate snapshot, the scheduler deferred the corrective worker with
`missing_rejected_candidate_snapshot`. That is the required safety behavior,
not a reason to weaken the fixture or bypass the correction authority. The
real joined qualification supplies the durable rejected snapshot and proves
the correction continuation end to end.

The earlier broad-file baseline remains recorded above: 63 passed and 8
failures in 445.81s, caused by existing full-file async cleanup/timeout
interactions. Slice 4E acceptance was therefore established with isolated
tests, while the deferred recovery gate remains the repository-wide merge
gate.

## Final source hashes

The implementation source and integration fixtures were not changed by the
Slice 4E qualification addition; the only Slice 4E change is this ledger.

```text
35bf75d72b4894a73768e954712047b568e9cf5e7dd4de779cbc6a8d1e9d4966  tests/integration/test_graph_decision_runtime.py
443c91d69a2d75fdcdf3dd805425f0c35b2c424dde10aa611e7eea8e01828a8f  tests/integration/test_graph_sequential_product_path.py
fa01a141b6340183db801384d668d0a1149033c99dcbe3c7b3310da953b1d0dc  src/orchestrator/graph_runtime/dispatch.py
a9ee74e57dabcea7c0262ad9761184fdc91c3d701249ffec4ae0e3888772d9f3  src/orchestrator/graph/decisions.py
7b2d4f18a3f6c95fc20c1394828a9b146269ee6d894d1ac5cd9f818775905cbc  src/orchestrator/graph/macros.py
```
