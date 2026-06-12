# Slice 2.1 — Event store + outbox (BUILDER)

You are the BUILDER agent for slice 2.1 of the task-world execution-graph kernel — the first Phase 2 (effectful shell) slice.

## Ground truth (read these first, in order)

1. `docs/graph-approach/execution-graph-prd-plus.md` — §12.1 (event envelope, ordering), §12.2 (command handling shape), §12.3 (agent side effects, crash table, ScheduleTick), §13 (runtime recovery policy), §27.4 (failure-injection tests), §30–§31 (storage/implementation boundaries)
2. `docs/graph-approach/execution-graph-evaluation.md` §6 amendments where they touch the PRD
3. The slice definition (from the sequencing deck): "2.1 Event store + outbox — Transactional append + outbox rows; dispatch worker; crash-point recovery table (PRD §12.3, §13). Done when: failure-injection tests for all four crash points; no side effect before commit."
4. Existing pure kernel: `src/orchestrator/graph/` — especially `commands.py:apply_command` (the pure half of this controller), `projections.py:reduce_event`/`GraphProjection`, `models.py:EventEnvelope`, `store.py:InMemoryEventStore`
5. Existing persistence conventions from slice 0.1: `src/orchestrator/db/access/event_store_v2.py`, migration `src/orchestrator/db/migrations/versions/u1a2b3c4d5e6_add_events_v2_table.py` (events_v2: global `position` autoincrement, `UNIQUE(aggregate_id, version)` as per-aggregate ordering guard and duplicate-detection identity)

## Scope — what to build

### 1. Durable graph event store (SQLite)

A new effectful package `src/orchestrator/graph_runtime/` (name final — the pure kernel `src/orchestrator/graph/` must stay import-pure; do NOT add IO there). Inside it, a SQLite-backed event store for graph `EventEnvelope`s following the events_v2 conventions:

- Store graph events in the existing `events_v2` table: `aggregate_id` = `run_id`, `version` = the envelope's run-local `position` (PRD §12.1: events are totally ordered per run by position), `event_type` = envelope `event_type`, `payload` = full envelope serialized as JSON, `timestamp` = envelope timestamp. The `UNIQUE(aggregate_id, version)` constraint is the optimistic-concurrency guard: appending at a stale position must fail the transaction.
- API shape (sync or async — match what lets tests be simple and fast; the rest of `orchestrator.db` is async SQLAlchemy, follow that unless you have a strong reason): `append_events(run_id, expected_position, events) -> stored events`, `read_run(run_id, from_position=0) -> list[EventEnvelope]`. Round-trip must reconstruct identical `EventEnvelope`s (model_validate of the stored payload).

### 2. Outbox table + transactional append

- New Alembic migration adding a `graph_outbox` table: `outbox_id` (pk), `event_id` (unique — keyed by event id per §12.3 step 2), `run_id`, `kind` (e.g. `agent_dispatch`), `payload` (JSON), `status` (`pending` / `dispatching` / `completed` / `failed`), `attempts` (int), `created_at`, `updated_at`, `last_error` (nullable). Follow existing migration file conventions (see the events_v2 migration). Chain the revision onto the current head.
- The controller transaction (PRD §12.2) writes accepted events AND their outbox rows in ONE transaction: both commit or neither. If event append fails (stale `expected_position`, duplicate version), no outbox row exists. If outbox insert fails, the event append rolls back too.

### 3. Controller — the effectful wrapper around `apply_command`

`GraphController` (in `graph_runtime/controller.py`) with the §12.2 shape:

```text
validate boundary input
load events for run → rebuild projection at position P (reduce_event over stored events)
call pure apply_command(projection, events, command_type, payload, clock, id_gen)
in ONE transaction: append returned events (expected_position guard) + insert outbox rows for side-effect-bearing events
after commit: hand pending outbox rows to the dispatcher (never before)
```

