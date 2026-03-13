# Architecture: Configurable Phase Pipelines

## Current State

Every task implicitly follows a two-phase cycle: `BUILDING → VERIFYING`. This is hardcoded in the executor and engine — there is no explicit phase sequence on a task. The `TaskStatus` enum has dedicated `BUILDING` and `VERIFYING` values that map directly to these two phases. Verify failure always loops back to `BUILDING` (`retry_target` is effectively hardcoded to phase 0).

**Key files and their roles:**

| File | Role |
|------|------|
| `src/orchestrator/config/models.py` | `TaskConfig` — task shape in routine YAML; `task_context`, `verifier`, `script`, `auto_verify` define the current implicit phases |
| `src/orchestrator/config/enums.py` | `TaskStatus` (`BUILDING`, `VERIFYING`), `ModelProfile` — used for agent selection |
| `src/orchestrator/state/models.py` | `TaskState` — runtime state; `Attempt` tracks one builder/verifier cycle |
| `src/orchestrator/state/factory.py` | Creates `TaskState` from `TaskConfig` |
| `src/orchestrator/db/models.py` | `TaskModel` — persists task status, attempts |
| `src/orchestrator/workflow/engine.py` | `WorkflowEngine` — drives `BUILDING` → `VERIFYING` → complete/retry |
| `src/orchestrator/workflow/transitions.py` | `can_submit_for_verification()`, `evaluate_grades()` — phase gate logic |
| `src/orchestrator/workflow/prompts.py` | `build_builder_prompt()`, `build_verifier_prompt()` — two hardcoded prompt types |
| `src/orchestrator/workflow/events.py` | Event types for activity tracking |
| `src/orchestrator/runners/executor.py` | Spawns builder, then verifier; loops on revision |
| `src/orchestrator/api/schemas/tasks.py` | `TaskDetailResponse`, `PromptResponse` |
| `ui/src/types/tasks.ts` | Frontend task types |
| `ui/src/components/detail/TaskDetailCard.tsx` | Task detail card |
| `ui/src/components/dashboard/StepTimeline.tsx` | Step/task progress badges |

## Proposed Changes

### New Components

#### `PhaseType` enum — `src/orchestrator/config/enums.py`

```python
class PhaseType(str, Enum):
    BUILD = "build"
    VERIFY = "verify"
    PLAN = "plan"
    SUMMARIZE = "summarize"
    GAP_CHECK = "gap_check"
    SCRIPT = "script"
    AUTO_VERIFY = "auto_verify"
    HUMAN_REVIEW = "human_review"
```

#### `PhaseConfig` model — `src/orchestrator/config/models.py`

```python
class PhaseConfig(BaseModel):
    type: PhaseType
    prompt: str | None = None          # agent prompt override (replaces task_context for this phase)
    profile: ModelProfile | None = None  # agent profile override
    condition: str | None = None        # Jinja2-like condition; skip phase if false
    cmd: str | None = None             # shell command (script type only)
    retry_target: int | None = None    # verify type: phase index to loop to on failure

    @model_validator(mode="after")
    def _validate_retry_target(self) -> "PhaseConfig":
        # retry_target validated at TaskConfig level (needs phase list context)
        return self
```

`TaskConfig` addition:
```python
phases: list[PhaseConfig] | None = None
```

#### `PhaseStarted` and `PhaseCompleted` events — `src/orchestrator/workflow/events.py`

```python
class PhaseStarted(WorkflowEvent):
    task_id: str
    phase_index: int
    phase_type: str

class PhaseCompleted(WorkflowEvent):
    task_id: str
    phase_index: int
    phase_type: str
    output_length: int  # chars stored in phase_outputs
```

### Modified Components

#### `TaskState` — `src/orchestrator/state/models.py`

Add fields:
```python
current_phase_index: int = 0
phase_outputs: dict[int, str] = Field(default_factory=dict)
phases_config: list[PhaseConfig] | None = None
```

