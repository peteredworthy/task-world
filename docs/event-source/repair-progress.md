# Event-Source Repair Progress

## Baseline

- Worktree: `worktrees/r187`
- Branch: `orchestrator/run-a8c5b27f-1025-4b9d-af18-c34eb20390ec`
- Baseline status: clean worktree before repair loop
- Full intent: `docs/event-source/intent.md`
- Planning summary: `docs/event-source/plan-summary.md`

## Loop Roles

- Meta Planner: selects the next significant but achievable repair chunk.
- Builder: implements only the selected chunk, using AST-aware tools where possible for large refactors.
  The builder may install a Python refactoring tool such as Rope, LibCST, or Bowler, or build a small AST-based script, when the change is structurally broad enough to justify it.
- Verifier: compares the implementation against the Meta Planner request and checks for introduced bugs.
- Gap Analyzer: keeps a current-state report against the full event-source intent.

## Operating Rules

- Keep each chunk independently testable.
- Prefer AST-aware refactoring tools for broad Python edits; avoid grep-and-edit for structural changes.
- Preserve API and WebSocket response contracts unless a chunk explicitly says otherwise.
- Do not remove compatibility code unless the selected chunk includes the replacement and tests.
- Record each loop result here before committing.

## Current Known Gaps

- `events_v2` is not yet the only authoritative write path; direct read-model mutations remain in production state transitions.
- Some state changes still use transitional helpers such as `save_run()` and `update_latest_attempt()`.
- Normal and child run creation now emit explicit creation events; legacy snapshot replay remains for older logs.
- Projection rebuild/checkpoint handling and startup recovery are incomplete.
- Some event type names are not canonical for replay/bootstrap.
- Output batching still lacks a true timer-backed 100ms flush.
- Architecture documentation overstates completion and still references legacy output behavior.

## Iterations

### Iteration 1

- Meta Planner chunk: finish event-only signal cleanup.
- Objective: remove remaining runtime `pending_signals` paths and make signal processing redeliverable when handlers fail.
- Scope:
  - Remove `DbSignalTransport` and `PendingSignalModel` from runtime exports and default paths.
  - Ensure `ParentOversightService` no longer falls back to `DbSignalTransport`.
  - Change `SignalConsumer` so `SignalProcessed` is appended only after handler success.
  - Update focused signal tests to assert `events_v2`-only behavior.
- Out of scope:
  - Legacy `EventStore` dual-write removal.
  - Direct `save_run()` or `update_latest_attempt()` mutation removal.
  - JSONL outbox transaction timing.
  - Alembic history rewrites.
- Builder result: removed runtime `DbSignalTransport` / `PendingSignalModel`, replaced fallback signal queues with `EventSignalTransport`, and changed `SignalConsumer` so `SignalProcessed` is appended after handler success. The follow-up pass kept event-backed production signal consumption in `SignalConsumer` only so active executor loops cannot race the poller for the same `events_v2` signal.
- Verifier result: found and resolved one blocking dual-consumer race. Final local verification passed:
  - `uv run pytest tests/unit/test_event_signal_transport.py tests/unit/test_signal_consumer.py tests/unit/test_signal_redelivery.py tests/integration/test_signal_events.py tests/integration/test_signal_queue.py -q`
  - `uv run pyright src/orchestrator/workflow/signals src/orchestrator/workflow/parent_oversight.py src/orchestrator/api/deps.py scripts/worker.py tests/unit/test_event_signal_transport.py`
  - `uv run ruff check` on touched files
  - `rg -n "DbSignalTransport|PendingSignalModel|pending_signals" src/orchestrator scripts --glob '!src/orchestrator/db/migrations/versions/*'`
- Residual note: `EventSignalTransport.drain()` remains for compatibility and tests, but production event-backed signal processing no longer calls it; `SignalConsumer` is the sole runtime `events_v2` signal consumer.
- Gap report update:
  - Critical: event log is not yet the single source of truth.
  - Critical: JSONL outbox can write before failed projection/commit rollback.
  - High: production run creation relies on snapshots rather than explicit task creation events.
  - High: startup recovery trusts existing projections unless the DB is empty.
  - Medium: event type names are not canonical for replay/bootstrap.

### Iteration 2

