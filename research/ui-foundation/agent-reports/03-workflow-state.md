# Workflow And State Audit

## Purpose

Establish the implemented workflow-state reality for the closed
`workflow-state` scope without allocating canonical IDs or treating legacy
run/task state as graph-kernel state. This audit traces accepted signals through
the durable `events_v2` stream and SQL read-model projections, records legal
state transitions and execution-mode distinctions, and separates tested facts
from documentation and inference.

Status labels used below are **implemented**, **tested**,
**documented-only**, **inferred**, and **unclear**. An accepted asynchronous
request is not described as its eventual lifecycle result unless the consumer,
event, and projection path was inspected.

## Scope inspected

- Required framing: `AGENTS.md`, the approved design
  `docs/superpowers/specs/2026-07-23-ui-foundation-phase-0-3-design.md`, the
  closed `research/ui-foundation/catalog/scope.yaml`, and
  `research/ui-foundation/agent-reports/00-delegation-plan.md`.
- State declarations and legacy pure transitions:
  `src/orchestrator/config/enums.py`,
  `src/orchestrator/workflow/engine/transitions.py`, and
  `src/orchestrator/workflow/engine/engine.py`.
- Workflow command/service boundary, recovery, worktree transitions, and
  lifecycle signal acceptance:
  `src/orchestrator/workflow/service.py`,
  `src/orchestrator/workflow/commands/`, and
  `src/orchestrator/workflow/signals/`.
- Execution boundary and task selection: `src/orchestrator/executor.py`
  (re-export shim), `src/orchestrator/runners/executor.py`, and
  `src/orchestrator/workflow/signals/runtime.py`.
- Locking, durable append, projections, secondary JSONL sink, and recovery:
  `src/orchestrator/workflow/locks.py`,
  `src/orchestrator/db/access/event_store_v2.py`,
  `event_outbox.py`, `jsonl_outbox.py`, and `src/orchestrator/db/projections/`.
- Focused evidence was read and executed from workflow, signal, event-sourcing,
  projection-recovery, and workflow-service tests. Graph-specific lifecycle
  references were inspected only to distinguish mode behavior, not to audit the
  graph kernel.

## Key findings

### State carriers and legal transitions

| Provisional key | Finding | Status and evidence |
|---|---|---|
| `WF-run-status` | The legacy persisted run vocabulary is `draft`, `active`, `paused`, `stopping`, `completed`, `failed`, and `cancelled`. The terminal set is completed/failed/cancelled, but graph mode has a narrow failed-reopen exception. | implemented, tested: `config/enums.py::RunStatus`, `TERMINAL_RUN_STATUSES`; `service.py::resume_run`, `apply_resume_run`; `test_signal_queue.py` and `test_workflow_engine.py`. |
| `WF-run-edges` | Legacy engine edges are `draft -> active`; `active -> stopping`; `active|stopping -> paused` (pause is idempotent once paused); `paused -> active`; `active|paused|stopping -> cancelled`; and active-only completion/failure. The service implements pause as visible `active -> stopping` followed by queued `stopping -> paused`. | implemented, tested: `engine.py::{start_run,stop_run,pause_run,resume_run,cancel_run}`; `service.py::{apply_start_run,apply_stop_run,pause_run,apply_pause_run,apply_complete_run,_apply_terminal_stop}`; `test_signal_queue.py::test_pause_active_run_enters_stopping_then_paused`. |
| `WF-task-status` | Legacy task statuses are `pending`, `building`, `pending_user_action`, `verifying`, `recovering`, `fan_out_running`, `completed`, and `failed`. `VALID_TRANSITIONS` documents ordinary adjacency, while helper transitions add qualified paths. | implemented: `enums.py::TaskStatus`; `transitions.py::VALID_TRANSITIONS`, `transition_*`. |
| `WF-task-edges` | Builder start creates an attempt and permits pending/building/verifying/pending-user-action/recovering -> building. Checklist gate permits building -> verifying. Verification yields completed, failed at attempt limit, or a new building revision attempt. Clarification is building -> pending-user-action -> building; approval is verifying -> pending-user-action -> completed/building/failed; recovery starts only from verifying. Fan-out parent is pending -> fan-out-running, then verifying/completed/failed. | implemented, tested: `transitions.py::{transition_to_building,transition_to_verifying,transition_after_verification,transition_to_pending_clarification,transition_from_clarification,transition_to_pending_approval,transition_from_approval,transition_to_recovering}`; `test_workflow_engine.py`; `test_workflow_service.py` recovery cases. |
| `WF-force-accept` | Qualified force-accept bypasses grades and moves **failed, building, or verifying -> completed**. It is not legal from pending, pending-user-action, recovering, fan-out-running, or completed. The completion cascade can reactivate a failed run in memory only to recalculate remaining work, then emits the resulting run status. | implemented, tested: `transitions.py::transition_force_accept`; `engine.py::force_accept`; `tests/unit/test_transitions_recovering_force_accept.py::TestTransitionForceAccept::{test_valid_from_failed,test_valid_from_building,test_valid_from_verifying,test_invalid_from_pending,test_invalid_from_completed,test_invalid_from_recovering}`. `tests/integration/test_api_tasks.py` remains graph-mode endpoint-rejection evidence only, not proof of these legacy pure-transition edges. |
| `WF-step-run-cascade` | A step completes only when all top-level (not fan-out-child) tasks are terminal. Completion advances index, applies conditional forward/back edges or skips, then can make a run completed or failed. A failed step normally fail-stops unless configured transitions route it. | implemented, tested: `transitions.py::{is_step_complete,step_has_failure,check_step_progression}`; `engine.py::complete_verification`; `test_workflow_engine.py::{test_complete_verification_advances_step,test_run_auto_completes_when_all_steps_done,test_run_auto_fails_when_task_fails}`. |

