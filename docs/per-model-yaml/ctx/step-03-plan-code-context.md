# Step 03: Code Locations

## Code Locations

- `src/orchestrator/runners/execution/phase_handler.py` — `PhaseHandler._extract_metrics_and_usage()` lines 50–113: build `list[ModelTokenUsage]` from ActionLog parent (lines 67–80) and sub-agents grouped by model (lines 83–100); derive legacy flat metrics as sums (lines 102–111)
- `src/orchestrator/runners/execution/phase_handler.py` — `PhaseHandler._execute_building()` line 263: call `_extract_metrics_and_usage()`, pass result to `store_attempt_metrics()` at line 270
- `src/orchestrator/runners/execution/phase_handler.py` — `PhaseHandler._execute_verifying()` line 390: same pattern for verifier phase
- `src/orchestrator/runners/execution/phase_handler.py` — `PhaseHandler._execute_recovering()` line 460: same pattern for recovery phase
- `src/orchestrator/runners/costs.py` — `get_model_costs()` lines 73–95: called to populate cost rates on each `ModelTokenUsage` entry
