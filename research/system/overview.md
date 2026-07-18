# Current System Understanding — Synthesis

> As of 2026-07-07, HEAD `23746c228`. This page is the orientation read;
> details in [graph-kernel](graph-kernel.md),
> [runtime-runners-cost](runtime-runners-cost.md),
> [design-history](design-history.md).

## What the system is

A self-hosted orchestrator (Python/FastAPI/SQLite + React UI) that coordinates
LLM coding agents (Claude/Codex CLI, Codex Server, OpenHands) through a **typed,
event-sourced, dynamically growing work graph**. Each run executes in an
isolated git worktree. Tasks flow builder → verifier with fresh LLM context
per phase; planners grow the graph at runtime via validated patches; a
deterministic final gate (typed blockers, invariant checks) decides
completion. The graph carrier is the default; the older Routine/Run workflow
engine still hosts the drive loop and legacy paths.

## What is intentional

The core design philosophy is explicit, consistent across docs, and mostly
implemented in the graph stack:

- Event log as sole truth; projections disposable; pure reducers; injected
  clock/IDs (kernel purity).
- Controller as the only graph writer; agents propose, controller
  accepts/rejects; permissions as data, not prompt text.
- Completion as a deterministic invariant over typed records; no silent
  quiescence.
- Fresh context per phase; single writer per worktree; supersede-never-edit.
- Validation standard: product-path proof over green tests.

External evidence (2025-26) independently converged on almost every one of
these choices — see [../external/orchestration-topologies.md](../external/orchestration-topologies.md).
**The architecture does not need reinvention.** The gaps are in policy,
telemetry, and unfinished consolidation, not in the core model.

## What is accidental / fragile

1. **Two architectures coexist.** The legacy workflow engine retains
   multi-source-of-truth state (`SessionStateManager` snapshots, mutable run
   rows, `oversight_state` blob) that the event-driven migration never
   finished; the graph drive loop lives inside the legacy module and
   duplicates runtime helpers deliberately.
2. **Ledger/doc staleness cuts both ways**: W7 (glob-overlap safety fix) is
   merged but its spec/status docs still read as open; W8 is partially done;
   W5 typed payloads only one slice in. The incident doc's "open kernel gap"
   on cross-region supersession also appears fixed but unproven against the
   full incident topology.
3. **Verification is LLM-heavy**: per-requirement rubric grading by a model,
   with check nodes available but no systematic execution-first policy; the
   final-gate poison class of incidents came from identity-pinned gating and
   its closure is not yet pinned by an incident-replay regression.
4. **Cost telemetry has holes**: claude_sdk undercounts (no action log);
   unmatched models cost $0 in rollups (the UI shows "cost unknown", but
   aggregates treat it as free — and the SDK default model is unmatched);
   no finish_reason/reasoning-token capture; no cross-run rollup surface.
5. **Prompt sources triplicated** (hardcoded workflow strings, hardcoded SDK
   builder, DB agent_configs) with no drift guard.
6. **No policy layer for retries/escalation/budgets**: max_attempts exists,
   but no evidence-based cap, no model-tier escalation, no per-run/node cost
   budgets enforced at dispatch.
7. **No orchestrator-level eval harness**: FR acceptance tests pin kernel
   invariants, but nothing measures whether prompt/profile changes make runs
   better or worse.

## Strength/weakness at a glance

| Layer | Verdict |
|---|---|
| Pure kernel (commands/reducers/scheduler/validator) | Strong, well-tested, do not disturb |
| Controller/outbox/recovery | Strong post-W2/W3/W6 |
| Drive loop | Works, but accreted; W8 target |
| Prompt assembly | Capped but untested; not cache-aware; hydration policies good bones |
| Verification | Right topology, wrong default oracle mix |
| Runners | Four selectable types; Codex Server replaces removed Claude SDK runner |
| Cost/observability | Good substrate (rate-embedded usage records), holed capture |
| Legacy workflow engine | Live liability; shrink, don't extend |
| UI/API readbacks | Rich, rebuildable read models |

## The one-paragraph thesis

This project already has what most 2026 agent frameworks are converging
toward: durable event-sourced graph state, a deterministic controller,
single-writer discipline, and clean-context verification. The highest-value
next work is not new topology — it is (a) closing the small set of known
safety/consistency gaps, (b) making verification execution-first with
deterministic completion facts, (c) adding the policy layer the dry-run
modeling already identified as missing (retry/escalation/budget routing), and
(d) instrumenting cost/outcomes well enough that future changes can be judged
by evidence. See [../recommendations/README.md](../recommendations/README.md).

## Runner disposition update — 2026-07-18

The Claude SDK telemetry and prompt observations above are retained as the
historical rationale for removal. Current selection is limited to
`openhands_local`, `openhands_docker`, `cli_subprocess`, and `codex_server`.
Historical SDK records normalize to `retired` for readback only and cannot be
selected, discovered, or dispatched.
