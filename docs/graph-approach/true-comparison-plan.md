# True Comparison Plan — Dynamic Feature Implementation

## Purpose

The first carrier comparison answered a narrower question: can the execution
graph run fixed work at comparable cost while preserving independent
verification? Yes. It did not answer the original graph question:

> Does a dynamic execution graph produce better feature implementations than a
> fixed routine or a 3-agent fixed plan when discovery changes the shape of the
> work?

This document defines the comparison needed to answer that question.

Operational work required before that comparison is tracked in
`dynamic-graph-operational-plan.md`.

## What The First Comparison Missed

The graph arm in `carrier-comparison.md` exercised a static worker/verifier
path. It did not require the graph to:

- start from an under-specified feature intent;
- discover a requirement or validation gap during execution;
- have a real planner agent emit `submit_patch` graph patches;
- create future worker/verifier/check nodes from those patches;
- mark downstream plan regions suspect after semantic changes;
- run a gap planner after local verifier success;
- append corrective work that was not in the original plan;
- block final completion on stale evidence, suspect regions, or open proposals.

Without those behaviors, the graph arm is mostly a different execution carrier
for the same fixed plan. That is useful, but it is not a dynamic-graph
comparison.

## Comparison Arms

Run the same feature scenario across five arms:

| Arm | Carrier | Planning behavior | Expected capability |
|---|---|---|---|
| A | Legacy single-agent | One builder prompt plus configured checks | Cheapest fixed-plan baseline |
| B | 3-agent fixed routine | Builder, auditor, fixer over an up-front plan | Independent review of fixed work |
| C | Mind-the-gap skill | Repeated planner/gap-finder, builder, validator chunks with durable state | Adaptive chunking outside the graph |
| D | Static graph carrier | Routine compiled to graph worker/verifier/check nodes | Event-sourced fixed work |
| E | Dynamic graph | Planner emits graph patches; gap planner can append work | Adaptive plan and invariant-driven completion |

Arm D is intentionally retained. It separates "graph as reliable carrier" from
"graph as dynamic planner." Arm C must follow `mind-the-gap-skill.md`; otherwise
the comparison only tests an ad hoc chunk loop, not the intended non-graph
adaptive strategy.

## Mind-the-gap Arm Requirements

Arm C is the non-graph adaptive baseline. It must implement the Mind the Gap
skill faithfully:

- establish and record the test baseline before the first chunk;
- have the planner/gap-finder compare the full target against compact verified
  state before selecting the next chunk;
- give builders edit access only for the assigned chunk;
- use fresh, independent validators for each chunk;
- require all relevant tests to pass before a chunk is marked valid;
- require validators to protect previously verified behavior and cross-feature
  interactions, not just the local chunk;
- have the orchestrator review validation evidence before updating durable state;
- record verified behavior, validation evidence, decisions, risks, and remaining
  gaps in compact durable state;
- escalate after repeated validation failure or conflicting requirements.

The previous big-task Arm C run used fresh builder/validator agents and chunked
work, but it allowed validators to be too local and recorded too little evidence.
That result is useful evidence about a weak implementation of the skill, not a
conclusive result against the skill itself.

## Scenario Requirements

Use a real but small repo feature that forces adaptive behavior. The scenario
must include:

1. An initially ambiguous must requirement.
2. A discovery step that makes that requirement concrete.
3. A validation definition that is initially too weak.
4. A local verifier pass that is still globally insufficient.
5. Corrective work that must be appended after the original plan.
6. A final acceptance check that fails if stale evidence or open proposals remain.

The dry-run model in `dynamic_intent_graph_feature_dry_run.md` is the template:
ambiguous `R2`, validation requirement `R4`, a gap-planner finding after local
verification, and appended corrective work.

## Scenario Admission Gate

Do not launch A/C/E arms until the candidate scenario passes this gate:

1. A one-shot single-agent baseline on the same starting snapshot fails the
   hidden oracle materially, while still producing useful partial work.
2. The failure is caused by missed discovery, weak local validation, or missing
   corrective work, not by tool outage, quota, dependency setup, or an oracle
   that encodes a preferred implementation seam.
