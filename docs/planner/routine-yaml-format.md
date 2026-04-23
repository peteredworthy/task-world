# Routine YAML Format Guide

Reference document for agents writing or editing routine step YAML files.

---

## Top-level shape (either wrapped or unwrapped)

```yaml
id: "my-routine"
name: "My Routine"
description: "..."
inputs: []
steps: []
```

Required top-level fields: `id` (string), `name` (string), `steps` (array, >=1 step).
Optional: `description`, `inputs` (array of `{name, required, default, description}`).

---

## Step shape

Each step must have:
- `id` (string, e.g. `"S-01"`)
- `title` (string)
- `tasks` (array, >=1 task)

Optional: `step_context`, `type` (standard|dry_run), `gate`, `transitions`,
`mcp_servers` (array of MCP server configs), `available_tools` (array of strings).

### mcp_servers

Attach external tool servers to a step (all tasks inherit):

```yaml
mcp_servers:
  - name: "browser"                    # unique name (required)
    command: "npx"                     # stdio transport
    args: ["-y", "@playwright/mcp@latest", "--headless"]
  - name: "my-api"                     # OR url transport (not both)
    url: "https://api.example.com/mcp/sse"
    auth_token_env: "MY_API_TOKEN"     # env var name, never inline token
```

Use `mcp_servers` when tasks need browser control, external APIs, or tools not built
into the agent. See `docs/planner/mcp-server-guide.md` for details.

---

## Task shape

Each task must have:
- `id` (string, e.g. `"T-01"`)
- `title` (string)
- `task_context` (string) — **REQUIRED**, describes what the agent should do

Optional:
- `requirements` (array of `{id, desc, priority: critical|expected|nice_to_have}`)
- `artifacts` (array of `{path, required}`)
- `auto_verify: {items: [{id, cmd, must}]}`
- `verifier: {rubric: [{id, text}], submission_template: {grade_scale, require_reason_if_below, require_remediation_if_below}}`
- `retry: {max_attempts: N}`
- `context_from` (array of `{artifact, as, required}`)

### Incremental oversight slices

For large or uncertain work, the planning routine may emit one YAML step as the
first executable slice instead of a full multi-step routine. In that case, preserve
these headings in builder/verifier-visible text, normally inside `task_context` and
rubric text:

- `Assumption Under Test`: the one fact this slice is meant to prove or disprove.
- `Target Behavior Or Missing Proof`: the bug, workflow, or evidence gap being targeted.
- `Real Verification Surface`: the actual UI, API, CLI, integration path, or runtime
  surface to exercise. Shim-only or helper-only checks are not enough for frontend
  or integration behavior.
- `Stop Or Replan Conditions`: concrete conditions that mean execution should stop
  and planning should adapt, including bug not reproduced, behavior already correct,
  environment unable to verify the target surface, or evidence contradicting the plan.
- `Evidence Artifacts`: exact files, logs, screenshots, traces, command outputs, or
  notes the builder/verifier must leave for the next planning cycle.

For frontend or integration work, a fallback harness or mocked shim can help diagnose
failures, but it cannot be the readiness proof. If a wrapper falls back after the real
browser, UI, API, CLI, or integration path fails, capture both outcomes and treat the
real-surface failure as a stop/replan condition. Do not make a `must: false` command
the strongest evidence for a behavior claim.

Do not encode later speculative slices as executable steps. Put them in planning
documentation as deferred candidates until the first slice produces evidence.

### Rubric item ID rule

Rubric item IDs **must exactly match** requirement IDs:
- If a task has requirements R1, R2, R3, rubric items must use ids `"R1"`, `"R2"`, `"R3"`
- Do NOT use descriptive suffixes like `"R1_enum"` or `"R2_config"`
- Descriptive context belongs in the rubric `text` field, not the `id`
- Mismatched IDs cause CLI validation warnings which block the run

---

## Example step

