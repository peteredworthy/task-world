# Run Analysis: b46dbe62 (idea-to-plan / agent-runners refactor)

**Date:** 2026-03-06
**Routine:** idea-to-plan
**Feature:** agent-runners refactor
**Runner:** cli_subprocess (claude-opus-4-6)

## Overview

| Metric | Value |
|--------|-------|
| Total cost | $18.28 |
| Wall-clock time | 69.7 minutes |
| Total actions | 703 |
| Cache tokens consumed | 11.6M |
| Output tokens | 199K |
| Tasks (all passed first attempt) | 9 |
| Agent died events | 20 |

## 1. Areas Requiring Large Context

**The top 3 cost tasks consumed 52% of the budget ($9.51):**

| Task | Cost | Cache Tokens | Why |
|------|------|-------------|-----|
| Create Step Files | $3.50 | 1.88M | Needed to read all prior artifacts (intent, plan, arch, clarifications) + reference docs + write 8 step files. 127 actions. |
| Simulate & Failure Analysis | $3.16 | 2.57M | Read every step file multiple times to cross-reference failure modes. Highest cache usage of any task. |
| Cross-Check Artifacts | $2.85 | 1.61M | Re-read nearly everything to validate consistency. 52 reads with 30 duplicates (58% waste). |

The fundamental problem: **each task starts a fresh agent session with no memory of what prior tasks produced.** Every task re-reads the same reference docs (`idea_to_plan_detailed.md`, `AGENTS.md`, templates) and every task re-reads the growing set of prior outputs (intent.md, plan.md, architecture.md, step files). By task 6 (Cross-Check), the agent is reading 52 files just to rebuild context that earlier tasks already had.

## 2. Token Waste

### Duplicate file reads: ~40% of all reads were redundant
- **249 total reads, 103 duplicates (41%)**
- Worst offender: Cross-Check read 52 files, only 22 unique
- `intent.md` was read 17+ times across the run
- `clarifications.md` was read 12+ times
- `plan.md` was read 11+ times

### ToolSearch overhead: 32 calls
Every task session starts cold and must call `ToolSearch` to load tools (Read, Write, Bash, etc.) before doing anything. That's 32 calls producing zero value — pure ceremony.

### Agent died events: 20 restarts
Server restarts caused `agent_not_running_on_startup` 20 times. Each restart means the agent re-initialises from scratch, re-reads everything, and loses any in-context understanding.

### Within-task re-reads
Even within a single task, files get re-read because the context window fills and earlier reads get compressed/evicted. The Simulate task re-read `step-08.md` 4 times and `dry-run-notes.md` 4 times within one session.

## 3. Where Sub-Agents Would Have Helped

### Parallelisable work (wall-clock savings)
- **Create Step Files** (16 min) wrote 8 separate step files sequentially. Each step file is independent — 8 sub-agents could have done this in ~2 min.
- **Simulate & Failure Analysis** analysed each step's failure modes sequentially. 8 parallel sub-agents (one per step) would cut 9 min to ~2 min.
- **Cross-Check Artifacts** checked consistency across all artifacts sequentially. Could split into parallel checks: intent<>plan, plan<>steps, steps<>architecture.

### Context isolation (token savings)
Sub-agents with focused prompts wouldn't need to read the entire artifact set. A sub-agent writing step-03.md only needs: intent.md, plan.md (the step-3 section), architecture.md (relevant section), and the step-file template. That's ~4 files instead of 29.

**Estimated impact:** Parallelism could cut wall-clock from 70 min to ~35 min. Context isolation could reduce total tokens by ~30-40%.

## 4. Where a Simpler/Cheaper Model Could Be Used

