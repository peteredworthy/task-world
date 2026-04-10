# D4: Context Utilization Analysis

**Run analyzed:** `8bf41c40-9db2-49a6-b188-0145631ce134`
**Tasks examined:** 8 completed (passed) tasks with longest agent output
**Date:** 2026-03-04

## Methodology

Each builder prompt was split into 8 sections based on `##` headers. For each
section, keywords and phrases were extracted and searched for in the agent's
output text. Two levels of analysis were performed:

1. **Keyword match** -- what % of distinctive terms from each prompt section
   appear somewhere in the agent output.
2. **Behavioral adherence** -- did the agent actually follow the instruction
   (e.g., update checklist, attempt git commit), even if it never quoted the
   instruction text.

The agent_output column captures the agent's final summary text across all
builder and verifier attempts for that task, including narrative thinking,
implementation notes, and verification results.

---

## Prompt Structure

Every builder prompt follows this template:

| Section | Avg chars | % of prompt | Content |
|---------|-----------|-------------|---------|
| Role Preamble | 77 | 2.6% | "You are a skilled software developer..." |
| How This Workflow Works | 92 | 3.1% | BUILDER phase description |
| Your Workflow | 1054 | 35.5% | 7-step numbered workflow instructions |
| Important | 387 | 13.0% | 5 MUST/CRITICAL rules |
| Avoiding Loops | 512 | 17.2% | 4 anti-loop heuristics |
| Step Context | 233 avg | 7.8% | Step-level objective (varies per task) |
| Task | 343 avg | 11.6% | Specific implementation task (varies per task) |
| Requirements | 147 avg | 5.0% | 2-3 checklist items (varies per task) |

**Template (identical across all tasks):** 2203 chars (74.2% of prompt)
**Task-specific content:** 766 chars avg (25.8% of prompt)

---

## Per-Task Results

### Task 1: Register All Tools in MCP Server

Prompt: 2878 chars | Output: 13757 chars

| Section | Chars | Keywords found | % |
|---------|-------|----------------|---|
| Role Preamble | 77 | 0/2 | 0% |
| How This Workflow Works | 92 | 2/4 | 50% |
| Your Workflow | 1054 | 8/14 | 57% |
| Important | 387 | 0/5 | 0% |
| Avoiding Loops | 512 | 0/6 | 0% |
| Step Context | 211 | 9/18 | 50% |
| Task | 290 | 5/8 | 63% |
| Requirements | 131 | 14/16 | 88% |

### Task 2: Add Step-Level Tool Hints to CLI Prompt

Prompt: 2886 chars | Output: 11448 chars

| Section | Chars | Keywords found | % |
|---------|-------|----------------|---|
| Role Preamble | 77 | 0/2 | 0% |
| How This Workflow Works | 92 | 2/4 | 50% |
| Your Workflow | 1054 | 7/14 | 50% |
| Important | 387 | 0/5 | 0% |
| Avoiding Loops | 512 | 0/6 | 0% |
| Step Context | 276 | 10/25 | 40% |
| Task | 258 | 11/14 | 79% |
| Requirements | 106 | 8/11 | 73% |

### Task 3: Implement Step-Level Tool Filtering in OpenHands Agent

Prompt: 2956 chars | Output: 9615 chars

| Section | Chars | Keywords found | % |
|---------|-------|----------------|---|
| Role Preamble | 77 | 0/2 | 0% |
| How This Workflow Works | 92 | 2/4 | 50% |
| Your Workflow | 1054 | 8/14 | 57% |
| Important | 387 | 0/5 | 0% |
| Avoiding Loops | 512 | 0/6 | 0% |
| Step Context | 251 | 7/21 | 33% |
| Task | 335 | 10/13 | 77% |
| Requirements | 124 | 11/16 | 69% |

### Task 4: Implement Additive Tool Filtering in Claude SDK Agent

Prompt: 2980 chars | Output: 9598 chars

| Section | Chars | Keywords found | % |
|---------|-------|----------------|---|
| Role Preamble | 77 | 0/2 | 0% |
| How This Workflow Works | 92 | 2/4 | 50% |
| Your Workflow | 1054 | 7/14 | 50% |
| Important | 387 | 0/5 | 0% |
| Avoiding Loops | 512 | 0/6 | 0% |
| Step Context | 194 | 8/18 | 44% |
| Task | 386 | 13/16 | 81% |
| Requirements | 154 | 14/18 | 78% |

### Task 5: Add MCP Server Info to CLI Prompt and .mcp.json

Prompt: 3084 chars | Output: 9253 chars

| Section | Chars | Keywords found | % |
|---------|-------|----------------|---|
| Role Preamble | 77 | 0/2 | 0% |
| How This Workflow Works | 92 | 2/4 | 50% |
| Your Workflow | 1054 | 6/14 | 43% |
| Important | 387 | 0/5 | 0% |
| Avoiding Loops | 512 | 0/6 | 0% |
| Step Context | 276 | 14/25 | 56% |
| Task | 381 | 12/16 | 75% |
| Requirements | 181 | 13/19 | 68% |

