# Token Usage Analysis: Run b14aa49f

**Run ID:** `b14aa49f-5be8-46a1-97ec-db1db06c685f`
**Date:** 2026-03-10
**Model:** claude-haiku-4-5-20251001
**Duration:** 3.46 hours
**Structure:** 6 steps, 20 tasks, 21 attempts (1 revision)
**Total tokens:** 97.1M (96.6M cache, 509K write, 12K read)
**Estimated cost:** ~$9.77

## Context Construction

Each attempt starts a **completely fresh agent process** with a newly built prompt. There is no session continuity between tasks — the orchestrator builds a new `ExecutionContext` each time containing only the task description, requirements, variable substitutions, and (for retries) verifier feedback.

The 96.6M "cache" tokens are **Anthropic prompt caching**, not orchestrator-level context reuse. Within a single agent session, each tool call triggers a new API round-trip where the conversation prefix (system prompt + prior turns) is re-sent and hits the prompt cache. The more tool calls an agent makes, the more cache tokens accumulate.

**No sub-agents were used.** All 1,834 tool calls ran within flat, single-agent sessions.

## Per-Attempt Breakdown

| Task | Att | Tools | Cache | Cache/Tool | Duration |
|------|-----|-------|-------|------------|----------|
| Create ConditionEvaluator Module with Core Types | 1 | 36 | 1.24M | 34K | 5.3m |
| Implement Tokenizer and Recursive Descent Parser | 1 | 49 | 2.77M | 57K | 8.8m |
| Implement Safety Constraints | 1 | 41 | 2.03M | 50K | 4.3m |
| Write Comprehensive Unit Tests for Evaluator | 1 | 31 | 1.45M | 47K | 4.0m |
| Add StepCondition Model and StepConfig.condition Field | 1 | 72 | 2.81M | 39K | 6.6m |
| Add Skip Fields to StepState and StepModel with Migration | 1 | 82 | 3.45M | 42K | 8.7m |
| Add StepSkipped Event and Update Factory | 1 | 97 | 5.61M | 58K | 8.6m |
| Implement Condition Evaluation in Step Progression | 1 | 107 | 6.90M | 64K | 10.1m |
| Implement Chain-Skip and Edge Cases | 1 | 113 | 9.20M | 81K | 11.7m |
| Update Persistence and Write Integration Tests | 1 | 86 | 4.77M | 55K | 24.2m |
| Implement Repeat-For Expansion Logic | 1 | 113 | 6.82M | 60K | 14.4m |
| Handle Edge Cases and Repeat-For + When Combo | 1 | 47 | 1.85M | 39K | 7.2m |
| Write Repeat-For Tests | 1 | 57 | 3.99M | 70K | 8.4m |
| Write Repeat-For Tests | 2 | 97 | 4.97M | 51K | 12.5m |
| Add API Schemas for Conditional Steps | 1 | 66 | 3.17M | 48K | 8.3m |
| Add Skip-Step API Endpoint | 1 | 152 | 10.06M | 66K | 15.5m |
| Write API Integration Tests | 1 | 119 | 7.05M | 59K | 14.2m |
| Update TypeScript Types and Step State Utils | 1 | 127 | 4.87M | 38K | 10.3m |
| Update StepTimeline and ActivityFeed Components | 1 | 118 | 6.29M | 53K | 11.2m |
| Add Manual Gate UI | 1 | 132 | 2.68M | 20K | 5.0m |
| Write Frontend Tests | 1 | 92 | 4.59M | 50K | 8.4m |

### Key observations

- **Cache/tool ranges from 20K to 81K** depending on how much file content the agent accumulates in its conversation window before each subsequent call.
- **Most expensive attempt:** "Add Skip-Step API Endpoint" at 10.06M cache tokens / 152 tool calls — an API endpoint task that required reading many existing router, schema, and test files.
- **Cache/tool grows within tasks** as the conversation lengthens, but resets at task boundaries (fresh agent).

## Tool Call Breakdown

**1,834 total tool calls across 21 attempts.**

| Tool | Count | % |
|------|-------|---|
| Bash | 1,218 | 66.4% |
| Read | 370 | 20.2% |
| Edit | 140 | 7.6% |
| Glob | 60 | 3.3% |
| Grep | 25 | 1.4% |
| TodoWrite | 11 | 0.6% |
| Write | 10 | 0.5% |

### Bash sub-categories

| Category | Count | % of Bash | % of All |
|----------|-------|-----------|----------|
| Navigation (ls, cd) | 248 | 20.4% | 13.5% |
| Searching (grep, find) | 332 | 27.3% | 18.1% |
| Reading files (cat, head, tail) | 212 | 17.4% | 11.6% |
| Running tests (pytest, vitest) | 155 | 12.7% | 8.5% |
| Git operations | 126 | 10.3% | 6.9% |
| curl (API testing) | 145 | 11.9% | 7.9% |

### Productive vs discovery tool calls

