# R06 — Typed Attempt-Handoff Contract (Brief, Decisions Register, Failure Record)

**Priority: P2. Effort: medium. Completes the graph's handoff semantics.**

## Problem

The best-documented multi-agent failure modes are handoff failures:

- Vague briefs → duplicated/gapped work (Anthropic, High). Fix: every
  fresh-context worker gets objective, output format, tool guidance, explicit
  boundaries.
- Lost implicit decisions → the next attempt re-litigates settled choices
  (Cognition, Med). Fix: make decisions explicit in durable state.
- Accreted prose feedback → context poisoning; a wrong diagnosis re-injected
  forever (Breunig; and our own final-check poison incidents are the
  state-level cousin).

Repo evidence: node contracts already type inputs/outputs and prompt
hydration (`graph/contracts.py`), and the task brief largely exists. What's
missing is (a) enforcement that briefs are complete, (b) any carrier for
attempt-N decisions, (c) structured (rather than prose) prior-attempt failure
context — `docs/token-cost-improvements/02-child-result-state-handoff.md`
proposed a version of this and was never implemented.

## Proposed change

1. **Brief completeness at patch admission**: the patch validator requires
   worker nodes to carry non-empty `objective`, `boundaries` (what NOT to
   touch — complements write claims), and `output_contract` (expected
   artifacts/records). Reject at admission, the same way roles and topology
   are enforced today.
2. **Decisions register**: a new small typed output record
   (`decision_note`: chosen approach, alternatives rejected, why — hard cap
   ~1-2K tokens via R05 field budgets) that builders emit on submit.
   Hydrated into: the next attempt of the same task (repair or escalation),
   and sibling tasks in the same region when the edge opts in. Supersedable
   like any record — a corrected decision replaces, not appends.
3. **Structured failure record**: verifier verdicts and agent-death causes
   already exist as typed records; the revision prompt builds its feedback
   section *only* from these (requirement IDs, verbatim error excerpts,
   file/line pointers) — never from prior-attempt prose transcripts. This is
   the prompt-side twin of R03's distilled-feedback rule.

## Expected benefit

- Attacks the two best-documented handoff failure classes with kernel
  enforcement rather than prompt discipline — the thing this architecture is
  uniquely positioned to do.
- Escalated fresh attempts (R03) start from decisions, not from zero.

## Cost / complexity

One new record kind + contract fields + validator rules + prompt-assembly
sections. Rides existing machinery (records, hydration policies, patch
validation).

## Risks

- Builders may emit boilerplate decision notes. Accept: even boilerplate
  beats nothing; review samples during R07 evals and tune the prompt.
- More admission-time rejections initially frustrate planners; provide the
  fields in horizon templates so the default path always passes.

## Validation

- Measure attempt-N+1 re-litigation (reverting/redoing attempt-N choices) on
  frozen-suite revision tasks before/after.
- Patch-rejection rate for incomplete briefs should spike then drop to ~0 as
  templates absorb the requirement.

## Dependencies

R05 field budgets (size caps); horizon-template updates; benefits R03.
