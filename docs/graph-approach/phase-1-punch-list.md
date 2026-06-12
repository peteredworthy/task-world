# Phase 1 Punch List — Kernel Audit (2026-06-12)

> **STATUS (2026-06-12, later same day): CLOSED.** Slices 1.8 and 1.9 executed
> via builder→auditor→fixer codex agents (audit per `audit-checklist.md`; both
> slices BOUNCEd once and were fixed). All items P1-1 … P1-8 closed — P1-8 was
> pulled forward into 1.8 by the auditor. Final gate: 146 kernel tests in
> ~1.3s, full unit suite 2563 passed in ~19s, 93 fixtures / 137 COVERAGE rows,
> no mocks, kernel pure and import-isolated. Audit reports:
> `/tmp/codex-graph/audit-1.8-report.md`, `/tmp/codex-graph/audit-1.9-report.md`
> (copied below in spirit; see git history of this branch for the diff).
> Additions beyond the original list, forced by audits: configured-gate
> tracking in §14, `record_decision` validation, real event emission for all
> v1 patch ops, `acknowledge_start` command, §17 criterion-8 precondition
> surface (`precondition_failed:<name>`), external-claim key validation,
> `node_ready`/`node_deferred` documented as audit-only events.
> Next: Phase 2 (2.1 event store + outbox).

Audit of slices 1.1–1.7 against `execution-graph-prd-plus.md` and the
sequencing deck. Verdict: **ACCEPT-WITH-PUNCHLIST**. The pure-function kernel
(models, store, reducers, scheduler, callback validator, patch validator) is
real and well unit-tested — 76 tests, ~1s. But the fixture corpus is largely
assertion theater, and two PRD-required behaviors claimed by slice done-whens
are not implemented. These must land before Phase 2 builds on them.

## Status

| Slice | Claim | Audit result |
|---|---|---|
| 0.1–0.3 | Event-log durability, cost records, snapshot plumbing | Done (prior session) |
| 1.1 Models | Pydantic models for §6, §10–§12, §16, §19 | Done — `src/orchestrator/graph/models.py` |
| 1.2 Harness | Fixtures executable, bad fixture caught | Done with gap (P1-3) |
| 1.3 Corpus | Every PRD table row → fixture | Done with gaps (P1-2, P1-6) |
| 1.4 Reducers | §14 task projection formula; every `then_projection` real | **Partially done — see P1-1** |
| 1.5 Scheduler | Readiness + tie-breaks + §18 matrix | Done with gaps (P1-4, P1-5) |
| 1.6 Callbacks | §19 stale matrix pure validation | Done — real coverage in `test_callbacks.py` |
| 1.7 Patch validator | Read-set staleness + authority | Done — real coverage in `test_patch_validator.py` |

## Findings (ordered by severity)

### P1-1 — §14 task projection formula not implemented (HIGH, slice 1.4 done-when violated)

`reduce_event` never populates `task_states`; `project_task_states` always
returns `{}`. The six fixtures in `task_projection.yaml` inject a
`task_projection_changed` event carrying the desired state and assert the event
exists — tautological. The PRD formula (accepted / needs_revision /
blocked_invalid_test / blocked_environment / in_progress / pending derived from
candidate, verifier, gate, appeal, and lease facts; latest candidate by
`attempt_number` then event position; verifier result ignored unless
`candidate_id` matches) exists nowhere in code.

Fix: reduce `output_record_accepted`, `verification_passed/failed`,
`appeal_opened`, `oversight_decision_recorded`, `approval_decision_recorded`,
`input_bound` into projection state (candidates, verdicts per candidate_id,
appeals, gates) and derive task state per the §14 formula. Rewrite the six
fixtures to feed raw facts and assert the derived state.

### P1-2 — Fixture corpus asserts what it injects (HIGH)

The harness (`scenario.py`) appends `given_events`, records `when_command` as a
`command_recorded` event, and replays reducers. It never dispatches the command
to any kernel logic. Consequently:

- `invariants.yaml`: 9 of 10 "invariant" fixtures inject e.g.
  `callback_rejected_stale` or `graph_patch_rejected` in `given_events` and
  assert the same event in `then_events`. They cannot fail.
- `stale_callbacks.yaml`, `run_lifecycle.yaml`, `readiness.yaml`,
  `patch_validator.yaml`: same echo pattern. The real §19/§16/§17 coverage
  lives only in the unit tests.

Fix: add a pure command applier —
`apply_command(projection, events, command, clock, id_gen) -> list[EventEnvelope]`
— that routes `when_command` through `validate_callback`, `validate_patch`,
`schedule`/`evaluate_readiness`, and run-lifecycle transition rules, emitting
accepted/rejected events. Then `then_events` become outputs of kernel logic,
not echoes. This is the §27.3 intent ("when_command → then_events") and is the
seed of the slice 2.1 controller, so it is prerequisite work, not throwaway.
Rewrite fixtures so `given_events` contain only facts and the behavior under
test comes from the command.

