# Event-Driven Migration — Intent

## Goal

Migrate the Orchestrator from its current dual-write, state-mutation-first architecture to a true event-sourced system where the append-only event log is the single source of truth and all queryable state is derived via projections. [I-01 → S-00/T-01/R1, S-01/T-03/R2, S-02/T-02/R1, S-03/T-02/R1, S-04/T-02/R2, S-05/T-04/R3]

This eliminates the consistency gap between SQLite state and the JSONL journal, removes the need for ad-hoc recovery logic, and makes the system trivially replayable and auditable. [I-02 → S-01/T-03/R2, S-02/T-02/R1, S-05/T-04/R1]

## Scope

### In Scope

- Convert existing event dataclasses (~20 `WorkflowEvent` subclasses) to Pydantic models as a separate preparatory step before the main migration begins. [I-03a → S-00/T-01/R1]
- Replace the current `RunRepository` direct-state-mutation pattern with command handlers that emit events and projectors that update read models. [I-03 → S-03/T-02/R1, S-03/T-03/R1]
- Event-source entity creation: `RunCreated` and `TaskCreated` events capture the full initial state so the system can fully reconstruct from an empty database without a baseline snapshot. [I-03b → S-03/T-01/R3, S-03/T-03/R3]
- Consolidate the dual-write path (`EventStore` + `JsonlEventJournal`) into a single append-only event store (SQLite) that is the authoritative state source. JSONL continues as a real-time secondary write via an outbox observer pattern (keyed by event sequence number, idempotent on retry). [I-04 → S-01/T-01/R1, S-01/T-03/R2]
- Implement projection rebuilds: ability to reconstruct all read-model state from the event log alone (replaces `journal_replay.py` ad-hoc recovery). [I-05 → S-02/T-01/R1, S-02/T-02/R2]
- Migrate the signal system (`DbSignalTransport`, `_active_run_ids`) to be event-driven, eliminating the process-local active-run registry (resolves TD-03). [I-06 → S-04/T-02/R1, S-04/T-02/R2]
- Batch `AgentOutputEvent` writes to resolve the per-line session overhead (resolves TD-09). Default: 100ms flush interval, 50 lines batch size. [I-07 → S-05/T-01/R1, S-05/T-02/R1]
- Maintain all existing API contracts — no breaking changes to REST endpoints or WebSocket event shapes. [I-08 → S-01/T-03/R3, S-02/T-02/R3, S-03/T-03/R3, S-04/T-02/R3, S-05/T-04/R3]
- Maintain all existing CLI behavior. [I-09 → S-02/T-02/R2, S-05/T-04/R3]
- Preserve the `BufferingEmitter` pattern in `WorkflowEngine` for synchronous state-machine transitions. [I-10 → S-03/T-02/R1]

### Out of Scope

- Multi-worker / distributed deployment (TD-03 is resolved within single-process; true distributed event bus is future work). [I-11 → NO-REQ: explicitly out of scope]
- Changes to the frontend React UI beyond consuming existing WebSocket events. [I-12 → NO-REQ: explicitly out of scope]
- External routine fetching (S3-REMAINING). [I-13 → NO-REQ: explicitly out of scope]
- Redesign of the routine YAML schema. [I-14 → NO-REQ: explicitly out of scope]
- Changes to the agent runner protocol or agent implementations. [I-15 → NO-REQ: explicitly out of scope]


## Constraints

- All tests must pass after each phase — no intermediate breakage. [I-16 → S-00/T-01/R3, S-01/T-03/R3, S-02/T-02/R3, S-03/T-03/R3, S-04/T-02/R3, S-05/T-04/R3]
- Existing Alembic migrations must not be deleted or rewritten; new migrations add event-store tables and projection tables alongside existing ones until cutover. [I-17 → S-01/T-01/R1, S-02/T-01/R1]
- The JSONL journal format must remain readable by existing tooling during the transition. Post-migration, JSONL is written as a secondary output via an outbox observer (not inline in `_persist`), keyed by event sequence number for idempotent retry. The bootstrap script reads JSONL when the DB is empty. [I-18 → S-01/T-03/R1, S-05/T-03/R1]
- No mocking in tests — use real in-memory SQLite and real event stores. [I-19 → S-00/T-01/R3, S-01/T-02/R3, S-01/T-03/R3, S-02/T-02/R3, S-03/T-03/R2, S-04/T-01/R3, S-05/T-01/R2]
- Async by default — all new I/O paths must be async. [I-20 → S-01/T-02/R1, S-02/T-01/R1, S-03/T-01/R2, S-04/T-02/R2, S-05/T-01/R1]
- Import discipline: all new code respects the 9-module boundary (`api`, `cli`, `config`, `db`, `envfiles`, `git`, `runners`, `state`, `workflow`). [I-21 → S-01/T-03/R3, S-02/T-02/R3, S-03/T-03/R3, S-04/T-02/R3, S-05/T-04/R3]
- Pydantic for all event and projection models. [I-22 → S-00/T-01/R1, S-02/T-01/R1]
- The `WorkflowEngine` must remain pure (no I/O) — event emission stays synchronous and buffered. [I-23 → S-03/T-02/R1]

## Definition of Complete

- The system can be started with an empty database and fully reconstruct state from the event log alone (including entity creation via `RunCreated`/`TaskCreated` events). [I-24 → S-03/T-01/R3, S-03/T-03/R3, S-05/T-03/R1]
- `RunRepository` no longer performs direct state mutations; all writes go through event emission followed by projection updates. [I-25 → S-03/T-02/R1, S-03/T-03/R1]
- The `_active_run_ids` process-local set is removed; active-run tracking is derived from event state. [I-26 → S-04/T-02/R1]
- `AgentOutputEvent` persistence is batched (100ms flush / 50 lines batch, configurable), resolving TD-09. [I-27 → S-05/T-01/R1, S-05/T-02/R2]
- All existing integration and unit tests pass without modification (or with minimal adaptation to new imports). [I-28 → S-00/T-01/R3, S-01/T-03/R3, S-02/T-02/R3, S-03/T-03/R3, S-04/T-02/R3, S-05/T-04/R3]
- A new `projection rebuild` command exists in the CLI that reconstructs all read-model tables from the event log. Rebuild requires a server stop (brief downtime acceptable). [I-29 → S-02/T-02/R2]
- Event store append + projection update latency does not regress API response times by more than 10% on typical operations. [I-30 → S-05/T-04/R3]
- The dual-write path (`EventStore` + `JsonlEventJournal`) is unified: SQLite event store is the single source of truth, JSONL written as a secondary outbox observer. [I-31 → S-01/T-03/R2, S-05/T-04/R1]
- Recovery on startup reads from the event log, not from ad-hoc state snapshots. [I-32 → S-05/T-03/R1, S-05/T-03/R2]
