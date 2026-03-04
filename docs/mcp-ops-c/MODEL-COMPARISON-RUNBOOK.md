# MCP-Ops-C Model Comparison Runbook

Run the `mcp-ops-c` routine with different models or agent implementations and compare
output quality, completeness, and correctness against a fixed spec.

## Routine Under Test

- **Routine ID:** `mcp-ops-c`
- **File:** `routines/mcp-ops-c/routine.yaml`
- **Scope:** Implement step-level tool availability and external MCP server support across
  all five agent types (CLI, Claude SDK, Codex Server, OpenHands, User-Managed).
- **Structure:** 9 steps, 27 tasks, 3 milestones.

| Step | Title | Tasks |
|------|-------|-------|
| S-01 | MCPServerConfig Model + StepConfig Extension | 3 |
| S-02 | ExecutionContext Extension + Executor Wiring | 3 |
| S-03 | CLI Agent Tool Hints + MCP Info in Prompt | 3 |
| S-04 | Claude SDK Tool Filtering + MCP Wiring | 3 |
| S-05 | Codex Server Phase Filtering + Context Filtering + MCP Wiring | 3 |
| S-06 | OpenHands Tool Filtering + MCP Wiring | 4 |
| S-07 | User-Managed MCP All-Tools + MCP Info in Prompt Response | 4 |
| S-08 | Integration Tests + Example Routines | 2 |
| S-09 | Final Validation | 3 |

The routine specifies no `agent_type` or `model` per task — those are set at run creation time.

---

## Running a New Comparison

### Prerequisites

```bash
cd /Users/peter/code/task-world

# Server must be running
./dev.sh
# or: uv run uvicorn scripts.serve:app --reload --reload-dir src --reload-dir scripts --port 8000 --host 0.0.0.0
```

### Create and Start a Run

```bash
# Create run (returns run_id)
curl -s -X POST http://localhost:8000/api/runs \
  -H "Content-Type: application/json" \
  -d '{
    "routine_id": "mcp-ops-c",
    "repo_name": "task-world",
    "branch": "main",
    "agent_type": "<AGENT_TYPE>",
    "agent_config": {<MODEL_OVERRIDES>}
  }' | jq .

# Start it
curl -s -X POST http://localhost:8000/api/runs/<RUN_ID>/start
```

Replace `<AGENT_TYPE>` with one of: `cli`, `claude_sdk`, `codex_server`, `openhands`.
Model overrides depend on agent type (e.g., `{"model": "claude-haiku-4-5-20251001"}`).

### Locate the Worktree

The run's worktree lands at:
```
worktrees/run-<RUN_ID>/
```
Branch name: `orchestrator/run-<RUN_ID>`

### Wait for Completion

Monitor via:
```bash
curl -s http://localhost:8000/api/runs/<RUN_ID> | jq '.status, .current_step_index'
```

Or watch the UI at `http://localhost:5173`.

---

## Collecting Stats

All commands below use the worktree path. Set it once:

```bash
WT="worktrees/run-<RUN_ID>"
```

### Line Counts (src / tests / examples)

```bash
# Summary per directory
git -C "$WT" diff main..HEAD --stat -- src/
git -C "$WT" diff main..HEAD --stat -- tests/
git -C "$WT" diff main..HEAD --stat -- examples/

# Precise insertions/deletions
git -C "$WT" diff main..HEAD --numstat -- src/ tests/ examples/

# New vs modified files
git -C "$WT" diff main..HEAD --diff-filter=A --name-only -- src/ tests/ examples/
git -C "$WT" diff main..HEAD --diff-filter=M --name-only -- src/ tests/ examples/

# Commit count
git -C "$WT" log main..HEAD --oneline | wc -l
```

### Full Diff for Code Review

```bash
git -C "$WT" diff main..HEAD
```

---

## Gap Analysis Checklist

Read the full diff and check each of the following areas. For each item, record
**PASS**, **GAP**, or **N/A** and a one-line note.

### A. Schema Foundation (Steps S-01, S-02)

| # | Check | What to look for |
|---|-------|-----------------|
| A1 | `MCPServerConfig` dual transport | `model_validator` rejects both `url+command` set and neither set |
| A2 | `StepConfig` extended | `available_tools: list[str] | None` and `mcp_servers: list[MCPServerConfig] | None`, both default `None` |
| A3 | `ExecutionContext` extended | `step_id`, `available_tools`, `mcp_servers` fields added |
| A4 | Executor populates context | All three fields extracted from step config and passed to builder, verifier, AND recovery phases |
| A5 | Backward compat | Existing routines without new fields still parse; no required fields added |

