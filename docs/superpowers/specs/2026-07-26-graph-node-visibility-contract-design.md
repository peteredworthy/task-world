# Graph Node Visibility Contract Design

## Objective

Define a small, iterative information hierarchy for graph nodes inside one
stable run workspace. The contract decides how close each fact must remain to
the node it explains. It does not define the full application, fleet, decision
workflow, observatory, or production implementation.

The first visual baseline is a left-to-right layered dependency DAG with
port-bound edges, a compact attached hover preview, and a right-side selected
node inspector that is independent of graph scrolling.

## Scope

### Included

1. Four visibility classes for graph-node information.
2. State-aware classification using four operator-relevant archetypes.
3. A strict first-class information budget.
4. One provisional graph-node visibility matrix.
5. Graph layout and edge-routing invariants needed to evaluate the hierarchy.
6. Hover, focus, click, selection, disclosure, and inspector behavior.
7. A small visual iteration and evaluation loop.

### Excluded

1. A complete operator-loop concept.
2. Fleet and cross-run information classification.
3. Decision-surface and action-modal design.
4. Production graph layout implementation details.
5. A canonical semantic catalog, schema, generator, or validator.
6. Exhaustive classification of every backend field or node state.

## Working Principle

Information placement is an explicit, revisable decision. It is not inferred
from which screen happens to render a field.

Visibility class controls distance from the node. Visual priority controls
prominence within that class. Capability status, freshness, confidence, and
synthetic-data status annotate a fact; they do not receive permanent regions of
their own.

## Visibility Classes

### Class 1: Always Visible

Class-1 information remains visible whenever the node is visible. Node identity
and kind are always present and do not consume the operational-signal budget.
Each node may show at most three additional Class-1 signals.

Selection must not remove, relocate, or replace Class-1 information.

### Class 2: Visible When Selected

Class-2 information appears in one spatially stable inspector associated with
the selected node. Selecting another node changes only:

- the node selection treatment;
- an optional attached preview;
- the inspector contents.

Unrelated graph, synopsis, and workspace regions do not change.

### Class 3: Locally Available

Class-3 information requires an explicit disclosure from the node or inspector.
It expands and scrolls inside the inspector. It does not re-proportion the graph
or transform one workspace layout into another.

### Class 4: Separate Destination

Class-4 information supports a different job or requires substantial space,
such as a full transcript or repository diff. Opening it preserves:

- run identity;
- selected node;
- attempt or time context;
- graph viewport and zoom;
- return location and scroll state.

Class 4 is not an overflow bin for unresolved hierarchy.

## Classification Scope

Classification is assigned by element type and operational-state archetype. The
first element is a graph node. The first four archetypes are:

1. Active: ready, leased, or running.
2. Waiting or blocked.
3. Failed or attention-required.
4. Settled: completed, retired, or cancelled.

These archetypes are split only when a concrete visual or decision need cannot
be represented honestly by the group.

## First-Class Slots

The three Class-1 operational slots answer stable questions rather than
accumulating badges:

| Archetype | State slot | Current line | Consequence line |
|---|---|---|---|
| Active | Ready, leased, or running | Current work plus activity age | Immediate successors and relationship to the final invariant |
| Waiting or blocked | Waiting or blocked | Exact missing input, gate, authority, or resource plus wait age | Work prevented from becoming ready |
| Failed or attention-required | Failed or attention-required | Primary verifier or failure reason plus current attempt | Affected successors and final-gate effect |
| Settled | Completed, retired, or cancelled | Outcome plus completion age or duration | Final-invariant result or surviving successor path |

The consequence may be communicated through selected edges and affected
descendants instead of an extra prose block.

A new Class-1 fact must fit one of these slots or displace an existing signal.
It cannot become a fourth operational badge.

## Provisional Node Matrix

| Information unit | Active | Waiting / blocked | Failed / attention | Settled |
|---|---:|---:|---:|---:|
| Bound input summary | 2 | 2 | 2 | 3 |
| Lease, execution, model, or profile | 2 | 3 | 3 | 3 |
| Attempt or retry summary | 3 | 2 | 2 | 2 |
| Verifier grade and reason | 3 | 2 | 2, with primary reason promoted to 1 | 2 |
| Output records or artifacts | 2 when produced | 3 | 2 | 2 |
| Usage and price coverage | 2 | 3 | 2 | 2 |
| Prompt-summary metadata | 3 | 3 | 3 | 3 |
| Scheduler and event evidence | 3 | 3 | 3 | 3 |
| Complete input or output record payload | 3 | 3 | 3 | 3 |
| Full transcript or tool trace | 4 | 4 | 4 | 4 |
| Full repository diff or review | 4 | 4 | 4 | 4 |
| Cross-run comparison | 4 | 4 | 4 | 4 |

The matrix is deliberately provisional. Iteration promotes or demotes one
information unit at a time based on whether an operator can answer what matters,
why, and what it affects.

