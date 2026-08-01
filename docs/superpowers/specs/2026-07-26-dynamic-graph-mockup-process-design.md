# Dynamic Graph Mockup Process Design

## Objective

Produce one implementation-grounded, clickable concept deck for the full
operator loop around a dynamic graph. The concept may include proposed typed
steering, but must distinguish proposed behavior from current and derived
behavior.

This process replaces the deleted semantic-catalog pipeline. It preserves the
useful source audits and recorded decisions while making reviewable screens the
primary measure of progress.

## Review Of The Previous Process

The previous Phase 0-3 process produced useful implementation research, but its
failure to produce useful mockups was structural:

- The approved design excluded view contracts, interaction architectures,
  prototypes, and screens.
- The implementation plan optimized for schemas, catalogs, stable IDs,
  validators, generated projections, and feedback import rather than operator
  comprehension or design learning.
- Human and visual feedback followed exhaustive research and normalization.
- Canonicalization created a second semantic system with its own defects,
  including invented states, conflated command outputs, and incorrect
  cross-references.
- Uncertainty was treated as a global prerequisite even when it had no effect on
  a concrete screen.

The retained useful foundation is:

- `research/ui-foundation/agent-reports/01` through `11`;
- `research/ui-foundation/DECISIONS.md`;
- the jobs, journeys, decision-information contract, information architecture,
  and evaluation rubric under `docs/jtbd/`;
- direct source and test citations when a visible screen claim needs fresh
  confirmation.

The deleted catalog, schema, validator, projection, and feedback-import
machinery must not be rebuilt.

## Scope

### Included

1. One versioned scenario covering the full operator loop.
2. One coherent interface concept represented by a clickable static HTML deck.
3. Current, derived, and proposed information in the same concept with honest
   visual distinctions.
4. Desktop and narrow responsive states.
5. Task-based evaluation using the existing JTBD rubric.
6. One focused implementation-reality challenge after the first deck exists.

### Excluded

1. A comprehensive semantic model of the orchestrator.
2. Machine-readable capability catalogs or stable research IDs.
3. Custom validators, generators, source snapshots, or feedback importers.
4. Exhaustive design of every graph state, command, or operator journey.
5. Backend or production UI implementation.
6. Treating proposed steering or cross-run analysis as current capability.

## Working Principle

Research just enough to make one visible screen claim honest. Review the screen,
then let observed design needs pull further research.

Every iteration must change a reviewable screen or stop. A research question is
out of scope when either answer would leave the concept unchanged.

## Process

### 1. Freeze The Scenario

Create a concise scenario sheet for one degrading run, `r314`, within a fleet of
four graph runs. It records:

- operator questions and expected answers at each stage;
- realistic identities, graph structure, states, records, events, and usage;
- whether each nontrivial claim is current, derived, or proposed;
- direct citations to the retained reports or decisive source;
- known missing, stale, partial, and unpriced conditions.

The scenario is a design fixture, not a generalized domain model.

### 2. Build The Graybox Immediately

Build all seven linked states at low fidelity before polishing any one screen.
The first useful review artifact is the clickable flow, not additional research
documentation.

### 3. Review The Operator Flow

Walk through the scenario using the rubric tasks. Record:

- wrong or unsupported inferences;
- missing decision information;
- destination changes, selection resets, and backtracks;
- persistent elements that do not help the current decision;
- ambiguity between current, derived, and proposed behavior;
- action outcomes that are accepted but not visibly applied.

### 4. Pull Targeted Research

Begin with `DECISIONS.md` and reports 01-11. Reopen implementation or tests only
for a specific displayed field, state, relationship, transition, or action that
remains ambiguous. Record the answer directly in the scenario note and update
the affected screen.

No research artifact is created unless the deck directly consumes it.

### 5. Run One Focused Reality Challenge

A second reader challenges only claims that could materially alter the deck:

- wrong identity or selection scope;
- invented fields, states, relationships, or actions;
- optimistic success before projection confirmation;
- unsupported causal language;
- current/future capability leakage;
- misleading authority, freshness, cost, or coverage claims.

The challenge edits the scenario or deck findings directly. It does not create a
parallel canonical model.

### 6. Refine Once And Evaluate

Apply the focused findings, complete one refinement pass, and score the concept.
The result is an explicit continue, revise, combine, or stop recommendation.

## Scenario Data

### Fleet

Use four graph runs, `r311` through `r314`. For each run include status, current
frontier, last event time, pending human action, active lease, final-gate state,
recorded usage, and pricing coverage.

The three quiet runs make positive observed claims such as named active work and
recent events. They are not labeled healthy by a fictitious current classifier.

### Run `r314`

Use six to eight graph nodes representing:

- worker attempt 1 and its candidate;
- verifier attempt 1 and its failed report;
- worker attempt 2 and its candidate;
- verifier attempt 2 and its failed report;
- a human gate or corrective planning point;
- the final gate blocked by the unresolved requirement.

