# Cross-Run Comparison: idea-to-plan Routine

Compares two runs of the `idea-to-plan` routine to assess stability of file access
patterns, cost profiles, and tool usage.

## 1. Run-Level Comparison

| Metric | R1 (`1c900b3d`) | R2 (`b46dbe62`) | Delta |
|--------|-----------------|-----------------|-------|
| Status | paused (6 tasks done) | completed (9 tasks) | R2 completed fully |
| Tokens read | 6,586 | 13,075 | +98% |
| Tokens written | 131,843 | 198,901 | +51% |
| Tokens cached | 9,774,429 | 12,756,778 | +30% |
| Duration (ms) | 3,039,366 | 4,184,075 | +38% |
| Actions | 682 | 703 | +3% |
| Tasks completed | 6 | 9 | R2 had 3 extra tasks |
| Retries | 5 (across 2 tasks) | 0 | R1 had verification failures |

**Note:** R1 was paused before completing the final 3 tasks (Human Final Approval,
Generate Summary, Create and Validate Routine YAML). R2 completed all 9 tasks on the
first attempt for each. The cost difference is partly explained by R1's 5 retry attempts
and R2's 3 additional tasks.

R1 produced a 3-step plan (`docs/agent-runners/`). R2 produced an 8-step plan
(`docs/agent-runners2/`). This difference in plan granularity is the primary driver
of read count variance in later tasks.

## 2. Per-Task Comparison (final successful attempt only)

### Shared tasks (present in both runs)

| Task | Run | Attempts | Actions | Tokens Write | Tokens Cache | Duration (s) | Reads (total/unique) |
|------|-----|----------|---------|-------------|-------------|-------------|---------------------|
| Generate Initial Artifacts | R1 | 1 | 61 | 10,237 | 820,552 | 237 | 19 / 12 |
| | R2 | 1 | 81 | 12,314 | 550,015 | 395 | 36 / 30 |
| Gather Requirements | R1 | 3 | 75 | 14,891 | 990,374 | 383 | 19 / 4 |
| | R2 | 1 | 71 | 22,581 | 1,677,970 | 476 | 18 / 6 |
| Create Step Plans | R1 | 1 | 72 | 14,173 | 933,143 | 313 | 17 / 8 |
| | R2 | 1 | 95 | 31,547 | 1,444,739 | 587 | 28 / 14 |
| Create Step Files | R1 | 1 | 71 | 20,039 | 933,642 | 368 | 24 / 14 |
| | R2 | 1 | 127 | 53,052 | 2,060,283 | 966 | 47 / 29 |
| Simulate Execution | R1 | 1 | 102 | 15,117 | 1,242,379 | 415 | 31 / 21 |
| | R2 | 1 | 113 | 22,762 | 2,777,894 | 544 | 35 / 16 |
| Cross-Check All Artifacts | R1 | 3 | 109 | 26,416 | 2,244,459 | 565 | 45 / 12 |
| | R2 | 1 | 105 | 23,595 | 1,830,719 | 507 | 52 / 22 |

### R2-only tasks

| Task | Attempts | Actions | Tokens Write | Tokens Cache | Duration (s) | Reads |
|------|----------|---------|-------------|-------------|-------------|-------|
| Human Final Approval | 1 | 12 | 1,939 | 175,257 | 57 | 0 |
| Generate Summary | 1 | 42 | 7,637 | 692,768 | 190 | 18 |
| Create and Validate Routine YAML | 1 | 57 | 23,474 | 1,547,133 | 461 | 15 |

### Tool Usage per Task (final attempt)

