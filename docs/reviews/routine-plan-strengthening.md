# Routine Plan Strengthening: Wiring Verification

**Date:** 2026-03-05
**Source:** Post-run validation of run a70797d7 against `docs/reviews/action-plan.md`
**File modified:** `routines/routine-improvements/routine.yaml`

---

## Problem

Run a70797d7 completed all 27 tasks successfully per the orchestrator. However, deep code inspection revealed that 3 of 15 actions were **dead code** — built, tested, but never called from the running system. The verifier graded them as passing because it checked that the code existed and tests passed, without verifying that the code was wired into the application.

| Severity | Actions | Nature |
|----------|---------|--------|
| **High** (dead code) | A6, A11, A13 | Features built and tested but never called |
| **Medium** | A7+A8, A18 | Partial migration; not in worktree |
| **Low** | A2, A4, A14, A16 | Soft enforcement, undiscoverable docs, invisible field |
| **None** | A1, A5, A10, A12, A17 | Fully wired and correct |

## Changes Made

### 1. Global Verifier Instructions

Added to the routine `description` field (applies to all tasks):

> You must verify not just that code exists, but that it is WIRED INTO the running application. A feature that is implemented but never called from the live code paths is NOT complete.

Includes specific guidance:
- New functions must be imported AND called from service/router/executor code
- New API fields must appear in both ORM model AND Pydantic response schema
- New callbacks must be constructed in executor and passed to `agent.execute()`
- New prompt sections must appear in the prompt returned by `/tasks/{id}/prompt`
- Grade F for dead code

### 2. Auto-Verify Fixes (from observed execution failures)

| Step/Task | Fix | Original Error |
|-----------|-----|----------------|
| S-03/T-01 | `import Executor` → `import AgentExecutor` | Wrong class name |
| S-10/T-01 | `orchestrator.routers.tasks` → `orchestrator.api.routers.tasks` | Wrong module path |
| S-11/T-01 | `StepConfig(tasks=[])` → `assert 'step_auto_verify' in StepConfig.model_fields` | Pydantic validation error on empty task list |

### 3. New Wiring Requirements

| Task | New Req | What it enforces |
|------|---------|-----------------|
| S-05/T-01 (A7) | R3 | Git commit instructions must exist in ALL agent builder paths (cli, claude_sdk, codex_server, openhands) |
| S-06/T-01 (A8) | R3 | No instructions lost in migration — every instruction removed from shared prompt must exist in all relevant agent prompt paths |
| S-07/T-01 (A6) | R2 | `compress_clarifications()` is called from `respond_to_clarification()` in service.py — not just defined, but wired |
| S-07/T-01 (A6) | R3 | Compressed decisions are passed to `generate_builder_prompt()` via the `decisions=` parameter |
| S-08/T-01 (A14) | R2 | Guidance document is cross-referenced from AGENTS.md or another discoverable location |
| S-10/T-01 (A11) | R3 | `on_escalation` callback created in executor.py and passed to `agent.execute()` |
| S-10/T-01 (A11) | R4 | Escalation endpoint listed in callback instructions returned by `GET /tasks/{id}/prompt` |
| S-11/T-01 (A12) | R3 | `step_auto_verify` executed from the live step completion path in service.py |
| S-12/T-02 (A13) | R4 | `TaskContextBuilder` imported and called from the prompt generation path — summarized content appears in prompts |
| S-13/T-01 (A16) | R3 | Complexity field included in task API response schema |

### 4. New Auto-Verify Wiring Checks

Grep-based checks that verify code is present in the expected integration points:

| Task | Check ID | Command |
|------|----------|---------|
| S-07/T-01 (A6) | `wiring_check` | `grep -q "compress_clarifications" src/orchestrator/workflow/service.py` |
| S-10/T-01 (A11) | `executor_wiring` | `grep -q "on_escalation" src/orchestrator/agents/executor.py` |
| S-10/T-01 (A11) | `callback_instructions` | `grep -q "escalat" src/orchestrator/api/routers/tasks.py` |
| S-12/T-02 (A13) | `wiring_check` | `grep -rq "TaskContextBuilder\|SummaryCache" src/.../tasks.py src/.../prompts.py src/.../service.py` |

### 5. New Verifier Rubric Items

Explicit rubric entries for the three highest-severity gaps:

| Task | Rubric ID | Instruction |
|------|-----------|-------------|
| S-07/T-01 (A6) | R2_wiring | Verify `compress_clarifications()` is imported AND called in `respond_to_clarification()`. Grade F if imported but never called. |
| S-10/T-01 (A11) | R3_wiring | Verify `on_escalation` callback is created and passed to `agent.execute()`. Grade F if callback exists but is never passed to agents. |
| S-12/T-02 (A13) | R4_wiring | Verify `TaskContextBuilder` is called from the prompt generation path. Grade F if classes exist but are never called from the live prompt path. |

### 6. Enhanced Task Context

Updated task_context for affected tasks to include explicit wiring instructions:
- A6: "CRITICAL WIRING" block explaining the import/call chain required
- A7: Warning about ensuring git instructions exist in all agent paths
- A8: Warning about instructions being lost in migration
- A11: Steps 4 and 5 added for executor callback and callback instructions
- A12: "WIRING" block requiring code path tracing
- A13: "CRITICAL WIRING" block with trace requirements
- A14: Instruction to add cross-reference from AGENTS.md
- A16: Instruction to add field to API response schema

## Hypothesis

These changes test whether **better requirements and better verification instructions** are sufficient to prevent dead-code gaps, without changes to the orchestrator itself. If the re-run still produces unwired features, the problem is structural (the system cannot verify wiring) rather than instructional (the verifier wasn't told to check).
