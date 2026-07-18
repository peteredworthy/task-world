# Dynamic Graph Backlog Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the confirmed post-W5.5 graph defects, consolidate duplicated graph policy safely, complete W8, and remove the broken Claude SDK runner while preserving historical readback.

**Architecture:** Keep the typed event-sourced graph kernel authoritative. Add real-store and cross-surface regressions before replacing mirrors or moving pure policy; effectful driver/runtime guards remain in place. Remove Claude SDK behavior completely, map persisted relational values to a non-selectable `retired` runner, and normalize immutable historical payloads only at deserialization boundaries.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, SQLAlchemy/Alembic, SQLite, Click/httpx, React 19, TypeScript, TanStack Query, Vitest, pytest/xdist, Ruff, Pyright, uv.

## Global Constraints

- Work only in `/Users/peter/code/task-world/worktrees/backlog-closeout` on `codex/backlog-closeout`, based on `60ca04f96` or newer.
- Never modify `orchestrator.db` or `.orchestrator/state/history.jsonl`; migration tests use temporary databases.
- Use `uv run` for every Python command and `uv` for dependency/lock operations.
- No mocks, monkeypatching, global state, or direct external imports from graph submodules.
- Add a failing test before each behavior fix and record the RED command/output in the relevant durable document.
- Preserve event order, lease semantics, lifecycle semantics, contamination checks, polling, retries, and all effectful incident guards.
- Event-triggered graph driving, wholesale legacy retirement, and Claude SDK repair are out of scope.
- After each original closeout task, a fresh verifier with no builder context must run the exact four-command gate and its evidence must be committed.
- Do not merge to main; leave the branch and worktree for review.

## File Map

- `src/orchestrator/graph/projections.py`: canonical scheduler views and pure graph outcome policy.
- `src/orchestrator/graph/models.py`: typed projection fields, including projected node retry limits.
- `src/orchestrator/graph/payload_registry.py`: generated retained fields for compact/read-model paths.
- `src/orchestrator/graph/__init__.py`: public graph surface, pruned to actual repository consumers.
- `src/orchestrator/graph_runtime/store.py`: materialized read-model persistence that delegates to canonical projections.
- `src/orchestrator/graph_runtime/controller.py`: projection rebuild delegation.
- `src/orchestrator/workflow/graph_driver.py`: effectful graph orchestration only after pure policy relocation.
- `src/orchestrator/api/routers/graph.py`: typed graph decision endpoint.
- `src/orchestrator/graph/_commands.py`: target-kind validation for approval decisions.
- `ui/src/components/GraphDecisionModal.tsx`: full human-gate decision modal.
- `ui/src/components/GraphPanel.tsx`: pending-gate action entry point.
- `ui/src/api/client.ts`, `ui/src/hooks/useApi.ts`, `ui/src/types/runs.ts`: graph decision client contract.
- `src/orchestrator/cli/approve.py`: graph-aware approval routing while preserving the legacy path.
- `src/orchestrator/runners/agents/claude_cli/agent.py`: Codex `exec --model` argv construction.
- `src/orchestrator/config/enums.py`: readable versus selectable runner types.
- `src/orchestrator/runners/**`, `src/orchestrator/api/**`, `scripts/worker.py`: Claude SDK removal and retired-runner enforcement.
- `src/orchestrator/db/migrations/versions/zg1h2i3j4k5l_retire_claude_sdk_runner.py`: relational data migration.
- `src/orchestrator/state/session.py`, `src/orchestrator/workflow/events/__init__.py`: read-time legacy-value normalization.
- `docs/dynamic-graph/guard-retirement-ledger.md`: incident guard and retirement conditions.
- `docs/dynamic-graph/claude-sdk-runner-removal-decision.md`: runner removal decision.

---

### Task 1: Record Fresh-Main Triage

**Files:**
- Modify: `docs/dynamic-graph/status.md`
- Modify: `docs/dynamic-graph/dynamic-graph-implementation-review.html`
- Modify: `docs/dynamic-graph/incident-2026-07-04-w2-driver-crash-w3-final-check-strand.md`
- Modify: `research/recommendations/01-close-known-safety-gaps.md`

**Interfaces:**
- Consumes: fresh-main source evidence at base `60ca04f96`.
- Produces: four explicit `OPEN` findings and implementation evidence pointers for later tasks.

- [ ] **Step 1: Add the triage table to the durable status**

Add a dated section with this exact classification and evidence shape:

```markdown
## Backlog Closeout Triage — 2026-07-17

| Finding | Status | Fresh-main evidence |
| --- | --- | --- |
| Scheduler-view snapshot drift | OPEN | `graph_runtime/store.py::_scheduler_view_from_projection` duplicates canonical scheduler policy and does not exclude ready `max_grants_reached` nodes. |
| Graph human-gate approval path | OPEN | `GraphPanel` only renders pending gates; `runs approve` only posts to the legacy step endpoint. |
| Codex cli_subprocess model routing | OPEN | `CLIAgent` constructs `codex --model MODEL exec ...` instead of `codex exec --model MODEL ...`. |
| R01(a) July 4 supersession replay | OPEN | Focused supersession tests exist, but no real-store incident-shape replay jointly proves task acceptance, projection parity, empty final blockers, and completion. |
```

Append equivalent status notes to the review, incident, and R01 without deleting historical diagnosis.

- [ ] **Step 2: Verify the documentation diff**

Run:

```bash
git diff --check
git diff -- docs/dynamic-graph research/recommendations/01-close-known-safety-gaps.md
```

Expected: no whitespace errors; all four findings are explicitly `OPEN` and cite current symbols.

- [ ] **Step 3: Commit Task 0 triage**

```bash
git add docs/dynamic-graph/status.md \
  docs/dynamic-graph/dynamic-graph-implementation-review.html \
  docs/dynamic-graph/incident-2026-07-04-w2-driver-crash-w3-final-check-strand.md \
  research/recommendations/01-close-known-safety-gaps.md
git commit -m "docs: triage dynamic graph closeout findings"
```

