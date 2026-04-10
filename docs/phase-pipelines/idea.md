# Option A: Configurable Phase Pipelines

## Idea

Replace the hardcoded builder→verifier two-phase cycle with a configurable per-task phase sequence. Currently every task follows BUILDING → VERIFYING. This means you can't have a planning phase before building, a summarization phase after, a gap-check phase between build and verify, or tasks that only have a single phase (script-only, or verify-only for reviewing external work).

The insight is that "builder" and "verifier" are just phase types. The current system is a special case where every task implicitly has `phases: [build, verify]`. Making this explicit opens up arbitrary phase chains without adding new hierarchy levels.

## What to Build

### 1. Phase Configuration

Tasks gain an optional `phases` list. If omitted, defaults to `[build, verify]` for backward compatibility:

```yaml
tasks:
  - id: T-01
    title: "Implement auth module"
    phases:
      - type: plan
        profile: ARCHITECT
        prompt: "Design the auth approach. Output a design.md file."
      - type: build
        # uses task_context as prompt (existing behavior)
      - type: verify
        # uses verifier rubric (existing behavior)
      - type: summarize
        profile: SUMMARIZER
        prompt: "Write a changelog entry for the auth module."

  - id: T-02
    title: "Run migrations"
    phases:
      - type: script
        cmd: "uv run alembic upgrade head"
      - type: auto-verify
        # runs auto_verify items and completes if all pass
```

### 2. Phase Types

- **build**: The standard builder phase. Uses `task_context` as prompt. Agent implements requirements and marks checklist items done. Ends with submit_for_verification callback.
- **verify**: The standard verifier phase. Uses verifier rubric. Agent grades requirements. Can loop back to a previous phase on failure.
- **plan**: A planning/design phase. Agent produces a design document or plan. Output is passed as context to subsequent phases. No checklist interaction — just produces an artifact.
- **summarize**: A summarization phase. Agent reads all prior phase outputs and produces a summary. Runs after build/verify are complete.
- **gap-check**: Agent reviews build output and identifies gaps before formal verification. Can produce targeted feedback that goes to a subsequent build phase (like a lightweight pre-verification).
- **script**: Runs a shell command. No agent involved. Pass/fail based on exit code. Like auto_verify but as a first-class phase.
- **auto-verify**: Runs the task's auto_verify items. No agent. Passes if all must items pass. Can be placed anywhere in the pipeline.
- **human-review**: Pauses and waits for human input. Like the existing PENDING_USER_ACTION but as an explicit phase.

### 3. Phase State Machine

Each task tracks `current_phase_index: int = 0`. The engine advances through phases:

1. Start at phase 0
2. Execute phase (spawn agent for agent-phases, run command for script-phases)
3. Phase completes → advance to next phase
4. If verify phase fails and `retry_target` is set, loop back to that phase index
5. If final phase completes → task COMPLETED

Transitions within a task:
- Forward: phase N → phase N+1 (normal progression)
- Backward: verify phase → earlier phase (on grade failure, like current revision loop)
- Skip: optional phase skipped (condition not met)

### 4. Phase Context Passing

Each phase's output is available to subsequent phases:
- Plan phase produces `design.md` → build phase prompt includes "Design from planning phase: ..."
- Build phase produces code → verify phase sees the code (existing behavior)
- Gap-check produces feedback → next build phase includes the feedback

Context is passed via a `phase_outputs: dict[int, str]` on the task state, keyed by phase index.

### 5. Optional/Conditional Phases

A phase can have a `condition` (like step conditions from Option C):

```yaml
phases:
  - type: plan
    condition: "{{complexity}} == 'high'"
  - type: build
  - type: verify
```

If the condition is false, the phase is skipped and the engine advances to the next one.

### 6. Verify Phase Retry Target

Currently, verify failure always loops back to BUILDING. With phases, the verify phase specifies where to loop:

```yaml
phases:
  - type: plan       # index 0
  - type: build      # index 1
  - type: verify     # index 2
    retry_target: 1  # loop back to build phase on failure
```

