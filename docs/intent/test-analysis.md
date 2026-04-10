# Integration Test Analysis & Optimization Strategy

*Generated: 2026-04-09. Based on analysis of ~90 integration test files.*

---

## Executive Summary

The integration test suite has grown organically and suffers from three main problems:

1. **~15 files are unit tests misplaced in `tests/integration/`** — they test internal implementation details and should move to `tests/unit/`. Moving them won't change coverage but will run faster (no DB setup overhead) and make the integration suite smaller.

2. **~6 duplication clusters** where multiple files test the same lifecycle scenario with minor variations. Consolidation could reduce test count by ~30% without losing any coverage.

3. **~10 files have timing-dependent tests** using `asyncio.sleep()` polling loops instead of event-driven waiting. These are the primary flakiness risk.

The good news: most tests use the `drain()` helper pattern correctly — no widespread sleep abuse, good async patterns overall.

---

## Behavior Inventory

### Workflow Lifecycle
| Behavior | Tested In |
|----------|-----------|
| DRAFT → ACTIVE → COMPLETED | test_parity_linear, test_workflow_execution, test_workflow_service, test_mock_agent_workflow, test_api_full_lifecycle |
| DRAFT → ACTIVE → PAUSED → ACTIVE | test_parity_pause_resume, test_signal_queue, test_api_full_lifecycle |
| Task revision cycle (grade F → new attempt) | test_parity_revision, test_workflow_service, test_api_full_lifecycle |
| Fan-out (parent → N child tasks) | test_parity_fan_out, test_parity_fan_out_replay, test_fan_out |
| Conditional step skipping | test_parity_skip, test_conditional_steps, test_repeat_for_edge_cases, test_skip_step_api |
| Backward step transition | test_api_backward_transitions |
| Run recovery (rewind to task) | test_api_runs, test_api_runs_recover |
| Idempotent API calls | test_idempotency |
| STOPPING state transitions | test_stopping_state |
| Escalation | test_api_escalation |

### User Interaction Gates
| Behavior | Tested In |
|----------|-----------|
| Human approval gate | test_api_human_approval, test_approval_workflow, test_api_approval |
| Clarification request/response | test_api_clarifications, test_clarification_workflow |
| User-managed agent lifecycle | test_api_user_managed, test_user_managed_agent |
| Pending actions list | test_api_clarifications, test_approval_workflow |

### Agents & Execution
| Behavior | Tested In |
|----------|-----------|
| CLI agent subprocess execution | test_cli_agent |
| Claude SDK agent lifecycle | test_claude_sdk_agent |
| OpenHands local agent | test_openhands_agent |
| OpenHands Docker agent | test_openhands_docker_agent |
| Codex server agent lifecycle | test_codex_lifecycle |
| Codex callback routing | test_codex_server_callbacks |
| Agent executor error handling | test_agent_executor |
| Executor loop invariants | test_executor_loop_invariant |
| Pre-run health check | test_executor_health_check |
| Agent death detection | test_agent_monitor |
| Agent config CRUD | test_api_agent_configs |
| Agent runners list/quota | test_api_agents |
| Model profiles | test_api_model_profiles |
| Agent system prompt injection | test_prompt_agent_system_prompt, test_e2e_agent_overrides |
| Verifier model pinning | test_verifier_model_pinning |

### Auto-Verify
| Behavior | Tested In |
|----------|-----------|
| Pre-gate auto-verify (blocks submit) | test_auto_verify_workflow, test_auto_verify_timing |
| Post-gate auto-verify (proceeds to VERIFYING) | test_auto_verify_workflow |
| Auto-verify with non-must items | test_auto_verify_workflow |

### Persistence & Recovery
| Behavior | Tested In |
|----------|-----------|
| DB persistence across restarts | test_parity_recovery, test_full_persistence |
| Event journal replay | test_parity_replay, test_event_recovery, test_event_journal_replay |
| Batch replay with checkpointing | test_event_journal_replay, test_db_recovery_e2e |
| Signal redelivery on startup | test_signal_redelivery |
| Event store append/retrieve | test_event_store |

