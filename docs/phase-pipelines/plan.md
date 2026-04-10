# Plan: Configurable Phase Pipelines

## Overview

Implement phase pipelines in five milestones: (1) config models and enums, (2) state, DB, and factory, (3) engine and transitions, (4) executor, prompts, and API surface, (5) frontend. Each milestone delivers independently testable functionality. Backward compatibility is maintained throughout — the old `build → verify` path continues to work until the synthesized phases path fully replaces it.

## Milestones

### M1: Config Models + Enums

**Goal:** Define all new types so the rest of the system can reference them without touching the engine or executor.

**Deliverables:**
- `PhaseType` enum in `src/orchestrator/config/enums.py`: `build`, `verify`, `plan`, `summarize`, `gap_check`, `script`, `auto_verify`, `human_review`
- `PhaseConfig` Pydantic model in `src/orchestrator/config/models.py`:
  ```python
  class PhaseConfig(BaseModel):
      type: PhaseType
      prompt: str | None = None          # override for agent phases
      profile: ModelProfile | None = None  # agent profile override
      condition: str | None = None        # skip condition
      cmd: str | None = None             # for script type only
      retry_target: int | None = None    # for verify type: phase index to loop to on failure
  ```
- `phases: list[PhaseConfig] | None = None` added to `TaskConfig`
- Validator on `TaskConfig`: `phases` is mutually exclusive with `fan_out`; `phases` may co-exist with `task_context`, `verifier`, `auto_verify`, `script` (these remain for backward compat synthesis)
- Unit tests: `PhaseConfig` field validation, `PhaseType` values, `retry_target` bounds check (must be < phase index of verify phase), `phases` on `TaskConfig`

**Verification:** `uv run pytest tests/unit/ -v` passes, `uv run pyright` clean, existing tests unaffected.

### M2: State, DB, and Factory

**Goal:** Thread phase state through the runtime models and persistence layer.

**Deliverables:**
- `TaskState` additions in `src/orchestrator/state/models.py`:
  ```python
  current_phase_index: int = 0
  phase_outputs: dict[int, str] = Field(default_factory=dict)
  phases_config: list[PhaseConfig] | None = None
  ```
- `current_phase_type` property on `TaskState`: returns `phases_config[current_phase_index].type` if `phases_config` is set, else derives from `status` (backward compat)
- Alembic migration: add `current_phase_index` (Integer, default 0) and `phase_outputs` (JSON, default `{}`) to `tasks` table
- Phase synthesis in `src/orchestrator/state/factory.py`:
  - `task_context` is non-empty + `verifier` has rubric items → synthesize `[PhaseConfig(type=build), PhaseConfig(type=verify)]`
  - `task_context` is non-empty + no verifier rubric + `auto_verify` items → synthesize `[PhaseConfig(type=build), PhaseConfig(type=auto_verify)]`
  - `task_context` is non-empty + no verifier rubric + no `auto_verify` items → synthesize `[PhaseConfig(type=build)]` (build only, no verification)
  - `script` is set → synthesize `[PhaseConfig(type=script, cmd=task.script)]`
  - `phases` is explicitly set on `TaskConfig` → use as-is (copy to `phases_config`)
- `PhaseStarted` and `PhaseCompleted` event types in `src/orchestrator/workflow/events.py`:
  ```python
  class PhaseStarted(WorkflowEvent):
      task_id: str
      phase_index: int
      phase_type: str

  class PhaseCompleted(WorkflowEvent):
      task_id: str
      phase_index: int
      phase_type: str
      output_length: int
  ```
- Unit tests: synthesis for each case, `TaskState` fields populated correctly, DB migration tested against in-memory SQLite

**Verification:** `uv run pytest tests/unit/ -v` passes, Alembic migration applies cleanly.

### M3: Engine + Transitions

**Goal:** Wire phase advancement into the workflow engine so the state machine drives phase progression.

**Deliverables:**
- `advance_phase(run_id, task_id)` on `WorkflowEngine`:
  - Increments `current_phase_index`
  - Evaluates `condition` of next phase (reuse conditional-steps evaluation); skips if false
  - If no more phases → call existing task completion path
  - Emits `PhaseStarted` for the new phase
- `complete_phase(run_id, task_id, output: str)` on `WorkflowEngine`:
  - Stores `output` in `phase_outputs[current_phase_index]`
  - Emits `PhaseCompleted`
  - Calls `advance_phase`
