# Step 04: Code Locations

## Code Locations

- `src/orchestrator/db/access/repositories.py` — `RunRepository.update_latest_attempt()` lines 842–869: accumulate per-model usage into both attempt-level (lines 842–855) and run-level (lines 856–869) breakdowns by merging entries with matching model names
- `src/orchestrator/runners/execution/attempt_store.py` — `AttemptStore.store_attempt_metrics()` lines 109–131: accept `token_usage_by_model` kwarg, delegate to `RunRepository.update_latest_attempt()`
- `src/orchestrator/runners/execution/phase_handler.py` — all three phase execution methods (_execute_building, _execute_verifying, _execute_recovering) line ~270: pass `token_usage_by_model` to `store_attempt_metrics()`
