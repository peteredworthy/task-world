# Architecture: Conditional Step Execution

## Current State

Steps execute unconditionally in sequence. The workflow engine advances `current_step_index` through `check_step_progression()` in `transitions.py` when all tasks in the current step reach terminal status. Steps have no concept of being skipped or repeated.

**Key files and their roles:**

| File | Role |
|------|------|
| `src/orchestrator/config/models.py` | `StepConfig` — defines step shape in routine YAML |
| `src/orchestrator/state/models.py` | `StepState` — runtime state during execution |
| `src/orchestrator/db/models.py` | `StepModel` — persistent storage |
| `src/orchestrator/workflow/transitions.py` | `check_step_progression()` — decides when to advance |
| `src/orchestrator/workflow/engine.py` | `WorkflowEngine` — orchestrates state transitions |
| `src/orchestrator/state/factory.py` | `create_run_from_routine()` — builds Run from RoutineConfig |
| `src/orchestrator/workflow/events.py` | Event types for activity tracking |
| `src/orchestrator/api/schemas/runs.py` | `StepSummary` — API response shape |
| `ui/src/components/dashboard/StepTimeline.tsx` | Step timeline rendering |
| `ui/src/lib/stepTimelineUtils.ts` | Step state classification and badge classes |

## Proposed Changes

### New Components

#### `ConditionEvaluator` — `src/orchestrator/workflow/condition_evaluator.py`

Safe expression evaluator using recursive descent parsing. No external dependencies.

**Interface:**
```python
class ConditionEvaluator:
    def evaluate(
        self,
        expression: str,
        variables: dict[str, Any],
        step_outcomes: dict[str, StepOutcome],
    ) -> bool | None:
        """
        Returns True (execute), False (skip), or None (manual gate, needs user input).
        Raises ConditionEvalError for malformed expressions.
        """
```

**Supported grammar:**
```
expr     → or_expr
or_expr  → and_expr ("or" and_expr)*
and_expr → not_expr ("and" not_expr)*
not_expr → "not" not_expr | compare
compare  → primary (("==" | "!=" | "in" | "not" "in") primary)?
primary  → STRING | NUMBER | BOOL | LIST | VARIABLE | "(" expr ")"
```

**Variable resolution:**
- `{{var_name}}` → looks up in `variables` dict (populated from run config + repeat-for item)
- `steps.S-XX.has_failures` → looks up in `step_outcomes` dict, returns boolean
- `steps.S-XX.all_passed` / `steps.S-XX.any_completed` → similar outcome queries
- `steps.S-XX.completed` → whether the step finished (regardless of pass/fail)
- `steps.S-XX.skipped` → whether the step was skipped
- `always` → returns `True`
- `never` → returns `False`
- `manual` → returns `None` (signals manual gate)

**Safety constraints:**
- Maximum expression length: 500 characters
- Maximum parse depth: 10 levels
- No attribute access beyond `steps.{id}.{property}`
- No function calls
- Unknown variables resolve to empty string (falsy)

**Error handling:**
- Malformed expressions raise `ConditionEvalError`
- The engine responds to `ConditionEvalError` by pausing the run with the error details, allowing the user to fix the routine

#### `StepCondition` — added to `src/orchestrator/config/models.py`

```python
class StepCondition(BaseModel):
    when: str | None = None        # Expression to evaluate
    repeat_for: str | None = None  # Variable name containing list to iterate
```

#### `StepOutcome` — added to `src/orchestrator/workflow/condition_evaluator.py`

```python
class StepOutcome(BaseModel):
    has_failures: bool
    all_passed: bool
    any_completed: bool
    completed: bool    # Step finished executing (regardless of pass/fail)
    skipped: bool      # Step was skipped by condition evaluation
```

Built from `StepState` by checking task statuses and skip fields.

#### `StepSkipped` event — added to `src/orchestrator/workflow/events.py`

```python
class StepSkipped(BaseModel):
    step_index: int
    step_id: str
    condition: str
    reason: str
```

### Modified Components

#### `StepConfig` — `src/orchestrator/config/models.py`

Add field:
```python
condition: StepCondition | None = None
```

No change to existing fields. Steps without `condition` behave as before.

#### `StepState` — `src/orchestrator/state/models.py`

Add fields:
```python
skipped: bool = False
skip_reason: str | None = None
```

#### `StepModel` — `src/orchestrator/db/models.py`

Add columns via Alembic migration:
```python
skipped = Column(Boolean, default=False, nullable=False)
skip_reason = Column(String, nullable=True)
```

Migration: `alembic revision -m "add step skipped and skip_reason columns"` — defaults ensure existing rows are valid.