**implemented:** `pending_user_action`, `recovering`, and `fan_out_running` are
task states, not run states. Step state is instead composed from `completed`,
`skipped`, approval data, and the current run index; it is not an independent
status enum. **implemented:** attempt `outcome` is a nullable free-form value,
not a closed state machine. Evidence: `config/enums.py::TaskStatus`,
`state/models.py::{StepState,Attempt}`.

### Accepted signal through durable event and projection

The production path is **implemented** and asynchronous, but it is not one
atomic handler-plus-acknowledgement transaction:

1. **implemented, tested:** A lifecycle service method validates the current
   projected run, appends `SignalEnqueued` through
   `EventSignalTransport.enqueue`, and commits the enqueue via
   `commit_with_event_outbox`. `start_run`, `resume_run`, and `cancel_run`
   return the **pre-transition** run. `pause_run` first durably applies
   `active -> stopping`, then queues PAUSE and returns stopping. Evidence:
   `service.py::{start_run,pause_run,resume_run,cancel_run}`;
   `signals.py::EventSignalTransport.enqueue`;
   `test_signal_queue.py::{test_run_start_signal_consumed_draft_to_active,test_pause_active_run_enters_stopping_then_paused}`.
2. **implemented, tested:** `SignalConsumer._find_pending_run_ids` and
   `_fetch_next_event_signal` identify unacknowledged `signal_enqueued` positions.
   It serializes FIFO delivery within a run and may dispatch different run IDs
   concurrently. Evidence: `consumer.py::{_tick,_process_run,_fetch_next_event_signal}`;
   `test_signal_queue.py::test_concurrent_runs_process_signals_independently`.
3. **implemented:** `_handle_signal` routes `RUN_START`, `RESUME`, `PAUSE`,
   `CANCEL`, `ACTIVITY_COMPLETED`, and `ACTIVITY_VERIFIED` to an apply method.
   Those apply methods append transition events and **commit internally before
   returning**. Evidence: `consumer.py::{_handle_signal,_dispatch_event_signal}`;
   `service.py::{apply_start_run,apply_pause_run,apply_resume_run,apply_cancel_run,apply_submission,apply_verification}`.
4. **implemented, tested:** each event append flushes an `events_v2` row and
   invokes `ProjectionRegistry` in that append's SQL transaction; projectors
   update run/step and task/attempt read models. Evidence:
   `event_store_v2.py::SqliteEventStore.append`; `projections/registry.py::__call__`;
   `test_event_sourced_workflow.py::test_empty_db_rebuild`.
