# Architecture: Gap Analyzer + Targeted Retry

## Current State

Steps complete when all their tasks reach terminal state (`check_step_progression()` in `transitions.py`). There is no mechanism for post-step integration verification. Tasks are verified individually; two tasks that each pass can leave integration gaps that are never caught.

**Key files and their roles:**

| File | Role |
|------|------|
| `src/orchestrator/config/models.py` | `StepConfig` — defines step shape in routine YAML |
| `src/orchestrator/config/enums.py` | Enums for statuses, priorities, verdict types |
| `src/orchestrator/state/models.py` | `StepState`, `TaskState` — runtime state |
| `src/orchestrator/db/models.py` | `StepModel` — persistent storage |
| `src/orchestrator/workflow/transitions.py` | `check_step_progression()` — decides when to advance |
| `src/orchestrator/workflow/engine.py` | `WorkflowEngine` — orchestrates state transitions |
| `src/orchestrator/workflow/service.py` | `WorkflowService` — persistence + engine wrapper |
| `src/orchestrator/workflow/prompts.py` | Prompt generation for builders and verifiers |
| `src/orchestrator/workflow/events.py` | Event types for activity tracking |
| `src/orchestrator/runners/executor.py` | Agent spawning loop |
| `src/orchestrator/api/schemas/runs.py` | `StepSummary` — API response shape |
| `ui/src/components/dashboard/StepTimeline.tsx` | Step timeline rendering |
| `ui/src/lib/stepTimelineUtils.ts` | Step state classification and badge classes |

## Proposed Changes

### New Components

#### `StepVerifierConfig` — added to `src/orchestrator/config/models.py`

```python
class StepVerifierConfig(BaseModel):
    prompt: str
    max_iterations: int = 3
    auto_verify: AutoVerifyConfig | None = None
```

`StepConfig` gains:
```python
step_verifier: StepVerifierConfig | None = None
```

Steps without `step_verifier` are unaffected — the conditional step path added earlier (`skipped`, `condition`) is independent.

#### `StepVerdict` enum — added to `src/orchestrator/config/enums.py`

```python
class StepVerdict(str, Enum):
    PASS = "pass"
    RETRY = "retry"
    FIX = "fix"
    FAIL = "fail"
```

#### `GapAction` and `GapReport` — added to `src/orchestrator/state/models.py`

```python
class GapAction(BaseModel):
    type: Literal["retry_task", "spawn_fix", "pass", "fail"]
    task_id: str | None = None          # for retry_task
    feedback: str | None = None         # for retry_task
    title: str | None = None            # for spawn_fix
    context: str | None = None          # for spawn_fix
    requirements: list[RequirementConfig] | None = None  # for spawn_fix

class GapReport(BaseModel):
    id: str = Field(default_factory=generate_id)
    iteration: int
    assessment: str
    verdict: StepVerdict
    actions: list[GapAction] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_utc_now)
```

The verifier LLM must output JSON matching `GapReport` (minus `id` and `timestamp`, which are set by the engine).

#### New event types — added to `src/orchestrator/workflow/events.py`

```python
class StepVerificationStarted(WorkflowEvent):
    step_id: str
    iteration: int
    max_iterations: int

class GapReportGenerated(WorkflowEvent):
    step_id: str
    iteration: int
    assessment: str
    verdict: str
    action_count: int

class StepVerificationCompleted(WorkflowEvent):
    step_id: str
    total_iterations: int
    final_verdict: str
```

### Modified Components

#### `StepState` — `src/orchestrator/state/models.py`

Add fields:
```python
verifying: bool = False
verifier_iterations: int = 0
gap_reports: list[GapReport] = Field(default_factory=list)
```

#### `StepModel` — `src/orchestrator/db/models.py`

Add columns via Alembic migration:
```python
verifying: Mapped[bool] = mapped_column(Integer, default=0)
gap_reports: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
```

Migration: `alembic revision -m "add step_verifier columns"` — existing rows default to `verifying=False`, `gap_reports=[]`.

#### `check_step_progression()` — `src/orchestrator/workflow/transitions.py`

Current flow: all tasks terminal → mark step completed → advance `current_step_index`.

New flow:
1. (Unchanged) Check if all tasks in current step are terminal.
2. If all terminal **and** step has `step_verifier` **and** `step.verifying == False`:
   - Signal the engine to call `start_step_verification()` instead of completing.
   - Do NOT advance `current_step_index` yet.
3. If all terminal **and** no `step_verifier` (or `step.verifying == True` awaiting re-check after actions):
   - Proceed with existing completion path.

The `verifying == True` flag suppresses re-triggering verification while the loop is in progress. It is cleared by `complete_step_verification()` when verdict is `pass` or `fail`.