- [ ] **Step 4: Run the fresh Task 0 verifier**

Dispatch a fresh verifier with only the commit SHA and these commands:

```bash
uv run pytest tests/ -q -n auto --dist worksteal
uv run ruff check .
uv run pyright
git diff --check
```

Expected baseline: `4824 passed, 3 skipped`, Ruff clean, Pyright `0 errors`, diff check clean. Record the actual count and verifier SHA in `docs/dynamic-graph/status.md`, then commit:

```bash
git add docs/dynamic-graph/status.md
git commit -m "docs: record Task 0 verifier evidence"
```

---

### Task 2: Pin The July 4 Supersession Incident

**Files:**
- Modify: `tests/integration/test_graph_read_models.py`
- Modify only if RED exposes residue: `src/orchestrator/graph/projections.py`
- Modify: `docs/dynamic-graph/incident-2026-07-04-w2-driver-crash-w3-final-check-strand.md`
- Modify: `research/recommendations/01-close-known-safety-gaps.md`
- Modify: `docs/dynamic-graph/p1-resolution-ledger.md`

**Interfaces:**
- Consumes: `GraphEventStore`, `project_task_states`, `project_final_invariant_blockers`, `project_run_state`, projection checkpoints.
- Produces: `test_july_4_incident_replay_preserves_supersession_and_completion_parity`.

- [ ] **Step 1: Add the documented incident event fixture**

In `test_graph_read_models.py`, add `_july_4_supersession_incident_events(run_id)`. Build this ordered stream using the file's real `_event`, `_candidate_event`, `_verification_payload`, and `_file_state_event` helpers:

```python
def _july_4_supersession_incident_events(run_id: str) -> list[EventEnvelope]:
    return [
        _event("incident-active", run_id, "run_lifecycle_changed", {"to_state": "active"}),
        _event("incident-origin-worker", run_id, "node_created", {
            "node_id": "worker-origin", "kind": "worker", "role": "builder",
            "state": "completed", "task_region_id": "origin",
        }),
        _candidate_event("incident-origin-candidate", run_id, "origin", "candidate-origin"),
        _event("incident-origin-verifier", run_id, "node_created", {
            "node_id": "verifier-origin", "kind": "verifier", "role": "verifier",
            "state": "failed", "task_region_id": "origin",
        }),
        _event("incident-origin-failed", run_id, "verification_failed", {
            **_verification_payload("candidate-origin", "failed"),
            "node_id": "verifier-origin", "verifier_node_id": "verifier-origin",
        }),
        _event("incident-gap-planner", run_id, "node_created", {
            "node_id": "gap-planner-recovery", "kind": "gap_planner",
            "role": "gap_planner", "state": "completed",
        }),
        _event("incident-gap-classified", run_id, "output_record_accepted", {
            "record_id": "classified-gap-recovery", "record_kind": "output",
            "record_type": "classified_gap", "producer_node_id": "gap-planner-recovery",
            "port": "classified_gap", "schema": "GapClassification",
            "value": {"classification": "corrective_work_required"},
        }),
        _event("incident-corrective-worker", run_id, "node_created", {
            "node_id": "worker-corrective", "kind": "worker", "role": "fixer",
            "state": "completed", "task_region_id": "corrective",
        }),
        _event("incident-corrective-candidate", run_id, "output_record_accepted", {
            "task_region_id": "corrective", "candidate_id": "candidate-corrective",
            "attempt_number": 1, "producer_node_id": "worker-corrective",
            "record_id": "candidate-corrective", "record_kind": "output",
            "record_type": "candidate", "port": "candidate",
            "schema": "ImplementationCandidate", "supersedes_task_region_id": "origin",
            "value": {"summary": "repair origin candidate"},
        }),
        _event("incident-corrective-verifier", run_id, "node_created", {
            "node_id": "verifier-corrective", "kind": "verifier", "role": "verifier",
            "state": "completed", "task_region_id": "corrective",
        }),
        _event("incident-corrective-passed", run_id, "verification_passed", {
            **_verification_payload("candidate-corrective", "passed"),
            "node_id": "verifier-corrective", "verifier_node_id": "verifier-corrective",
        }),
        _file_state_event("incident-corrective-file-state", run_id, "corrective", "candidate-corrective"),
        _event("incident-final-gate", run_id, "node_created", {
            "node_id": "final-gate-incident", "kind": "final_gate",
            "role": "final_gate", "state": "completed",
        }),
        _event("incident-completion-decision", run_id, "output_record_accepted", {
            "record_id": "completion-decision-incident", "record_kind": "output",
            "record_type": "completion_decision", "producer_node_id": "final-gate-incident",
            "port": "completion_decision", "schema": "CompletionDecision",
            "value": {"status": "passed", "blockers": []},
            "provenance": {"source": "final_gate_evaluated"},
        }),
        _event("incident-completed", run_id, "run_lifecycle_changed", {
            "from_state": "active", "to_state": "completed",
        }),
    ]
```

- [ ] **Step 2: Add the real-store replay assertion**

Append through `GraphEventStore`, read full and compact events plus the incremental checkpoint, delete read models, rebuild, and assert this contract on all four paths:

```python
expected = {
    "task_states": {"corrective": "accepted", "origin": "accepted"},
    "final_gate_state": "completed",
    "final_blockers": [],
    "run_state": "completed",
}
```

Use a typed `_incident_projection_outcome(events, projection=None)` helper that calls only public `orchestrator.graph` projectors.

- [ ] **Step 3: Run the incident regression**

```bash
uv run pytest tests/integration/test_graph_read_models.py::test_july_4_incident_replay_preserves_supersession_and_completion_parity -q
```

Expected: GREEN is acceptable because the implementation fix already exists. If it fails with `origin: needs_revision`, change only `_apply_accepted_region_supersessions`; if compact alone fails, correct retained typed payload fields instead of weakening blockers.

- [ ] **Step 4: Record closure without overstating replay fidelity**

Document that this is a faithful minimal reconstruction through real SQLite/store, not a byte-identical production export and not a journal replay. Mark R01(a) closed and cite all four projection paths.

