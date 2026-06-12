# Slice 1.8 Audit Report — command applier + §14 task projection formula

## Re-derived Acceptance Criteria

1. `apply_command` must be the pure command kernel used by scenario fixtures: `when_command` must produce `then_events`; fixtures must not satisfy expected outcomes by injecting them in `given_events`.
2. Run lifecycle commands must enforce the §10.1 lifecycle transition table and reject illegal/terminal transitions, including resume after cancel.
3. Callback commands must require the §19 callback identity fields and route through stale/idempotency validation before emitting accepted/rejected events.
4. Duplicate callback with same idempotency key and same payload must return the prior result; same key with different payload must reject as idempotency conflict.
5. Callback for revoked/expired/suspended/released/old-generation authority must emit `callback_rejected_stale` and not mutate node outcome.
6. Patch commands must route through `validate_patch`; accepted patches emit graph events, rejected patches emit rejection events, and stale invalidating read-set conflicts reject.
7. `schedule_tick` must use injected `now` to append `lease_expired` for active leases past `expires_at`; future-expiry leases must remain active without silent projection changes.
8. The §14 task projection must derive states from raw candidate/verifier/gate/appeal/check/lease facts, not from injected `task_projection_changed` events.
9. §14 `accepted`: latest candidate has a matching accepted verifier pass and all configured gates passed.
10. §14 `needs_revision`: latest candidate has a matching accepted verifier failure and no active appeal overrides it.
11. §14 `blocked_invalid_test`: oversight accepted invalid-test appeal and no replacement verification has passed.
12. §14 `blocked_environment`: latest check failed as environment/tool error.
13. §14 `in_progress` and `pending`: active worker/verifier/check lease yields `in_progress`; no candidate attempt started yields `pending`.
14. Latest candidate selection must use highest `attempt_number`, then candidate creation event position; verifier/check results whose `candidate_id` does not match the latest candidate must be ignored.
15. Corpus test must assert `result.passed`, and new/changed tests must follow project standards: no mocks/monkeypatching, pure/in-memory, kernel suite under 5 seconds.
16. Reducers and command kernel must be deterministic: no wall-clock, random, filesystem, network, or generated IDs except injected event payloads/clock/id generator.

## Criteria Table