### API Surface
| Behavior | Tested In |
|----------|-----------|
| Runs CRUD + lifecycle | test_api_runs, test_api_runs_validation |
| Tasks CRUD + checklist | test_api_tasks |
| Routines CRUD + validation | test_api_routines, test_project_routines |
| Repos list + branch ops | test_api_repos, test_api_repos_validation |
| Activity feed + SSE | test_api_activity |
| WebSocket run subscriptions | test_api_websocket |
| Auth / JWT | test_api_auth |
| Health endpoint | test_api_health |
| MCP endpoints (SSE, tools) | test_mcp_server, test_mcp_sse, test_mcp_tools |
| Prune API | test_prune_api |
| Env files | test_api_runs_envfiles, test_envfile_workflow, test_envfile_events, test_envfile_revert |
| Codex agent types | test_api_runs_codex_agent_types |
| Run recovery API | test_api_runs_recover |
| Skip step API | test_skip_step_api |

### Review & Merge
| Behavior | Tested In |
|----------|-----------|
| Diff API (aggregate, commit, task scope) | test_review_api |
| Merge readiness gates | test_review_merge_readiness |
| Background test execution | test_review_test_api |
| Back-merge clean/conflict | test_conflict_back_merge |
| Conflict resolution (ours/theirs/manual) | test_conflict_resolve |

### Infrastructure
| Behavior | Tested In |
|----------|-----------|
| Worktree creation | test_worktree |
| Scaffolding file copy | test_scaffolding |
| DB table creation + cascade | test_database |
| Run repository roundtrip | test_repositories |
| Clarification repository CRUD | test_clarification_repository |
| Branch ops (git) | test_branch_ops, test_api_branch_ops |
| Signal queue processing | test_signal_queue |
| CLI commands | test_cli, test_cli_repos |

---

## Problems

### 1. Unit Tests Disguised as Integration Tests

These files belong in `tests/unit/` — they test internal components with no need for the full app stack:

| File | What it actually tests |
|------|----------------------|
| `test_event_store.py` | EventStore.append/get mechanics, payload serialization |
| `test_signal_redelivery.py` | SignalConsumer._redeliver_on_startup() internals, direct DB manipulation |
| `test_clarification_repository.py` | ClarificationRepository CRUD — pure data layer |
| `test_database.py` | ORM table creation and cascade delete behavior |
| `test_repositories.py` | RunRepository.save/get — pure data layer |
| `test_agent_resolution.py` | get_agent_system_prompt() — simple DB lookup function |
| `test_executor_health_check.py` | AgentRunnerExecutor._run_project_health_check() — internal method |
| `test_branch_ops.py` | Low-level git branch operations, no workflow context needed |

**Additional files with unit tests embedded in integration files:**
- `test_auto_verify_workflow.py` — `TestFindTaskConfig` and `TestResolveAutoVerifyConfig` classes test pure helper functions; extract them
- `test_api_human_approval.py` — 4 tests directly call `executor._find_next_task()` and `_is_step_gate_satisfied()`; extract them
- `test_check_and_apply_methods.py` — tests internal WorkflowService gate contract rather than user behavior; borderline

### 2. Duplication Clusters

These clusters test essentially the same scenarios. One canonical test file per cluster should be kept; the rest should either be deleted or merged:

#### Cluster A: Full Workflow Lifecycle (5 files)
- `test_parity_linear.py` — canonical linear workflow, keep
- `test_workflow_execution.py` — near-identical lifecycle, overlaps heavily with parity_linear
- `test_workflow_service.py` — service-level lifecycle + error handling; keep the unique error tests
- `test_mock_agent_workflow.py` — adds MockAgent variant; could be one test in workflow_execution
- `test_api_full_lifecycle.py` — API-level lifecycle; keep (different layer)

**Recommendation:** Merge `test_workflow_execution.py` into `test_parity_linear.py`. Extract error-handling tests from `test_workflow_service.py` to unit tests. Fold `test_mock_agent_workflow.py` into one parameterized test.

#### Cluster B: Event Replay / Recovery (5 files)
- `test_parity_recovery.py` — DB-level persistence across restart
- `test_parity_replay.py` — event replay mechanism
- `test_event_recovery.py` — event-based state recovery
- `test_event_journal_replay.py` — journal replay + checkpointing
- `test_db_recovery_e2e.py` — full backup/restore E2E

These are the most expensive tests in the suite (each sets up full run state). They overlap heavily.

**Recommendation:** One recovery test file covering: (a) DB persistence across restart, (b) event replay restores state, (c) journal checkpoint resume. The E2E recovery test can cover the full scenario. Reduces from 5 files to 2.