- [ ] **Step 5: Commit the incident pin**

```bash
git add tests/integration/test_graph_read_models.py \
  docs/dynamic-graph/incident-2026-07-04-w2-driver-crash-w3-final-check-strand.md \
  docs/dynamic-graph/p1-resolution-ledger.md \
  research/recommendations/01-close-known-safety-gaps.md
git commit -m "test: replay July 4 graph supersession incident"
```

---

### Task 3: Canonicalize Snapshot Scheduler And Lease Views

**Files:**
- Modify: `tests/integration/test_graph_event_store.py`
- Modify: `tests/unit/test_graph_scheduler_view.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph_runtime/store.py`

**Interfaces:**
- Consumes: `GraphProjection.last_deferred_reasons`, `project_scheduler_view`, `project_lease_view`.
- Produces: canonical event and projection fast paths with identical scheduler/lease results.

- [ ] **Step 1: Write the failing real-store parity test**

Add `test_incremental_scheduler_snapshot_matches_canonical_rebuild_for_max_grants`. Seed ready `worker-maxed` deferred for `max_grants_reached`, planned `worker-input` deferred for missing input, and ready `worker-resource` deferred for resource conflict. Assert incremental and rebuilt snapshots both equal:

```python
{
    "ready": ["worker-maxed", "worker-resource"],
    "blocked": [{"node_id": "worker-input", "reason": "missing_required_input:candidate"}],
    "waiting_resources": [
        {"node_id": "worker-resource", "reason": "resource_conflict:write:write"}
    ],
    "waiting_gates": [],
}
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/integration/test_graph_event_store.py::test_incremental_scheduler_snapshot_matches_canonical_rebuild_for_max_grants -q
```

Expected: incremental `blocked` incorrectly includes `worker-maxed`.

- [ ] **Step 3: Make the canonical projector own retained deferrals**

In `project_scheduler_view`, fold events once and read reasons from the projection:

```python
proj = projection if projection is not None else _project(events)
node_states = project_node_states([], projection=proj)
ready = sorted(project_ready_nodes([], projection=proj))
latest_deferrals = proj["last_deferred_reasons"]
```

Keep existing bucket classification and `max_grants_reached` exclusion. Delete `_latest_node_deferrals` after confirming no consumers remain.

- [ ] **Step 4: Delete store mirrors**

In `_assign_projection_snapshot`, always assign:

```python
row.scheduler = dict(project_scheduler_view([], projection=projection))
row.lease_view = dict(project_lease_view([], projection=projection))
```

Delete `_scheduler_view_from_projection` and `_lease_view_from_projection`. Update the unit test to compare event replay with `projection=` fast paths rather than importing a private store helper.

- [ ] **Step 5: Run GREEN and static checks**

```bash
uv run pytest tests/unit/test_graph_scheduler_view.py tests/integration/test_graph_event_store.py -q
uv run ruff check src/orchestrator/graph/projections.py src/orchestrator/graph_runtime/store.py tests/unit/test_graph_scheduler_view.py tests/integration/test_graph_event_store.py
uv run pyright
git diff --check
```

Expected: all focused tests pass, Ruff clean, Pyright `0 errors`.

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/graph/projections.py src/orchestrator/graph_runtime/store.py \
  tests/unit/test_graph_scheduler_view.py tests/integration/test_graph_event_store.py
git commit -m "fix: canonicalize graph snapshot scheduler views"
```

---

### Task 4: Fix Codex CLI Model Routing

**Files:**
- Modify: `tests/unit/test_cli_agent.py`
- Modify: `src/orchestrator/runners/agents/claude_cli/agent.py`

**Interfaces:**
- Consumes: `CLIAgent(command, args, model)`.
- Produces: Codex argv `codex exec --model MODEL ...`; non-Codex ordering unchanged.

- [ ] **Step 1: Add exact argv tests**

Add tests for factory defaults, an absolute Codex path with custom args, and unchanged Claude ordering:

```python
assert [agent._command, *agent._args] == [
    "/usr/local/bin/codex", "exec", "--model", "gpt-5.2-codex",
    "--dangerously-bypass-approvals-and-sandbox", "Do the thing",
]
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/unit/test_cli_agent.py -q
```

Expected: Codex tests show `--model` before `exec`; existing non-Codex tests pass.

- [ ] **Step 3: Insert the model after Codex exec**

Use command basename and preserve all custom args:

```python
base_args = list(args or [])
if model is not None:
    if Path(command).name == "codex" and "exec" in base_args:
        exec_index = base_args.index("exec") + 1
        base_args = [
            *base_args[:exec_index], "--model", model, *base_args[exec_index:]
        ]
    else:
        base_args = ["--model", model, *base_args]
```

- [ ] **Step 4: Run GREEN and commit**

```bash
uv run pytest tests/unit/test_cli_agent.py -q
uv run ruff check src/orchestrator/runners/agents/claude_cli/agent.py tests/unit/test_cli_agent.py
uv run pyright
git add src/orchestrator/runners/agents/claude_cli/agent.py tests/unit/test_cli_agent.py
git commit -m "fix: route Codex CLI model after exec"
```

---

### Task 5: Add Graph Human-Gate Approval To Kernel And API

**Files:**
- Modify: `tests/unit/test_graph_commands.py`
- Modify: `tests/integration/test_graph_decisions_api.py`
- Modify: `src/orchestrator/graph/_commands.py`

**Interfaces:**
- Consumes: `RecordGraphDecisionRequest`, `record_decision` graph command.
- Produces: approval decisions accepted only for pending `gate`/`human_gate` targets and durable successor release.

- [ ] **Step 1: Add target-kind RED test**

Seed an active graph with a ready worker and submit an approval. Assert a single rejection:

```python
assert [event.event_type for event in output] == ["command_rejected"]
assert output[0].payload == {
    "command_type": "record_decision",
    "reason": "approval decisions require gate or human_gate target",
}
```

- [ ] **Step 2: Add API product-path test**

Seed an active human gate, decision request, active lease, planned successor, and gate-to-successor decision edge. POST:

```python
{
    "decision_type": "approval",
    "node_id": "human-gate-1",
    "decision": "approved",
    "decider": {"kind": "human", "id": "alice", "role": "operator"},
    "reason": "Reviewed output.",
}
```

Assert `approval_decision_recorded`, decision readback, gate removal from pending decisions, released lease, and ready successor. Add a non-gate POST that returns 409 without advancing graph state.

- [ ] **Step 3: Run RED**

```bash
uv run pytest tests/unit/test_graph_commands.py::test_record_decision_rejects_approval_for_non_gate_target \
  tests/integration/test_graph_decisions_api.py::test_record_approval_decision_is_durable_and_releases_waiting_successor -q