- Verify phase failure → instead of hardcoded return to `BUILDING`, use `retry_target` from `PhaseConfig` (default: phase immediately before the verify phase)
- `start_task()` uses `current_phase_index` (supports resuming mid-pipeline after server reload)
- `WorkflowService`: persist/load `current_phase_index` and `phase_outputs` from `TaskModel`
- Unit tests:
  - `advance_phase` emits `PhaseStarted`, increments index
  - `complete_phase` stores output and calls advance
  - Condition evaluation: true → advance, false → skip to next
  - Verify failure with `retry_target=1` → jumps to phase 1 not phase 0
  - Final phase complete → task COMPLETED
  - Resume: `start_task` starts at `current_phase_index` not 0 when index > 0

**Verification:** `uv run pytest tests/unit/ tests/integration/ -v` passes.

### M4: Executor, Prompts, and API Surface

**Goal:** Connect executor to phase dispatch, generate phase-type-specific prompts, and expose phase state through the API.

**Deliverables:**
- Phase dispatch in `src/orchestrator/runners/executor.py`:
  - Agent phases (`plan`, `build`, `verify`, `summarize`, `gap_check`) → spawn agent with `phase.profile` override if set, pass phase-specific prompt
  - `script` phase → run `phase.cmd` via subprocess; exit 0 → `complete_phase("")`; non-zero → phase failure (loop to `retry_target` or fail task)
  - `auto_verify` phase → run `AutoVerifyRunner` against task's `auto_verify` config; all `must` items pass → `complete_phase(results_summary)`; any fail → phase failure
  - `human_review` phase → transition task to `PENDING_USER_ACTION`; wait for human callback; on resume → `complete_phase("")`
- Phase-specific prompts in `src/orchestrator/workflow/prompts.py`:
  - `build_plan_phase_prompt(task_config, phase_config, prior_outputs)` — design/planning task
  - `build_summarize_phase_prompt(task_config, phase_config, prior_outputs)` — summarize all prior outputs
  - `build_gap_check_phase_prompt(task_config, phase_config, prior_outputs)` — review build output for gaps
  - All phases inject `prior_outputs` as context sections (e.g. "Plan phase output:", "Build phase output:")
  - Existing `build_builder_prompt` and `build_verifier_prompt` unchanged; called for `build`/`verify` phase types
- API schema additions:
  - `TaskDetailResponse` in `src/orchestrator/api/schemas/tasks.py`: add `current_phase_index: int`, `current_phase_type: str | None`, `phase_count: int`, `phase_outputs: dict[int, str]`
  - `PromptResponse`: add `phase_type: str | None`
  - Populate in `get_task` response serialization
- Integration tests:
  - Task with `phases: [plan, build, verify]` → plan runs, output stored, build gets plan context, verify runs
  - Script-only task (`phases: [script]`) → command runs, exit 0 → task completes
  - `auto_verify` phase after `build` → all items pass → task completes
  - Verify `retry_target` → failure loops to correct phase index
  - Conditional phase: condition false → phase skipped, task advances
  - Backward compat: task without `phases` field → synthesized pipeline behaves identically to today
  - GET task response includes `current_phase_index`, `current_phase_type`, `phase_outputs`

**Verification:** `uv run pytest tests/integration/ -v` passes, API returns correct phase data.

### M5: Frontend

**Goal:** Render phase progress and phase-type context in the UI.

**Deliverables:**
- `ui/src/types/tasks.ts`: add `current_phase_index: number`, `phase_count: number`, `current_phase_type: string | null`, `phase_outputs: Record<number, string>` to `TaskDetailResponse`; add `PhaseType` string literal type
- Phase progress indicator component (new, or inline in `TaskDetailCard.tsx`):
  - Horizontal chain of phase badges: type icon/name, status (completed=solid+checkmark, active=pulsing+colored, pending=dimmed+outline)
  - Colors by type: build=green, verify=purple, plan=blue, summarize=cyan, gap_check=amber, script=gray, auto_verify=teal, human_review=orange
  - Conditional/skipped phases: dashed + dimmed
- `ui/src/components/detail/TaskDetailCard.tsx`:
  - Phase indicator at top of task detail
  - Phase outputs section: collapsible list of prior phase outputs
- `ui/src/components/dashboard/StepTimeline.tsx`:
  - Mini phase dots below active task badges in step tooltip
  - Dots colored by phase type, current phase pulsing
- `ui/src/components/detail/ActivityFeed.tsx`:
  - `PhaseStarted` event: "Phase N started: {type}"
  - `PhaseCompleted` event: "Phase N completed: {type} → Phase N+1"