- Which events produce outbox rows: `agent_dispatch_requested` (and any event your reading of §12.3 says carries side-effect intent — document the mapping in code). The mapping must be a single explicit table/function, not scattered conditionals.
- Commands rejected by the pure kernel (`command_rejected`, `callback_rejected_*`, `graph_patch_rejected`) still append their rejection events (they are accepted facts) but produce no outbox rows.
- Clock and id_gen are injected (reuse the kernel's `Clock`/`IdGenerator` protocols). The controller itself must not call `datetime.now()` or `uuid4` directly.
- Concurrent/stale command handling: if append fails on the unique constraint, surface a typed error (e.g. `StaleProjectionError`) — caller retries by reloading (PRD §12.1 rule 3). Do not auto-retry inside the transaction.

### 4. Dispatch worker (outbox worker)

`OutboxDispatcher` in `graph_runtime/outbox.py`:

- Pulls `pending` rows in `outbox_id` order, marks `dispatching`, invokes an injected side-effect executor (a small Protocol, e.g. `def dispatch(item: OutboxItem) -> None`), then marks `completed`. Executor failure → `attempts += 1`, `last_error` recorded, status back to `pending` (bounded retries → `failed` after N attempts; N configurable, default small).
- Idempotency: dispatch is keyed by `event_id`. A row already `completed` is never re-dispatched. A row found in `dispatching` at startup (crashed mid-dispatch) is treated as pending again — the executor contract is at-least-once, so executors must be idempotent; document this on the Protocol.
- Provide an explicit `dispatch_pending()` (process-now) method for deterministic tests. A background loop/task is optional and NOT required for this slice — 2.3 wires the real runner.

### 5. Recovery (§12.3 crash table + §13)

`recover(...)` in `graph_runtime/recovery.py`, run at startup: rebuild projection from the event log, then reconcile:

- Outbox `pending`/`dispatching` rows → re-dispatch idempotently (§13 row: "Outbox dispatch pending → retry dispatch idempotently").
- Active lease with no `agent_started`/start-ack event → leave lease intact; recovery exposes it for the runtime layer to reattach or await callback/expiry (§12.3 crash point 3). For this slice, recovery returns a structured report (e.g. `RecoveryReport` listing `redispatched`, `awaiting_start_ack`, `awaiting_callback`) — actual process reattach is slice 2.3.
- The controller must never infer success from anything but accepted events (§13 last paragraph).

### 6. Failure-injection tests (the done-when)

`tests/integration/test_graph_outbox_crash_points.py` (+ a store test file) using REAL SQLite (tmp-file via `tmp_path`, or in-memory — but crash-point tests need a fresh controller/dispatcher over the SAME db file to model restart, so tmp-file). Simulate "crash" by: an injected executor (hand-written class, NOT a mock) that raises at a configured call, then discard the controller/dispatcher objects and build new ones over the same DB file, run `recover()` + `dispatch_pending()`, assert outcome. Cover the FOUR §12.3 crash points:

1. **Before append**: command applied but transaction made to fail before commit (e.g. force the unique-constraint failure by appending at a stale expected_position, or inject a failing session) → assert NO events stored, NO outbox row, dispatcher never invoked. (This is also the "no side effect before commit" proof — assert the executor's call log is empty.)
2. **After append, before outbox starts agent**: events + outbox row committed, dispatcher never ran (crash) → new dispatcher over same DB finds pending row, dispatches exactly once.
3. **After agent starts, before start acknowledgement**: outbox row completed (executor ran), no `acknowledge_start` command processed → `recover()` reports the lease as `awaiting_start_ack`; lease still active in projection; re-running recovery does NOT double-dispatch (executor call count unchanged).
4. **Agent dies**: lease active, controller processes an `agent_died`-style command/callback path per the kernel (`submit_callback` failure path or the kernel's existing handling — use whatever `apply_command` supports today; if the kernel has no `agent_died` command, drive it via the lease-expiry `schedule_tick` path and document the equivalence) → lease revoked/expired in projection, no orphan outbox rows.

Plus:

- Duplicate dispatch attempt (call `dispatch_pending()` twice) → executor invoked once per outbox row.
- Transactionality: make the outbox insert fail (e.g. pre-insert a row with the same `event_id` unique key) → event append rolled back too; store position unchanged.
- Round-trip: append via controller, read back, projection rebuilt equals projection computed in-memory.
- Stale `expected_position` append → typed error, nothing written.

### 7. Unit tests for the store/outbox pieces

`tests/integration/test_graph_event_store.py`: append/read round-trip, per-run isolation, unique-version conflict, read_from offset. Keep module-scoped engine fixtures so the file stays fast (project standard: see `tests/integration` conftest patterns; memory note — module-scoped fixtures, template DB).

## Done when (all must hold)

1. Failure-injection tests cover ALL FOUR §12.3 crash points, each as a distinct test with the recovery behavior asserted from the §12.3 table.
2. A test proves no side effect starts before commit (executor call log empty when transaction fails).
3. Events + outbox rows commit atomically (both-or-neither test passes).
4. Dispatch is idempotent (double `dispatch_pending`, restart-mid-dispatch cases).
5. `recover()` returns the §13-derived report and re-dispatch is idempotent.
6. Alembic migration exists, chains onto current head, and `uv run alembic upgrade head` works on a fresh tmp DB (the integration conftest probably already does this — confirm).
7. Kernel purity preserved: `src/orchestrator/graph/` has no new imports of sqlite/sqlalchemy/asyncio/filesystem; kernel suite still ~146 tests under 5s.
8. Fresh runs green: `uv run pytest tests/unit -q` and `uv run pytest tests/integration -q` (or at minimum the full integration files you added plus the existing suite untouched-green), `uv run ruff check src tests`.

## Hard constraints

- NO mocks, NO monkeypatching anywhere (project standard, non-negotiable). Hand-written fake executor classes injected via constructor are fine.
- Real SQLite in tmp dirs/in-memory only. NEVER touch the main `orchestrator.db` or run the server. NEVER `rm orchestrator.db`.
- Do NOT run `git commit`, `git stash`, `git checkout`, `git reset`, or any git mutation. Read-only git is fine.
- Touch ONLY: `src/orchestrator/graph_runtime/**` (new), `src/orchestrator/db/migrations/versions/*` (one new migration), `src/orchestrator/db/__init__.py` or model modules ONLY if the outbox table needs a SQLAlchemy model registered, `tests/integration/test_graph_event_store.py` (new), `tests/integration/test_graph_outbox_crash_points.py` (new). If you must touch anything else, stop and write why in your summary.
- The working tree is clean at start. Leave unrelated files untouched.
- Async vs sync: pick one and be consistent; if async, tests use the project's existing async test patterns (anyio/pytest-asyncio — check conftest).

When done, write a summary of what you built, decisions made (especially the outbox-event mapping and crash-point-4 modeling), and fresh test output to stdout.