#### Cluster C: MCP (3 files)
- `test_mcp_server.py` — MCP server tool registration and invocation
- `test_mcp_sse.py` — SSE transport endpoint availability
- `test_mcp_tools.py` — tool handler behavior

**Recommendation:** Consolidate into one `test_mcp.py`. The transport test is minimal (2 tests), tool behavior tests can coexist with lifecycle tests.

#### Cluster D: Agent Prompt/Override (2 files)
- `test_e2e_agent_overrides.py` — cascading agent resolution (task > step > routine)
- `test_prompt_agent_system_prompt.py` — system prompt injection at multiple cascade levels

These test the same cascading resolution logic at overlapping levels.

**Recommendation:** Merge into one `test_agent_overrides.py`.

#### Cluster E: Conflict/Merge (3 files)
- `test_conflict_back_merge.py` — clean and conflicting back-merges
- `test_conflict_resolve.py` — ours/theirs/manual resolution
- `test_review_merge_readiness.py` — merge readiness gates + accept

These are closely related and share fixture setup patterns.

**Recommendation:** Keep all three but extract shared fixtures to conftest.py to eliminate boilerplate.

#### Cluster F: Clarification vs Approval
- `test_api_clarifications.py` — clarification via API
- `test_api_human_approval.py` — approval gate via API + internal executor tests
- `test_api_approval.py` — stub (only checks endpoint existence, no real workflow)
- `test_approval_workflow.py` — service-layer approval/rejection
- `test_clarification_workflow.py` — service-layer clarification cycle

**Recommendation:** Delete `test_api_approval.py` (absorbed by `test_api_human_approval.py`). Move executor internals from `test_api_human_approval.py` to unit tests.

### 3. Timing-Dependent Tests (Flakiness Risk)

| File | Location | Issue |
|------|----------|-------|
| `test_api_websocket.py` | Lines 174, 194, 233, 264, 329, 369, 375, 383 | `asyncio.sleep()` to wait for throttle (0.1s) and batch windows (0.05-0.07s). **Justified** — testing timing-dependent features. But any system slowdown causes false failures. |
| `test_review_test_api.py` | Line 169 `_wait_for_completion` | Polling loop with `asyncio.sleep(0.2)`. Should use event/callback. |
| `test_review_merge_readiness.py` | Line 169 `_wait_for_completion` | Same as above (shared helper). |
| `test_user_managed_agent.py` | Lines 179, 284 | `asyncio.sleep(0.05)` to trigger signal propagation. Should use drain pattern. |
| `test_cli_agent.py` | Line 366 | `asyncio.sleep(0.1)` polling for subprocess startup. Should use process-ready signaling. |
| `test_agent_executor.py` | Line 366 | `asyncio.sleep(0.1)` in polling loop for task completion. |
| `test_openhands_agent.py` | Line 179 | Via `test_user_managed_agent` helper. |

**For WebSocket tests specifically:** The throttle/batch behavior tests are inherently timing-sensitive. Consider making the throttle and batch window durations injectable (already parameterized?) and use shorter intervals in tests, or use a `FakeClock` pattern.

### 4. Implementation Detail Tests

Tests that check *how* rather than *what* — brittle to refactoring:

| File | Test | Detail Being Checked |
|------|------|---------------------|
| `test_api_human_approval.py` | `test_executor_stops_at_human_approval_gate` | Calls `executor._find_next_task()` directly |
| `test_api_human_approval.py` | `test_executor_proceeds_after_gate_approved` | Calls `executor._is_step_gate_satisfied()` |
| `test_parity_recovery.py` | All tests | Directly inspects ORM object properties after reload |
| `test_parity_replay.py` | All tests | Direct run state manipulation, replay function internals |
| `test_event_recovery.py` | All tests | Event-to-state mapping verification, grade snapshot structure |
| `test_codex_server_callbacks.py` | Most tests | Calls `agent._route_tool_call()` internal method |
| `test_agent_monitor.py` | lock tests | Tests `lock_manager.is_locked()` internal state |
| `test_e2e_agent_overrides.py` | prompt composition | Tests `_SEPARATOR` constant presence |
| `test_prompt_agent_system_prompt.py` | separator tests | Tests `_SEPARATOR` constant presence |
| `test_mcp_sse.py` | handler tests | Tests `_SessionPerCallHandler` and `SubmitEventRegistry` internals |

---

## Prioritized Action Plan

