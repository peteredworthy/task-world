# Projection Simplification Wave 1 — Run-Health Repair Ledger

## Recovery-closure incident and baseline

- Seed commit: `8dc2859433d1e2e43f482f3afa05c5d06a78ecab` contains the
  hook-validated driver repair that primes only `runner_recovery` outbox work
  before the first resumed schedule tick. This behavior is preserved.
- Preserved AR-A evidence: run
  `b7e430e1-af51-4121-b2a1-f3df6950abeb` has failed outbox row `1320`, kind
  `runner_recovery`, attempts `3`, with `last_error` beginning
  `graph_projection_checkpoint (event_payload_exceeds_byte_cap)`.
- Replacement evidence: run `8e677613-36c1-4a96-a73e-46b5a678955b` has four
  failed `snapshot_cleanup` outbox rows with
  `event_payload_exceeds_byte_cap`.
- Additional recovery evidence: run
  `b598c0d2-f8b5-46bd-b037-000ab4132414` has a `runner_recovery` failure with
  `recovery_tail_exceeds_bounded_cap`.
- Delivery evidence: repair run
  `f33bd494-0d70-444f-9714-e6852910c063` streamed a complete worker
  implementation and passing focused tests, but delivered no callback before
  its lease expired; the run was paused so its worktree remained preserved.

The durable path baseline is: `GraphEventStore.append_events` stores the
authoritative event row, appends bounded summaries and references, advances the
disposable projection checkpoint, and queues event-journal work; the runtime
reader loads that checkpoint and folds only the bounded event tail. Graph
events map `runner_recovery_requested` and `cleanup_requested` to durable
`runner_recovery` and `snapshot_cleanup` outbox rows. `OutboxDispatcher`
claims, dispatches, and marks those rows completed or failed while retaining
failed rows and their errors. Runner recovery and managed snapshot cleanup
construct their completion payloads from the checkpoint-owned projection and
the durable outbox intent. Callback submission enters through the selected
runner's lease-bound callback boundary,
where stale/revoked leases, file state, payload, secret, symlink, and cache
authority checks remain authoritative. The observed failures show that a
valid bounded checkpoint/recovery payload can still exceed the event payload
cap at the durable event/outbox boundary, and that a bounded-tail read can
reject a valid current graph history before recovery delivery.

This closure must make normal bounded checkpoints and recovery/cleanup payloads
fit the existing caps, without enlarging caps blindly, disabling validation,
authorizing temporary artifacts, serializing an unbounded graph, or adding a
generic requeue endpoint. Failed rows remain visible, lifecycle state remains
conservative, and recovery remains idempotent and lease-safe.

## Fresh terminal corrective run

- Main is exactly `27da58e6e755df45ec2e2f4f0ef4546f669bb541`.
- The original linear hook-passing checkpoints were cherry-picked in order:
  `8dc2859433d1e2e43f482f3afa05c5d06a78ecab`, then
  `47f3cdc709920a178b6d588bdecb9c895ba38a3d`. Their parent chain is
  `main -> 8dc -> 47`; later r397 ledger-only commits were not substituted.
- r397 `0900166e-08e7-4914-aa74-1606535a9952` accepted
  `runner_submission_staged` at graph position 170, rejected a duplicate
  submit at 171, recovered positions 172–176, redispatched positions 183–190,
  and was manually paused to stop its retry loop.
- r398 `10d9fa2e-7e34-4d3f-9813-1d2b254e17cf` was paused and superseded before
  validation because later ledger-only commits were mistakenly selected; no
  r398 work is mergeable.
- Earlier r396 and outbox 1334/1344 corrections remain preserved.
- This run closes the deterministic snapshot-cleanup replay gap: cleanup
  dispatch validates the durable `CleanupRequestedPayload`, compares its
  ownership identity with the projected request, rejects malformed or
  conflicting intent, and uses the validated durable payload for the
  filesystem side effect.
- This run must produce a fresh independently verified accepted callback.

Corrective-run evidence:

- The named real SQLite/files crash-point test failed on the checkpoint chain
  with a same-snapshot replay (`superseded_by_record_id` remained unset).
