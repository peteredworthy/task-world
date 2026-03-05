# Routine Effectiveness Review: Idea-to-Plan and MCP Operations

**Date:** 2026-03-04
**Scope:** Two-stage review of (1) the "Idea to Implementation Plan" routine (the plan-maker) and (2) the "MCP Operations — Per-Step Tool & External MCP Configuration" routine (the plan it produced), evaluated through runs c3e5f5a6 (openhands_local) and 8bf41c40 (codex_server).

---

## Executive Summary

The planning system produces high-quality, comprehensive plans (4,454 lines across 28 artifacts for MCP-ops). However, **execution fidelity is low**: the codex run reached 78% completion but burned 3.5 hours, with one task failing 8 times in a 2.1-hour loop due to a gate bug. The openhands run stalled at 33% from infrastructure instability.

Experiments D1–D10 (see Part 7) confirmed and quantified the key systemic issues:

1. **Gates are structurally broken** — 30.4% false-positive rate (D1), checklist gate never blocked anything across 37 evaluations, and a non-performing agent can reach COMPLETED status on tasks with no auto-verify or verifier (D5).
2. **74.6% of requirements have no automated verification** (D2) — all 15 core implementation tasks rely entirely on LLM verifier judgment.
3. **Verifier grades vary by up to 4 letter grades** on structurally similar code (D7), and a mid-run model switch amplified variance further.
4. **34% of prompts are dead weight** (D4) — achievable 39% reduction with no behavioral impact. The "Avoiding Loops" instruction (512 chars) is demonstrably ignored by agents.
5. **Context size doesn't predict token usage** — task complexity spans 4 orders of magnitude regardless of prompt size (D10). Token budgets should be set per task type, not per context size.
6. **Plan staleness increases monotonically** (D8) — 0% at step 1, 6.5% by step 7, primarily from naming divergence and cross-step signature drift.
7. **Two completed tasks were actively destructive** (D1) — deleting 130+ lines of test coverage while self-reporting "done" and passing all gates.
8. **Codex is 16x faster than OpenHands** with equal quality on overlapping tasks (D9), but both hit ceilings: Codex at integration tests, OpenHands at complex wiring tasks.

---

## Part 1: The Plan-Maker (Idea to Implementation Plan Routine)

### 1.1 What It Produces

The idea-to-plan routine is an 8-step workflow that transforms an idea into executable artifacts:

| Stage | Output | Purpose |
|-------|--------|---------|
| S-01 | intent.md, plan.md, architecture.md | Initial framing |
| S-02 | clarifications.md + doc updates | Requirements gathering via Q&A |
| S-03 | step-XX-plan.md files | Contracts and verification per step |
| S-04 | steps/step-XX.md files | Atomic task breakdown |
| S-05 | dry-run-notes.md | Simulated execution, gap finding |
| S-06 | verification-report.md | Cross-artifact consistency check |
| S-07 | (human approval gate) | Final go/no-go |
| S-08 | plan-summary.md, routine.yaml | Validated execution package |

For MCP-ops, this produced **28 files totaling ~4,454 lines** — a thorough specification that identified 11 files to modify, 16 Definition of Complete items, 20 dry-run gaps, and a 9-step/26-task execution routine.

### 1.2 Strengths of the Plan-Maker

**S1. Structured uncertainty front-loading.** The clarification system (S-02) resolved 7 design questions before implementation began, preventing costly mid-execution pivots. Questions like "should step tools be additive or restrictive?" were answered early.

**S2. Dry-run gap detection.** S-05 identified pre-existing bugs (Codex builders seeing the grade tool, OpenHands missing the tools parameter) that would have blocked execution. 16 of 20 gaps were tracked into implementation steps.

**S3. Human gates.** S-07 requires explicit human approval before routine packaging, preventing obviously flawed plans from reaching execution.

**S4. Validation loop on routine YAML.** S-08/T-02 runs `uv run orchestrator routines validate` and includes a detailed format guide with anti-patterns (no shell pipes in auto_verify), reducing the most common YAML errors.

### 1.3 Weaknesses of the Plan-Maker

**W1. Context explosion through artifact interpolation.**
The `context_from` mechanism loads entire planning documents into downstream task prompts:

| Task | Artifacts Loaded | Estimated Prompt Size |
|------|------------------|----------------------|
| S-02/T-01 | intent.md + plan.md + architecture.md | ~50,000 tokens |
| S-03/T-01 | plan.md + architecture.md | ~35,000 tokens |
| S-06/T-01 | intent.md + plan.md + dry-run-notes.md | ~45,000 tokens |

Each downstream stage re-loads the full text of prior artifacts without summarization. The system lacks context compression — a task in S-06 receives all of S-01's output verbatim even though it only needs the high-level decisions.

**W2. Step context repetition within multi-task steps.**
When a step has 3 tasks (e.g., S-01 of mcp-ops-c), each task receives the same `step_context` in its prompt. For S-01 with 3 tasks, that's 3× the same ~500-character step description. Minor per-task, but compounds across a 26-task routine.

