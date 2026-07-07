# R02 — Execution-First Verification and Deterministic Completion Facts

**Priority: P1. Effort: medium. The highest-expected-value behavioral change.**

## Problem

Verification is LLM-rubric-heavy. External evidence says this is the weakest
oracle available:

- LLM judges misclassify *correct* code as non-compliant, and richer judge
  prompts make it worse (arXiv 2508.12358, High).
- 75.8% of failures among self-assessing coding agents were **false
  successes**, which LLM judges barely detect (0.54-0.65 AUROC) while cheap
  deterministic detectors reach 0.83-0.95 at 3300× speed (arXiv 2606.09863,
  High).
- Recommended fallback: execution-based checks whenever judge consistency is
  low (arXiv 2604.16790).

Repo evidence: the kernel already has first-class `check` nodes that run
in-process (`graph_runtime/dispatch.py` `_run_check`), hidden oracles, and a
design principle that "completion is a deterministic invariant over typed
records" — but requirement grading itself is a verifier-LLM rubric, and there
is no systematic split between requirements a test can check and requirements
only judgment can check. Revision-loop churn where the verifier's "fail" is
wrong is invisible (see [../open-questions.md](../open-questions.md) OQ-2).

## Proposed change

1. **Requirement oracle classification.** Add an `oracle` field to the
   requirement/verification contract: `execution | judgment | hybrid`.
   Planner prompts (and routine YAML schema) require declaring it; the patch
   validator enforces presence. This mirrors the SWE-bench Verified annotation
   rubric ("is it well-specified? can a test reject invalid solutions?") at
   graph-build time.
2. **Deterministic pre-verifier gate.** Before any verifier LLM dispatch, the
   runtime evaluates cheap environment facts and attaches them to the
   verifier packet — and *fails fast* without an LLM call when they fail:
   - declared tests were actually executed, and their exit status;
   - diff non-empty when the task claims changes;
   - changed files ⊆ declared write claims / expected artifact set.
   Natural home: `_submit_callback` capture in `graph_runtime/dispatch.py`,
   next to the existing file-state boundary — the facts become typed fields on
   the candidate record.
3. **Execution-oracle requirements route to check nodes**, not verifier
   prompts: the compiler/horizon templates emit a check node per
   execution-checkable requirement; the verifier LLM grades only the
   judgment residue, one requirement per verdict (binary, minimal prompt —
   per the bias literature, no holistic scoring, no "explain and propose
   corrections" instructions).

## Expected benefit

- Removes the dominant silent-failure mode (false success) with deterministic
  code instead of model judgment.
- Cuts verifier tokens (fewer requirements graded by LLM; failed
  deterministic gates skip the LLM entirely).
- Reduces false-fail revision churn by shrinking the LLM's grading surface.

## Cost / complexity

Schema addition (requirement contract + candidate record fields), compiler
and horizon-template changes, prompt edits. No new infrastructure. The
existing check-node machinery carries the load.

## Risks

- Planners may misclassify requirements as execution-checkable when no good
  test exists → gate stalls. Mitigate: `hybrid` mode where check failure is a
  blocker but check success still requires a (cheap) judgment pass.
- Deterministic facts can be gamed by an agent editing tests. Mitigate: the
  file-state boundary already records what changed; flag test-file edits in
  the verifier packet.

## Validation

- Standing metric from the event log: false-pass rate (task accepted, later
  reopened/superseded) and verifier-overturn rate (fail → pass with no code
  change) before vs after.
- Eval-harness comparison (R07) on frozen tasks.

## Dependencies

- Benefits from R07 (eval harness) for measurement; can land first.
- Aligns with W5 typed-payload slices (new fields ride the same migration
  pattern).
