# D6: Time-to-First-Action Analysis

**Run:** `8bf41c40-9db2-49a6-b188-0145631ce134`
**Date:** 2026-03-04
**Agent type:** codex_server (all 22 tasks)

## Methodology

For each of the 22 tasks that passed on their first attempt, the analysis measures
how long the builder agent spent "orienting" (reading files, exploring the codebase,
checking existing state) before taking its first useful modification action (editing
a file, writing code, running tests).

**Data sources:**
- `task_status_changed` events to isolate the builder phase (building -> verifying transition)
- `agent_output` streaming events (token-level) to reconstruct the agent's narrative text
- `run_status_changed` events to subtract paused intervals from wall-clock time

**Method:**
1. Builder phase events are split into "segments" -- blocks of streamed assistant text
   separated by gaps > 3 seconds (which correspond to tool execution).
2. Each segment is classified as orientation (reading, checking, inspecting) or action
   (editing, patching, writing tests, confirming changes) using pattern matching on
   the agent's narrative.
3. Orientation time = time from builder start to the end of the last orientation-only
   segment before the first action segment.
4. Paused intervals (server restarts, manual pauses) are subtracted from all durations.

**Limitation:** The Codex server agent only streams assistant narrative text, not tool
call details. When the agent enters long silent tool-execution sequences (common after
pauses), the narrative segments become sparse and action detection is unreliable.
Five tasks could not be classified because the builder ran silently for most of its
duration. Those are reported separately.

## Per-Task Results

### Tasks with Detected Action Boundary (17 tasks)

| # | Task | Category | Builder Active (s) | Orientation (s) | Orientation % | Segments | First Action Seg | Detection |
|---|------|----------|-------------------|-----------------|---------------|----------|-----------------|-----------|
| 1 | Define MCPServerConfig Model | impl | 71 | 19.9 | 28.1% | 9 | 3 | "now has to look like" (post) |
| 2 | Extend StepConfig with available_tools | impl | 80 | 18.3 | 22.9% | 12 | 3 | "the gap for this task is" (pre) |
| 4 | Extend ExecutionContext with Step-Level Fields | impl | 150 | 25.6 | 17.1% | 6 | 4 | "requirements are covered" (post) |
| 6 | Write Unit Tests for ExecutionContext Extension | test | 44 | 8.0 | 18.3% | 7 | 2 | "already matches" (post) |
| 10 | Implement MCP Connector Beta Wiring | impl | 194 | 33.9 | 17.5% | 13 | 5 | "patch is in" (post) |
| 11 | Write Unit Tests for Claude SDK Tool Filtering | test | 76 | 14.2 | 18.7% | 9 | 3 | "I have enough context" (pre) |
| 12 | Add Phase Filtering to build_dynamic_tool_specs() | impl | 75 | 10.8 | 14.4% | 11 | 2 | "is already phase-aware" (post) |
| 13 | Add Step-Level Tool Filtering to dynamicTools | impl | 95 | 22.9 | 24.0% | 11 | 4 | "I have enough context" (pre) |
| 14 | Write Unit Tests for Codex Server Filtering | test | 97 | 9.3 | 9.6% | 9 | 2 | "existing test file only covers" (pre) |
| 15 | Research OpenHands SDK MCP Support | research | 117 | 88.5 | 75.6% | 12 | 10 | "requirements are satisfied" (post) |
| 16 | Implement Step-Level Tool Filtering in OpenHands | impl | 200 | 68.9 | 34.6% | 13 | 9 | "targeted tests pass" (post) |
| 17 | Implement MCP Config Passthrough to OpenHands | impl | 112 | 32.8 | 29.2% | 11 | 5 | "implementation change is in place" (post) |
| 18 | Write Unit Tests for OpenHands Tool Filtering | test | 75 | 5.1 | 6.8% | 9 | 1 | "already matches" (post) |
| 19 | Register All Tools in MCP Server | impl | 305 | 26.9 | 8.8% | 13 | 5 | "I have enough context" (pre) |
| 20 | Extend CallbackInstructions with mcp_servers | impl | 46 | 3.3 | 7.2% | 6 | 1 | "schema already contains" (post) |
| 21 | Populate mcp_servers in Prompt Response Endpoint | impl | 159 | 47.8 | 30.0% | 13 | 6 | "patch is in" (post) |
| 22 | Write Unit Tests for All-Tools Registration | test | 59 | 21.2 | 35.7% | 9 | 4 | "The edit is" (post) |

### Tasks with Insufficient Event Coverage (5 tasks)

These tasks had limited builder-phase streaming events (often 1 text segment before a
long pause, then silent tool execution after resume). All 5 confirmed to have made code
modifications via different start/end commit hashes, but the orientation boundary could
not be reliably determined.