**W3. Plans optimized for human reading, not agent execution.**
The step files (step-XX.md) are 118–284 lines of prose. They describe *what* to build with narrative explanations rather than structured, machine-parseable instructions. A limited AI agent must extract actionable information from paragraphs of English, which is error-prone.

**W4. Research tasks without research tools.**
S-06/T-01 ("Research OpenHands SDK MCP Support") asks the agent to investigate SDK capabilities, but the routine provides no web search, documentation browsing, or SDK introspection tools. The agent must rely on whatever it can learn from reading installed source files.

**W5. No feedback on plan quality before execution.**
The human approval gate (S-07) is the only quality checkpoint. There's no automated assessment of whether the produced routine.yaml is likely to succeed — e.g., whether requirements are independently verifiable, whether auto_verify commands are correctly structured, or whether task scopes are actually atomic.

**W6. Clarifications file grows unboundedly.**
Each Q&A round appends to `clarifications.md`. After 3-5 rounds, this file can reach 500-1,000 lines, and every downstream task re-reads the entire file through `context_from`. No summarization or pruning occurs.

---

## Part 2: The Produced Plan (MCP Operations Routine)

### 2.1 Routine Structure

9 steps, 26 tasks, organized in three milestones:
- **Milestone 1** (S-01, S-02): Schema & context foundation — 6 tasks
- **Milestone 2** (S-03 through S-07): Agent-specific tool filtering — 17 tasks
- **Milestone 3** (S-08, S-09): Integration & validation — 5 tasks

### 2.2 Execution Results

| Metric | Run c3e5f5a6 (OpenHands) | Run 8bf41c40 (Codex) |
|--------|--------------------------|----------------------|
| Agent type | openhands_local | codex_server |
| Progress | 33% (3/9 steps) | 78% (7/9 steps) |
| Status | Paused (agent died) | Paused (health check failed) |
| Duration | Unknown (not tracked) | 3.27 hours execution |
| Token usage (read) | 28.9M | Not tracked by codex |
| Token usage (write) | 187K | Not tracked |
| Tasks completed | 10/28 | 18/28 |
| Tasks failed | 0 | 1 (after 8 attempts) |
| Agent died events | 9 | 2 |
| Agent error events | 0 | 6 |

### 2.3 The Codex Run in Detail

**Checklist gate: 37 evaluations, 0 rejections.** The gate never blocked a single submission. Agents self-mark requirements as `done` and the gate simply confirms the agent's claim.

**Grade evaluations: 29 passed, 8 failed.** All 8 failures were on one task — "Create Integration Tests for Step-Level Tool Control" (946657c8). Every other task passed grading on the first attempt.

**The 8-attempt death spiral on task 946657c8:**

| Attempt | Duration | R1 Grade | R2 Grade | Root Cause |
|---------|----------|----------|----------|------------|
| 1 | 3 min | B | F | PermissionError on env-store path |
| 2 | 9 min | D | D | Tests regressed to model-level |
| 3 | 7 min | C | F | Same regression, full suite failures |
| 4 | 7 min | B | F | Multi-step cases weak, many failures |
| 5 | 31 min | D | C | Tests stripped back, only targeted file ran |
| 6 | 23 min | A | B | Finally good, but teardown loop warning |
| 7 | 23 min | A | C | macOS sandbox panic in system-configuration |
| 8 | crash | — | — | ChecklistItemNotFoundError (empty req ID) |

**Total time wasted: 2.1 hours** on a single task. The core problem: R2 required "all existing test suites pass (no regressions)" — but the codex agent was running in a sandbox where pre-existing tests failed due to environmental constraints (openhands not installed, macOS sandbox restrictions). The requirement was unfulfillable in the execution environment.

### 2.4 The OpenHands Run in Detail

**Token consumption is extreme.** A single task ("Add Step-Level Tool Hints to CLI Prompt") consumed **6.3M read tokens and 54K write tokens across 645 actions**. Another task ("Implement Additive Tool Filtering in Claude SDK Agent") consumed **9.5M read tokens in 291 actions**. Total across 12 attempts: 28.9M tokens read.

OpenHands uses an agentic loop where it reads and re-reads files many times. The token cost per task is roughly 10-30× what a focused agent would need.

**Infrastructure instability.** 9 `agent_died` events over 2 days. The OpenHands agent requires a running Docker container that gets killed when the orchestrator server restarts. Unlike Codex, the tasks that did complete were high-quality (all passed grading on first attempt), but the agent couldn't stay alive long enough to finish.

---

## Part 3: Gate Effectiveness Analysis

### 3.1 Checklist Gate — Structurally Worthless

The checklist gate (`gates.py:22-66`) checks only `item.status`. This status is set by the builder agent calling `PATCH /tasks/{id}/checklist/{req_id}` with `{"status": "done"}`. The gate performs **zero independent verification**.

Worse, if no verifier grades are recorded, the auto-complete path (`transitions.py:279-287`) assigns every `done`-status item an automatic A grade:

```python
if item.status == ChecklistStatus.DONE:
    item.grade = "A"
    item.grade_reason = "Auto-graded (builder self-reported done, no verifier rubric)"
```