| Task | Current Cost | Could Use Cheaper? | Reasoning |
|------|-------------|-------------------|-----------|
| Human Final Approval | $0.25 | Haiku ($0.03) | Just formats a summary for human review — no reasoning needed |
| Generate Summary | $0.93 | Sonnet ($0.30) | Summarising existing artifacts is straightforward extraction |
| Create Routine YAML | $1.97 | Sonnet ($0.60) | Mechanical translation of step files into YAML structure |
| Cross-Check Artifacts | $2.85 | Sonnet ($0.90) | Checklist-style verification, not creative work |
| Generate Initial Artifacts | $1.21 | Maybe Sonnet | Depends on quality requirements for initial drafts |

**Tasks that genuinely need Opus:** Create Step Plans ($2.27), Create Step Files ($3.50), Simulate & Failure Analysis ($3.16) — these require deep reasoning about dependencies, failure modes, and architectural tradeoffs.

**Estimated savings from model selection:** ~$4-5 of the $18.28 (25-30%).

## 5. Where Providing Summaries Would Have Been Valuable

### Inter-task summaries (the biggest win)
Right now each task re-reads everything from scratch. If the orchestrator generated a **running context summary** after each task completed, subsequent tasks could receive:
- A 500-token summary of what was decided/produced so far
- Only the specific files they need to modify/reference

For example, by task 6 (Cross-Check), instead of reading 52 files, the agent could receive:
- A summary of all artifacts and their key decisions (~1K tokens)
- Just the specific files to validate (~5 files)

**Estimated token reduction: 50-60%** for later tasks.

### Summarised reference docs
The agent reads `idea_to_plan_detailed.md`, `AGENTS.md`, templates, and format docs repeatedly. These are static reference material. Pre-summarising them into task-specific instruction sets would save significant context.

## 6. File Search Overhead

**312 file-finding operations** (249 Read + 63 Glob) out of 703 total actions = **44% of all actions were just finding and reading files.**

Breaking this down:
- 249 Read calls (35% of all actions)
- 63 Glob calls (9% of all actions)
- 4 Grep calls (negligible)
- Only 277 Bash + 38 Write + 24 Edit = actual productive work

The agent spends nearly half its time just orienting itself in the codebase and re-ingesting information.

## 7. Additional Efficiency Factors

### a) Cold-start penalty per task
Each of the 9 tasks starts a fresh Claude session. System prompt, CLAUDE.md, AGENTS.md, and other auto-loaded context gets re-sent every time. That's ~5-10K tokens of fixed overhead x 9 = ~50-90K tokens burned on boilerplate.

### b) Verification overhead
Every task has auto-verify + LLM verification. For a planning run (no code), the verifier re-reads all outputs to grade them. The verification step roughly doubles the reads for each task. Consider whether planning tasks need full LLM verification or if auto-verify (file existence + structure checks) is sufficient.

### c) Sequential step execution
The 8-step pipeline is fully sequential. Steps 1-3 (plan > requirements > step plans) must be sequential, but steps like "Generate Summary" and "Create Routine YAML" in the final step could run in parallel.

### d) Prompt engineering for focus
The task prompts reference docs like `idea_to_plan_detailed.md` and `idea_to_plan_stripped.md` — the agent reads both, but one is a subset of the other. Consolidating reference material or embedding the relevant section directly in the prompt would eliminate discovery reads.

### e) No checkpoint/resume within tasks
When an agent dies (20 times in this run), it restarts from scratch. If the orchestrator could snapshot the agent's working state (which files it's already processed, what decisions it's made), restart cost would drop from "full re-read" to "resume from checkpoint."

### f) Bash as investigation tool
277 Bash calls (39% of actions). Many of these are likely `ls`, `cat`, `find` equivalents or git operations to understand repository state. A pre-built workspace summary (file tree, recent commits, key config) injected into the prompt would eliminate many of these.

## 8. Summary of Potential Savings

