# Big-task carrier comparison — experiment design

Follow-on to `carrier-comparison.md`, which compared carriers on a *one-function* task and
found cost dominated by per-turn cache noise. That experiment's own conclusion: the
review/planning premium "pays off on large/ambiguous implementation tasks, not one-function
toys." This experiment supplies that larger task and compares three **orchestration
strategies** head-to-head.

## The three arms (strategies)

| Arm | Strategy | Defining trait |
|---|---|---|
| **A — Graph** | task-world execution-graph carrier (the real thing in `docs/graph-approach`): recursive-horizon planning, worker/verifier nodes, event-sourced, single mutation path | adaptive plan granularity + structural independent verification |
| **B — Idea-to-plan** | front-load a complete plan, then execute the whole plan, then verify | all planning weight up front; minimal mid-course replanning |
| **C — Mind-the-gap** | repeated planner/gap-finder → builder → validator cycles, orchestrator holds durable state | small independently-verified chunks, fresh builder/validator per chunk |

Arm C is intended to follow the `mind-the-gap` skill, captured in
`../mind-the-gap-skill.md`. The important parts are not just "many small
chunks": baseline first, relevant tests passing for every validated chunk,
fresh builder and validator agents, orchestrator review of validation evidence,
and compact durable state containing verified behavior, evidence, decisions,
risks, and remaining gaps.

## Controlled variables (held constant)

- **Target feature**: `spec.md` (Versioning + Trash + Search for desktop-test). Beyond
  one-shot: ~12 endpoints, on-disk metadata store, retention/collision/binary edge cases.
- **Worker model**: `gpt-5.3-codex-spark` (codex) for every implementation/verification
  agent in every arm. (User has codex headroom; conserves the limited Claude budget the
  Opus orchestrator runs on.)
- **Orchestrator**: Claude Opus (this session) for all arms.
- **Starting code**: a fresh copy of `desktop-test` per arm (`comparison-arms/arm-*`).
- **Grading oracle**: the hidden 56-test acceptance suite in `acceptance/`, run by the
  orchestrator after each arm. Arms get `spec.md` only, never the suite.

## What is measured

| Dimension | Metric |
|---|---|
| Effectiveness / correctness | hidden acceptance suite pass rate (×/32) |
| Completeness | endpoints implemented; app imports & starts |
| Efficiency | wall-clock; # agent invocations; # iterations/retries; LOC changed |
| Cost | codex tokens (input/cached/output/reasoning) from `--json` `turn.completed.usage`; USD via `pricing` in driver |
| Quality | independent Opus code review (structure, safety, dead-ends) |

## Measurement mechanics

- Arms B & C run via `codex exec --json -m gpt-5.3-codex-spark -C <armdir>`; each call's
  JSONL is captured and token usage summed into `metrics/<arm>.json`.
- Arm A runs through task-world (real graph carrier). Known gap (`carrier-comparison.md`):
  `codex_server` does **not** persist token usage, so Arm A token counts come from the
  codex account-usage delta + the runner-independent proxy (node/agent invocations, tool
  calls, wall time). This asymmetry is reported, not hidden.

## Caveats (honest accounting)

1. **Level mismatch**: Arm A is a productionized carrier inside task-world; B and C are
   orchestrator-driven loops. The comparison is strategy-vs-strategy on identical
   target/model/oracle, not implementation-vs-implementation. Noted in the writeup.
2. **n=1 per arm** for a large task (budget/time). Treat deltas as directional, not
   statistically significant — same posture as the small-task study.
3. **Token capture asymmetry** for Arm A (above).
4. Codex non-determinism: a re-run would differ. The acceptance oracle is deterministic.
5. **Mind-the-gap fidelity matters**: an Arm C run that only narrows chunks but lets validators
   check each chunk locally is not a faithful skill run. Validators must also protect all
   previously verified behavior and cross-feature interactions, and the orchestrator must record
   reviewed evidence before the next planner pass.

## Resumability

`state.json` is the checkpoint (phase, per-arm status, run ids). `results.md` is the live
log. Per-arm transcripts in `metrics/`. If the orchestrator session is interrupted, a new
session resumes from `state.json`. Deliverable: `presentation.html`.
