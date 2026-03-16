# Architecture: Idea-to-Plan Routine Optimization

## System Overview

This effort produces a new optimized variant (`routines/idea-to-plan-optimized/routine.yaml`). The original routine is preserved for A/B comparison. Two small engine fixes are required: two-pass template resolution in `templates.py` (for per-item context in fan-out prompts) and passing run variables to `shared_context` resolution in `executor.py`. All other changes use existing orchestrator mechanisms.

```
┌─────────────────────────────────────────────────────────┐
│                 idea-to-plan routine YAML                │
│                                                         │
│  Existing mechanisms used:                              │
│  ├── context_from     (R1, R6) -- inject artifacts      │
│  ├── fan_out          (R2, R3) -- parallel execution    │
│  ├── profile          (R4)     -- model routing         │
│  ├── auto_verify only (R5)     -- skip LLM verifier    │
│  └── task_context     (R7)     -- prompt instructions   │
│                                                         │
│  Engine fixes:                                          │
│  ├── two-pass template resolution (templates.py)        │
│  └── shared_context variable passing (executor.py)      │
└─────────────────────────────────────────────────────────┘
```

## Current vs. Proposed Task Structure

### Current Structure (9 sequential tasks)

```
S-01/T-01  Generate Initial Artifacts      [architect]
S-02/T-01  Gather Requirements             [architect]
S-03/T-01  Create Step Plans               [architect]
S-04/T-01  Create Step Files               [coder]      ← sequential, N files
S-05/T-01  Simulate Execution              [architect]  ← sequential, N steps
S-06/T-01  Cross-Check Artifacts           [coder]
S-07/T-01  Human Final Approval            [summarizer]
S-08/T-01  Generate Summary                [summarizer]
S-08/T-02  Create Routine YAML             [coder]
```

### Proposed Structure (with fan-out)

```
S-01/T-01  Generate Initial Artifacts      [architect]  + context_from(refs) + no-source-code directive
S-02/T-01  Gather Requirements             [architect]  (unchanged)
S-03/T-01  Create Step Plans               [architect]  (unchanged)
S-04/T-01  Create Step Files               [coder]      ← fan_out over step plans
  └── sub-agent per step-*-plan.md (max 4 concurrent)
S-05/T-01  Simulate Execution Per Step     [architect]  ← fan_out over step files (was dry_run type)
  └── sub-agent per step-*.md (max 4 concurrent)
  └── shared_context: intent, plan, architecture
  └── per-item context via {{item_content}} (step file content)
S-05/T-02  Merge Dry Run Notes             [summarizer] ← NEW merge task
S-06/T-01  Cross-Check Artifacts           [coder]      + context_from(arch, clarif)
S-07/T-01  Human Final Approval            [summarizer] - verifier removed
S-08/T-01  Generate Summary                [summarizer] - verifier removed + structural auto-verify
S-08/T-02  Create Routine YAML             [coder]      + context_from(intent, plan, arch)
```

**Key structural change:** S-05 is converted from `dry_run` step type to standard step with `fan_out`. The `dry_run` type's `target_steps`, `context_limit`, and `report_path` config are removed. Simulation instructions move into `per_item_prompt`, and context is provided via `shared_context` (same for all items) and `{{item_content}}` (per-item step file content).

## Key Integration Points

### 1. `context_from` Injection

The orchestrator resolves `context_from` entries before building the task prompt. File contents are injected as `{{context.<alias>}}` variables in the task_context template.

**File affected:** `routines/idea-to-plan-optimized/routine.yaml` (new variant)

**How it works today:** Tasks in S-02 and S-03 already use `context_from`. The mechanism reads the artifact file, and injects its content into the template variable. If the artifact doesn't exist and `required: false`, the variable is empty.

**What changes:** 5 additional tasks get `context_from` entries. Reference docs (`docs/plan-runner/*.md`) are also injected as artifacts, which is a slight stretch of the mechanism (these are static files, not generated artifacts) but works because `context_from` resolves any file path.

### 2. Fan-Out Configuration

`fan_out` is configured at the task level. When the executor encounters a task with `fan_out`, it:
1. Globs `input_glob` to find input files
2. Creates a sub-task per file
3. Runs sub-tasks concurrently (up to `max_concurrent`)
4. Each sub-task gets `item_content`, `item_stem`, `output_path` variables (note: `item_path` is NOT currently supported despite appearing in some YAML examples)
5. `shared_context` files are read and injected into each sub-task

**Current fan-out usage:** The orchestrator supports fan-out but it hasn't been used in the idea-to-plan routine yet.

**Risk:** The `output_pattern` naming may not produce the desired filenames. For S-04, `step-03-plan.md` with stem `step-03-plan` would produce `docs/.../steps/step-03-plan.md` instead of `docs/.../steps/step-03.md`. The `per_item_prompt` should instruct the agent on the correct output filename, or accept the longer name.