- Meta Planner chunk: make JSONL outbox post-commit.
- Objective: ensure `history.jsonl` is only a secondary output for events durably committed to `events_v2`.
- Scope:
  - Keep projection listeners synchronous inside `SqliteEventStore.append()` so projection failures still abort the transaction.
  - Queue JSONL observer batches on the SQLAlchemy session after projections succeed.
  - Add explicit commit/rollback helpers that flush queued JSONL writes only after successful database commit and clear queued work on rollback or commit failure.
  - Move production event-writing transaction boundaries in `WorkflowService`, signal processing, task signal routes, parent oversight fallback signals, runner monitor, and output batching to the helper.
- Out of scope:
  - Removing legacy `EventStore`.
  - Removing `save_run()` or other direct read-model mutation helpers.
  - Redesigning event payloads or snapshot-based run creation.
  - Normalizing all event type names.
- Builder result: added `event_outbox` commit/rollback helpers, changed `SqliteEventStore` listeners into post-commit outbox observers, made JSONL write failures propagate after database commit, and wired event-writing production paths through `create_wired_event_store_v2()` plus `commit_with_event_outbox()`.
- Verifier result: found and resolved initial blocking gaps in API imports and unwired signal paths. Final verification found no blockers. Final local verification passed:
  - `uv run pytest tests/unit/test_event_store_v2.py tests/unit/test_jsonl_outbox.py tests/unit/test_signal_consumer.py tests/integration/test_event_store_wiring.py tests/integration/test_signal_events.py -q`
  - `uv run pyright src/orchestrator/db src/orchestrator/workflow/service.py src/orchestrator/workflow/signals/consumer.py src/orchestrator/api/deps.py src/orchestrator/api/routers/tasks.py src/orchestrator/workflow/parent_oversight.py`
  - `uv run ruff check` on touched files
  - `rg -n "await self\._session\.commit\(" src/orchestrator/workflow/service.py`
- Residual note: `EventSignalTransport.drain()` remains for compatibility and tests, but production event-backed signal processing does not use it.
- Gap report update:
  - Critical: event log is not yet the single source of truth; legacy `EventStore` and direct read-model writes remain.
  - High: production run creation relies on snapshots rather than explicit task creation events.
  - High: projection rebuild and startup recovery still trust existing projections unless explicitly rebuilt.
  - Medium: event type names are not canonical for replay/bootstrap.

### Iteration 3

- Meta Planner chunk: remove legacy `EventStore` from production event emission.
- Objective: make production event emission write only to `events_v2`, while leaving the old event table and store as compatibility/test debt.
- Scope:
  - Remove `secondary_store`, `emit_legacy_only`, and production legacy `EventStore` construction.
  - Make `PersistentEventEmitter.emit()` persist through its configured v2 store only.
  - Add notify-only listener methods for events already appended by command handlers.
  - Wire API dependencies, workflow service, review routes, output batching, activity reads, and runner log broadcasting to v2 stores.
  - Ensure direct child fan-out lifecycle events append to `_store_v2` and then notify listeners without dual-write.
- Out of scope:
  - Removing the legacy `EventStore` module/table, old migrations, compatibility scripts, or legacy tests.
  - Removing `save_run()` and other direct read-model mutation helpers.
  - Redesigning snapshot-based creation events.
  - Fixing projection rebuild/checkpoint semantics.
- Builder result: removed production dual-write wiring, converted `PersistentEventEmitter` to v2-only persistence plus notify-only broadcasts, moved runner log events to wired v2 storage with post-commit JSONL outbox flushing, changed activity reads to v2, and updated tests around v2-only emission.
- Verifier result: found and resolved two blocking gaps:
  - Review API routes emitted v2 events without committing the request session/outbox.
  - `start_fan_out_parent()` appended a duplicate `task_status_changed` event by emitting after `handle_update_task_status()` had already persisted it.
  Final verification found no blockers. Final local verification passed:
  - `uv run pytest tests/integration/test_event_store_wiring.py tests/integration/test_output_batching.py tests/integration/test_agent_logs.py tests/integration/test_workflow_service.py tests/unit/test_event_store.py -q`
  - `uv run pytest tests/unit/test_event_store.py tests/integration/test_event_store_wiring.py tests/integration/test_workflow_service.py tests/unit/test_signal_consumer.py tests/integration/test_output_batching.py -q`
  - `uv run pyright src/orchestrator/api/deps.py src/orchestrator/api/routers/review.py src/orchestrator/workflow/service.py src/orchestrator/workflow/events/logger.py src/orchestrator/runners/execution/event_broadcaster.py`
  - `uv run ruff check` on touched files
  - `rg -n "emit_legacy_only|secondary_store|self\._event_store|EventStore\(" src/orchestrator/api src/orchestrator/workflow src/orchestrator/runners`
