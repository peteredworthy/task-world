# Incident — Graph driver dies on "database is locked"; run stranded ACTIVE

Diagnosed 2026-07-03 from run `2bed8f2f-078f-40d1-9332-18e4c7f73f92`. Second occurrence
same day: run `8feabee5-e00b-4490-a3e9-9ef8e342c001` (09:53 EDT), identical stack.
Not covered by any of `w1`–`w8` — new underlying issue.

## Symptom

Graph run frozen indefinitely with a healthy-looking status:

- run `status: active`, `pause_reason: null`, `last_error: null`
- `ready_nodes: []` yet several nodes stuck `planned`
- the stuck nodes' required inputs are already bound (`input_bound` events present)
- no `schedule_tick`-caused events after some point; agent callbacks/heartbeats
  continue past it (REST path does not need the driver)

## Timeline (UTC, run 2bed8f2f)

1. **19:19:33** — last `schedule_tick`; dispatched
   `verifier-corrective-w1b-residual-raw-scans` and
   `worker-corrective-w1b-cleanup-tie-parity`.
2. **19:20:43** — drive loop crashed: `sqlite3.OperationalError: database is locked`
   on `UPDATE graph_outbox` in `GraphOutboxDispatcher._mark_completed`
   (`src/orchestrator/graph_runtime/outbox.py:224`), reached from
   `dispatch_pending` inside `drive_to_quiescence`
   (`src/orchestrator/workflow/graph_driver.py:502`). Logged as
   `ERROR SignalConsumer: graph driver for 2bed8f2f... failed`
   (`.orchestrator/logs/dev/latest/backend.log:5313`).
3. **19:23:19 / 19:27:40** — both in-flight agents completed via REST callbacks;
   kernel accepted records and released leases without the driver. The worker's
   `candidate` record bound to the verifier's `candidate_under_test` port
   (event position 33102).
4. **After 19:27:40** — nothing. `verifier-corrective-w1b-cleanup-tie-parity` is
   fully input-bound and one `schedule_tick` from ready, but the driver task is
   gone. Four nodes (`verifier-corrective-w1b-cleanup-tie-parity`,
   `planner-gap-w1b-post-corrective-failures`, both final invariant checks) sit
   `planned` forever.

## Root cause: three stacked gaps

1. **SQLite write contention, no mitigation.** `db/access/connection.py` creates the
   engine with no WAL journal mode and no `busy_timeout` PRAGMA, on NullPool (fresh
   connection per session). Concurrent writers — drive loop, agent REST callbacks,
   heartbeat renewals — contend on one database file; heartbeat writes landed 12s
   after the crash, so the contention window is real.
2. **Bookkeeping commit outside the try.** `dispatch_pending` wraps
   `executor.dispatch(item)` in try/except (`_mark_failed_attempt` on failure), but
   the success-path `_mark_completed` commit sits outside it. A transient DB error
   during bookkeeping escapes the entire drive loop.
3. **No fail-safe on driver death.** The exception propagates out of
   `drive_to_quiescence` and `run()`, skipping the outcome bridge that would pause
   the run (`graph_driver.py:432–438`). `_safe_run_graph_driver`
   (`workflow/signals/consumer.py:616`) catches, logs, and discards — the run stays
   ACTIVE with no driver, no pause reason, and no re-arm. The signature-based
   no-progress → `graph_blocked` guard lives *inside* the loop, so it never fires.

## Spec coverage check (why w1–w8 don't cover this)

- **W6 (outbox hardening)** is closest but scopes dispatch *attempt* failures —
  backoff, failed-row surfacing, requeue. This crash is in success-path bookkeeping;
  W6 as written does not fix it.
- **W8 (drive-loop cleanup)** simplifies loop internals and keeps guards; it does not
  address the driver task dying.
- **W2 (recovery at source)** repairs kernel/graph state, not driver process death.

## Fixes (implemented 2026-07-03)

1. **Connection hardening** — `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000`
   set on every new connection of the file-backed engine
   (`db/access/connection.py`, connect-event hook; per-connection because NullPool
   opens a fresh connection per session).
2. **Outbox bookkeeping retry** — `_retry_locked` (exponential backoff, lock-class
   `OperationalError` only) wraps `_mark_completed`, `_mark_failed_attempt`,
   `_claim_next`, and `reset_dispatching_to_pending`. Claim retry is safe: the
   transaction rolls back whole, so a retry re-selects the same pending row
   (at-least-once contract). Tests: `tests/unit/test_outbox_retry.py`.
