# Routine & Step-File YAML Format

Reference for editing `routines/{feature}/routine.yaml` and the per-step YAML
files in `routines/{feature}/steps/`. The schema is enforced by
`RoutineConfig` in `src/orchestrator/config/models.py`; validate after every
edit.

## Validation command

```bash
uv run orchestrator --json routines validate routines/{feature}/routine.yaml
```

A step file can be parse-checked alone with
`python -c 'import yaml; yaml.safe_load(open("routines/{feature}/steps/step-01-plan.yaml"))'`,
but only the full routine validation proves schema correctness.

## Routine header (`routine.yaml`)

- Top level may be wrapped in a `routine:` root key (preferred, matches `/routines`).
- Required: `id` (kebab-case), `name`, `steps`.
- Optional: `description`, `inputs` (each: `name`, `required`, `description`),
  `env_files`, `auto_verify` defaults.
- In the yaml-steps style, each entry in `steps:` is a thin stub that references
  a step file instead of inlining content:

```yaml
steps:
  - file: "steps/step-01-plan.yaml"
  - file: "steps/step-02-plan.yaml"
```

## Step file (`steps/step-NN-plan.yaml`)

Top-level keys:

- `id` — step id, e.g. `"S-01"`.
- `title` — short imperative title.
- `step_context` — multi-line block: the step's framing, core assumption,
  stop/replan conditions, evidence expectations. Builder/verifier-visible.
- `tasks` — ordered list.

Each task:

- `id` — e.g. `"T-01"` (unique within the step).
- `title` — one concern per task; do not bundle multiple implementation
  concerns into one task.
- `task_context` — multi-line instructions for the builder. State the
  verification surface explicitly.
- `requirements` — list of requirement objects: `id` (e.g. `"R1"`), `desc`,
  optional `priority` (`critical` | `expected` | `nice`).
- `verifier` — optional block with `rubric` text describing per-requirement
  A/B/C grading criteria.
- `auto_verify` — optional block with `items`: each item has `id`, `cmd`
  (shell command run from the worktree root), and `must` (boolean; `must: true`
  failures block submission). Prefer contract-level checks (run a test, import
  a module, assert behavior) over existence-only checks (`test -f`); static
  checks may supplement but not replace behavioral evidence.

## Rules

- No unsupported inheritance keys (`ref`, `use`).
- Keep ids stable when editing; renumber coherently if tasks are split.
- Every task keeps `task_context` and `auto_verify.items` after edits.
- `{{feature}}` and other `{{...}}` input placeholders are substituted at run
  creation; do not introduce new placeholder names that are not declared
  routine inputs.
- After any edit, re-run the validation command and fix until clean.
