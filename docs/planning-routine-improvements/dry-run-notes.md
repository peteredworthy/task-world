# Dry Run Simulation Notes

## Per-Step Simulation Results

### Step 01: Context Injection (M1)

**Tasks**: 1 task — Copy original routine and add `context_from` declarations.

**Assumptions**:
- Original routine exists at `routines/idea-to-plan/routine.yaml` ✅ Confirmed
- `context_from` field uses `as:` (Pydantic alias for `as_name`) ✅ Confirmed in `config/models.py:177`
- `required` field exists on `ContextSource` ✅ Confirmed (`required: bool = True`, line 178)
- Reference docs at `docs/plan-runner/` exist ✗ **NOT FOUND** — directory does not exist

**Expected Outputs**: New file at `routines/idea-to-plan-optimized/routine.yaml` with `context_from` on 5 tasks plus reference doc entries on S-01/T-01 and S-04/T-01.

**Blockers & Mitigation**:
- **GAP-01: Reference doc files missing**: `docs/plan-runner/idea_to_plan_stripped.md`, `docs/plan-runner/idea_to_plan_detailed.md`, `docs/plan-runner/step-files.md` do not exist in the repo. The original routine references them as text instructions (lines 49-51 of routine.yaml), implying they should exist. Since `required: false` is used, context injection will silently fail — no crash, but the optimization benefit is lost. **Mitigation**: Step file updated with dependency note and fallback instruction.
- **`docs/planner/templates/*.md` also doesn't exist** — referenced in S-03/T-01 `task_context`. Not a blocker for the optimized routine since it's just a text reference, not a `context_from` entry.

**Gaps Identified**:
1. GAP-01: Reference doc dependency — files must exist at runtime for context injection to work. Applied to step files: **YES** (added dependency verification note to step-01.md)
2. GAP-17 (CRITICAL): `as:` values in `context_from` entries use bare names (e.g., `as: "intent"`) but `task_context` templates reference `{{context.intent}}`. The prompt generator does simple `{{key}} → value` replacement — so `as: "intent"` only resolves `{{intent}}`, NOT `{{context.intent}}`. All `as:` values must be prefixed with `context.` (e.g., `as: "context.intent"`). This is a pre-existing bug in the original routine. Applied to step files: **YES** (added critical warning to step-01.md and step-05.md)

---

### Step 02: Verification Optimization (M2)

**Tasks**: 1 task — Remove `verifier.rubric` from S-07/T-01 and S-08/T-01, add structural auto-verify.

**Assumptions**:
- S-07/T-01 currently has a `verifier` block ✅ Confirmed (routine.yaml lines 595-601)
- S-08/T-01 currently has a `verifier` block ✅ Confirmed (routine.yaml lines 627-635)
- Removing `verifier` block causes executor to skip LLM verifier ✅ Correct behavior
- S-08/T-01 already has `auto_verify` ✅ Confirmed (line 622-625, checks `summary_exists`)

**Expected Outputs**: S-07/T-01 and S-08/T-01 have no `verifier` blocks. S-08/T-01 has enhanced `auto_verify`.

**Blockers & Mitigation**: None — straightforward YAML deletion and addition.

**Gaps Identified**: None. Well-specified and low-risk.

---

### Step 03: Profile-Based Model Routing (M3)

**Tasks**: 1 task — Add `profile` fields to all 9 tasks.

**Assumptions**:
- `profile` field exists in `TaskConfig` ✅ Confirmed (`config/models.py:197`, `profile: ModelProfile | None = None`)
- `ModelProfile` enum has `architect`, `coder`, `summarizer` values ✅ Confirmed
- Profile field is accepted by routine YAML schema validation ✅ Valid `TaskConfig` field

**Expected Outputs**: Every task has a `profile` field with correct tier assignment.

**Blockers & Mitigation**: None — additive YAML field.

**Gaps Identified**: None. Step 05 later adds S-05/T-02 which needs a profile — Step 05 already includes `profile: "summarizer"` in the T-02 spec, so no gap.

---

### Step 04: Engine Enhancements (M4 Prerequisites)

**Tasks**: 2 tasks — Two-pass template resolution and shared_context variable passing.

#### Task 1: Two-Pass Template Resolution