**Important:** The fan-out parent verification path in the executor is a separate code path and must remain untouched. The new condition applies to `step_verifier`-configured steps only.

#### `WorkflowEngine` — `src/orchestrator/workflow/engine.py`

Two new methods:

```python
async def start_step_verification(self, run_id: str, step_id: str) -> None:
    """Mark the step as verifying, increment iteration counter, emit event."""

async def complete_step_verification(
    self, run_id: str, step_id: str, gap_report: GapReport
) -> None:
    """Append gap report, dispatch actions, emit events."""
```

**`complete_step_verification` action dispatch logic:**

```
if verifier_iterations >= max_iterations:
    → pause run with reason "step_verifier_max_iterations"

elif verdict == PASS:
    → clear verifying flag
    → emit StepVerificationCompleted
    → call existing step completion path (same as no-verifier case)

elif verdict == FAIL:
    → clear verifying flag
    → emit StepVerificationCompleted
    → pause run with reason "step_verifier_failed"

elif verdict in (RETRY, FIX):
    for each action:
        if type == retry_task:
            if task.status != COMPLETED: skip (cannot retry non-completed tasks)
            if task.current_attempt >= task.max_attempts: treat whole report as FAIL
            reset task to PENDING, prepend feedback to next builder prompt
        if type == spawn_fix:
            create TaskState(title=..., requirements=..., spawned_by_gap_report=True)
            add to step.tasks
            persist
    # verifying stays True; executor waits for all tasks to re-terminal
```

#### Step verifier prompt — `src/orchestrator/workflow/prompts.py`

New function `build_step_verifier_prompt(step_config, step_state, auto_verify_results)`:

```
{step_verifier.prompt}

## Step Context
{step_config.step_context}

## Task Outcomes
For each task in step:
  ### {task.config_id}: {task.title}
  Status: {task.status}
  Last attempt outcome: {last_attempt.outcome}
  Grades: {grade_snapshot}
  Auto-verify results: {last_attempt.auto_verify_results}

## Step Auto-Verify Results
{auto_verify_results}

## Required Output
You MUST respond with a JSON object matching this schema:
{
  "assessment": "<string>",
  "verdict": "pass" | "retry" | "fix" | "fail",
  "actions": [
    // for retry_task:
    {"type": "retry_task", "task_id": "<id>", "feedback": "<string>"},
    // for spawn_fix:
    {"type": "spawn_fix", "title": "<string>", "context": "<string>",
     "requirements": [{"id": "R1", "desc": "<string>", "priority": "critical"}]}
  ]
}
Respond with JSON only. No markdown fences, no preamble.
```

#### Executor — `src/orchestrator/runners/executor.py`

After the inner task execution loop (where each task gets a builder/verifier cycle):

```python
# After all tasks in step reach terminal state:
if step_config.step_verifier:
    await service.start_step_verification(run_id, step.id)

    # Run step auto_verify if configured
    auto_verify_results = []
    if step_config.step_verifier.auto_verify:
        auto_verify_results = await run_auto_verify(
            step_config.step_verifier.auto_verify, ...
        )

    # Build prompt and spawn verifier agent
    prompt = build_step_verifier_prompt(step_config, step_state, auto_verify_results)
    output = await spawn_agent(prompt, ...)

    # Parse JSON output
    try:
        raw = json.loads(extract_json(output))
        gap_report = GapReport(iteration=step_state.verifier_iterations, ...)
    except (json.JSONDecodeError, ValidationError):
        gap_report = GapReport(verdict=StepVerdict.FAIL, assessment="Parse error", ...)

    await service.complete_step_verification(run_id, step.id, gap_report)

    # If retry/fix actions were dispatched, the task execution loop runs again
    # for tasks that are now PENDING; this is handled by the existing executor loop
```

The existing executor task loop already re-checks task statuses; tasks reset to PENDING by `retry_task` or newly created by `spawn_fix` will be picked up automatically in the next iteration.

#### `StepSummary` — `src/orchestrator/api/schemas/runs.py`

Add fields:
```python
verifying: bool = False
verifier_iterations: int = 0
gap_reports: list[GapReportSchema] = Field(default_factory=list)
```

`GapReportSchema` mirrors `GapReport` (Pydantic model for JSON serialization).

### Interaction Diagram

