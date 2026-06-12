Criteria table:

| # | criterion | code evidence | test evidence | status |
|---|---|---|---|---|
| 1 | Accepted graph events use the PRD envelope, are append-only, ordered per run, and rejected on stale `expected_position`. | `src/orchestrator/graph/models.py:241`, `src/orchestrator/graph_runtime/store.py:27`, `src/orchestrator/db/orm/models.py:338` | `tests/integration/test_graph_event_store.py:42`, `:88`, `:112` | MET |
| 2 | Commands load projection at a known position, run pure command logic, append events, and write outbox rows in one transaction. | `src/orchestrator/graph_runtime/controller.py:67`, `:79`, `:93`, `:98`; `src/orchestrator/graph_runtime/outbox.py:70` | `tests/integration/test_graph_outbox_crash_points.py:296`, `:334` | MET |
| 3 | No side effect may start before commit; dispatch may happen only after durable event + outbox commit. | Current code does dispatch after `session.begin()` exits: `src/orchestrator/graph_runtime/controller.py:67`, `:100` | Partial only: stale command no dispatch at `tests/integration/test_graph_outbox_crash_points.py:139`; no test observes committed DB state from inside executor | PARTIAL |
| 4 | `lease_granted` must produce controller-accepted `agent_dispatch_requested`, and the outbox row must be keyed by that dispatch event id. | `src/orchestrator/graph_runtime/controller.py:109`, `:127`; `src/orchestrator/graph_runtime/outbox.py:52`; `src/orchestrator/db/orm/models.py:353` | Indirect: `tests/integration/test_graph_outbox_crash_points.py:162`; weak round-trip at `:334`; no direct field assertion | PARTIAL |
| 5 | Crash point 1, before append: no lease, no outbox row, no dispatch. | `src/orchestrator/graph_runtime/controller.py:70`; `src/orchestrator/graph_runtime/store.py:37` | `tests/integration/test_graph_outbox_crash_points.py:139` | MET |
| 6 | Crash point 2, after append before outbox starts agent: pending outbox survives restart and dispatches. | `src/orchestrator/graph_runtime/recovery.py:30`; `src/orchestrator/graph_runtime/outbox.py:123` | `tests/integration/test_graph_outbox_crash_points.py:162` | MET |
| 7 | Crash point 3, after agent starts before start acknowledgement: lease remains active and recovery reattaches/waits. | `src/orchestrator/graph_runtime/recovery.py:41`; `src/orchestrator/graph/commands.py:380` | `tests/integration/test_graph_outbox_crash_points.py:186` | PARTIAL |
| 8 | Crash point 4, agent dies: controller accepts `agent_died`, revokes lease, creates retry/recovery per policy. | No `agent_died` path in `graph_runtime`/`graph`; only lease expiry at `src/orchestrator/graph/commands.py:616` | `tests/integration/test_graph_outbox_crash_points.py:218` tests expiry instead | UNMET |
| 9 | Outbox dispatch is at-least-once, retries `dispatching` rows on restart, and uses stable `event_id` for idempotency. | `src/orchestrator/graph_runtime/outbox.py:37`, `:123`, `:138`, `:158` | `tests/integration/test_graph_outbox_crash_points.py:248`, `:267`; callback idempotency unit tests at `tests/unit/test_callbacks.py:94` | PARTIAL |
| 10 | §13 recovery must rebuild from event log and must not infer success from process/files. | `src/orchestrator/graph_runtime/recovery.py:35`; no filesystem/process checks present | `tests/integration/test_graph_outbox_crash_points.py:186`; no success-inference negative test | PARTIAL |

Fresh test results:

- `uv run pytest tests/unit -q`: 2563 passed in 16.35s.
- `uv run pytest tests/integration/test_graph_event_store.py tests/integration/test_graph_outbox_crash_points.py -q`: 12 passed in 2.64s.
- Kernel suite: 146 passed in 1.27s, under 5s.
- Static check: no IO/DB/clock/random imports found in `src/orchestrator/graph/`; `graph_runtime` uses injected `Clock`/`IdGenerator`.

