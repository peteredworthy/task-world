# Five JTBD UI Approaches HTML Presentation Design

## Objective

Create one standalone HTML presentation that compares five genuinely distinct interface architectures against Task World's complete operator loop. The presentation must help a product stakeholder judge how each architecture balances visual clarity, information density, relationship comprehension, evidence access, action safety, and navigation burden.

The mockups must avoid the common LLM-UI pattern of sparse prose inside padded cards. They should communicate through topology, tracks, matrices, ribbons, lanes, status geometry, color, and compact labels while retaining enough text to explain requirements and consequences accurately.

## Source Grounding

The presentation uses the canonical JTBD package:

- `docs/jtbd/jobs.md`
- `docs/jtbd/journeys.md`
- `docs/jtbd/decision-information.md`
- `docs/jtbd/information-architecture.md`
- `docs/jtbd/evaluation-rubric.md`

The eight jobs form the operating loop:

`J1 notice -> J2 position -> J3 decide / J4 explain -> J5 verify -> J6 act -> J7 learn -> J8 compare`

Every concept must support that complete loop rather than specializing in one job. The same illustrative run, facts, grades, evidence, costs, decisions, and recovery outcome must appear in all five concepts so the comparison tests architecture rather than content.

## Audience and Decision

The primary audience is the product owner acting as product stakeholder, design evaluator, and engineering decision-maker.

The presentation should make it possible to:

1. Identify which organizing geometry best exposes attention, position, cause, evidence, and safe action.
2. Identify elements worth combining across concepts.
3. Reject patterns that waste space, hide relationships, or force avoidable navigation.
4. Separate current and derivable product behavior from proposed capability gaps.

The presentation is exploratory. Its final comparison should record strengths, risks, and promising combinations rather than declare a cosmetic winner.

## Deliverable

Create:

`outputs/jtbd-ui-directions/05-five-approach-interactive-comparison.html`

The file must:

- open directly in a browser without a build step;
- contain its CSS, JavaScript, and SVG inline;
- make no external font, icon, CDN, or network requests;
- support keyboard, mouse, and touch interaction;
- remain usable at desktop, tablet, and narrow viewport widths;
- show a readable failure notice if initialization fails.

## Presentation Structure

The presentation has seven slides:

1. **Operating loop:** a compact JTBD map, scenario synopsis, visual legend, and interaction guide.
2. **Operational Cartography:** topology-centered workspace.
3. **Causal Spine:** time-and-causality-centered workspace.
4. **Intervention Desk:** unresolved-decision-centered workspace.
5. **Evidence Workbench:** claims-and-provenance-centered workspace.
6. **Mission Weave:** workstream-and-stage-centered workspace.
7. **Comparison:** rubric-based strengths, risks, and candidate combinations.

Deck navigation uses visible previous/next controls and left/right arrow keys. The URL hash identifies the current slide so reload and deep links restore it.

Each concept slide contains one full-screen interactive workspace and a common five-position state rail:

`Fleet -> Position -> Cause / Evidence -> Action -> Outcome`

The state rail changes the workspace in place. It does not navigate to separate mockup slides. Number keys `1` through `5` select workspace state so they do not conflict with deck navigation.

## Shared Scenario

All five concepts use one JavaScript scenario object. It includes:

- a fleet with healthy, progressing, waiting, degraded, and settled runs;
- degraded run `r314`, promoted because one required recovery claim failed twice;
- human-readable run, region, node, requirement, and evidence labels;
- secondary generated IDs such as `R2` and `N18`;
- builder and verifier node lineage across attempts;
- grades, files changed, new evidence, packet differences, costs, and attempt budget;
- three blocked successors and the final invariant path;
- a proposed typed intervention that binds an incident record and replay fixture;
- validation, corrective execution, recovery, final-gate success, and reusable learning;
- capability status for every action or derived claim.

Illustrative values remain identical across concepts. A rendering helper formats shared facts, preventing concept-specific copies from drifting.

## Five Interface Architectures

### 1. Operational Cartography

**Stable object:** the selected graph node, requirement, and constraint path.