**Assumptions**:
- Current regex `_PLACEHOLDER_RE = r"\{\{(.+?)\}\}"` uses non-greedy matching ✅ Confirmed (`templates.py:8`)
- Current resolution is single-pass ✅ Confirmed (`templates.py:56`, single `_PLACEHOLDER_RE.sub()` call)
- Two-pass approach with same `_PLACEHOLDER_RE` regex will handle nested `{{file:docs/{{feature}}/plan.md}}` ✗ **BROKEN**

**GAP-05 (CRITICAL) — Regex nesting failure**:

The proposed two-pass approach in step-04.md will NOT work for nested patterns. Here's why:

Given template: `{{file:docs/{{feature}}/{{item_stem}}-plan.md}}`

The non-greedy regex `\{\{(.+?)\}\}` matches the **shortest** string between `{{` and `}}`:
1. First match: `{{file:docs/{{feature}}` (capturing `file:docs/{{feature`)
2. Second match: `{{item_stem}}` (capturing `item_stem`)

In Pass 1 (skip `{{file:...}}`):
- Match 1: key=`file:docs/{{feature` → starts with `file:`, returned unchanged
- Match 2: key=`item_stem` → resolved to value

Result: `{{feature}}` was consumed by the outer match and never resolved independently\!

**Fix**: Use `[^{}]+` character class to prevent matching across brace boundaries:

```python
_INNER_RE = re.compile(r"\{\{([^{}]+)\}\}")   # non-nested only
_OUTER_RE = re.compile(r"\{\{(.+?)\}\}")       # any (for file: refs after inner resolved)

# Pass 1: resolve plain variables using _INNER_RE
def _replace_vars(match):
    key = match.group(1).strip()
    if key.startswith("file:"):
        return match.group(0)
    return vars_.get(key, match.group(0))

result = _INNER_RE.sub(_replace_vars, template)

# Pass 2: resolve {{file:...}} using _OUTER_RE
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

return _OUTER_RE.sub(_replace_files, result)
```

With `[^{}]+`:
- Pass 1: `{{feature}}` matches (no braces inside), resolves to `myproject`. `{{item_stem}}` matches, resolves. The outer `{{file:docs/...}}` is NOT matched because its content contains `{` and `}`.
- After Pass 1: `{{file:docs/myproject/step-01-plan.md}}`
- Pass 2: `{{file:docs/myproject/step-01-plan.md}}` matches, reads file contents.

Applied to step files: **YES** (step-04.md updated with correct regex approach)

#### Task 2: Pass Run Variables to shared_context Resolution

**Assumptions**:
- `shared_context` entries resolved at `executor.py:1203-1207` without `variables` ✅ Confirmed
- Run config variables available at `run.config` ✅ Confirmed (`executor.py:1216-1218`)
- Fix is to add `variables=config_vars` to `resolve_template()` call ✅ Correct

**Expected Outputs**: `shared_context` entries with `{{feature}}` resolve to actual paths.

**GAP-07 (MEDIUM)**: Even with variable resolution, bare paths like `"docs/myproject/plan.md"` in shared_context produce the PATH STRING in the prompt, not file contents. `resolve_template()` only reads files for `{{file:...}}` patterns. This means step-05's shared_context entries MUST use `{{file:...}}` format. See Step 05 gaps.

Applied to step files: **YES** (step-04.md Task 2 updated with note about `{{file:...}}` requirement)

**GAP-13 (MEDIUM) — Variable construction ordering**: In `executor.py`, the `variables` dict (lines 1210-1218) is built AFTER the shared_context resolution loop (lines 1203-1207). The fix must build a separate `config_vars` dict from `run.config` BEFORE the shared_context loop — it cannot reuse the `variables` dict built later. The `variables` dict includes `item_content`, `item_stem`, `output_path` which are per-item and should NOT be injected into shared_context paths.

Applied to step files: **YES** (step-04.md Task 2 updated with explicit code showing ordering)

**GAP-14 (MEDIUM) — No integration test assertions for shared_context fix**: Step-04/T2 originally specified "all integration tests pass" without defining new test assertions for the shared_context variable fix. Added three specific test assertions: (1) shared_context with `{{file:...}}` resolves to file contents, (2) nested variables resolve after two-pass fix, (3) bare paths return literal strings (regression guard).

