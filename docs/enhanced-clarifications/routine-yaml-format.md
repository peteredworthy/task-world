# Routine YAML Notes: enhanced-clarifications

Use this file while editing `routines/enhanced-clarifications/routine.yaml`.

## Schema Checklist

- [ ] Top-level `id`, `name`, `steps` present
- [ ] Every step has `id`, `title`, and non-empty `tasks`
- [ ] Every task has `id`, `title`, `task_context`
- [ ] Requirement objects use `id` + `desc`
- [ ] No unsupported inheritance keys (`ref`, `use`)

## Validation Command

```bash
uv run orchestrator --json routines validate routines/enhanced-clarifications/routine.yaml
```

## Last Validation Output

```json
{
  "valid": true,
  "id": "enhanced-clarifications",
  "name": "Enhanced Clarification System",
  "steps": 5,
  "inputs": 0
}
```

## Routine Structure Overview

```
routines/enhanced-clarifications/routine.yaml
  id: enhanced-clarifications
  name: Enhanced Clarification System
  steps:
    S-01: Data Model & MCP Tool
      T-01: Extend ClarificationQuestion and ClarificationAnswer domain models
      T-02: Update CLARIFICATION_TOOL inputSchema
      T-03: Mirror new fields in API schemas and update the router
      T-04: Write integration and unit tests for Step 1

    S-02: Prompt Changes & History Endpoint
      T-05: Update respond_to_clarification in workflow/service.py
      T-06: Update generate_builder_prompt in workflow/prompts.py
      T-07: Add repository method for clarification history
      T-08: Add ClarificationHistoryItem/Response schemas and history route
      T-09: Write integration and unit tests for prompt and history

    S-03: WebSocket Push
      T-10: Audit and update ClarificationRequested event dataclass
      T-11: Verify and add WebSocket broadcast for clarification events
      T-12: Write integration tests for WS clarification events

    S-04: Frontend – Question Types & Skip
      T-13: Extend TypeScript types in clarifications.ts
      T-14: Update QuestionCard to render all four question types
      T-15: Update ClarificationModal for multi-select state, validation, and skip flow

    S-05: Frontend – WebSocket Handler & History UI
      T-16: Add clarification event payload types to activity.ts
      T-17: Extend useWebSocket processEvent with clarification handlers
      T-18: Add useClarificationHistory query hook
      T-19: Create ClarificationHistoryCard component
      T-20: Wire ClarificationHistoryCard into the activity feed
```

## Step Dependencies

| Step | Depends On | Can Run Concurrently With |
|------|-----------|--------------------------|
| S-01 | (none)    | —                        |
| S-02 | S-01      | S-03, S-04               |
| S-03 | S-01      | S-02, S-04               |
| S-04 | S-01      | S-02, S-03               |
| S-05 | S-02, S-03, S-04 | —               |

## Source Documentation

This routine was generated from:
- `docs/enhanced-clarifications/steps/step-01.md` → S-01 (T-01..T-04)
- `docs/enhanced-clarifications/steps/step-02.md` → S-02 (T-05..T-09)
- `docs/enhanced-clarifications/steps/step-03.md` → S-03 (T-10..T-12)
- `docs/enhanced-clarifications/steps/step-04.md` → S-04 (T-13..T-15)
- `docs/enhanced-clarifications/steps/step-05.md` → S-05 (T-16..T-20)

All task_context fields reference the original step files for full implementation
guidance including exact code snippets.

## Edit Guidelines

When modifying `routine.yaml`:

1. **Adding a task**: Place it in the correct step, ensure it has `id`, `title`,
   and `task_context`. IDs must be unique across all steps (use `T-NN` format).

2. **Changing requirements**: Each requirement needs `id`, `desc`, and `priority`
   (one of: `critical`, `expected`, `nice_to_have`).

3. **Adding auto_verify**: Each item needs `id` and `cmd`. Set `must: true` only
   for commands that should block progression on failure.

4. **Adding a verifier**: Use `rubric` list with `id` and `text` per item.
   Optionally add `submission_template` with `grade_scale` for graded reviews.

5. **Retry**: Use `retry: {max_attempts: N}` to allow automatic reattempts.

6. **Step context**: Use `step_context` on steps to give the agent broader context
   about what the step accomplishes and its prerequisites.

## Common Validation Failures

- Missing `task_context` (REQUIRED on every task)
- Empty `tasks` list
- Wrong types (`tasks` as object instead of list)
- Unknown fields (`schema_version`, `owner`, `tags`, `critical`, `verify` are NOT valid)
- Duplicate IDs across steps/tasks