Add property (not stored, derived):
```python
@property
def current_phase_type(self) -> str | None:
    if self.phases_config and self.current_phase_index < len(self.phases_config):
        return self.phases_config[self.current_phase_index].type.value
    return None
```

#### `TaskModel` — `src/orchestrator/db/models.py` + Alembic migration

```python
current_phase_index: Mapped[int] = mapped_column(Integer, default=0)
phase_outputs: Mapped[dict[int, str]] = mapped_column(JSON, default=dict)
```

Migration: `alembic revision -m "add phase pipeline columns to tasks"` — existing rows default to `current_phase_index=0`, `phase_outputs={}`.

#### Phase synthesis — `src/orchestrator/state/factory.py`

```python
def _synthesize_phases(task_config: TaskConfig) -> list[PhaseConfig]:
    """Build phase list from legacy task fields when phases is not explicit."""
    if task_config.script:
        return [PhaseConfig(type=PhaseType.SCRIPT, cmd=task_config.script)]
    has_verifier = bool(task_config.verifier.rubric)
    has_auto_verify = bool(task_config.auto_verify.items)
    phases = [PhaseConfig(type=PhaseType.BUILD)]
    if has_verifier:
        phases.append(PhaseConfig(type=PhaseType.VERIFY))
    elif has_auto_verify:
        phases.append(PhaseConfig(type=PhaseType.AUTO_VERIFY))
    return phases
```

When creating `TaskState` from `TaskConfig`:
```python
phases_config = task_config.phases if task_config.phases else _synthesize_phases(task_config)
task_state.phases_config = phases_config
```

#### `WorkflowEngine` — `src/orchestrator/workflow/engine.py`

Two new methods:

```python
async def advance_phase(self, run_id: str, task_id: str) -> None:
    """Move task to the next phase, evaluating conditions and handling completion."""
    task = await self._get_task(run_id, task_id)
    next_index = task.current_phase_index + 1

    # Walk forward, skipping phases whose condition is false
    while next_index < len(task.phases_config):
        phase = task.phases_config[next_index]
        if phase.condition and not self._evaluate_condition(phase.condition, run):
            next_index += 1
            continue
        break

    if next_index >= len(task.phases_config):
        # All phases done → task complete
        await self._complete_task(run_id, task_id)
        return

    task.current_phase_index = next_index
    await self.service.persist_task(run_id, task)
    await self._emit(PhaseStarted(task_id=task_id, phase_index=next_index,
                                   phase_type=task.phases_config[next_index].type.value))

async def complete_phase(self, run_id: str, task_id: str, output: str) -> None:
    """Record phase output and advance to next phase."""
    task = await self._get_task(run_id, task_id)
    task.phase_outputs[task.current_phase_index] = output
    await self._emit(PhaseCompleted(task_id=task_id,
                                     phase_index=task.current_phase_index,
                                     phase_type=task.phases_config[task.current_phase_index].type.value,
                                     output_length=len(output)))
    await self.service.persist_task(run_id, task)
    await self.advance_phase(run_id, task_id)
```

Verify phase failure path (currently in `complete_verification`):
```python
# Before: always reset to BUILDING
# After:
verify_phase = task.phases_config[task.current_phase_index]
retry_index = verify_phase.retry_target
if retry_index is None:
    retry_index = task.current_phase_index - 1  # default: phase before verify
task.current_phase_index = retry_index
```

#### Phase-specific prompts — `src/orchestrator/workflow/prompts.py`