Applied to step files: **YES** (step-04.md Task 2 updated with specific integration test assertions)

---

### Step 05: Fan-Out Parallelism (M4b)

**Tasks**: 2 tasks — Convert S-04/T-01 to fan_out, restructure S-05 to fan_out + merge.

#### Task 1: Convert S-04/T-01 to Fan-Out

**Assumptions**:
- `FanOutConfig` supports `input_glob`, `output_pattern`, `per_item_prompt`, `shared_context`, `max_concurrent` ✅ Confirmed (`config/models.py:98-108`)
- `FanOutConfig` has its own `auto_verify: AutoVerifyConfig | None` field ✅ Confirmed (`config/models.py:107`)
- `shared_context` is `list[str]` ✅ Confirmed
- `context_from` should be removed from fan_out tasks ✅ Correct (ignored at runtime)

**GAP-08 (CRITICAL) — fan_out and task_context are mutually exclusive**:

`TaskConfig._validate_task_config()` in `config/models.py:216-219`:
```python
if self.fan_out is not None:
    if self.task_context \!= "":
        raise ValueError("Task '...': 'fan_out' and 'task_context' are mutually exclusive.")
```

Step 01 adds/updates `task_context` on S-04/T-01 and S-05/T-01. Step 05 adds `fan_out` but does NOT instruct removing `task_context`. Routine validation WILL fail with ValueError.

**Fix**: Step 05 must explicitly instruct removing `task_context` from S-04/T-01 and S-05/T-01 when adding `fan_out`. The `per_item_prompt` inside `fan_out` replaces `task_context`.

Applied to step files: **YES** (step-05.md updated with explicit task_context removal instruction)

**GAP-10 (HIGH) — shared_context entries are plain paths, not file references**:

Step-05.md specifies shared_context entries as bare paths:
```yaml
shared_context:
  - "docs/{{feature}}/plan.md"
```

But `resolve_template("docs/myproject/plan.md")` returns the literal string `"docs/myproject/plan.md"` — it does NOT read the file. Only `{{file:...}}` patterns trigger file reads.

**Fix**: Use `{{file:...}}` format:
```yaml
shared_context:
  - "{{file:docs/{{feature}}/plan.md}}"
  - "{{file:docs/{{feature}}/architecture.md}}"
```

Applied to step files: **YES** (step-05.md updated)

**GAP-11 (MEDIUM) — per-item auto_verify placed at wrong level**:

Step-05.md places `auto_verify` with `{{output_path}}` outside the `fan_out` block. But `{{output_path}}` is a per-item variable only available during fan_out child execution. `FanOutConfig` has its own `auto_verify` field for per-item checks.

**Fix**: Move per-item auto_verify inside the `fan_out` block.

Applied to step files: **YES** (step-05.md updated)

#### Task 2: Restructure S-05 from dry_run to Fan-Out + Merge

**Assumptions**:
- S-05 currently has `type: dry_run` and `dry_run:` config ✅ Confirmed (routine.yaml:326-333)
- Tasks within a step run sequentially (T-02 after T-01) ✅ Correct architecture

**GAP-09 (HIGH) — double-plan naming in per_item_prompt**:

S-05/T-01 fans out over step files at `docs/{{feature}}/steps/step-*.md`. Due to S-04's output naming, these files are named `step-01-plan.md` (item_stem = `step-01-plan`).

The per_item_prompt contains:
```
{{file:docs/{{feature}}/{{item_stem}}-plan.md}}
```

With `item_stem` = `step-01-plan`, this resolves to: `step-01-plan-plan.md` — FILE NOT FOUND.

**Fix**: Change to `{{file:docs/{{feature}}/{{item_stem}}.md}}`. Since `item_stem` = `step-01-plan`, this resolves to `step-01-plan.md` — the correct step plan file.

Applied to step files: **YES** (step-05.md updated)

Same GAP-08, GAP-10, GAP-11 also apply to S-05/T-01. All applied.