- Residual note: legacy `EventStore` references remain in scripts and legacy tests outside the production acceptance grep.
- Gap report update:
  - Critical: event log is still not the single source of truth because production paths still write read-model state directly through helpers such as `save_run()` and attempt/oversight mutation helpers.
  - High: creation remains snapshot-based and does not yet model run/task creation as explicit replayable events.
  - High: projection rebuild checkpoints and startup recovery semantics remain incomplete.
  - Medium: event type name mismatches still weaken JSONL bootstrap/replay.
  - Medium: output batching still lacks a true timer-backed 100ms flush.

### Iteration 4

- Meta Planner chunk: replace snapshot-based run creation with explicit creation events.
- Objective: make new run creation replayable from first-class `RunCreated`, `StepCreated`, and `TaskCreated` events instead of one opaque `run_snapshot`.
- Scope:
  - Convert `WorkflowService.create_run()` to build explicit initial run/step/task creation metadata.
  - Add step creation events and projector handling.
  - Update task projection so initial tasks include checklist, complexity, max attempts, fan-out metadata, initial status, and initial attempts where needed.
  - Route CLI-created runs through `WorkflowService.create_run()`.
  - Preserve legacy `RunCreated.run_snapshot` projection support.
  - Include child-run creation after verifier found it still bypassed events.
- Out of scope:
  - Removing `save_run()` generally.
  - Refactoring `_persist` or all direct read-model mutations.
  - Removing legacy snapshot replay support.
  - Fixing output batching timer behavior.
  - Changing public REST/WebSocket response shapes.
- Builder result: added shared `build_create_run_command()` translation, emitted explicit creation batches for normal and child runs, projected explicit step/task creation, updated CLI create to use the service path, and added tests for explicit creation and child-run rebuild.
- Verifier result: found and resolved one blocking gap:
  - Child-run creation still used parent oversight `save_run()` and bypassed explicit creation events.
  Final verification found no blockers. Final local verification passed:
  - `uv run pytest tests/unit/test_command_handlers.py tests/unit/test_projectors.py tests/unit/test_pydantic_events.py tests/integration/test_event_sourced_workflow.py tests/integration/test_api_runs.py::test_create_run_produces_run_created_event_in_events_v2 tests/unit/test_super_parent_service_mechanics.py::test_create_child_run_events_rebuild_child_read_model -q`
  - `uv run pytest tests/integration/test_projection_recovery.py tests/integration/test_event_sourced_workflow.py tests/unit/test_pydantic_events.py -q`
  - `uv run pytest tests/unit/test_super_parent_service_mechanics.py::test_create_child_run_events_rebuild_child_read_model tests/unit/test_projectors.py tests/unit/test_pydantic_events.py -q`
  - `uv run pyright src/orchestrator/workflow src/orchestrator/db/projections src/orchestrator/cli/runs.py`
  - `uv run ruff check` on touched files
  - `rg -n "save_run\(|run_snapshot=" src/orchestrator/workflow/parent_oversight.py src/orchestrator/cli/runs.py src/orchestrator/workflow src/orchestrator/db/projections -g '*.py'`
- Residual note: explicit creation restores core initial attempt/status fields, but not every historical attempt detail such as prompts, comments, or commit SHAs. That remains outside this chunk unless full attempt snapshot parity becomes a later requirement.
- Gap report update:
  - Critical: event log is still not the single source of truth because core workflow transitions and several helper paths still write read-model state directly.
  - Critical: attempt storage and runner totals still mutate attempts/tasks/runs directly.
  - High: projection rebuild checkpoints and startup recovery semantics remain incomplete.
  - Medium: event type name mismatches still weaken JSONL bootstrap/replay.
  - Medium: output batching still lacks a true timer-backed 100ms flush.

