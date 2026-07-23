# User Journeys

These journeys describe trigger-to-outcome behavior. Screen names are responsibilities, not fixed implementations; a candidate design may merge responsibilities if it preserves clarity and context.

## Journey A — The all-quiet sweep

**Jobs:** J1  
**Trigger:** The operator sits down or returns after a context switch.  
**Outcome:** Confidence that nothing needs attention without opening a run.  
**Target:** Under 30 seconds, zero required clicks.

| Stage | Operator question | Information required | Evidence / provenance | UI responsibility |
|---|---|---|---|---|
| Orient | Is the system alive and current? | Data freshness, connection state, last fleet update | Event stream / API freshness | State freshness is visible without competing with health |
| Scan | Does anything need me? | Explicit empty “needs you” state; ranked exceptions if not empty | Decision queue, lifecycle state, detectors | Silence becomes a positive claim, not an empty box |
| Trust | Are quiet runs actually progressing? | Named frontier work, last-event age, final-gate position, burn against cap | Scheduler/topology, events, usage | Healthy rows say what is happening; they do not expose actions |
| Leave | Can I safely look away? | No unresolved human waits, no stale heartbeat, no runaway signal | Shared health classifier | No click is the successful completion state |

**Failure modes to design against:** status colors without explanations; percent complete on a growing plan; a blank alert area that could also mean stale data; action buttons on healthy rows.

## Journey B — Answer a decision

**Jobs:** J3  
**Trigger:** A run reaches a human gate, clarification, patch approval, or escalation.  
**Outcome:** A safe, recorded answer with consequences understood; the run unblocks or deliberately remains paused.  
**Target:** Under one minute for a routine decision.

| Stage | Operator question | Information required | Evidence / provenance | UI responsibility |
|---|---|---|---|---|
| Notice | What needs my decision and how urgent is it? | Exact question, wait age, blocked work, blast radius | Pending-action/decision view | Rank first and state the constraint inline |
| Understand | Why is this being proposed? | Proposer, reason, affected nodes/files/requirements, alternatives | Proposal record, patch diff, verifier reports | Enter a focused decision state without losing run context |
| Judge | What happens for each answer? | Consequence, reversibility, risk, validation path, cost of deferral | Command contract and topology | State outcomes in plain language before controls |
| Act | What am I authorizing? | Choice, optional rationale, identity, timestamp | `record_decision` or relevant command | Use a proper modal/decision surface; never inline destructive confirmation |
| Confirm | Did the decision take effect? | Recorded event, new state, next frontier, audit entry | Event ledger and scheduler | Show command acceptance and resulting state, not only a toast |

**Recovery paths:** stale proposal → refresh and re-evaluate; validation failure → explain the violated invariant; user defers → preserve question, age, and consequence; command failure → keep decision state and make retry safe.

## Journey C — Diagnose and steer a degrading run

**Jobs:** J2, J4, J5, J6  
**Trigger:** A repeated verifier finding indicates that another retry is unlikely to add information.  
**Outcome:** The run recovers without cancel-and-restart, and the intervention is auditable.  
**Target:** Find the causal information gap before spending another attempt.

This journey is the comparison scenario for the four concept decks.

| Stage | Operator question | Information required | Evidence / provenance | UI responsibility |
|---|---|---|---|---|
| Detect | Why did this run move to the top? | Same requirement, same failing grade, consecutive attempts, attempts left, cost of another attempt, blocked successors | Verification records, attempts, usage, topology | Constraint line already contains the diagnosis |
| Locate | Where is the failure and what depends on it? | Failing node/requirement, active frontier, downstream nodes and final gate | Graph topology and scheduler | Open with failure selected; preserve fleet context in breadcrumb/synopsis |
| Compare | What changed between attempts? | Requirements × attempts, grade reasons, candidate delta, prompt/packet delta | Requirement and verification records, candidates, packet summaries | Keep comparison, evidence, and actions within one selection context |
| Explain | What did the builder know and why was the fix insufficient? | Delivered context, referenced-but-missing evidence, reproduction scenario, tool/file activity | Bound records, verifier reason, transcript, file boundary | Separate evidence from inference and display the causal gap |
| Decide | Retry, retire, patch manually, or steer? | Information delta, expected benefit, cost, scope, authority, reversibility, validation route | Decision-information contract | Make the economic and epistemic trade-off explicit |
| Specify | What new knowledge or instruction should enter the run? | Directive, attachments, evidence IDs, scope, budget, approval mode | Operator input and artifact references | Produce a durable typed directive rather than ephemeral chat |
| Validate | Is the proposed corrective graph safe? | Patch diff, validator result, stale-base status, topology effect, final-invariant path | Existing patch validator and proposal record | Proposed steering goes through the same rigor as agent patches |
| Watch | Did the intervention reach the intended work? | Directive binding, corrective frontier, budget burn, suspended/superseded strand, verification state | Prompt packet, topology, events, usage | Let the operator verify “the agent saw it” and observe recovery |
| Learn | Should this context move upstream? | Detection-to-recovery time, avoided waste, directive reuse, similar incidents | Outcome record and cross-run comparison | Turn an intervention into a candidate routine/policy improvement |