| Optimisation | Token Savings | Cost Savings | Time Savings |
|-------------|--------------|-------------|-------------|
| Inter-task summaries | ~50% | ~$9 | ~20 min |
| Sub-agent parallelism | ~20% (less duplication) | ~$3 | ~25 min |
| Cheaper models for mechanical tasks | — | ~$4-5 | — |
| Eliminate duplicate reads | ~15% | ~$2-3 | ~10 min |
| Pre-loaded tools (no ToolSearch) | ~2% | ~$0.50 | ~2 min |
| Pre-built workspace context | ~10% | ~$1-2 | ~5 min |

**Theoretical optimised run: ~$5-7 in 20-25 minutes** vs the current $18.28 in 70 minutes — roughly **60% cost reduction and 65% time reduction** while maintaining the same 8-stage rigour.

The single highest-impact change is **inter-task context passing** — giving each task a summary of what prior tasks produced rather than making it rediscover everything from scratch.

## 9. Per-Stage File Access Patterns

See [file-access-patterns.md](file-access-patterns.md) for detailed per-stage breakdown.

## 10. Cross-Run Stability

See [cross-run-comparison.md](cross-run-comparison.md) for comparison across multiple idea-to-plan runs.

## 11. What Simulate & Cross-Check Actually Caught

### Simulate & Failure Analysis ($3.16) — high value
- **20 concrete failure modes**: rope vs Protocol classes, Alembic autogenerate drop+create
  instead of rename, parsers/ subdirectory not mentioned, SQLite batch mode required
- **6 critical gaps** in step files: wrong file paths (`agentConfigUtils.ts` location),
  missing `batch_alter_table()` instructions, missing default prompt text, non-idempotent seeding
- **6 important gaps**: no rope fallback, inline components assumed to be separate files,
  phase name mismatches ("build" vs "building")
- **4 nice-to-haves**: checkpoint verification between tasks, sidebar UX differentiation

### Cross-Check ($2.85) — mostly redundant with simulate
- **Intent-to-plan mapping**: confirmed all 10 scope items map to milestones (zero issues found)
- **Plan-to-step alignment**: confirmed all 8 milestones have step plans and step files
- **Gap remediation tracking** (unique value): discovered 12 of 16 dry-run recommendations
  were still UNRESOLVED in step files — the simulate step found problems but step files
  weren't updated
- **Architecture & clarification consistency**: verified data models, APIs, flows, and all
  10 Q&A responses reflected in artifacts

### Assessment
- Intent-to-plan alignment check found zero issues — could be a script
- ~70% of Cross-Check (sections 1-3, 5-6) is structural alignment that could be scripted
  or done by a cheap model
- Only gap remediation tracking (section 4) required reading content — a single Sonnet task (~$0.30)
- Simulate step found real bugs but should be parallelised per step (~$1 instead of $3.16)
- Combined savings: $6.01 → ~$1.50

## 12. Parallelisation Design Options

### The problem
Simulate and Cross-Check tasks process items sequentially (step-by-step, file-by-file).
Sub-agents per step would cut wall-clock time 8x and reduce context per agent. But the
orchestrator needs a general mechanism — not one hard-coded to "steps".

### Option A: File-driven fan-out
The task prompt declares a glob pattern. The orchestrator finds matching files and spawns
one sub-agent per file, each receiving the file content as context.

```yaml
fan_out:
  glob: "docs/{{feature}}/steps/step-*.md"
  context_per_item: |
    Simulate execution of this step against the codebase.
    STEP FILE: {{item_content}}
    INTENT: {{docs/{{feature}}/intent.md}}
  merge: concatenate  # or "summarise"
```

**Pros**: General — works for any task that processes a set of files. Naturally adapts
to 3-step or 8-step plans. No orchestrator knowledge of "what a step is".

**Cons**: Assumes 1:1 relationship between files and parallelisable work units. Not all
tasks decompose this way (e.g., "check consistency between all artifacts" is inherently
cross-cutting).

### Option B: Explicit sub-task list in routine YAML
The routine author declares sub-tasks within a task. The orchestrator runs them in parallel.