| # | Task | Category | Builder Active (s) | Segments | Reason |
|---|------|----------|-------------------|----------|--------|
| 3 | Write Unit Tests for MCPServerConfig | test | 84 | 1 | 40-min pause after 1 segment; silent builder after resume |
| 5 | Update Executor to Populate Step-Level Context | impl | 176 | 5 | All segments read-oriented; action ran silently |
| 7 | Add Step-Level Tool Hints to CLI Prompt | impl | 273 | 5 | All segments read-oriented; action ran silently |
| 8 | Add MCP Server Info to CLI Prompt and .mcp.json | impl | 254 | 1 | 9-min pause after 1 segment; silent builder after resume |
| 9 | Write Unit Tests for CLI Tool Hints and MCP Info | test | 93 | 8 | All segments read/check-oriented; edit not narrated |

## Summary Statistics

### Detected Tasks Only (n=17)

| Metric | Orientation (s) | Orientation (%) |
|--------|----------------|-----------------|
| Mean | 26.9 | 23.4 |
| Median | 21.2 | 18.7 |
| P25 | 10.8 | 14.4 |
| P75 | 33.9 | 30.0 |
| Min | 3.3 | 6.8 |
| Max | 88.5 | 75.6 |

### By Task Category (detected only)

| Category | Count | Mean Orient (s) | Mean Orient (%) | Mean Builder Active (s) |
|----------|-------|-----------------|-----------------|------------------------|
| Implementation | 11 | 28.3 | 21.3 | 118.2 |
| Test | 5 | 11.6 | 17.8 | 70.1 |
| Research | 1 | 88.5 | 75.6 | 117.1 |

### Fastest Orientation (< 15% of builder)

| Task | Orientation | Builder | % |
|------|------------|---------|---|
| Write Unit Tests for OpenHands Tool Filtering | 5.1s | 75s | 6.8% |
| Extend CallbackInstructions with mcp_servers | 3.3s | 46s | 7.2% |
| Register All Tools in MCP Server | 26.9s | 305s | 8.8% |
| Write Unit Tests for Codex Server Filtering | 9.3s | 97s | 9.6% |
| Add Phase Filtering to build_dynamic_tool_specs() | 10.8s | 75s | 14.4% |

### Slowest Orientation (> 30% of builder)

| Task | Orientation | Builder | % |
|------|------------|---------|---|
| Research OpenHands SDK MCP Support | 88.5s | 117s | 75.6% |
| Write Unit Tests for All-Tools Registration | 21.2s | 59s | 35.7% |
| Implement Step-Level Tool Filtering in OpenHands | 68.9s | 200s | 34.6% |
| Populate mcp_servers in Prompt Response Endpoint | 47.8s | 159s | 30.0% |
| Implement MCP Config Passthrough to OpenHands | 32.8s | 112s | 29.2% |

## Key Findings

### 1. Orientation typically consumes ~20% of builder time

For the 17 tasks with reliable measurement, the median orientation percentage is
18.7% (mean 23.4%). The typical agent reads 2-4 files before making its first
modification, taking 10-30 seconds of active time.

### 2. Test-writing tasks orient faster than implementation tasks

Test tasks average 11.6s orientation (17.8%) vs implementation tasks at 28.3s (21.3%).
This makes sense: test tasks target specific files identified in the step instructions,
while implementation tasks often need to survey multiple call sites and understand
existing patterns before editing.

### 3. Research tasks have the highest orientation ratio

The one research task (OpenHands SDK MCP Support) spent 75.6% of its builder time
reading SDK source code, docs, and installed packages before writing a research note.
This is expected behavior -- the task's primary deliverable IS the investigation.

### 4. "Already done" detection is fast

Three tasks found their work already present from prior builder runs in the same
worktree (segments 1, 2, or 3 = "already matches", "schema already contains",
"is already phase-aware"). These oriented in 3-11 seconds before confirming the
existing state satisfied requirements.

### 5. Silent tool execution creates measurement gaps

Five of 22 tasks (23%) could not be reliably measured because the Codex server agent
entered long silent tool-execution periods (no streamed narrative). This is especially
common after run pauses/resumes, where the agent resumes execution without narrating
its actions. Future instrumentation should log tool call metadata (tool name,
file paths) separately from the assistant narrative to enable precise measurement.

### 6. Orientation does not correlate strongly with builder duration

The correlation is weak: short tasks (46-75s) can have either low (7%) or moderate
(24%) orientation. Long tasks (200-305s) similarly range from 9% to 35%. The primary
driver of builder duration is the complexity of the edit and verification steps, not
the orientation phase.

## Recommendations

1. **Instrument tool calls separately.** Recording tool name, target file, and
   timestamp for each tool invocation would enable precise orientation/action
   classification without relying on narrative text analysis.

2. **Pre-populate context in prompts.** For tasks in later steps that build on earlier
   steps' work, including a summary of recent changes in the prompt could reduce the
   3-5 file reads agents typically perform during orientation.

3. **Consider orientation budgets.** A 20% orientation ratio is reasonable, but tasks
   spending > 50% of their time orienting (like the research task) might benefit from
   more structured context in their step instructions.