5. **implemented, unexercised for the inter-commit crash window:** only after
   the handler returns does `_dispatch_event_signal` append `SignalProcessed`
   and commit the consumer session. Since an `apply_*` may already have committed
   lifecycle effects (and may fail while flushing its post-commit observer), a
   crash or post-commit observer failure can leave the transition projected but
   the enqueued position unmarked. On redelivery, idempotent apply paths or
   `InvalidTransitionError` stale handling are relied on to avoid repeating the
   transition; stale handling appends the marker in a fresh session. Evidence:
   `consumer.py::_dispatch_event_signal`; `service.py::{apply_start_run,apply_pause_run,apply_resume_run,_apply_terminal_stop}`;
   `event_outbox.py::commit_with_event_outbox`; `jsonl_outbox.py::JsonlOutboxObserver`.

**implemented, tested — acceptance/result distinction.** `POST /start` returns 202 while
the row stays `draft`; consuming the signal makes it `active`.
`tests/integration/test_signal_queue.py::test_run_start_signal_consumed_draft_to_active`
asserts both observations. The analogous resume test proves paused before drain
and active after it. The visible stopping intermediate is deliberately different:
the pause request itself persists `stopping`, whereas `paused` waits for the
consumer. Therefore an API acceptance response or queued event is durable
command evidence, not proof of the requested resulting state.

### Durable authority, projection, and recovery

- **implemented, tested:** `events_v2` is the durable source for run/task
  projection reconstruction. The registry expands legacy creation snapshots,
  applies relevant projectors synchronously after append, and aborts the append
  transaction when a projector raises. `test_event_sourced_workflow.py::test_empty_db_rebuild`
  deletes read-model rows and rebuilds matching run/step/task/attempt state from
  stored events; `test_projection_recovery.py::test_full_lifecycle_rebuild`
  restores a corrupted run status from the final status event.
- **implemented, tested:** consumer startup rebuilds its lifecycle projector,
  discovers unprocessed enqueued positions, and redelivers inactive runs.
  `test_signal_redelivery.py::test_startup_redelivery_processes_pending_signal`
  proves processing and acknowledgement; `test_startup_redelivery_skips_active_runs`
  proves its in-memory active guard.
- **implemented, tested in ordinary stale-signal cases; unexercised for an
  apply-committed/marker-missing crash:** stale `InvalidTransitionError`,
  retired-runner errors, and missing runs are intentionally acknowledged as
  discarded signals. This avoids indefinite retries, but the durable record
  distinguishes enqueued and processed positions rather than recording a typed
  rejection outcome. Evidence: `consumer.py::_dispatch_event_signal`;
  `test_signal_consumer.py::test_stale_activity_signal_for_paused_run_does_not_block_resume`.
- **implemented:** runtime executor safety pauses before entering the agent loop
  (`executor_not_started`), clears that marker on its first loop iteration,
  pauses on cancellation as `server_shutdown`, pauses unexpected errors, and
  finally pauses any still-active run as `executor_exited`. These are service
  lifecycle writes, not new task states.

### Retries, locks, cancellation, and races

- **implemented, tested — retries:** failed verification before `max_attempts` creates a new attempt
  and returns to building; at the limit it fails the task. Rejected approval has
  the same retry-or-fail structure. Recovery retry/skip/abandon is a separate
  recovering-state mechanism; it must not be collapsed into ordinary verifier
  revision. `check_submission`/`apply_submission` split the REST path: the
  former synchronously performs auto-verify/checklist validation and persists
  evidence, while the latter applies building -> verifying after the signal.
- **implemented; test coverage of lock failure paths is unclear — separate lock
  boundaries:** production `WorkflowService.start_task` first gets the run
  (thereby validates run existence) and rejects a non-`ACTIVE` run **before** it
  builds/calls the engine. It does not validate task identity or future-step
  eligibility itself. Inside the direct `WorkflowEngine.start_task` boundary,
  `InMemoryLockManager.acquire` occurs before task lookup, future-step validation,
  and `transition_to_building`; a direct engine caller can therefore retain a
  lock when a later task/step/transition check raises because this method has no
  exception-safe `finally` release. The manager is keyed only by task ID, has a
  five-minute passive-expiry check, lets the same agent refresh/acquire, and only
  the owner may release; `is_locked` does not delete expired entries. Terminal
  `complete_verification` releases only completed/failed locks and retains a
  revision lock. The monitor can release a default-agent lock after detected
  death. Evidence: `service.py::start_task`; `engine.py::{start_task,complete_verification}`;
  `locks.py::InMemoryLockManager`; `runners/runtime/monitor.py::on_agent_died`.
  This is process-local coordination, not a durable DB lease.