3. The deterministic harness can run the weak acceptance and hidden oracle
   outside all agents.
4. All known dynamic-graph smoke invariants from DG-5.1x/DG-5.2x are covered by
   local harness checks before Arm E spends live model tokens.
5. The scenario has enough coupled surface area that a single prompt is unlikely
   to hold all relevant state: at least 5-8 active requirements, repo-state
   discovery, cross-feature interactions, and at least one required
   post-validation correction.

S1 dynamic smoke is operational evidence only. S2 live agent-output streaming is
also rejected as a comparison scenario because the single-agent arm completed it
correctly in one pass.

## Fairness Controls

- Same repository snapshot for every arm.
- Same model family and runner where possible.
- Same wall-clock and token budget.
- Same hidden acceptance tests, run outside all agents.
- Same allowed tools, except graph-only tools required for patch submission in
  Arm E.
- Same final human scoring rubric, blind to carrier.
- Each arm gets one initial attempt and the same retry budget.
- Record every model turn, tool call, token usage, file-state boundary, and final
  diff.

## Metrics

Primary outcome metrics:

- hidden acceptance pass/fail;
- number of active requirements satisfied;
- number of stale or invalid evidence links used in final acceptance;
- whether corrective work was appended when required;
- whether final completion was blocked until all proposals were decided;
- human review score for maintainability and scope control.

Secondary cost/process metrics:

- total input/output/cache/reasoning tokens;
- cost by runner/model;
- agent invocations and tool calls;
- planner patches accepted/rejected;
- count of appended/superseded/suspect regions;
- retries and verifier failures;
- elapsed time.

## Missing Implementation For Arm E

The kernel has many primitives for dynamic planning, but a true production
dynamic-feature arm still needs these pieces:

1. **Planner-agent patch submission path.**
   Planner nodes can exist and the controller can accept `submit_patch`, but the
   production dispatch prompt currently treats a generic planner like a normal
   builder, and generic planner submit produces no patch record. A real planner
   must receive a graph packet and submit structured patch operations through a
   fenced tool/API path.

2. **Dynamic feature routine.**
   There is no production routine whose main path is "plan the next horizon,
   implement it, verify it, run gap analysis, then decide whether to append
   more graph." Add a routine dedicated to Arm E instead of reusing the static
   graph carrier.

3. **Gap planner / invariant gate.**
   The dry run identified the key failure mode: local verification can pass
   against weak explicit requirements. Arm E needs a mandatory gap-planner pass
   after discovery or semantic requirement change, plus a pre-final invariant
   gate that blocks on stale evidence, suspect regions, blocked must
   requirements, and open proposals.

4. **Requirement and evidence revision records.**
   Dynamic comparison needs first-class records for requirement versions,
   validation-strengthening proposals, support-edge freshness, suspect regions,
   and superseded evidence. Some low-level record mechanics exist, but the
   feature-level policy is not yet wired as a production workflow.

5. **Planner prompt/context packet.**
   The graph node prompt is currently minimal. A planner needs a compact packet
   containing active intent, requirement versions, accepted evidence, open
   proposals, current graph frontier, available patch ops, budget, and examples
   of valid patch shapes.

6. **Observability and scoring.**
   The comparison script must ingest graph-specific dynamic facts: patch counts,
   rejected reasons, appended work, suspect/superseded regions, proposal
   decisions, invariant-gate failures, and graph verifier grades in `/activity`.

7. **Safety and authority policy.**
   Validation strengthening can be auto-accepted when it proves an already-active
   must requirement. New behavior requirements need explicit authority. This
   distinction must be encoded before comparing dynamic planning quality.

## Done When The Comparison Is Valid

The comparison is valid only when Arm E completes a feature run where at least
one planner-generated patch creates future work, at least one semantic discovery
or gap-planner event changes the future graph, and final completion depends on
the graph invariant gate rather than the original routine sequence ending.

Until then, comparisons should be described as **carrier comparisons**, not
dynamic-graph comparisons.
