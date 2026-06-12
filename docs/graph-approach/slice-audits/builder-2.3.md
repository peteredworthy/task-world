# Slice 2.3 — Runner integration (BUILDER)

You are the BUILDER agent for slice 2.3 of the task-world execution-graph kernel (Phase 2). This is an L-size slice: the graph meets real agent runtimes.

## Ground truth (read these first, in order)

1. `docs/graph-approach/execution-graph-prd-plus.md` — §12.3 (agent dispatch as side effect, ScheduleTick), §13 (runtime recovery: reattach / agent_died / awaiting callback), §19 (lease & callback semantics: every callback carries lease identity — lease_id, generation, execution_id, base_snapshot_id; stale matrix), §14 (task projection formula — the e2e target state is `accepted`), §15.1–15.2 (worker/verifier lifecycle), §21 (roles/permissions), §27.5 (test boundaries: integration tests cover runner adapter contract; NO real LLM in tests)
2. The slice definition (sequencing deck): "2.3 Runner integration — One real builder/verifier cycle through an existing adapter (Claude SDK or CLI) behind graph callbacks; lease identity in callbacks; reattach-on-restart. Done when: End-to-end run on a real repo: build → boundary → verify → task projection accepted; server-restart mid-run recovers."
3. Existing graph runtime (slices 2.1/2.2): `src/orchestrator/graph_runtime/` — `GraphController.handle_command` (commands: `seed_compiled_events`, `schedule_tick`, `acknowledge_start`, `submit_callback`, `agent_died`…), `OutboxDispatcher` (+ `OutboxItem`, executor Protocol, at-least-once), `recovery.py` (RecoveryReport: redispatched / awaiting_start_ack / awaiting_callback), `seeding.py` (`seed_run`)
4. Pure kernel: `src/orchestrator/graph/` — `commands.py` (callback validation incl. provenance, output records, input binding), `projections.py` (`project_task_states`, §14 formula), `compiler.py`
5. Existing runner layer: `src/orchestrator/runners/` — `interface.py` (`AgentRunner` protocol: `execute(context, on_checklist_update, on_submit, …) -> ExecutionResult`, `cancel()`), `types.py` (`ExecutionContext`, `ExecutionResult`, callbacks), `agents/` (claude_cli, claude_sdk, codex, mock, user_managed), `agent_factory.py`. The established no-LLM e2e pattern: `MockAgent`/`MockBehavior` (`src/orchestrator/runners/agents/mock/agent.py`, used by `tests/integration/test_mock_agent_workflow.py`) — a real protocol implementation, configurable, NOT unittest.mock.

## Scope — what to build

### 1. Graph dispatch executor (`src/orchestrator/graph_runtime/dispatch.py` or similar)

The bridge from outbox to runner: an implementation of the 2.1 executor Protocol that, given an `agent_dispatch` OutboxItem (carrying lease_id, node_id, generation, execution_id, run_id from the `agent_dispatch_requested` payload):

- Builds an `ExecutionContext` for the node from graph facts: the routine snapshot record + task/node payloads in the projection (task context, requirements, worktree path / repo dir passed in at construction). Keep the mapping explicit and documented.
- Resolves the `AgentRunner` via an injected factory (Protocol — production wiring can use `agent_factory`; tests inject one returning MockAgent). Do NOT import FastAPI or the workflow service.
- Sends `acknowledge_start` through the `GraphController` when the agent execution begins (this is the §12.3 start acknowledgement).
- Translates the runner's `on_submit` result into a graph `submit_callback` command through the controller, carrying FULL lease identity: `lease_id`, `lease_generation`, `execution_id`, `base_snapshot_id`, `observed_graph_position`, `idempotency_key`, `payload_hash`, plus `output_records` (for a worker: an ImplementationCandidate-style record on the worker's output port; for a verifier: a verification result — see point 2). The kernel validates; the dispatcher must NOT pre-judge validity.
- On runner exception/death: sends `agent_died` through the controller (lease revoked, retry per kernel policy).
- Tracks running executions in-process (execution_id → handle) so reattach/recovery can interrogate liveness. Expose `is_running(execution_id)`.

### 2. Verifier cycle → task projection `accepted`

The §14 formula needs an accepted verifier PASS for the latest candidate. Wire the verifier path: when a verifier node's callback reports its verdict, the kernel must end up with the verification fact (`verification_passed`/`verification_failed` keyed by `candidate_id`) that `project_task_states` consumes. Check what `apply_command`'s callback path supports today — if verifier callbacks currently only produce generic output records, extend the PURE kernel minimally so a verifier callback's output record of a verification kind (e.g. `record_kind: "verification"`, payload carrying `candidate_id` + verdict) yields the verification event. Provenance rules from 2.2 still apply (verifier can only report as itself; candidate_id must reference a real candidate bound to its input). Negative path: verification_failed → task projection `needs_revision`.

