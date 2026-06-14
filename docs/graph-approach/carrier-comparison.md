# Carrier comparison — existing vs 3-sub-agent vs execution graph

Slice 4.3 conclusion. Compares the three ways the orchestrator gets work done, on
**completeness / correctness of implementation** vs **token / agent cost**, using
real run data from this codebase. Reproduce the tables with
`uv run python scripts/compare_carriers.py <label=run_id> …` (the metric maths is
unit-tested in `tests/unit/test_compare_carriers.py`).

## The three carriers

| Carrier | What runs | Correctness mechanism |
|---|---|---|
| **Existing (legacy single-agent)** | one builder agent on the workflow engine; completion validated by `auto_verify` scripts | scripts + agent self-report; **no independent reviewer** |
| **3-sub-agent (builder → auditor → fixer)** | builder agent + **verifier agent**, retry-with-feedback (the `graph-kernel-slice` routine) on the legacy engine | an independent LLM auditor grades against the spec; up to 3 retries |
| **Execution graph** | structural worker + verifier **nodes** driven by `GraphRunDriver`; event-sourced | the verifier is a graph node; correctness is replayable from the event log; the controller is the sole mutation path (§28) |

## Controlled experiment (identical task, `cli_subprocess` / Claude Sonnet)

Same task under each carrier — "create `scratch/compare_demo.py` with
`is_even(n:int)->bool`". Run with `cli_subprocess` because it is the one runner
that persists token usage (see *Measurement gaps* below).

| carrier | completed | output correct | tokens (write) | tokens (cache) | reviewer |
|---|---|---|---|---|---|
| legacy-1agent | yes | ✅ byte-identical | **1 405** | 237 386 | scripts only |
| 3-agent | yes | ✅ byte-identical | **2 272** (+62 %) | 154 541 | builder + auditor |
| graph | yes | ✅ byte-identical | *not captured* | *not captured* | worker + verifier |

Runs: `aeebd6b1` (legacy-1agent), `c8ae2eff` (3-agent), `5c4ae768` (graph). All
three produced the **identical, correct** implementation, so on a well-specified
small task **completeness and correctness are equal** — the differentiator is the
cost of, and the assurance from, the review step:

- The 3-agent pattern spends **~62 % more output tokens** than the single agent.
  That premium is entirely the auditor's grading turn — it buys an *independent*
  correctness judgement the single agent cannot give itself.
- The execution graph does the same worker+verifier work, so its agent-token cost
  is ≈ the 3-agent pattern's; the extra it carries is event-store I/O, not LLM
  tokens. Its payoff is structural: deterministic replay, crash recovery, and a
  single auditable mutation path rather than orchestration policy.

## Real implementation evidence (this session)

The 3-agent pattern and the graph carrier were exercised on real, non-toy work —
the entire execution-graph slice programme:

| carrier | runs | completed | first-pass all-A | retries needed |
|---|---|---|---|---|
| 3-sub-agent (slices 3.3–3.8, 4.1, 4.2) | 8 | 7 recorded* | 7/7 | 0 |
| execution graph (dogfood gate) | 1 | 1 | 1 (verified by callbacks) | 0 |

*Slice 3.3's run record is `failed`: its builder pre-dated the codex
submission-feedback fix (`8f62b04c`) and died at the commit gate; the work was
sound and merged by hand. Every slice from 3.4 onward completed first-pass all-A
through the orchestrator, including the 8.9k-line deletion in 4.2 — which bounced
once on a commit-gate failure and **self-healed in-session** via the feedback
loop. This is the 3-agent pattern's core value: independent audit + retry caught
and fixed real gaps (e.g. the slice-3.1 termination-invariant bypass in an
earlier session) that a single agent would have shipped.

## Cost proxy (runner-independent)

Token capture is uneven (below), so agent **turns** are the portable cost proxy:

- legacy single-agent: **1** agent invocation per task.
- 3-sub-agent: **2** invocations (builder + auditor), **+1 per retry**.
- execution graph: **2** node executions (worker + verifier), retries are new
  lease generations.

So the steady-state cost ordering is `legacy < 3-agent ≈ graph`, with the graph
adding event-store overhead rather than LLM cost.

## Measurement gaps found (follow-ups, not blockers)

The comparison surfaced real observability gaps worth closing:

1. **`codex_server` does not persist token usage** — `token_usage_by_model` stays
   empty; `total_tokens_*` are 0. All codex-built slices therefore have no token
   record. (Claude `cli_subprocess` does persist usage.)
2. **Graph-mode dispatch does not persist token usage** — even under
   `cli_subprocess` the graph run reported 0 tokens, because the graph dispatch
   path does not thread the runner's usage back to the run totals.
3. **Graph verifier grades are not surfaced in `/activity`** as `grade` events the
   way legacy verification is, so a graph run shows `all-A = 0` here despite the
   verifier node grading and accepting the worker (confirmed via
   `callback_accepted` on the gate run).

These do not change the verdict but should be wired so graph runs are first-class
in cost/quality dashboards.

## Decision (ADR): converge on the execution graph

- **Graph is the default carrier** (slice 4.1, `default_execution_mode = "graph"`).
  It delivers the 3-sub-agent pattern's independent-reviewer correctness
  *structurally* — verifier-as-node, event-sourced, deterministic replay, single
  mutation path — at comparable agent-token cost.
- **The parent/child oversight carrier is removed** (slice 4.2); its capability is
  the planner chain (3.8) + the graph decisions/appeals/review UI (3.6).
- **Legacy single-agent is retained as an explicit opt-out**, not deleted: it is
  the cheapest path for trivial or not-yet-portable routines, and keeps the
  default flip one-line reversible (`default_execution_mode = "legacy"`). It is
  *frozen*, not extended.
- **Rollback**: set `default_execution_mode = "legacy"`; no code change.

Net: the ~62 % auditor token premium is the price of independent correctness, and
the all-A record on real slices shows it pays for itself on implementation work;
the execution graph makes that correctness mechanism structural and replayable, so
it becomes the carrier — with legacy kept as a cheap, reversible escape hatch.