### Priority 1: Move unit tests out of integration/ (Quick wins, ~15 min each)

These require no rewriting — just move the file and fix imports:

1. Move `test_event_store.py` → `tests/unit/test_event_store.py`
2. Move `test_signal_redelivery.py` → `tests/unit/test_signal_redelivery.py`
3. Move `test_clarification_repository.py` → `tests/unit/test_clarification_repository.py`
4. Move `test_database.py` → `tests/unit/test_database.py`
5. Move `test_repositories.py` → `tests/unit/test_repositories.py`
6. Move `test_agent_resolution.py` → `tests/unit/test_agent_resolution.py`
7. Move `test_executor_health_check.py` → `tests/unit/test_executor_health_check.py`
8. Move `test_branch_ops.py` → `tests/unit/test_branch_ops.py`

These files don't use the FastAPI app fixture — they should run with a simple in-memory DB or no DB at all. Moving them removes them from the integration run entirely.

Extract unit tests from mixed files:
- Extract `TestFindTaskConfig` and `TestResolveAutoVerifyConfig` from `test_auto_verify_workflow.py`
- Extract executor internals tests from `test_api_human_approval.py`

### Priority 2: Fix polling sleeps (Flakiness reduction)

Convert sleep-based polling to event/drain patterns:

1. `test_review_test_api.py` + `test_review_merge_readiness.py` — `_wait_for_completion` should use a mock or inject a callback rather than polling with `asyncio.sleep(0.2)`.
2. `test_user_managed_agent.py` — the `asyncio.sleep(0.05)` calls should use `drain_signals()`.
3. `test_agent_executor.py` — polling loop at line 366 should await an event rather than sleep.

For `test_api_websocket.py`: The timing tests are inherently harder to fix. Consider making the throttle/batch window durations configurable at app creation time, then using near-zero values in tests plus a `drain()` call.

### Priority 3: Delete/consolidate duplicates (Larger refactor)

1. **Delete `test_api_approval.py`** — it's a stub; `test_api_human_approval.py` and `test_approval_workflow.py` cover real behavior.

2. **Consolidate recovery cluster** — merge `test_parity_recovery.py` + `test_parity_replay.py` + `test_event_recovery.py` into a single `test_recovery.py` with ~5 representative scenarios instead of 15+ overlapping ones.

3. **Consolidate MCP** — merge `test_mcp_server.py` + `test_mcp_sse.py` + `test_mcp_tools.py` into `test_mcp.py`.

4. **Merge agent overrides** — merge `test_e2e_agent_overrides.py` + `test_prompt_agent_system_prompt.py` into one file.

5. **Merge workflow lifecycle** — merge `test_workflow_execution.py` into `test_parity_linear.py`, fold `test_mock_agent_workflow.py` into a single parameterized test.

### Priority 4: Extract shared fixtures to conftest.py

Multiple test files independently define:
- Git repo setup with worktree
- `shared_app` fixture with module scope
- `client_with_repo` pattern

Extracting these to `tests/integration/conftest.py` eliminates boilerplate and ensures consistent fixture scoping. Files that would benefit: all review/conflict tests, all worktree-dependent tests.

---

## Estimated Impact

| Action | Files affected | Estimated reduction |
|--------|---------------|---------------------|
| Move pure unit tests | ~8 files | Remove from integration run; run as unit tests |
| Delete/consolidate duplicates | ~12 files | ~25% fewer integration tests |
| Fix polling sleeps | ~5 files | Flakiness elimination + time savings |
| Extract conftest fixtures | ~8 files | Setup time reduction via shared module-scope fixtures |

**Conservative estimate:** 30-35% reduction in integration test count; 20-30% faster wall-clock time; near-zero timing-induced flakiness.

---

## Patterns to Avoid in New Tests

1. **Never use `asyncio.sleep()` for polling** — use the `drain()` helper or inject a completion callback
2. **Don't test internal methods** — if the behavior is only observable via private methods, either expose it through an API or test at the next level up
3. **One canonical lifecycle test per layer** — don't write a 5th test that goes "create run → start → build → verify → complete"; extend the existing canonical one
4. **Repository tests belong in unit tests** — any test that directly calls `.save()` / `.get()` on a repository with an in-memory DB is a unit test
5. **Avoid string matching on event type names** — use the event class or enum constant
6. **Don't share module-scoped DB across tests that mutate state** — creates hidden inter-test dependencies