Findings:

| severity | type | description | location |
|---|---|---|---|
| HIGH | laziness | Crash point 4 is not implemented. The PRD says agent death accepts `agent_died`, revokes lease, and creates retry/recovery. The test substitutes lease expiry via `schedule_tick`; that is not equivalent because it does not model a runtime death signal, managed-process absence, revocation, or retry policy. | `tests/integration/test_graph_outbox_crash_points.py:218`; `src/orchestrator/graph/commands.py:616` |
| HIGH | laziness | No test fails if dispatch is moved inside the DB transaction. Current code dispatches after commit, but the tests do not use an executor that verifies the outbox/event rows are externally visible and committed before side effect execution. This is a core “no side effect before commit” invariant. | `src/orchestrator/graph_runtime/controller.py:67`, `:100` |
| HIGH | laziness | Atomicity is only tested for outbox insert failure after an event append inside a manual transaction. There is no controller-level regression test proving `agent_dispatch_requested` can never commit without its outbox row, and `GraphEventStore` is publicly exported and can append such an event without outbox enforcement. | `src/orchestrator/graph_runtime/store.py:27`; `src/orchestrator/graph_runtime/__init__.py:7`; `tests/integration/test_graph_outbox_crash_points.py:296` |
| MEDIUM | laziness | Stale concurrent append behavior is not actually tested at the UNIQUE-constraint race. Existing stale-position tests hit the preflight `current_position` check, so the `IntegrityError -> StaleProjectionError` path can regress unnoticed. | `src/orchestrator/graph_runtime/store.py:62`; `tests/integration/test_graph_event_store.py:88` |
| MEDIUM | laziness | Partial dispatch crash is weakly modeled. `restart_mid_dispatching` manually marks a row `dispatching` without first executing the side effect, so it does not prove the “agent started, process died before completed mark” at-least-once/idempotent path. | `tests/integration/test_graph_outbox_crash_points.py:267` |
| MEDIUM | lie | `agent_dispatch_requested` emitted by the runtime controller is consistent with PRD §12.3 and §28 because the controller appends it, not the agent. It is present by code, but tests only assert indirectly via outbox behavior / event round-trip, not correct envelope fields. | `src/orchestrator/graph_runtime/controller.py:127`; `tests/integration/test_graph_outbox_crash_points.py:334` |
| LOW | laziness | Recovery report assertions are weak. They mostly assert list length/equality, not full content such as run id, node id, generation, execution id, and state-specific classification. | `tests/integration/test_graph_outbox_crash_points.py:180`, `:211`, `:290` |
| LOW | standards | New/changed tests comply with no mocks/monkeypatching and use real SQLite/temp files. `RecordingExecutor` is a real injected fake object, not a mock. | `tests/integration/test_graph_outbox_crash_points.py:48`, `:61` |

§12.3 crash rows: 4 total. Rows 1-3 have some evidence; row 4 is not met.

§13 recovery rows: 6 total. “Outbox dispatch pending” is implemented/tested. “Active lease after agent started before acknowledgement” is partially tested as awaiting start ack. Legitimately deferred to later runner/callback slices, but must be named: managed-process reattach, managed-process missing -> `agent_died`, user-managed pending external action, suspended retained session, callback receipt replay. The managed-process missing / `agent_died` row is not safely deferrable if slice 2.1 claims all four §12.3 crash points.

Verdict: BOUNCE

The implementation has a solid start: event append, per-run ordering, transactional outbox insert, post-commit dispatch in current code, and pending/dispatching outbox recovery all pass fresh tests. The slice is not done because two core invariants lack hard evidence: no regression test proves side effects cannot run before commit, and the fourth PRD crash point is replaced by lease expiry rather than `agent_died` lease revocation plus retry/recovery policy. The concurrency/partial-dispatch/idempotency coverage is also thinner than the slice definition requires.