Include directed edges, required bindings, scheduler buckets, node states,
leases, one repeated requirement, two verification reasons, candidate records,
file-state boundaries, prompt-summary metadata, a compact ordered event window,
and two usage facts with at least one unpriced item.

Include one currently executable decision and one separately labeled proposed
typed-steering path.

## Concept Deck

### 1. Fleet

Support a confident all-quiet sweep and make `r314` prominent through explicit
observed conditions. Preserve ranking, filtering, and return context when the
operator enters the run.

### 2. Graph Workspace

Show frontier, blockers, dynamic expansion, required bindings, downstream
topology, and final-gate state together. Selection is one `node_id` scoped to the
run. Graph nodes and legacy tasks are not presented as interchangeable.

### 3. Failure Comparison

Compare the repeated requirement, verifier reasons, candidate evidence,
file-state boundaries, and scoped cost across two attempts. Raw differences are
current evidence; retry information value is not presented as a current
detector.

### 4. Node Audit

Keep the selected node and decision question stable while exposing bound
records, outputs, available prompt summary, trace evidence, file-state boundary,
and usage. Missing exact prompts, incomplete traces, and non-causal file-state
evidence remain visible limitations.

### 5. Intervention Decision

Present current gate, patch, retry, or lifecycle actions with trigger, scope,
evidence, consequence, validation, reversibility, and provenance. Attribution
labels do not imply authenticated identity. Destructive or consequential actions
use a proper modal.

### 6. Proposed Steering

Explore typed instruction and context injection as a proposed capability. The
concept may show intended scope, evidence binding, budget, validation, and
delivery proof, but it must not appear executable in the current product.

### 7. Recovery And Postscript

Show command acceptance as `accepted, applying...` until the projection confirms
the resulting graph state. Continue through corrective work and a lightweight
postscript or comparison view. Unsupported cohort analysis remains proposed.

## Continuity And Responsive Behavior

Across every state preserve:

- run identity and synopsis;
- selected node and evidence object;
- attempt or time context;
- unresolved decision or action state;
- freshness and capability honesty;
- source location and return context.

Desktop may show context and focus side by side. Narrow layouts stack them below
a sticky context strip. Responsive behavior must not remove information needed
to authorize an action.

Raw prompts, transcripts, tool activity, diffs, and full topology use
progressive disclosure rather than separate context-resetting destinations.

## Action And Error States

The deck includes representative variants for:

- accepted but not yet applied;
- projection-confirmed success;
- stale proposal or stale graph base;
- validation rejection with reason;
- unavailable or partial evidence;
- unpriced usage;
- disconnected event stream, where `Live` means connection only;
- action unavailable in the current state, including cancel while stopping.

## Deliverables

Create only:

- `research/ui-foundation/mockups/operator-loop-scenario.md`;
- `research/ui-foundation/mockups/operator-loop-concept.html`;
- `research/ui-foundation/mockups/operator-loop-review.md`.

The HTML is offline, opens through `file://`, embeds its scenario data, and has
no build or network dependency.

## Evaluation

### Current-Grounded Track

Use rubric tasks 1-6 to test quiet-fleet confidence, attention, graph position,
repeated-failure explanation, retry judgment from available evidence, and
ground-truth inspection.

### Future-Concept Track

Use tasks 7-9 to explore proposed steering, proof that an intervention reached
corrective work, and cross-run comparison. These tasks measure coherence and
desirability, not current implementation readiness.

### Hard Rejection Conditions

Reject or substantially revise the concept when:

- decision readiness, evidence access, action safety, or capability honesty
  scores below 3;
- a proposed or derived capability can be mistaken for a current fact or action;
- changing lenses loses selection, attempt/time, pending action, or return
  context;
- action feedback stops at click or HTTP acceptance;
- the narrow layout hides decision-critical information.

## Verification

Verification is proportional to a concept artifact:

1. Open the HTML through `file://` with no network access.
2. Exercise all links, disclosures, and action-result variants.
3. Inspect representative desktop and narrow viewports.
4. Complete the rubric walkthrough and record observations.
5. Confirm every visible nontrivial claim is cited in the scenario sheet or
   clearly labeled derived or proposed.

Automated browser tests are optional if interaction complexity makes regression
risk material. They are not a prerequisite for design learning.

## Stop Conditions

Stop research when:

- either possible answer would leave the deck unchanged;
- uncertainty can be omitted or honestly labeled;
- resolution requires unrelated backend or future-product design;
- one research pass does not change a screen.

Stop expanding artifacts when a proposed file is not directly consumed by the
concept or its evaluation.

Stop refining after one focused challenge and one response pass. Evaluate the
concept and decide whether to continue, revise, combine, or stop before beginning
another design round.