```yaml
steps:
  - id: "S-01"
    title: "Setup"
    step_context: "Initialize project files"
    tasks:
      - id: "T-01"
        title: "Create base files"
        task_context: "Create the initial project structure"
        requirements:
          - id: "R1"
            desc: "Project files are created correctly"
            priority: critical
          - id: "R2"
            desc: "Files follow project conventions"
            priority: expected
        auto_verify:
          items:
            - id: "files_exist"
              cmd: "test -f README.md"
              must: true
        verifier:
          rubric:
            - id: "R1"
              text: "R1 — A: all files created with correct content. B: files exist but incomplete."
            - id: "R2"
              text: "R2 — A: files follow naming and structure conventions. B: minor deviations."
        retry:
          max_attempts: 2
```

---

## Auto-verify path rules

All paths in `auto_verify` commands **must be relative to the project root**.
Auto-verify commands run with cwd set to the worktree root.
NEVER use absolute paths or hardcoded worktree paths.

- BAD:  `grep -q 'foo' /home/user/project/worktrees/r25/src/main.py`
- GOOD: `grep -q 'foo' src/main.py`
- BAD:  `cd /home/user/project/worktrees/r25/ui && npx tsc --noEmit`
- GOOD: `cd ui && npx tsc --noEmit`

---

## Auto-verify exit code rules

The exit code determines pass/fail. Exit 0 = pass, non-zero = fail.

**NEVER use shell pipes (`|`) in auto_verify commands.** In a pipeline, the exit code
comes from the LAST command only. `pytest ... | tail -5` always returns 0 because
`tail` succeeds even when `pytest` fails — silently hiding test failures.

The runner already captures the last N lines of output (`tail_lines` config), so piping
through `tail`/`head` is unnecessary and harmful.

- BAD:  `uv run pytest tests/ -q 2>&1 | tail -5`  (exit code = tail = always 0)
- GOOD: `uv run pytest tests/ -q`  (exit code = pytest = correct)
- BAD:  `ls *.md | wc -l | awk '{if ($1>=1) exit 0; else exit 1}'`
- GOOD: `ls *.md >/dev/null 2>&1`  (ls exits non-zero when no files match)

---

## Auto-verify quality: contract-level vs existence-only

Every task **must** have at least one auto_verify item or a verifier rubric.
Tasks without either can pass via self-report alone — this is a critical gap.

**Prefer contract-level checks over existence checks:**

- BAD:  `test -f src/models.py` (file exists but may be empty/wrong)
- GOOD: `uv run python -c "from mymodule.models import MyModel; m = MyModel(name='test'); assert m.name == 'test'"`
- GOOD: `uv run pytest tests/unit/test_models.py -v`
- GOOD: `uv run python -c "import mymodule; assert hasattr(mymodule, 'expected_function')"`

Contract-level means: test public API signatures, return types, schema fields/defaults,
import paths, and integration boundaries. Do NOT test internal implementation details.

**Classifying checks (use this in verifier rubric):**
- contract-level: import/assertion, test run, type check, schema validation
- existence-only: `test -f`, `grep -q`, `grep -c`, `ls`

---

## Wiring verification

When a task introduces a new component to REPLACE existing functionality, structural
checks alone are insufficient. A builder can satisfy every `hasattr()`, import, and
structural assertion while the system continues using the old code path.

For any task that replaces an existing code path, include at least one of:
- A grep/AST check confirming the old call site is gone
- An integration test that exercises the full path through the NEW component
  and would fail if the old path were still active
- A verifier rubric item instructing the verifier to read both the old call site
  AND the new component and confirm the transition happened

Structural checks do NOT verify wiring. Parity tests that pass via the old code path
do NOT verify that the new component is in use. Mark wiring requirements as critical.

---

## Common validation failures

- Missing `task_context` (REQUIRED on every task)
- Empty `tasks` list
- Wrong types (tasks as object instead of list)
- Unknown fields (`schema_version`, `owner`, `tags`, `critical`, `verify` are NOT valid)
- Shell pipes in `auto_verify` commands
- Mismatched rubric IDs (must match requirement IDs exactly)
