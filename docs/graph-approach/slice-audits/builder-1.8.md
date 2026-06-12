# Slice 1.8 — Command applier + §14 task projection formula (BUILDER)

You are the BUILDER agent for slice 1.8 of the task-world execution-graph kernel.

## Ground truth (read these first, in order)

1. `docs/graph-approach/execution-graph-prd-plus.md` — §10.1 (run lifecycle), §14 (task projection formula), §19 (lease/callback semantics, lease expiry), §27.3 (fixture format)
2. `docs/graph-approach/phase-1-punch-list.md` — items P1-1, P1-2, P1-3, P1-7 define this slice's scope exactly
3. Existing kernel: `src/orchestrator/graph/` (models, store, clock, projections, scenario, scheduler, callbacks, patch_validator)
4. Existing tests: `tests/unit/test_graph_*.py`, `test_scenario_harness.py`, `test_fixture_corpus.py`, `test_callbacks.py`; fixtures in `tests/fixtures/graph/`

## Scope — what to build

### 1. P1-1: §14 task projection formula (HIGH)

Extend `GraphProjection` and `reduce_event` in `src/orchestrator/graph/projections.py` to track, per `task_region_id`: candidates (from `output_record_accepted` / candidate-creating events, ordered by `attempt_number` then event position), verifier verdicts keyed by `candidate_id` (`verification_passed`/`verification_failed` — a verdict is IGNORED unless its `candidate_id` matches the candidate being evaluated), appeals (`appeal_opened`, `oversight_decision_recorded` with invalid-test outcomes), gate decisions (`approval_decision_recorded`), environment-failure checks, and active leases for the task region. Derive `task_states[task_region_id]` exactly per the PRD §14 formula:

- `accepted` — latest candidate has accepted verifier pass AND all configured gates passed
- `needs_revision` — latest candidate has accepted verifier failure and no active appeal overrides it
- `blocked_invalid_test` — oversight accepted invalid-test appeal and no replacement verification has passed
- `blocked_environment` — latest check failed as environment/tool error
- `in_progress` — a worker/verifier/check lease is active for the task region
- `pending` — no candidate attempt has started

"latest candidate" = highest `attempt_number`, then candidate creation event position.

### 2. P1-2: pure command applier (HIGH)

New module `src/orchestrator/graph/commands.py` with a pure function:

```python
apply_command(projection, events, command_type, payload, clock, id_gen) -> list[EventEnvelope]
```

No IO, no global time (use injected clock), no randomness (use injected id_gen). It routes commands through the existing kernel functions and returns the accepted/rejected events the controller would append:

- run lifecycle commands (`accept_run`, `start`, `pause`, `resume`, `cancel`, `complete`, `fail`) — validate against the §10.1 transition table; legal transition → `run_lifecycle_changed`; illegal → `command_rejected` with reason
- `submit_callback` — build a `CallbackRequest`, call `validate_callback`, emit `callback_accepted` (+ resulting node/lease events such as `node_state_changed` to completed and `lease_released`) or `callback_rejected_stale` / `callback_rejected_conflict` / `callback_duplicate_returned`
- `submit_patch` — call `validate_patch`, emit `graph_patch_accepted` (+ `node_created`/`edge_created`/`node_retired` per ops) or `graph_patch_rejected` with the validator's rejection reasons
- `schedule_tick` — call `schedule` over the projection's ready nodes, emit `node_ready` / `lease_granted` events for selected nodes; ALSO (P1-7) emit `lease_expired` for any active lease whose `expires_at` is at or before the injected `now` (track `expires_at` in the lease projection from `lease_granted` payloads)
- `raise_appeal` — well-formed → `appeal_opened` + oversight `node_created`; malformed → `command_rejected`
- `record_decision` (human approval/oversight) — emit `approval_decision_recorded` / `oversight_decision_recorded`

Update `run_scenario` in `src/orchestrator/graph/scenario.py`: when a scenario has a `when_command`, dispatch it through `apply_command` and append the RETURNED events to the store (keep appending a `command_recorded` event first for audit if you like, but `then_events` must be satisfiable only by applier output). Backward compatibility with echo fixtures is NOT a goal — the fixtures get rewritten (next point).

### 3. Rewrite the tautological fixtures

Rework these fixture files so `given_events` contain only prior facts and the behavior under test is produced by `when_command` through `apply_command`:

