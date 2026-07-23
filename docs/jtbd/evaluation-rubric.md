# UI Concept Evaluation Rubric

Use this rubric to compare sketches, prototypes, and implemented surfaces. Score the same scenario and viewport for every candidate.

## Scoring scale

| Score | Meaning |
|---|---|
| 1 | The user cannot complete the task reliably or must reconstruct critical context manually |
| 2 | The task is possible but requires repeated switching, hidden assumptions, or expert product knowledge |
| 3 | The task is understandable with minor friction or one avoidable context break |
| 4 | The task is clear, evidence-backed, and efficient for the intended operator |
| 5 | The interface makes the correct next question obvious, exposes confidence, and prevents likely mistakes |

## Weighted criteria

| Criterion | Weight | What good looks like | Evidence to collect |
|---|---:|---|---|
| Attention clarity | 12 | The operator sees what needs attention and why without scanning every run | Time to identify highest-priority run; false opens |
| Position and blast radius | 10 | Active work, blockers, and final-invariant effect are understood together | Time to answer “where are we and what is blocked?” |
| Causal comprehension | 15 | The operator finds the causal moment and distinguishes fact from inference | Correct explanation of repeated failure; evidence cited |
| Decision readiness | 15 | Trigger, evidence, consequence, options, authority, and cost are visible before action | Time and confidence to choose retry vs intervention |
| Evidence access | 10 | Raw prompt/packet, transcript, records, and file boundary are reachable without losing the question | Context losses; backtracks; successful provenance checks |
| Context continuity | 12 | Selection, run synopsis, attempt/time, and pending decision survive depth changes | Number of view switches and selection resets |
| Complexity control | 10 | Dense states have a readable order; quiet states remain quiet; progressive disclosure is purposeful | Visible persistent elements; confusion/overload observations |
| Action safety and feedback | 8 | Scope, consequence, reversibility, validation, and resulting state are explicit | Misclicks; unconfirmed commands; recovery success |
| Capability honesty | 4 | Current, derived, approximate, unpriced, stale, and proposed states are distinguishable | Incorrect assumptions about what the system did or knows |
| Responsive integrity | 4 | Narrow layouts preserve decision-critical context rather than merely hiding it | Task completion at desktop and narrow widths |

**Total:** 100.

## Required scenario tasks

Test each concept with the same tasks:

1. Confirm that three healthy runs need no attention.
2. Identify why `r314` moved to the top of the fleet.
3. Locate the failing requirement and name what it blocks.
4. Explain why attempt 2 did not solve the problem.
5. Decide whether another retry has a meaningful information delta.
6. Inspect the ground-truth packet or transcript supporting that decision.
7. Specify a scoped intervention with evidence, authority, and budget.
8. Verify that the intervention reached corrective work and preserved the final invariant.
9. Find the outcome and compare it with prior runs.

## Switching and clutter measures

Track these separately from subjective preference:

| Measure | Desired direction |
|---|---|
| Destination changes before the intervention decision | Lower |
| Lens/tab changes that reset selection | Zero |
| Manual re-selection of run/node/attempt | Zero |
| Backtracks to recover lost context | Lower |
| Persistent elements with no value in the current state | Lower |
| Decision-critical facts visible or one expansion away | Higher |
| Derived claims with one-step evidence access | 100% |
| Actions whose resulting state is visibly confirmed | 100% |

The goal is not zero navigation. The goal is zero avoidable reconstruction. A deliberate drill to raw evidence is useful; bouncing between disconnected panels to remember one decision is not.

## Prototype comparison record

For each concept, record:

- viewport and device;
- scenario data version;
- participant expertise;
- task completion and time;
- score and observation for each criterion;
- moments of hesitation or incorrect inference;
- view switches, selection resets, and backtracks;
- information that was missing, duplicated, or persistently irrelevant;
- product/data capability assumed by the concept;
- recommendation: continue, combine, revise, or stop.

## Decision rule

Do not choose a concept solely from the weighted total. A candidate is not viable if it scores below 3 on decision readiness, evidence access, action safety, or capability honesty, even if its visual appeal or fleet scan score is high.