| Category | Count | % of Total |
|----------|-------|------------|
| **Productive** (Edit, Write, tests, git, curl) | 576 | 31% |
| **Context discovery** (ls, cd, grep, find, cat, Read, Glob, Grep) | 1,247 | 68% |
| **Overhead** (TodoWrite) | 11 | 1% |

**68% of all tool calls are the agent orienting itself** — finding files, reading existing code, searching for patterns and conventions. Each of these calls re-sends the full (cached) conversation, driving up cache token counts.

## Most-Read Files

The same core files are read repeatedly across different tasks:

| File | Times Read | Notes |
|------|-----------|-------|
| `workflow/transitions.py` | 47 | Read by nearly every task |
| `tests/integration/test_conditional_steps.py` | 19 | |
| `workflow/engine.py` | 18 | |
| `workflow/service.py` | 18 | |
| `workflow/condition_evaluator.py` | 17 | File being built by this run |
| `config/models.py` | 16 | |
| `api/routers/runs.py` | 16 | |
| `tests/unit/test_task_transitions.py` | 15 | |
| `ui/src/pages/RunDetail.tsx` | 15 | |

`transitions.py` being read 47 times across 21 attempts means every task reads it ~2.2 times on average. This is pure waste — the file's contents are known to the orchestrator and could be injected.

## Search Pattern Examples

Typical discovery patterns the agent performs via Bash:

```bash
# Finding files by name
find worktrees/r20 -type f -name "*.py" | grep -i condition
find worktrees/r20 -type d -name alembic

# Searching for existing patterns to follow
grep -r "skipped\|skip_reason" tests/ --include="*.py"
grep -r "step.*skipped\|StepState.*skipped" src/ --include="*.py"
grep -n "MAX_\|max_depth\|max_length" src/orchestrator/workflow/condition_evaluator.py

# Understanding project structure
ls src/orchestrator/workflow/
ls tests/unit/ | grep workflow

# Reading files via bash instead of Read tool
head -20 src/orchestrator/workflow/gates.py | grep -A 5 "from typing"
```

These searches answer questions the orchestrator already has answers to:
- Where is the relevant code? → Known from routine config and project structure.
- What patterns do existing files follow? → Could be summarized in the prompt.
- What's the directory layout? → A file tree could be pre-injected.

## Token Formula

For a given attempt:

```
cache_tokens ≈ tool_calls × avg_conversation_size_at_midpoint
```

Where `avg_conversation_size_at_midpoint` grows as the agent reads files and accumulates tool results. A task that reads 15 files and makes 100 tool calls will have a much larger cache bill than one that reads 3 files and makes 30 calls — even if the actual *productive work* (edits, test runs) is similar.

## Recommendations

### High Impact

**1. Pre-inject key files into the task prompt**

The orchestrator knows which files each task will need. Injecting their contents directly eliminates the discovery phase. For this run, including `transitions.py`, `engine.py`, `service.py`, and `config/models.py` in every task prompt would have eliminated ~100+ Read calls and the associated cache tokens.

Implementation: Extend `context_from` or add a `files` field to task config that automatically reads and injects file contents into the `ExecutionContext`.

Estimated savings: **30-40% fewer tool calls**, reducing cache tokens proportionally.

**2. Provide a project file tree**

Include a directory listing of relevant source directories so the agent doesn't need `ls` and `find` to orient itself. A single `tree` output of `src/orchestrator/` and `ui/src/` would eliminate ~248 navigation calls.

Estimated savings: **~13% fewer tool calls.**

**3. Provide pattern examples in the prompt**

Include snippets showing existing conventions (event definitions, schema patterns, router patterns, test patterns). This eliminates the "grep for examples" phase.

Estimated savings: **~10% fewer tool calls.**

### Medium Impact

**4. Delegate test runs to sub-agents**

Test execution (155 calls) produces large stdout that inflates the conversation window. Running tests in a sub-agent keeps the main context lean, reducing cache tokens for all subsequent tool calls.

**5. Set a CLAUDE.md in the worktree**

A worktree-level `CLAUDE.md` with project conventions, file locations, and patterns would be loaded automatically by Claude Code, reducing the need for discovery.

### Low Impact

**6. Deduplicate file reads across tasks**

Some mechanism to note "you already know what transitions.py looks like from a prior task" — though this conflicts with the stateless-per-attempt design. Alternatively, inject a summary of previously-modified files rather than requiring the agent to re-read them.

## Cost Context

At Haiku pricing with 99.5% cache hits, this run cost ~$9.77. The recommendations above could plausibly reduce this to ~$5-6 by cutting tool calls by 40-50%. The bigger win is **wall-clock time** — eliminating 700+ discovery calls at ~1-3 seconds each would save 15-30 minutes of the 3.46-hour run.

For runs using more expensive models (Sonnet, Opus), the same patterns would cost 5-20x more, making these optimizations significantly more impactful.
