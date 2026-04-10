# Improving the `idea-to-plan` Routine

Based on token usage analysis of two production runs (b14aa49f and b46dbe62),
the `idea-to-plan` routine has significant cost and latency inefficiencies.
This document recommends concrete changes using mechanisms that already exist
in the orchestrator: `context_from`, `fan_out`, agent profiles, and
auto-verify-only verification.

**Baseline (run b46dbe62, Opus):** $18.28, 70 minutes, 703 actions, 41% duplicate reads.

**Target after all recommendations:** ~$5–7, 20–25 minutes.

---

## Table of Contents

1. [R1: Add `context_from` to every task](#r1-add-context_from-to-every-task)
2. [R2: Fan-out Create Step Files](#r2-fan-out-create-step-files)
3. [R3: Fan-out Simulate Execution](#r3-fan-out-simulate-execution)
4. [R4: Use profiles to route mechanical tasks to cheaper models](#r4-use-profiles-to-route-mechanical-tasks-to-cheaper-models)
5. [R5: Drop LLM verification on mechanical tasks](#r5-drop-llm-verification-on-mechanical-tasks)
6. [R6: Embed reference docs in prompts](#r6-embed-reference-docs-in-prompts)
7. [R7: Suppress source code exploration in early tasks](#r7-suppress-source-code-exploration-in-early-tasks)
8. [Summary](#summary)
9. [Implementation order](#implementation-order)
10. [What this does NOT address](#what-this-does-not-address)

---

## R1: Add `context_from` to every task

**Problem:** Each task starts a fresh agent session with no memory. By task 6,
the agent reads 52 files to rebuild context that prior tasks already had.
`intent.md` alone was read 17+ times across the run.

**Root cause:** Several tasks (S-01/T-01, S-04/T-01, S-05/T-01) lack
`context_from` declarations. The agent discovers files by trial and error.

**Fix:** Add `context_from` entries so the orchestrator injects file contents
directly into the prompt. The agent sees the content immediately — no Read
calls, no discovery phase.

### Current state

| Step | Task | Has `context_from`? |
|------|------|---------------------|
| S-01 | Generate Initial Artifacts | No |
| S-02 | Gather Requirements | Yes (intent, plan, architecture) |
| S-03 | Create Step Plans | Yes (plan, architecture) |
| S-04 | Create Step Files | No |
| S-05 | Simulate Execution | No |
| S-06 | Cross-Check Artifacts | Yes (intent, plan, dry_run) |
| S-08 | Generate Summary | No |
| S-08 | Create Routine YAML | No |

### Recommended additions

**S-04/T-01 (Create Step Files):** Needs plan, architecture, clarifications,
and all step plans:

```yaml
context_from:
  - artifact: "docs/{{feature}}/plan.md"
    as: "plan"
    required: true
  - artifact: "docs/{{feature}}/architecture.md"
    as: "architecture"
    required: true
  - artifact: "docs/{{feature}}/clarifications.md"
    as: "clarifications"
    required: false
```

Step plan files can't be enumerated statically (count varies per run), so
the task_context should instruct the agent: "Read all `docs/{{feature}}/step-*-plan.md`
files" — but the core docs above eliminate the majority of discovery reads.

**S-05/T-01 (Simulate Execution):** Needs all output artifacts:

```yaml
context_from:
  - artifact: "docs/{{feature}}/intent.md"
    as: "intent"
    required: true
  - artifact: "docs/{{feature}}/plan.md"
    as: "plan"
    required: true
  - artifact: "docs/{{feature}}/architecture.md"
    as: "architecture"
    required: true
  - artifact: "docs/{{feature}}/clarifications.md"
    as: "clarifications"
    required: false
```

**S-06/T-01 (Cross-Check):** Already has intent, plan, dry_run. Add:

```yaml
  - artifact: "docs/{{feature}}/architecture.md"
    as: "architecture"
    required: true
  - artifact: "docs/{{feature}}/clarifications.md"
    as: "clarifications"
    required: false
```

**S-08/T-01 (Generate Summary):** Needs the core docs + dry-run notes:

```yaml
context_from:
  - artifact: "docs/{{feature}}/intent.md"
    as: "intent"
    required: true
  - artifact: "docs/{{feature}}/plan.md"
    as: "plan"
    required: true
  - artifact: "docs/{{feature}}/dry-run-notes.md"
    as: "dry_run"
    required: false
  - artifact: "docs/{{feature}}/verification-report.md"
    as: "verification"
    required: false
```

**S-08/T-02 (Create Routine YAML):** Needs the step files + plan:

```yaml
context_from:
  - artifact: "docs/{{feature}}/intent.md"
    as: "intent"
    required: true
  - artifact: "docs/{{feature}}/plan.md"
    as: "plan"
    required: true
  - artifact: "docs/{{feature}}/architecture.md"
    as: "architecture"
    required: true
```

**Estimated impact:** Eliminates 8–20 Read calls per task. Across 9 tasks,
saves ~100+ tool calls and the cache tokens they accumulate. **~30–40% token
reduction.**

---

## R2: Fan-out Create Step Files

**Problem:** S-04/T-01 (Create Step Files) writes N step files sequentially.
In run b46dbe62, this was 8 files over 16 minutes with 127 actions. Each
step file is independent — it only needs the corresponding step plan plus
shared context.

**Fix:** Use `fan_out` to process step plans in parallel:

```yaml
- id: "S-04"
  title: "Task Breakdown"
  tasks:
    - id: "T-01"
      title: "Create Step Files"
      fan_out:
        input_glob: "docs/{{feature}}/step-*-plan.md"
        output_pattern: "docs/{{feature}}/steps/{{item_stem}}.md"
        per_item_prompt: |
          Convert this step plan into an executable step file.

          STEP PLAN:
          {{item_content}}

          Write the step file to {{output_path}}.

          Follow docs/plan-runner/step-files.md for format.

          Each task must be:
          - Atomic (<5 files, <500 LOC)
          - Independently verifiable
          - Runnable in sequence
          - Linked to relevant context
        shared_context:
          - "docs/{{feature}}/plan.md"
          - "docs/{{feature}}/architecture.md"
          - "docs/{{feature}}/clarifications.md"
          - "docs/plan-runner/step-files.md"
        max_concurrent: 4
        max_attempts: 2
        auto_verify:
          items:
            - id: "step_file_exists"
              cmd: "test -f {{output_path}}"
              must: true
```

The `item_stem` for `step-03-plan.md` resolves to `step-03-plan`. To get
`step-03.md` as output, the `output_pattern` might need adjustment based
on the naming convention, or the `per_item_prompt` can instruct the agent
on the exact output filename.

**Estimated impact:** 16 min → ~4 min (4 concurrent workers). Each sub-agent
reads only its plan + 4 shared files instead of all plans. **~60% fewer reads
for this task.**

---

## R3: Fan-out Simulate Execution

**Problem:** S-05/T-01 (Simulate Execution) analyses each step's failure
modes sequentially. In run b46dbe62, this took 9 minutes with 113 actions
and was the highest cache-token task (2.57M).

**Fix:** Fan out over step files, then merge results:

```yaml
- id: "S-05"
  title: "Dry Run & Failure Mode Analysis"
  tasks:
    - id: "T-01"
      title: "Simulate Execution Per Step"
      fan_out:
        input_glob: "docs/{{feature}}/steps/step-*.md"
        output_pattern: "docs/{{feature}}/dry-run/{{item_stem}}-notes.md"
        per_item_prompt: |
          Simulate execution of this step against the codebase.

          STEP FILE:
          {{item_content}}

          For each task in this step:
          1. Walk through execution and capture assumptions, expected outputs, blockers
          2. Identify failure modes (wrong file refs, wrong names, format issues,
             missing persistence mappings, broken tests)
          3. Propose hardening actions for each failure mode
          4. Apply fixes directly to the step file at {{item_path}}

          Save analysis to {{output_path}} with sections:
          - Simulation results
          - Failure modes (table: task, mode, likelihood, hardening action)
          - Changes applied to step file (list what you changed)
        shared_context:
          - "docs/{{feature}}/intent.md"
          - "docs/{{feature}}/plan.md"
          - "docs/{{feature}}/architecture.md"
        max_concurrent: 4
        max_attempts: 2
        auto_verify:
          items:
            - id: "notes_exist"
              cmd: "test -f {{output_path}}"
              must: true

    - id: "T-02"
      title: "Merge Dry Run Notes"
      profile: "summarizer"
      context_from:
        - artifact: "docs/{{feature}}/intent.md"
          as: "intent"
          required: true
      task_context: |
        Merge all per-step dry-run notes from docs/{{feature}}/dry-run/
        into a single docs/{{feature}}/dry-run-notes.md.

        Include:
        - Combined failure mode table (all steps)
        - Persistence mapping audit (if any step adds state fields)
        - Summary of all changes applied to step files
        - Cross-step risks (dependencies between steps that could fail)
      requirements:
        - id: "R1"
          desc: "Merged dry-run-notes.md covers all steps"
          priority: critical
      auto_verify:
        items:
          - id: "merged_notes_exist"
            cmd: "test -f docs/{{feature}}/dry-run-notes.md"
            must: true
```

**Estimated impact:** 9 min → ~3 min. Each sub-agent reads only its step file
+ 3 shared docs instead of all step files. The merge task (T-02) is cheap
and mechanical. **~70% fewer reads for this step.**

---

## R4: Use profiles to route mechanical tasks to cheaper models

**Problem:** Run b46dbe62 used Opus ($18.28) for all 9 tasks. Several tasks
are mechanical and don't need deep reasoning.

**Fix:** Set `profile` on tasks to route them to appropriate models.
Configure profile-to-model mappings in agent settings:

| Profile | Model | Use case |
|---------|-------|----------|
| `architect` | claude-opus-4-6 | Complex design, step planning |
| `coder` | claude-sonnet-4-6 | Implementation, routine YAML creation |
| `summarizer` | claude-haiku-4-5 | Summarization, formatting, approval |

### Per-task profile assignments

```yaml
# S-01/T-01: Generate Initial Artifacts — needs deep reasoning
profile: "architect"

# S-02/T-01: Gather Requirements — needs reasoning for good questions
profile: "architect"

# S-03/T-01: Create Step Plans — needs architectural reasoning
profile: "architect"

# S-04/T-01: Create Step Files — mechanical translation of plans
profile: "coder"

# S-05/T-01: Simulate Execution — needs reasoning per step
profile: "architect"

# S-05/T-02: Merge Dry Run Notes — summarization
profile: "summarizer"

# S-06/T-01: Cross-Check Artifacts — checklist verification
profile: "coder"

# S-07/T-01: Human Final Approval — trivial acknowledgement
profile: "summarizer"

# S-08/T-01: Generate Summary — straightforward extraction
profile: "summarizer"

# S-08/T-02: Create Routine YAML — mechanical translation
profile: "coder"
```

### Cost estimate with profiles

| Task | Current (Opus) | With profile | Savings |
|------|---------------|-------------|---------|
| Generate Initial Artifacts | $1.21 | $1.21 (architect/Opus) | $0 |
| Gather Requirements | $2.38 | $2.38 (architect/Opus) | $0 |
| Create Step Plans | $2.27 | $2.27 (architect/Opus) | $0 |
| Create Step Files | $3.50 | $1.05 (coder/Sonnet) | $2.45 |
| Simulate Execution | $3.16 | $3.16 (architect/Opus) | $0 |
| Cross-Check Artifacts | $2.85 | $0.85 (coder/Sonnet) | $2.00 |
| Human Final Approval | $0.25 | $0.03 (summarizer/Haiku) | $0.22 |
| Generate Summary | $0.93 | $0.10 (summarizer/Haiku) | $0.83 |
| Create Routine YAML | $1.97 | $0.60 (coder/Sonnet) | $1.37 |
| **Total** | **$18.28** | **~$11.41** | **~$6.87** |

**Estimated impact: ~$5–7 savings (30–38%).**

Note: the merge task (T-02) from R3 adds a small cost (~$0.10 at Haiku).
Fan-out sub-agents inherit the parent task's profile, so Simulate sub-agents
still use `architect`.

---

## R5: Drop LLM verification on mechanical tasks

**Problem:** Every task currently has a verifier rubric, spawning an LLM
agent to grade the output. For planning tasks (no code), the verifier
re-reads all outputs to grade them. This roughly doubles the reads and
cost for each task.

**Fix:** For tasks where auto-verify commands can fully validate the output,
remove the `verifier.rubric`. When a task has only `auto_verify.items` and
no rubric, the executor skips the LLM verifier entirely and auto-completes
verification.

### Tasks where LLM verification can be replaced with auto-verify only

**S-07/T-01 (Human Final Approval):**
The task is "acknowledge approval and submit." LLM verification is pointless.

```yaml
# Remove verifier.rubric entirely. Keep:
auto_verify:
  items:
    - id: "no_changes"
      cmd: "test $(git diff --name-only | wc -l) -eq 0"
      must: true
# No verifier → auto-completes
```

**S-08/T-01 (Generate Summary):**
Auto-verify can check the file exists and has expected sections:

```yaml
auto_verify:
  items:
    - id: "summary_exists"
      cmd: "test -f docs/{{feature}}/plan-summary.md"
      must: true
    - id: "has_sections"
      cmd: "grep -q 'Intent' docs/{{feature}}/plan-summary.md && grep -q 'Risks' docs/{{feature}}/plan-summary.md"
      must: true
# Remove verifier.rubric → no LLM verification
```

**S-04/T-01 (Create Step Files) — if using fan-out:**
Each fan-out child already has `auto_verify`. The outer verification can
use a lighter rubric or auto-verify only.

### Tasks where LLM verification should remain

- **S-01/T-01** (Generate Initial Artifacts) — quality of initial plan matters
- **S-02/T-01** (Gather Requirements) — cross-consistency is subtle
- **S-03/T-01** (Create Step Plans) — contract quality needs judgement
- **S-05/T-01** (Simulate Execution) — gap identification quality matters
- **S-06/T-01** (Cross-Check) — this IS the verification step
- **S-08/T-02** (Create Routine YAML) — keep for validation correctness

### Using a lighter verifier model

For tasks that keep LLM verification, the verifier doesn't need the same
model as the builder. Set `verifier_model` at run creation:

```json
{
  "verifier_model": "claude-sonnet-4-6"
}
```

This applies to all tasks in the run. The verifier grades against the rubric
using Sonnet instead of Opus. Since grading is less demanding than generation,
this works well for planning rubrics.

**Estimated impact:** Removing LLM verification on 2–3 tasks saves ~$1–2.
Using a lighter verifier model on remaining tasks saves ~$2–3 more.

---

## R6: Embed reference docs in prompts

**Problem:** The agent reads the same reference documents in nearly every
task. `docs/plan-runner/step-files.md` is always read by Create Step Files.
`docs/plan-runner/idea_to_plan_stripped.md` is always read by Generate
Initial Artifacts. These are static and predictable.

**Fix:** Use `context_from` to inject them, or embed their content directly
in `task_context`. For files that are always needed:

```yaml
# S-01/T-01: Generate Initial Artifacts
context_from:
  - artifact: "docs/plan-runner/idea_to_plan_stripped.md"
    as: "checklist"
    required: true
  - artifact: "docs/plan-runner/idea_to_plan_detailed.md"
    as: "principles"
    required: true

# S-04/T-01: Create Step Files
context_from:
  - artifact: "docs/plan-runner/step-files.md"
    as: "format_guide"
    required: true
```

The cross-run comparison showed these reference files are **100% stable** —
both runs read them. Pre-loading eliminates the discovery phase.

**Estimated impact:** ~10% fewer tool calls per task. Small per-task but
compounds across 9 tasks.

---

## R7: Suppress source code exploration in early tasks

**Problem:** In run b46dbe62, the Generate Initial Artifacts task read 18
source code files (agent implementations, API routers, UI components) to
understand the system before creating planning docs. Run 1c900b3d used
scaffolding templates instead and was equally successful but cheaper.

**Fix:** Add explicit instructions to the task context discouraging source
code exploration. The scaffolding templates and `codebase_context` input
exist for this purpose:

```yaml
# S-01/T-01: Generate Initial Artifacts
task_context: |
  ...existing prompt...

  IMPORTANT: Do NOT read source code files (src/, ui/) to understand the
  project. The CODEBASE CONTEXT input above and the reference docs below
  contain everything you need. Reading source code wastes time and budget
  without improving plan quality.
```

This is a prompt-level fix, not a system mechanism. It relies on the agent
following instructions, which is imperfect but effective in practice (run
1c900b3d demonstrated this).

**Estimated impact:** Eliminates ~20 Read calls in the first task. Saves
~$0.50–1.00 and 5 minutes.

---

## Summary

| Recommendation | Mechanism | Token savings | Cost savings | Time savings |
|---------------|-----------|---------------|-------------|-------------|
| R1: `context_from` everywhere | `context_from` | ~30–40% | ~$5–7 | ~20 min |
| R2: Fan-out step files | `fan_out` | ~60% for S-04 | ~$1–2 | ~12 min |
| R3: Fan-out simulation | `fan_out` | ~70% for S-05 | ~$1–2 | ~6 min |
| R4: Model profiles | `profile` | — | ~$5–7 | — |
| R5: Auto-verify only | Remove rubric | ~50% for affected tasks | ~$3–5 | ~10 min |
| R6: Embed reference docs | `context_from` | ~10% | ~$1 | ~5 min |
| R7: Suppress exploration | Prompt text | ~20 reads in S-01 | ~$0.50–1 | ~5 min |

**Combined estimate (conservative, accounting for overlap):**

| Metric | Before | After | Reduction |
|--------|--------|-------|-----------|
| Cost | $18.28 | ~$5–7 | 60–70% |
| Wall-clock | 70 min | 20–25 min | 65% |
| Tool calls | 703 | ~250–300 | 55–60% |
| Duplicate reads | 103 (41%) | ~10–15 (5%) | 85% |

---

## Implementation order

### Phase 1: Quick wins (routine YAML edits only)

1. **R1** — Add `context_from` to S-04, S-05, S-06, S-08 tasks. Mechanical
   YAML edits, zero code changes. Highest single impact.

2. **R7** — Add exploration suppression to S-01 task context. One line of
   prompt text.

3. **R6** — Add reference doc `context_from` entries to S-01, S-04. Mechanical
   YAML edits.

**Effort:** ~30 minutes. **Impact:** ~40% cost reduction.

### Phase 2: Profile configuration

4. **R4** — Add `profile` fields to each task in the routine YAML. Configure
   profile-to-model mappings in agent settings (Agents page or seed config).

5. **R5** — Remove `verifier.rubric` from S-07/T-01 and S-08/T-01. Add
   structural auto-verify commands as replacements. Set `verifier_model`
   to Sonnet for the run.

**Effort:** ~1 hour. **Impact:** additional ~$5–7 savings per run.

### Phase 3: Parallelism

6. **R2** — Convert S-04/T-01 to fan-out. Requires restructuring the task
   config and adjusting the outer verification. Test with a small plan first.

7. **R3** — Convert S-05/T-01 to fan-out + merge. More complex because the
   merge task (T-02) needs to synthesise cross-step risks. Test carefully.

**Effort:** ~2–3 hours. **Impact:** ~60% wall-clock reduction for S-04 + S-05.

---

## What this does NOT address

- **Agent died events (20 restarts in b46dbe62):** This is a server stability
  issue, not a routine design issue. The `server_shutdown` auto-resume
  mechanism mitigates it, but preventing the restarts is a separate concern.

- **Within-task context window eviction:** When an agent reads many files in
  one session, earlier reads get compressed/evicted, causing re-reads within
  the same task. This is an LLM context window limitation, not addressable
  through routine config. Fan-out (R2, R3) partially mitigates this by giving
  each sub-agent a smaller context.

- **ToolSearch cold-start (32 calls):** Every fresh agent session calls
  ToolSearch to discover available tools. This is Claude Code infrastructure
  overhead, not controllable from routine YAML.

- **Variable plan sizes:** A plan with 8 steps inherently costs more than one
  with 3 steps. This scales linearly and is not waste — it's proportional to
  the work being done. Fan-out (R2, R3) makes it scale more efficiently.