## Graph Layout Grammar

The workspace uses a left-to-right layered dependency DAG.

### Structure

- Horizontal rank is determined by dependency depth.
- Parallel branches occupy separate vertical lanes.
- Multi-input joins visibly converge.
- Dynamic expansion adds a branch without unnecessarily repositioning unaffected
  ranks.
- Retired or superseded paths remain spatially related but visually subdued.

### Nodes

- Node dimensions are measured from identity and the three Class-1 slots.
- Text remains inside its node container.
- Nodes expose explicit left target ports and right source ports.
- State and attention styling remain secondary to the three information slots.

### Edges

- Edges are generated from an explicit source and target edge list.
- Every edge terminates on the correct node ports.
- Routing does not pass through nodes.
- Attention and retired paths may receive distinct treatment without changing
  topology.

### Required Fixture

The first fixture contains:

- a planner fan-out;
- two parallel worker branches;
- a verifier failure;
- a retired or superseded path;
- a human gate;
- a dynamically added corrective branch;
- a multi-input join;
- a final check.

A straight chronological chain is not a valid evaluation fixture.

## Interaction Grammar

### Hover And Keyboard Focus

Hover or focus presents a compact horizontal preview approximately one node high.

- The preview is centered above or below the exact node.
- A visible stem terminates at the node boundary.
- Placement is clamped to the graph canvas and avoids nodes and routed edges.
- If no collision-free placement exists, the preview is omitted.
- Hover is an accelerator, never the only information path.

### Click Or Tap

Click or tap commits selection and opens the right inspector.

- The preview closes immediately.
- Graph world coordinates and node positions do not change.
- The graph canvas and inspector are sibling layout regions.
- Horizontal scrolling belongs only to the graph canvas.
- The inspector uses vertical scrolling only when its own Class-2 and Class-3
  content exceeds available height.
- If the selected node would be obscured, the graph viewport pans only enough to
  keep it visible; the DAG is not recomputed.

While the inspector is open, hover previews are suppressed. Selecting another
node updates the node highlight and inspector in place.

## Data Flow

```text
Graph nodes + explicit edges
  -> layered rank and lane layout
  -> measured node boxes and port positions
  -> routed port-to-port edges
  -> state-aware Class-1 composition

Pointer/focus target
  -> collision-checked attached preview

Committed selection
  -> selected-node treatment
  -> stable Class-2 inspector
  -> local Class-3 disclosure
  -> optional Class-4 destination with return context
```

Selection and information depth are separate state. Changing selection does not
implicitly expand Class 3 or navigate to Class 4.

## Responsive And Accessibility Behavior

- Keyboard focus provides the same preview opportunity as hover.
- Enter or Space commits selection.
- Touch opens the inspector directly and does not depend on hover.
- At narrow widths, the graph remains the primary context and may pan
  horizontally; the inspector becomes an explicit overlay or stacked region.
- Opening the inspector does not silently hide information required to understand
  the selected node.
- Focus remains on an equivalent selected-node or inspector target after state
  changes.

## Iteration Process

The next artifact contains one graph workspace only. Each iteration answers one
bounded question:

1. Can the unselected graph show what matters, why, and what it affects?
2. Does hover or focus preview useful information without obscuring topology?
3. Does selection change only the approved bounded regions?
4. Are Class-2 facts sufficient before Class 3 is opened?
5. Which single fact should move up or down one class?

Classification changes are recorded in plain language, for example:

```text
Failed node: attempts remaining moves Class 2 -> Class 1 because urgency could
not be judged without selection.
```

No identifier ledger or machine validation is required.

## Evaluation

Evaluation occurs in this order:

1. Render the graph in a real browser at desktop and narrow widths.
2. Ask the operator to identify the attention node, primary constraint, and
   affected final path without clicking.
3. Hover or focus several node types and check preview attachment and occlusion.
4. Select several nodes and verify that only selection treatment and inspector
   contents change.
5. Exercise Class-3 disclosure and return from a Class-4 destination.
6. Promote or demote specific matrix items from observed difficulty.
7. Verify visible facts against implementation sources only after the visual
   behavior is acceptable.

A visual failure blocks semantic refinement. Source correctness cannot compensate
for poor hierarchy, disconnected edges, unstable regions, or unreadable graph
structure.

## Stop Conditions

Stop the current iteration when:

- a visual defect prevents evaluation of the current question;
- graph edges do not attach correctly;
- text escapes node or inspector regions;
- selection changes unrelated regions;
- the fixture does not exercise branching, joining, or expansion;
- another information item would exceed the Class-1 budget;
- a proposed change expands scope beyond graph-node hierarchy.

Return to the matrix or graph grammar before adding more content or screens.

## Visual Checkpoint

The accepted visual direction is preserved in the brainstorming companion as
`graph-grammar-dag-v2.html`. It is a layout and interaction checkpoint, not
production code or evidence that collision handling and responsive behavior are
fully implemented.