Topology is the primary geometry. Nodes carry human-readable work labels, generated IDs as metadata, state, and visible grades. Color highlights verified flow, the active constraint, blast radius, and proposed correction. Regions and suppressed-node counts make a large graph legible without pretending every node fits at once.

Fleet state uses a proportional ribbon and ranked exception list. Selecting a requirement displays every node that touched it as vertical rows with fixed statistic columns. The growing dimension is vertical; statistics such as grade, files changed, new evidence, and cost remain fixed columns with a sticky header.

This concept is strongest at position and relationship comprehension. Its principal risk is overwhelming users as graph size and edge density increase.

### 2. Causal Spine

**Stable object:** the selected event, causal interval, and branch.

A dense event spine organizes planner changes, builders, verdicts, retries, evidence arrival, decisions, and recovery in causal order. Parallel graph branches occupy compact tracks rather than being flattened into one timeline. Selecting an event expands evidence and consequences beside the spine while preserving the run synopsis and current interval.

The fleet view summarizes each run as a compact pulse strip showing activity, waits, retries, and decision markers. The evidence state aligns causal events with node lineage and source records.

This concept is strongest at explaining what changed and why. Its principal risk is making topology and downstream blast radius less immediately visible.

### 3. Intervention Desk

**Stable object:** the unresolved operator case.

The fleet becomes a ranked queue of exceptions rather than a gallery of run cards. Each case encodes urgency, blocked scope, age, reversibility, estimated cost, and confidence. Selecting a case assembles trigger, evidence, consequence, options, authority, and validation into one decision surface.

Healthy runs remain a compressed distribution. Diagnosis and evidence are embedded in the case instead of requiring disconnected screens. Resolved cases collapse into an auditable outcome strip.

This concept is strongest at attention allocation and action latency. Its principal risk is making quiet exploration and non-exception monitoring secondary.

### 4. Evidence Workbench

**Stable object:** the selected claim or requirement and its provenance.

Requirements, node lineage, grades, packet inputs, changed files, transcript signals, costs, and verifier evidence align in a dense comparison surface. Rows represent growing node or attempt sets; columns represent stable measurements. A compact graph locator preserves position and blast radius without dominating the workspace.

Evidence records link visibly to the claim they support or contradict. Full prompt, transcript, and diff content remain progressive detail, while size, source, freshness, omission, and delta remain visible in the main workspace.

This concept is strongest at verification and attempt comparison. Its principal risk is appearing analytical or tabular before the operator understands the run's overall shape.

### 5. Mission Weave

**Stable object:** the selected workstream, stage segment, and branch join.

Parallel regions flow through plan, build, verify, gate, and settle lanes. Dynamic graph additions branch into the weave rather than being forced into a fixed pipeline. Width, color, join points, and rework loops communicate throughput, blocked work, repeated verification, and final-invariant convergence.

Fleet state compresses each run into a miniature weave. Selecting a segment reveals its nodes, evidence, and decisions without leaving the lane context. Interventions appear as explicit branch insertions with validation and authority markers.

This concept is strongest at communicating parallel progress and rework. Its principal risk is implying a more regular stage model than a highly dynamic graph actually has.

## Visual and Density System

All five concepts use one semantic visual language so differences come from architecture, not theme.

### Labels

- Human-readable names are primary.
- Generated IDs such as `R2` and `N18` are secondary metadata.
- Requirement text is visible wherever a grade or decision depends on it.
- Grades are visible wherever attempts, requirements, or verification nodes appear.

### Density

- Growing dimensions run vertically and use sticky headers where necessary.
- Fixed statistics become columns, compact glyphs, ribbons, aligned tracks, or lane markers.
- Low-entropy totals use proportional ribbons or inline telemetry, never large metric cards.
- Whitespace separates reading groups; it does not pad nested boxes.
- Exception states may become dense, but follow `constraint -> evidence -> consequence -> action`.
- Healthy states collapse deliberately and expose no unnecessary action controls.

### Semantics

- Teal: verified or progressing.
- Coral: blocking, failed, or requiring attention.
- Amber: waiting, proposed, or requiring judgment.
- Blue-gray: context, inactive structure, or unknown state.
- Color is never the only state signal.

Node, event, case, evidence record, and workstream segment use distinct shapes. Charts must have an explicit domain meaning and must not be decorative.

