# Manual Claude CLI Run — MCP-Ops-C

Paste the prompt below into a fresh Claude Code session started inside the worktree:

```bash
cd worktrees/manual-claude-run
claude
```

---

## Prompt

```
You are implementing a feature spec defined in a routine YAML file. Your job is to read
the routine, understand all requirements, and implement them step by step — writing
production code, tests, and example files as specified.

## Your Spec

Read `routines/mcp-ops-c/routine.yaml` — this is your single source of truth. It defines
9 steps (S-01 through S-09) with 27 tasks total. Each task has a description, requirements,
and auto-verify commands.

Supporting design docs are in `docs/mcp-ops-c/` — read the intent, architecture, and
step plan files for additional context. The step implementation guides in
`docs/mcp-ops-c/steps/step-XX.md` contain detailed implementation plans per task.

## Rules

1. **Work sequentially through steps S-01 → S-09.** Complete all tasks in a step before
   moving to the next. Tasks within a step can be done in any order.

2. **Read existing code before modifying it.** Understand the patterns in the codebase.
   Read AGENTS.md for project conventions.

3. **Run each task's auto_verify commands after implementing it.** These are the acceptance
   criteria. A task is done when its verify commands pass.

4. **Run the full test suite periodically** (at minimum after each step):
   ```
   uv run pytest tests/unit -x -q
   uv run pytest tests/integration -x -q
   ```
   The baseline is 330 unit tests and 235 integration tests passing (2 expected failures
   for missing openhands module, 3 skipped). Do not regress.

5. **Commit after each step** with a descriptive message summarizing what was implemented.

6. **Do NOT look at other git branches, worktrees, or run artifacts.** You must implement
   from the spec and existing code only. Do not run `git worktree list`, `git branch -a`,
   or check out other branches. The only branch you should interact with is your current
   branch (main).

7. **Follow project conventions from AGENTS.md:**
   - No mocking in tests (no patch, MagicMock, or monkeypatching)
   - Use real objects with dependency injection
   - Pydantic for all data models
   - Async by default
   - Explicit error types

8. **Key implementation concerns to get right:**
   - `auth_token_env` stores environment variable NAMES, never inline tokens. Every agent
     that handles MCP servers must resolve the env var at runtime via `os.environ.get()`.
     Tokens must never appear in prompt text, .mcp.json files, or log output.
   - Tool filtering is ADDITIVE: phase tools (builder/verifier baselines) are always
     included; step-level `available_tools` expand the set, never restrict it.
   - Unknown tool names produce warnings, never errors or crashes.
   - All new fields must default to None for backward compatibility.

## Getting Started

1. Read `routines/mcp-ops-c/routine.yaml` in full
2. Read `AGENTS.md` for project conventions
3. Read `docs/mcp-ops-c/intent.md` and `docs/mcp-ops-c/architecture.md` for design context
4. Read `docs/mcp-ops-c/steps/step-01.md` for your first step's implementation plan
5. Explore the existing code in `src/orchestrator/` to understand the codebase
6. Begin implementing S-01
```