**Note on input file path availability**: S-05/T-01's per_item_prompt says "Apply fixes directly to the step file being analyzed." The agent needs to know the input file's path to edit it. While `{{input_path}}` is NOT a template variable in per_item_prompt, the executor appends `Input file: {input_path}` and `Output file: {output_path}` to the full prompt (executor.py line 1237). So the agent CAN see the input file path in the prompt footer. No fix needed — this is already handled by the executor.

---

### Step 06: Validation and Live Test (M4c)

**Tasks**: 2 tasks — Schema validation + test suites, then live test run.

**Assumptions**:
- `uv run orchestrator --json routines validate` command exists ✅
- Profile-to-model mappings must be configured before live test ✅
- Claude CLI is available ✅ Per clarification Q5

**GAP-12 (MEDIUM)**: No verification step checks that profile-to-model mappings are configured. Missing mappings silently fall back to default model.

Applied to step files: **YES** (step-06.md updated with profile mapping verification)

**GAP-15 (MEDIUM) — No pass/fail thresholds for live test metrics**: The metrics comparison table had target columns but no explicit pass/fail criteria. Without thresholds, the agent has no way to determine if the optimization "worked." Added pass threshold column with minimum: cost < $12 (35% reduction), wall-clock < 50 min, tool calls < 500, duplicate reads < 60. Cost is the primary gate; other metrics are diagnostic.

Applied to step files: **YES** (step-06.md Task 2 updated with pass/fail thresholds and diagnostic guidance)

**GAP-16 (LOW) — Live test verification assertions lack specificity**: "Fan-out steps execute sub-agents concurrently" and "No LLM verifier spawns" are behavioral claims without specific checks. Added concrete assertions: check concurrent child tasks in run detail, verify attempt count = 1 with no verifier_prompt for auto-verify-only tasks, check agent metadata shows correct model per profile.

Applied to step files: **YES** (step-06.md Task 2 functionality outcomes updated)

---

## Persistence Mapping Audit

**N/A** — No new state model fields are introduced by any step.

All changes are to:
- Routine YAML configuration (steps 01-03, 05) — no persistence impact
- `resolve_template()` pure function in `templates.py` (step 04 Task 1) — no persistence
- `executor.py` variable passing (step 04 Task 2) — no new state, just fixing an existing call

No `TaskState`, `StepState`, `Run`, or `Attempt` fields are added. No DB columns, repo write/read mappings, or migrations needed.

---

## Failure Mode Analysis

| Step | ID | Failure Mode | Likelihood | Severity | Hardening Action |
|------|-----|-------------|------------|----------|------------------|
| 01 | GAP-01 | Reference docs (`docs/plan-runner/*.md`) don't exist → `context_from` silently empty | HIGH | MEDIUM | Added dependency verification note. `required: false` prevents crash. |
| 01 | — | Agent modifies original routine instead of copy | LOW | HIGH | Already hardened with `git diff` check. |
| 04-T1 | GAP-05 | Regex `.+?` can't handle nested `{{}}` → inner variables consumed by outer match | CERTAIN | CRITICAL | **Fixed**: Use `[^{}]+` regex for Pass 1. |
| 04-T1 | — | Existing tests break from regex change | MEDIUM | MEDIUM | `[^{}]+` matches all non-nested patterns identically. Run full test suite. |
| 04-T2 | GAP-07 | shared_context entries produce path strings, not file contents | CERTAIN | HIGH | **Fixed**: Use `{{file:...}}` format in step-05.md. |
| 05-T1 | GAP-08 | `fan_out` + `task_context` mutually exclusive → ValueError | CERTAIN | CRITICAL | **Fixed**: Remove `task_context` when adding `fan_out`. |
| 05-T1 | GAP-10 | shared_context bare paths → literal strings in prompt | CERTAIN | HIGH | **Fixed**: Use `{{file:...}}` format. |
| 05-T1 | GAP-11 | Per-item auto_verify at task level → `{{output_path}}` undefined | HIGH | MEDIUM | **Fixed**: Move inside `fan_out` block. |
| 05-T2 | GAP-09 | `{{item_stem}}-plan.md` doubles `-plan` suffix → file not found | CERTAIN | HIGH | **Fixed**: Use `{{item_stem}}.md` instead. |
| 05-T2 | — | Merge task can't find per-step notes | LOW | MEDIUM | Auto_verify on T-01 ensures notes exist first. |
| 06-T2 | GAP-12 | Profile mappings not configured → default model → no cost savings | MEDIUM | MEDIUM | **Fixed**: Added verification check. |
| 04-T2 | GAP-13 | `config_vars` built from wrong dict or after shared_context loop | MEDIUM | HIGH | **Fixed**: Explicit code showing ordering in step-04.md. |
| 04-T2 | GAP-14 | No integration test assertions for shared_context variable fix | MEDIUM | MEDIUM | **Fixed**: Added 3 specific test assertions to step-04.md. |
| 06-T2 | GAP-15 | No pass/fail thresholds → ambiguous live test result | MEDIUM | MEDIUM | **Fixed**: Added cost < $12 threshold + diagnostic guidance. |
| 06-T2 | GAP-16 | Live test behavioral claims without concrete checks | LOW | LOW | **Fixed**: Added specific assertion checks for fan-out, verifier, and model metadata. |
| 01 | GAP-17 | `as:` values missing `context.` prefix → `{{context.X}}` templates never resolve | CERTAIN | CRITICAL | **Fixed**: Added warning to step-01.md and step-05.md requiring `context.` prefix on all `as:` values. |