### Task 6: Implement MCP Connector Beta Wiring

Prompt: 3036 chars | Output: 8886 chars

| Section | Chars | Keywords found | % |
|---------|-------|----------------|---|
| Role Preamble | 77 | 0/2 | 0% |
| How This Workflow Works | 92 | 2/4 | 50% |
| Your Workflow | 1054 | 8/14 | 57% |
| Important | 387 | 0/5 | 0% |
| Avoiding Loops | 512 | 0/6 | 0% |
| Step Context | 194 | 11/18 | 61% |
| Task | 410 | 11/16 | 69% |
| Requirements | 186 | 10/18 | 56% |

### Task 7: Extend ExecutionContext with Step-Level Fields

Prompt: 2960 chars | Output: 8663 chars

| Section | Chars | Keywords found | % |
|---------|-------|----------------|---|
| Role Preamble | 77 | 0/2 | 0% |
| How This Workflow Works | 92 | 2/4 | 50% |
| Your Workflow | 1054 | 7/14 | 50% |
| Important | 387 | 0/5 | 0% |
| Avoiding Loops | 512 | 0/6 | 0% |
| Step Context | 209 | 12/18 | 67% |
| Task | 382 | 9/15 | 60% |
| Requirements | 123 | 9/11 | 82% |

### Task 8: Implement MCP Config Passthrough to OpenHands Agent

Prompt: 2971 chars | Output: 7364 chars

| Section | Chars | Keywords found | % |
|---------|-------|----------------|---|
| Role Preamble | 77 | 0/2 | 0% |
| How This Workflow Works | 92 | 2/4 | 50% |
| Your Workflow | 1054 | 8/14 | 57% |
| Important | 387 | 0/5 | 0% |
| Avoiding Loops | 512 | 0/6 | 0% |
| Step Context | 251 | 10/21 | 48% |
| Task | 302 | 10/14 | 71% |
| Requirements | 172 | 13/17 | 77% |

---

## Cross-Task Section Summary

| Section | Avg chars | Keyword hit rate | Tasks with any reference |
|---------|-----------|-----------------|--------------------------|
| Role Preamble | 77 | 0% | 0/8 (0%) |
| How This Workflow Works | 92 | 50% | 8/8 (100%) |
| Your Workflow | 1054 | 53% | 8/8 (100%) |
| Important | 387 | 0% | 0/8 (0%) |
| Avoiding Loops | 512 | 0% | 0/8 (0%) |
| Step Context | 233 | 49% | 8/8 (100%) |
| Task | 343 | 72% | 8/8 (100%) |
| Requirements | 147 | 73% | 8/8 (100%) |

---

## Behavioral Adherence Analysis

Beyond keyword matching, did agents actually *follow* the instructions?

### Instructions Followed (100% adherence across all 8 tasks)

| Instruction | Source section | Adherence |
|------------|---------------|-----------|
| Update checklist with R1/R2/R3 markings | Your Workflow | 8/8 |
| Attempt git commit | Your Workflow | 8/8 |
| Submit for verification | Your Workflow | 8/8 |
| Reference the source file path | Task | 8/8 |
| Use function/class names from task | Task | 8/8 |
| Report "blocked" status when applicable | Your Workflow | 8/8 |

### Instructions Not Followed (0% adherence)

| Instruction | Source section | Adherence |
|------------|---------------|-----------|
| Use `git --no-pager` | Your Workflow | 0/8 |
| Mark items `not_applicable` | Your Workflow | 0/8 |
| Mention CRITICAL requirements | Important | 0/8 |
| Reference verifier review process | Important | 0/8 |
| Reference 10-tool-call limit | Avoiding Loops | 0/8 |
| Self-check for repetition/loops | Avoiding Loops | 0/8 |
| Reference the doc path from prompt | Task | 0/8 |

### Note on "Avoiding Loops" -- Ironic Non-Adherence

Despite the "Avoiding Loops" section being 512 chars of anti-loop guidance,
every single agent output shows significant repetition patterns:

- **uv-blocked workaround mentions:** 1-4 per task (avg 2.4)
- **Sandbox/index.lock error mentions:** 6-18 per task (avg 12.5)
- **Rerun/retry mentions:** 1-4 per task (avg 2.4)

Each task's agent output contains 3 separate builder attempt narratives
(the agent was retried when it couldn't git-commit due to sandbox
restrictions). The agent repeatedly discovered the same sandbox limitation
across attempts without learning from prior failures.

### Reference Doc Usage

The prompt includes a `Reference: docs/mcp-ops-c/steps/step-XX.md (Task N)`
line for each task. Agents never referenced these docs by their file path,
but 6/8 tasks show the agent indirectly mentioning "the step doc" or "the
step note" or "the task note" -- suggesting they read the file but referenced
it generically rather than by name.