- `tests/fixtures/graph/task_projection.yaml` — 6 scenarios feed raw facts (candidate created, verification_passed/failed, appeal, gate decision, lease events) and assert the DERIVED `then_projection` task state. No scenario may inject `task_projection_changed`.
- `tests/fixtures/graph/run_lifecycle.yaml` — each transition driven by a lifecycle `when_command`; add at least 2 negative scenarios (illegal transition → `command_rejected`, run state unchanged).
- `tests/fixtures/graph/stale_callbacks.yaml` — each of the 10 §19 rows driven by a `submit_callback` command; `then_events` assert the applier's accept/reject event.
- `tests/fixtures/graph/invariants.yaml` — each invariant scenario must attempt the violation via `when_command` and assert the kernel rejects it (e.g. callback without valid lease → `callback_rejected_stale` PRODUCED by the applier; planner over-broad patch → `graph_patch_rejected` produced by validate_patch). Replace every `invariant_checked` echo. If an invariant genuinely needs slice-1.9 readiness logic (successor-requires-inputs, snapshot mismatch), keep the strongest assertion currently possible and mark it with a `# strengthened-in-1.9` comment.
- `tests/fixtures/graph/node_lifecycle_*.yaml` and `patch_validator.yaml` — convert where a command exists for the transition; pure state-recording rows may remain event-driven but must assert `then_projection`, not just echo `then_events`.

Update `tests/fixtures/graph/COVERAGE.md` to match.

### 4. P1-3: corpus test asserts results

In `tests/unit/test_fixture_corpus.py::test_all_fixtures_run_through_harness`, assert `result.passed` with `result.failures` in the failure message. Keep the duplicate check in `test_graph_projections.py` or dedupe — your call, but at least one corpus-wide `passed` assertion must exist in the corpus test file.

### 5. Unit tests

Add `tests/unit/test_graph_commands.py` covering: every lifecycle transition (legal + illegal), callback accept and each reject path, patch accept/reject, schedule_tick granting leases, lease expiry on tick (P1-7: lease with `expires_at` past injected now → `lease_expired` emitted; future → not emitted), appeal open/reject. Extend `tests/unit/test_graph_projections.py` with direct §14 formula tests: each of the 6 states, latest-candidate selection by attempt_number then position, verdict ignored when candidate_id mismatches.

## Done when (all must hold)

1. Every fixture's `then_events` for command-driven scenarios is produced by `apply_command` — no fixture injects its own expected outcome event.
2. §14 formula derives all six task states from raw facts; `project_task_states` returns real values.
3. `test_all_fixtures_run_through_harness` asserts `result.passed`.
4. `lease_expired` emitted by `schedule_tick` for past-expiry leases.
5. `uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_projections.py tests/unit/test_scheduler.py tests/unit/test_patch_validator.py tests/unit/test_callbacks.py tests/unit/test_fixture_corpus.py tests/unit/test_scenario_harness.py tests/unit/test_graph_commands.py -q` is green and completes in under 5 seconds.
6. `uv run ruff check src/orchestrator/graph tests/unit tests/fixtures` and `uv run pyright src/orchestrator/graph` (if pyright configured; otherwise skip) pass.

## Hard constraints

- Pure kernel only: no filesystem (beyond reading fixtures in tests), no network, no DB, no FastAPI, no runner imports inside `src/orchestrator/graph/`.
- NO mocks, NO monkeypatching anywhere in tests (project standard, non-negotiable).
- Touch ONLY: `src/orchestrator/graph/**`, `tests/unit/test_graph_*.py`, `tests/unit/test_scenario_harness.py`, `tests/unit/test_fixture_corpus.py`, `tests/unit/test_callbacks.py`, `tests/unit/test_scheduler.py`, `tests/unit/test_patch_validator.py`, `tests/fixtures/graph/**`. Do not modify any other file. The working tree has unrelated modified files — leave them exactly as they are.
- Do NOT run `git commit`, `git stash`, `git checkout`, `git reset`, or any git command that mutates state. Read-only git (status/diff/log) is fine.
- Do NOT touch `orchestrator.db`, `.orchestrator/`, or start any server.
- Keep the kernel's existing public API in `src/orchestrator/graph/__init__.py` working; add new exports (`apply_command`, etc.).

## Output

Finish with a summary: files changed, test counts before/after, wall-clock of the kernel test run, and an honest list of anything you could not complete.