### Iteration 5

- Meta Planner chunk: make `WorkflowService._persist()` event-first for core engine transitions.
- Objective: remove the shared state-first `save_run()` write from `_persist()` so core `WorkflowEngine` transitions persist through `events_v2` and projectors.
- Scope:
  - Refactor `_persist()` to drain buffered events, append through the v2 store, notify listeners without duplicate rows, commit with `commit_with_event_outbox()`, and reload from `RunRepository`.
  - Add narrow event payload/projector support for core task transition state needed after removing `save_run()`.
  - Add real-DB regression tests for start task, submit, verifier pass/revision, event counts, replay, and auto-verify-only persistence.
- Out of scope:
  - Removing `save_run()` globally.
  - Refactoring attempt store, fan-out, recovery, or parent oversight direct SQL helpers.
  - Changing explicit run/task creation from Iteration 4.
  - Fixing projection rebuild checkpoints/startup recovery.
  - Implementing timer-backed output batching.
- Builder result: `_persist()` now appends buffered events to `events_v2`, calls notify-only broadcast, commits via the outbox helper, and reloads projected state. `TaskStatusChanged` and `AutoVerifyCompleted` now carry targeted projection payloads for current attempts, attempt snapshots, checklist state, and auto-verify results, with projector handling for those fields. Full-suite hook failures also exposed and fixed adjacent event-first gaps for safety-net completion status, super-parent terminal guard fact/status projection, backward step/task reset projection, and escalation checklist projection.
- Verifier result: found and resolved one blocking gap:
  - Auto-verify/checklist state changes were dropped when `_persist()` received only an `AutoVerifyCompleted` event and no `TaskStatusChanged`.
  Final verification found no blockers. Final local verification passed:
  - `uv run pytest tests/integration/test_auto_verify_workflow.py::test_submit_with_passing_auto_verify tests/integration/test_auto_verify_workflow.py::test_submit_with_failing_must_auto_verify tests/integration/test_check_and_apply_methods.py::TestCheckSubmission::test_passing_auto_verify_auto_marks_and_passes_gate tests/integration/test_auto_verify_timing.py::test_passing_auto_verify_allows_transition tests/unit/test_step_auto_verify.py::test_step_auto_verify_failing_halts_run -q`
  - `uv run pytest tests/integration/test_workflow_service.py tests/integration/test_event_sourced_workflow.py tests/unit/test_projectors.py tests/integration/test_check_and_apply_methods.py tests/unit/test_pydantic_events.py -q`
  - `uv run pytest tests/unit/test_super_parent_service_mechanics.py::test_safety_net_save_applies_terminal_guard tests/integration/test_api_backward_transitions.py::test_transition_backward_basic 'tests/integration/test_executor_loop_invariant.py::TestExecutorLoopNeverLeavesActive::test_run_not_active_after_loop[NoTaskReason.ALL_COMPLETE]' -q`
  - `uv run pytest tests/integration/test_api_escalation.py::test_escalate_pauses_run_and_marks_requirement tests/integration/test_api_escalation.py::test_escalation_resume_after_human_intervention -q`
  - `uv run pytest tests/integration/test_workflow_service.py tests/integration/test_event_sourced_workflow.py tests/unit/test_projectors.py tests/integration/test_check_and_apply_methods.py tests/unit/test_pydantic_events.py tests/integration/test_auto_verify_workflow.py::test_submit_with_passing_auto_verify tests/integration/test_auto_verify_workflow.py::test_submit_with_failing_must_auto_verify tests/integration/test_auto_verify_timing.py::test_passing_auto_verify_allows_transition tests/unit/test_step_auto_verify.py::test_step_auto_verify_failing_halts_run tests/unit/test_super_parent_service_mechanics.py::test_safety_net_save_applies_terminal_guard tests/integration/test_api_backward_transitions.py::test_transition_backward_basic 'tests/integration/test_executor_loop_invariant.py::TestExecutorLoopNeverLeavesActive::test_run_not_active_after_loop[NoTaskReason.ALL_COMPLETE]' -q`
  - `uv run pytest tests/integration/test_workflow_service.py tests/integration/test_event_sourced_workflow.py tests/unit/test_projectors.py tests/integration/test_check_and_apply_methods.py tests/unit/test_pydantic_events.py tests/integration/test_api_escalation.py::test_escalate_pauses_run_and_marks_requirement tests/integration/test_api_escalation.py::test_escalation_resume_after_human_intervention -q`
  - `uv run pyright src/orchestrator/workflow/service.py src/orchestrator/db/projections tests/integration/test_check_and_apply_methods.py`
  - `uv run ruff check` on touched files
  - `uv run pyright`
  - `uv run ruff check .`
  - `git diff --check`
