# Step 05: Executor and Monitor Integration

Integrate local and remote Codex agents into run lifecycle management so start/resume/recovery/cancel/monitor semantics match other managed agents.

## Intent Verification
**Original Intent**: `docs/codex-server/intent.md` requires lifecycle controls, recovery behavior, and callback workflow continuity for both Codex variants.

**Functionality to Produce**:
- Executor dispatch creates both Codex agents
- Spawn/resume/recover paths support both variants without duplicate runs
- Monitor and cancellation paths correctly handle Codex-managed sessions

**Final Verification Criteria**:
- Lifecycle transitions remain correct during start/pause/resume/cancel/recover
- Dead-agent detection does not false-positive or leak task locks

---

## Task 1: Add executor dispatch for codex_server and codex_server_remote

**Description**: Extend agent creation logic so lifecycle code can instantiate both variants.

**Implementation Plan (Do These Steps)**
- [ ] Update `src/orchestrator/agents/executor.py` `_create_agent` branches for both Codex agent types.
- [ ] Ensure required config is passed through unchanged to each agent constructor.
- [ ] Add/update unit tests for successful dispatch and unsupported-type safety.

```bash
uv run pytest tests/unit -k "executor and create_agent" -v
```

**References**
- `docs/codex-server/step-05-plan.md`
- `docs/codex-server/step-03-plan.md`
- `docs/codex-server/step-04-plan.md`

**Constraints**
- [ ] Atomicity budget: change <=3 files and <=220 LOC.
- [ ] Do not modify monitor logic in this task.

**Functionality (Expected Outcomes)**
- [ ] Executor can create both Codex agent variants.
- [ ] Existing agent creation behavior remains unchanged.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit -k "executor and codex" -v` passes.
- [ ] `uv run ruff check src/orchestrator/agents/executor.py` passes.

---

## Task 2: Integrate spawn/cancel/resume/recover flow for both variants

**Description**: Wire Codex variants through execution lifecycle paths and preserve task-lock correctness.

**Implementation Plan (Do These Steps)**
- [ ] Update `src/orchestrator/agents/executor.py` lifecycle paths to support both Codex types in spawn/resume/recover logic.
- [ ] Ensure cancellation semantics propagate to both Codex agents and release locks cleanly.
- [ ] Define and enforce stale-session conflict rule for recovery: if persisted session is healthy, resume; if stale/unreachable, fail-fast that session and start a new attempt with explicit reason.
- [ ] Add/update integration tests covering start, pause/resume, cancel, and recover for each variant.
- [ ] Add integration tests for both stale-session and healthy-session recovery branches.

```bash
uv run pytest tests/integration -k "recover or resume or cancel" -v
```

**References**
- `docs/codex-server/step-05-plan.md`
- `src/orchestrator/workflow/service.py`

**Constraints**
- [ ] Atomicity budget: change <=5 files and <=450 LOC.
- [ ] System must remain runnable after this task.

**Functionality (Expected Outcomes)**
- [ ] Lifecycle operations behave consistently across existing and new managed agents.
- [ ] Recovery does not create duplicate execution attempts.
- [ ] Recovery behavior is deterministic when persisted session state conflicts with runtime health.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/integration -k "codex and lifecycle" -v` passes.
- [ ] `uv run pyright src/orchestrator/agents/executor.py` passes.

---

## Task 3: Extend monitor health/dead-agent handling for Codex sessions

**Description**: Make monitoring aware of Codex local/remote session behavior and avoid false dead-agent decisions.

**Implementation Plan (Do These Steps)**
- [ ] Update `src/orchestrator/agents/monitor.py` health checks to include Codex local and remote run states.
- [ ] Ensure timeout/dead-agent paths trigger existing recovery or failure handling without orphaning sessions.
- [ ] Add/update tests for dead-agent detection with both Codex variants.

```bash
uv run pytest tests/unit -k "monitor and codex" -v
```

**References**
- `docs/codex-server/step-05-plan.md`
- `docs/codex-server/context/open-risks.md`
- `src/orchestrator/agents/monitor.py`

**Constraints**
- [ ] Atomicity budget: change <=4 files and <=320 LOC.
- [ ] Keep monitor checks lightweight and non-blocking.

**Functionality (Expected Outcomes)**
- [ ] Dead-agent monitoring covers both Codex variants.
- [ ] No lock leaks or ghost-running attempts after monitor interventions.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit -k "dead-agent and codex" -v` passes.
- [ ] `uv run ruff check src/orchestrator/agents/monitor.py` passes.
