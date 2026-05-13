# Plan: Routine System Effectiveness Improvements

## Implementation Order

Work is organized into 5 milestones, ordered by dependency chain and impact. Each milestone produces independently testable, deployable improvements. Earlier milestones fix bugs and close security holes; later milestones add capabilities.

---

## Milestone 1: Gate Fixes & Safety (A1, A2, A5, A10)

**Goal:** Close the structural holes that let incomplete/destructive work through gates.

### Step 1: Fix auto_verify timing (A1)

Reorder `submit_for_verification()` in `engine.py` so auto_verify commands execute before the checklist gate evaluates self-reported status. If any `must: true` auto_verify item fails, block the BUILDING→VERIFYING transition.

**Files:** `src/orchestrator/workflow/engine.py`
**Tests:** Unit test confirming auto_verify failure blocks transition even when all checklist items are self-reported as done.
**Risk:** Low — this is a bug fix restoring intended behavior.

### Step 2: Require verification on every task (A2)

Add validation that every task has at least one of: auto_verify items, or a verifier rubric. Implement at two levels:
1. **Load-time validation** in `models.py` — `TaskConfig` model_validator rejects tasks with neither
2. **Runtime guard** in `transitions.py` — block auto-grade path (the code that assigns A to self-reported "done" items) when no verification was configured

**Files:** `src/orchestrator/config/models.py`, `src/orchestrator/workflow/transitions.py`
**Tests:** Validation error on task with no auto_verify and no verifier; runtime block on auto-grade path.
**Decision:** Warn by default (log warning, allow loading). Add `strict_validation` flag to enable hard rejection. This lets existing routines work while encouraging migration.
**Risk:** Low with this migration strategy — existing routines continue to work until strict mode is enabled.

### Step 3: Pre-run test health check (A5)

Before the first task attempt in a run, execute the project's test suite. If it returns non-zero, block task start with a descriptive error. This replaces baseline comparison — if tests are clean at start, any new failures are regressions.

**Files:** `src/orchestrator/agents/executor.py`
**Tests:** Integration test with a project that has failing tests — verify task start is blocked.
**Risk:** Medium — need to handle projects without test suites, and avoid blocking on skipped tests.
**Decision:** Test command is configured via a project-level config file with convention fallback (default: `uv run pytest --tb=no -q`). See architecture for config file format.

### Step 4: Verifier model pinning (A10)

At run creation, snapshot the current verifier model into the run state. All verifier invocations within the run use this pinned model, ignoring any config changes made after run start.

**Files:** `src/orchestrator/workflow/engine.py` or `src/orchestrator/agents/executor.py`, `src/orchestrator/state/models.py`
**Tests:** Unit test confirming verifier uses pinned model even when config changes.
**Risk:** Low — additive field on run state.

---

## Milestone 2: Prompt & Context Efficiency (A7, A8, A6, A14)

**Goal:** Reduce prompt waste and move agent-specific content to the right place.

### Step 5: Trim prompt dead weight (A7)

Remove the "Avoiding Loops" section and other identified dead-weight sections from the shared system prompt in `prompts.py`. The 39% reduction figure from experiment D4 is informational — we remove the specific identified sections rather than targeting an exact percentage.

**Files:** `src/orchestrator/workflow/prompts.py`
**Tests:** Unit test confirming removed sections don't appear in generated prompts. Verify remaining prompt structure is valid.
**Risk:** Low — D4 confirmed these sections are universally ignored.

### Step 6: Migrate agent-specific instructions (A8)

Move agent-behavioral instructions (file re-reading avoidance, response length preferences, tool usage patterns) from the shared prompt template to individual agent implementations.

**Files:** `src/orchestrator/agents/cli.py`, `src/orchestrator/agents/openhands.py`, `src/orchestrator/agents/codex_server.py`, `src/orchestrator/agents/claude_sdk.py`, `src/orchestrator/workflow/prompts.py`
**Tests:** Verify each agent's prompt includes its specific instructions; verify shared prompt no longer contains agent-specific content.
**Risk:** Low — instructions already exist; this is a move, not a rewrite.

### Step 7: Compress clarifications on resolution (A6)

After each Q&A round resolves, summarize resolved questions into a "decisions" section. Downstream tasks receive decisions only. Archive raw Q&A separately.

**Files:** `src/orchestrator/workflow/service.py` or new module for summarization
**Tests:** Unit test verifying resolved Q&A is compressed; downstream prompt only contains decisions.
**Risk:** Medium — summarization quality matters. Start with template-based extraction (decision + rationale), not LLM summarization.

### Step 8: Step context guidance (A14)

Add guidance to planner documentation about keeping `step_context` compact and builder-relevant. Step context is intentionally duplicated per task (each task needs it), so the fix is making it shorter, not deduplicating.

**Files:** New or updated documentation in `docs/` (planner guidance)
**Tests:** N/A (documentation only).
**Risk:** None.

---