```

Expected: worker-target approval is incorrectly accepted; valid gate path may already pass.

- [ ] **Step 4: Add symmetric approval validation**

In `_apply_record_decision`, before event creation:

```python
if decision_type == "approval" and node_kind not in {"gate", "human_gate"}:
    return [
        _command_rejected(
            make_event,
            "record_decision",
            "approval decisions require gate or human_gate target",
        )
    ]
```

Retain existing terminal/non-pending rejection and API Pydantic value validation.

- [ ] **Step 5: Run GREEN and commit**

```bash
uv run pytest tests/unit/test_graph_commands.py tests/integration/test_graph_decisions_api.py -q
uv run ruff check src/orchestrator/graph/_commands.py tests/unit/test_graph_commands.py tests/integration/test_graph_decisions_api.py
uv run pyright
git add src/orchestrator/graph/_commands.py tests/unit/test_graph_commands.py tests/integration/test_graph_decisions_api.py
git commit -m "fix: validate graph human gate decisions"
```

---

### Task 6: Add Graph Human-Gate Approval To UI

**Files:**
- Create: `ui/src/components/GraphDecisionModal.tsx`
- Create: `ui/src/components/__tests__/GraphPanel.decisions.test.tsx`
- Modify: `ui/src/components/GraphPanel.tsx`
- Modify: `ui/src/types/runs.ts`
- Modify: `ui/src/api/client.ts`
- Modify: `ui/src/hooks/useApi.ts`

**Interfaces:**
- Consumes: `GET/POST /api/runs/{run_id}/graph/decisions`.
- Produces: `useRecordGraphDecision(runId)` and a full approve/reject modal.

- [ ] **Step 1: Add UI contract types and failing component tests**

Define `GraphApprovalDecision`, `RecordGraphDecisionRequest`, and response types. Test that the compact row has only `Review decision`, opening it creates a `role="dialog"` with prompt, consequence, optional note, Cancel, Approve, Reject, and authority requests have no approval action.

- [ ] **Step 2: Run RED**

```bash
npm --prefix ui test -- src/components/__tests__/GraphPanel.decisions.test.tsx
```

Expected: no review action, modal, mutation, or complete pending-gate fields exist.

- [ ] **Step 3: Add the API client and mutation**

Add:

```typescript
recordRunGraphDecision(runId, data) {
  return fetchApi('/api/runs/' + runId + '/graph/decisions', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}
```

`useRecordGraphDecision` invalidates graph decisions, projection, scheduler, events, node detail, and run queries on success.

- [ ] **Step 4: Implement the modal and GraphPanel entry point**

Follow `detail/ApprovalModal.tsx` for focus trap, Escape, body lock, backdrop, disabled pending state, and error rendering. The compact row contains one `Review decision` button; approve/reject/cancel controls exist only in the modal footer. Submit exact typed actor/reason payloads and omit blank reasons.

- [ ] **Step 5: Run GREEN and commit**

```bash
npm --prefix ui test -- src/components/__tests__/GraphPanel.decisions.test.tsx
npm --prefix ui run typecheck
npm --prefix ui run lint
git add ui/src/components/GraphDecisionModal.tsx \
  ui/src/components/__tests__/GraphPanel.decisions.test.tsx \
  ui/src/components/GraphPanel.tsx ui/src/types/runs.ts ui/src/api/client.ts ui/src/hooks/useApi.ts
git commit -m "feat: approve graph human gates in UI"
```

---

### Task 7: Route CLI Approval By Execution Mode

**Files:**
- Modify: `src/orchestrator/cli/approve.py`
- Create: `tests/integration/test_cli_approve.py`

**Interfaces:**
- Consumes: run `execution_mode`, graph decision view, legacy pending actions.
- Produces: `_graph_approval_payload` and graph-aware `runs approve` routing.

- [ ] **Step 1: Add payload and live-route RED tests**

Assert the pure payload exactly matches:

```python
{
    "decision_type": "approval",
    "node_id": "gate-1",
    "decision": "rejected",
    "decider": {"kind": "human", "id": "alice", "role": "operator"},
    "reason": "Needs correction.",
}
```

Using a real test app/httpx transport, prove graph mode reads graph decisions and posts approval/rejection while legacy mode still posts unchanged step approval data.

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/integration/test_cli_approve.py -q -n 0
```

Expected: graph run reports no legacy pending actions and records no graph decision.

- [ ] **Step 3: Extract graph and legacy handlers**

At command start, GET `/api/runs/{run_id}`. For `execution_mode == "graph"`, GET `/graph/decisions`, process pending human gates, and POST typed decisions. Otherwise execute the existing pending-actions/clarification/step-approval flow unchanged.

- [ ] **Step 4: Run GREEN and commit**

```bash
uv run pytest tests/integration/test_cli_approve.py tests/integration/test_cli.py -q -n 0
uv run ruff check src/orchestrator/cli/approve.py tests/integration/test_cli_approve.py
uv run pyright
git add src/orchestrator/cli/approve.py tests/integration/test_cli_approve.py
git commit -m "feat: approve graph human gates from CLI"
```

---

### Task 8: Verify And Document All Confirmed-Open Regressions

**Files:**
- Modify: `docs/dynamic-graph/status.md`
- Modify: `docs/dynamic-graph/dynamic-graph-implementation-review.html`

**Interfaces:**
- Consumes: Tasks 2–7 commits.
- Produces: Task 3 regression evidence with RED/GREEN commands and SHAs.

- [ ] **Step 1: Run focused cross-surface checks**

```bash
uv run pytest tests/integration/test_graph_read_models.py \
  tests/unit/test_graph_scheduler_view.py tests/integration/test_graph_event_store.py \
  tests/unit/test_cli_agent.py tests/unit/test_graph_commands.py \
  tests/integration/test_graph_decisions_api.py tests/integration/test_cli_approve.py -q -n 0
npm --prefix ui test -- src/components/__tests__/GraphPanel.decisions.test.tsx
```

- [ ] **Step 2: Commit source evidence notes**

Record each RED observation, GREEN command/count, and source commit SHA, then:

```bash
git add docs/dynamic-graph/status.md docs/dynamic-graph/dynamic-graph-implementation-review.html
git commit -m "docs: close confirmed graph regressions"
```

- [ ] **Step 3: Dispatch the fresh regression-task verifier**

```bash
uv run pytest tests/ -q -n auto --dist worksteal
uv run ruff check .
uv run pyright
git diff --check
```

Record exact output and verifier SHA in status, commit as `docs: record regression verifier evidence`.

---

### Task 9: Consolidate Remaining Kernel Mirrors

**Files:**
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/payload_registry.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph_runtime/store.py`
- Modify: `src/orchestrator/graph_runtime/controller.py`
- Modify: `tests/unit/test_graph_projections.py`
- Modify: `tests/unit/test_graph_payload_field_allowlists.py`
- Modify: `tests/integration/test_graph_node_detail_read_models.py`

**Interfaces:**
- Consumes: typed payload specs and `build_projection`.
- Produces: projected `max_attempts`, canonical projection folds, guarded lease-summary mirror, and `_clone_projection` field coverage.

- [ ] **Step 1: Add parity tests before changing mirrors**

Add tests proving first `node_created.max_attempts` wins, bool is not accepted as an integer retry limit, incremental rich lease summaries equal rebuild plus `project_leases`, and cloned projection keys equal `initial_projection()` keys without nested aliasing.

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/unit/test_graph_projections.py \
  tests/unit/test_graph_payload_field_allowlists.py \
  tests/integration/test_graph_node_detail_read_models.py -q
```

Expected: `NodeCreationProjection` lacks `max_attempts`; clone helper is absent. Lease parity should characterize current behavior.

- [ ] **Step 3: Add typed retry policy and bump checkpoint schema**

Add `max_attempts: int | None` to `NodeCreationProjection`, retain it in generated `node_created` payload specs, and increment `PROJECTION_SCHEMA_VERSION`. Preserve first-write-wins reduction.

- [ ] **Step 4: Delegate projection folds and extract the clone**

Make controller/store rebuild helpers call public `build_projection`. Extract the existing `reduce_event` copy block verbatim into `_clone_projection(state)`; do not change copy depth or normalization while extracting.

- [ ] **Step 5: Keep `_lease_from_grant` only behind parity evidence**

Do not redesign node-detail reduction if the new incremental/rebuild/canonical test passes. Add a ledger disposition of `load-bearing mirror with parity guard`; extract a shared constructor only if the test exposes drift.

- [ ] **Step 6: Run GREEN and commit**

```bash
uv run pytest tests/unit/test_graph_projections.py \
  tests/unit/test_graph_payload_field_allowlists.py \
  tests/integration/test_graph_node_detail_read_models.py \
  tests/integration/test_graph_event_store.py -q
uv run ruff check .
uv run pyright
git diff --check
git add src/orchestrator/graph src/orchestrator/graph_runtime/controller.py \
  src/orchestrator/graph_runtime/store.py tests/unit/test_graph_projections.py \
  tests/unit/test_graph_payload_field_allowlists.py \
  tests/integration/test_graph_node_detail_read_models.py
git commit -m "refactor: consolidate graph projection mirrors"
```

---

### Task 10: Move Pure Driver Policy Into The Graph Kernel

**Files:**
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `src/orchestrator/workflow/graph_driver.py`
- Modify: `src/orchestrator/workflow/__init__.py`
- Modify: `tests/unit/test_graph_driver_logic.py`
- Modify: `tests/unit/test_graph_projections.py`
- Modify: `tests/integration/test_graph_run_driver.py`

**Interfaces:**
- Produces: `project_graph_projection_snapshot`, `project_graph_outcome`, `project_graph_completion_eligible`, `project_graph_blocked_reason`, `project_active_lease_wait_plan`, `project_node_max_attempts`; graph-owned `GraphRunOutcome`, `GraphProjectionSnapshot`, `ActiveLeaseWaitPlan`.
- Preserves: `orchestrator.workflow.GraphRunOutcome` re-export.

- [ ] **Step 1: Split existing outcome tests into kernel-policy cases**

Pin completed, blocked, failed, ready-node explanation, active leases, failed node, missing source, environment failure, nonaccepted tasks, nearest lease deadline, missing execution IDs, and no-expiry waits using public graph calls.

- [ ] **Step 2: Run baseline policy tests**

```bash
uv run pytest tests/unit/test_graph_driver_logic.py tests/unit/test_graph_projections.py -q
```

Expected: existing driver behavior passes before relocation.

- [ ] **Step 3: Move only pure types/functions**

Move projection snapshot building, outcome/blocker classification, lease wait planning, and retry-limit projection to `graph/projections.py`. Replace driver bodies with imports/calls. Leave contamination, I/O, retries, outbox waits, lifecycle transitions, polling, leases, crash/reopen bridges, and recovery bounds in `graph_driver.py`.

- [ ] **Step 4: Run behavior-parity suites**

```bash
uv run pytest tests/unit/test_graph_driver_logic.py tests/unit/test_graph_projections.py \
  tests/integration/test_graph_run_driver.py tests/integration/test_graph_dynamic_e2e.py \
  tests/integration/test_graph_default_carrier.py tests/integration/test_graph_startup_recovery.py \
  tests/integration/test_graph_runner_e2e.py -q
uv run pyright
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/graph/projections.py src/orchestrator/graph/__init__.py \
  src/orchestrator/workflow/graph_driver.py src/orchestrator/workflow/__init__.py \
  tests/unit/test_graph_driver_logic.py tests/unit/test_graph_projections.py \
  tests/integration/test_graph_run_driver.py
git commit -m "refactor: move graph outcome policy into kernel"
```

---

### Task 11: Prune Graph Exports And Create Guard Ledger

**Files:**
- Create: `tests/unit/test_graph_public_exports.py`
- Create: `docs/dynamic-graph/guard-retirement-ledger.md`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `docs/dynamic-graph/w8-drive-loop-cleanup-spec.md`
- Modify: `docs/dynamic-graph/status.md`
- Modify: `docs/dynamic-graph/dynamic-graph-implementation-review.html`

**Interfaces:**
- Consumes: AST imports in `src` and `tests`.
- Produces: exact public export guard and durable retirement conditions.

- [ ] **Step 1: Add the AST export guard**

Collect `from orchestrator.graph import Name` and `import orchestrator.graph as alias; alias.Name` outside `graph/__init__.py`. Assert consumers equal `set(orchestrator.graph.__all__)`; permit no unannotated compatibility set.

- [ ] **Step 2: Run RED and prune current zero-consumer exports**

```bash
uv run pytest tests/unit/test_graph_public_exports.py -q
```

Expected: currently unused re-exports fail the equality. Remove only names reported by the test; do not delete underlying symbols or rewrite consumers to submodule imports.

- [ ] **Step 3: Run the mandatory collection gate**

```bash
uv run pytest tests/ --collect-only -q
uv run pytest tests/unit/test_graph_public_exports.py tests/unit/test_graph_*.py tests/integration/test_graph_*.py -q
uv run pyright
```

Expected: collection succeeds with no ImportError and Pyright remains `0 errors`.

- [ ] **Step 4: Write the guard ledger**

Use columns `Guard`, `Source`, `Incident`, `Behavior`, `Regression`, `Retirement condition`, `Disposition`. Include retired recovery no-op/signature detector/pure policy; replaceable mirrors; and load-bearing contamination, reopen, crash, stale/SQLite retries, outbox wait, event-position guard, lease renewal/recovery bounds, callback rejection, compromised file state, startup process recovery, outbox redispatch, terminal filtering. State explicitly that event-triggered driving is not a retirement condition.

- [ ] **Step 5: Close W8 and commit**

Update actual pre/post export counts, policy relocation, mirror treatment, guard ledger, focused commands, and source SHAs. Do not claim polling was converted.

```bash
git add src/orchestrator/graph/__init__.py tests/unit/test_graph_public_exports.py \
  docs/dynamic-graph/guard-retirement-ledger.md docs/dynamic-graph/w8-drive-loop-cleanup-spec.md \
  docs/dynamic-graph/status.md docs/dynamic-graph/dynamic-graph-implementation-review.html
git commit -m "refactor: close W8 graph consolidation"
```

- [ ] **Step 6: Dispatch the fresh Task 1 verifier**

Run the exact four-command gate, record count and verifier SHA in W8/status, and commit `docs: record W8 verifier evidence`.

---

### Task 12: Introduce Readable But Non-Selectable Retired Runner

**Files:**
- Create: `tests/unit/test_retired_agent_runner.py`
- Modify: `src/orchestrator/config/enums.py`
- Modify: `src/orchestrator/config/__init__.py`
- Modify: `src/orchestrator/api/schemas/runs.py`
- Modify: `src/orchestrator/runners/agent_factory.py`
- Modify: `tests/unit/test_agent_types.py`
- Modify: `tests/unit/test_api_runs_validation.py`
- Regenerate: `ui/src/types/generated-enums.ts`

**Interfaces:**
- Produces: `AgentRunnerType.RETIRED`, `SELECTABLE_AGENT_RUNNER_TYPES`, `SELECTABLE_AGENT_RUNNER_VALUES`, `normalize_persisted_agent_runner_type`, `is_selectable_agent_runner_type`.

- [ ] **Step 1: Add retirement contract RED tests**

Assert `claude_sdk` is absent from enum values, `RETIRED` is readable but not selectable, normalizer maps old strings, create/resume/recover reject both `claude_sdk` and `retired`, and factory raises `AgentNotAvailableError` for retired.

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/unit/test_retired_agent_runner.py tests/unit/test_agent_types.py tests/unit/test_api_runs_validation.py -q
```

Expected: RETIRED/selectable helpers do not exist and `claude_sdk` is still accepted.

- [ ] **Step 3: Implement explicit readable/selectable split**

Add `RETIRED = "retired"`, remove `CLAUDE_SDK`, define an explicit frozenset of the four active runner types, and use selectable values at all run request validators. Add display `Retired runner`; never derive selectable values by iterating the full enum.

- [ ] **Step 4: Regenerate enums and run GREEN**

```bash
uv run python scripts/export_enums.py
uv run python scripts/export_enums.py --check
uv run pytest tests/unit/test_retired_agent_runner.py tests/unit/test_agent_types.py tests/unit/test_api_runs_validation.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/config src/orchestrator/api/schemas/runs.py \
  src/orchestrator/runners/agent_factory.py tests/unit/test_retired_agent_runner.py \
  tests/unit/test_agent_types.py tests/unit/test_api_runs_validation.py \
  ui/src/types/generated-enums.ts
git commit -m "feat: represent retired historical runners"
```

---

### Task 13: Migrate And Normalize Historical Claude SDK Values

**Files:**
- Create: `src/orchestrator/db/migrations/versions/zg1h2i3j4k5l_retire_claude_sdk_runner.py`
- Modify: `src/orchestrator/db/access/repositories.py`
- Modify: `src/orchestrator/state/session.py`
- Modify: `src/orchestrator/workflow/events/__init__.py`
- Modify: `tests/integration/test_migrations.py`
- Modify: `tests/integration/test_session_persistence.py`
- Modify: `tests/integration/test_projection_recovery.py`
- Modify: `tests/unit/test_pydantic_events.py`

**Interfaces:**
- Consumes: `normalize_persisted_agent_runner_type`.
- Produces: relational values `retired`; immutable JSON/events normalize only when read.

- [ ] **Step 1: Add migration and deserialization RED tests**

At pre-migration revision `zf1g2h3i4j5k`, insert `claude_sdk` into `runs.runner_type`, `attempts.runner_type`, `cost_records.agent_runner_type`, `interaction_log_artifacts.agent_runner_type`, and `agent_runner_model_profile_defaults.runner_type`. Assert upgrade maps them to `retired` while IDs/content remain unchanged and `events_v2.payload` bytes remain unchanged. Add state JSON and workflow-event tests proving nested values deserialize as RETIRED without rewriting files.

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/integration/test_migrations.py tests/integration/test_session_persistence.py \
  tests/integration/test_projection_recovery.py tests/unit/test_pydantic_events.py -q
```

Expected: enum validation fails on historical values and migration revision is absent.

- [ ] **Step 3: Add the linear migration**

Set `down_revision = "zf1g2h3i4j5k"`. Resolve any `(runner_type, profile)` retired collision deterministically before updating model defaults, then update all five columns. Do not update event payloads or journal files. Document downgrade behavior in the migration docstring.

- [ ] **Step 4: Normalize at three read boundaries**

Repository `_agent_runner_type` calls the shared normalizer. `SessionStateManager.load` deep-copies and maps run plus nested attempt values. `deserialize_event` recursively maps `claude_sdk` only under runner keys (`runner_type`, `agent_runner_type`, `old_agent`, `new_agent`) before Pydantic validation.

- [ ] **Step 5: Run GREEN and migration checks**

```bash
uv run pytest tests/integration/test_migrations.py tests/integration/test_session_persistence.py \
  tests/integration/test_projection_recovery.py tests/unit/test_pydantic_events.py -q
uv run alembic -c alembic.ini heads
```

Expected: one head `zg1h2i3j4k5l`; temporary DB tests pass; append-only payload remains unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/db/migrations/versions/zg1h2i3j4k5l_retire_claude_sdk_runner.py \
  src/orchestrator/db/access/repositories.py src/orchestrator/state/session.py \
  src/orchestrator/workflow/events/__init__.py tests/integration/test_migrations.py \
  tests/integration/test_session_persistence.py tests/integration/test_projection_recovery.py \
  tests/unit/test_pydantic_events.py
git commit -m "feat: migrate Claude SDK history to retired runner"
```

---

### Task 14: Delete Claude SDK Runtime And Dependency

**Files:**
- Delete: `src/orchestrator/runners/agents/claude_sdk/`
- Delete: `tests/unit/test_claude_sdk_agent.py`
- Delete: `tests/unit/test_claude_sdk_tool_filtering.py`
- Delete: `tests/integration/test_claude_sdk_agent.py`
- Create: `tests/integration/test_claude_sdk_removal.py`
- Modify: `src/orchestrator/runners/agent_detector.py`
- Modify: `src/orchestrator/runners/__init__.py`
- Modify: `src/orchestrator/runners/executor.py`
- Modify: `src/orchestrator/runners/runtime/monitor.py`
- Modify: `src/orchestrator/api/app.py`
- Modify: `scripts/worker.py`
- Modify: `src/orchestrator/graph_runtime/gatekeeper.py`
- Modify: `pyproject.toml`
- Regenerate: `uv.lock`

**Interfaces:**
- Produces: no SDK factory, detector, model discovery, exports, managed-runner path, or dependency.

- [ ] **Step 1: Add removal guard RED test**

Assert SDK source directory and public exports are absent, factory discovery has no Claude SDK/retired factory, active discovery returns neither old nor retired type, and pyproject/lock contain no `claude-agent-sdk`.

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/integration/test_claude_sdk_removal.py -q
```

Expected: SDK package, exports, detector, and dependency are present.

- [ ] **Step 3: Remove all executable SDK paths**

Delete the package/tests and all SDK branches. Preserve Claude CLI discovery with static CLI config; do not relocate SDK-owned Anthropic model fetching. Do not add RETIRED to managed/in-process/quota runner sets.

- [ ] **Step 4: Remove dependency and regenerate lock**

```bash
uv lock
```

Remove only `claude-agent-sdk`; retain `anthropic` if still direct/transitive.

- [ ] **Step 5: Run GREEN and absence searches**

```bash
uv run pytest tests/integration/test_claude_sdk_removal.py tests/integration/test_api_agents.py -q
uv run ruff check .
uv run pyright
```

Expected remaining `claude_sdk` occurrences in live source/tests are restricted to migration, compatibility normalizers, and negative/historical tests.

- [ ] **Step 6: Commit**

```bash
git add -A src/orchestrator/runners src/orchestrator/api/app.py \
  src/orchestrator/graph_runtime/gatekeeper.py scripts/worker.py pyproject.toml uv.lock \
  tests/unit/test_claude_sdk_agent.py tests/unit/test_claude_sdk_tool_filtering.py \
  tests/integration/test_claude_sdk_agent.py tests/integration/test_claude_sdk_removal.py
git commit -m "refactor: remove Claude SDK runner"
```

---

### Task 15: Fence Retired Selection, Start, Resume, And Configuration

**Files:**
- Modify: `src/orchestrator/api/routers/runners.py`
- Modify: `src/orchestrator/api/schemas/model_profiles.py`
- Modify: `src/orchestrator/api/schemas/review.py`
- Modify: `src/orchestrator/api/routers/review.py`
- Modify: `src/orchestrator/cli/runs.py`
- Modify: `src/orchestrator/workflow/service.py`
- Modify: `src/orchestrator/workflow/engine/errors.py`
- Modify: `src/orchestrator/workflow/__init__.py`
- Modify: `src/orchestrator/api/errors.py`
- Modify: `tests/integration/test_api_model_profiles.py`
- Modify: `tests/integration/test_api_runs.py`
- Modify: `tests/integration/test_graph_run_driver.py`

**Interfaces:**
- Produces: `RetiredAgentRunnerError`; active replacement-runner resume path.

- [ ] **Step 1: Add selection/lifecycle RED tests**

GET/PUT model defaults reject `claude_sdk` and `retired`; conflict overrides reject both; CLI rejects both; retired draft start and resume without replacement return a clear 409; resume with CODEX_SERVER succeeds and clears old SDK config; graph driver rejects RETIRED before seeding.

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/integration/test_api_model_profiles.py tests/integration/test_api_runs.py \
  tests/integration/test_graph_run_driver.py tests/integration/test_cli.py -q
```

- [ ] **Step 3: Enforce selectable types at every boundary**

Use shared selectable values in Pydantic request schemas, model-default path/body checks, conflict requests, and CLI parsing. Add `RetiredAgentRunnerError` checks in both public and `apply_*` start/resume methods. An explicit active replacement is allowed and receives `{}` unless new config is supplied; never carry SDK config forward.

- [ ] **Step 4: Run GREEN and commit**

```bash
uv run pytest tests/integration/test_api_model_profiles.py tests/integration/test_api_runs.py \
  tests/integration/test_graph_run_driver.py tests/integration/test_cli.py -q
uv run ruff check .
uv run pyright
git add src/orchestrator/api src/orchestrator/cli/runs.py src/orchestrator/workflow \
  tests/integration/test_api_model_profiles.py tests/integration/test_api_runs.py \
  tests/integration/test_graph_run_driver.py tests/integration/test_cli.py
git commit -m "fix: reject retired runner execution"
```

---

### Task 16: Close Claude SDK Product And Documentation Surface

**Files:**
- Create: `docs/dynamic-graph/claude-sdk-runner-removal-decision.md`
- Modify: `AGENTS.md`
- Modify: `AGENTS.lite.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/dynamic-graph/status.md`
- Modify: `docs/dynamic-graph/dynamic-graph-implementation-review.html`
- Modify: `docs/dynamic-graph/incident-2026-07-04-w2-driver-crash-w3-final-check-strand.md`
- Modify: `docs/dynamic-graph/p1-resolution-ledger.md`
- Modify: `research/open-questions.md`
- Modify: `research/recommendations/01-close-known-safety-gaps.md`
- Modify: `research/recommendations/04-cost-telemetry-and-budgets.md`
- Modify: `research/recommendations/08-consolidation-and-legacy-shrink.md`
- Modify: `research/system/design-history.md`
- Modify: `research/system/runtime-runners-cost.md`
- Modify: `research/system/overview.md`
- Modify: `routines/mcp-ops-c/routine.yaml`
- Modify: `routines/routine-improvements/routine.yaml`
- Modify: `routines/temporal-alignment/routine.yaml`

**Interfaces:**
- Produces: decision `remove`, OQ-5 closure, no executable routine references to deleted SDK symbols.

- [ ] **Step 1: Remove current-product SDK claims and executable tasks**

Update runner lists to the four active runners plus readback-only retired state. Remove SDK-specific routine milestones/import checks rather than leaving broken executable routines. Preserve historical incident facts with dated supersession notes.

- [ ] **Step 2: Write the removal decision**

Record failure evidence, decision, Codex Server replacement, migration/read-time compatibility, no journal rewrite/database wipe, and reintroduction criteria. State retired is not selectable or dispatchable.

- [ ] **Step 3: Verify documentation and routine loading**

```bash
uv run pytest tests/unit/test_routine_loading.py tests/integration/test_routine_loading.py -q
git diff --check
```

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md AGENTS.lite.md docs research routines
git commit -m "docs: record Claude SDK runner removal"
```

- [ ] **Step 5: Dispatch the fresh Task 2 verifier**

Run the exact four-command gate. Also run `uv run python scripts/export_enums.py --check` and `uv run alembic -c alembic.ini heads`. Record exact results/SHAs in status and decision doc, then commit `docs: record Claude SDK removal verifier evidence`.

---

### Task 17: Final Branch Verification And Evidence

**Files:**
- Modify: `docs/dynamic-graph/status.md`
- Modify: `docs/dynamic-graph/w8-drive-loop-cleanup-spec.md`
- Modify: `docs/dynamic-graph/guard-retirement-ledger.md`
- Modify: `docs/dynamic-graph/claude-sdk-runner-removal-decision.md`

**Interfaces:**
- Consumes: all source commits and per-task verifier evidence.
- Produces: final reviewable head SHA and complete durable closeout ledger.

- [ ] **Step 1: Run a fresh final verifier**

Dispatch a new verifier with no builder context:

```bash
uv run pytest tests/ -q -n auto --dist worksteal
uv run ruff check .
uv run pyright
git diff --check
```

Expected: full suite green, Ruff clean, Pyright `0 errors`, diff check clean.

- [ ] **Step 2: Run generated/migration/export checks**

```bash
uv run python scripts/export_enums.py --check
uv run alembic -c alembic.ini heads
uv run pytest tests/ --collect-only -q
uv run pytest tests/unit/test_graph_public_exports.py tests/integration/test_claude_sdk_removal.py -q
```

- [ ] **Step 3: Record exact final evidence**

Record command outputs, counts, source commit SHAs, verifier identity/SHA, and final head predecessor. Do not write an anticipated SHA.

- [ ] **Step 4: Commit evidence and report the final head**

```bash
git add docs/dynamic-graph/status.md docs/dynamic-graph/w8-drive-loop-cleanup-spec.md \
  docs/dynamic-graph/guard-retirement-ledger.md \
  docs/dynamic-graph/claude-sdk-runner-removal-decision.md
git commit -m "docs: finalize dynamic graph backlog evidence"
git status --short --branch
git log --oneline -20
git rev-parse HEAD
```

Expected: clean worktree on `codex/backlog-closeout`. Report the final SHA and leave the branch/worktree in place without merging.
