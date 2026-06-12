**Criteria Table**

| # | criterion | code evidence | test evidence | status |
|---|---|---|---|---|
| 1 | Dispatch must be durable: `lease_granted` + `agent_dispatch_requested` + outbox row before side effect. | [controller.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/controller.py:80), [outbox.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/outbox.py:71) | `test_agent_dispatch_requested_event_envelope_is_persisted_exactly`, `test_controller_does_not_start_side_effect_before_commit`, `test_controller_rolls_back_events_when_dispatch_outbox_insert_fails` | PASS |
| 2 | Outbox dispatch starts/resumes runner and callback includes lease identity. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:121), [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:209) | `test_graph_runner_builder_verifier_pass_accepts_task`, `test_graph_runner_rejects_stale_generation_callback_through_stack` | PARTIAL |
| 3 | `acknowledge_start` marks leased node running before normal execution. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:123), [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:665) | `test_acknowledge_start_validates_lease_identity_and_marks_running` | PARTIAL |
| 4 | Worker/verifier lifecycle must not allow callback completion before running. | [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:294), [callbacks.py](/Users/peter/code/task-world/src/orchestrator/graph/callbacks.py:88) | No test for submit-before-ack ordering. | UNMET |
| 5 | Runtime recovery must retry pending outbox and not start side effects before accepted events. | [recovery.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/recovery.py:23), [outbox.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/outbox.py:124) | `test_crash_after_append_before_outbox_starts_agent_restarts_dispatch`, `test_restart_mid_dispatching_row_is_retried_idempotently` | PASS |
| 6 | Restart recovery must reattach live managed process, continue waiting, and not infer success. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:243) | `test_graph_runner_restart_reattaches_running_builder` | PARTIAL |
| 7 | Missing process path must append `agent_died`, revoke lease, and reschedule. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:257), [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:706) | `test_graph_runner_restart_marks_missing_builder_dead_and_redispatches`, `test_agent_died_revokes_active_lease_and_requeues_node` | PASS |
| 8 | Callback validation must enforce `lease_id`, exact generation, `execution_id`, `base_snapshot_id`. | [callbacks.py](/Users/peter/code/task-world/src/orchestrator/graph/callbacks.py:61) | Old-generation stack test only: `test_graph_runner_rejects_stale_generation_callback_through_stack` | UNMET |
| 9 | Task projection: accepted only for latest candidate with verifier pass; needs_revision on verifier failure; ignore mismatched candidate. | [projections.py](/Users/peter/code/task-world/src/orchestrator/graph/projections.py:482) | `test_task_projection_accepted`, `test_task_projection_needs_revision`, `test_task_projection_ignores_mismatched_verdict_candidate`, runner pass/fail e2e tests | PASS |
| 10 | Verifier records must be produced only by verifier and bound to candidate input; builder cannot self-accept. | [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:383) | Bound/unbound verifier tests exist; no worker-smuggled `record_kind:"verification"` test. | UNMET |
| 11 | ExecutionContext must be built from graph facts, not hardcoded test strings. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:148), [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:300) | Covered indirectly by runner e2e seeded from `RoutineConfig`; not asserted directly. | PARTIAL |
| 12 | Slice done-when: real repo build → boundary → verify → accepted; verifier fail → needs_revision from SQLite readback. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:343) | `test_graph_runner_builder_verifier_pass_accepts_task`, `test_graph_runner_verifier_fail_needs_revision`; repos created with `git init`. | PASS |
| 13 | No real LLM in tests; no mocking/monkeypatching. | Test code uses hand-written fakes. | grep found no `unittest.mock`, `MagicMock`, `patch`, or `monkeypatch` in relevant tests. | PASS |

**Findings**