```python
def _format_prior_outputs(phase_outputs: dict[int, str], phases_config: list[PhaseConfig]) -> str:
    """Format prior phase outputs as context sections."""
    parts = []
    for idx, output in sorted(phase_outputs.items()):
        phase_name = phases_config[idx].type.value.title()
        parts.append(f"## {phase_name} Phase Output\n{output[:2000]}")
    return "\n\n".join(parts)

def build_plan_phase_prompt(task_config: TaskConfig, phase: PhaseConfig,
                             prior_outputs: dict[int, str], phases_config: list[PhaseConfig]) -> str:
    context = _format_prior_outputs(prior_outputs, phases_config)
    return f"""{phase.prompt or 'Design an approach for this task.'}

## Task Context
{task_config.task_context}

{context}

Produce a design document or plan as your output. This output will be available to subsequent phases.
"""

def build_summarize_phase_prompt(task_config: TaskConfig, phase: PhaseConfig,
                                  prior_outputs: dict[int, str], phases_config: list[PhaseConfig]) -> str:
    context = _format_prior_outputs(prior_outputs, phases_config)
    return f"""{phase.prompt or 'Summarize the work done in this task.'}

## Task Context
{task_config.task_context}

{context}
"""

def build_gap_check_phase_prompt(task_config: TaskConfig, phase: PhaseConfig,
                                  prior_outputs: dict[int, str], phases_config: list[PhaseConfig]) -> str:
    context = _format_prior_outputs(prior_outputs, phases_config)
    return f"""{phase.prompt or 'Review the build output and identify gaps before formal verification.'}

## Task Context
{task_config.task_context}

{context}

Identify any gaps, missing requirements, or quality issues. Your output will be included as context for the next phase.
"""
```

#### Executor — `src/orchestrator/runners/executor.py`

Phase dispatch loop replaces the hardcoded build/verify sequence:

```python
async def _run_task_phases(self, run_id, task, task_config, ...):
    phases = task.phases_config
    while task.current_phase_index < len(phases):
        phase = phases[task.current_phase_index]

        if phase.type in (PhaseType.BUILD, PhaseType.PLAN, PhaseType.SUMMARIZE, PhaseType.GAP_CHECK):
            # Agent phase: spawn builder/planner agent
            profile = phase.profile or task_config.profile
            prompt = _get_phase_prompt(task_config, phase, task.phase_outputs, phases)
            output = await self._spawn_agent(run_id, task, prompt, profile, ...)
            await self.service.complete_phase(run_id, task.id, output)

        elif phase.type == PhaseType.VERIFY:
            # Existing verifier flow (grades, checklist, etc.)
            await self._run_verify_phase(run_id, task, task_config, ...)
            # complete_phase called inside _run_verify_phase on pass

        elif phase.type == PhaseType.SCRIPT:
            exit_code, output = await self._run_script(phase.cmd, ...)
            if exit_code == 0:
                await self.service.complete_phase(run_id, task.id, output)
            else:
                await self._handle_script_failure(run_id, task, phase, output)

        elif phase.type == PhaseType.AUTO_VERIFY:
            results = await self._run_auto_verify(task_config.auto_verify, ...)
            if all(r["passed"] for r in results if r["must"]):
                await self.service.complete_phase(run_id, task.id, _format_av_results(results))
            else:
                await self._handle_auto_verify_failure(run_id, task, phase, results)

        elif phase.type == PhaseType.HUMAN_REVIEW:
            await self.service.transition_task(run_id, task.id, TaskStatus.PENDING_USER_ACTION)
            return  # executor exits; resumes when human submits

        # Refresh task state (advance_phase persisted the new index)
        task = await self.service.get_task(run_id, task.id)
```

#### API schema additions — `src/orchestrator/api/schemas/tasks.py`

```python
class TaskDetailResponse(BaseModel):
    # ... existing fields ...
    current_phase_index: int = 0
    current_phase_type: str | None = None
    phase_count: int = 0
    phase_outputs: dict[int, str] = Field(default_factory=dict)

class PromptResponse(BaseModel):
    # ... existing fields ...
    phase_type: str | None = None  # "build", "verify", "plan", etc.
```

### Status Mapping

To maintain backward compatibility, `TaskStatus` values are preserved. Phase types map to status:

| Phase Type | `TaskStatus` | Notes |
|------------|-------------|-------|
| `build` | `BUILDING` | unchanged |
| `plan` | `BUILDING` | planning is an agent phase like building |
| `summarize` | `BUILDING` | summarization is an agent phase |
| `gap_check` | `BUILDING` | gap check is an agent phase |
| `verify` | `VERIFYING` | unchanged |
| `script` | `BUILDING` | script runs like a build step |
| `auto_verify` | `VERIFYING` | auto-verify is a verification step |
| `human_review` | `PENDING_USER_ACTION` | unchanged |

The `current_phase_type` field on `TaskDetailResponse` provides the fine-grained type for UI display.

### Interaction Diagram

```
TaskConfig.phases set?
  │
  ├─ YES → use as-is → copy to phases_config
  │
  └─ NO → factory synthesizes phases_config:
            script?         → [script]
            task_context + rubric → [build, verify]
            task_context + auto_verify → [build, auto_verify]
            task_context only → [build]  (no verification)

Executor phase loop:
  current_phase_index = 0
  │
  ├─ phase.type == plan/build/summarize/gap_check
  │     spawn agent → output
  │     complete_phase(output) → phase_outputs[idx] = output → advance_phase
  │
  ├─ phase.type == verify
  │     spawn verifier → grades
  │     pass → complete_phase → advance_phase
  │     fail → current_phase_index = retry_target (or idx-1)
  │
  ├─ phase.type == script
  │     run cmd
  │     exit 0 → complete_phase → advance_phase
  │     exit N → handle failure (retry or fail task)
  │
  ├─ phase.type == auto_verify
  │     run AutoVerifyRunner
  │     all must pass → complete_phase → advance_phase
  │     any fail → handle failure
  │
  └─ phase.type == human_review
        → PENDING_USER_ACTION (pause)
        → on human resume → complete_phase → advance_phase

advance_phase:
  next_index++
  while condition false: next_index++
  if next_index >= len(phases): task COMPLETED
  else: emit PhaseStarted, persist
```

### Frontend Phase Indicator

New component (or inline in `TaskDetailCard.tsx`):

```
[Plan ✓] → [Build ●] → [Verify ○]
  solid      pulsing     dimmed
  checkmark  green       outline
```

Phase badge classes by type:
- `plan`: blue (`bg-blue-500`)
- `build`: green (`bg-green-500`)
- `verify`: purple (`bg-purple-500`)
- `summarize`: cyan (`bg-cyan-500`)
- `gap_check`: amber (`bg-amber-500`)
- `script`: gray (`bg-gray-500`)
- `auto_verify`: teal (`bg-teal-500`)
- `human_review`: orange (`bg-orange-500`)

## Technology Choices

| Choice | Option Selected | Alternatives Considered | Rationale |
|--------|----------------|------------------------|-----------|
| `TaskStatus` enum | Keep unchanged | Add `PHASE_ACTIVE` generic status | Zero DB migration; API consumers unaffected |
| Phase synthesis location | `state/factory.py` | `config/models.py` validator | Factory already maps config → state; keeps models lean |
| Phase context passing | `phase_outputs: dict[int, str]` | Artifact files on disk | In-memory/DB storage is simpler; artifacts already tracked separately |
| Condition evaluation | Reuse conditional-steps evaluator | New expression parser | Already implemented (Option C); consistent behavior |
| `retry_target` default | `current_phase_index - 1` | Always loop to phase 0 | Matches current behavior; more flexible for multi-build pipelines |
| Frontend phase state | Derive from `current_phase_index` + `phase_count` | Server-sent state enum | Less state to serialize; purely derived from existing fields |

## Testing Strategy

### Unit Tests — `tests/unit/`

**Config models** (`tests/unit/test_phase_config.py`):
- `PhaseConfig` with all 8 `PhaseType` values — valid
- `PhaseConfig.cmd` required for `script` type
- `retry_target` must reference a valid earlier phase index
- `TaskConfig.phases` co-exists with `task_context`, `verifier`, `auto_verify`
- `TaskConfig.phases` is mutually exclusive with `fan_out`