| # | criterion | code evidence | test evidence | status |
|---|---|---|---|---|
| 1 | Fixtures route `when_command` through `apply_command`; no injected expected outcomes | `run_scenario` records command and calls `apply_command` at `src/orchestrator/graph/scenario.py:35-59`; `apply_command` dispatcher at `src/orchestrator/graph/commands.py:52-86` | Harness test `tests/unit/test_scenario_harness.py:24-59`; corpus asserts pass at `tests/unit/test_fixture_corpus.py:42-51` | PARTIAL |
| 2 | Run lifecycle commands enforce §10.1 and reject illegal transitions | Transition map and rejection path at `src/orchestrator/graph/commands.py:32-40`, `src/orchestrator/graph/commands.py:89-125` | `tests/unit/test_graph_commands.py:78-104`; resume-after-cancel fixture `tests/fixtures/graph/stale_callbacks.yaml:69-75` | MET |
| 3 | Callback command requires §19 identity fields and calls validator | Required fields and `validate_callback` call at `src/orchestrator/graph/commands.py:128-166` | `tests/unit/test_graph_commands.py:107-163`; `tests/unit/test_callbacks.py:83-239` | MET |
| 4 | Duplicate idempotent callback and idempotency conflict behavior | Idempotency scan at `src/orchestrator/graph/callbacks.py:91-113`; command event mapping at `src/orchestrator/graph/commands.py:176-186` | `tests/unit/test_callbacks.py:90-122`; `tests/unit/test_graph_commands.py:128-163` | MET |
| 5 | Stale revoked/expired/suspended/released/old-generation callbacks reject without outcome mutation | Lease/node/run stale checks at `src/orchestrator/graph/callbacks.py:61-83`; stale event mapping at `src/orchestrator/graph/commands.py:176-179` | `tests/unit/test_callbacks.py:139-239`; fixture rows `tests/fixtures/graph/stale_callbacks.yaml:19-97` | MET |
| 6 | Patch commands validate patches and reject stale invalidating read-set conflicts | Patch construction and validation at `src/orchestrator/graph/commands.py:214-259`; stale validation at `src/orchestrator/graph/patch_validator.py:145-172` | `tests/unit/test_graph_commands.py:166-198`; `tests/unit/test_patch_validator.py:88-142` | PARTIAL |
| 7 | `schedule_tick` emits `lease_expired` only for past active leases | Schedule tick path at `src/orchestrator/graph/commands.py:262-330`; expiry logic at `src/orchestrator/graph/commands.py:409-433` | `tests/unit/test_graph_commands.py:226-255`; adversarial future-expiry probe emitted no events | MET |
| 8 | §14 derives all six task states from raw facts | Projection reducer handles candidate/verdict/appeal/gate/environment/lease facts at `src/orchestrator/graph/projections.py:165-179`, `src/orchestrator/graph/projections.py:214-383` | Unit tests for six states at `tests/unit/test_graph_projections.py:206-288`; fixture rows `tests/fixtures/graph/task_projection.yaml:1-48` | PARTIAL |
| 9 | `accepted` requires matching verifier pass and all configured gates passed | Matching verdict lookup and gate check at `src/orchestrator/graph/projections.py:356-363` | Pass-with-approved-gate test at `tests/unit/test_graph_projections.py:206-221`; no configured-but-undecided gate test | UNMET |
| 10 | `needs_revision` unless active appeal overrides latest failure | Failure/override branch at `src/orchestrator/graph/projections.py:370-375`; active appeal helper at `src/orchestrator/graph/projections.py:392-395` | Failure test at `tests/unit/test_graph_projections.py:224-235`; no test for active appeal override | UNMET |
| 11 | `blocked_invalid_test` until replacement verification passes | Invalid-test block branch at `src/orchestrator/graph/projections.py:364-369`; replacement helper at `src/orchestrator/graph/projections.py:398-414` | Blocked-invalid-test test at `tests/unit/test_graph_projections.py:238-258`; no replacement-pass test | UNMET |
| 12 | `blocked_environment` on environment/tool check failure | Environment recording at `src/orchestrator/graph/projections.py:312-333`; branch at `src/orchestrator/graph/projections.py:376-377` | `tests/unit/test_graph_projections.py:261-273`; fixture `tests/fixtures/graph/task_projection.yaml:27-33` | MET |
| 13 | `in_progress` and `pending` states | Lease task association at `src/orchestrator/graph/projections.py:117-153`; derivation at `src/orchestrator/graph/projections.py:350-353`, `src/orchestrator/graph/projections.py:378-381`, `src/orchestrator/graph/projections.py:417-425` | `tests/unit/test_graph_projections.py:276-288`; fixture `tests/fixtures/graph/task_projection.yaml:35-48` | MET |
| 14 | Latest candidate by attempt then event position; mismatched candidate verdict ignored | Latest candidate helper at `src/orchestrator/graph/projections.py:386-390`; verdict scoped by latest candidate at `src/orchestrator/graph/projections.py:356-358` | Mismatched verdict test at `tests/unit/test_graph_projections.py:316-327`; test named latest candidate at `tests/unit/test_graph_projections.py:291-313` covers highest attempt but not a pure attempt-number tie | PARTIAL |
| 15 | Corpus asserts `result.passed`; tests no mocks and pure/fast | Corpus assertion at `tests/unit/test_fixture_corpus.py:42-51` | Fresh required suite: `96 passed in 1.08s`; grep found no `monkeypatch`, `MagicMock`, or `unittest.mock` in target tests | MET |
| 16 | Deterministic reducers/command kernel | `apply_command` accepts injected `clock`/`id_gen` at `src/orchestrator/graph/commands.py:52-63`; event factory uses those at `src/orchestrator/graph/commands.py:468-485` | `rg -n "datetime\\.now|time\\.time|random|uuid" src/orchestrator/graph` returned no matches | MET |

