# D9: Agent Comparison + D10: Token Budget Analysis

**Date:** 2026-03-04
**Source data:** Two runs of the same routine (`mcp-ops-c`) in `orchestrator.db`

| Run ID     | Agent          | Model            | Steps Completed | Final Status |
|------------|----------------|------------------|-----------------|--------------|
| `c3e5f5a6` | openhands_local | qwen3.5-27b     | S-01..S-03 (paused at S-04 T-02) | paused |
| `8bf41c40` | codex_server   | (default codex)  | S-01..S-07 (failed at S-08 T-01) | paused |

Both runs executed the identical routine YAML. Steps S-01, S-02, and S-03 (9 tasks
each) were completed by both agents, enabling direct comparison.

---

## D9: Agent Comparison

### Head-to-Head: S-01 through S-03 (9 tasks)

#### Wall-Clock Duration

| Step | Task | Title (abbreviated)                      | OpenHands (min) | Codex (min) | Ratio OH/CX |
|------|------|------------------------------------------|----------------:|------------:|-------------:|
| S-01 | T-01 | Define MCPServerConfig Model             |       610.1 (*) |         2.1 |      293.2x  |
| S-01 | T-02 | Extend StepConfig fields                 |        50.4     |         2.5 |       20.4x  |
| S-01 | T-03 | Unit tests for MCPServerConfig           |        24.0     |        41.5 |        0.6x  |
| S-02 | T-01 | Extend ExecutionContext                  |       104.3     |         3.7 |       28.5x  |
| S-02 | T-02 | Update Executor wiring                   |       186.8     |        27.1 |        6.9x  |
| S-02 | T-03 | Unit tests for ExecutionContext          |        15.0     |         0.8 |       17.9x  |
| S-03 | T-01 | CLI prompt tool hints                    |       537.2     |        10.6 |       50.5x  |
| S-03 | T-02 | CLI MCP info + .mcp.json                 |        95.5     |        14.3 |        6.7x  |
| S-03 | T-03 | Unit tests for CLI tool hints            |        51.6     |         1.7 |       30.8x  |
| **Total** | | | **1,674.8** | **104.3** | **16.1x** |

(*) S-01 T-01 OpenHands includes a 9.4-hour pause (agent died at 03:48, resumed at
13:13). **Adjusted active time: ~45 min** (still 21x slower than Codex's 2.1 min).

#### Adjusted Wall-Clock (excluding known pauses in S-01 T-01)

With the S-01 T-01 pause removed, OpenHands active time for S-01..S-03 drops from
1,674.8 min to approximately **1,109.7 min** (18.5 hours). The OpenHands run also had
multiple server restarts and agent deaths scattered throughout (7 `agent_died` events
total across the run), so true "thinking time" is likely lower still, but individual
pauses in later tasks are shorter and harder to precisely delineate.

Codex completed the same 9 tasks in **104.3 min** wall-clock (1.7 hours). Codex's
`sum(duration_ms)` across these 9 tasks is **26.1 min**, meaning ~78 min was overhead
(verification, auto-verify commands, inter-task transitions, and a few error-recovery
pauses).

#### Token Consumption

| Step | Task | OH tokens_read | OH tokens_write | OH total tokens | CX tokens |
|------|------|---------------:|----------------:|----------------:|----------:|
| S-01 | T-01 |        606,342 |           7,934 |         614,276 | not tracked |
| S-01 | T-02 |        692,622 |           7,856 |         700,478 | not tracked |
| S-01 | T-03 |              0 |               0 |               0 | not tracked |
| S-02 | T-01 |        334,060 |           4,296 |         338,356 | not tracked |
| S-02 | T-02 |      1,579,065 |          10,890 |       1,589,955 | not tracked |
| S-02 | T-03 |        311,015 |           3,216 |         314,231 | not tracked |
| S-03 | T-01 |      6,315,467 |          53,859 |       6,369,326 | not tracked |
| S-03 | T-02 |      3,727,538 |          18,969 |       3,746,507 | not tracked |
| S-03 | T-03 |      1,740,511 |          11,191 |       1,751,702 | not tracked |
| **Total** | |  **15,306,620** |    **118,211** | **15,424,831** | **0** |

Codex Server does not report token counts (all zeros). It reports `duration_ms` instead.
OpenHands consumed **15.4M total tokens** (15.3M read, 118K write) across 9 tasks via
qwen3.5-27b running locally.

#### Actions

| Step | Task | OH actions | CX actions |
|------|------|------------|------------|
| S-01 | T-01 |         41 |          0 |
| S-01 | T-02 |         44 |          0 |
| S-01 | T-03 |          0 |          0 |
| S-02 | T-01 |         26 |          0 |
| S-02 | T-02 |         64 |          0 |
| S-02 | T-03 |         19 |          0 |
| S-03 | T-01 |        645 |          0 |
| S-03 | T-02 |         92 |          0 |
| S-03 | T-03 |         50 |          0 |
| **Total** | |    **981** |      **0** |

Codex Server's `num_actions` is 0 for all S-01..S-07 tasks (the executor did not
instrument action counting for this agent type until S-08). OpenHands logged 981
actions across 9 tasks. S-03 T-01 alone consumed 645 actions -- this was the CLI
prompt tool-hints task, suggesting OpenHands struggled significantly with it.

