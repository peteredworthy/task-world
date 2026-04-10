# Action Plan: Routine Effectiveness Improvements

**Date:** 2026-03-04
**Source:** `docs/reviews/routine-effectiveness-review.md` + human feedback (2 rounds)

---

## Actions

### A1. Fix auto_verify timing (Bug Fix)
Auto_verify commands must run *before* the checklist gate accepts self-reported "done" status. This was the intended behavior but isn't happening. If any `must: true` auto_verify item fails, block BUILDING→VERIFYING regardless of self-reported status.
**Evidence:** D1 (30.4% false-positive rate), D5 (bypass confirmed)
**Scope:** `src/orchestrator/workflow/engine.py` — reorder auto_verify execution relative to checklist gate in `submit_for_verification()`.

### A2. Require auto_verify or verifier on every task (Enforcement)
No task should be completable via self-report alone. If a task has neither auto_verify nor a verifier rubric, block the auto-grade path that currently assigns straight As. Options: (a) validation error at routine load time, or (b) runtime block at `transition_after_verification`.
**Evidence:** D5 (undefended tasks auto-grade to A)
**Scope:** `src/orchestrator/config/models.py` (validation) or `src/orchestrator/workflow/transitions.py` (runtime).

### A3. Per-requirement grading (Gate Improvement)
Replace composite rubric items (`R1-R3 — A: ...`) with one rubric item per requirement. Each requirement gets its own grade, evaluated independently against thresholds.
**Evidence:** D7 (4-grade variance), review analysis
**Scope:** Routine YAML authoring guidance + verifier prompt generation in `src/orchestrator/workflow/prompts.py`.

### A4. Test count regression guard (Automated Check)
Provide a reusable auto_verify command that captures the test list before the builder starts and compares after. Flag if tests were removed. Opt-in per task — not suitable for cleanup/renaming tasks.
**Evidence:** D1 (2 tasks deleted 130+ lines of tests undetected)
**Scope:** New utility script (e.g., `scripts/check_test_count.sh`) + documentation for routine authors.

### A5. Pre-run test health check (Enforcement)
Don't start a task if the test suite isn't clean. If CI is green, there are no pre-existing failures. This replaces the "baseline comparison" approach entirely.
**Evidence:** Run data (death spiral from pre-existing failures)
**Scope:** `src/orchestrator/agents/executor.py` — run test suite before first task attempt, block if non-zero.

### A6. Compress clarifications on resolution (Context Efficiency)
After each Q&A round, summarize resolved questions into a "decisions" section. Archive raw Q&A. Downstream tasks receive decisions only.
**Evidence:** Analysis (unbounded clarifications growth)
**Scope:** `src/orchestrator/workflow/service.py` or new summarization step in idea-to-plan routine.

### A7. Trim prompt dead weight (Context Efficiency)
Remove the "Avoiding Loops" section (512 chars, universally ignored) and other dead-weight prompt sections identified in D4. Target 39% prompt reduction.
**Evidence:** D4 (34% dead weight, agents violate "Avoiding Loops" instruction)
**Scope:** `src/orchestrator/workflow/prompts.py` — system message template.

### A8. Migrate agent-specific instructions to agent runners (Architecture)
Move agent-behavioral instructions (e.g., "do not re-read files", "use shorter responses") from the shared prompt template into individual agent runner implementations.
**Evidence:** D9 (agents have fundamentally different interaction patterns)
**Scope:** `src/orchestrator/agents/cli.py`, `openhands.py`, `codex_server.py`, `claude_sdk.py`.

### A9. Sub-agent tool for OpenHands (Capability)
Provide a sub-agent spawning tool for OpenHands so research tasks can delegate exploration to lightweight sub-agents. Other agent types already support this.
**Evidence:** D6 (research tasks: 75.6% orientation), D10 (task type drives token cost)
**Scope:** `src/orchestrator/agents/openhands.py` — new tool registration.

### A10. Verifier model pinning (Stability)
Pin the verifier model at run creation time. Prevent mid-run model switches that amplify grade variance.
**Evidence:** D7 (D→A grade jump coincided with model switch)
**Scope:** `src/orchestrator/workflow/engine.py` or `executor.py` — snapshot model at run start, enforce on verifier invocations.

### A11. Agent escalation for unfulfillable requirements (Human Escalation)
Give the builder/verifier the ability to flag a requirement as "cannot be fulfilled in this environment" and escalate to the human. Pair with ensuring environment-dependent tests skip (not fail) when prerequisites are missing.
**Evidence:** Run data (8-attempt death spiral on unfulfillable R2)
**Scope:** New callback type in `src/orchestrator/agents/interface.py`, API endpoint, and UI surface.