| severity | type | description | location |
|---|---|---|---|
| HIGH | lease identity | Future lease generations are accepted. `validate_callback` rejects only `request.lease_generation < generation`, so generation `999` against active generation `1` passes. §19 requires lease generation identity, not “not older than current.” | [callbacks.py](/Users/peter/code/task-world/src/orchestrator/graph/callbacks.py:84) |
| HIGH | lifecycle | A mutating callback can complete a node while it is still `leased`, before `acknowledge_start`. The validator rejects terminal states only; `leased` is accepted, then `_apply_callback_command` emits `node_state_changed completed` and `lease_released`. This violates §15.1/§15.2 leased → running → completed ordering. | [callbacks.py](/Users/peter/code/task-world/src/orchestrator/graph/callbacks.py:88), [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:294) |
| HIGH | test coverage | No adversarial test covers a worker callback smuggling `record_kind:"verification"`. The pure kernel appears to reject it, but by the audit protocol “no test evidence = UNMET.” | [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:398), [test_graph_commands.py](/Users/peter/code/task-world/tests/unit/test_graph_commands.py:187) |
| MED | restart realism | The “reattach” restart test reuses the same live `BlockingSubmitAgent`, same `running` task dict, same engine/session factory, same clock, and same ID generator. It does not discard all in-memory runtime state and rebuild from only the DB file, so it does not prove server-restart realism. | [test_graph_runner_e2e.py](/Users/peter/code/task-world/tests/integration/test_graph_runner_e2e.py:305) |
| MED | recovery behavior | There is no test for runner `execute()` raising mid-run and proving `agent_died` is appended and the lease is not stuck. Code has a catch path, but no test evidence. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:145) |
| MED | dispatch identity | Dispatcher falls back to `base_snapshot_id="S0"` if the dispatch payload lacks it. That re-derives identity instead of requiring the durable dispatch payload to carry it. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:166) |

**Verification Run**

`uv run pytest tests/integration/test_graph_runner_e2e.py -q`: 5 passed in 2.73s  
`uv run pytest tests/unit -q`: 2592 passed in 14.72s  
`uv run pytest tests/integration/test_graph_outbox_crash_points.py tests/integration/test_graph_routine_compile.py tests/integration/test_graph_event_store.py -q`: 46 passed in 4.03s  
Kernel subset: 95 passed in 0.89s  
Purity grep for I/O imports in `src/orchestrator/graph/`: no matches  
`uv run ruff check src tests`: passed

**Verdict**

BOUNCE. The happy-path runner cycle and several crash-point behaviors are implemented and passing, but the pure kernel still accepts callbacks with future lease generations and can complete nodes before start acknowledgement. The restart evidence is also too in-memory to prove the slice’s restart recovery claim. Fix those lifecycle/identity bugs and add the missing adversarial tests before accepting slice 2.3.
tokens used
165,020
**Criteria Table**

| # | criterion | code evidence | test evidence | status |
|---|---|---|---|---|
| 1 | Dispatch must be durable: `lease_granted` + `agent_dispatch_requested` + outbox row before side effect. | [controller.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/controller.py:80), [outbox.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/outbox.py:71) | `test_agent_dispatch_requested_event_envelope_is_persisted_exactly`, `test_controller_does_not_start_side_effect_before_commit`, `test_controller_rolls_back_events_when_dispatch_outbox_insert_fails` | PASS |
| 2 | Outbox dispatch starts/resumes runner and callback includes lease identity. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:121), [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:209) | `test_graph_runner_builder_verifier_pass_accepts_task`, `test_graph_runner_rejects_stale_generation_callback_through_stack` | PARTIAL |
| 3 | `acknowledge_start` marks leased node running before normal execution. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:123), [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:665) | `test_acknowledge_start_validates_lease_identity_and_marks_running` | PARTIAL |
| 4 | Worker/verifier lifecycle must not allow callback completion before running. | [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:294), [callbacks.py](/Users/peter/code/task-world/src/orchestrator/graph/callbacks.py:88) | No test for submit-before-ack ordering. | UNMET |
| 5 | Runtime recovery must retry pending outbox and not start side effects before accepted events. | [recovery.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/recovery.py:23), [outbox.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/outbox.py:124) | `test_crash_after_append_before_outbox_starts_agent_restarts_dispatch`, `test_restart_mid_dispatching_row_is_retried_idempotently` | PASS |
| 6 | Restart recovery must reattach live managed process, continue waiting, and not infer success. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:243) | `test_graph_runner_restart_reattaches_running_builder` | PARTIAL |
| 7 | Missing process path must append `agent_died`, revoke lease, and reschedule. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:257), [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:706) | `test_graph_runner_restart_marks_missing_builder_dead_and_redispatches`, `test_agent_died_revokes_active_lease_and_requeues_node` | PASS |
| 8 | Callback validation must enforce `lease_id`, exact generation, `execution_id`, `base_snapshot_id`. | [callbacks.py](/Users/peter/code/task-world/src/orchestrator/graph/callbacks.py:61) | Old-generation stack test only: `test_graph_runner_rejects_stale_generation_callback_through_stack` | UNMET |
| 9 | Task projection: accepted only for latest candidate with verifier pass; needs_revision on verifier failure; ignore mismatched candidate. | [projections.py](/Users/peter/code/task-world/src/orchestrator/graph/projections.py:482) | `test_task_projection_accepted`, `test_task_projection_needs_revision`, `test_task_projection_ignores_mismatched_verdict_candidate`, runner pass/fail e2e tests | PASS |
| 10 | Verifier records must be produced only by verifier and bound to candidate input; builder cannot self-accept. | [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:383) | Bound/unbound verifier tests exist; no worker-smuggled `record_kind:"verification"` test. | UNMET |
| 11 | ExecutionContext must be built from graph facts, not hardcoded test strings. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:148), [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:300) | Covered indirectly by runner e2e seeded from `RoutineConfig`; not asserted directly. | PARTIAL |
| 12 | Slice done-when: real repo build → boundary → verify → accepted; verifier fail → needs_revision from SQLite readback. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:343) | `test_graph_runner_builder_verifier_pass_accepts_task`, `test_graph_runner_verifier_fail_needs_revision`; repos created with `git init`. | PASS |
| 13 | No real LLM in tests; no mocking/monkeypatching. | Test code uses hand-written fakes. | grep found no `unittest.mock`, `MagicMock`, `patch`, or `monkeypatch` in relevant tests. | PASS |