**Evidence from experiments:**
- **D1:** 37/37 checklist gate evaluations passed — the gate never blocked anything. Of 23 tasks that passed, 7 (30.4%) were partial or insufficient. Two tasks were *actively destructive*, deleting 130+ lines of test coverage while self-reporting "done."
- **D5:** Static code tracing confirms a non-performing agent that marks all items "done" without writing code can reach COMPLETED status on any task lacking both auto-verify and verifier rubric. The auto-grade path assigns straight As to self-reported "done" items. The LLM verifier is the only real defense, and only when configured.

### 3.2 Auto-Verify Commands — Multiple Failure Modes

**Exit code masking (the pipe bug):**
The routine's format guide warns against pipes, and the `_reject_pipes` validator blocks literal `|`. However, the actual run data reveals this bug was present in an earlier version of the routine — the `full_suite_pass` check used `| tail -5`, causing pytest's non-zero exit code to be swallowed by tail's exit 0. This was the primary cause of the 8-attempt death spiral.

**Self-authored tests:**
7 of the 26 tasks include auto_verify commands that run tests the agent itself wrote (e.g., `uv run pytest tests/unit/test_mcp_server_config.py -v`). An agent can write trivially-passing tests that verify nothing meaningful. There is no golden test suite.

**D2 experiment confirmed:** 74.6% of requirements (47 of 63) have zero auto_verify coverage. All 15 core implementation tasks (S-03 through S-07) lack auto_verify entirely. Auth token security — a recurring critical requirement across 4 tasks — has zero automated verification. The 8 "agent-authored test" checks create circular dependencies where verification quality depends entirely on what is being verified.

**Existence-only checks:**
Several auto_verify commands only verify file existence (`test -f docs/{{feature}}/intent.md`), not content quality. A 1-line file passes.

**Insufficient verification depth — specific examples:**

| Task | Auto-verify | What it misses |
|------|------------|----------------|
| S-01/T-01 | `model_importable` + `dual_transport_rejected` | Doesn't verify neither-transport case. Import error passes `dual_transport_rejected`. |
| S-02/T-01 | `context_fields` Python one-liner | Doesn't assert output is `None None None` — wrong defaults still pass. |
| S-01/T-02 | `uv run pytest tests/ -x --timeout=30 -q` | 30-second timeout may be too short. Pre-existing failures cause false negatives. |
| S-08/T-01 | `full_suite_pass` | Agent-authored integration tests self-certify. |
| S-05/T-01 | No auto_verify at all | Phase filtering implementation has no automated check. |

### 3.3 Verifier Rubrics — Too Composite, Too Subjective

**Composite grading collapses requirements.** Most rubric items cover 2-3 requirements in a single grade:

```yaml
R1-R3 — A: MCPServerConfig uses Pydantic model_validator...
         B: Model works but validation is incomplete...
```

One B grade can mask the complete failure of one sub-requirement while the others are A-quality. The system has no per-requirement grading — the verifier assigns one grade to the entire rubric item.

**Subjective language permits wide interpretation.** Phrases like "minor leak" (S-03/T-02), "mostly correct" (S-05/T-02), and "reasonably scoped" (S-04/T-01) give the verifier agent latitude to pass borderline work. A more limited AI verifier will default to generous grading.

**D7 experiment confirmed verifier inconsistency:** Across 8 evaluations of task 946657c8 on structurally similar code, R1 grades ranged from D to A — a 4-letter-grade swing. A mid-run model switch (default → gpt-5.3-codex) coincided with the largest jump (D→A). R2 grades ranged from F to B, though this was more justified by genuine environmental variation. The composite rubric did not mask per-requirement failures on *passed* tasks (D3), but 7 tasks received auto-grades with no LLM verification at all, and 6 requirements received A grades with null justifications.

**Verification breadth requires enormous context.** S-09/T-03 asks the verifier to confirm "all 16 intent items addressed" — requiring cross-reference of `intent.md`, the full git diff, and all implementation files. A token-constrained verifier will skim rather than verify each item.

### 3.4 Grade Threshold Gap

No step in mcp-ops-c uses a `gate: { type: grade_threshold }` configuration. Grade evaluation only occurs per-task via `transition_after_verification()`. There is no aggregate quality gate that prevents step advancement when, say, 2 of 3 tasks passed with B grades but the third had a critical C.

---

## Part 4: Token Usage and Context Efficiency

### 4.1 Where Tokens Are Consumed

**Builder prompt assembly** (`prompts.py`) concatenates:
1. System message (~3,500 chars, fixed)
2. Step context (0–500 chars)
3. Clarifications (0–2,000 chars)
4. Task context (300–825 chars in mcp-ops-c; up to 50,000 chars in idea-to-plan with artifact loading)
5. Requirements list (100–300 chars)
6. Previous verifier feedback on revision (0–2,000 chars)

**Minimal prompt:** ~5,500 tokens.
**Idea-to-plan downstream task:** ~50,000 tokens (with artifact interpolation).
**Revision prompt:** adds ~2,000 tokens of verifier feedback.