- After the corrective dispatch change, that exact test passed.
- Configured acceptance and boundary/signal checks: `75 passed`; both script
  checks passed.
- Ruff check and format check, Pyright, UI lint, and UI typecheck passed.
- Full suite: `5482 passed, 4 skipped, 4 warnings`.

## Baseline

- Base commit: `27da58e6e755df45ec2e2f4f0ef4546f669bb541`
- Scope: repair graph-run resume scheduling before projection-simplification work continues.
- Preserved incident: run `b7e430e1-af51-4121-b2a1-f3df6950abeb` rejected the
  `worker-stage5-implementation` callback at graph position 80 because its
  `file_state` contained unauthorized `tmp/.orchestrator/state/history.jsonl`.
  Recovery revoked the lease and returned the node to `ready` at positions
  81–86. An explicit `POST /resume` then emitted `signal_enqueued`, `active`,
  and `signal_processed`, but immediately classified the graph as blocked with
  `graph has ready node(s) not dispatched: worker-stage5-implementation`; no
  `agent_dispatch_requested` followed.

## Reproduction

Status: reproduced against the preserved product run and isolated in a focused
driver regression.

Product readback showed graph positions 80–86 as
`callback_rejected_conflict`, `runner_recovery_requested`, `agent_died`,
`lease_revoked`, `runtime_retry_scheduled`, `output_record_accepted`, and
`node_state_changed(ready)`. The resume signal then produced only the lifecycle
events at the workflow layer before `graph_blocked`; no graph position 87
`schedule_tick` or `agent_dispatch_requested` was appended. The kernel's
`schedule_tick` guard intentionally returns no events while an execution
attempt is `recovery_requested`. The driver scheduled before priming the
recovery outbox tranche, allowing its no-progress classification to win.

The original unauthorized `tmp/.orchestrator/state/history.jsonl` rejection is
preserved; the repair does not alter file-state authority or authorize the
artifact.

## Acceptance

- RH-1: explicit API resume of a paused graph with a retryable ready node
  durably schedules and dispatches it before quiescence classification.
- RH-2: resume/recovery is idempotent: no duplicate dispatch, lease, callback,
  or retry; stale/revoked leases are not revived; resource and gate blocking
  remain truthful.
- RH-3: preserve signal-queue lifecycle ownership, checkpoint+tail bounded
  recovery, the user-selected runner, cache/secret/symlink/lease/file-state/
  payload validation, and the original callback rejection.
- RH-4: focused pure/integration regressions cover ready-on-resume,
  recovery-to-ready, duplicate-signal/idempotency, scheduler capacity/resource
  conflict, and quiescence timing using real objects, SQLite, and files only.
- RH-5: an independent verifier exercises a real Codex callback/recovery path.

## Product-real proof

Status: verifier/operator gate after merge.

After repair is merged, resume the preserved AR-A run and observe
`agent_dispatch_requested` followed by a valid callback or graph transition.
Record the event positions and confirm the unauthorized `tmp` artifact remains
rejected.

## Regression evidence

Status: complete for worker-side repair; product-real verifier gate remains.

The new unit regression proves recovery dispatch precedes the first schedule
tick, and the new SQLite/files integration regression resumes a paused graph
and observes both dispatch requests before completion. Existing focused tests
cover recovery-to-ready/orphan lease recovery, duplicate-arm signal
idempotency, scheduler resource/capacity deferral, and quiescence timing.
The fresh terminal corrective run adds the durable cleanup-intent replay
regression and records the configured acceptance, boundary, signal, lint,
type, UI, and full-suite results above.

Completed prior-checkpoint evidence:

- Acceptance: `47 passed, 9 skipped` for the required focused command.
- Signal routing: `scripts/check_signal_routing.py` passed.
- Ruff check and format check: passed (`722 files already formatted`).
- Pyright: `0 errors, 0 warnings, 0 informations`.
- Full suite: `5482 passed, 4 skipped, 4 warnings`.

## Ownership