---

## Dead Weight Analysis

### Sections with 0% keyword utilization across all 8 tasks

| Section | Chars | % of prompt | Status |
|---------|-------|-------------|--------|
| Role Preamble | 77 | 2.6% | DEAD -- never referenced, generic framing |
| Important | 387 | 13.0% | DEAD -- rules are followed but never quoted |
| Avoiding Loops | 512 | 17.2% | DEAD -- not referenced, not effectively followed |

**Total dead weight: 976 chars (34.3% of average prompt)**

### Nuance: "Important" vs "Avoiding Loops"

These two sections score identically (0% keyword match), but their actual
impact differs:

- **Important section** (387 chars): Agents *did* follow these rules --
  they updated checklists before submitting, attempted git commits, etc.
  The section likely influences behavior at the instruction-following level
  even though agents never quote it. This is "invisible utilization" -- the
  instructions are internalized rather than echoed.

- **Avoiding Loops section** (512 chars): Agents did *not* follow these
  rules. They repeatedly re-discovered the same sandbox errors, retried
  identical commands, and showed no evidence of the "Am I making forward
  progress?" self-check. This section appears to be genuinely dead weight
  that neither influences behavior nor gets referenced.

### Exact-phrase dead weight check

Every one of these exact phrases from the prompt appeared in **zero** of the
8 agent outputs:

- "skilled software developer"
- "orchestrated workflow"
- "BUILDER phase"
- "report your progress"
- "mark it done using the orchestrator tools"
- "flexible forms like 'R1', 'R-01', or '1'"
- "not_applicable"
- "ALWAYS use `git --no-pager`"
- "git --no-pager"
- "pager hangs"
- "MUST update the checklist"
- "CRITICAL requirements must be marked"
- "MUST commit your changes"
- "verifier will review the committed code"
- "asked to revise"
- "Limit exploration to at most 10 tool calls"
- "NEVER re-read a file"
- "same command twice"
- "referenced document does not exist"
- "Am I making forward progress"
- "repeating earlier steps"

---

## Summary

### Utilization Tiers

| Tier | Sections | Chars | % of prompt | Keyword hit rate |
|------|----------|-------|-------------|------------------|
| High utilization | Task, Requirements | 490 | 16.5% | 72-73% |
| Medium utilization | Step Context, Your Workflow, How This Workflow Works | 1379 | 46.4% | 49-53% |
| Invisible utilization | Important | 387 | 13.0% | 0% (but rules followed) |
| Dead weight | Role Preamble, Avoiding Loops | 589 | 19.8% | 0% (rules not followed) |

### Key Findings

1. **74% of the prompt is template, 26% is task-specific.** Agents spend most
   of their attention on the 26% that varies (Task + Requirements sections
   have 72-73% keyword match rate).

2. **The "Avoiding Loops" section (512 chars, 17% of prompt) is the single
   largest piece of dead weight.** It is never referenced and demonstrably
   not followed -- agents in this run repeatedly retried the same failing
   commands (uv, git) across 3 builder attempts per task.

3. **The "Important" section (387 chars, 13% of prompt) appears dead by
   keyword analysis but is actually followed.** Agents update checklists,
   attempt commits, and submit for verification as instructed. This is
   "invisible utilization" -- the instructions shape behavior without being
   echoed in output.

4. **Reference docs are never cited by path.** The `Reference: docs/...`
   line in the Task section is ignored in its exact form by all 8 agents,
   though 6/8 mention the doc indirectly. This suggests agents read the
   referenced file but don't track where they found the information.

5. **`git --no-pager` instruction is universally ignored.** Despite clear
   instructions in the Your Workflow section, no agent used this flag. This
   may indicate the instruction is in a section that's too long for per-item
   retention (1054 chars with 7 numbered steps + sub-bullets).

### Recommendations

1. **Remove "Avoiding Loops" section** or replace with a shorter, more
   actionable constraint. The current 512 chars of anti-loop guidance has
   zero observable effect.

2. **Shorten "Your Workflow" section.** At 1054 chars (35% of prompt), it
   contains too many sub-instructions for reliable adherence. Focus on the
   3-4 steps agents actually follow (implement, update checklist, commit,
   submit) and cut the rest.

3. **Remove "Role Preamble"** entirely. "You are a skilled software
   developer" adds no measurable value.

4. **Keep "Important" section** but consider merging it into a shortened
   "Your Workflow" to reduce total prompt length.

5. **Consider embedding the reference doc content** directly in the prompt
   rather than providing a file path. Agents read the file but lose
   attribution, so the indirection adds latency without value.

6. **Estimated prompt reduction:** Removing dead weight and tightening the
   template could reduce prompt size from ~2969 chars to ~1800 chars (39%
   reduction) while preserving all observed behavioral effects.