**Findings**

| severity | type | description | location |
|---|---|---|---|
| HIGH | lease identity | Future lease generations are accepted. `validate_callback` rejects only `request.lease_generation < generation`, so generation `999` against active generation `1` passes. §19 requires lease generation identity, not “not older than current.” | [callbacks.py](/Users/peter/code/task-world/src/orchestrator/graph/callbacks.py:84) |
| HIGH | lifecycle | A mutating callback can complete a node while it is still `leased`, before `acknowledge_start`. The validator rejects terminal states only; `leased` is accepted, then `_apply_callback_command` emits `node_state_changed completed` and `lease_released`. This violates §15.1/§15.2 leased → running → completed ordering. | [callbacks.py](/Users/peter/code/task-world/src/orchestrator/graph/callbacks.py:88), [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:294) |
| HIGH | test coverage | No adversarial test covers a worker callback smuggling `record_kind:"verification"`. The pure kernel appears to reject it, but by the audit protocol “no test evidence = UNMET.” | [commands.py](/Users/peter/code/task-world/src/orchestrator/graph/commands.py:398), [test_graph_commands.py](/Users/peter/code/task-world/tests/unit/test_graph_commands.py:187) |
| MED | restart realism | The “reattach” restart test reuses the same live `BlockingSubmitAgent`, same `running` task dict, same engine/session factory, same clock, and same ID generator. It does not discard all in-memory runtime state and rebuild from only the DB file, so it does not prove server-restart realism. | [test_graph_runner_e2e.py](/Users/peter/code/task-world/tests/integration/test_graph_runner_e2e.py:305) |
| MED | recovery behavior | There is no test for runner `execute()` raising mid-run and proving `agent_died` is appended and the lease is not stuck. Code has a catch path, but no test evidence. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:145) |
| MED | dispatch identity | Dispatcher falls back to `base_snapshot_id="S0"` if the dispatch payload lacks it. That re-derives identity instead of requiring the durable dispatch payload to carry it. | [dispatch.py](/Users/peter/code/task-world/src/orchestrator/graph_runtime/dispatch.py:166) |

**Verification Run**

`uv run pytest tests/integration/test_graph_runner_e2e.py -q`: 5 passed in 2.73s  
`uv run pytest tests/unit -q`: 2592 passed in 14.72s  
`uv run pytest tests/integration/test_graph_outbox_crash_points.py tests/integration/test_graph_routine_compile.py tests/integration/test_graph_event_store.py -q`: 46 passed in 4.03s  
Kernel subset: 95 passed in 0.89s  
Purity grep for I/O imports in `src/orchestrator/graph/`: no matches  
`uv run ruff check src tests`: passed

**Verdict**

BOUNCE. The happy-path runner cycle and several crash-point behaviors are implemented and passing, but the pure kernel still accepts callbacks with future lease generations and can complete nodes before start acknowledgement. The restart evidence is also too in-memory to prove the slice’s restart recovery claim. Fix those lifecycle/identity bugs and add the missing adversarial tests before accepting slice 2.3.