### Progressive Detail

The main workspace keeps these visible:

- current constraint and scope;
- human-readable requirement or decision;
- grades and attempt lineage;
- evidence availability and delta;
- blast radius or downstream consequence;
- cost, attempts left, and capability status;
- action entry point and resulting state.

Full prompts, transcripts, tool logs, and file diffs open as progressive detail without losing the selected run, node, attempt, requirement, or pending decision.

## Interaction Model

Each concept implements interactions appropriate to its stable object:

- Cartography selects nodes, requirements, and paths.
- Causal Spine selects events, intervals, and branches.
- Intervention Desk selects cases, evidence packets, and options.
- Evidence Workbench selects claims, rows, records, and comparisons.
- Mission Weave selects lanes, segments, joins, and rework loops.

Selection updates a persistent detail surface in the same workspace. State changes preserve the most relevant selection when possible. Any destructive or consequential action opens a proper modal with scope, consequence, authority, reversibility, and confirmation; confirm/cancel controls never appear inline in compact rows.

The mock interaction for typed steering is labeled **Proposed capability**. The presentation must not imply that a steering directive or planner-assisted replanning currently exists.

## Internal Architecture

The standalone document separates responsibilities internally:

1. **Scenario model:** immutable shared facts and capability labels.
2. **Deck controller:** slide navigation, hash restoration, progress, and keyboard behavior.
3. **Workspace controller:** operating-loop state, concept selection, modal state, and focus restoration.
4. **Concept renderers:** five independent renderers consuming the shared scenario.
5. **Shared primitives:** status markers, grade glyphs, capability labels, evidence links, modal shell, and compact legends.

Concept renderers must not own duplicate scenario facts. They receive the same scenario and derive their own projection.

## Responsive Behavior

- Wide desktop: context and focus may appear simultaneously.
- Tablet: re-proportion context and focus before hiding either.
- Narrow viewport: stack a sticky synopsis and selection context above the focus surface.
- Growing tables scroll vertically with headers retained.
- Decision-critical evidence is not removed at narrow widths; labels shorten and raw detail remains expandable.
- Presentation controls remain reachable by touch and keyboard.

## Failure Handling and Accessibility

- Initialization is wrapped so a readable failure notice replaces an empty presentation.
- Every interactive control is a semantic button or link with a visible focus state.
- Workspace state and selection changes update a polite live region.
- Modals trap focus, close on Escape, restore focus to their trigger, and prevent background interaction.
- Reduced-motion preferences disable nonessential transitions.
- Text and non-color markers accompany every status color.

## Comparison Slide

The final slide uses the weighted criteria in `docs/jtbd/evaluation-rubric.md`:

- attention clarity;
- position and blast radius;
- causal comprehension;
- decision readiness;
- evidence access;
- context continuity;
- complexity control;
- action safety and feedback;
- capability honesty;
- responsive integrity.

It records expected strengths, risks, and candidate combinations. It does not fabricate user-testing scores. Any score shown must be clearly labeled as a design hypothesis rather than observed evidence.

## Verification

Verify the completed document against these conditions:

1. All seven slides render and are directly addressable by hash.
2. All five operating-loop states render for every concept.
3. Keyboard, mouse, and touch controls change slides and workspace states correctly.
4. Shared scenario facts remain identical across concepts.
5. Generated IDs never replace human-readable names as the primary label.
6. Grades remain visible in all contexts where they affect interpretation.
7. Growing node, event, case, record, and lane sets use vertical growth or semantic aggregation rather than horizontal overflow.
8. Desktop, tablet, and narrow layouts preserve decision-critical context without clipping.
9. Current, derivable, and proposed capabilities are visually distinguishable.
10. Consequential action confirmation uses a modal with focus management.
11. The document makes no external requests and opens from the filesystem.
12. No large metric card, unexplained chart, or persistently irrelevant panel survives review.
13. The comparison slide uses rubric language and avoids unsupported empirical claims.

## Scope Boundaries

This deliverable is a presentation and interactive design artifact. It does not modify the production React UI, backend APIs, graph runtime, or steering capabilities. Its purpose is to expose architectural trade-offs before implementation decisions are made.