- **implemented, tested in paused stale-activity behavior; unclear for every
  mid-agent ordering — cancellation/pause race:** a pause request writes `stopping` before its
  PAUSE signal. The active executor may still be mid-agent work in that interval;
  the consumer removes the registered workflow and applies paused later. Activity
  signals delivered without an active workflow are ignored when the run is
  paused, preventing a stale completion/verification from advancing it after a
  pause. Cancel applies terminal state through the queue; graph cancellation
  additionally drives the graph kernel to terminal before `apply_cancel_run`.
- **implemented, tested for independent runs; inferred for all SQLite scheduling
  interleavings — concurrency:** signal FIFO is per run, not globally serial. The consumer
  creates one processing task per run, while `SqliteEventStore` assigns
  aggregate versions under retrying optimistic concurrency. Fan-out expansion
  explicitly catches `StaleDataError`, reloads already-created children, and
  avoids duplicating expansion in that path. No client-provided run version is
  required for legacy lifecycle requests.

### Legacy versus graph mode

| Dimension | Legacy execution | Graph execution | Status and exact evidence |
|---|---|---|
| Work driver | `RunWorkflow` selects a current step/task and runs the builder/verifier cycle. | `SignalConsumer` arms a re-enterable graph driver; it resumes durable graph position without reseeding. | implemented: `runners/executor.py::_run_agent_loop`; `consumer.py::{_handle_run_start,_handle_resume,arm_graph_run}`. |
| Task state model | `TaskStatus`, attempts, checklist/grade gates, human clarification/approval, and fan-out state are active mechanisms. | Graph kernel node/run state is distinct; no scoped proof equates graph node with task or graph run state with `TaskStatus`. | implemented for legacy; unclear for conversion: `enums.py::TaskStatus`; `consumer.py::_handle_resume`; graph equivalence absent from inspected boundaries. |
| Resume from failed | Failed legacy runs are not resumable through lifecycle resume. | Failed graph row may reopen, but graph-kernel `failed -> resuming -> active` commands are also required. | implemented: `service.py::{resume_run,apply_resume_run}`; graph sequence documented in `apply_resume_run` docstring; graph-kernel legality not independently tested here. |
| Cancel | Removes legacy workflow registration and applies `cancelled`. | Consumer drives graph cancellation to terminal, disarms graph driver, then applies row-level cancelled. | implemented: `consumer.py::_handle_cancel`; `graph_driver.py::apply_graph_cancel_until_terminal`; graph terminal ordering unexercised here. |
| States only in mode | `recovering`, `fan_out_running`, step index/condition progression, and checklist verifier cycle are legacy carriers. | Graph topology and `resuming` are graph concepts, not `RunStatus` values. | implemented for named legacy enum states; documented-only in this report for graph `resuming`: `enums.py::{RunStatus,TaskStatus}`; `service.py::apply_resume_run`. |

**inferred from the implemented boundary:** shared row-level `RunStatus` is a
projection/control boundary, not evidence of a shared full execution topology.

### JSONL authority conflict

**documented-only versus implemented conflict:** `AGENTS.md` states that transitions are
logged to JSONL first and recovery reconstructs from history. Executable code
does the opposite ordering: `SqliteEventStore.append` flushes `events_v2`, runs
projections in the SQL transaction, and queues the JSONL observer;
`commit_with_event_outbox` commits SQL before `JsonlOutboxObserver` writes JSONL.
`drain_committed_events_to_journal` explicitly calls the event table
authoritative after a post-commit JSONL failure and reconciles missing positions.
The current durable implementation is consequently SQL-event-first with JSONL
as a recoverable, idempotent secondary sink. This audit does not erase the
documentation contradiction.

### Closed-scope demand disposition