- Source: `src/orchestrator/workflow/graph_driver.py` and
  `src/orchestrator/graph_runtime/dispatch.py`.
- Tests: `tests/unit/test_graph_driver_logic.py`,
  `tests/integration/test_graph_run_driver.py`,
  `tests/integration/test_graph_outbox_durability.py`,
  `tests/integration/test_graph_outbox_crash_points.py`, and
  `tests/integration/test_graph_file_state_boundary.py`.
- Artifact: this ledger only.
- Explicitly out of scope: Stage 3, UI source, archival APIs, the master
  ledger, `AGENTS.md`, architecture files, schema, database, auth, cap
  expansion, generic requeue, and validation weakening.

## Gap rows

| ID | Requirement/evidence | Status | Owner |
| --- | --- | --- | --- |
| G-01 | Reproduce the preserved ready-on-resume quiescence defect | Done | worker |
| G-02 | Diagnose actual resume/driver scheduling order | Done | worker |
| G-03 | Repair durable dispatch before quiescence classification | Done | worker |
| G-04 | Prove recovery/idempotency and truthful blocking behavior | Done | worker |
| G-05 | Add focused pure/integration regressions, including timing | Done | worker |
| G-06 | Exercise a real Codex callback/recovery path independently | Open | verifier |
| G-07 | Complete product-real AR-A resume proof after merge | Open | verifier/operator |
| G-08 | Run required checks and submit with hooks | Done | worker |

## Recovery-closure implementation evidence

The second defect was isolated to the side-effect readers. Runner recovery and
snapshot cleanup used the raw bounded-runtime event reader from position zero.
That made an unrelated historical callback body subject to the current event
envelope byte cap, and made every long-but-valid history subject to the
128-event recovery-tail cap, even when the durable projection checkpoint was
current. The fix uses the checkpoint-owned projection for current lifecycle and
record facts, validates the durable outbox intent for the requested operation,
and takes baseline identity from the checkpoint-owned execution attempt. The
existing driver seed still primes only `runner_recovery` before the first
resumed schedule tick.

This keeps the raw runtime reader conservative: the exact 16,384-byte event
boundary is accepted, one byte over is reported as
`event_payload_exceeds_byte_cap`, and more than 128 requested history events is
reported as `recovery_tail_exceeds_bounded_cap`. Those failures remain visible
as read-model errors rather than being hidden by a larger cap or an unbounded
fallback. Recovery and cleanup delivery no longer need that historical scan;
the outbox row remains durable and failed rows retain their status/error.

Completed worker evidence:

- `tests/integration/test_graph_outbox_durability.py` uses real SQLite/files
  and Git fixtures for exact byte-boundary behavior, oversized historical
  runner recovery, oversized historical snapshot cleanup, bounded-tail
  recovery, and no-duplicate recovery completion.
- Required acceptance: `74 passed`.
- Graph-projection boundary check: passed.
- Signal-routing check: passed.
- Ruff check/format: passed.
- Pyright: `0 errors, 0 warnings, 0 informations`.

The independent verifier/operator must still audit seed commit
`8dc2859433d1e2e43f482f3afa05c5d06a78ecab` with this recovery closure and
observe a real Codex callback transition on the product run. Tests do not
substitute for that evidence.

## r399 disposition

r399 (`dbc0f979-4e5c-40b8-b11f-abfa11da2a46`) was paused/manual_pause after
repeated identical durable-history failures. Accepted callbacks were initial
worker pos75, initial verifier pos97, corrective worker pos176, corrective
verifier pos202, v2 worker pos217, v2 verifier pos241, recovery gap planner
pos283, and recovery worker pos309. Snapshot
`dd18fe343e87878c09dbda2d822f948aad4709d2` / tree
`dc34c79150721709a060687c3f0a4d77a0d058e8` preserves the final authorized
two-file delta. r399 repeatedly proved configured acceptance 75 passed, full
suite 5482 passed/4 skipped, Ruff, Pyright, boundary, signal, UI lint/typecheck,
and real callback acceptance, but was not mergeable because the branch lacked a
final durable commit.