## Milestone 3: Safety Guards (A11)

**Goal:** Allow agents to escalate unfulfillable work.

### Step 10: Agent escalation for unfulfillable requirements (A11)

Add a new callback type allowing builder/verifier agents to flag a requirement as "cannot be fulfilled in this environment" and escalate to the human. The run pauses on escalation.

**Files:** `src/orchestrator/agents/interface.py` (new callback type), `src/orchestrator/routers/tasks.py` (new endpoint), `src/orchestrator/workflow/engine.py` (handle escalation), UI components
**Tests:** Integration test: agent calls escalation endpoint → run pauses → human can modify/skip.
**Risk:** Medium — new API surface. Keep minimal: one endpoint, one callback type.

---

## Milestone 4: Schema & Architecture Extensions (A12, A13, A16, A17)

**Goal:** Extend the config schema and loader for new capabilities.

### Step 11: Step-level integration tests (A12)

Add `step_auto_verify` field to `StepConfig`. After all tasks in a step complete, execute step-level auto_verify commands that verify cross-task integration. **Decision:** If step_auto_verify fails, the step fails and the run halts (no auto-advance to next step).

**Files:** `src/orchestrator/config/models.py`, `src/orchestrator/workflow/engine.py` (step completion logic)
**Tests:** Unit test with step_auto_verify configured; verify execution after step tasks complete.
**Risk:** Low — additive schema field, clear execution point in step completion.

### Step 12: Context summarization with critical-aspect preservation (A13)

Expand `context_from` schema to include `summarize: true` and `critical: "description"`. When summarize is set:
1. Generate summary using a configurable model (default: a cheap model like Haiku, configurable per routine/project)
2. Verify critical aspects are preserved (check against `critical` description)
3. Re-summarize if critical aspects missing (max 2 iterations)
4. Cache summaries per step for reuse across tasks

Intent documents should NOT be summarized. Plan and architecture CAN be when only high-level context is needed.

**Files:** `src/orchestrator/config/models.py` (schema), `src/orchestrator/workflow/prompts.py` (summary generation), new summary cache module
**Tests:** Unit test for summary generation; integration test for critical-aspect verification loop.
**Risk:** High — summarization quality is hard to guarantee. Implement as opt-in with clear documentation. The critical-aspect check is the safety net.

### Step 13: Task complexity labeling (A16)

Add `complexity: simple | standard` field to task config. `simple` = atomic, suitable for local LLMs. `standard` = may need more capable models. Diagnostic metadata only — no automatic behavior changes.

**Files:** `src/orchestrator/config/models.py`, `src/orchestrator/config/enums.py`
**Tests:** Schema validation test for the new field.
**Risk:** None — purely additive metadata.

### Step 14: Multi-file routine definitions (A17)

Support routines split across multiple YAML files. A root `routine.yaml` can reference step files (`step-01.yaml`, `step-02.yaml`). The loader resolves references, validates all files exist, and assembles the complete routine. **Decision:** If a step specifies `file` AND includes other step fields, validation fails — no overlap allowed.

**Files:** `src/orchestrator/config/loader.py`, `src/orchestrator/config/models.py` (step reference schema)
**Tests:** Unit test loading a multi-file routine; validation test for missing step files.
**Risk:** Medium — file resolution paths, relative vs absolute references, error messages for missing files.

---

## Milestone 5: Planning Documentation (A18)

**Goal:** Ensure planner docs reflect failure mode analysis practices.

### Step 15: Failure mode analysis in dry run (A18)

Update planner documentation to reflect that the dry-run stage should include failure mode analysis: identify likely failure modes per step, then re-engineer the plan to minimize their likelihood. This is already partially done in existing routine YAML — ensure docs match.

**Files:** Documentation in `docs/` or routine templates
**Tests:** N/A (documentation only).
**Risk:** None.

---

## Dependencies Between Milestones

```
M1 (Gate Fixes) ← no dependencies, start immediately
M2 (Prompt)     ← no hard dependencies, runs in PARALLEL with M1
M3 (Guards)     ← follows M1/M2
M4 (Schema)     ← A12 depends on step completion logic touched in M1
                ← A13 depends on prompt changes in M2
                ← A17 depends on loader, independent of M1-M3
M5 (Docs)       ← can run anytime, no code dependencies
```

**Decision:** M1 and M2 run in parallel for faster delivery. No hard dependencies exist between them.

## Iteration Strategy

Each milestone is independently shippable. Within each milestone, steps are ordered so earlier steps unblock later ones. If any step proves more complex than expected:
1. Ship what's complete in the current milestone
2. Move the complex step to the next milestone
3. Continue with the next milestone's steps that aren't blocked

## Test Strategy Summary

- Maintain 786+ test baseline throughout
- Each new feature adds unit tests (pure function behavior) and integration tests (API/workflow behavior)
- Run full test suite after each milestone before merging
- No mocking — use real objects with dependency injection per AGENTS.md constraints
