# Routine YAML Format Guide

Use this guide when generating `routines/<feature>/routine.yaml`.

## 1. Top-Level Shape

Valid files can be either wrapped or unwrapped:

```yaml
routine:
  id: "my-routine"
  name: "My Routine"
  description: "..."
  inputs: []
  steps: []
```

or

```yaml
id: "my-routine"
name: "My Routine"
description: "..."
inputs: []
steps: []
```

## 2. Required Fields

- `id` (string): unique routine id, kebab-case recommended.
- `name` (string): human-readable name.
- `steps` (array): at least one step.

## 3. Step Shape

Each step must include:

- `id` (string)
- `title` (string)
- `tasks` (array with at least one task)

Optional on steps:

- `step_context` (string)
- `type` (`standard` or `dry_run`)
- `gate` (for human approval)
- `dry_run` (required when `type: dry_run`)
- `transitions`

Example:

```yaml
- id: "S-01"
  title: "Setup"
  step_context: "Initialize project files"
  tasks:
    - id: "T-01"
      title: "Create files"
      task_context: "Create base project files"
      requirements:
        - id: "R1"
          desc: "Files are created"
          priority: critical
```

## 4. Task Shape

Each task must include:

- `id` (string)
- `title` (string)
- `task_context` (string)

Optional:

- `requirements`
- `artifacts`
- `context_from`
- `auto_verify`
- `verifier`
- `retry`
- `model_overrides`

## 5. Common Validation Failures

- Missing required keys (`id`, `name`, `steps`, `tasks`, `task_context`).
- Wrong type (e.g., `tasks` as object instead of list).
- Empty `tasks` list.
- Using unsupported inheritance keys (`ref`, `use`).
- Invalid gate or step type values.

## 6. Validate Before Submission

Run this command and fix all errors:

```bash
uv run orchestrator --json routines validate routines/<feature>/routine.yaml
```

If invalid, use reported `loc` and `msg` to patch exact fields.

## 7. Builder Feedback Loop

When validation auto-checks fail during a run:

- The task returns to `BUILDING`.
- Auto-verify failures are included in next builder prompt feedback.
- Update `routine.yaml` and re-run validation until it passes.