### 3. Reattach-on-restart + recovery wiring

Extend `recover()` usage: on startup, for each active lease in `awaiting_callback`/`awaiting_start_ack`, consult the dispatch executor's liveness (`is_running`) — process alive → reattach (keep waiting; for MockAgent simulate a re-attachable execution), process gone → send `agent_died` through the controller (kernel revokes lease, reschedules). This implements §13 rows "active lease with known managed process" and "active lease with missing process". Keep it a small, testable orchestration function (e.g. `reconcile_runtime(controller, dispatcher, report)`), not buried in app startup.

### 4. The e2e drill (the done-when)

`tests/integration/test_graph_runner_e2e.py` — real tmp git repo (init a repo in tmp_path with a file or two; agents in this slice don't need to touch files yet — file-state is slice 2.4 — but the run executes against the real repo dir), real tmp-file SQLite, MockAgent-style runners (hand-written/configured, no unittest.mock, no monkeypatching):

1. Compile a routine with one task that has a worker AND a verifier (rubric) — e.g. a 1-step routine built in-test or a fixture YAML under tests/fixtures.
2. `seed_run` → start run → `schedule_tick` → outbox dispatch runs the builder agent → `acknowledge_start` → agent submits → worker callback accepted with candidate output record → boundary (node completed, candidate bound to verifier input).
3. Next `schedule_tick` leases the verifier → verifier agent runs → verification-pass callback → task projection for the task region == `accepted` (assert via `project_task_states` over events read back from SQLite).
4. Negative variant: verifier fails → `needs_revision`.
5. RESTART MID-RUN: crash after builder dispatch but before its callback (executor records the pending execution, then the test discards controller/dispatcher objects — "server restart"). Build fresh controller/dispatcher/recovery over the same DB file:
   - Variant A (reattach): dispatcher reports execution still running → recovery keeps the lease; the agent then completes; run proceeds to accepted.
   - Variant B (dead): dispatcher reports execution gone → recovery sends `agent_died`; kernel revokes + reschedules; re-dispatched agent completes; run proceeds to accepted.
6. Lease identity enforcement: a callback missing/incorrect lease generation is rejected stale (kernel already does this — assert it through the full stack once).

### 5. Production wiring (thin)

Factory function assembling controller + dispatcher + dispatch executor + recovery for the real app (real `agent_factory`), placed in `graph_runtime` with no FastAPI import. Actual HTTP/API exposure is slice 2.6 — do NOT touch `src/orchestrator/api/`.

## Done when (all must hold)

1. E2e drill passes: build → boundary → verify → task projection `accepted` on a real tmp repo through real adapters (protocol-level, MockAgent), all state via graph events in SQLite.
2. Restart-mid-run recovers in BOTH variants (reattach; agent_died + re-dispatch) and still reaches `accepted`.
3. Callbacks carry full lease identity end-to-end; stale-generation callback rejected through the full stack.
4. Verifier fail → `needs_revision` (negative §14 path).
5. Kernel purity preserved (`src/orchestrator/graph/` no IO imports); kernel suite <5s; `graph_runtime` imports no FastAPI/workflow-service.
6. Fresh green: `uv run pytest tests/unit -q`, `uv run pytest tests/integration -q`, `uv run ruff check src tests`, `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime`.

## Hard constraints

- NO mocks, NO monkeypatching in tests (MockAgent/hand-written protocol fakes injected via constructor are the established pattern and are fine). No real LLM calls anywhere in tests.
- Real SQLite tmp files, real git repos in tmp dirs only. NEVER touch the main `orchestrator.db`, never run the server, no git mutation of THIS repo (read-only git on the main repo fine; full git freedom inside tmp-dir test repos).
- Touch ONLY: `src/orchestrator/graph_runtime/**`, `src/orchestrator/graph/**` (minimal pure extensions for the verification record path), `src/orchestrator/runners/__init__.py` (export only, if needed), `tests/integration/test_graph_runner_e2e.py` (new), `tests/unit/test_graph_commands.py` / `test_graph_projections.py` (verification path units), `tests/fixtures/graph/**` + COVERAGE.md if fixtures added. Nothing else.
- If the verifier-verdict kernel extension grows beyond ~150 lines of kernel change, stop and write why in your summary instead of bloating the kernel.

When done, write a summary: dispatch mapping decisions, verifier-verdict design, reattach mechanics, e2e drill flow, fresh test output.
