# Information Architecture for a New UI

The interface should reduce cognitive switching while resisting the opposite failure: bolting every feature onto one screen. The central strategy is stable context plus progressive disclosure.

## Three destination responsibilities

| Destination | Primary question | Owns | Must not become |
|---|---|---|---|
| Fleet / mission control | What needs attention now? | J1 and entry to J3/J6 | A miniature run-detail screen for every row |
| Run workspace | Where, why, what evidence, and what can I do? | J2–J6 | A collection of independent tabs that reset context |
| Observatory | What repeats across runs and did changes help? | J7–J8 | A dashboard of totals without drill-through or coverage honesty |

Map, ledger, transcript, spend, and review are lenses or focus modes within a run context. They may change the projection, but they must preserve selection, attempt/time context, and unresolved decisions.

## Shared run-health model

Every surface uses one classification and explanation. Color is secondary to a constraint sentence.

| Health state | Operational definition | Required explanation | Primary action | Capability status |
|---|---|---|---|---|
| Healthy | Frontier leased/emitting; no human wait; evidence converging; burn inside pace | Named active work, last-event age, final-gate position | None | Inputs **Current**; classifier **Derivable** |
| Needs decision | Human gate, clarification, patch approval, or escalation pending | Exact question, age, blocked scope | Review decision | Core states **Current** |
| Degraded | Same requirement/finding fails repeatedly; attempts near max; patch/rejection loop | Failing claim, grade history, attempts left, blast radius | Diagnose; retry only with an information delta; steer when available | **Derivable** |
| Stalled | Active lease but no new events beyond heartbeat threshold, or repeated outbox backoff/failure | Stall age, active lease, failed queue item, last successful event | Inspect, retire/retry, or requeue | Signals mixed **Current/Derivable** |
| Runaway | Burn exceeds budget pace or repetition/prompt-pressure detector fires | Current burn, cap/pace, unpriced share, live offender | Pause or constrained intervention | Usage **Current**; enforcement/detectors mixed |
| Steered | Operator directive active and corrective work executing | Directive scope, authority, binding, correction budget, topology change | Watch or withdraw | **Gap** |
| Settled | Final invariant resolved and run merged/cancelled/failed-terminal | Outcome, intervention count, duration, cost coverage | Post-mortem / compare | **Current/Derivable** |

## Persistent context model

The UI maintains one canonical selection:

```text
run → region/step → node/task → attempt → record/event/requirement
```

The selection state also carries:

- source location and return context;
- attempt or time range;
- active comparison target;
- pending decision, if any;
- evidence expansion state;
- data freshness and capability-status annotations.

Changing a lens must not clear these fields. Deep links should encode enough state to reopen the same diagnostic question.

## Complexity controls

### Keep together

The following belong in one stable decision context because users mentally join them:

- current constraint and blast radius;
- requirement text, grades by attempt, and grade reason;
- what the agent received and what the verifier relied on;
- cost/attempts remaining and the intervention choices;
- proposed action, scope, consequence, and validation result.

### Disclose progressively

These can start summarized and expand without replacing the context:

- raw transcript and full prompt;
- complete tool-call log;
- full file diff;
- complete topology;
- historical events outside the causal window;
- advanced patch JSON or configuration.

### Put elsewhere

These deserve separate destination responsibility:

- routine library and source editing;
- runner/profile administration;
- cross-run aggregates and cohort comparisons;
- full merge-conflict resolution and destructive repository operations.

## Avoiding repeated view switching

1. **Stable selection:** changing projection keeps the same object and attempt selected.
2. **Pinned synopsis:** run health, constraint, final-gate state, burn, and freshness survive depth changes.
3. **Evidence in place:** grade reasons, packet gaps, and activity summaries expand next to the claim they support.
4. **Actions beside evidence:** the action entry point stays in the same context; only confirmation/consequence moves into a proper modal.
5. **Re-proportion before navigate:** on wide screens, trade space between context and focus; on narrow screens, stack them with a sticky context strip.
6. **Return-state fidelity:** drills to raw evidence and returns restore filters, selection, and scroll.
7. **One vocabulary:** node, attempt, requirement, record, directive, and gate mean the same thing everywhere.

## Avoiding clutter and feature accretion

Use a four-part test before adding any persistent element:

1. Which job or decision does it serve?
2. Is it required before action, or can it be progressive detail?
3. Does it duplicate a claim already shown elsewhere?
4. Can it disappear in states where it has no decision value?

Healthy states should be deliberately quiet. Exception states may become information-dense, but density must follow a reading order: constraint → evidence → consequence → action.

## Four viable interface architectures

| Direction | Stable object | Depth mechanism | Switching avoided by | Primary risk |
|---|---|---|---|---|
| Persistent Inspector / Control Room | Selection and inspector | 60/40 split flips between canvas and inspector | Inspector survives lens changes | Inspector becomes an overgrown drawer |
| Event Spine / Case File | Causal timeline | Expand event clusters in place | Narrative contains state, evidence, and action | Topology and parallelism become harder to see |
| Exception Queue / Intervention Desk | Unresolved case | Work one case in a dedicated surface | Decision packet contains everything needed | Quiet monitoring and exploration become secondary |
| Focus + Context / Evidence Map | Focus evidence plus compact causal map | Semantic zoom and re-proportioning | Context strip stays live while evidence dominates | Visual grammar may require learning and careful responsive design |

## Responsive behavior

- Desktop: allow two simultaneous surfaces when both answer different necessary questions.
- Tablet: prefer a 40/60 or 35/65 context/focus split with compact map/timeline forms.
- Narrow screen: stack focus below a sticky synopsis/context strip; keep the selection and action state persistent.
- Modals: reserve for confirmation, destructive consequences, or structured operator input—not routine evidence browsing.
- Do not hide the evidence required to authorize an action merely because the screen is narrow; shorten summaries and provide expandable raw evidence instead.

## Implementation sequence implied by the jobs

1. Persistent selection, run synopsis, and joined inspector/causal view.
2. Attention-ranked fleet and honest health explanations.
3. Decision packets and action-result feedback.
4. Derived repeat-failure, packet-difference, stall, and budget signals.
5. Typed steering capability, first as context injection and later as planner-assisted replanning.
6. Rich topology/map lens after the workspace can already answer position and diagnosis.
7. Observatory after node attribution and price coverage are trustworthy.