**D4 experiment findings:** 74% of the builder prompt is boilerplate template; only 26% is task-specific. Task-specific sections (task context, requirements) have 72-73% keyword match rates in agent output, confirming agents focus on varying content. 34% of the prompt (~976 chars) is dead weight that is never referenced or followed — the "Avoiding Loops" section (512 chars) is the largest offender and is demonstrably violated by agents who repeatedly retry identical failing commands. An estimated **39% prompt reduction** is achievable with no behavioral impact.

### 4.2 Token Waste Patterns

| Pattern | Impact | Where |
|---------|--------|-------|
| Full artifact re-loading without summarization | +30,000–50,000 tokens per task | idea-to-plan S-02, S-03, S-06 |
| Step context repeated per task in multi-task steps | +500 chars × (tasks-1) per step | Every multi-task step |
| OpenHands read-loop pattern | 6-10M tokens per task | All OpenHands tasks |
| 8-attempt death spiral on unfulfillable requirement | 2.1 hours, unknown tokens | codex run task 946657c8 |
| Verifier re-reading entire implementation on each revision | Full context per attempt | Every revision cycle |
| Clarifications file unbounded growth | +500–1,000 lines over Q&A rounds | idea-to-plan S-02+ |

### 4.3 What Genuinely Requires Large Context

Not everything can be shrunk. These operations legitimately need large context:

1. **Cross-artifact consistency checks** (S-06): Must see intent, plan, step files, and dry-run notes simultaneously to detect contradictions.
2. **Routine YAML generation** (S-08/T-02): Needs the full format guide (~80 lines) plus all step/task definitions to produce valid YAML.
3. **Final review** (S-09/T-03): Must cross-reference 16 intent items against implementation.
4. **Step planning** (S-03): Must understand the full plan and architecture to define per-step contracts.

These are candidates for **dedicated large-context operations** rather than running under the same token budget as simple tasks.

---

## Part 5: Recommendations

### 5.1 Gate Improvements

**G1. Add independent verification to the checklist gate.**
The checklist gate should run auto_verify commands *before* accepting self-reported `done` status. If auto_verify is configured and any `must: true` item fails, block the BUILDING→VERIFYING transition regardless of self-reported status.
[HUMAN]Running auto checks before accepting done was how it was expected to work. If that isn't the case then we should fix it.

**G2. Separate per-requirement grading.**
Replace composite rubric items (`R1-R3 — A: ...`) with one rubric item per requirement. The verifier assigns one grade per requirement, and the grade threshold evaluates each independently. This prevents a passing grade on R1 from masking a failing R2.
[HUMAN]Agree

**G3. Add pre-written verification tests.**
For critical requirements, include golden test files that are NOT written by the builder agent. These could be checked into the repo alongside the routine and run as part of auto_verify. The builder's implementation must pass tests it didn't author.
[HUMAN]I like the TDD aspect but I have found this to be fragile as the LLM writing the test creates an imagined implementation. We could use this only if we ensure that the design focuses on a defined edge contract and the tests align with that contract.