## Fresh Test Run

Command:

```bash
uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_projections.py tests/unit/test_scheduler.py tests/unit/test_patch_validator.py tests/unit/test_callbacks.py tests/unit/test_fixture_corpus.py tests/unit/test_scenario_harness.py tests/unit/test_graph_commands.py -q
```

Observed:

```text
96 passed in 1.08s
```

No `UV_CACHE_DIR` override was required.

## Adversarial Pass

| attack | observed result |
|---|---|
| Illegal run transition: `complete` from `queued` | `command_rejected` with reason `illegal transition from queued` |
| Callback with revoked lease | `callback_rejected_stale`, reason `lease revoked` |
| Callback duplicate key with different payload | `callback_rejected_conflict`, reason `idempotency payload conflict` |
| Patch with stale invalidating read-set | `graph_patch_rejected`, reason `stale patch conflicts with invalidating events`, read-set `["worker-1"]` |
| `schedule_tick` with expired lease | `lease_expired` emitted for the expired lease |
| `schedule_tick` with future-expiry lease | No expiry event emitted |
| Latest-candidate tie by `attempt_number` then event position | Projection chose later same-attempt candidate and returned `accepted` |
| Verdict with mismatched `candidate_id` | Mismatched pass ignored; projection stayed `pending` |
| Gate explicitly unapproved | Projection stayed `pending`, not `accepted` |
| Configured gate with no decision | Projection incorrectly returned `accepted` |
| Invalid-test appeal accepted, replacement verification passes | Projection returned `accepted`, leaving `blocked_invalid_test` |
| Malformed `record_decision` approval/oversight payloads | `approval_decision_recorded` / `oversight_decision_recorded` emitted anyway |

## Findings

| severity | laziness/lie/standards | description | location |
|---|---|---|---|
| HIGH | correctness | §14 gate handling is incomplete. The reducer only tracks gate decisions, not configured gates, so a passed candidate with a configured but undecided gate projects to `accepted`. This violates "all configured gates passed." | `src/orchestrator/graph/projections.py:297-310`, `src/orchestrator/graph/projections.py:358-363` |
| HIGH | laziness | `record_decision` emits accepted approval/oversight events without validating required payload shape, target node/run state, cancellation, or lease/authority. Malformed decisions become accepted events instead of rejections. | `src/orchestrator/graph/commands.py:368-377` |
| HIGH | laziness | Patch command applier still has stubbed accepted branches. `create_gate`, `create_revision_attempt`, `create_appeal`, `set_resource_claims`, `set_allowed_actions`, and `mark_plan_region_suspect` can validate as accepted but `_patch_op_events` emits no graph events for them. | `src/orchestrator/graph/commands.py:380-406` |
| HIGH | lie | Fixture `invariant_snapshot_mismatch_not_consumed` now asserts `callback_accepted` for a base snapshot mismatch. P1-8 may be deferred, but a fixture named as the invariant should not encode the opposite behavior. | `tests/fixtures/graph/invariants.yaml:82-91` |
| MEDIUM | laziness | 32 scenarios with `when_command: null` still have `then_events` satisfiable purely by `given_events`. All 32 also assert nonempty projections, so they are legitimate pure-projection scenarios, but the event assertions are still echo-style and add no command-kernel coverage. | Examples: `tests/fixtures/graph/node_lifecycle_worker.yaml:5-73`, `tests/fixtures/graph/readiness.yaml:6-85` |
| MEDIUM | laziness | Eight scenarios use `then_projection: {}`. This lets command-event fixtures avoid proving any derived state, and `test_fixture_corpus_then_projections_satisfied` skips falsy projections. | `tests/fixtures/graph/invariants.yaml:20-26`, `tests/fixtures/graph/invariants.yaml:48-61`, `tests/fixtures/graph/invariants.yaml:104-110`, `tests/fixtures/graph/patch_validator.yaml:35-80`, `tests/fixtures/graph/stale_callbacks.yaml:1-17`, `tests/unit/test_graph_projections.py:337-340` |
| MEDIUM | lie | "Full fixture rewrite" is unsupported by the diff. Only 8 of 11 YAML fixture files changed; `node_lifecycle_appeal.yaml`, `node_lifecycle_gate.yaml`, and `readiness.yaml` are unchanged. | `git diff --name-only -- tests/fixtures/graph`; `find tests/fixtures/graph -name '*.yaml'` |
| MEDIUM | laziness | Latest-candidate test is mislabeled/incomplete: it proves higher `attempt_number` beats lower attempt, but does not isolate the event-position tie-break. The adversarial scratch probe passed, but the required test evidence is missing. | `tests/unit/test_graph_projections.py:291-313` |
| MEDIUM | laziness | No test covers "active appeal overrides latest verifier failure." The helper exists, but the acceptance criterion has no direct test evidence. | `src/orchestrator/graph/projections.py:392-395`; absent from `tests/unit/test_graph_projections.py` |
| MEDIUM | laziness | No test covers accepted invalid-test appeal followed by replacement verification pass leaving `blocked_invalid_test`. The scratch probe passed, but there is no committed test evidence. | `src/orchestrator/graph/projections.py:398-414`; absent from `tests/unit/test_graph_projections.py` |
| LOW | standards | No mock/monkeypatch violation found in the target tests. The grep hit `_patch(...)` helper names only when searching broadly for `patch`, not mocking APIs. | Target test grep |
| LOW | standards | Determinism grep found no `datetime.now`, `time.time`, `random`, or `uuid` usage in `src/orchestrator/graph`. | `src/orchestrator/graph` grep |