| Scope demand | Audit disposition |
|---|---|
| `jobs.J1.current-constraint` | Partial: pause reason, last error, task status, and gates are present, but no one authoritative “current constraint” classifier is implemented. |
| `jobs.J1.human-wait-state` | Partial/current by legacy carrier: `pending_user_action`, pending approval/clarification data, and pause reasons identify several waits; graph waits are distinct. |
| `jobs.J2.blocked-reason` | Partial: gate/pause/error strings and task states exist, without a normalized cross-mode blocked-reason contract. |
| `jobs.J2.attempts-left`, `jobs.J8.retries` | Partial/current for legacy tasks: `current_attempt` and `max_attempts` support arithmetic, but no shared graph/legacy retry metric or projection was found. |
| `jobs.J4.state-transitions`, `jobs.J4.retries-rejections` | Current for the evidenced legacy transition/event paths; graph topology transitions require the separate graph-runtime evidence and must remain distinct. |
| `jobs.J6.current-failure`, `jobs.J8.outcome` | Partial: errors, pause reasons, task failure, terminal row status, and attempt outcomes exist, but no unified current-failure/outcome semantics spans both modes. |
| `feedback.resulting-state`, `feedback.next-activity` | Partial: durable projections make resulting state queryable after processing; acceptance responses do not consistently provide it or next activity. |

## Important uncertainties

1. **Blocking state-model uncertainty:** the graph kernel's complete legal state
   graph was not normalized here. Only its integration/reopen/cancel distinction
   was examined, so a downstream model must not infer graph edges from legacy
   `RunStatus` or `TaskStatus`.
2. **Lock durability uncertainty:** the only inspected task lock is in-memory.
   Its behavior across multiple processes, server restart, and timeout while an
   agent is still executing is not established as safe distributed locking.
3. **Signal result uncertainty:** `SignalProcessed` proves consumer handling
   completed or a stale signal was discarded; it is not a typed durable
   acceptance/rejection/result record for every queued command.
4. **Signal acknowledgement atomicity uncertainty:** `apply_*` commits transition
   effects before `_dispatch_event_signal` appends `SignalProcessed`. A crash or
   `CommittedSecondaryOutputError` in that interval can leave projected state
   applied without an acknowledgement marker. Redelivery relies on idempotent
   transition methods or the consumer's stale-transition discard path; exact
   coverage of this inter-commit failure is unexercised.
5. **Recovery breadth uncertainty:** startup redelivery is tested for pending
   signals and projection rebuilding is tested for workflow events. Whether all
   executor/agent subprocess side effects are reconstructable after a crash is
   not proved by these tests.
6. **Run-state documentation uncertainty:** `AGENTS.md` debugging examples use
   `queued`, while executable `RunStatus` uses `draft` and adds stopping and
   cancelled. The enum establishes the scoped domain vocabulary; all API
   readback variants were not independently re-audited here.

## Conflicts found

1. **CON-WF-01 — JSONL-first documentation conflicts with SQL-first code.**
   `AGENTS.md` requires JSONL-first transition authority; the event store,
   projection registry, outbox commit sequence, and journal reconciler establish
   committed `events_v2` as authoritative after secondary failure.
2. **CON-WF-02 — single-queue lifecycle invariant has a CLI exception.**
   `AGENTS.md` says all lifecycle transitions use the signal queue, but the
   independently inspected API/actions report identifies
   `cli.runs.start_run` directly invoking `WorkflowService.apply_start_run`.
   REST acceptance timing and that CLI behavior are not one contract.
3. **CON-WF-03 — handler-plus-marker atomicity claim is false.**
   `SignalConsumer._dispatch_event_signal` appends `SignalProcessed` after the
   handler returns, but `WorkflowService.apply_*` commits its lifecycle effects
   internally. A crash or post-commit observer failure after that commit can
   leave an applied projection without the marker. Redelivery relies on
   idempotency/stale-transition handling, not one atomic handler-plus-marker
   transaction.
4. **CON-WF-04 — direct-engine lock acquisition precedes only its later
   validations.** Production `WorkflowService.start_task` verifies run existence
   and `ACTIVE` status before calling the engine. The direct
   `WorkflowEngine.start_task` then obtains the in-memory lock before task
   lookup, future-step validation, and transition success, without a `finally`
   release. The documented pessimistic-lock intent therefore does not prove
   exception-safe release for direct-engine task/step/transition failures.
5. **CON-WF-05 — terminality differs by mode.** `TERMINAL_RUN_STATUSES` includes
   failed, while graph-mode service logic permits a qualified failed reopen.
   Failed must not be called absolutely terminal without its mode qualifier.

## Decisions required

1. Reconcile the authoritative architecture statement: retain SQL event-store
   authority plus journal reconciliation, or redesign to genuinely make JSONL
   first. Do not document both as current.
2. Decide whether the process-local task lock satisfies the required
   pessimistic-lock invariant for multi-process/restart operation; if not,
   commission a separate durable lease design rather than implying it exists.
