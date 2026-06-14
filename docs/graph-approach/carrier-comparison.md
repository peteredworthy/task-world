# Carrier comparison — existing vs 3-sub-agent vs execution graph

Slice 4.3 conclusion. Compares the three ways the orchestrator gets work done, on
**completeness / correctness of implementation** vs **full cost** (input / output /
cache tokens, tool calls, estimated USD). Reproduce with
`uv run python scripts/compare_carriers.py <label=run_id> …` (metric maths is
unit-tested in `tests/unit/test_compare_carriers.py`).

## The three carriers

| Carrier | What runs | Correctness mechanism |
|---|---|---|
| **Existing (legacy single-agent)** | one builder agent on the workflow engine; completion validated by `auto_verify` scripts | scripts + agent self-report; **no independent reviewer** |
| **3-sub-agent (builder → auditor → fixer)** | builder agent + **verifier agent**, retry-with-feedback (the `graph-kernel-slice` routine) on the legacy engine | an independent LLM auditor grades against the spec; up to 3 retries |
| **Execution graph** | structural worker + verifier **nodes** driven by `GraphRunDriver`; event-sourced | the verifier is a graph node; correctness is replayable from the event log; the controller is the sole mutation path (§28) |

## Controlled experiment — full cost (identical task, `cli_subprocess` / Sonnet)

Same small task under each carrier ("create a one-function file"), **2 runs each**,
reported as per-run averages. Output tokens alone badly undercount cost — the
totals below are dominated by **cache-read** tokens (prompt-cache reads, which
scale with the number of model turns / tool calls).

| carrier | runs | completed | correct | avg input | avg output | avg cache | avg tool calls | avg cost (USD) |
|---|---|---|---|---|---|---|---|---|
| legacy-1agent | 2 | 2/2 | ✅ | 74 | 2 032 | 221 348 | 16.0 | **$0.24** |
| 3-agent | 2 | 2/2 | ✅ | 78 | 2 540 | 165 150 | 13.5 | **$0.29** |
| graph | 2 | 2/2 | ✅ | 146 | 3 072 | 715 818 | 39.0 | **$0.26** |

What the full picture shows (and what a single output-token number hid):

- **All three are equally complete and correct** on a well-specified task — each
  produced the identical, working implementation.
- **Cost lands within run-to-run noise across all three (~$0.24–0.29).** An
  earlier single-run reading suggested the auditor doubled cost; with two runs the
  gap collapses. For small tasks the carrier is **not** the dominant cost factor.
- **Cache-read tokens dominate** total volume (200k–700k) — two orders of
  magnitude above input+output. Cost tracks *turns*, and turns track *tool calls*.
- **The execution graph drives ~2.5× the tool calls** (39 vs ~15) and the most
  cache, yet lands at comparable USD because cache-read is cheap per token. The
  bare graph node prompt (title + task_context only) gives the agent less framing
  than the legacy builder prompt, so it explores more — a prompt-tuning lever, not
  an inherent carrier cost.
- The auditor's extra **output** tokens (3-agent vs legacy: 2 540 vs 2 032) are
  real but a tiny share of the bill.

Runs: legacy `aeebd6b1`,`131bf95e`; 3-agent `c8ae2eff`,`3684d00c`; graph
`841d8911`,`0fa83688`.

## Cost proxy (runner-independent)

Token capture is uneven across runners (below), so **number of agents** is the
portable structural proxy:

- legacy single-agent: **1** agent invocation per task.
- 3-sub-agent: **2** (builder + auditor), **+1 per retry**.
- execution graph: **2** node executions (worker + verifier); retries are new
  lease generations.

So the structural floor is `legacy < 3-agent ≈ graph` (one extra reviewer agent),
but at small-task scale per-turn cache overhead and agent exploration swamp that
floor in the measured USD.

## Real implementation evidence (this session)

The 3-agent pattern and the graph carrier ran the entire execution-graph slice
programme — real, non-toy work:

| carrier | runs | completed | first-pass all-A | retries needed |
|---|---|---|---|---|
| 3-sub-agent (3.3–3.8, 4.1, 4.2) | 8 | 7 recorded* | 7/7 | 0 |
| execution graph (dogfood gate) | 1 | 1 | 1 (via callbacks) | 0 |

*Slice 3.3's run record is `failed` (its builder pre-dated the codex
submission-feedback fix and died at the commit gate; work merged by hand). Every
slice from 3.4 on completed first-pass all-A, **including the 8.9k-line deletion
in 4.2**, which bounced once on a commit-gate failure and self-healed in-session.
The auditor + retry has caught real defects a single agent would have shipped
(e.g. the slice-3.1 termination-invariant bypass). This is where the review
premium pays off: large/ambiguous implementation tasks, not one-function toys.

## Architecture: one shared cost-accounting path (fixed this session)

Originally, token/cost accounting lived **only** in the legacy attempt flow
(`update_latest_attempt`), welded to the DB `attempt` model — so graph runs, which
have no attempt, recorded **zero** tokens. That is the smell the comparison
exposed: a concern both carriers need, implemented in one. It is now extracted
into two carrier-agnostic functions both paths call:

- `runners/execution/usage.py :: extract_metrics_and_usage(result)` — ExecutionResult
  → metrics + per-model usage + tool-call count. Used by `PhaseHandler` (legacy)
  and the graph usage callback.
- `db/access/mutations.py :: merge_token_usage_into_run(run, …)` — the single run-
  level sink. Legacy calls it from the attempt update; the graph dispatch path
  calls it via an injected `on_agent_usage` callback (emitter above the import
  boundary, §28-style), so `graph_runtime` stays clean while sharing the logic.

After this, graph runs report full read/write/cache/tool-call/cost (the `graph`
rows above were measured through it).

## Remaining measurement gaps (follow-ups)

1. **`codex_server` still does not persist token usage** — its session usage isn't
   threaded into an ExecutionResult action-log, so codex-built runs show 0 tokens.
   (All runner-agnostic numbers above use `cli_subprocess`.)
2. **Graph verifier grades aren't emitted as `/activity` grade events**, so graph
   runs show `all-A = 0` here despite the verifier node grading + accepting the
   worker (confirmed via `callback_accepted`). A UI/observability gap, not a
   correctness one.

## Decision (ADR): converge on the execution graph

- **Graph is the default carrier** (slice 4.1, `default_execution_mode = "graph"`).
  The decision rests on **structural correctness**, not cost: graph gives the
  3-sub-agent pattern's independent-reviewer guarantee as event-sourced,
  replayable nodes with a single mutation path — and the data shows it does so at
  cost comparable to the alternatives, not at a premium.
- **The parent/child oversight carrier is removed** (slice 4.2); its capability is
  the planner chain (3.8) + the graph decisions/appeals/review UI (3.6).
- **Legacy single-agent is retained as an explicit, frozen opt-out** — cheapest in
  *agents* for trivial/not-yet-portable routines, and it keeps the default flip
  one-line reversible (`default_execution_mode = "legacy"`).
- **Rollback**: set `default_execution_mode = "legacy"`; no code change.

Net: on cost the three carriers are comparable for small tasks (cache-dominated,
noisy); the auditor/verifier's value is *correctness on real work*, shown by the
all-A slice record. The execution graph makes that correctness mechanism
structural and replayable at no cost premium, so it becomes the carrier — with
legacy kept as a cheap, reversible escape hatch.