### B. auth_token_env Handling (Critical — Check Every Agent)

The spec requires: env var **names** stored, never inline tokens. Tokens resolved at
runtime from `os.environ`, never embedded in prompts, `.mcp.json`, or logs.

| # | Agent | Check | What to look for |
|---|-------|-------|-----------------|
| B1 | Claude SDK | `_build_mcp_params` resolves token | `os.environ.get(mcp.auth_token_env)` → `authorization_token` field |
| B2 | CLI | `.mcp.json` auth handling | Token must be resolved from env and injected into child process env or `.mcp.json` — NOT a `${VAR}` shell reference (Claude Code doesn't expand those) |
| B3 | CLI | Prompt doesn't leak tokens | Auth section uses `${ORCHESTRATOR_AUTH_TOKEN}` reference, not the value |
| B4 | Codex Server | `mcpServers` auth handling | `auth_token_env` must be resolved and included (e.g., as header or env entry) |
| B5 | OpenHands | `_build_openhands_mcp_config` resolves token | `os.environ.get(mcp.auth_token_env)` → injected into server env dict |
| B6 | Prompt endpoint | No raw tokens in API response | `CallbackInstructions.mcp_servers` may expose env var **names** but never values |

### C. Tool Filtering (Steps S-03–S-07)

| # | Agent | Check | What to look for |
|---|-------|-------|-----------------|
| C1 | Claude SDK | Deep copy of phase tools | `copy.deepcopy()` or equivalent — mutations must not corrupt module-level `_BUILDER_TOOLS`/`_VERIFIER_TOOLS` |
| C2 | Claude SDK | Step tool registry populated | `_STEP_TOOL_REGISTRY` (or equivalent) must contain entries, otherwise `available_tools` is a no-op |
| C3 | Claude SDK | Additive semantics | Phase tools always included; step tools expand, never restrict |
| C4 | Claude SDK | Unknown tools warn, don't crash | Unknown `available_tools` entries produce `logger.warning`, not exceptions |
| C5 | Codex Server | Grade tool excluded for builders | `build_dynamic_tool_specs(is_verifier=False)` must NOT include `grade`/`set_grade` |
| C6 | Codex Server | Step tool registry populated | Same as C2 — unknown tools should resolve, not just warn |
| C7 | OpenHands | Step tools additive | Tool names list starts from defaults, step tools appended |
| C8 | OpenHands | Unknown tools handled gracefully | `try/except` around tool creation for unknown names |
| C9 | CLI | Step tools in prompt | `available_tools` appear as hint text in the prompt |
| C10 | MCP Server (User-Managed) | All tools registered | `ALL_TOOLS = BUILDER_TOOLS \| VERIFIER_TOOLS`, no phase filtering at registration |

### D. MCP Wiring (Steps S-03–S-07)

| # | Agent | Check | What to look for |
|---|-------|-------|-----------------|
| D1 | Claude SDK | Beta API call | `client.beta.messages.create(betas=["mcp-client-2025-11-20"], mcp_servers=...)` |
| D2 | Claude SDK | STDIO servers handled | Skipped with warning (Connector beta is URL-only) |
| D3 | CLI | `.mcp.json` written | `Path(working_dir) / ".mcp.json"` with correct structure |
| D4 | CLI | MCP info in prompt | External MCP servers section with names/URLs |
| D5 | Codex Server | `mcpServers` in thread params | Array of `{name, url/command, args, env}` in `thread/start` |
| D6 | OpenHands | `mcp_config` passed to OHAgent | `agent_kwargs["mcp_config"] = mcp_config` |
| D7 | OpenHands | Graceful fallback | `TypeError` catch when SDK doesn't support `mcp_config` |
| D8 | User-Managed | `CallbackInstructions.mcp_servers` | Prompt endpoint populates `mcp_servers` from step config |

### E. Integration & Polish (Steps S-08, S-09)

| # | Check | What to look for |
|---|-------|-----------------|
| E1 | Integration tests exist | `test_step_tool_control.py` (or equivalent) covers end-to-end flow |
| E2 | Example routines exist | At least one YAML in `examples/routines/` demonstrating step tools + MCP |
| E3 | Example routines tested | Are they loaded by tests, or purely documentation? |
| E4 | Existing tests pass | No regressions in the baseline test suite |
| E5 | No unrelated changes | Diff limited to routine scope — no drive-by refactors that break things |

---

## Baseline Results (March 2026)

### Run Metadata

| | Sonnet 4.6 (orchestrator) | Haiku 4.5 (orchestrator) | Opus 4.6 (manual CLI) |
|---|-----------|-----------|-------------------|
| **Run ID / Worktree** | `7f0d6bcf` | `cb17fb0b` | `manual-claude-run` |
| **Agent type** | CLI (orchestrated) | CLI (orchestrated) | Claude Code (direct) |
| **Commits** | 27 | 25 | 8 |

### Execution Stats (Orchestrator Runs)

| Metric | Sonnet 4.6 | Haiku 4.5 | Ratio |
|--------|-----------|-----------|-------|
| Wall time | ~12h 20m | ~10h 44m | 0.87x |
| Agent time | 2h 14m | 4h 18m | 1.9x |
| Cost | $24.72 | $18.24 | 0.74x |
| Write tokens | 276K | 570K | 2.1x |
| Cache tokens | 43.5M | 97.6M | 2.2x |
| Actions | 1,148 | 1,978 | 1.7x |
| Tasks needing retries | 2/30 | 6/30 | 3x |
| Max attempts on a task | 2 | 3 | — |
| Agent deaths | 3 | 4 | — |
| Agent errors | 0 | 2 | — |

Sonnet used ~half the agent time and tokens but cost ~35% more due to higher per-token
pricing. Haiku needed 3x more retries and produced 2x the write tokens to reach a
comparable result.

The manual Opus 4.6 run was executed directly via Claude Code CLI without the
orchestrator, so agent time / token / cost stats are not available for direct comparison.
It completed S-01 through S-08 in 8 clean commits (one per step). It did not execute
S-09 (final validation), which is the step that catches test regressions.

### Line Counts

| Metric | Sonnet 4.6 | Haiku 4.5 | Opus 4.6 (manual) |
|--------|-----------|-----------|-------------------|
| **src/ insertions** | 611 | 494 | 393 |
| **src/ deletions** | 395 | 108 | 41 |
| **src/ net** | +216 | +386 | +352 |
| **src/ files** | 18 (0 new, 18 modified) | 12 (0 new, 12 modified) | 12 (0 new, 12 modified) |
| **tests/ insertions** | 1,699 | 1,315 | 961 |
| **tests/ deletions** | 39 | 47 | 13 |
| **tests/ net** | +1,660 | +1,268 | +948 |
| **tests/ files** | 19 (8 new, 11 modified) | 21 (7 new, 14 modified) | 10 (8 new, 2 modified) |
| **examples/ insertions** | 58 | 319 | 90 |
| **examples/ files** | 1 (1 new) | 3 (3 new) | 1 (1 new) |
| **Total insertions** | **2,368** | **2,128** | **1,444** |
| **Total deletions** | **434** | **155** | **54** |
| **Total net** | **+1,934** | **+1,973** | **+1,390** |
| **Total files** | 38 (9 new, 29 modified) | 36 (10 new, 26 modified) | 22 (9 new, 13 modified) |

### Test Results

| Suite | Sonnet 4.6 | Haiku 4.5 | Opus 4.6 (manual) |
|-------|-----------|-----------|-------------------|
| Unit | 1262 pass | 1254 pass | 761 pass, **6 fail** |
| Integration | 287 pass, 1 flaky | 258 pass, 1 flaky | 203 pass, **2 fail** |
| **Total** | **1549** | **1512** | **964** |

The flaky test in Sonnet and Haiku is `test_ws_clarification_requested` — a websocket
race condition under pytest-xdist. Passes in isolation in both.

**Manual run failures (8 total)** — all are pre-existing tests the run didn't update,
not bugs in the new implementation code:

| # | Test | Root Cause | Sonnet/Haiku |
|---|------|-----------|--------------|
| 1–3 | `test_allowlist_*_four_*` (3 tests) | `complete_recovery` added to allowlist, tests expect 4 | Updated |
| 4 | `test_execute_output_event_populates_output_lines` | Output line splitting changed | Updated |
| 5 | `test_check_agent_alive_openhands_local_always_false` | Monitor alive-check behavior changed | Updated |
| 6 | `test_includes_commit_metadata` | `get_commit_diff()` no longer includes commit headers | Updated |
| 7 | `test_config_schema_populated` | `tools` field removed from OpenHands config | Updated |
| 8 | `test_commit_scope_with_ref` | Same `diff_ops` change as #6 | Updated |

The orchestrator runs fixed these in S-09 (Final Validation). The manual run stopped
at S-08 and never ran the "fix all regressions" step.

### Scope Differences

- **Sonnet touched 6 extra src/ files** not in scope: `detector.py`, `monitor.py`,
  `db/models.py`, `routers/agents.py`, `routers/runs.py`, `git/branch_ops.py`.
  This accounts for most of its higher deletion count (395 vs 108).
- **Haiku wrote 3 example routines** (319 lines) vs Sonnet's 1 and the manual run's 1
  (58 and 90 lines). None are loaded by tests — all are documentation-only.
- **Sonnet's integration test** (`test_step_tool_control.py`) was 492 lines vs Haiku's
  132 and the manual run's 331. Sonnet embedded YAML parsing tests; Haiku used only
  Python dicts; the manual run was in between.
- **Manual run was the leanest** — 22 files, 1,390 net lines, 8 clean commits. It
  touched only the 12 core src/ files needed for the feature, with no out-of-scope
  changes. However, it only modified 2 existing test files (vs 11–14 for the orchestrator
  runs), which is why it has 8 test regressions.

### Gap Analysis Results

All three runs share the same core functional gaps. The manual run has two additional
gaps not present in the orchestrator runs.

| # | Severity | Gap | Sonnet | Haiku | Manual | Notes |
|---|----------|-----|--------|-------|--------|-------|
| B2 | **HIGH** | CLI `auth_token_env` — writes `${VAR}` shell reference into `.mcp.json` instead of resolving the token | FAIL | FAIL | FAIL | Claude Code parses `.mcp.json` as JSON, doesn't expand shell vars |
| B4 | **HIGH** | Codex Server `auth_token_env` — completely ignored in `mcpServers` thread params | FAIL | FAIL | FAIL | Copies `url`, `command`, `args`, `env` but never reads `auth_token_env` |
| C1 | **LOW** | Claude SDK shallow copy of phase tools | FAIL | PASS | FAIL | Sonnet and manual use `list()` (latent bug); Haiku uses `copy.deepcopy()` |
| C2 | **MEDIUM** | Claude SDK step tool registry empty — `available_tools` always no-op | FAIL | FAIL | FAIL | Additive code path exists but registry has no entries to resolve against |
| C6 | **MEDIUM** | Codex Server step tool registry also empty — unknown tools warned and skipped | FAIL | FAIL | FAIL | Same pattern as C2 |
| A4 | **MEDIUM** | Recovery phase missing step context | PASS | PASS | **FAIL** | Manual run's `_handle_recovery` omits `step_id`, `available_tools`, `mcp_servers` |
| E4 | **MEDIUM** | Existing tests regressed | PASS | PASS | **FAIL** | 8 pre-existing tests broken; S-09 never executed |
| B6 | **LOW** | Prompt endpoint exposes env var names (not values) via `CallbackInstructions.mcp_servers` | INFO | INFO | INFO | Minor info disclosure |

**B4 is the only gap that matters for actual functionality** — authenticated MCP servers
will silently fail for the Codex Server agent. B2 has the same effect for CLI agents.
C2/C6 are "works as designed but empty" — no additional tools are defined to register
yet, so the additive path is correct but inert. C1 is a latent correctness issue
(currently safe because nothing mutates the tool dicts downstream).

The manual run's two unique gaps (A4 recovery context, E4 test regressions) demonstrate
the value of the orchestrator's S-09 validation step and its builder/verifier cycle,
which catches regressions that a single-pass agent misses.

### Implementation Quality Notes

| Aspect | Sonnet 4.6 | Haiku 4.5 | Opus 4.6 (manual) |
|--------|-----------|-----------|-------------------|
| Phase tool copy safety | `list()` shallow copy | `copy.deepcopy()` (fully safe) | `list()` shallow copy |
| OpenHands MCP fallback | `TypeError` catch | Same | Same |
| MCP server all-tools | `ALL_TOOLS` union | Same | Same |
| Codex grade filtering | Conditional on `is_verifier` | Same | Same |
| STDIO handling (Claude SDK) | Skipped with warning | Same | Same |
| Recovery context wiring | Full (step_id, tools, MCP) | Full | **Missing** |
| Existing test maintenance | All updated | All updated | **8 regressions** |
| Commit discipline | 27 (multi per step) | 25 (multi per step) | 8 (1 per step, clean) |

---

## Comparing a New Run

After collecting stats for a new run, fill in this template:

```markdown
### New Run: <MODEL_NAME>

#### Execution Stats

| Metric | <MODEL_NAME> | Sonnet 4.6 | Haiku 4.5 | Opus 4.6 (manual) |
|--------|-------------|-----------|-----------|-------------------|
| Wall time | | ~12h 20m | ~10h 44m | n/a |
| Agent time | | 2h 14m | 4h 18m | n/a |
| Cost | | $24.72 | $18.24 | n/a |
| Write tokens | | 276K | 570K | n/a |
| Cache tokens | | 43.5M | 97.6M | n/a |
| Actions | | 1,148 | 1,978 | n/a |
| Tasks needing retries | | 2/30 | 6/30 | n/a |
| Max attempts on a task | | 2 | 3 | n/a |
| Agent deaths | | 3 | 4 | n/a |
| Agent errors | | 0 | 2 | n/a |

#### Line Counts

| Metric | <MODEL_NAME> | Sonnet 4.6 | Haiku 4.5 | Opus 4.6 (manual) |
|--------|-------------|-----------|-----------|-------------------|
| src/ insertions | | 611 | 494 | 393 |
| src/ deletions | | 395 | 108 | 41 |
| src/ net | | +216 | +386 | +352 |
| src/ files | | 18 | 12 | 12 |
| tests/ insertions | | 1,699 | 1,315 | 961 |
| tests/ net | | +1,660 | +1,268 | +948 |
| examples/ files | | 1 | 3 | 1 |
| Total net | | +1,934 | +1,973 | +1,390 |
| Total files | | 38 | 36 | 22 |
| Commits | | 27 | 25 | 8 |

#### Test Results

| Suite | <MODEL_NAME> | Sonnet 4.6 | Haiku 4.5 | Opus 4.6 (manual) |
|-------|-------------|-----------|-----------|-------------------|
| Unit pass | | 1,262 | 1,254 | 761 |
| Unit fail | | 0 | 0 | 6 |
| Integration pass | | 287 | 258 | 203 |
| Integration fail | | 1 flaky | 1 flaky | 2 |

#### Gap Checklist

| Check | Result | Sonnet | Haiku | Manual | Notes |
|-------|--------|--------|-------|--------|-------|
| A1–A5 (Schema) | | PASS | PASS | PASS | |
| A4 (Recovery context) | | PASS | PASS | FAIL | Manual omits step fields in recovery |
| B1 (Claude SDK auth) | | PASS | PASS | PASS | |
| B2 (CLI .mcp.json auth) | | FAIL | FAIL | FAIL | All three wrote ${VAR} instead of resolving |
| B3 (CLI prompt no leak) | | PASS | PASS | PASS | |
| B4 (Codex auth) | | FAIL | FAIL | FAIL | All three ignored auth_token_env |
| B5 (OpenHands auth) | | PASS | PASS | PASS | |
| B6 (Prompt endpoint) | | INFO | INFO | INFO | |
| C1 (Deep copy) | | FAIL | PASS | FAIL | Only Haiku used deepcopy |
| C2 (SDK tool registry) | | FAIL | FAIL | FAIL | Empty in all three |
| C3–C4 (SDK additive + unknown) | | PASS | PASS | PASS | |
| C5 (Codex grade filtering) | | PASS | PASS | PASS | |
| C6 (Codex tool registry) | | FAIL | FAIL | FAIL | Empty in all three |
| C7–C8 (OpenHands tools) | | PASS | PASS | PASS | |
| C9 (CLI tool hints) | | PASS | PASS | PASS | |
| C10 (MCP all-tools) | | PASS | PASS | PASS | |
| D1–D8 (MCP wiring) | | PASS | PASS | PASS | |
| E1–E2 (Tests + examples) | | PASS | PASS | PASS | |
| E4 (Existing tests pass) | | PASS | PASS | FAIL | 8 regressions in manual run |

#### New Gaps Found
(list any gaps not present in the three baselines above)

#### Baseline Gaps Fixed
(note which of B2/B4/C1/C2/C6/A4 the new model got right)

#### Scope Discipline
(did the model stay within routine scope, or make unrelated changes?)
```
