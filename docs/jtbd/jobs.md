# Jobs to Be Done

The jobs use the form “When … I want … so that …” and add the fields needed to judge a UI: trigger, success signal, urgency, information demand, current pain, and likely home surface.

## J1 — Triage the fleet

**When** I return to several long-running jobs, **I want** a ranked account of which runs need me, which are progressing, and which are quietly stuck, **so that** nothing waits on me unnoticed and I spend attention only where it changes an outcome.

| Dimension | Definition |
|---|---|
| Trigger | Starting work, returning from a context switch, or receiving an alert |
| Frequency / target | Many times per day; confident sweep in under 30 seconds |
| Success signal | The operator can state why every visible run is healthy or needs attention without opening each run |
| Must know | Health class, current constraint, human wait state, frontier activity, last-event age, budget pace, blast radius |
| Current pain | Run cards require manual scanning; quiet and stuck can look alike |
| Likely home | Fleet / mission control |
| Capability status | Core run state is **Current**; attention ranking and several health detectors are **Derivable** |

## J2 — Understand current position

**When** I open one run, **I want** to see what is executing, what is blocked and on what, and how far the final invariant is on a plan that grows while it runs, **so that** I can judge pace and health without reading raw events.

| Dimension | Definition |
|---|---|
| Trigger | Opening an active, paused, failed, or recently settled run |
| Frequency / target | Every run visit; answer “where are we?” in under 15 seconds |
| Success signal | Current frontier, blockers, downstream effect, and final-gate state are visible together |
| Must know | Active nodes/steps, dependency path, planner horizon, blocked reason, attempts left, final-invariant progress |
| Current pain | Step rows and panels expose fragments; dynamic graph growth weakens fixed-percent progress |
| Likely home | Workspace, usually map or compact causal view |
| Capability status | Topology and scheduler views are **Current**; a diagnostic projection is **Derivable** |

## J3 — Make a safe decision

**When** a run asks for a human gate, patch approval, clarification, or escalation, **I want** the question, consequence, provenance, and supporting evidence together, **so that** I can answer safely in under a minute.

| Dimension | Definition |
|---|---|
| Trigger | Pending human action or escalation |
| Frequency / target | A few times per day; safe response in under one minute |
| Success signal | The operator knows what will happen for approve, deny, defer, or alternate input before committing |
| Must know | Exact question, why now, proposer, affected scope, evidence, alternatives, downstream effect, reversibility |
| Current pain | Decision and clarification components exist, but context is distributed and graph decision flows are not unified in one operator path |
| Likely home | Fleet call-to-action into a decision-focused workspace state |
| Capability status | Human gates, clarifications, and decision recording are **Current**; unified evidence packets are **Derivable** |

## J4 — Find the causal moment

**When** a run fails, stalls, or takes a surprising shape, **I want** verdicts, reasons, patches, rejections, retries, and lifecycle changes joined in order, **so that** I can find the causal moment without mentally joining multiple panels.

| Dimension | Definition |
|---|---|
| Trigger | Degraded health, terminal failure, unexpected cost, or operator suspicion |
| Frequency / target | Per incident; identify the causal branch in under five minutes |
| Success signal | The operator can explain what changed, why the system reacted, and which evidence supports that explanation |
| Must know | Ordered events, attempt lineage, requirement-grade changes, patch provenance, state transitions, retries and rejections |
| Current pain | Activity, grade, graph, logs, and review surfaces require manual joins |
| Likely home | Workspace ledger / causal timeline |
| Capability status | Events and records are **Current**; a joined causal narrative is **Derivable** |

## J5 — Verify the story against ground truth

**When** a causal trail points to a node or record, **I want** the actual prompt packet, transcript, tool calls, produced records, file-state boundary, and cost, **so that** I can verify the explanation rather than trust a summary.

| Dimension | Definition |
|---|---|
| Trigger | A disputed claim, surprising agent behavior, repeated failure, or audit |
| Frequency / target | Per diagnosis; evidence accessible in one selection context |
| Success signal | The operator can distinguish what the agent saw, did, produced, and changed |
| Must know | Bound input records, omitted/referenced context, prompt size, transcript, tools, artifacts, file delta, output records, usage |
| Current pain | Evidence exists across trace, logs, file, graph-record, and review surfaces |
| Likely home | Workspace transcript/evidence lens with persistent selection |
| Capability status | Most raw evidence is **Current**; packet comparison and repeat-tool flags are **Derivable** |

## J6 — Put a run back on track

**When** I understand what is wrong, **I want** to approve or deny, retry with changed conditions, retire or requeue work, or provide new instruction and context for replanning, **so that** a long run does not become a cancel-and-restart.

| Dimension | Definition |
|---|---|
| Trigger | A diagnosis with a clear intervention or an operator-owned piece of missing knowledge |
| Frequency / target | Per incident; action available in the evidence context |
| Success signal | The intervention is scoped, consequence-aware, validated, auditable, and observable through recovery |
| Must know | Current failure, information delta, alternatives, expected effect, scope, authority, budget, reversibility, validation path |
| Current pain | Existing actions are split across UI and expert API commands; new information cannot be injected as a typed graph input |
| Likely home | Workspace action rail / decision surface |
| Capability status | Gate decisions, lifecycle signals, retry/requeue, and raw graph patches are **Current**; typed steering and planner-assisted replanning are a **Gap** |

## J7 — Discover cross-run patterns

**When** I review spend or tune prompts and policies, **I want** cross-run aggregates and detectors for token drivers, repeated work, prompt pressure, and verifier churn, **so that** I can find waste and judge changes by evidence rather than anecdote.

| Dimension | Definition |
|---|---|
| Trigger | Weekly operations review, cost anomaly, or policy/prompt tuning |
| Frequency / target | Weekly; produce a ranked list of evidence-backed opportunities |
| Success signal | Every aggregate drills to the exact runs/nodes behind it and states unpriced or missing coverage |
| Must know | Spend/tokens by node kind, unpriced share, prompt size, retries without new information, repeated tools/work, verifier churn |
| Current pain | Per-run usage exists, but cross-run attribution and detectors are incomplete |
| Likely home | Observatory |
| Capability status | Usage events and some summary fields are **Current**; producer wiring, honest rollups, and detectors are **Derivable** or a **Gap** by metric |

## J8 — Compare a run with its predecessors

**When** a routine has run many times, **I want** this run compared with comparable predecessors, **so that** regressions from prompt, policy, routine, or model-profile changes surface before they become expensive.

| Dimension | Definition |
|---|---|
| Trigger | Routine change, model/profile change, post-mortem, or performance regression |
| Frequency / target | Per meaningful change; comparison in one review session |
| Success signal | The operator can see outcome deltas and drill through to explain them |
| Must know | Comparable cohort, routine SHA, model/profile, duration, tokens, price coverage, patch count, retries, grade churn, interventions, outcome |
| Current pain | Run histories exist without a purpose-built comparable-cohort view |
| Likely home | Observatory / run postscript |
| Capability status | Run metadata is **Current**; cohort definition and comparison projection are **Derivable** |

## Coverage check

The eight jobs form one operating loop:

`J1 notice → J2 position → J3 decide / J4 explain → J5 verify → J6 act → J7 learn → J8 compare`

The loop is intentionally not a navigation model. A good UI may support several adjacent jobs in one stable surface when their information overlaps.