**Context injection for fan-out tasks:** Fan-out tasks use two dedicated mechanisms for context injection (not `context_from`, which is ignored at runtime during fan_out child execution):

1. **`shared_context`** — Common files injected identically into every sub-agent (e.g., intent.md, plan.md, architecture.md). File paths support `{{variable}}` resolution via the shared_context variable fix (section 6).

2. **Per-item context via two-pass template resolution** — Item-specific files injected into each sub-agent's `per_item_prompt` using `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}` syntax. The two-pass template resolution engine change (section 5) resolves variables first (`{{feature}}`, `{{item_stem}}`), then reads the resulting file path. This is a committed engine change in M4 (~10 lines in `templates.py`).

Together, these provide full context control: `shared_context` for common artifacts, `{{item_content}}` for the fan-out input file itself, and `{{file:...}}` with variable interpolation for per-item related artifacts (e.g., the step-plan corresponding to each step file in S-05).

**Example (S-05/T-01):** Each fan-out sub-agent simulating a step file receives:
- `shared_context`: intent.md, plan.md, architecture.md (same for all)
- `{{item_content}}`: the step file being simulated (e.g., `step-03.md`)
- `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}`: the corresponding step-plan (e.g., `step-03-plan.md`), resolved via two-pass templates

**Note:** `context_from` and `task_context` fields ARE mutually exclusive (schema validation rejects combinations). Fan-out tasks should not use `context_from`; non-fan-out tasks in the same step (e.g., S-05/T-02 merge task) can use `context_from` normally.

### 3. Profile-Based Model Routing

The `profile` field on `TaskConfig` maps to a `ModelProfile` enum (`architect`, `coder`, `summarizer`, `designer`). The agent runner resolves the profile to a concrete model string via its per-profile defaults.

**Confirmed mappings** for the CLI_SUBPROCESS agent runner:
- `architect` -> `claude-opus-4-6`
- `coder` -> `claude-sonnet-4-6`
- `summarizer` -> `claude-haiku-4-5`

These must be configured via the Agents UI page or API before running the optimized routine. If no mapping exists, the profile field has no effect and the run's default model is used.

### 4. Auto-Verify-Only Tasks

When a task has `auto_verify.items` but no `verifier.rubric`, the executor runs the auto-verify commands and, if all pass, marks verification as complete without spawning an LLM verifier agent.

**Tasks affected:** S-07/T-01 (Human Final Approval), S-08/T-01 (Generate Summary).

**Current behavior:** Both tasks have `verifier.rubric`, which spawns an LLM agent to grade output. This is wasteful for S-07 (trivial acknowledgement) and S-08/T-01 (structural output).

**New auto-verify for S-08/T-01:**
```yaml
auto_verify:
  items:
    - id: "summary_exists"
      cmd: "test -f docs/{{feature}}/plan-summary.md"
      must: true
    - id: "has_sections"
      cmd: "grep -q 'Intent' docs/{{feature}}/plan-summary.md && grep -q 'Risks' docs/{{feature}}/plan-summary.md"
      must: true
```

### 5. Two-Pass Template Resolution (Engine Enhancement)

**File:** `src/orchestrator/workflow/templates.py`

**Current behavior:** `resolve_template()` uses a single `re.sub()` pass with regex `\{\{(.+?)\}\}`. All placeholders (variables and `{{file:...}}`) are resolved in one pass. This means `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}` fails -- the non-greedy regex matches `{{file:docs/{{feature}}` as the first placeholder (capturing `file:docs/{{feature`), which is neither a valid file path nor a known variable.

**Required change:** Split resolution into two passes:
1. **Pass 1:** Resolve all non-`file:` placeholders (plain variable lookups from the `variables` dict)
2. **Pass 2:** Resolve `{{file:...}}` placeholders (now with variable values already substituted in paths)

**Implementation sketch:**
```python
def resolve_template(template, variables=None, worktree_path=None):
    vars_ = variables or {}

    # Pass 1: resolve plain variables only (skip {{file:...}})
    def _replace_vars(match):
        key = match.group(1).strip()
        if key.startswith("file:"):
            return match.group(0)  # leave for pass 2
        if key in vars_:
            return vars_[key]
        return match.group(0)

    result = _PLACEHOLDER_RE.sub(_replace_vars, template)

    # Pass 2: resolve {{file:...}} references
    def _replace_files(match):
        key = match.group(1).strip()
        if key.startswith("file:"):
            rel_path = key[len("file:"):]
            full = Path(worktree_path or ".") / rel_path
            try:
                return full.read_text()
            except (FileNotFoundError, IsADirectoryError, OSError):
                return f"[File not found: {rel_path}]"
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_replace_files, result)
```

**Risk:** If a resolved variable value itself contains `{{file:...}}`, the second pass would process it. This is unlikely in practice (variable values come from run config and fan-out input metadata, not user-controlled templates) but should be documented.

