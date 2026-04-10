# Step Context Guide: Keeping It Concise

`step_context` is a short string attached to each step in a routine YAML. It appears in the builder prompt for **every task** in that step. Because it is duplicated once per task, verbose context bloats agent prompts unnecessarily and dilutes the task-specific instructions that matter most.

## What step_context is for

`step_context` gives the builder a brief framing of *why this step exists* in the larger workflow. It is not the place for task instructions — those belong in `task_context` and `requirements`.

## Rules of thumb

- **One or two sentences maximum.** If you need more, the information belongs in `task_context`.
- **No duplication.** Do not restate what is already in the task title, `task_context`, or requirement descriptions.
- **No implementation details.** The builder reads `task_context` and `requirements` for what to do. `step_context` is orientation, not instruction.
- **Think "chapter heading", not "chapter".** The step title already names the step. `step_context` adds the one-sentence "why" that makes the title meaningful.

## Good vs verbose examples

### Too verbose (avoid)

```yaml
step_context: |
  In this step we will create all the project files that are needed for the
  application to run. You should create a README.md with a title and description,
  and a config.json with name and version fields. Make sure the JSON is valid.
  These files will be reviewed in the next step for quality.
```

This repeats the task requirements verbatim and adds implementation guidance that belongs in `task_context`.

### Concise (good)

```yaml
step_context: Create the core project files used in all subsequent steps.
```

Or, when step order matters:

```yaml
step_context: Foundation step — outputs here are consumed by S-02 and S-03.
```

### When step_context can be omitted entirely

If the step title is self-explanatory and there is no inter-step dependency worth calling out, leave `step_context` as a one-liner or omit it. An empty string is better than padding.

## Why brevity matters

Each task in a step receives its own copy of `step_context` in its builder prompt. A five-sentence `step_context` in a step with four tasks adds twenty sentences of repeated boilerplate to the LLM context. Over a multi-step routine this compounds quickly, increasing token cost and reducing signal-to-noise for the agent.

## Checklist for routine authors

Before committing a routine, review each `step_context` and ask:

1. Is this already covered by the step title?
2. Is this already covered by `task_context` or `requirements`?
3. Is this longer than two sentences?

If yes to any of these, trim or remove it.