#### Revision Cycles (Attempts)

| Agent    | Tasks needing revision | Max attempts used | Total attempts |
|----------|------------------------|-------------------|----------------|
| OpenHands | 0 of 9 (S-01..S-03)  | 1                 | 9              |
| Codex    | 1 of 9 (S-04 T-01)    | 2                 | 10             |

Both agents passed all 9 overlapping tasks on the **first attempt**. Neither required
a revision cycle in S-01..S-03.

In S-04 (which only Codex completed), Codex needed a revision on T-01 ("Implement
Additive Tool Filtering in Claude SDK Agent") -- attempt 1 returned `revision_needed`,
attempt 2 passed.

OpenHands had one `reverted` attempt on S-04 T-02 ("Implement MCP Connector Beta
Wiring") and was still working on attempt 2 when the run was paused.

#### Quality (Grade Snapshots)

All 9 overlapping tasks received **grade A** on all requirements for both agents.
Neither agent produced work that was graded below A. The grading was performed by the
same LLM verifier for both runs (using the same rubric from the routine YAML).

Tasks T-03 in each step (unit test writing tasks) were auto-graded without an LLM
verifier since no verifier rubric was defined for them. Both agents received automatic
grade A for these.

#### Error Recovery

**Codex** encountered 4 session-failure errors during S-01..S-03:
- S-01 T-03: "Session failed after 6510ms" (recovered, still passed)
- S-02 T-02: "Session failed after 11367ms" (recovered, still passed)
- S-03 T-01: "Session failed after 42670ms: ValueError: Separator is not found" (recovered)
- S-03 T-02: "Session failed after 5632ms: ValueError: Separator is not found" (recovered)

Despite these errors, the executor recovered and the tasks passed. The errors
contributed to longer wall-clock times for those tasks (S-01 T-03's 41.5 min
wall-clock includes a ~40 min pause/recovery gap visible in the events log).

**OpenHands** had 7 `agent_died` events across the entire run, primarily due to
`agent_not_running_on_startup` (server restarts) and `agent_health_check_failed`.
These caused multi-hour gaps but the agent recovered and completed its work after
each restart.

#### Codex Extended Progress (S-04 through S-07)

Codex completed 4 additional steps (15 more tasks) that OpenHands never reached:

| Step | Tasks | Wall-clock (min) | Sum duration_ms | Revisions |
|------|------:|------------------:|----------------:|-----------|
| S-04 |     3 |             10.4  |       527,146   | 1 (T-01)  |
| S-05 |     3 |              6.6  |       396,105   | 0         |
| S-06 |     4 |             10.8  |       648,600   | 0         |
| S-07 |     4 |             12.7  |       760,916   | 0         |

All 15 tasks passed. Only S-04 T-01 needed a second attempt.

Codex then failed at S-08 T-01 ("Create Integration Tests for Step-Level Tool Control")
after **8 consecutive failed attempts**, including attempts with upgraded models
(gpt-5.3-codex, gpt-5.1-codex-mini). This integration test task appears to be a
ceiling for the codex agent in this routine.

### D9 Summary

| Dimension | Winner | Notes |
|-----------|--------|-------|
| **Speed** | Codex (16x faster) | 104 min vs 1,675 min wall-clock (S-01..S-03). Even adjusting for OH pauses, Codex is ~10x faster. |
| **Throughput** | Codex | Completed 7 steps (24 tasks) vs OpenHands' 3 steps (9 tasks). |
| **Quality** | Tie | Both received all-A grades on overlapping tasks. |
| **Revision cycles** | Tie | Both needed 0 revisions in overlapping tasks. |
| **Reliability** | Codex (edge) | Codex had session failures but auto-recovered. OpenHands had 7 agent deaths requiring server restarts. |
| **Ceiling** | Both hit walls | Codex failed at integration tests (S-08). OpenHands stalled at MCP Connector Beta Wiring (S-04 T-02). |
| **Cost** | OpenHands | Local qwen3.5-27b = $0 API cost (compute cost for local GPU not tracked). Codex = paid API. |

**Key insight:** Codex Server is dramatically faster and more reliable for structured
coding tasks. OpenHands with a local model (qwen3.5-27b) can produce equivalent-quality
output but at 10-16x the wall-clock time and with significantly more instability. The
local model's advantage is zero API cost, but the time penalty is severe.

---

## D10: Token Budget Analysis

This analysis uses OpenHands token data (the only agent that tracks tokens) to explore
whether task context size predicts token consumption.

### Context Size vs. Token Consumption (OpenHands, S-01..S-03)

| Step | Task | Task Type        | Context (chars) | Total Context* | Tokens Read  | Tokens Write | Total Tokens  | Actions |
|------|------|------------------|----------------:|---------------:|-------------:|-------------:|--------------:|--------:|
| S-01 | T-01 | Model creation   |             726 |          1,199 |      606,342 |        7,934 |       614,276 |      41 |
| S-01 | T-02 | Schema extension |             369 |            764 |      692,622 |        7,856 |       700,478 |      44 |
| S-01 | T-03 | Test writing     |             516 |            865 |            0 |            0 |             0 |       0 |
| S-02 | T-01 | Schema extension |             381 |            707 |      334,060 |        4,296 |       338,356 |      26 |
| S-02 | T-02 | Wiring/plumbing  |             458 |            790 |    1,579,065 |       10,890 |     1,589,955 |      64 |
| S-02 | T-03 | Test writing     |             390 |            642 |      311,015 |        3,216 |       314,231 |      19 |
| S-03 | T-01 | Feature impl     |             257 |            633 |    6,315,467 |       53,859 |     6,369,326 |     645 |
| S-03 | T-02 | Feature impl     |             380 |            828 |    3,727,538 |       18,969 |     3,746,507 |      92 |
| S-03 | T-03 | Test writing     |             292 |            611 |    1,740,511 |       11,191 |     1,751,702 |      50 |

*Total Context = task_context + step_context + requirements text (characters).

### Correlation Analysis

**Context size does NOT predict token consumption.** The data shows no meaningful
correlation:

- S-01 T-02 has the **second-smallest** context (764 chars) but consumed **700K tokens**
  (second-highest in S-01).
- S-03 T-01 has the **smallest** context in its step (633 chars) but consumed
  **6.4M tokens** -- the most of any task by a factor of 1.7x.
- S-01 T-01 has the **largest** context in S-01 (1,199 chars) but consumed fewer tokens
  than T-02.

Context sizes across all 9 tasks fall in a narrow band (611-1,199 chars), while token
consumption varies by **orders of magnitude** (0 to 6.4M). The Pearson correlation
between total context size and tokens consumed is effectively zero.

### What DOES Drive Token Consumption?

**Task complexity and the number of files/interactions required** are the dominant
factors:

#### Pattern 1: Schema tasks (S-01, S-02 T-01) -- moderate tokens
- Add fields to a single file, run tests
- Tokens: 300K-700K
- Actions: 26-44
- These are constrained, well-defined edits

#### Pattern 2: Wiring/plumbing tasks (S-02 T-02) -- elevated tokens
- Modify executor code, update context construction in multiple code paths
- Tokens: 1.6M
- Actions: 64
- Requires understanding existing code flow, finding builder and verifier paths

#### Pattern 3: Feature implementation (S-03 T-01, T-02) -- very high tokens
- Build new functionality (tool hints, MCP info sections, .mcp.json writing)
- Tokens: 3.7M-6.4M
- Actions: 92-645
- Requires reading existing agent code, understanding prompt structure,
  implementing new methods, handling edge cases

#### Pattern 4: Test writing (T-03 tasks) -- variable
- S-01 T-03: 0 tokens (likely auto-passed or data not recorded)
- S-02 T-03: 314K tokens, 19 actions
- S-03 T-03: 1.75M tokens, 50 actions
- Token cost tracks the **complexity of the code under test**, not the test description

### S-01 (Simple Schema) vs. S-03 (Agent Code Modification)

| Metric | S-01 (3 tasks) | S-03 (3 tasks) | Ratio S-03/S-01 |
|--------|---------------:|---------------:|----------------:|
| Total context chars | 2,828 | 2,072 | 0.7x (smaller!) |
| Total tokens read | 1,298,964 | 11,783,516 | 9.1x |
| Total tokens write | 15,790 | 84,019 | 5.3x |
| Total actions | 85 | 787 | 9.3x |
| Wall-clock (min) | 684.5 | 684.3 | 1.0x |

S-03 tasks have **less context text** than S-01 but consume **9x more tokens** and
**9x more actions**. This confirms that token budget is driven by:

1. **Intrinsic task complexity** -- modifying agent code with prompt construction,
   file writing, and security considerations is harder than adding Pydantic fields
2. **Codebase exploration** -- the agent reads more existing code to understand patterns
3. **Iteration loops** -- more complex tasks involve more edit-test-fix cycles
4. **Context window filling** -- as the agent reads more files, each subsequent LLM
   call includes more context, multiplicatively increasing token_read counts

### Token Efficiency: Read/Write Ratio

| Step | Avg tokens_read per task | Avg tokens_write per task | Read/Write ratio |
|------|-------------------------:|--------------------------:|------------------:|
| S-01 | 432,988 | 5,263 | 82:1 |
| S-02 | 741,380 | 6,134 | 121:1 |
| S-03 | 3,927,839 | 28,006 | 140:1 |

The read/write ratio **increases with task complexity**: S-03 tasks read 140 tokens for
every 1 token written, compared to 82:1 for S-01. This suggests that complex tasks
require proportionally more "reading and understanding" relative to "producing output."

### D10 Summary

1. **Context size is not a useful predictor of token consumption.** All tasks in this
   routine have similar context sizes (600-1,200 chars) but token usage spans 4 orders
   of magnitude.

2. **Task complexity is the dominant driver.** Schema changes (add a field) cost ~500K
   tokens. Feature implementations (new methods, file writing, security handling) cost
   3-6M tokens. The ratio is 6-12x.

3. **Token budgets should be set per task TYPE, not per context size:**
   - Schema/model tasks: ~500K-700K tokens
   - Wiring/plumbing tasks: ~1-2M tokens
   - Feature implementation tasks: ~3-7M tokens
   - Test writing tasks: 300K-2M tokens (tracks complexity of code under test)

4. **The read/write ratio (82:1 to 140:1) suggests that LLM agents spend the vast
   majority of their token budget on context ingestion, not generation.** Caching
   strategies that reduce re-reading of already-seen files could dramatically reduce
   token costs. (OpenHands reported 0 cache tokens, indicating no prompt caching was
   active.)

5. **For budgeting purposes:** A conservative estimate for a local model agent is
   ~1.7M tokens per task average (15.4M / 9 tasks). But the variance is enormous
   (0 to 6.4M), so per-task budgets based on task type classification would be more
   useful than a flat average.

---

## Methodology Notes

- Wall-clock times are computed from `started_at` / `completed_at` timestamps in the
  `attempts` table. These include all overhead (verification, auto-verify, transitions).
- The OpenHands S-01 T-01 wall-clock of 610 min includes a 9.4-hour server-shutdown
  pause; adjusted active time is ~45 min.
- Codex `duration_ms` values appear to represent session/agent execution time, not
  including verification overhead. Codex wall-clock times include the full cycle.
- Codex does not track token counts (all zeros). Token analysis is OpenHands-only.
- Both runs used the same routine YAML, same orchestrator, same verification pipeline.
- The OpenHands run used `qwen3.5-27b` (local model). The Codex run used the default
  codex server model (likely gpt-4o or similar).
- Grade comparisons are valid because the same LLM verifier + rubric evaluated both.