3. **Crash-path bridge** — `run()` wraps `drive_to_quiescence`; any non-cancel
   exception pauses the run `graph_driver_crashed` with the error detail, then
   re-raises for the consumer log. Resume re-arms the driver.

## Second crash class found by the bridge: stale-position race

First post-fix resume of 2bed8f2f crashed again — this time *visibly*
(`graph_driver_crashed` pause): recovery-primed zombie executions appended
`command_rejected` events concurrently with the driver's first `schedule_tick`,
so the position the driver had read was stale by the time its command landed —
`IntegrityError: UNIQUE` on `events_v2` surfaced as `StaleProjectionError`. The
drive loop, unlike `apply_graph_cancel_until_terminal`, had no stale retry.

**Fix:** `GraphRunDriver._handle_command_at_head` — re-read head position and
retry (bounded) on `StaleProjectionError`; used for the loop's own commands
(`schedule_tick`, `complete`), which are idempotent at head. Tests in
`tests/unit/test_graph_driver_logic.py`
(`test_handle_command_at_head_retries_stale_position_races`,
`test_handle_command_at_head_raises_after_exhausting_attempts`).

**Outcome:** run 2bed8f2f completed 2026-07-03T22:47:48Z after the fixes below plus
two operator patches (retire + recreate the runtime-failed check; retire the
replacement once the cite-latest-candidate rule made it redundant — see gap 5).

## Follow-up gaps found while driving 2bed8f2f to completion

1. **Unresolvable hidden-oracle binding kills checks.** `hidden_oracle_command` is an
   optional routine input defaulting to `""`; the planner prompt hint instructs
   binding final-invariant checks to `dynamic_feature_hidden_oracle`; the resolver
   had no fallback → non-retryable `check node missing command_definition` at
   dispatch. **Fixed:** `graph/command_bindings.py` falls back to the run's
   `acceptance_command` (tests: `tests/unit/test_command_bindings.py`).
2. **Runtime-failed checks have no recovery path.** `_failed_check_recovery_events`
   keys on failed check *results*; a check that dies before producing one (only a
   `failure_record`) stays `failed` forever, blocking task acceptance and
   completion. Recovery required an operator `submit_patch` (role `human`):
   `retire_node` the dead check + `create_node` a replacement + re-wire evidence
   edges. Open gap — W2 territory.
3. **Kernel repair sweep created a graph cycle.** `_passed_verification_final_check_edges`
   (a `schedule_tick` sweep) added `verifier-corrective → check-final-invariant-primary`
   (position 33126), closing a cycle through the check's failure edge. Sweeps skip
   cycle validation; the patch validator enforces it and rejects any patch whose
   endpoints touch a cycle member — locking out planner/operator patches on those
   nodes. Workaround: route recovery edges only through non-cycle nodes. Open gap —
   the sweep should refuse cycle-forming edges. W2 territory.
4. **Dev-reload stranding.** `--reload` (WatchFiles) kills the driver task with
   CancelledError — deliberately not bridged to a pause — and in-process check
   executions die with it; startup does not re-arm active graph runs. Every source
   edit while a graph run is active strands it until a manual pause + resume. Open
   gap: startup redelivery (or the reload path) should re-arm drivers for runs
   left `active` with a non-zero graph position.
5. **Cite-latest-candidate vs cross-region evidence.** `_required_checks_passed`
   requires every non-retired check's result to cite the region's *latest*
   candidate. The recovery check (r2) took evidence from the cleanup verifier,
   whose report cites the `corrective_work_region` candidate — so its *passed*
   result blocked acceptance of `region-w1b-residual-raw-scans`. Resolved by
   retiring r2 (the primary check already cites the right candidate). Lesson for
   operator patches: wire check evidence from a verifier in the same task region
   as the check, or its result will never satisfy the cite rule.
6. **Stale read-model on `/graph`.** After the retire patch, the projection
   snapshot behind `GET /graph` served `task_states` several events behind the
   log (region showed `pending` while a fresh fold said `accepted`). Cosmetic
   here, but misleading during diagnosis — W3 (incremental snapshots) territory.

## Diagnosis recipe

When a graph run shows `active` + no `pause_reason` + empty `ready_nodes` + `planned`
nodes whose inputs are bound:

1. `grep "ERROR SignalConsumer: graph driver" .orchestrator/logs/dev/latest/backend.log`
2. In `events_v2` (aggregate `graph:<run_id>`), the last event with
   `causation_id: schedule_tick` marks driver death time; callbacks after it confirm
   the server stayed up while the driver was gone.

Recovery: pause + resume the run to re-arm the driver; bound-and-ready nodes dispatch
on the first tick.