**Phase synthesis** (`tests/unit/test_phase_synthesis.py`):
- `task_context + rubric` → `[build, verify]`
- `task_context + auto_verify items, no rubric` → `[build, auto_verify]`
- `script set` → `[script(cmd=...)]`
- Explicit `phases` on config → passed through unchanged
- `has_verification=True` when phases include verify or auto_verify

**Engine phase logic** (`tests/unit/test_phase_engine.py`):
- `advance_phase`: increments index, emits `PhaseStarted`
- `advance_phase` with false condition: skips to next phase
- `advance_phase` at last phase: calls `_complete_task`
- `complete_phase`: stores output, emits `PhaseCompleted`, calls `advance_phase`
- Verify failure with `retry_target=1`: `current_phase_index` set to 1
- Verify failure with no `retry_target`: `current_phase_index` set to `current - 1`
- Resume: `start_task` at `current_phase_index=2` starts phase 2 not phase 0

### Integration Tests — `tests/integration/`

**Phase pipeline flows** (`tests/integration/test_phase_pipelines.py`):
- Task with `phases: [plan, build, verify]` completes all three phases; plan output is in build prompt
- Script-only task (`phases: [script]`, `cmd` exit 0) → task COMPLETED
- Script-only task (`cmd` exit 1) → task FAILED (or loops to retry if retry_target set)
- `auto_verify` phase after build: all must items pass → task COMPLETED; any fail → task retries
- Conditional phase (`condition: false`) is skipped; task advances to next phase
- Verify `retry_target: 1` failure → task goes to phase 1, not phase 0
- `human_review` phase → task enters PENDING_USER_ACTION; resumes and advances on human callback

**Backward compatibility** (`tests/integration/test_phase_pipelines.py`):
- Existing task YAML without `phases` field: synthesized pipeline runs identically to current behavior
- Routine with `script` field (no `phases`) runs as single script phase

**Regression** (existing test suites):
- All existing `tests/integration/` tests pass without modification

**API surface**:
- GET task response includes `current_phase_index`, `current_phase_type`, `phase_count`, `phase_outputs`
- `PromptResponse` includes `phase_type`

### Frontend Tests — `ui/src/`

**Phase indicator** (`ui/src/__tests__/PhaseIndicator.test.tsx`):
- Renders all phases in correct order
- Completed phases have checkmark and solid background
- Active phase has pulsing class and correct color for type
- Pending phases have dimmed/outline class
- Conditional phases with condition=false shown as dashed + dimmed

**Activity feed** (additions to existing test file):
- `PhaseStarted` event renders with phase type and index
- `PhaseCompleted` event renders with "→ Phase N+1"

**TaskDetailCard** (additions to existing test file):
- Phase outputs section renders prior output text in collapsible
- Phase indicator appears at top of card when `phase_count > 1`

## Security & Performance Considerations

### Security
- **Script phase**: `phase.cmd` comes from routine YAML, authored by the routine creator — same trust level as `auto_verify.cmd`. No user-supplied shell commands from agents. Existing `AutoVerifyItemConfig` pipe rejection validator should be applied to `PhaseConfig.cmd` too.
- **Phase outputs in prompts**: phase outputs are stored as text and injected into subsequent prompts. No code execution of output content; same trust model as existing `task_context` injection.
- **Condition evaluation**: reuses existing conditional-steps evaluator which handles variable substitution safely.

### Performance
- **Phase dispatch loop**: synchronous advancement; no parallelism between phases within a task (phases are sequential by design).
- **Phase outputs stored in DB**: JSON column on `TaskModel`; total size bounded by task's phases and output lengths. Truncation in prompt injection (2000 chars/phase) prevents prompt overflow.
- **DB migration**: two new columns with defaults; existing rows need no backfill; safe additive migration.
- **Frontend rendering**: phase indicator is a simple static component; no additional API calls needed (data already in `TaskDetailResponse`).