## Laziness Check Details

Fixture echo count across all fixture files:

- `echo_null_total`: 32 scenarios where `when_command` is null and all `then_events` are satisfiable by `given_events`.
- `echo_null_legit_nonempty_projection`: 32. These do assert a derived projection, so they are not empty theater, but the event assertions are still echoes.
- `echo_null_theater_no_projection`: 0.
- `then_projection_empty_dict`: 8 scenarios.
- `then_projection_missing_or_null`: 0.
- `then_projection_nonempty`: 71 scenarios.

The empty projection scenarios are:

- `invariants.yaml::invariant_no_callback_without_valid_lease`
- `invariants.yaml::invariant_planner_authority_scoped`
- `invariants.yaml::invariant_file_state_rejects_residue`
- `patch_validator.yaml::patch_stale_requirement_in_read_set_rejected`
- `patch_validator.yaml::patch_stale_retired_region_rejected`
- `patch_validator.yaml::patch_planner_create_gate_rejected`
- `stale_callbacks.yaml::stale_duplicate_same_payload`
- `stale_callbacks.yaml::stale_duplicate_different_payload`

## Lies Check Details

- Builder claim "96 passed in 1.08s": verified true by fresh run.
- Builder claim "full fixture rewrite": not fully supported. Fixture diff touched `COVERAGE.md` and 8 YAML files, but 3 YAML fixture files were unchanged.
- Determinism: verified by grep; no forbidden nondeterminism found in `src/orchestrator/graph`.

## Verdict

BOUNCE — The core shape is real: `apply_command` exists, fixtures can route commands through it, callback/patch/schedule paths are mostly exercised, and the fresh suite is green. But the slice is not done against the re-derived criteria. The §14 formula still accepts a task with a configured but undecided gate, several formula branches lack test evidence, command applier has accepted no-op/stub branches, malformed decision commands emit accepted events, and the fixture corpus still contains echo assertions plus empty projections. These are not cosmetic gaps; they touch the command kernel and the task projection formula the slice was meant to settle.