- Frontend tests:
  - Phase indicator renders all phases with correct states
  - Active phase has pulsing class
  - Completed phase has checkmark
  - Phase outputs section renders prior output text
  - ActivityFeed renders `PhaseStarted`/`PhaseCompleted` events

**Verification:** `npx vitest run` passes, TypeScript clean, ESLint clean.

## Implementation Order

### Step 1: Config Models (M1)
**Prerequisites:** None.
**Deliverables:** `PhaseType` enum, `PhaseConfig` model, `phases` on `TaskConfig`, unit tests.

### Step 2: State, DB, Factory (M2)
**Prerequisites:** Step 1 (PhaseConfig defined).
**Deliverables:** `TaskState` fields, Alembic migration, synthesis logic, event types, unit tests.

### Step 3: Engine Lifecycle (M3)
**Prerequisites:** Steps 1-2 (models and state exist).
**Deliverables:** `advance_phase`, `complete_phase`, verify retry_target, persistence, unit tests.

### Step 4: Executor + Prompts + API (M4)
**Prerequisites:** Step 3 (engine methods working).
**Deliverables:** Phase dispatch in executor, phase prompts, API schema additions, integration tests.

### Step 5: Frontend (M5)
**Prerequisites:** Step 4 (API returns phase data).
**Deliverables:** All frontend changes — types, phase indicator, activity feed, mini dots, tests.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| `TaskStatus` enum | Keep existing values; add `current_phase_type` for detail | Avoid DB enum migration; API consumers relying on BUILDING/VERIFYING continue working |
| Backward compat approach | Synthesize phases in factory; engine uses phases_config always | Single code path after synthesis; no if/else branches in engine |
| `retry_target` default | Phase immediately before the verify phase | Matches current behavior (always retries the build phase) |
| Phase output storage | `phase_outputs: dict[int, str]` on TaskState + JSON in DB | Keyed by index; survives phase skips; simple to inject into prompts |
| Condition evaluation | Reuse existing conditional-steps evaluator from Option C | Already implemented; consistent behavior; no new DSL |
| Script phase failure | Fail task (or loop to `retry_target` if set) | Explicit; no silent pass-through on non-zero exit |
| `human_review` phase | Transition to PENDING_USER_ACTION; resume on human callback | Reuses existing pending_action infrastructure |

## Risks and Unknowns

| Risk | Mitigation |
|------|------------|
| Synthesis produces wrong default for tasks with both `task_context` and `script` | Existing validator already rejects this combination; synthesis never sees it |
| `retry_target` pointing past the verify phase index | Add validator: `retry_target` must be < current phase index |
| Phase prompt context too large (many prior outputs) | Truncate each output to 2000 chars in prompt builder; full text in `phase_outputs` for API display |
| `human_review` phase + server restart | `current_phase_index` persisted in DB; server reload restores task at correct phase |
| Fan-out tasks getting `phases_config` | Fan-out uses separate executor path; skip phase synthesis for fan-out tasks (no phases) |
| Frontend fast-refresh errors if component/utility boundary crossed | Follow existing pattern: utilities in separate `.ts` files, components in `.tsx` |

## References

- [idea.md](idea.md) — Full feature specification
- `src/orchestrator/config/models.py` — `TaskConfig`, `AutoVerifyConfig`
- `src/orchestrator/config/enums.py` — `TaskStatus`, `ModelProfile`, `PhaseType` (new)
- `src/orchestrator/state/models.py` — `TaskState`, `Attempt`
- `src/orchestrator/state/factory.py` — task state creation from config
- `src/orchestrator/db/models.py` — `TaskModel`
- `src/orchestrator/workflow/engine.py` — `WorkflowEngine`
- `src/orchestrator/workflow/service.py` — `WorkflowService`
- `src/orchestrator/workflow/transitions.py` — `can_submit_for_verification()`
- `src/orchestrator/workflow/prompts.py` — prompt generation
- `src/orchestrator/workflow/events.py` — event types
- `src/orchestrator/runners/executor.py` — agent spawning loop
- `src/orchestrator/api/schemas/tasks.py` — `TaskDetailResponse`, `PromptResponse`
- `ui/src/types/tasks.ts` — frontend task types
- `ui/src/components/detail/TaskDetailCard.tsx` — task detail rendering
- `ui/src/components/dashboard/StepTimeline.tsx` — step/task badges