**Capability warning:** the specification and UI for typed steering are useful design targets, but `steering_directive`, `inject_directive`, and a steering planner are not current repository capabilities.

## Journey D — Audit one node deeply

**Jobs:** J5  
**Trigger:** A claim needs verification or an operator wants to understand actual agent behavior.  
**Outcome:** The node’s inputs, interaction, outputs, file effect, and cost are understood in one stable context.

| Stage | Operator question | Information required | Evidence / provenance | UI responsibility |
|---|---|---|---|---|
| Select | Which exact execution unit am I auditing? | Node, attempt, candidate/verdict record, timestamps, state | Topology, ledger, or drill-through | Any source sets one canonical selection |
| Inputs | What did the agent actually receive? | Prompt, bound records and sizes, omitted references, model/profile, policies | Prompt packet / hydration record | Show delivered context separately from referenced context |
| Activity | What did it do? | Transcript, tools, repeated calls, elapsed time, errors | Runner trace / action log | Progressive disclosure; searchable without obscuring selection |
| Outputs | What did it produce? | Records, artifacts, candidate summary, changed paths | Graph records and artifact store | Outputs link back to the causal trail |
| Boundary | What changed in the repository? | Start/end commit or file-state boundary, diffstat, affected files | Git/file-state evidence | Keep summary visible while full diff opens in a proper review surface |
| Compare | How did this attempt differ from the previous one? | Packet delta, activity delta, output delta, grades, cost | Attempts, prompts, records, usage | Diff the right units; do not force two manually synchronized views |

## Journey E — Review patterns and compare runs

**Jobs:** J7, J8  
**Trigger:** Weekly operational review or a change to routine, prompt, policy, model, or profile.  
**Outcome:** A ranked, priced list of improvement opportunities with drill-through to ground truth.

| Stage | Operator question | Information required | Evidence / provenance | UI responsibility |
|---|---|---|---|---|
| Establish coverage | Can I trust the totals? | Date/cohort, included runs, unpriced share, missing node attribution | Usage and run metadata | Put coverage caveats beside totals, not in a footnote |
| Find | What is driving waste or churn? | Pareto by node kind, retry-without-new-info, prompt pressure, repeated tools/work, verifier churn | Aggregates and named detectors | Rank findings by cost, confidence, and addressability |
| Verify | Is this pattern real? | Exact contributing nodes/runs and detector evidence | Drill-through IDs | Every number reaches its source selection |
| Compare | Did the change help? | Comparable cohort, configuration delta, outcome/time/token/patch/verdict/intervention deltas | Run and routine metadata | Explain comparison eligibility and avoid false precision |
| Act upstream | What should change? | Routine/prompt/policy source, likely effect, affected live runs | Source configuration and incident evidence | Link to the source; steering a live run remains a separate explicit action |

## Cross-journey continuity requirements

1. A selection made in fleet, ledger, map, transcript, or observatory must resolve to the same canonical object.
2. Moving between position, cause, and evidence must preserve run, selection, time/attempt, and unresolved decision.
3. Back navigation must restore the prior ranking/filter and scroll position.
4. Every derived claim must expose source evidence and freshness.
5. Every action must show scope, consequence, reversibility, authority, and confirmation state.
6. A responsive layout may re-proportion or stack surfaces, but it must not silently remove context needed for a decision.