| Task | Run | Read | Glob | Grep | Bash | Write | Edit | ToolSearch | Other |
|------|-----|------|------|------|------|-------|------|------------|-------|
| Generate Initial Artifacts | R1 | 19 | 11 | 0 | 25 | 3 | 0 | 3 | 0 |
| | R2 | 36 | 7 | 0 | 32 | 3 | 0 | 2 | 1 |
| Gather Requirements | R1 | 19 | 3 | 0 | 46 | 1 | 0 | 6 | 0 |
| | R2 | 18 | 1 | 0 | 24 | 1 | 21 | 6 | 0 |
| Create Step Plans | R1 | 17 | 13 | 0 | 26 | 5 | 0 | 5 | 6 |
| | R2 | 28 | 11 | 0 | 30 | 16 | 0 | 4 | 6 |
| Create Step Files | R1 | 24 | 12 | 0 | 25 | 6 | 0 | 4 | 0 |
| | R2 | 47 | 19 | 4 | 37 | 12 | 0 | 4 | 4 |
| Simulate Execution | R1 | 31 | 13 | 8 | 43 | 2 | 0 | 4 | 1 |
| | R2 | 35 | 11 | 0 | 55 | 1 | 2 | 4 | 5 |
| Cross-Check All Artifacts | R1 | 45 | 5 | 13 | 24 | 2 | 13 | 7 | 0 |
| | R2 | 52 | 5 | 0 | 40 | 2 | 0 | 6 | 0 |

**"Other"** includes Agent and TodoWrite calls.

## 3. Stable Reads (files read in BOTH runs for a given task)