```yaml
tasks:
  - id: simulate
    parallel_sub_tasks:
      - id: sim-s1
        context: "Simulate step 1: {{file:docs/{{feature}}/steps/step-01.md}}"
      - id: sim-s2
        context: "Simulate step 2: {{file:docs/{{feature}}/steps/step-02.md}}"
```

**Pros**: Explicit control. Works for non-file-based parallelism too.
**Cons**: Verbose. Doesn't adapt to variable step counts. Routine author must enumerate.

### Option C: Dynamic fan-out from prior task output
A task declares it fans out over items produced by a prior task. The orchestrator reads
the prior task's output to determine the fan-out set.

```yaml
tasks:
  - id: create-steps
    produces: "docs/{{feature}}/steps/step-*.md"
  - id: simulate
    fan_out:
      from_task: create-steps
      per_item: "Simulate this step: {{item_content}}"
```

**Pros**: Fully dynamic — adapts to whatever the prior task produced.
**Cons**: Requires the orchestrator to inspect filesystem after a task completes to
discover outputs. Adds coupling between tasks.

### Option D: Hybrid — file glob with shared context injection
Combine file-driven fan-out with a mechanism to inject shared context (summaries, reference
docs) into each sub-agent. This addresses both the parallelisation and the context waste.

```yaml
tasks:
  - id: simulate
    fan_out:
      glob: "docs/{{feature}}/steps/step-*.md"
      shared_context:
        - "{{file:docs/{{feature}}/intent.md}}"
        - "{{file:docs/{{feature}}/plan.md}}"
        - "{{summary:prior_tasks}}"  # orchestrator-generated summary
      per_item_prompt: |
        Simulate execution of this step. Identify failure modes, wrong assumptions,
        and missing instructions.
        STEP: {{item_content}}
      merge: concatenate_to_file
      merge_target: "docs/{{feature}}/dry-run-notes.md"

```

**Pros**: General, adapts to variable counts, solves context waste simultaneously.
**Cons**: More complex orchestrator machinery. Merge strategy needs thought (concatenate
vs summarise vs structured merge).

### Recommendation: file-mapped fan-out (simplified)

#### Design

```yaml
tasks:
  # Fan-out task: spawns parallel sub-agents, one per matching file
  - id: simulate
    fan_out:
      input_glob: "docs/{{feature}}/steps/step-*.md"
      output_pattern: "docs/{{feature}}/dry-run/{{item_stem}}-notes.md"
      max_attempts: 4        # inner retry limit (mechanical verification only)
      shared_context:
        - "{{file:docs/{{feature}}/intent.md}}"
        - "{{file:docs/{{feature}}/plan.md}}"
      per_item_prompt: |
        Simulate execution of this step. Write your analysis to {{output_path}}.
        STEP: {{item_content}}
      auto_verify:           # inner verification — mechanical only, per sub-agent
        items:
          - id: output_exists
            cmd: "test -f {{output_path}}"
          - id: has_failure_modes
            cmd: "grep -q 'Failure Mode' {{output_path}}"
    # outer verification — LLM verifier checks the full set
    verifier:
      rubric:
        - id: completeness
          text: "Every input step file has a corresponding analysis in dry-run/"
        - id: consistency
          text: "No contradictions between per-step analyses"
    max_attempts: 2          # outer retry limit

  # Script-only task: no LLM, just runs a command. Fail = pause.
  - id: combine-dry-run
    script: |
      cat docs/{{feature}}/dry-run/step-*-notes.md > docs/{{feature}}/dry-run-notes.md
```

#### How it works

1. **Fan-out**: orchestrator resolves `input_glob`, derives output paths, spawns one
   sub-agent per file in parallel. Each sub-agent receives `shared_context` +
   `per_item_prompt` with `{{item_content}}` and `{{output_path}}` interpolated.

