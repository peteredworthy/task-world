# Decision–Information Contract

JTBD explains desired progress; this contract explains what a person must know to decide safely. Use it to test every proposed screen and to prevent both under-informed actions and indiscriminate data dumping.

## Required information layers

Every consequential decision surface should answer these questions in order:

1. **Trigger — Why is this in front of me now?**
2. **State — What is true at this moment?**
3. **Cause — What evidence explains that state?**
4. **Consequence — What is blocked, at risk, or likely to happen next?**
5. **Options — What actions are available, and how do they differ?**
6. **Authority — What exactly will this action authorize or change?**
7. **Confidence — What is measured, derived, missing, stale, or uncertain?**
8. **Confirmation — Did the command land, and what changed as a result?**

These layers do not require eight panels. They require a readable order within a stable context.

## Decision inventory

| Decision | Must know before acting | Evidence and freshness | Consequence to show | Safe action design | Capability |
|---|---|---|---|---|---|
| Ignore / keep watching | Positive progress claim, last-event age, no human wait, burn pace, final-gate trend | Live scheduler, decision, event, and usage timestamps | Cost and delay if health signal is wrong | No primary action on healthy items; drill-through available | Mixed **Current/Derivable** |
| Approve a gate or patch | Question/proposal, proposer, reason, diff/affected scope, validator result, downstream path | Proposal and validator records; mark stale base | What starts, retires, or becomes reachable | Full decision modal with approve, deny, defer and explicit next state | **Current**, presentation **Derivable** |
| Answer a clarification | Exact ambiguity, why it blocks, options, free-text implications, which future work receives the answer | Clarification request and task state | Work resumed and artifact/context updated | Preserve question context; confirm recorded answer and resumed phase | **Current** |
| Retry | Failure reason, attempt history, information or condition that will differ, attempts left, expected cost | Verification, packet diff, usage | Same failure may repeat; max-attempt effect | Disable “blind retry” recommendation when no input delta exists; explain what changes | Retry **Current**; information-delta detector **Derivable** |
| Pause / resume / cancel | Current leases, queued work, data durability, what pause means, whether cancel is reversible | Lifecycle state and signal contract | In-flight/queued effect and terminal outcome | Destructive cancel in modal; command acceptance and resulting state shown | **Current** |
| Retire or supersede a strand | Node scope, descendants, alternative path, final-invariant effect, active leases, rollback path | Topology, scheduler, patch validation | Work removed/suspended and joins rewired or blocked | Expert action through validated patch with visual topology diff | Raw patch **Current**; assisted UI **Derivable** |
| Requeue failed outbox/work | Failed item, attempts, backoff reason, idempotency/safety, downstream consumer | Outbox/event state and failure record | Duplicate work risk or renewed progress | Scope and count explicit; confirmation and new queue state visible | **Current** where endpoint exists; unified action **Derivable** |
| Steer with new context | Why retry lacks information, directive text, attachments, scope, authority, correction budget, supersession | Operator-authored record plus evidence IDs; packet binding after dispatch | New knowledge enters future packets; optional corrective graph proposal | Typed directive, scoped binding, propose-by-default, validator and audit trail | **Gap** |
| Apply steering patch | Proposed topology change, directive provenance, validator result, stale-base state, old/new route to final invariant | Steering proposal, directive, patch validator | Corrective region starts; prior strand suspends/supersedes | Proper approval gate; never direct inline confirmation | **Gap** plus existing validator machinery |
| Change a routine/prompt/policy | Repeated evidence, affected cohort, source version, expected benefit, regression risk | Cross-run findings and source SHA | Future runs change; live runs do not unless separately steered | Edit at source with preview/versioning; separate live-run action | Partly **Current**, analysis **Derivable** |

## Display priority at the intervention moment

For a degraded run, the minimum viable decision bundle is:

| Priority | Information | Why it cannot be deferred |
|---|---|---|
| 1 | Constraint sentence | Establishes why the operator is here |
| 2 | Failing requirement with grade history | Distinguishes broad failure from one persistent claim |
| 3 | Verifier reason and supporting scenario | Establishes whether the failure is credible |
| 4 | Input delta between attempts | Answers whether another retry can learn anything new |
| 5 | Attempts left and approximate retry cost | Makes waiting/continuing an explicit trade-off |
| 6 | Blast radius / final-gate effect | Shows urgency and scope |
| 7 | Action choices with consequences | Converts understanding into a safe decision |
| 8 | Provenance and raw evidence links | Lets the operator challenge the summary without losing context |

Everything else is progressive detail. If an interface cannot keep priorities 1–7 in one navigable context, it is not ready for J6.

## Confidence and honesty rules

- Show timestamps or age for live health inputs.
- Label detectors and derived claims; let the user open their evidence.
- Display unpriced usage as an explicit share rather than treating it as $0.
- Avoid percentages for completion when the plan can grow. Prefer frontier, horizon, blockers, and final-invariant state.
- Distinguish observed facts (“R2 received C twice”) from inference (“another identical retry is unlikely to help”).
- State when a value is approximate, such as the expected cost of another attempt.
- Never imply that a proposed steering directive reached an agent until its prompt packet proves the binding.

## Action feedback contract

An action is not complete when a button is clicked. The UI must show:

1. command accepted or rejected;
2. validation result and reason;
3. durable event/record identity;
4. resulting lifecycle/topology/decision state;
5. next expected system activity;
6. recovery path if the action fails or races with newer state.

