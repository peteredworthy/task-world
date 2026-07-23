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
| `WF-step-run-cascade` | A step completes only when all top-level (not fan-out-child) tasks are terminal. Completion advances index, applies conditional forward/back edges or skips, then can make a run completed or failed. A failed step normally fail-stops unless configured transitions route it. | implemented, tested: `transitions.py::{is_step_complete,step_has_failure,check_step_progression}`; `engine.py::complete_verification`; `test_workflow_engine.py::{test_complete_verification_advances_step,test_run_auto_completes_when_all_steps_done,test_run_auto_fails_when_task_fails}`. |

`pending_user_action`, `recovering`, and `fan_out_running` are task states, not
run states. Step state is instead composed from `completed`, `skipped`, approval
data, and the current run index; it is not an independent status enum. Attempt
`outcome` is a nullable free-form value rather than a closed state machine.

### Accepted signal through durable event and projection

The production path is durable and asynchronous:

1. A lifecycle service method validates the current projected run and appends a
   `SignalEnqueued` event through `EventSignalTransport.enqueue`; it commits via
   `commit_with_event_outbox`. `start_run`, `resume_run`, and `cancel_run` return
   the **pre-transition** run. `pause_run` is distinct: it first durably applies
   `active -> stopping`, then returns the stopping run after queueing `PAUSE`.
2. `SignalConsumer._find_pending_run_ids` and
   `_fetch_next_event_signal` identify unacknowledged `signal_enqueued` rows by
   global position. It runs one FIFO drain task per run ID and may process
   different run IDs concurrently.
3. `_handle_signal` sends `RUN_START`, `RESUME`, `PAUSE`, `CANCEL`,
   `ACTIVITY_COMPLETED`, or `ACTIVITY_VERIFIED` to the corresponding apply
   method. The apply method emits a `RunStatusChanged` or task/attempt event.
4. `SqliteEventStore.append` flushes an `events_v2` row, then invokes
   `ProjectionRegistry` in the same SQLAlchemy transaction. `RunStateProjector`
   updates `runs`/`steps`; `TaskStateProjector` updates `tasks`/`attempts`;
   `RunLifecycleProjector` refreshes the consumer's in-memory activity view.
5. Only after the handler succeeds does `_dispatch_event_signal` append
   `SignalProcessed` in that same session and commit. Thus a successful
   acknowledged signal has both handler effects and its processed marker in the
   database transaction. If stale, the consumer rolls back handler work and
   writes a processed marker in a fresh transaction; if another exception occurs
   it writes no marker, permitting redelivery.

**Acceptance/result distinction (tested).** `POST /start` returns 202 while
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
- **implemented:** stale `InvalidTransitionError`, retired-runner errors, and
  missing runs are intentionally acknowledged as discarded signals. This avoids
  indefinite retries, but it means the durable record distinguishes enqueued and
  processed positions rather than recording a typed rejection outcome.
- **implemented:** runtime executor safety pauses before entering the agent loop
  (`executor_not_started`), clears that marker on its first loop iteration,
  pauses on cancellation as `server_shutdown`, pauses unexpected errors, and
  finally pauses any still-active run as `executor_exited`. These are service
  lifecycle writes, not new task states.

### Retries, locks, cancellation, and races

- **Retries:** failed verification before `max_attempts` creates a new attempt
  and returns to building; at the limit it fails the task. Rejected approval has
  the same retry-or-fail structure. Recovery retry/skip/abandon is a separate
  recovering-state mechanism; it must not be collapsed into ordinary verifier
  revision. `check_submission`/`apply_submission` split the REST path: the
  former synchronously performs auto-verify/checklist validation and persists
  evidence, while the latter applies building -> verifying after the signal.
- **Locks:** `InMemoryLockManager` is keyed only by task ID, has a five-minute
  default expiry, lets the same agent refresh/acquire, and only the owner may
  release. `WorkflowEngine.start_task` acquires before its transition; terminal
  `complete_verification` releases only for completed/failed, retaining a lock
  across a revision. The monitor attempts to release default-agent locks after
  agent death. This is process-local, time-expiring pessimistic coordination,
  not a durable DB lease; restart/process races therefore remain outside its
  proven protection.
- **Cancellation/pause race:** a pause request writes `stopping` before its
  PAUSE signal. The active executor may still be mid-agent work in that interval;
  the consumer removes the registered workflow and applies paused later. Activity
  signals delivered without an active workflow are ignored when the run is
  paused, preventing a stale completion/verification from advancing it after a
  pause. Cancel applies terminal state through the queue; graph cancellation
  additionally drives the graph kernel to terminal before `apply_cancel_run`.
- **Concurrency:** signal FIFO is per run, not globally serial. The consumer
  creates one processing task per run, while `SqliteEventStore` assigns
  aggregate versions under retrying optimistic concurrency. Fan-out expansion
  explicitly catches `StaleDataError`, reloads already-created children, and
  avoids duplicating expansion in that path. No client-provided run version is
  required for legacy lifecycle requests.

### Legacy versus graph mode

| Dimension | Legacy execution | Graph execution |
|---|---|---|
| Work driver | `RunWorkflow` selects a current step/task and runs the builder/verifier cycle. | `SignalConsumer` arms a re-enterable graph driver; it must resume from durable graph position and not seed again. |
| Task state model | `TaskStatus`, attempts, checklist/grade gates, human clarification/approval, and fan-out state are active mechanisms. | Graph kernel node/run state is a distinct model; no proof equates graph node with task or graph run state with `TaskStatus`. |
| Resume from failed | Failed legacy runs are not resumable through lifecycle resume. | `WorkflowService.resume_run` permits failed graph run reopening, but documentation in the method requires graph-kernel `failed -> resuming -> active` commands as well. |
| Cancel | Removes legacy workflow registration and applies `cancelled`. | Consumer first calls `apply_graph_cancel_until_terminal`, disarms graph driver, then applies the same row-level cancelled status. |
| States only in mode | `recovering`, `fan_out_running`, step index/step condition progression, and checklist verifier cycle are legacy task-flow carriers. | Graph lifecycle topology and graph `resuming` are graph-mode concepts; they are not declared `RunStatus` values. |

The shared row-level `RunStatus` is therefore a projection/control boundary, not
evidence of a shared full execution topology.

### JSONL authority conflict

There is a material source conflict. `AGENTS.md` states that transitions are
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
4. **Exactly-once side-effect uncertainty:** durable signal handler and marker
   commit together, but pre-commit worktree/agent side effects and post-commit
   JSONL output do not become one atomic external transaction.
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
3. **CON-WF-03 — “exactly once” wording is too broad if applied to the whole
   operation.** `SignalConsumer` atomically marks successful handler processing
   in the DB, yet JSONL is post-commit and agents/worktrees are external. It is
   valid only for the scoped durable handler/marker transaction, not every
   observable side effect.
4. **CON-WF-04 — terminality differs by mode.** `TERMINAL_RUN_STATUSES` includes
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
