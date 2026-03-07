# Implementation Plan: Fan-Out Tasks & Script-Only Tasks

## Overview

Two new task execution modes for the orchestrator:

1. **Fan-out tasks** — spawn parallel sub-agents from a file glob, each producing
   a known output file. Inner mechanical verification with 4 retries. Outer LLM
   verification re-runs all sub-agents with feedback on failure.
2. **Script-only tasks** — run a shell command, no LLM. Exit 0 = pass, non-zero = fail + pause.

## Design Decisions (locked in)

- Sub-agents share the parent task's worktree
- Inner verification is mechanical only (auto_verify), max_attempts: 4
- Outer verification failure re-runs ALL sub-agents with full verifier comment
- No roll-up/merge in fan-out — add a script task after if needed
- `max_concurrent` configurable in YAML, default 4
- Any sub-agent failure = task failure = run pauses
- UI shows fan-out sub-agents as parallel "attempts" (building/verifying in parallel)

## Phase 1: Config & Schema Changes

### 1a. Config models (`src/orchestrator/config/models.py`)

Add `FanOutConfig` and `script` field to `TaskConfig`:

```python
class FanOutConfig(BaseModel):
    input_glob: str                    # e.g. "docs/{{feature}}/steps/step-*.md"
    output_pattern: str                # e.g. "docs/{{feature}}/dry-run/{{item_stem}}-notes.md"
    per_item_prompt: str               # prompt template with {{item_content}}, {{output_path}}
    shared_context: list[str] = []     # e.g. ["{{file:docs/intent.md}}"]
    max_attempts: int = 4              # inner retry limit (mechanical only)
    max_concurrent: int = 4            # parallel sub-agent limit
    auto_verify: AutoVerifyConfig | None = None  # inner mechanical checks

class TaskConfig:
    # ... existing fields ...
    fan_out: FanOutConfig | None = None
    script: str | None = None          # shell script for script-only tasks
```

Validation: `task_context`, `fan_out`, and `script` are mutually exclusive.

### 1b. DB models (`src/orchestrator/db/models.py`)

Add to `TaskModel`:
```python
parent_task_id: Mapped[str | None] = mapped_column(String, ForeignKey("tasks.id"), nullable=True)
fan_out_index: Mapped[int | None] = mapped_column(Integer, nullable=True)  # which sub-agent (0-based)
fan_out_input: Mapped[str | None] = mapped_column(String, nullable=True)   # input file path
fan_out_output: Mapped[str | None] = mapped_column(String, nullable=True)  # output file path
```

No changes to AttemptModel — sub-agents create normal attempts on their child tasks.

### 1c. State models (`src/orchestrator/state/models.py`)

Add to `TaskState`:
```python
parent_task_id: str | None = None
fan_out_index: int | None = None
fan_out_input: str | None = None
fan_out_output: str | None = None
```

### 1d. Alembic migration

Add columns: `parent_task_id`, `fan_out_index`, `fan_out_input`, `fan_out_output` to tasks table.

### 1e. API schemas (`src/orchestrator/api/schemas/tasks.py`)

Add fan-out fields to `TaskDetailResponse`:
```python
parent_task_id: str | None = None
fan_out_index: int | None = None
fan_out_input: str | None = None
fan_out_output: str | None = None
```

## Phase 2: Workflow Engine Changes

### 2a. Fan-out expansion (`src/orchestrator/workflow/engine.py`)

When a fan-out task is started:
1. Resolve `input_glob` in the worktree directory
2. For each matching file, derive output path from `output_pattern`
3. Create child `TaskModel` + `TaskState` records (title: parent title + filename)
4. Set parent task status to a new status: `fan_out_running`
5. Start child tasks (up to `max_concurrent` at a time)

### 2b. Child task lifecycle

Child tasks follow normal PENDING → BUILDING → VERIFYING → COMPLETED/FAILED flow.
- Inner verification: only `auto_verify` (from `fan_out.auto_verify`), no LLM verifier
- On auto_verify failure: retry up to `fan_out.max_attempts`
- On child failure (exhausted retries): parent task fails, run pauses