3. Define a typed queued-command outcome record if UI action feedback must prove
   accepted, rejected/stale, resulting state, and next activity without polling.
4. Specify a cross-mode state contract only after graph-runtime evidence defines
   its own topology and conversion boundaries. Preserve legacy task, graph node,
   and run-row concepts as distinct until then.
5. Resolve whether CLI lifecycle direct application is allowed as a documented
   compatibility path or must conform to the signal-queue acceptance contract.

## Artifact paths

- Created: `research/ui-foundation/agent-reports/03-workflow-state.md`.
- Created handoff/audit record: `.superpowers/sdd/task-5-audit-report.md`.
- No canonical catalog, source, test, implementation, database, or git files
  were modified by this task.

## Evidence pointers

Primary implementation evidence:

- `src/orchestrator/config/enums.py::{RunStatus,TaskStatus,TERMINAL_RUN_STATUSES}`.
- `src/orchestrator/workflow/engine/transitions.py::{VALID_TRANSITIONS,transition_to_building,transition_to_verifying,transition_after_verification,check_step_progression}`.
- `src/orchestrator/workflow/engine/engine.py::{start_run,stop_run,pause_run,resume_run,cancel_run,start_task,complete_verification}`.
- `src/orchestrator/workflow/service.py::{start_run,pause_run,resume_run,cancel_run,apply_start_run,apply_pause_run,apply_resume_run,apply_cancel_run,check_submission,apply_submission,check_verification,apply_verification}`.
- `src/orchestrator/workflow/signals/signals.py::EventSignalTransport` and
  `src/orchestrator/workflow/signals/consumer.py::{_process_run,_dispatch_event_signal,_handle_signal,_redeliver_on_startup}`.
- `src/orchestrator/workflow/signals/runtime.py::{RunWorkflow.run,_run_loop,resolve_no_task_action}`.
- `src/orchestrator/runners/executor.py::{_find_next_task,_execute_task,_execute_fan_out}` and `src/orchestrator/workflow/locks.py::InMemoryLockManager`.
- `src/orchestrator/db/access/event_store_v2.py::{SqliteEventStore.append,create_wired_event_store_v2}`;
  `event_outbox.py::commit_with_event_outbox`; `jsonl_outbox.py::{JsonlOutboxObserver,drain_committed_events_to_journal}`.
- `src/orchestrator/db/projections/{registry,run_state,task_state,run_lifecycle}.py`.

Decisive test evidence executed successfully:

```text
uv run pytest tests/unit/test_workflow_engine.py tests/unit/test_signal_consumer.py tests/unit/test_signal_redelivery.py tests/integration/test_signal_queue.py tests/integration/test_event_sourced_workflow.py tests/integration/test_projection_recovery.py tests/integration/test_workflow_service.py -q -n 0
110 passed in 8.91s
```

Key assertions include:

- `test_signal_queue.py::test_run_start_signal_consumed_draft_to_active`,
  `test_resume_signal_consumed_paused_to_active`, and
  `test_pause_active_run_enters_stopping_then_paused`.
- `test_signal_redelivery.py::test_startup_redelivery_processes_pending_signal`
  and `test_startup_redelivery_skips_active_runs`.
- `test_event_sourced_workflow.py::test_empty_db_rebuild` and
  `test_projection_recovery.py::test_full_lifecycle_rebuild`.
- `test_workflow_engine.py::test_event_sequence`,
  `test_complete_verification_revision`, and
  `test_run_auto_fails_when_task_fails`.
- `test_workflow_service.py::{test_trigger_recovery_projects_pause_and_attempt_snapshot_without_save_run,test_complete_recovery_retry_projects_attempts_and_resumes_without_save_run}`.

## Recommended next delegation

1. Delegate a narrow graph-runtime/state audit to enumerate graph command
   legality, node/run states, and the failed-reopen sequence, then reconcile it
   with this report without aliasing node/task/step/region.
2. Delegate durable lock and external-side-effect recovery analysis before any UI
   represents an execution as safely exclusive or exactly-once.
3. Normalize the SQL-event-first/JSONL-first conflict as an explicit canonical
   conflict and require architecture adjudication before deriving recovery or
   audit-history claims.
4. Have action/state synthesis model queued acceptance separately from applied
   result, with evidence positions and stale-discard behavior preserved.
