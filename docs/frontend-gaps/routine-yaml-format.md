# Frontend-Gaps Routine YAML Format Guide

Reference for editing `routines/frontend-gaps/routine.yaml`.

## Top-Level Structure

```yaml
id: frontend-gaps
name: Frontend Gaps Implementation
description: "..."
inputs:
  - name: feature_name
    required: false
    default: frontend-gaps
    description: Name of the feature being implemented
steps:
  - id: S-01
    title: "..."
    step_context: "..."
    tasks: [...]
    gate:
      type: auto_verify
      auto_verify:
        items:
          - id: tsc_check
            cmd: "cd ui && npx tsc --noEmit"
            must: true
```

## Required Fields

| Level   | Field          | Type   | Required | Notes                                    |
|---------|----------------|--------|----------|------------------------------------------|
| Root    | `id`           | string | Yes      | Kebab-case identifier                    |
| Root    | `name`         | string | Yes      | Human-readable name                      |
| Root    | `steps`        | array  | Yes      | At least one step                        |
| Root    | `description`  | string | No       | Free text                                |
| Root    | `inputs`       | array  | No       | Each: {name, required, default?, description} |
| Step    | `id`           | string | Yes      | e.g. "S-01"                              |
| Step    | `title`        | string | Yes      | Step title                               |
| Step    | `tasks`        | array  | Yes      | At least one task                        |
| Step    | `step_context` | string | No       | Describes the step goal                  |
| Step    | `gate`         | object | No       | Gate configuration                       |
| Task    | `id`           | string | Yes      | e.g. "T-01"                              |
| Task    | `title`        | string | Yes      | Task title                               |
| Task    | `task_context` | string | Yes      | **REQUIRED** — what the agent should do  |

## Task Optional Fields

- `requirements` — array of `{id, desc, priority}` where priority is `critical`, `expected`, or `nice`
- `artifacts` — array of `{path, required}`
- `auto_verify` — `{items: [{id, cmd, must}]}`
- `verifier` — `{rubric: [{id, text}], submission_template: {grade_scale, require_reason_if_below, require_remediation_if_below}}`
- `retry` — `{max_attempts: N}`
- `context_from` — array of `{artifact, as, required}`

## Gate Types

Valid `gate.type` values: `checklist`, `grade_threshold`, `human_approval`, `auto_verify`.

This routine uses `auto_verify` gates with `npx tsc --noEmit` on every step.

## Priority Values

Valid priority values: `critical`, `expected`, `nice`.

Do **not** use `nice_to_have` — the schema expects `nice`.

## Routine Layout

| Step | Title | Tasks | Gaps |
|------|-------|-------|------|
| S-01 | Step-Level Approval UI | T-01 to T-04 (4) | Gap 1 |
| S-02 | Branch Status + Back-Merge | T-05 to T-09 (5) | Gaps 2, 3 |
| S-03 | Merge Strategy + Clarification + Gate Types | T-10 to T-14 (5) | Gaps 4, 7, 8 |
| S-04 | Attempt Cost + Auto-Verify + Progress | T-15 to T-19 (5) | Gaps 5, 6, 9 |
| S-05 | History Page + Live Guidance | T-20 to T-23 (4) | Gaps 10, 11 |
| S-06 | Routine Detail + Agents Flow + Revision Viz | T-24 to T-26 (3) | Gaps 12, 13, 14 |
| S-07 | Grade Threshold + Blocked State + Elapsed Time | T-27 to T-31 (5) | Gaps 15, 16, 17 |
| S-08 | Validation + Env Files + Transitions + WebSocket | T-32 to T-39 (8) | Gaps 18–21 |

**Total: 39 tasks across 8 steps covering 21 gaps.**

## Validation

Always validate after editing:

```bash
uv run orchestrator --json routines validate routines/frontend-gaps/routine.yaml
```

Fix errors using the `loc` path and `msg` from the output.

## Common Mistakes

- Missing `task_context` on any task (required, not optional)
- Using `auto` instead of `auto_verify` for gate type
- Using `nice_to_have` instead of `nice` for priority
- Empty `tasks` list on a step
- Using unsupported fields like `schema_version`, `owner`, `tags`
