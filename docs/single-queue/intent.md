# Single-Queue Signal Model

## Purpose

Replace the dual-path signal routing with a single, uniform queue through which all
lifecycle signals pass. In the current model `WorkflowService` inspects a process-local
`_active_run_ids` set at enqueue time and either writes to the `pending_signals` table
or mutates the DB directly. This document specifies the target model and what must be
true when the work is complete.

---

## Goals

- Eliminate sender-side routing: all lifecycle signals (start, pause, resume, cancel) are enqueued to `pending_signals` unconditionally, removing the `has_active_workflow` branch in `WorkflowService`. [I-01 → S-03/T-01/R1]
- Introduce a single consumer that reads from the queue and is the sole entity creating/destroying `RunWorkflow` instances. [I-02 → S-02/T-01/R1, S-02/T-01/R2]
- Add a `STOPPING` run state so that pause/cancel of an active run is observable and race-free. [I-03 → S-01/T-01/R3, S-06/T-01/R5]
- Move active-run registry management (`register_active_run`, `unregister_active_run`) exclusively into the consumer module, removing it from the public API surface. [I-04 → S-04/T-01/R1, S-04/T-01/R2]
- Add signal delivery tracking (`delivered_at`, `handled_at`) to support crash recovery and redelivery. [I-05 → S-01/T-01/R2, S-02/T-01/R3]
- Lay groundwork for future multi-worker separation without requiring it now. [I-06 → NO-REQ: emergent property of the single-queue design; no dedicated step needed]

---

## Scope

### In Scope

- Restructure `pending_signals` table: integer PK, `delivered_at`/`handled_at` columns, ordering by PK not `created_at`. [I-07 → S-01/T-01/R1, S-01/T-01/R2]
- Add `STOPPING` to `RunStatus` with defined transitions (ACTIVE -> STOPPING -> PAUSED/FAILED). [I-08 → S-01/T-01/R3]
- Add `RUN_START` signal type; make `RESUME` signal functional (not a no-op). [I-09 → S-01/T-01/R5, S-03/T-01/R1]
- Rewrite `WorkflowService.start_run()`, `pause_run()`, `resume_run()`, `cancel_run()` to always enqueue signals instead of branching. [I-10 → S-03/T-01/R1]
- Remove `has_active_workflow` usage from `WorkflowService`, routers, and all API-request code paths. [I-11 → S-03/T-01/R5]
- Build the consumer loop: serial per-run FIFO processing, concurrent across runs, startup redelivery of unhandled signals. [I-12 → S-02/T-01/R1, S-02/T-01/R4]
- Remove `unregister_active_run()` call from `RunWorkflow.handle_pause`. [I-13 → S-03/T-01/R4]
- Add `scripts/check_signal_routing.py` pre-commit guard to prevent registry function imports outside the consumer module. [I-14 → S-05/T-01/R1, S-05/T-01/R2]
- Add AGENTS.md rules for signal queue and runner isolation. [I-15 → S-05/T-01/R3]
- Alembic migration for `pending_signals` schema changes and `STOPPING` status. [I-16 → S-01/T-01/R1]
- Update `retry_fan_out_child()` to remove its `has_active_workflow` check. [I-17 → S-03/T-01/R2]

### Out of Scope

- Separate runner processes (future work; this change makes it easier but does not do it). [I-18 → NO-REQ: explicitly out of scope]
- Event broadcast decoupling (`EventBroadcaster` / WebSocket/SSE). [I-19 → NO-REQ: explicitly out of scope]
- Performance optimization of the queue. [I-20 → NO-REQ: explicitly out of scope]

---

## Constraints

- All existing tests must continue to pass after each phase of implementation. [I-21 → S-06/T-01/R1]
- The `STOPPING` state must not be a valid source for resume, restart, or duplicate pause/cancel signals via the API. [I-22 → S-01/T-01/R4]
- `RunWorkflow` and `AgentRunnerExecutor` must not access `app.state` or any FastAPI application-context object directly; dependencies are injected at construction. [I-23 → S-05/T-01/R5]
- No new process-local shared state that crosses the API/executor boundary. [I-24 → S-05/T-01/R3]
- The consumer must handle crash recovery: signals with `delivered_at IS NOT NULL AND handled_at IS NULL` for inactive runs are re-delivered on startup. [I-25 → S-02/T-01/R4]
- `created_at` is retained on `pending_signals` for audit but must not be used for ordering. [I-26 → S-01/T-01/R2]

---

## Definition of Complete

- All lifecycle signals (start, pause, resume, cancel) are routed through `pending_signals` with no direct-DB branching in `WorkflowService`. [I-27 → S-03/T-01/R1, S-06/T-01/R4]
- `has_active_workflow()` is not called from `WorkflowService`, routers, or any API-initiated code path. [I-28 → S-03/T-01/R5, S-06/T-01/R3]
- `register_active_run()` and `unregister_active_run()` are only called from the consumer module. [I-29 → S-04/T-01/R1, S-04/T-01/R2]
- The `STOPPING` state exists in `RunStatus` and the defined transitions (R5-R9 from the PRD) are enforced. [I-30 → S-01/T-01/R3, S-01/T-01/R4]
- The consumer processes signals per-run FIFO, sets `delivered_at`/`handled_at`, and redelivers unhandled signals on startup. [I-31 → S-02/T-01/R1, S-02/T-01/R3, S-02/T-01/R4]
- `scripts/check_signal_routing.py` runs as a pre-commit hook and catches disallowed imports/calls outside the consumer module. [I-32 → S-05/T-01/R1, S-05/T-01/R2, S-05/T-01/R4]
- AGENTS.md contains the four signal-queue and runner-isolation rules. [I-33 → S-05/T-01/R3]
- All existing tests pass after each phase. [I-34 → S-06/T-01/R1]
- An Alembic migration exists for the `pending_signals` schema changes and `STOPPING` status value. [I-35 → S-01/T-01/R1]
- `RUN_START` and `RESUME` signals are functional and handled by the consumer (not no-ops). [I-36 → S-02/T-01/R2, S-06/T-01/R4]
