# Slice 2.1 — Event store + outbox (FIXER)

You are the FIXER agent for slice 2.1 of the task-world execution-graph kernel. The BUILDER implemented the slice; the AUDITOR returned BOUNCE. Your job: close EVERY HIGH and MEDIUM finding below (LOWs too where cheap). Do not regress anything green.

## Ground truth (read first)

1. `docs/graph-approach/execution-graph-prd-plus.md` — §12.2, §12.3 (crash table), §13 (recovery table), §15 (lease/node states), §19 (lease semantics), §27.4
2. The full audit report: `/tmp/codex-graph/audit-2.1-report.md` (read it)
3. Existing implementation: `src/orchestrator/graph_runtime/` (store.py, outbox.py, controller.py, recovery.py), pure kernel `src/orchestrator/graph/` (commands.py, projections.py, models.py), tests `tests/integration/test_graph_event_store.py`, `tests/integration/test_graph_outbox_crash_points.py`

## Findings to close

### HIGH-1 — Crash point 4 (`agent_died`) not implemented

PRD §12.3 row 4: "Agent dies → Controller accepts `agent_died`, revokes lease, creates retry/recovery according to policy." The builder substituted lease expiry via `schedule_tick`. Not equivalent.

Fix:
- Add an `agent_died` command to the PURE kernel (`src/orchestrator/graph/commands.py` — keep it IO-free, follow the existing `_apply_*` pattern). Payload: `lease_id` (+ optional `execution_id`, `reason`). Validation: lease must exist and be active (else `command_rejected`). Accepted events: `agent_died`, `lease_revoked`, and the retry/recovery policy event(s) — node back to a schedulable/failed state per §15 (worker node in `leased`/`running` → a retry is possible: emit `node_state_changed` accordingly; document the v1 policy choice in code). Reducers in `projections.py` must consume what they don't already.
- Kernel unit tests in `tests/unit/test_graph_commands.py`: accepted path (lease revoked, node state transition), rejected path (unknown/inactive lease).
- Rewrite the crash-point-4 integration test: full sequence — schedule_tick grants lease + dispatch, outbox dispatches (agent "started"), then `agent_died` command through the CONTROLLER → assert lease revoked in rebuilt projection, retry/recovery event present, no orphan pending outbox rows, and a subsequent `schedule_tick` can re-lease the node (scheduler may decide again).

### HIGH-2 — No test pins "no side effect before commit"

Fix: add a test with an executor (hand-written class, no mocks) that, when invoked, opens its OWN separate sqlite connection/session to the same tmp-file DB and asserts the triggering event row AND its outbox row are already committed and visible from that independent connection. If anyone moves dispatch inside the controller transaction, this test must fail (uncommitted rows invisible to the second connection / locked). Use the controller's real auto-dispatch path.

### HIGH-3 — No controller-level atomicity regression test

Fix: prove via `GraphController.handle_command` that `agent_dispatch_requested` can never commit without its outbox row. Approach: pre-insert a `graph_outbox` row whose `event_id` collides with the id the deterministic id_gen will produce for the dispatch event (id_gen is injected — construct the collision), call `handle_command(schedule_tick)`, assert: typed error raised, NO new events stored (position unchanged), no extra outbox rows, dispatcher never invoked. Also: either stop exporting `GraphEventStore` from `graph_runtime/__init__.py` as a public bypass, or document on it that direct append bypasses outbox enforcement and is for read/replay + controller use only — and add the outbox-row insertion enforcement at the single controller chokepoint (mapping function) so the invariant has one owner.

### MEDIUM-1 — UNIQUE-constraint race path untested

`store.py` preflight position check masks the `IntegrityError → StaleProjectionError` path. Fix: test with two sessions/stores over the same DB where both read the same position and both append (second append passes any preflight against its stale snapshot but hits `UNIQUE(aggregate_id, version)`) → assert `StaleProjectionError` surfaced (not IntegrityError, not swallowed) and store state intact. If the current preflight makes this unreachable in one session, drive it with two concurrent session objects.

### MEDIUM-2 — Restart-mid-dispatch weakly modeled

Current test manually marks a row `dispatching`. Fix: model the real interleaving — executor that performs/records its side effect then raises a crash-simulating exception that escapes the dispatcher's retry handling (or: dispatcher variant/seam that marks `dispatching`, calls executor, and the test's executor raises BEFORE the `completed` mark is written; the row must remain `dispatching` in the DB — verify by reading the row). Then: fresh dispatcher + `recover()` over the same DB → row re-dispatched (at-least-once: executor call count == 2 for that event_id), `attempts` incremented, row ends `completed`. Document at-least-once + executor-must-dedup-by-event_id on the executor Protocol if not already.

### MEDIUM-3 — `agent_dispatch_requested` envelope never directly asserted

Fix: in a controller test, read back the stored `agent_dispatch_requested` event and assert envelope fields exactly: `event_type`, `run_id`, monotonic `position` (immediately after its `lease_granted`), `actor.kind == "controller"`, `causation_id` referencing the lease grant (or command), payload contains `lease_id`/`node_id`/execution identity, `schema_version`, timestamp from injected clock.

### LOW-1 — Recovery report assertions weak

Strengthen: assert full content of report entries (run_id, node_id, lease_id, generation, classification) in the crash-point-2/3 tests, not just list lengths.

## Done when

1. All HIGH and MEDIUM findings closed with the tests described (each as a distinct, named test).
2. Fresh runs green:
   - `uv run pytest tests/integration/test_graph_event_store.py tests/integration/test_graph_outbox_crash_points.py -q`
   - `uv run pytest tests/unit -q` (kernel suite still under 5s)
   - `uv run pytest tests/integration -q`
   - `uv run ruff check src tests`
3. Kernel purity preserved: `agent_died` addition to `src/orchestrator/graph/` stays pure (no IO/clock/random imports).

## Hard constraints

- NO mocks, NO monkeypatching anywhere. Hand-written fake/recording classes injected via constructor are fine.
- Real SQLite in tmp dirs only. NEVER touch main `orchestrator.db`. No server.
- Do NOT run `git commit`, `git stash`, `git checkout`, `git reset`, or any git mutation. Read-only git fine.
- Touch ONLY: `src/orchestrator/graph_runtime/**`, `src/orchestrator/graph/commands.py`, `src/orchestrator/graph/projections.py`, `src/orchestrator/graph/models.py` (if needed for agent_died), `tests/unit/test_graph_commands.py`, `tests/unit/test_graph_projections.py`, `tests/integration/test_graph_event_store.py`, `tests/integration/test_graph_outbox_crash_points.py`, `tests/fixtures/graph/**` (+ COVERAGE.md) if you add agent_died fixtures. Nothing else.

When done, write a summary mapping each finding → fix → test, plus fresh test output, to stdout.
