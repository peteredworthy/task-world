# Option C: Conditional Steps + Optional Step Wiring

## Idea

Add the ability for steps in a routine to be conditionally skipped, conditionally executed, or repeated over a list of items. Currently, every step in a routine always executes in sequence. This makes routines rigid — a bug-fix routine must include the same steps for a trivial typo fix as for a complex architectural issue.

## What to Build

### 1. Step Conditions (`condition` field on StepConfig)

Steps gain an optional `condition` block that controls whether the step runs:

```yaml
steps:
  - id: S-02
    title: "Design solution"
    condition:
      when: "{{complexity}} == 'high'"
    tasks: [...]
```

When the engine advances to a step with a condition, it evaluates the expression. If false, the step is marked as `skipped` and the engine advances to the next step.

### 2. Condition Types

- **Variable-based**: `when: "{{complexity}} == 'high'"` — evaluates against run config variables and task output variables
- **Output-based**: `when: "steps.S-01.has_failures"` — checks results from previous steps (has_failures, all_passed, any_completed)
- **Always/never**: `when: "always"` (default) or `when: "never"` (useful for temporarily disabling a step)
- **Manual gate**: `when: "manual"` — pauses the run and asks the user whether to execute this step

### 3. Step-Level Repeat (`repeat_for`)

A step can repeat for each item in a list:

```yaml
steps:
  - id: S-03
    title: "Fix bug"
    condition:
      repeat_for: "{{bug_ids}}"
    tasks: [...]
```

When `repeat_for` is specified, the engine creates N copies of the step (one per item). Each copy gets `{{item}}` and `{{item_index}}` in scope for template substitution. This is like fan-out but at the step level — each iteration goes through the full step lifecycle including verification.

### 4. Skip Tracking

- `StepState` gets a `skipped: bool` field (default false) and a `skip_reason: str | None` field
- Skipped steps are persisted in the DB with a new column
- Activity events are emitted for step skips

## Codebase Context

This is the task-world orchestrator project. Key files:

- **Config models**: `src/orchestrator/config/models.py` — `StepConfig` needs a new `condition` field. Create a `StepCondition` pydantic model with `when: str | None` and `repeat_for: str | None`.
- **Enums**: `src/orchestrator/config/enums.py` — No new enums needed, but may want a `StepStatus` or similar.
- **State models**: `src/orchestrator/state/models.py` — `StepState` needs `skipped: bool = False` and `skip_reason: str | None = None`.
- **DB models**: `src/orchestrator/db/models.py` — `StepModel` needs `skipped` column and `skip_reason` column.
- **Workflow transitions**: `src/orchestrator/workflow/transitions.py` — `check_step_progression()` needs to handle skipping. When advancing to the next step, check its condition. If false, skip and advance again.
- **Workflow engine**: `src/orchestrator/workflow/engine.py` — The `start_run` and step advancement code needs condition evaluation. Create a `ConditionEvaluator` that safely evaluates expressions against run variables.
- **Factory**: `src/orchestrator/state/factory.py` — `create_run_from_routine()` may need to handle repeat_for expansion at run creation time (create N step copies).
- **Prompts**: `src/orchestrator/workflow/prompts.py` — Variable resolution already exists via `{{variable}}` syntax. Ensure repeat_for variables (`item`, `item_index`) are available.
- **Events**: `src/orchestrator/workflow/events.py` — Add a `StepSkipped` event type.
- **API schemas**: `src/orchestrator/api/schemas/runs.py` — `StepSummary` needs skipped/skip_reason fields.
- **API routers**: `src/orchestrator/api/routers/runs.py` — Step data in run responses needs to include skip info.

### Frontend Changes

- **Step timeline** (`ui/src/components/dashboard/StepTimeline.tsx`): Skipped steps should render with a dashed border and dimmed opacity. The `getStepState()` function in `stepTimelineUtils.ts` needs a new `'skipped'` state. Add corresponding `stepBadgeClasses` entry with dashed border.
- **Step timeline tooltip**: Show skip reason on hover for skipped steps.
- **Run detail** (`ui/src/pages/RunDetail.tsx`): Skipped steps should be visible but clearly de-emphasized. If a step has `condition.when` that hasn't been evaluated yet, show the condition text (e.g., "if critical").
- **Types** (`ui/src/types/runs.ts`): `StepSummary` needs `skipped: boolean` and `skip_reason: string | null`. For conditional steps, add `condition?: { when?: string; repeat_for?: string }`.
- **Activity feed** (`ui/src/components/detail/ActivityFeed.tsx`): Show step skip events in the timeline.
- **Repeat-for display**: When a step uses repeat_for, show the iterations as sub-items under the step badge (similar to how fan-out children are shown under a parent task).

### Condition Evaluator Safety

The condition evaluator must be safe — no arbitrary code execution. Use a restricted expression parser that supports:
- String comparison: `==`, `!=`
- Membership: `in`, `not in`
- Boolean: `and`, `or`, `not`
- Variable access: `{{variable}}`, `steps.S-XX.has_failures`
- Literals: strings, numbers, booleans, lists

Do NOT use Python's `eval()`. Use a simple recursive descent parser or an existing safe expression library.

## Relationship to Other Planned Work

This is Option C from the orchestration architecture research (see `docs/presentations/orchestration-directions.html`). It is independent of Options A (Phase Pipelines), B (Gap Analyzer), and D (Orchestrated Expansion). It should be implemented first as it has the highest value-to-effort ratio.

## Tests

- Unit tests for the condition evaluator (various expression types, edge cases, safety)
- Unit tests for step skipping in transitions.py
- Integration tests for conditional step runs via API
- Integration test for repeat_for expansion
- Frontend tests for skipped step display in StepTimeline