### A12. Step-level integration tests (Gate Improvement)
After all tasks in a step complete, run step-level integration tests that verify the tasks work together as a coherent component. Per-task auto_verify checks the part; step-level checks the whole. The planner should generate these as part of the step plan.
**Evidence:** D1 (individual tasks pass but combined result may not integrate)
**Scope:** New `step_auto_verify` field on `StepConfig`, executed in step completion logic in `src/orchestrator/workflow/engine.py`. Planner guidance in `docs/plan-runner/`.

### A13. Context summarization with critical-aspect preservation (Context Efficiency)
Expand the `context_from` schema to include `summarize: true` and `critical: "description of what must be preserved"`. When summarize is set, the system generates a summary using the primary agent's model, then verifies the critical aspects are preserved (iterative loop if not). Cache summaries for reuse across tasks in the same step.
**Implementation notes:**
- Start with the primary agent model for summarization (keep interface clean for later configurability).
- Fixed process for now, but design the interface to support swappable runners/models later.
- Intent documents should generally NOT be summarized (they're short). Plan and architecture CAN be when the task only needs high-level context.
**Evidence:** Analysis (50K token prompts in idea-to-plan downstream tasks)
**Scope:** `src/orchestrator/config/models.py` (schema), `src/orchestrator/workflow/prompts.py` (summary generation), new summary cache.

### A14. Step context guidance: keep compact (Planning Guidance)
Step context duplication across task prompts is intentional — each task needs to understand what it's part of. Do not deduplicate. Instead, add guidance to the planner to keep step_context compact and builder-relevant (not verbose descriptions).
**Evidence:** D4 (step context is used by agents), human feedback
**Scope:** `docs/plan-runner/` and `docs/planner/` — add guidance on step_context length and focus.

### A15. Golden contract tests during planning (Planning Improvement)
Generate verification test stubs during planning that test edge contracts only: public API signatures, return types, error cases, schema fields/types/defaults, integration boundaries (imports, wiring). Exclude internal implementation details. Requires clear prompting to constrain scope.
**Evidence:** D2 (74.6% requirements uncovered by auto_verify)
**Scope:** New stage or sub-task in idea-to-plan routine. Contract test template in `docs/planner/templates/`.

### A16. Task complexity labeling (Planning Metadata)
Add a `complexity: simple | standard` field to task config. `simple` = atomic enough for a local LLM (few decisions, small scope). `standard` = may need decomposition for local LLMs. No automatic splitting — use as a diagnostic to correlate with where local agents struggle.
**Evidence:** D9 (Codex 16x faster than OpenHands), D10 (complexity drives token cost)
**Scope:** `src/orchestrator/config/models.py` (schema), planner guidance.

### A17. Multi-file routine definitions (Architecture)
Support routines split across multiple YAML files — one per step. A root `routine.yaml` references step files (`step-01.yaml`, `step-02.yaml`, etc.). Benefits: planner works on one step at a time (smaller context), step-level version control, easier review.
**Evidence:** Human feedback, analysis (863-line routine YAML is unwieldy for construction)
**Scope:** `src/orchestrator/config/loader.py` (multi-file resolution), `src/orchestrator/config/models.py` (step reference schema).

### A18. Failure mode analysis in dry run (Planning Improvement)
Expand the dry-run stage (S-05) in the idea-to-plan routine to include failure mode analysis: identify likely failure modes per step, then re-engineer the plan to minimize their likelihood. Integrated into the existing dry-run process, not a separate stage.
**Evidence:** Run data (death spiral, unfulfillable requirements), human feedback
**Scope:** `routines/idea-to-plan/routine.yaml` — expand S-05 task_context and requirements.

---

## Priority Order

**Immediate (bug fixes + high-impact, low-effort):**
1. A1 — Fix auto_verify timing (bug)
2. A2 — Require verification on every task
3. A7 — Trim prompt dead weight
4. A5 — Pre-run test health check
5. A10 — Verifier model pinning

**Short-term (gate + planning improvements):**
6. A3 — Per-requirement grading
7. A4 — Test count regression guard
8. A11 — Agent escalation for unfulfillable requirements
9. A12 — Step-level integration tests
10. A14 — Step context guidance

**Medium-term (context efficiency + architecture):**
11. A6 — Compress clarifications
12. A13 — Context summarization with critical-aspect preservation
13. A8 — Agent-specific instructions to runners
14. A15 — Golden contract tests
15. A18 — Failure mode analysis in dry run

**Longer-term (new capabilities):**
16. A16 — Task complexity labeling
17. A17 — Multi-file routine definitions
18. A9 — Sub-agent tool for OpenHands