### 2c. Parent task completion

When all child tasks reach COMPLETED:
- Parent task transitions to VERIFYING (outer LLM verifier runs)
- If outer verifier passes: parent task → COMPLETED
- If outer verifier fails: all child tasks reset to PENDING, re-run with verifier
  feedback prepended to their prompts. Parent stays in `fan_out_running`.

### 2d. Script task execution

When a task with `script` is started:
1. Run the script in the worktree via subprocess
2. Capture stdout/stderr
3. Exit 0 → task COMPLETED (store output in attempt)
4. Non-zero → task FAILED, run pauses (store output + exit code in attempt)
5. No verification phase — script result IS the verification

## Phase 3: Executor Changes

### 3a. Fan-out executor (`src/orchestrator/runners/executor.py`)

New method to handle fan-out tasks:
- Spawn up to `max_concurrent` child agents in parallel
- Use asyncio.Semaphore for concurrency control
- Each child agent gets: shared_context + per_item_prompt with interpolated values
- Track child completion, handle failures

### 3b. Script executor

New method for script tasks:
- `asyncio.create_subprocess_shell()` in the worktree directory
- Capture output, check exit code
- Create attempt record with script output

### 3c. Template interpolation

Shared utility to resolve templates:
- `{{item_content}}` → file contents of the input file
- `{{item_stem}}` → filename without extension
- `{{output_path}}` → derived output path
- `{{file:path}}` → file contents (existing `context_from` mechanism)

## Phase 4: Frontend Changes

### 4a. Types (`ui/src/types/tasks.ts`)

Add to TaskDetailResponse:
```typescript
parent_task_id: string | null;
fan_out_index: number | null;
fan_out_input: string | null;
fan_out_output: string | null;
```

### 4b. Task display (`ui/src/components/detail/TaskDetailCard.tsx`)

- If task has children (is a fan-out parent): show child tasks as a grid/list
  of mini-cards, each showing status (building/verifying/completed/failed)
- Child tasks appear similar to attempts — show status icon, title (input filename),
  and expand to show attempt details
- Fan-out parent shows overall status + outer verifier feedback when applicable

### 4c. Script task display

- Show script output instead of agent output
- Simple pass/fail badge based on exit code

## Phase 5: Tests

### Backend tests
- Config validation: fan_out/script/task_context mutual exclusion
- Fan-out expansion: glob resolution, output path derivation, child task creation
- Child task lifecycle: inner retry with auto_verify, failure → parent failure
- Outer verification: re-run all children with feedback
- Script execution: exit 0 pass, non-zero fail
- Template interpolation: all {{...}} patterns
- Concurrency: max_concurrent respected

### Frontend tests
- Fan-out parent renders child task grid
- Child tasks show correct status badges
- Script task shows output

### Integration tests
- Full fan-out lifecycle with real files
- Script task lifecycle
- Fan-out with outer verification failure and re-run

## File Change Summary

| File | Change |
|------|--------|
| `src/orchestrator/config/models.py` | Add `FanOutConfig`, `TaskConfig.fan_out`, `TaskConfig.script` |
| `src/orchestrator/db/models.py` | Add fan-out columns to `TaskModel` |
| `src/orchestrator/state/models.py` | Add fan-out fields to `TaskState` |
| `src/orchestrator/config/enums.py` | Add `fan_out_running` to TaskStatus |
| `src/orchestrator/workflow/engine.py` | Fan-out expansion, child lifecycle, script execution |
| `src/orchestrator/runners/executor.py` | Fan-out agent spawning, script subprocess |
| `src/orchestrator/api/schemas/tasks.py` | Add fan-out fields to response |
| `src/orchestrator/api/routers/tasks.py` | Handle fan-out/script in task endpoints |
| `src/orchestrator/db/repositories.py` | Query/create child tasks |
| `ui/src/types/tasks.ts` | Add fan-out fields |
| `ui/src/components/detail/TaskDetailCard.tsx` | Fan-out parent/child display |
| Alembic migration | New columns on tasks table |
| Tests | Unit, integration, frontend |
