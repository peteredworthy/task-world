# Step 03 — Command-Event Refactor of RunRepository

## Purpose

Replace all `RunRepository` write methods with command handlers that emit
events. Projectors (from Step 02) handle the resulting state updates. After
this step, `RunRepository` becomes a read-only query layer. Entity creation
(`RunCreated`, `TaskCreated`) is fully event-sourced so the system can
reconstruct state from an empty database.

## Prerequisites / Dependencies

- **Step 02** must be complete — projectors must be wired and handling events
  so that emitted events actually update the read-model tables.
- **Step 01** — event store must be available for command handlers to append
  events.

## Functional Contract

### Inputs

| Input | Description |
|-------|-------------|
| Command models (Pydantic) | `CreateRunCommand`, `CreateTaskCommand`, `UpdateRunStatusCommand`, `UpdateTaskStatusCommand`, `UpdateChecklistCommand`, `SetGradeCommand`, `UpdateParentOversightFactsCommand`, etc. |
| Command handlers | One per write method; validates against current projection state, emits event(s) |
| `RunRepository` write methods | ~15 methods to refactor: `create_run`, `create_task`, `update_run_status`, `update_task_status`, `update_parent_oversight_facts`, `update_checklist`, `set_grade`, etc. |

### Outputs

- Command handler module at `src/orchestrator/workflow/commands/`.
- New event types as needed: `RunCreated`, `TaskCreated`, `ChecklistUpdated`,
  `GradeSet`, `ParentOversightFactsUpdated`, etc.
- `WorkflowService` calls command handlers instead of repository write
  methods.
- `RunRepository` write methods removed — it becomes a pure read-model query
  layer.
- `WorkflowEngine` remains pure (no I/O); buffered event emission pattern
  preserved.

### Errors

| Error | Handling |
|-------|----------|
| Invalid state transition (e.g., completing an already-failed run) | Command handler raises a domain-specific validation error before emitting any event |
| Version conflict on append | Handled by `RetryWithBackoff` (from Step 01) |
| Projection fails to update | Synchronous projection within the same transaction; failure rolls back the event append |

## Verification Strategy

1. **Unit tests** (`tests/unit/test_command_handlers.py`):
   - For each command handler: inject known projection state, invoke the
     handler, assert correct event(s) emitted.
   - Test validation: invalid state transitions produce domain errors, not
     events.
2. **Parity tests** (temporary, removed in Step 05):
   - Run the same operation sequence through both old (direct write) and new
     (command → event → projection) paths; assert identical read-model state.
3. **Integration test** (`tests/integration/test_event_sourced_workflow.py`):
   - Full flow: API request → command → event → projection → read-back via
     API. Assert response matches.
4. **Empty-DB rebuild test**:
   - Emit `RunCreated`, `TaskCreated`, status changes. Clear read-model
     tables. Rebuild projections. Assert full state reconstructed.
5. **Existing test suite**: `uv run pytest` — full suite passes.
6. **Type checking**: `uv run pyright` — confirms `RunRepository` no longer
   exposes write methods and all callers use command handlers.

## Deliverables

| Artifact | Location |
|----------|----------|
| Command models + handlers | `src/orchestrator/workflow/commands/` |
| New event types (RunCreated, TaskCreated, etc.) | `src/orchestrator/` (with existing event definitions) |
| Updated `WorkflowService` | `src/orchestrator/workflow/` |
| Read-only `RunRepository` | `src/orchestrator/db/access/` |
| Command handler unit tests | `tests/unit/test_command_handlers.py` |
| Integration test | `tests/integration/test_event_sourced_workflow.py` |