---

## Plan Changes Recommended

All changes applied directly to step files:

### 1. GAP-05: Fix regex for two-pass resolution (step-04.md)
**Change**: Use `_INNER_RE` (`[^{}]+`) for Pass 1, `_OUTER_RE` (`.+?`) for Pass 2.
**Applied**: YES

### 2. GAP-08: Remove task_context when adding fan_out (step-05.md)
**Change**: Explicit instruction to remove `task_context` from fan_out tasks.
**Applied**: YES

### 3. GAP-10: Use `{{file:...}}` for shared_context (step-05.md)
**Change**: All shared_context entries use `"{{file:docs/{{feature}}/plan.md}}"` format.
**Applied**: YES

### 4. GAP-09: Fix double-plan naming (step-05.md)
**Change**: `{{item_stem}}-plan.md` → `{{item_stem}}.md`
**Applied**: YES

### 5. GAP-11: Move auto_verify inside fan_out (step-05.md)
**Change**: Per-item auto_verify with `{{output_path}}` inside `fan_out.auto_verify`.
**Applied**: YES

### 6. GAP-01: Reference doc dependency (step-01.md)
**Change**: Added note about missing `docs/plan-runner/` files.
**Applied**: YES

### 7. GAP-07: shared_context file content note (step-04.md)
**Change**: Note that shared_context entries need `{{file:...}}` wrapper.
**Applied**: YES

### 8. GAP-12: Profile mapping verification (step-06.md)
**Change**: Added early check for profile configuration.
**Applied**: YES

### 9. GAP-13: Variable construction ordering (step-04.md)
**Change**: Added explicit code showing `config_vars` must be built BEFORE shared_context loop, not reusing the later `variables` dict.
**Applied**: YES

### 10. GAP-14: Integration test assertions for shared_context (step-04.md)
**Change**: Added 3 specific test assertions: file ref resolution, nested var resolution, bare path regression guard.
**Applied**: YES

### 11. GAP-15: Pass/fail thresholds for live test (step-06.md)
**Change**: Added pass threshold column (cost < $12 primary gate) and diagnostic guidance for each optimization.
**Applied**: YES

### 12. GAP-16: Specific live test verification assertions (step-06.md)
**Change**: Added concrete checks: concurrent child tasks, attempt count for auto-verify tasks, model metadata per profile.
**Applied**: YES

### 13. GAP-17: `as:` values need `context.` prefix for template resolution (step-01.md, step-05.md)
**Change**: The prompt generator (`prompts.py:84-85`) does `{{key}} → value` replacement from `run_config`. The `context_builder.build_context()` returns keys matching `as:` values directly. If `as: "intent"`, only `{{intent}}` resolves — NOT `{{context.intent}}`. Since the routine templates use `{{context.intent}}`, all `as:` values must be prefixed: `as: "context.intent"`. Added prominent warning to step-01.md (affects all context_from entries) and step-05.md (affects merge task). This is a pre-existing bug in the original routine that must be fixed in the optimized variant.
**Applied**: YES