### P1-3 — `test_all_fixtures_run_through_harness` never asserts `result.passed` (MEDIUM)

`tests/unit/test_fixture_corpus.py` only checks `result.scenario_name`. A
failing fixture passes this test. Coverage exists indirectly via
`test_graph_projections.py:193`; assert `result.passed` (with `failures` in the
message) in the corpus test itself and drop the redundancy.

### P1-4 — Readiness ignores §17 criteria 3–5 (MEDIUM)

`evaluate_readiness` checks run state, node state, existing lease, and resource
conflicts only. Missing: required input ports have accepted records (criterion
3 — `input_bound` events are not even reduced), upstream required dependency
failed/cancelled/pending-appeal blocks (4), human gate approved (5). The
"successor requires inputs" invariant and "gate blocked until input" fixtures
are echo-tested only. Fix: reduce `edge_created`/`input_bound`/decision events
into the projection and evaluate criteria 3–5 from it.

### P1-5 — Resource matrix shortcuts vs §18 (MEDIUM)

In `scheduler.py`:
- `snapshot_id` on `ResourceClaim` is dead — read-during-write never grants for
  immutable-snapshot readers (§18.2 deterministic policy). Currently any
  read/write path overlap conflicts.
- `_paths_overlap` is exact-string set intersection. `src/**` vs `src/foo.py`
  does not overlap → false-compatible for read/write. No glob expansion, no
  `..` rejection, no normalization (§18 path rules 1–4; symlink/case rules 5–6
  can stay deferred).
- Untested matrix cells: review_write row/column, graph_write × write
  ("compatible unless patch touches active writer lease" — currently
  unconditionally compatible), external exclusive flag (one test only).

Fix: implement glob-aware overlap + snapshot-aware read grants; add one test
per testable §18 matrix cell (the slice 1.5 done-when promised this).

### P1-6 — No §15.6 planner / §15.7 review lifecycle fixtures (LOW)

COVERAGE.md has no rows for the planner and review node lifecycle tables.
Planner is the centerpiece of Phase 3; add the fixtures now while the corpus
pattern is being reworked (P1-2).

### P1-7 — Lease expiry tick missing (LOW)

§19: a controller tick with injected `now` appends `lease_expired` for leases
past `expires_at`. Projections consume `lease_expired` but nothing emits it,
and `LeaseModel.expires_at` is unused. Small pure function
`expire_leases(projection, now) -> list[EventEnvelope]`; natural home in the
P1-2 command applier (`ScheduleTick`).

### P1-8 — Callback validation skips execution/snapshot identity (LOW)

`validate_callback` ignores `execution_id` and `base_snapshot_id` (§19 requires
both in every callback; §27.2 invariant I-8 is snapshot mismatch). Validate
`execution_id` against the lease's recorded execution and reject
`base_snapshot_id` mismatches as `snapshot_incompatible`.

## Disposition — proposed tuning slices (per audit-checklist recording rule)

**Slice 1.8 — command applier + task projection formula** (P1-1, P1-2, P1-3,
P1-7). Done when: every fixture's `then_events` is produced by
`apply_command`, no fixture injects its own expected outcome, §14 formula
derives all six task states from raw facts, corpus test asserts
`result.passed`.

**Slice 1.9 — readiness completion + resource matrix** (P1-4, P1-5, P1-6,
P1-8). Done when: §17 criteria 1–8 each have a fixture that fails if the
criterion is removed; every testable §18 matrix cell has a test; planner/review
lifecycle fixtures exist and pass.

Then proceed to Phase 2 as specced in the sequencing deck (unchanged):
2.1 event store + outbox, 2.2 routine compiler, 2.3 runner integration,
2.4 file-state boundary (`classify_file_state` — the one §27.1 pure function
still absent, deliberately deferred), 2.5 LLM gatekeeper, 2.6 compat API/UI.
Slice 1.8's `apply_command` becomes the kernel half of the 2.1 controller.

## Test speed (current, measured)

Kernel suite (`test_graph_models`, `test_graph_projections`, `test_scheduler`,
`test_patch_validator`, `test_callbacks`, `test_fixture_corpus`,
`test_scenario_harness`): 76 tests in ~1.0s, slowest item 0.04s. All pure /
in-memory — no DB, no HTTP, no agents. Keep this property through 1.8/1.9: the
command applier must stay IO-free; fixture rework should add cases, not
fixtures-with-sleeps. Budget: corpus under 2s total.
