# R03 — Evidence-Based Revision Caps and Model-Tier Escalation

**Priority: P1. Effort: small-medium. Turns retry behavior from folklore into
policy.**

## Problem

Revision loops today are bounded only by `max_attempts`, with the same model
retrying on accumulated feedback. External evidence:

- Two repair rounds capture 76-95% of achievable self-repair gains; marginal
  gain <2pp/attempt after round 2 (arXiv 2604.10508, High).
- Verbose accumulated feedback *degrades* later repairs; duplicate-fix
  attempts signal exhaustion (Med).
- For capable models repair beats resampling; escalating model tier with a
  fresh attempt beats a third repair; "almost right" cheap-model churn can
  out-cost one frontier call (Med).

Repo evidence: `docs/issues/001-validation-failure-recovery.md` documents the
current dead end — exhausted attempts mark the task failed and the run
proceeds silently. Per-run profile overrides are explicitly "not yet
implemented" (`runners/detection/profile_resolution.py:14`); the single
routing seam is `runners/executor.py:961-997`, and graph nodes carry model
profiles in their contracts.

## Proposed change

1. **Default attempt policy** (runtime policy, not prompt text):
   - Attempts 1-2: same coder-profile model, repair mode, with **distilled**
     feedback only (failed requirement IDs + minimal evidence + verbatim
     errors — not prior transcripts).
   - Attempt 3: escalate to the architect-profile model, **fresh attempt**
     (task brief + decisions register, no accumulated repair feedback).
   - After 3: stop and raise a typed blocker (`revision_exhausted`) —
     replacing the silent-failure path of issue 001 with the no-silent-
     quiescence principle.
2. **Duplicate-diff short-circuit**: if attempt N's diff is
   substantially identical to attempt N-1's (normalized diff hash), skip
   directly to escalation — the model is looping.
3. Represent the policy as data on the node contract (max_repairs,
   escalation_profile), defaulted globally, overridable per routine — keeping
   "permissions/policy are data, not prompt text".

## Expected benefit

- Cuts the long tail of wasted revision tokens (the marginal attempt is the
  most expensive and least likely to succeed).
- Converts silent task failure into an operator-visible blocker.
- First concrete use of the profile system for *dynamic* routing, through the
  existing seam.

## Cost / complexity

Small kernel change (attempt metadata already in state), one dispatch-time
policy check, diff-hash plumbing in the callback path.

## Risks

- Escalation model may be quota-constrained (subscription CLIs). Mitigate:
  escalation target is a profile, resolved per-runner; if unresolvable, the
  typed blocker fires instead.
- Diff similarity threshold too aggressive → premature escalation. Start
  with exact-normalized-hash equality only.

## Validation

- Event-log metrics: attempts-per-accepted-task distribution, tokens per
  accepted task, revision-exhausted rate, before vs after.
- R07 frozen-suite comparison.

## Dependencies

- R04 telemetry (accurate cost per attempt) to quantify the win.
- Decisions-register field from R06 improves escalated fresh attempts but is
  not required.