**G4. Environment-aware requirement filtering.**
Requirements like "all existing test suites pass" should specify exclusion patterns for known environmental failures (e.g., `exclude_patterns: ["test_openhands_executes"]` when openhands isn't installed). This prevents unfulfillable requirements from causing death spirals.
[HUMAN]I would preffer to give the verifier / builder the ability to raise the alarm to the human. I am trying to ensuer that tests such as this are skipped instead of fail when the environment is not correct.

**G5. Add step-level aggregate gates.**
Configure `gate: { type: grade_threshold }` on steps that contain multiple related tasks, so weak individual results can't compound into a passing step.
[HUMAN] I disagree, if we change gating on the step it should be to strengthen it through full feature tests not counting letters.

### 5.2 Context Efficiency

**C1. Implement context summarization for artifact loading.**
When `context_from` loads an artifact, offer a `summarize: true` option that uses a fast model to compress the document to key decisions and constraints rather than including full text. Target: reduce 500-line artifacts to 50-line summaries.
[HUMAN]Sounds sensible but it requires a great deal of care. During planning a MAJOR risk it the LLM ignoring important requirements. Some items like intent shouldn't be summarized, it is also short. Some like the plan can be summarized BUT only in some cases. Checking that the plan, intent, etc all align doesn't make sense checking only summaries. We may need to think about how to split the context for some of these. Confirming the outline of the plan aligns and then that each of the parts align. That still runs a risk of requirements / the intent not being met. Stages producing parts that are then never used in later stages etc. I'm open to deeper thoughts and options. There are certainly places where we can use summarization but it needs to be high quality, we need clarity on what can be removed and what can't. For some parts it won't work and we need alternative strategies.

**C2. Deduplicate step context.**
Move step context into the system prompt or a separate "step briefing" section that's included once, not per-task. Each task's prompt should only contain its task-specific context.
[HUMAN]Are you talking about it being duplicated in the YAML? If so that totally shouldn't be happening.

**C3. Add context budgets.**
Allow routines to specify `max_context_tokens: N` per task. The prompt builder truncates or summarizes loaded artifacts to fit within the budget. This forces routine authors to think about what context is actually necessary.
[HUMAN]Good for catching runaways but seems like asking an LLM to create a number that it is unlikely to be able to accurately guess.

**C4. Use sub-agents for research phases.**
Research tasks (like "Research OpenHands SDK MCP Support") should spawn lightweight sub-agents that return structured findings rather than running in the full builder context. This isolates the token cost of exploration.
[HUMAN] This is good but requires all agent runners to implement sub-agents. IIRC openhands is the only one that lacks that ability. We will need to provide a tool for it.

**C5. Compress clarifications on resolution.**
After each Q&A round, summarize resolved questions into a "decisions" section and archive the raw Q&A. Downstream tasks receive only the decisions, not the full dialogue history.
[HUMAN] Sounds good.

### 5.3 Execution Improvements

**E1. Add circuit breakers for death spirals.**
If a task fails 3 consecutive attempts with similar error patterns, pause the run and surface the issue to the human rather than retrying. The current `max_attempts` allows up to 8 retries with no pattern detection.
[HUMANM] 3 failures already causes failure. To reach 8 required human intervention.

**E2. Distinguish pre-existing failures from regressions.**
Before starting a task, capture a baseline test run. After the builder finishes, compare results. Only flag *new* failures as regressions. This prevents pre-existing environmental failures from blocking progress.
[HUMAN] Instead don't even start if the tests aren't clean. It shouldn't have been possible to commit with test failures.

**E3. Provide targeted tool access.**
Research tasks should have web search and documentation browsing tools. Implementation tasks should have code search and test running tools. The routine should declare per-step tool requirements so the orchestrator can provide appropriate capabilities.
[HUMAN] Nice to have. Works mostly with a very minimal tool set at the moment. 

**E4. Use structured output for agent instructions.**
Replace prose step files with structured formats (YAML/JSON task specs) that agents parse deterministically. Include: exact file paths, function signatures, expected test commands, and acceptance criteria as machine-readable fields.
[HUMAN] Is the suggestion to skip the prose step files, the final file is already YAML. I have been thinking that routines being defined by multiple yaml files might be better for splitting construction. 

**E5. Add agent-type-specific prompt optimization.**
OpenHands and Codex have different interaction patterns. OpenHands benefits from explicit "do not re-read files you've already seen" instructions. Codex benefits from shorter, more focused prompts. The prompt builder should adapt to agent type.
[HUMAN] These instructions should be migrated to the agent runners.

### 5.4 Planning Process Improvements

**P1. Validate auto_verify commands during planning.**
S-08/T-02 validates the routine YAML schema but doesn't validate that auto_verify commands are correct. Add a check: does each auto_verify command's exit code actually reflect the requirement? Flag commands that always exit 0 (like existence checks for behavior requirements).
[HUMAN] I like the concept but I don't think you have thought through the process. How, without carrying out the work do we confirm that the command really validates the right thing programatically? Existance checks will return 1 as the file doesn't exist. Existance file checks are present as they do actually catch failures. There have been times where an LLM forgot to implement a file at all! They are a low bar but not a useless one.

**P2. Generate golden tests during planning.**
During the step planning phase (S-03), generate verification test stubs that test the *contract*, not the implementation. Check these into the routine alongside the auto_verify commands. The builder must pass tests it didn't write.
[HUMAN] As long as these tests are suitably robust. They often have unforseen dependencies that break them, e.g. a service being correctly constructed has nothing to do with the implementation but if it doesn't align with the test's expectations it will fail.


**P3. Add requirement independence validation.**
During task breakdown (S-04), verify that each requirement can be checked independently of agent self-reporting. Flag requirements like "all tests pass" that depend on environmental state the agent can't control.
[HUMAN] Agree on all requirements must have a means of being verified. Disagree on the "all tests pass" requirement. It is a requirement. If we have tests that can't be passed this is a CI/CD is broken stop the world situation.

**P4. Produce agent-capability-matched plans.**
The planner should consider which agent type will execute the routine. An OpenHands agent has different capabilities (Docker container, browser) than a Codex agent (sandboxed, no network). Task instructions should adapt accordingly.
[HUMAN] This is one where I am torn. The capabilities should be adjusted to align as closely as possible. We have adjusted the Codex agent to give it suitable access. What is complex to decide if it should be adjusted to is simple local LLM vs state of the art LLM. A state of the art LLM needs fewer tasks (not less verification, even state of the art LLMs suffer for skipping requirements). A local LLM needs short simple tasks that don't require too many decisions.

**P5. Include failure recovery playbooks.**
For each step, the plan should include: "If this step fails after N attempts, here are the likely causes and remediation steps." This enables faster human intervention and better recovery agent decisions.
[HUMAN] Nice sounding but No. We can later add a prompt that produces something like this followed by a stage to re-engineer the plan to minimize the liklihood.

---

## Part 6: 10 Strategies to Understand Process Limitations

These are diagnostic experiments and measurements that would reveal additional weaknesses:

All experiments are designed for rapid iteration — they reuse existing run data, test single variables in isolation, and avoid re-running expensive full routines. Each can be completed in under 30 minutes.

### D1. Gate false-positive audit (from existing data)
**Method:** Query the database for the 18 completed tasks in run 8bf41c40. For each, `git diff` its `start_commit..end_commit` and score the diff as "genuinely complete," "partially complete," or "not done" against the requirement text. No new runs needed — just SQL + git on existing data.
**Cost:** ~20 minutes of human review.
**Expected insight:** Quantifies the checklist gate's false-positive rate using data already collected.

### D2. Auto_verify command audit (static analysis, no execution)
**Method:** Extract every `cmd` field from mcp-ops-c/routine.yaml. For each, answer: (a) does exit code reflect the requirement? (b) can it pass with incomplete implementation? (c) does it test behavior or just existence? Build a coverage matrix as a spreadsheet. No runs needed.
**Cost:** ~15 minutes of analysis.
**Expected insight:** Reveals which requirements have no effective automated verification — the exact gaps that let incomplete work through.

### D3. Single-task rubric split test
**Method:** Pick one task from the existing codex run that passed with a composite rubric (e.g., S-01/T-01 `model_quality` covering R1-R3). Write 3 separate rubric items. Re-run *only the verifier phase* against the existing code (no builder needed — the code is already in the worktree). Compare the 3 individual grades against the original composite grade.
**Cost:** One verifier invocation (~2 minutes).
**Expected insight:** Shows whether splitting rubrics changes grading outcomes, without re-running the builder.

### D4. Context utilization via output grep (from existing data)
**Method:** For 5 completed tasks in the codex run, pull the builder prompt from the database (`attempts.builder_prompt`) and the agent output (`attempts.agent_output`). Grep the output for strings from each prompt section (step_context, task_context, requirements, system message). Calculate what percentage of prompt sections appear referenced in output.
**Cost:** ~10 minutes of scripting against existing DB data.
**Expected insight:** Identifies dead-weight context sections that agents ignore — candidates for removal or summarization.

### D5. Adversarial gate bypass (mock agent, single task)
**Method:** Start a fresh run of mcp-ops-c. Use the API directly (`curl`) to: mark all R1/R2/R3 checklist items as `done` without making code changes, then call `POST /submit`. Observe whether the checklist gate blocks it. Then check if auto_verify catches it. Stop after one task — don't run the full routine.
**Cost:** ~5 minutes of API calls.
**Expected insight:** Proves whether the gate system has any defense against a non-performing agent, using exactly one task as a probe.

### D6. Time-to-first-action from existing logs
**Method:** Query the `events` table for agent_output events in run 8bf41c40. For each task, find the timestamp of the first event containing a file write or shell command (look for patterns like `"tool": "write"` or `"tool": "bash"`). Subtract from task start time. No new runs needed.
**Cost:** ~10 minutes of SQL.
**Expected insight:** Reveals orientation overhead per task. If agents spend 30%+ of task time reading before acting, prompts need restructuring.

### D7. Verifier consistency (replay same diff, 3 runs)
**Method:** Pick one completed task from the codex worktree. Extract its git diff. Run the verifier prompt against that diff 3 times using the API (or Claude directly). Compare grades across the 3 runs.
**Cost:** 3 verifier invocations (~5 minutes total).
**Expected insight:** If grades vary (e.g., A, B, A), the rubric is too subjective. If consistent, the rubric is reliable.

### D8. Plan freshness check (static diff analysis)
**Method:** For the codex run worktree, compare step-01.md instructions against the codebase at `end_commit` of step 1, then compare step-07.md instructions against the codebase at `end_commit` of step 7. Count how many file paths, function names, or API references in the step file are stale (renamed, moved, or deleted by earlier steps). No runs needed.
**Cost:** ~15 minutes of manual diff review.
**Expected insight:** Quantifies whether later steps are working from outdated instructions. If >20% of references are stale, plans need mid-execution refresh.

### D9. Minimal single-step agent comparison
**Method:** Take S-01 (3 tasks, well-defined schema work) and run it with CLI agent, then Codex agent — one step only, not the full 9-step routine. Compare: tokens used, time to completion, gate outcomes, grade outcomes.
**Cost:** ~30 minutes (two partial runs of 3 tasks each).
**Expected insight:** Reveals per-agent efficiency differences on identical work without the 3+ hour cost of a full routine run.

### D10. Token budget experiment (single task)
**Method:** Take S-04/T-01 (Claude SDK tool filtering) which has a 825-char task_context. Create a variant with (a) the full context as-is, and (b) a 200-char compressed version keeping only file path, function name, and acceptance criteria. Run both variants as standalone tasks. Compare: output quality, time to completion, tokens used.
**Cost:** Two single-task runs (~10 minutes).
**Expected insight:** Directly measures whether verbose task contexts improve output quality or just waste tokens. If quality is equal, all task contexts can be compressed.

---

## Part 7: Experiment Results Summary

All 10 experiments were conducted using existing run data and static analysis — no new full routine runs were required. Detailed reports are in `docs/reviews/experiments/`.

| Exp | Question | Key Finding | Impact on Conclusions |
|-----|----------|-------------|----------------------|
| **D1** | How often do gates pass incomplete work? | **30.4% false-positive rate** (7/23 tasks). 5 tasks insufficient (3 zero-diff, 2 destructive). | Confirms gate weakness is not theoretical — it's measured. Elevates G1 (independent verification) to urgent. |
| **D2** | How much do auto_verify commands actually cover? | **74.6% of requirements uncovered.** All 15 implementation tasks have zero auto_verify. Auth token security has zero automated checks. | Confirms auto_verify is a presence-check system, not a behavior-verification system. Validates G3 (golden tests). |
| **D3** | Does composite grading mask failures? | **No masking on passed tasks** — all passed with per-requirement A grades. Real masking is from auto-grading (7 tasks got A with no LLM review). | Revises G2 priority downward — composite rubrics aren't the problem. Auto-grading without verification is. |
| **D4** | How much of the prompt do agents actually use? | **34% dead weight.** 39% prompt reduction achievable. "Avoiding Loops" (512 chars) universally ignored. | Validates C2/C3 (context efficiency). Suggests prompt trimming is low-effort, high-value. |
| **D5** | Can a non-performing agent pass gates? | **Yes.** Tasks without auto-verify + verifier go straight to auto-grade A via self-report. LLM verifier is the only real defense. | Confirms the bypass vulnerability. Every task must have either auto-verify or a verifier rubric — no exceptions. |
| **D6** | How long do agents spend orienting? | **18.7% median** (21.2s). Implementation tasks: 21.3%. Test tasks: 17.8%. Research tasks: 75.6%. | Orientation overhead is modest for implementation. Prompts are not causing excessive reading time. Deprioritizes E4 (structured output). |
| **D7** | Are verifier grades consistent? | **4-letter-grade variance** (D to A) on R1 across 8 evaluations. Model switch amplified variance. | Confirms rubric subjectivity is a real problem. Validates need for objective, machine-checkable verification criteria. |
| **D8** | Do plans go stale during execution? | **Staleness increases monotonically:** 0% → 3.1% → 6.5%. Naming divergence and signature drift are the main causes. File paths stay accurate. | Staleness is measurable but modest at 9 steps. For longer routines (20+ steps), mid-execution plan refresh would be needed. |
| **D9** | How do agent types compare? | **Codex 16x faster** than OpenHands with equal quality. Both hit ceilings at different tasks. OpenHands has zero API cost but severe time penalty. | Validates E5 (agent-type optimization). Agent selection should be task-type-aware, not routine-level. |
| **D10** | Does context size drive token usage? | **No.** Task complexity spans 4 orders of magnitude regardless of context size. Read/write ratio increases with complexity (82:1 → 140:1). | Revises C3 — token budgets should be per task *type* (schema: 700K, feature: 7M), not per context size. |

### Conclusions Adjusted by Experiments

**Upgraded priorities:**
- **G1 (independent verification):** D1's 30.4% false-positive rate and D5's bypass proof make this the #1 fix.
- **Mandatory auto-verify or verifier on every task:** D5 showed tasks without either are completely undefended. This is a new recommendation.
- **Prompt trimming:** D4 showed 39% reduction is achievable — low effort, immediate payoff.

**Downgraded priorities:**
- **G2 (per-requirement grading):** D3 showed composite rubrics aren't masking failures on passed tasks. The auto-grade path is the real problem.
- **E4 (structured output):** D6 showed orientation overhead is only 18.7% — agents aren't struggling to parse prose instructions.
- **C3 (context budgets by size):** D10 showed context size doesn't predict token usage. Budget by task type instead.

**New finding — destructive tasks:**
D1 revealed that 2 tasks *deleted* working test code while passing all gates. This is worse than "incomplete" — it's regressive. Auto-verify must detect *regressions within the diff*, not just final state. A new recommendation: **diff-quality gate** that flags tasks whose diff has more deletions than additions in test files.
[HUMAN] This is something that we should provide an automated test that can be used for most tasks for. Run geting the list of tests before starting and check the list of tests after the builder. Note, it isn't suitable for everything. If a task involves code cleanup and or renaming this isn't going to work.
---

## Appendix A: Run Data Summary

### Run c3e5f5a6 (openhands_local)
- **Created:** 2026-03-01, **Duration:** 2+ days (intermittent)
- **Steps completed:** 3/9 (S-01, S-02, S-03)
- **Tasks completed:** 10/28, 1 building, 17 pending
- **Agent died:** 9 times (server restarts, health check failures)
- **Tokens:** 28.9M read, 187K write across 12 attempts
- **Peak single-task tokens:** 9.5M read (Claude SDK tool filtering)
- **Key issue:** Infrastructure instability, not plan quality

### Run 8bf41c40 (codex_server)
- **Created:** 2026-03-03, **Duration:** 3.27 hours execution
- **Steps completed:** 7/9 (S-01 through S-07)
- **Tasks completed:** 18/28, 1 building, 1 failed (8 attempts)
- **Agent errors:** 6 (session failures, ValueError, ChecklistItemNotFoundError)
- **Checklist gate:** 37/37 passed (never blocked)
- **Grade evaluations:** 29/37 passed; all 8 failures on one task
- **Key issue:** Death spiral on unfulfillable requirement + auto_verify pipe bug

### Task 946657c8 — The Death Spiral
- **Task:** "Create Integration Tests for Step-Level Tool Control"
- **Attempts:** 8, **Total time:** 2.1 hours
- **Root cause 1:** `full_suite_pass` auto_verify used `| tail -5`, masking pytest's non-zero exit code
- **Root cause 2:** R2 ("no regressions") required passing tests that depended on openhands being installed
- **Root cause 3:** Verifier running in sandbox with macOS system-configuration panics, giving inconsistent grades

---

## Appendix B: File Reference

| File | Role |
|------|------|
| `routines/idea-to-plan/routine.yaml` | The plan-maker routine (620 lines) |
| `routines/mcp-ops-c/routine.yaml` | The produced execution routine (863 lines) |
| `docs/mcp-ops-c/` | 28 planning artifacts (4,454 lines total) |
| `docs/plan-runner/idea_to_plan_stripped.md` | LLM execution map for planning |
| `docs/plan-runner/step-files.md` | Step file creation guide |
| `docs/planner/process.md` | Detailed stage-by-stage planning guide |
| `src/orchestrator/workflow/gates.py` | Gate evaluation logic |
| `src/orchestrator/workflow/auto_verify.py` | Auto-verification runner |
| `src/orchestrator/workflow/prompts.py` | Prompt assembly |
| `src/orchestrator/workflow/grades.py` | Grade threshold evaluation |
| `src/orchestrator/workflow/transitions.py` | State machine transitions |
| `src/orchestrator/workflow/engine.py` | Workflow engine |
| `src/orchestrator/workflow/service.py` | Workflow service (async bridge) |

---

## Appendix C: Priority Matrix (Experiment-Adjusted)

Priorities revised based on experiment results. Changes from original assessment marked with arrows.

| ID | Recommendation | Impact | Effort | Priority | Evidence |
|----|---------------|--------|--------|----------|----------|
| G1 | Independent verification in checklist gate | High | Medium | **P1** | D1: 30.4% false-positive rate |
| NEW | Mandatory auto-verify or verifier on every task | High | Low | **P1** | D5: undefended tasks auto-grade to A |
| E1 | Circuit breakers for death spirals | High | Low | **P1** | Run data: 2.1hr death spiral |
| E2 | Baseline test comparison (pre-existing vs regression) | High | Medium | **P1** | D1: 2 tasks destructive, undetected |
| NEW | Diff-quality gate (flag regressive diffs) | High | Medium | **P1** | D1: tasks deleted 130+ lines of tests |
| C6 | Prompt trimming (remove dead-weight sections) | Medium | Low | **P1** ↑ | D4: 39% reduction achievable |
| G4 | Environment-aware requirement filtering | Medium | Low | **P2** | Run data: unfulfillable R2 |
| G3 | Pre-written golden verification tests | High | High | **P2** | D2: 74.6% requirements uncovered |
| P1 | Validate auto_verify correctness during planning | Medium | Medium | **P2** | D2: weak/missing checks |
| D7fix | Verifier model pinning (prevent mid-run switches) | Medium | Low | **P2** ↑ | D7: 4-grade variance on model switch |
| C1 | Context summarization for artifact loading | High | High | **P2** | Analysis: 50K token prompts |
| G2 | Per-requirement grading | Medium | Medium | **P3** ↓ | D3: composite masking not observed |
| C2 | Deduplicate step context | Low | Low | **P3** | Analysis: minor repetition |
| C3 | Token budgets per task **type** (not size) | Medium | Medium | **P3** | D10: complexity, not context, drives cost |
| C4 | Sub-agents for research phases | Medium | Medium | **P3** | D6: 75.6% orientation on research tasks |
| C5 | Compress clarifications on resolution | Low | Low | **P3** | Analysis: unbounded growth |
| E3 | Targeted tool access per step | Medium | Medium | **P3** | Analysis: research tasks lack tools |
| E5 | Agent-type-specific prompt optimization | Medium | Medium | **P3** | D9: Codex 16x faster than OpenHands |
| P2 | Generate golden tests during planning | High | High | **P3** | D2: self-authored tests self-certify |
| P3 | Requirement independence validation | Medium | Medium | **P3** | Run data: unfulfillable requirements |
| E4 | Structured output for agent instructions | Low | High | **P4** ↓ | D6: 18.7% orientation — not a bottleneck |
| P4 | Agent-capability-matched plans | Medium | High | **P4** | D9: agents hit different ceilings |
| P5 | Failure recovery playbooks | Low | Medium | **P4** | Analysis: recovery is ad-hoc |
| G5 | Step-level aggregate gates | Low | Low | **P4** | Analysis: no step-level gates used |

### Experiment Reports

Detailed findings for each experiment are in `docs/reviews/experiments/`:
- `d1-gate-audit.md` — Gate false-positive audit
- `d2-autoverify-audit.md` — Auto_verify command coverage analysis
- `d3-d7-verifier-analysis.md` — Rubric split analysis + verifier consistency
- `d4-context-utilization.md` — Prompt section utilization measurement
- `d5-gate-bypass.md` — Adversarial gate bypass trace
- `d6-time-to-first-action.md` — Agent orientation time analysis
- `d8-plan-freshness.md` — Plan reference staleness over execution
- `d9-d10-comparison.md` — Agent comparison + token budget analysis