If `retry_target` is omitted, default behavior is to loop to the phase immediately before the verify phase.

## Codebase Context

This is the most architecturally impactful option. Key files:

- **Config models** (`src/orchestrator/config/models.py`):
  - Create `PhaseConfig` model: `type: PhaseType`, `prompt: str | None`, `profile: str | None`, `condition: str | None`, `cmd: str | None` (for script type), `retry_target: int | None` (for verify type).
  - Create `PhaseType` enum or string literal: `build`, `verify`, `plan`, `summarize`, `gap_check`, `script`, `auto_verify`, `human_review`.
  - Add `phases: list[PhaseConfig] | None = None` to `TaskConfig`. If None, synthesize `[build, verify]` from existing task_context/verifier fields.
  - Backward compatibility: tasks without `phases` field continue to work exactly as before.

- **Enums** (`src/orchestrator/config/enums.py`):
  - Add `PhaseType` enum.
  - `TaskStatus` enum needs rethinking. Currently has `BUILDING`, `VERIFYING` etc. With phases, the status should indicate which phase is active. Two approaches:
    1. Keep existing statuses and map phase types to them (plan → BUILDING, summarize → BUILDING, etc.)
    2. Add a generic `PHASE_ACTIVE` status and track phase type separately.
  - Recommend approach 1 for backward compatibility — map agent-based phases to BUILDING, verification phases to VERIFYING. Add `current_phase_type` field for detailed tracking.

- **State models** (`src/orchestrator/state/models.py`):
  - Add to `TaskState`: `current_phase_index: int = 0`, `phase_outputs: dict[int, str] = {}`, `phases_config: list[PhaseConfig] | None = None` (copied from task config at creation time).
  - The `phases_config` is stored on state so the engine can walk it without re-reading the routine config.

- **DB models** (`src/orchestrator/db/models.py`):
  - Add `current_phase_index` int column to `TaskModel`.
  - Add `phase_outputs` JSON column to `TaskModel`.

- **Workflow engine** (`src/orchestrator/workflow/engine.py`):
  - The core change: `submit_for_verification()` and `complete_verification()` become phase-generic.
  - `advance_phase(run_id, task_id)`: Moves to the next phase. Checks conditions, handles skip.
  - `complete_phase(run_id, task_id, output)`: Records phase output, triggers advance.
  - `start_task()`: Starts the first phase (or the retry_target phase on revision).
  - Verify phase failure: instead of always going to BUILDING, goes to the `retry_target` phase index.
  - Terminal phase completion triggers existing `check_step_progression`.

- **Workflow transitions** (`src/orchestrator/workflow/transitions.py`):
  - Generalize `can_submit_for_verification()` to `can_complete_phase()`.
  - Generalize `evaluate_grades()` to work for any verify-type phase.

- **Prompts** (`src/orchestrator/workflow/prompts.py`):
  - Each phase type has its own prompt template.
  - Plan phase: system prompt for planning, user prompt with task context and codebase context.
  - Build phase: existing builder prompt (unchanged).
  - Verify phase: existing verifier prompt (unchanged).
  - Summarize phase: system prompt for summarization, user prompt with all prior phase outputs.
  - Gap-check phase: system prompt for gap analysis, user prompt with build output.
  - Phase outputs from prior phases are included in subsequent phase prompts as context.

- **Executor** (`src/orchestrator/runners/executor.py`):
  - Phase-aware dispatching: for agent phases (plan, build, verify, summarize, gap_check), spawn the appropriate agent. For script phases, run the command. For auto_verify phases, run the auto_verify items. For human_review phases, transition to PENDING_USER_ACTION.
  - Agent profile selection: each phase can specify a `profile` override. Plan uses ARCHITECT, build uses CODER, etc.

- **Factory** (`src/orchestrator/state/factory.py`):
  - When creating TaskState from TaskConfig: if `phases` is set, copy to `phases_config`. If not, synthesize from existing fields:
    - Has `task_context` + has `verifier` → `[build, verify]`
    - Has `task_context` + no `verifier` + has `auto_verify` → `[build, auto_verify]`
    - Has `script` → `[script]`