**Testing:** Add unit tests for:
- `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}` with variables `feature=myproject`, `item_stem=step-01` -> reads `docs/myproject/step-01-plan.md`
- Plain variables still resolve in one pass
- `{{file:...}}` without nested variables still works
- Missing file returns `[File not found: ...]`

### 6. Shared Context Variable Resolution (Engine Fix)

**File:** `src/orchestrator/runners/executor.py` (line ~1206)

**Current behavior:** `shared_context` entries are resolved via `resolve_template(ctx_entry, worktree_path=worktree_path)` without passing the `variables` dict. This means `{{feature}}` in shared_context file paths (e.g., `docs/{{feature}}/intent.md`) is left unresolved.

**Required change:** Pass run config variables to the `resolve_template()` call. The variables dict (containing `feature` and other run config values) is built at line ~1210, so shared_context resolution needs to move after variable construction, or a partial dict from `run.config` should be passed.

**Implementation:** Build a `config_vars` dict from `run.config` before the loop, pass it to `resolve_template()` for shared_context entries. This is a ~3-line change.

## Files to Modify

| File | Changes |
|------|---------|
| `routines/idea-to-plan-optimized/routine.yaml` | **New file.** All R1-R7 changes: context_from, fan_out, profile, verifier removal, prompt updates, S-05 restructure |
| `routines/idea-to-plan/routine.yaml` | **Unchanged.** Preserved as baseline for A/B comparison |
| `src/orchestrator/workflow/templates.py` | **Modified.** Two-pass template resolution: variables first, then `{{file:...}}` references (~10 lines) |
| `src/orchestrator/runners/executor.py` | **Modified.** Pass run config variables to shared_context resolution (~3 lines) |
| `tests/unit/test_templates.py` | **New/modified.** Unit tests for two-pass resolution with nested variables |

One new routine file is created, two engine files are modified, and tests are added/updated.

**Source:** The new variant is based on `routines/idea-to-plan/routine.yaml` (the active 8-step version). The `examples/routines/idea_to_plan.yaml` file is an older copy.

## Testing Strategy

### Unit Testing

- **Template resolution tests:** New unit tests for two-pass resolution in `templates.py` (nested variables, missing files, edge cases).
- **Routine schema tests:** Existing `tests/unit/test_idea_to_plan_routine.py` validates the routine schema and should be updated to also validate the optimized variant. Task structure changes (T-02 added to S-05, S-05 type changed from `dry_run` to standard) will require test updates.

### Schema Validation

After each milestone, validate the routine:
```bash
uv run orchestrator --json routines validate routines/idea-to-plan-optimized/routine.yaml
```

### Integration Testing

Run the updated routine on a small test idea and compare metrics to the baseline:

| Metric | Baseline (b46dbe62) | Target |
|--------|---------------------|--------|
| Cost | $18.28 | $5-7 |
| Wall-clock | 70 min | 20-25 min |
| Tool calls | 703 | 250-300 |
| Duplicate reads | 103 (41%) | 10-15 (5%) |

**Test approach:**
1. After M1: Run and measure tool calls. Expect 30%+ reduction.
2. After M2: Verify no LLM verifier spawns for S-07/T-01 and S-08/T-01.
3. After M3: Check agent metadata for correct model per task.
4. After M4: Measure wall-clock for S-04 + S-05. Expect 4x speedup (16+9 min -> ~7 min).

**Live test:** After all milestones, run the optimized routine end-to-end using Claude CLI (already configured). Compare cost, time, and tool calls to the baseline ($18.28, 70 min, 703 tool calls).

### Regression Testing

- Existing `tests/unit/test_idea_to_plan_routine.py` must pass (update assertions for new variant's task structure).
- A full live test run (using Claude CLI) of the optimized routine must produce all expected artifacts: intent.md, plan.md, architecture.md, clarifications.md, step plans, step files, dry-run notes (now from fan-out merge), verification report, plan summary, routine YAML.

## Risk Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Fan-out naming mismatch | Step files get wrong names | Test with 2-step plan first; adjust output_pattern or prompt |
| Profile mappings not configured | All tasks run on same (expensive) model | Document required setup; add validation warning if profile is set but no mapping exists |
| Removing verifier misses quality issues | Summary or approval has subtle defects | Accept trade-off: these are low-stakes tasks; cross-check (S-06) catches upstream issues |
| context_from pushes past context limits | Task prompt too large for model | Monitor; largest injections are ~10KB total, well within limits |
| Fan-out context injection | Fan-out tasks cannot use `context_from` (ignored at runtime) | Committed two-pass template resolution (M4) provides per-item context via `{{file:...}}` in `per_item_prompt`; `shared_context` provides common artifacts |
| S-05 dry_run type removal | Losing context_limit and target_steps semantics | Fan-out provides better parallelism; context control moves to per_item_prompt and shared_context |