2. **Inner loop**: each sub-agent has only `auto_verify` (mechanical checks). If the
   script fails, the sub-agent retries with the script output as feedback, up to
   `max_attempts: 4`. No LLM verifier at the inner level.

3. **Sub-agent failure = task failure**: if ANY sub-agent exhausts its retries, the
   entire fan-out task fails and the run pauses. With 4 mechanical retries, if it
   still can't pass then something is genuinely wrong — human intervention needed.

4. **Outer verification**: once all sub-agents pass their inner checks, the outer
   LLM verifier checks the full set of output files. If it fails, ALL sub-agents
   re-run with the verifier feedback injected into their prompts. We accept the
   cost that most will produce the same output — simpler than tracking which ones
   need changes based on cross-cutting feedback.

5. **No roll-up in fan-out**: if you want to concatenate or summarise the outputs,
   add a separate task after. This keeps fan-out simple.

#### Script-only tasks

A new task type: `script` instead of `task_context`. No LLM involved.

- Orchestrator runs the script in the worktree
- Exit 0 = task completes successfully
- Non-zero exit = task fails, run pauses
- Useful for: concatenation, file moves, running test suites, generating reports
  from templates, any mechanical transformation

This also covers the "automated Cross-Check" case: a script that greps intent.md
for scope items and checks each appears in plan.md. Zero LLM cost for structural
alignment checks.

#### Why file mapping matters

The known input→output mapping gives us three things for free:

1. **Selective retry on outer failure.** When outer verification fails with feedback
   like "step-03 analysis misses the DB migration risk", all sub-agents re-run. But
   future optimisation could parse feedback to selectively retry — the file mapping
   makes this possible without schema changes.

2. **Resumability.** If the run pauses mid-fan-out (5 of 8 sub-agents done, server
   restart), the orchestrator globs `output_pattern`, diffs against `input_glob`,
   and only spawns sub-agents for inputs whose outputs are missing. The filesystem
   IS the state.

3. **Composability.** Downstream tasks (script-only or LLM) can reference the fan-out
   outputs via glob: `{{files:docs/{{feature}}/dry-run/*.md}}`. No special coupling
   between the fan-out task and its consumers.

#### Resolved design decisions

- **Concurrency limit**: configurable in YAML via `max_concurrent`, default 4.
  Orchestrator runs up to N sub-agents at a time, queuing the rest.
- **Outer retry feedback**: full verifier comment prepended to every sub-agent's
  prompt on re-run. Simple, no parsing. Can optimise later.
- **Shared worktree**: all sub-agents share the task's worktree. `output_pattern`
  enforces they write to different files. No isolation overhead.

#### Updated schema

```yaml
tasks:
  - id: simulate
    fan_out:
      input_glob: "docs/{{feature}}/steps/step-*.md"
      output_pattern: "docs/{{feature}}/dry-run/{{item_stem}}-notes.md"
      max_attempts: 4          # inner retries per sub-agent (mechanical only)
      max_concurrent: 4        # parallel sub-agents at a time, default 4
      shared_context:
        - "{{file:docs/{{feature}}/intent.md}}"
        - "{{file:docs/{{feature}}/plan.md}}"
      per_item_prompt: |
        Simulate execution of this step. Write your analysis to {{output_path}}.
        STEP: {{item_content}}
      auto_verify:
        items:
          - id: output_exists
            cmd: "test -f {{output_path}}"
          - id: has_failure_modes
            cmd: "grep -q 'Failure Mode' {{output_path}}"
    verifier:
      rubric:
        - id: completeness
          text: "Every input step file has a corresponding analysis"
        - id: consistency
          text: "No contradictions between per-step analyses"
    max_attempts: 2            # outer retries (re-runs all sub-agents with feedback)

  - id: combine-dry-run
    script: |
      cat docs/{{feature}}/dry-run/step-*-notes.md > docs/{{feature}}/dry-run-notes.md
```
