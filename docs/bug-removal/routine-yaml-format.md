# Routine YAML Format Guide for Bug Removal

This document describes the format of `routines/bug-removal/routine.yaml` and provides guidance
for future edits to that file.

## File Location

```
routines/bug-removal/routine.yaml
```

## Top-Level Structure

The routine uses the **unwrapped** format (no outer `routine:` wrapper key):

```yaml
id: "bug-removal"
name: "Bug and Gap Removal"
description: |
  Multi-line description...

steps:
  - id: "S-01"
    ...
```

### Required Top-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique routine identifier (e.g. `"bug-removal"`) |
| `name` | string | Human-readable routine name |
| `steps` | array | List of step definitions (must have at least 1) |

### Optional Top-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Multi-line routine overview; use `|` block scalar |
| `inputs` | array | Input variable definitions — this routine has none |

## Step Structure

Each entry in `steps` must have:

```yaml
steps:
  - id: "S-01"              # Required: string, e.g. "S-01"
    title: "Step Title"     # Required: string
    step_context: |         # Optional: multi-line context for the step
      Description...
    tasks:                  # Required: array, at least 1 task
      - id: "T-01"
        ...
```

### Optional Step Fields

| Field | Type | Description |
|-------|------|-------------|
| `step_context` | string | Context provided to the agent for this step |
| `type` | string | `standard` (default) or `dry_run` |
| `gate` | object | Human approval gate (`type: human_approval`) |
| `transitions` | object | `on_complete` and `on_condition` routing |

## Task Structure

Each task in `tasks` must have:

```yaml
tasks:
  - id: "T-01"                    # Required: string, e.g. "T-01"
    title: "Task Title"           # Required: string
    task_context: |               # REQUIRED: multi-line agent instructions
      What the agent must do...
    requirements:                 # Optional but strongly recommended
      - id: "R1"
        desc: "Requirement description"
        priority: critical        # critical | expected | nice_to_have
    auto_verify:                  # Optional: shell commands to auto-check
      items:
        - id: "check_id"
          cmd: "test -f some/file"
          must: true              # true = must pass, false = advisory
    verifier:                     # Optional: rubric for human verifier
      rubric:
        - id: "rubric_id"
          text: |
            Grading criteria...
    retry:                        # Optional: retry policy
      max_attempts: 2
    context_from:                 # Optional: load prior artifacts into context
      - artifact: "docs/foo/bar.md"
        as: "bar"
        required: true
    artifacts:                    # Optional: expected output files
      - path: "path/to/file"
        required: true
```

### task_context is REQUIRED

Every task **must** have a `task_context` field. This is the most common validation failure.
The `task_context` provides the agent's instructions — without it, the agent has no guidance.

## Requirements Priority Values

Only these three priority values are accepted:

- `critical` — must be marked done for submission to succeed
- `expected` — should be done; verifier grades against it
- `nice_to_have` — optional improvement

## Common Validation Failures

Run validation with:
```bash
uv run orchestrator --json routines validate routines/bug-removal/routine.yaml
```

| Error | Cause | Fix |
|-------|-------|-----|
| Missing `task_context` | Task has no `task_context` field | Add `task_context: \|` with content |
| Empty `tasks` list | Step has `tasks: []` or no tasks | Add at least one task per step |
| Unknown field | Using `schema_version`, `owner`, `tags`, `critical`, `verify` | Remove the field |
| Wrong type for `tasks` | `tasks:` is a dict instead of list | Use `tasks:` with `- id:` list items |
| Invalid priority | Using `high`, `medium`, `low` for priority | Use `critical`, `expected`, `nice_to_have` |

## Bug Removal Routine Structure

This routine encodes 12 steps corresponding to 10 bugs/gaps, organized in 4 milestones:

| Step | ID | Bug/Gap | Milestone | Tasks |
|------|----|---------|-----------|-------|
| S-01 | Fix GateBlockedError Handling | AGENT-DEATH-HUMAN-GATE | 1 | 3 |
| S-02 | Rewrite Human Gate Task Prompts | AGENT-DEATH-HUMAN-GATE | 1 | 2 |
| S-03 | Implement Failed-Run Recovery API | FAILED-RUN-RECOVERY | 1 | 4 |
| S-04 | Add Recovery UI | FAILED-RUN-RECOVERY | 1 | 4 |
| S-05 | Phase-Aware MCP Tool Filtering | MCP-TOOLS-NO-PHASE-FILTERING | 2 | 3 |
| S-06 | Wire Step-Level Human Approval UI | UI-STEP-APPROVAL | 2 | 3 |
| S-07 | Wire AgentGuidancePanel Lifecycle Hooks | UI-AGENT-GUIDANCE-PANEL | 3 | 3 |
| S-08 | Add Backward Step Transition UI | UI-BACKWARD-TRANSITIONS | 3 | 2 |
| S-09 | Branch Status Panel and Back-Merge | UI-BRANCH-STATUS | 3 | 3 |
| S-10 | Env File Management UI | UI-ENV-FILE-MANAGEMENT | 4 | 3 |
| S-11 | Surface Server GlobalConfig | UI-GLOBAL-CONFIG | 4 | 3 |
| S-12 | Routine YAML Validation UI | UI-ROUTINE-VALIDATION | 4 | 3 |

**Total: 12 steps, 34 tasks**

### Step Dependencies

Steps must be executed in order due to these dependencies:
- **S-02 requires S-01**: Actionable gate prompts require GateBlockedError to be handled first
- **S-04 requires S-03**: Recovery UI requires the backend recovery API endpoint

All other steps (S-05 through S-12) are independent of each other and could be parallelized.

## Editing Guidelines

### Modifying task_context

Use the YAML block scalar `|` for multi-line strings:

```yaml
task_context: |
  First line of instructions.

  Second paragraph with more detail.
```

### Adding a new requirement

```yaml
requirements:
  - id: "R5"
    desc: "New requirement description"
    priority: expected
```

IDs must be unique within a task. Use `R1`, `R2`, ... in sequence.

### Adding an auto_verify command

```yaml
auto_verify:
  items:
    - id: "unique_check_id"
      cmd: "uv run pytest tests/ -k 'new_test' -q 2>&1 | grep -q 'passed'"
      must: true
```

Commands run in the project root directory. Use `must: true` for required checks,
`must: false` for advisory checks that won't block submission.

### Changing retry policy

```yaml
retry:
  max_attempts: 3  # default is typically 1 if omitted
```

## Validation After Edits

Always validate after any change to the YAML:

```bash
uv run orchestrator --json routines validate routines/bug-removal/routine.yaml
```

A successful response looks like:
```json
{
  "valid": true,
  "id": "bug-removal",
  "name": "Bug and Gap Removal",
  "steps": 12,
  "inputs": 0
}
```

Fix all errors reported before committing changes.
