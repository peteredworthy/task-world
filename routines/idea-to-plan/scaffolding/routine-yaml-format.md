# Routine YAML Notes: {{feature}}

Use this file while creating `routines/{{feature}}/routine.yaml`.

## Schema Checklist

- [ ] Top-level `id`, `name`, `steps` present
- [ ] Every step has `id`, `title`, and non-empty `tasks`
- [ ] Every task has `id`, `title`, `task_context`
- [ ] Requirement objects use `id` + `desc`
- [ ] No unsupported inheritance keys (`ref`, `use`)

## Validation Command

```bash
uv run orchestrator --json routines validate routines/{{feature}}/routine.yaml
```

## Last Validation Output

<!-- Paste the latest validation output here when debugging failures -->