- **Events** (`src/orchestrator/workflow/events.py`):
  - Add `PhaseCompleted`, `PhaseStarted` event types with phase_type and phase_index.

- **API schemas** (`src/orchestrator/api/schemas/tasks.py`):
  - Add `current_phase_index`, `current_phase_type`, `phase_count`, `phase_outputs` to `TaskDetailResponse`.
  - Add `PromptResponse.phase_type` (currently has `phase` as "building"/"verifying").

### Frontend Changes

- **Task status display**: Currently shows "Building" or "Verifying" based on task status. With phases, show the current phase type: "Planning", "Building", "Verifying", "Summarizing", etc. The `TaskStatus` type in `ui/src/types/enums.ts` may need phase-aware display logic.

- **Phase progress indicator** (new component): Show a horizontal chain of phase badges within the task detail card. Similar to the step timeline but for phases within a task:
  - Each phase shows: type icon/letter, name, status (completed/active/pending)
  - Completed phases: solid background, checkmark
  - Active phase: pulsing indicator, colored by type (green=build, purple=verify, blue=plan, cyan=summarize)
  - Pending phases: dimmed, outline only
  - Conditional phases that will be skipped: dashed + dimmed

- **Task detail card** (`ui/src/components/detail/TaskDetailCard.tsx`):
  - Add phase progress indicator at the top of the task detail
  - Show current phase context/output in the attempt section
  - Phase outputs section: collapsible list of prior phase outputs (e.g., plan output, gap-check feedback)

- **Step timeline** (`ui/src/components/dashboard/StepTimeline.tsx`):
  - Below each active task in the step badge tooltip, show mini phase dots (colored by phase type) to indicate phase progress within the task.

- **Activity feed** (`ui/src/components/detail/ActivityFeed.tsx`):
  - Phase start/complete events in the timeline
  - Show phase type transitions (e.g., "Plan phase completed → Build phase started")

- **Types** (`ui/src/types/tasks.ts`):
  - Add `current_phase_index: number`, `phase_count: number`, `current_phase_type: string`, `phase_outputs: Record<number, string>` to `TaskDetailResponse`.
  - Add `PhaseType` string literal type.

- **Prompt display**: When viewing a task's prompt (in attempt details), show which phase the prompt was for.

### Migration Strategy

This is a significant engine change. The migration path:

1. Add `PhaseConfig` and `phases` field to TaskConfig (optional, defaults to None)
2. When `phases` is None, the engine follows the existing code path (BUILDING → VERIFYING). Zero behavior change for existing routines.
3. When `phases` is set, the engine follows the new phase-aware path.
4. Existing routines work without modification. New routines can opt into phases.
5. Over time, the old code path can be removed and all tasks use the phases system (the synthesized `[build, verify]` default).

## Relationship to Other Options

- **After Options C and D**: Can stack with both. Expanded tasks (D) can specify custom phases. Conditional steps (C) are independent.
- **Independent of Option B**: Step verifier operates at step level, phases operate at task level. They don't interact directly.
- **Enhances Option D**: When a builder uses the expansion API to create a subtask, it can specify a custom phase list for that subtask (e.g., `phases: [plan, build, verify]` for a complex subtask vs `phases: [build, auto_verify]` for a simple one).

## Tests

- Unit tests for PhaseConfig validation (valid types, retry_target bounds)
- Unit tests for phase synthesis from existing task fields
- Unit tests for phase advancement logic (forward, backward, skip)
- Unit tests for phase context passing
- Integration tests for tasks with custom phase pipelines
- Integration test for plan → build → verify chain
- Integration test for script-only task
- Integration test for verify phase retry_target (loop to specific earlier phase)
- Integration test for conditional phase skipping
- Integration test for backward compatibility (tasks without phases field)
- Frontend tests for phase progress indicator
- Frontend tests for phase-aware status display
