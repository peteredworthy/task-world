# R07 — A Small Frozen-Task Eval Harness for the Orchestrator Itself

**Priority: P1. Effort: medium. The measurement substrate for everything else.**

## Problem

The FR acceptance suite pins *kernel invariants* superbly, but nothing
measures whether a prompt edit, profile change, or policy change makes runs
**better** — cheaper, fewer attempts, fewer false passes. The project's own
epistemics ("tests are regression evidence only; product proof required")
demand exactly this instrument, and today product proof is manual dogfooding.

External evidence: the 2025-26 consensus eval stack is three layers
(end-to-end completion, trajectory evals, component evals) with small
versioned suites regression-gated on every prompt/model change; at solo
scale, 10-20 frozen tasks beat any leaderboard (High-for-pattern). Our event
journal already *is* a trajectory record, and `graph/scenario.py` already
replays event streams purely.

## Proposed change

1. **Frozen task suite**: 10-20 seed tasks with known-good outcomes, spanning
   the routine shapes that matter (single-task minimal graph, multi-region
   feature, revision-required task, gap-analysis trigger, final-invariant
   failure). Store as fixtures (routine YAML + repo fixture + expected
   outcome descriptor) under `tests/evals/` — separate from pytest CI (they
   cost real tokens).
2. **Trajectory assertions from the event log**, not output text: verifier
   ran before acceptance; no false pass (deterministic facts from R02 agree
   with acceptance); attempt count ≤ N; cost ≤ ceiling; no
   budget/quiescence blockers; expected artifact records present.
3. **A/B runner**: run the suite against a candidate change (prompt edit,
   policy flag, model default) vs baseline; emit a one-page diff (pass rate,
   attempts, tokens/$, wall clock). Even 10 tasks × 2 arms is actionable at
   this scale.
4. **Version the suite with the prompts**: eval fixtures live in-repo and
   change via PR, per the closure discipline (named evidence, re-run on
   main).

## Expected benefit

- R02/R03/R05/R06 all become falsifiable; without this they are
  plausible-but-unverified.
- Regressions from prompt/template edits caught before they burn real runs.
- The measurement itself answers OQ-1 (verifier diversity), OQ-2 (verifier
  overcorrection), OQ-6 (planner effort tiers).

## Cost / complexity

Fixture curation is the real cost (choosing tasks with unambiguous expected
outcomes — apply the SWE-bench Verified rubric: well-specified, tests that
reject invalid solutions). Runner is thin glue over existing run-creation API
+ event readbacks. Each full-suite run costs real tokens: budget it (R04) and
run on demand, not per-commit.

## Risks

- Overfitting prompts to the frozen suite. Mitigate: rotate 2-3 tasks
  quarterly; keep 2-3 held-out tasks used only for major changes.
- Nondeterminism across runs → noisy A/Bs. Mitigate: assert on invariant
  bands (attempts ≤ 3, cost ≤ X) rather than exact equality; 2-3 repetitions
  for close calls.

## Validation

The harness validates itself: seed it with one known-good and one
deliberately broken prompt variant; the broken one must fail the suite.

## Dependencies

R04 phase 1 (accurate cost per attempt) for the cost columns; R02's
deterministic facts make its false-pass assertion much stronger.