#### `check_step_progression()` — `src/orchestrator/workflow/transitions.py`

Current flow:
1. Check if current step's tasks are all terminal → mark completed
2. If completed and no failures → advance `current_step_index`

New flow:
1. (Unchanged) Check current step completion
2. When advancing to next step, evaluate its `condition.when`:
   - `True` or no condition → proceed normally (start tasks)
   - `False` → set `skipped=True`, `skip_reason`, advance to next step (loop)
   - `None` (manual) → return a signal to pause the run
   - `ConditionEvalError` raised → return a signal to pause the run with error details
3. Handle chain-skipping: loop continues until finding a non-skipped step or reaching the end
4. If the next step has `repeat_for`, perform runtime expansion before condition evaluation (see below)

The function needs access to run config variables and step outcomes, which are already available on the `Run` object.

#### Runtime Repeat-For Expansion — `src/orchestrator/workflow/engine.py`

**This happens at runtime, not at run creation.** When the engine reaches a step with `condition.repeat_for`:

1. Resolve the variable name to a list from the run context:
   - First check run config variables (provided at creation)
   - Then check prior step outputs (enables dynamic lists from earlier steps)
   - If the variable doesn't resolve to a list, pause the run with an error
2. For each item, create a `StepState` copy with:
   - ID: `{original_id}-{index}` (e.g., `S-03-0`, `S-03-1`)
   - Title: `{original_title} [{index + 1}/{count}]`
   - Extra variables: `item` = current item, `item_index` = index
3. Replace the single step with N copies in the run's step list
4. Persist the expanded steps to DB immediately
5. If the list is empty, create a single skipped step
6. If the step also has a `when` condition: evaluate `when` per copy after expansion. No agent/LLM work starts until a copy's `when` passes. This is purely programmatic evaluation.

**Key difference from static expansion:** Because expansion happens at runtime, `repeat_for` can reference outputs from prior steps (e.g., a list of files discovered by step 1). This is more powerful but requires the engine to handle step list mutations mid-run.

#### Manual Gate — Resume with Skip Option

When a run is paused at a manual gate (`when: "manual"`):
- **Execute** (existing resume): `POST /runs/{id}/resume` continues execution of the gated step
- **Skip** (new endpoint): `POST /runs/{id}/steps/{step_id}/skip` marks the step as skipped and advances to the next step

The frontend shows both options when paused at a manual gate. This ensures users aren't forced to execute a gated step — they can skip it if it's not needed for this particular run.

#### `create_run_from_routine()` — `src/orchestrator/state/factory.py`

Minimal changes: `repeat_for` expansion no longer happens here. The factory creates steps as-is from the routine config, preserving `condition` fields. Expansion is deferred to the engine at runtime.

#### `StepSummary` — `src/orchestrator/api/schemas/runs.py`

Add fields:
```python
skipped: bool = False
skip_reason: str | None = None
condition: StepConditionSchema | None = None  # shows the original condition for UI display
```

#### `WorkflowService` — persistence layer

Ensure `skipped` and `skip_reason` are saved to and loaded from `StepModel`.

### Interactions

```
Routine YAML                    Run Creation                    Execution
─────────────                   ────────────                    ─────────
StepConfig                      create_run_from_routine()       check_step_progression()
  condition:                      │                               │
    when: "{{x}} == 'y'"         │ preserve condition             │ advance to step
    repeat_for: "{{ids}}"        │ as-is (no expansion)          │   │
                                  │                               │   ▼
                                  ▼                               │ has repeat_for?
                                StepState (with condition)       │   │
                                                                  yes  no
                                                                  │    │
                                                            resolve list  has when?
                                                            from context    │
                                                                  │      no  yes
                                                            expand N      │   │
                                                            copies        ▼   ▼
                                                                  │   execute evaluate
                                                            eval when  normally    │
                                                            per copy        ┌───┴───┐
                                                                  │       true  false  None
                                                                  │         │    │      │
                                                                  ▼      execute skip  pause
                                                            per-copy         │  (manual)
                                                            execute/     advance
                                                            skip         to next
```

## Technology Choices

| Choice | Option Selected | Alternatives Considered | Rationale |
|--------|----------------|------------------------|-----------|
| Expression parser | Custom recursive descent | `ast.literal_eval`, `simpleeval` library, regex-based | No external deps; full control over allowed syntax; auditable security surface; `simpleeval` allows more than needed |
| Expansion timing | Runtime (engine reaches step) | Static (at run creation) | Enables prior step outputs as list sources; user explicitly chose power over simplicity |
| repeat_for + when combo | Expand first, evaluate per copy | Evaluate first then expand; disallow combo | Programmatic-only: no LLM work until condition passes; matches user expectation |
| Skip storage | Dedicated DB columns | JSON blob in existing column | Queryable; type-safe; simple migration |
| Manual gate | Reuse `pause_run()` + skip option | New state machine state; resume-only | Avoids new transitions; skip option gives users flexibility to execute or skip |
| Condition syntax errors | Pause run with error | Skip step; execute anyway | Safest: lets user fix the routine; chosen by user |
| Step outcome properties | 5 properties (has_failures, all_passed, any_completed, completed, skipped) | 3 properties (without completed/skipped) | `completed` and `skipped` enable richer conditions; chosen by user |

