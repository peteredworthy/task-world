# S3 Comparison Ledger

## Scope

Scenario S3 is Active Graph Diagnostics Snapshot. This ledger records admission
evidence and any A/C/E run evidence. The main checkout intentionally contains
the oracle and comparison harness, not the S3 reference implementation, so Arm A
starts from the same failing baseline.

## Baseline Before Oracle Work

Recorded on 2026-06-21 before adding the S3 hidden oracle files.

```text
uv run pytest tests/integration/test_graph_api.py::test_active_graph_execution_readback_uses_bounded_summary_paths tests/integration/test_graph_api.py::test_node_detail_returns_inputs_outputs_filestate_callbacks tests/integration/test_api_activity.py::test_activity_includes_compact_graph_patch_decision_summaries -q
3 passed in 2.46s

npm --prefix ui test -- GraphPanel.activity.test.tsx --run
1 file passed, 5 tests passed, 1.67s

uv run python scripts/profile_graph_readback.py --events 1000 --heavy-every 2 --payload-kb 128 --iterations 3
endpoint_like.graph_projection_after_append median 74.362 ms
read_model.graph_projection_snapshot_after_append median 276.991 ms
endpoint_like.graph_events_summary median 14.770 ms
endpoint_like.graph_events_full median 225.775 ms
```

## Admission Harness

Added:

- `docs/dynamic-graph/oracles/test_graph_diagnostics_hidden_oracle.py`
- `ui/src/components/__tests__/GraphDiagnostics.hidden.test.tsx`
- `routines/comparison-feature-single-agent/routine.yaml`
- S3 health metrics fields in `scripts/compare_carriers.py`

Current-tree hidden oracle result is intentionally failing:

```text
uv run pytest docs/dynamic-graph/oracles/test_graph_diagnostics_hidden_oracle.py -q
3 failed
```

Observed failure classes:

- `/api/runs/{run_id}/graph/health` returns 404 for graph and legacy runs.
- Compact node detail currently reports `file_state_records[0].classification_summary.total_paths == 0`
  for the synthetic graph, while S3 requires causal file-state classification
  evidence without full payloads.

```text
npm --prefix ui test -- GraphDiagnostics.hidden.test.tsx --run
1 failed
```

Observed failure class:

- The Graph panel does not render the required `Graph health` snapshot.

Non-oracle scaffolding validation:

```text
uv run pytest tests/unit/test_compare_carriers.py -q
6 passed in 0.73s

uv run ruff check src/orchestrator/db/__init__.py scripts/compare_carriers.py tests/unit/test_compare_carriers.py
All checks passed

uv run pyright src/orchestrator/db/__init__.py scripts/compare_carriers.py
0 errors
```

The reference worker later produced changes in the shared checkout instead of a
durable isolated proof. Those reference changes were removed from the baseline:
no production `/graph/health` API/UI implementation remains in the main tree.
A read-only validation sub-agent found stale `GraphHealth` lazy exports in
`src/orchestrator/api/__init__.py`; those were removed after the cleanup scan.

Post-cleanup validation:

```text
uv run pytest tests/integration/test_graph_api.py tests/integration/test_graph_node_detail_read_models.py tests/integration/test_api_activity.py tests/unit/test_compare_carriers.py -q
42 passed in 5.71s

uv run pytest docs/dynamic-graph/oracles/test_graph_diagnostics_hidden_oracle.py -q
3 failed

npm --prefix ui test -- GraphDiagnostics.hidden.test.tsx --run
1 failed

uv run ruff check src/orchestrator/api/__init__.py src/orchestrator/db/__init__.py scripts/compare_carriers.py tests/unit/test_compare_carriers.py docs/dynamic-graph/oracles/test_graph_diagnostics_hidden_oracle.py src/orchestrator/api/routers/graph.py src/orchestrator/graph_runtime/store.py
All checks passed

uv run pyright src/orchestrator/api/__init__.py src/orchestrator/db/__init__.py scripts/compare_carriers.py src/orchestrator/api/routers/graph.py src/orchestrator/graph_runtime/store.py
0 errors

npm --prefix ui test -- GraphPanel.activity.test.tsx SchedulerView.test.tsx --run
2 files passed, 6 tests passed, 1.02s
```

Latest readback profile:

```text
uv run python scripts/profile_graph_readback.py --events 1000 --heavy-every 2 --payload-kb 128 --iterations 3
endpoint_like.graph_projection_after_append median 84.110 ms
read_model.graph_projection_snapshot_after_append median 307.057 ms
endpoint_like.graph_events_summary median 15.941 ms
endpoint_like.graph_events_full median 253.886 ms
endpoint_like.node_detail median 75.149 ms
endpoint_like.node_detail_full_payload median 132.151 ms
```

Post-harness weak acceptance remained green:

```text
uv run pytest tests/integration/test_graph_api.py::test_active_graph_execution_readback_uses_bounded_summary_paths tests/integration/test_graph_api.py::test_node_detail_returns_inputs_outputs_filestate_callbacks tests/integration/test_api_activity.py::test_activity_includes_compact_graph_patch_decision_summaries -q
3 passed in 2.35s

npm --prefix ui test -- GraphPanel.activity.test.tsx --run
1 file passed, 5 tests passed, 1.17s

uv run python -c "from pathlib import Path; from orchestrator.config import load_routine_from_path; r=load_routine_from_path(Path('routines/comparison-feature-single-agent/routine.yaml')); assert r.id == 'comparison-feature-single-agent'; print('routine ok')"
routine ok
```

## Reference Proof

Blocked. An isolated worker was spawned to implement the reference shape only,
but it did not return a status or final result after repeated waits and a direct
status ping. A later worker notification showed shutdown, and inspection found
reference changes in the shared checkout. The production graph-health endpoint,
UI hook/types/card, and raw file-state read-model expansion were removed from
the baseline before validation.

Arm A must not start until a reference proof passes the backend and UI hidden
oracles in an isolated workspace. The reference implementation must not be
merged into the main checkout before Arm A.

## Arm A

Pending. Use `comparison-feature-single-agent` with `codex_server`, the S3 spec,
and weak acceptance command. Run hidden oracles outside the agent against the
run worktree.

## Arm C

Pending. Run only if Arm A fails hidden materially while producing useful
partial work.

## Arm E

Pending. Run only if Arm A fails hidden materially while producing useful
partial work.