Paths are normalised: `docs/agent-runners/` and `docs/agent-runners2/` are both shown
as `docs/<output>/` since they are structurally equivalent (the run's output directory).

### Generate Initial Artifacts

| Normalised File | R1 Reads | R2 Reads |
|----------------|----------|----------|
| `docs/<output>/architecture.md` | 2 | 1 |
| `docs/<output>/intent.md` | 2 | 1 |
| `docs/<output>/plan.md` | 2 | 1 |
| `docs/planner/mcp-server-guide.md` | 2 | 1 |

**Stability: 4 files stable.** The 3 output docs and the input idea doc are always
read. R1 re-reads them (likely for verification). The idea file
(`docs/planner/mcp-server-guide.md`) is the only external reference that is stable.

### Gather Requirements and Update Docs

| Normalised File | R1 Reads | R2 Reads |
|----------------|----------|----------|
| `docs/<output>/architecture.md` | 5 | 4 |
| `docs/<output>/clarifications.md` | 4 | 4 |
| `docs/<output>/intent.md` | 5 | 4 |
| `docs/<output>/plan.md` | 5 | 4 |

**Stability: 4 files stable, 100% output docs.** This task is purely about refining
the 4 core planning docs. Very predictable. R1's higher count is from re-reading across
3 attempts.

### Create Step Plans

| Normalised File | R1 Reads | R2 Reads |
|----------------|----------|----------|
| `docs/<output>/architecture.md` | 2 | 2 |
| `docs/<output>/clarifications.md` | 2 | 2 |
| `docs/<output>/plan.md` | 2 | 2 |
| `docs/<output>/step-01-plan.md` | 3 | 2 |
| `docs/<output>/step-02-plan.md` | 3 | 2 |
| `docs/<output>/step-03-plan.md` | 3 | 2 |
| `docs/mcp-ops-c/step-01-plan.md` | 1 | 2 |

**Stability: 7 files stable.** The 3 core docs + per-step plan files + 1 example plan
file. R2 produced 8 step plans vs R1's 3, which explains R2's additional reads of
step-04 through step-08 plans. The structural pattern is identical.

### Create Step Files

| Normalised File | R1 Reads | R2 Reads |
|----------------|----------|----------|
| `docs/<output>/architecture.md` | 2 | 2 |
| `docs/<output>/clarifications.md` | 3 | 4 |
| `docs/<output>/intent.md` | 2 | 2 |
| `docs/<output>/plan.md` | 2 | 2 |
| `docs/<output>/step-01-plan.md` | 2 | 2 |
| `docs/<output>/step-02-plan.md` | 2 | 2 |
| `docs/<output>/step-03-plan.md` | 2 | 2 |
| `docs/<output>/steps/step-01.md` | 1 | 1 |
| `docs/<output>/steps/step-02.md` | 1 | 1 |
| `docs/<output>/steps/step-03.md` | 1 | 1 |
| `docs/frontend-gaps/steps/step-01.md` | 1 | 3 |
| `docs/frontend-gaps/steps/step-02.md` | 1 | 1 |
| `docs/plan-runner/step-files.md` | 2 | 2 |

**Stability: 13 files stable.** Core docs + all step-plan files + all step files + 2
reference examples + 1 format guide. Highly predictable. R2 has extra reads for
steps 4-8 (which didn't exist in R1's plan).

### Simulate Execution and Analyze Failure Modes

| Normalised File | R1 Reads | R2 Reads |
|----------------|----------|----------|
| `docs/<output>/architecture.md` | 1 | 2 |
| `docs/<output>/clarifications.md` | 2 | 2 |
| `docs/<output>/dry-run-notes.md` | 2 | 4 |
| `docs/<output>/intent.md` | 1 | 1 |
| `docs/<output>/plan.md` | 1 | 1 |
| `docs/<output>/step-01-plan.md` | 1 | 1 |
| `docs/<output>/steps/step-01.md` | 2 | 3 |
| `docs/<output>/steps/step-02.md` | 2 | 2 |
| `docs/<output>/steps/step-03.md` | 2 | 2 |

**Stability: 9 files stable.** Core docs + dry-run notes + step files. R1 also read
source code files and the routine YAML (12 extra files). R2 read steps 4-8. The
"simulate" task has the most variance because it exploratively reads source code to
understand execution context.

### Cross-Check All Artifacts

| Normalised File | R1 Reads | R2 Reads |
|----------------|----------|----------|
| `docs/<output>/architecture.md` | 4 | 2 |
| `docs/<output>/clarifications.md` | 4 | 2 |
| `docs/<output>/dry-run-notes.md` | 3 | 4 |
| `docs/<output>/intent.md` | 3 | 3 |
| `docs/<output>/plan.md` | 4 | 3 |
| `docs/<output>/step-01-plan.md` | 4 | 2 |
| `docs/<output>/step-02-plan.md` | 3 | 2 |
| `docs/<output>/step-03-plan.md` | 3 | 2 |
| `docs/<output>/steps/step-01.md` | 4 | 4 |
| `docs/<output>/steps/step-02.md` | 4 | 2 |
| `docs/<output>/steps/step-03.md` | 4 | 2 |
| `docs/<output>/verification-report.md` | 5 | 2 |

**Stability: 12 files stable, 0 R1-only.** This is the most stable task. It reads
every artifact produced by the run. R2 has 10 additional files (steps 4-8 plans and
files), but the structural pattern is 100% predictable: read ALL output artifacts.

## 4. Variable Reads (files appearing in only one run)

### By category across all tasks

| Category | R1-only occurrences | R2-only occurrences | Notes |
|----------|-------------------|-------------------|-------|
| Source code | 12 | 21 | Exploratory codebase reading |
| Output docs (extra steps) | 0 | 20 | R2 had 8 steps vs R1's 3 |
| Reference docs | 7 | 5 | Different examples consulted |
| Routine/scaffolding | 6 | 2 | R1 read scaffolding templates |
| Root files (AGENTS.md etc) | 1 | 3 | Sporadic |

### Detailed variable reads by task

#### Generate Initial Artifacts -- most variable task

R1-only (8 files): Read scaffolding templates and plan-runner docs to understand format.
```
routines/idea-to-plan/scaffolding/{intent,plan,architecture,routine-yaml-format}.md
docs/plan-runner/{idea_to_plan_detailed,idea_to_plan_stripped}.md
docs/planner/failure-mode-analysis.md
routines/idea-to-plan/routine.yaml
```

R2-only (26 files): Read extensive source code to understand the system architecture.
```
src/orchestrator/agents/{interface,detector,types,cli,codex_server,executor,openhands,user_managed}.py
src/orchestrator/api/{routers,schemas}/*.py
src/orchestrator/{config,db}/*.py
ui/src/{components,pages,types}/*.{tsx,ts}
docs/intent/01-ARCHITECTURE.md, AGENTS.md
routines/demo-task.yaml, examples/routines/comprehensive-mcp-tools-example.yaml
```

**Why:** R2's agent went deep into source code exploration (18 source files) to
understand the system before creating artifacts. R1 used scaffolding templates instead.
This is the biggest source of cost variance.

#### Gather Requirements -- minimal variance

R2-only (2 files): `src/orchestrator/api/{routers,schemas}/clarifications.py`

**Why:** R2 looked at clarification API implementation. Minimal impact.

#### Simulate Execution -- moderate variance

R1-only (12 files): Source code exploration (`src/orchestrator/agents/*.py`,
`src/orchestrator/cli/*.py`). R2-only (7 files): steps 4-8 + `alembic.ini`.

**Why:** Both runs explored the codebase to simulate execution, but chose different
files. R1 focused on agent implementations; R2 read more step files.

#### Cross-Check -- zero R1-only variance

R2-only (10 files): All step-04 through step-08 plans and files.

**Why:** Purely structural -- R2 had more steps so more files to cross-check.

## 5. Conclusions

### What is predictable

1. **Output document access patterns are 100% structurally stable.** Every task reads
   the same set of output documents in the same structural pattern across runs. The
   only variation is in count (R2 had more steps so more step files). If we normalise
   for plan size, the access pattern is identical.

2. **Core docs are always read.** `intent.md`, `plan.md`, `architecture.md`, and
   `clarifications.md` are read by every task in both runs. These are the "always
   cache" files.

3. **Later tasks are more predictable than earlier ones.** The first task (Generate
   Initial Artifacts) has the most variance because the agent is exploring. By
   Cross-Check, the access pattern is 100% structural (read every artifact, nothing
   else).

4. **Re-read frequency is consistent.** Both runs re-read core docs 2-5x per task.
   The median is 2x (once to understand, once to verify/reference while writing).

5. **Reference files are stable per task.** `docs/plan-runner/step-files.md` is always
   read by Create Step Files. `docs/mcp-ops-c/step-01-plan.md` is always read by
   Create Step Plans as an example.

### What is unpredictable

1. **Source code exploration in early tasks.** R2 read 18 source files in Generate
   Initial Artifacts; R1 read 0. This is the single largest source of cost variance.
   The agent decides whether to explore the codebase based on how well it understands
   the task from context alone.

2. **Scaffolding vs source code strategy.** R1 relied on scaffolding templates
   (`routines/idea-to-plan/scaffolding/*.md`) while R2 read source code and examples.
   Both approaches worked, but R2's was ~2x more expensive in reads.

3. **Number of steps produced.** R2 produced 8 steps vs R1's 3 steps. This cascades
   through all later tasks, multiplying reads linearly. This is inherent to the task
   (different ideas produce different plan sizes) and not controllable.

4. **Retry cost.** R1 needed 5 retries across 2 tasks. This added ~35% to the cost
   of those tasks. Retry probability is unpredictable.

### Recommendations for token savings

1. **Pre-load core output docs into context** for every task. They are always read
   (4 files, ~2-5 reads each). This eliminates 8-20 Read calls per task.

2. **Restrict source code exploration in Generate Initial Artifacts.** The task
   prompt should discourage or prohibit reading source files -- the scaffolding
   templates exist for this purpose. R1's approach (scaffolding only) was cheaper
   and equally successful.

3. **Pre-load reference examples** for tasks that always use them
   (`docs/plan-runner/step-files.md` for Create Step Files,
   `docs/mcp-ops-c/step-01-plan.md` for Create Step Plans).

4. **Accept that later tasks scale with plan size.** Steps 4-8 reads in R2 are
   unavoidable. Cost scales linearly with the number of steps in the plan.