## Testing Strategy

### Unit Tests — `tests/unit/`

**Condition evaluator** (`tests/unit/test_condition_evaluator.py`):
- String comparison: `"foo" == "foo"` → True, `"foo" != "bar"` → True
- Variable substitution: `{{complexity}} == 'high'` with `{"complexity": "high"}` → True
- Output-based: `steps.S-01.has_failures` with matching outcome → correct boolean
- Output-based: `steps.S-01.completed` and `steps.S-01.skipped` → correct booleans
- Boolean operators: `and`, `or`, `not`, operator precedence
- Membership: `"a" in ["a", "b"]` → True
- Literals: `always` → True, `never` → False, `manual` → None
- Edge cases: empty expression, unknown variable (falsy), deeply nested parens
- Safety: expressions > 500 chars rejected, attribute traversal beyond allowed rejected, no code execution
- Syntax errors: malformed expressions raise `ConditionEvalError`

**Step skipping in transitions** (`tests/unit/test_transitions.py` additions):
- Step with false condition is skipped and marked with reason
- Chain-skip: multiple consecutive false conditions skip all, land on first true
- All steps skipped: run completes with no work
- Step with no condition: unchanged behavior
- Output-based condition references completed step outcomes correctly (including `completed` and `skipped` properties)
- Condition syntax error → run is paused with error details

**Runtime repeat-for expansion** (`tests/unit/test_engine.py` additions):
- List from run config → N step copies with `item` and `item_index`
- List from prior step output → N step copies (runtime resolution)
- Empty list → skipped step
- Variable not found → run paused with error
- repeat_for + when combo → expand first, evaluate `when` per copy

### Integration Tests — `tests/integration/`

**Conditional execution** (`tests/integration/test_conditional_steps.py`):
- Create routine with conditional step, provide config that makes condition true → step executes
- Same routine, config makes condition false → step skipped, next step starts
- Manual gate condition → run pauses, resume executes step
- Manual gate condition → run pauses, skip-step skips and advances
- Output-based condition: step 2 condition references step 1 failure state
- Condition syntax error → run paused with error, not crashed
- repeat_for with run config list → N step copies created, each executes independently
- repeat_for with prior step output list → N step copies created at runtime

**API surface** (additions to `tests/integration/test_api_full_lifecycle.py`):
- GET run response includes `skipped`, `skip_reason`, `condition` on steps
- Skipped steps have `StepSkipped` event in activity
- Skip-step endpoint works for manual gate paused runs

### Frontend Tests — `ui/src/`

**StepTimeline** (additions to existing test file):
- Skipped step renders with dashed border class
- Skipped step shows skip reason in tooltip
- Pending conditional step shows condition text
- repeat_for iterations render as sub-items
- Manual gate shows execute and skip buttons

## Security & Performance Considerations

### Security

- **No `eval()`** — The condition evaluator uses a hand-written parser. There is no path from user-supplied expressions to arbitrary code execution.
- **Input limits** — Expression length capped at 500 characters; parse depth capped at 10 levels. Prevents resource exhaustion from pathological input.
- **Allowlisted attribute access** — Only `steps.{id}.{property}` where property is one of `has_failures`, `all_passed`, `any_completed`, `completed`, `skipped`. No arbitrary attribute traversal.
- **Variable injection** — `repeat_for` variables (`item`, `item_index`) are injected per-step copy at expansion time. No cross-contamination between iterations.

### Performance

- **Condition evaluation is O(expression_length)** — Single pass parse + evaluate. No backtracking. Negligible compared to agent execution time.
- **Runtime repeat-for expansion is O(N × tasks_per_step)** — Happens once when the engine reaches the step. For reasonable list sizes (< 100 items), this is fast. Expansion is persisted immediately to avoid re-expansion on restart.
- **No extra DB queries** — Skip state is loaded with the step (already part of the joined query). No N+1 problem.
- **Chain-skip is bounded** — Maximum iterations = number of steps in the routine. No infinite loop risk.
- **Step list mutation** — Runtime expansion mutates the step list mid-run. The engine must persist the expanded list atomically to prevent inconsistency on restart.