- Residual note: direct `save_run()` paths remain in explicit non-core helpers, including recovery/escalation and other direct mutation surfaces.
- Gap report update:
  - Critical: attempt storage and runner totals still mutate attempts/tasks/runs directly.
  - High: fan-out, recovery, approval/clarification, and parent oversight helper paths still have direct read-model writes outside projectors.
  - High: projection rebuild checkpoints and startup recovery semantics remain incomplete.
  - Medium: event type name mismatches still weaken JSONL bootstrap/replay.
  - Medium: output batching still lacks a true timer-backed 100ms flush.

### Iteration 6

- Meta Planner chunk: event-source `AttemptStore` writes and run totals.
- Objective: remove the runner execution path's direct attempt/run mutations so prompts, output, errors, action logs, metrics, token usage, and runtime agent metadata persist through `events_v2` and projectors.
- Scope:
  - Refactor `AttemptStore` to append `AttemptUpdated` / run metadata events through the wired v2 event store and commit with the JSONL outbox helper.
  - Extend attempt update events and command payloads for prompts, action logs, and per-model token usage.
  - Project attempt prompt/output/error/action-log/token fields and increment run aggregate totals from attempt metric deltas.
  - Add a focused run metadata event that merges runtime metadata into `runner_config`.
  - Add real in-memory SQLite regression coverage for the runner-facing persistence path.
- Out of scope:
  - Removing the legacy `update_latest_attempt()` shim globally.
  - Refactoring fan-out, recovery, approval, clarification, or parent oversight direct mutation paths.
  - Fixing projection rebuild checkpoints/startup recovery.
  - Normalizing existing event type aliases.
  - Implementing timer-backed output batching.
- Builder result: `AttemptStore` now resolves the latest attempt through repository state, appends attempt/metadata events, lets projectors update attempts and runs, and no longer imports direct ORM models or the legacy mutation shim. `RunStateProjector` now handles attempt metric deltas and runtime metadata merges; `TaskStateProjector` persists the newly event-carried attempt fields. Regression coverage includes empty-read-model replay from `events_v2` for the attempt/metadata event stream.
- Verifier result: found no blocking gaps. Suggested adding replay coverage and direct payload assertions as non-blocking improvements; replay coverage was added before commit.
  Local verification passed:
  - `uv run pytest tests/integration/test_attempt_store_event_sourcing.py -q`
  - `uv run pytest tests/integration/test_attempt_store_event_sourcing.py tests/unit/test_command_handlers.py tests/unit/test_projectors.py tests/unit/test_pydantic_events.py -q`
  - `uv run pytest tests/integration/test_agent_executor.py::test_executor_persists_builder_prompt_before_execution tests/integration/test_agent_logs.py tests/integration/test_output_batching.py -q`
  - `uv run pyright src/orchestrator/runners/execution/attempt_store.py src/orchestrator/workflow/commands/attempt_and_fanout.py src/orchestrator/db/projections src/orchestrator/workflow/events src/orchestrator/workflow/__init__.py`
  - `uv run ruff check src/orchestrator/runners/execution/attempt_store.py src/orchestrator/workflow/commands/attempt_and_fanout.py src/orchestrator/db/projections src/orchestrator/workflow/events src/orchestrator/workflow/__init__.py tests/integration/test_attempt_store_event_sourcing.py`
  - `rg -n "update_latest_attempt|RunModel|TaskModel" src/orchestrator/runners/execution/attempt_store.py`
- Gap report update:
  - High: fan-out, recovery, approval/clarification, and parent oversight helper paths still have direct read-model writes outside projectors.
  - High: projection rebuild checkpoints and startup recovery semantics remain incomplete.
  - Medium: event type name mismatches still weaken JSONL bootstrap/replay.
  - Medium: output batching still lacks a true timer-backed 100ms flush.