```
Executor task loop                    Engine                    Transitions
──────────────────                    ──────                    ───────────
All tasks terminal
  │
  ├─ step_verifier configured?
  │     YES
  │     │
  │     ├─ run step auto_verify
  │     ├─ spawn verifier agent
  │     ├─ parse JSON → GapReport
  │     └─ complete_step_verification(gap_report)
  │           │
  │           ├─ verdict=PASS → step.verifying=False → complete step
  │           ├─ verdict=FAIL → pause run
  │           ├─ iterations >= max → pause run
  │           └─ verdict=RETRY/FIX
  │                 ├─ retry_task → reset task to PENDING
  │                 └─ spawn_fix  → add new TaskState (PENDING)
  │                       │
  │                       └─ task loop resumes ──────────────→ tasks run
  │                                                            all terminal
  │                                                               │
  │                                                            back to top ↑
  │
  NO (no step_verifier)
  │
  └─ check_step_progression() → advance current_step_index
```

## Technology Choices

| Choice | Option Selected | Alternatives Considered | Rationale |
|--------|----------------|------------------------|-----------|
| `spawn_fix` implementation | Bespoke minimal (create `TaskState` directly) | Wait for Option D | Option D not implemented; `max_iterations` provides sufficient guard |
| JSON parsing strategy | `json.loads` + `GapReport` validation, fall back to FAIL | Prompt engineering only | Hard parse failure is recoverable (run pauses); silent corruption is not |
| Verifier agent type | Same as step's configured agent | Dedicated verifier-only agent type | Consistent with task verifier pattern; avoids new agent type |
| State during loop | `verifying: bool` flag | New step status enum value | Simpler; avoids DB enum migration; `verifying` + `completed` together describe all states |
| Fan-out interaction | Leave existing path untouched | Migrate fan-out to use step verifier | Reduces risk; migration can happen later |

## Testing Strategy

### Unit Tests — `tests/unit/`

**Gap report and models** (`tests/unit/test_gap_analyzer_models.py`):
- `GapReport` validation: valid JSON → model, missing fields → error
- `GapAction` with all four types
- `StepVerifierConfig` defaults
- `StepVerdict` values

**Engine lifecycle** (`tests/unit/test_engine.py` additions or `tests/unit/test_gap_analyzer_engine.py`):
- `start_step_verification` sets `verifying=True`, increments `verifier_iterations`, emits event
- `complete_step_verification` with `pass` → step completes, `verifying=False`
- `complete_step_verification` with `fail` → run paused
- `complete_step_verification` with `retry_task` → target task reset to PENDING
- `complete_step_verification` with `retry_task` on non-COMPLETED task → rejected
- `complete_step_verification` with `spawn_fix` → new task in step
- `verifier_iterations >= max_iterations` → auto-fail regardless of verdict
- Two-pass iteration: retry → tasks complete → pass → step completes

### Integration Tests — `tests/integration/`

**Step verification flow** (`tests/integration/test_gap_analyzer.py`):
- Routine with `step_verifier`: tasks complete → verifier runs → `pass` → step advances
- Verifier returns `retry_task` → task re-runs → verifier runs again → `pass`
- Verifier returns `spawn_fix` → new task created and run → verifier runs again → `pass`
- Verifier returns `fail` → run paused with `step_verifier_failed` reason
- `max_iterations` reached → run paused
- Verifier output is invalid JSON → run paused
- GET run response includes `verifying`, `gap_reports` on step summary

**Regression** (additions to existing tests):
- Steps without `step_verifier` advance normally (no regression)

### Frontend Tests — `ui/src/`

**StepTimeline** (additions to existing test file):
- Step with `verifying=true` renders pulsing purple badge
- Verifying badge shows iteration counter ("Verifying 2/3")

**Gap report display** (`ui/src/components/__tests__/GapReport.test.tsx` or similar):
- Assessment text shown
- Verdict badge color: green/amber/red per verdict
- Action list renders type, task ID, feedback

**Fix-up tasks**:
- Task with `spawned_by_gap_report=true` renders with "Fix-up" badge and dashed border

## Security & Performance Considerations

### Security

- **No arbitrary code execution** — The step verifier output is parsed as JSON and validated against `GapReport` schema. Invalid output causes a `fail` verdict, not code execution.
- **`spawn_fix` requirements** — `requirements` from gap actions are treated as routine config, not executed directly. They go through the normal task builder/verifier pipeline.
- **`retry_task` guard** — Only COMPLETED tasks can be retried. This prevents retrying actively running or already-failed tasks.

### Performance

- **Verifier only runs after all tasks are terminal** — No concurrency concern; the executor's task loop has a natural synchronization point.
- **`max_iterations` bounds the loop** — Default of 3 iterations maximum. In the worst case, a step runs 3 verification cycles before the engine gives up.
- **JSON parsing is O(output_length)** — Negligible overhead.
- **`spawn_fix` tasks** — Added to the DB immediately; no deferred writes that could be lost on restart.
- **DB migration** — Two new columns with defaults; existing rows need no backfill.
