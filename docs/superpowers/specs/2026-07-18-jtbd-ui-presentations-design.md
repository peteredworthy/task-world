# JTBD Grounding and UI Concept Presentations — Design

## Objective

Create a durable JTBD reference for Task World and use it to compare four interface architectures against the same operator scenario. The comparison is about how well each architecture communicates complex run state, preserves evidence and actions in context, and avoids repeated view switching without accumulating permanent clutter.

## Audience and communication job

The audience is the product owner acting simultaneously as product/design stakeholder, engineering evaluator, and executive decision-maker.

By the end, the audience should be able to identify which UI architecture best supports rapid, evidence-backed intervention because every concept is tested against the same jobs, decisions, information needs, and recovery journey.

## Source grounding

The primary source is the supplied `task-world UI blueprint — jobs, journeys, steering.html`, especially its eight JTBD, five journeys, shared health model, persistent-inspector proposal, seven-scene recovery narrative, and audit of the missing steering capability.

Repository sources provide the current product model and constraints:

- `docs/intent/03-PRD.md`
- `docs/intent/08-UI-DESCRIPTION.md`
- `docs/intent/28-HUMAN-INTERACTION-DESIGN.md`
- `docs/ARCHITECTURE.md`
- Current UI and graph API surfaces under `ui/src/` and `src/orchestrator/`

All proposed capabilities will be labeled as current, derivable, or gap so a visual concept never implies that an unimplemented backend capability already exists.

## Documentation architecture

Create `docs/jtbd/` as the canonical product-discovery section:

- `README.md` — purpose, terminology, source status, navigation, and maintenance rules.
- `jobs.md` — the eight outcome-oriented jobs with trigger, progress, frequency, success signal, current pain, and home surface.
- `journeys.md` — five end-to-end journeys with trigger, decisions, screen transitions, information required, actions, evidence, and recovery states.
- `decision-information.md` — decision inventory stating what the user must know, why it matters, acceptable confidence, evidence provenance, consequences, and safe actions.
- `information-architecture.md` — shared health model, screen responsibilities, selection model, progressive-disclosure rules, switching/clutter constraints, responsive behavior, and current-versus-gap capabilities.
- `evaluation-rubric.md` — a reusable rubric for judging candidate UIs on clarity, decision readiness, context continuity, complexity control, evidence, action safety, responsiveness, and implementation honesty.

The section is a decision-support body, not a feature inventory. Every piece of displayed information must trace to a job or decision.

## Fair comparison scenario

All four decks use the same illustrative run `r314`:

1. The fleet is healthy and requires no action.
2. A repeated verifier finding promotes the run to attention.
3. The operator locates the failing requirement and its blast radius.
4. The operator establishes why the retry loop lacks new information.
5. The operator chooses steering over another retry.
6. A corrective region executes with the directive and evidence bound.
7. The run recovers and the intervention becomes reusable learning.

The mock values are illustrative, while product capabilities and gaps are grounded in the repository and supplied blueprint.

## Four interface architectures

### 1. Persistent Inspector — “Control Room”

An attention-ranked fleet opens into a two-pane workspace. The selected run/node/record is stable; the canvas switches lenses while a single inspector retains anatomy, evidence, decisions, and actions. Depth is achieved by flipping the 60/40 split, not by opening drawers or changing pages.

This is the strongest baseline and the closest to the supplied blueprint.

### 2. Event Spine — “Case File”

A continuous causal timeline is the primary object. Health, decisions, attempts, evidence, and actions attach to the event spine; selecting an event expands it in place while the run synopsis remains pinned. This approach minimizes spatial graph complexity and makes “why” exceptionally clear, at the cost of weaker topology awareness.

### 3. Exception Queue — “Intervention Desk”

The UI is organized around unresolved operator decisions rather than runs. Each case carries the constraint, consequence, evidence packet, recommended next action, and downstream effect in one working surface. Resolved cases collapse into history. This optimizes triage and action latency, but requires careful handling of quiet monitoring and non-exception exploration.

### 4. Focus + Context — “Evidence Map”

A compact causal map remains visible as a stable context strip while the selected node’s evidence becomes the dominant reading surface. Semantic zoom changes detail without changing destination; evidence, grades, packet differences, and actions occupy the focus area. This preserves topology better than the case file while avoiding a fully dense graph canvas.

## Mockup deck structure

Each PowerPoint contains five edge-to-edge desktop product mockups:

1. Quiet fleet state: global navigation, run selection, health claim, and current work.
2. Degraded diagnosis: repeated R2 failure, topology position, blast radius, and retry trade-off.
3. Evidence inspection: verifier scenario, attempt comparison, missing packet inputs, and provenance.
4. Steering: typed directive, selected evidence, scope, authority, correction budget, and approval boundary.
5. Recovery: corrective route, binding confirmation, final-gate outcome, cost, and captured learning.

There are no title, architecture, strategy, or evaluation slides. The PowerPoint canvas is the application viewport. A small direction label may appear inside normal product chrome, but every slide must read first as a usable Task World screen. The four decks use different interface architectures while holding the scenario facts constant.

## Visual and content constraints

- Use realistic application chrome, navigation, controls, selection states, status indicators, tables, inspectors, timelines, evidence viewers, forms, and modals.
- Avoid presentation headlines, explanatory prose, rubric scores, and concept summaries.
- Prefer one complete screen state per slide over disconnected wireframe fragments.
- Keep decision-critical information visible together: trigger, diagnosis, evidence, consequence, cost of waiting/continuing, action, and audit result.
- Use progressive disclosure within a stable surface rather than page hopping.
- Never place destructive confirmation controls inline; actions lead to a proper decision surface.
- Label proposed steering capabilities honestly.
- Use a shared factual ledger so mock values and terminology do not drift between decks.

## Verification

- Check every JTBD and journey against the source blueprint.
- Verify the decision-information matrix covers every consequential operator action.
- Render every slide and inspect it individually at full size.
- Run overflow checks and fix all clipping, wrapping, and unintended overlaps.
- Confirm all four decks use the same scenario facts and can be scored against the same rubric.
- Confirm the decks differ in interface architecture, not only theme.

## Scope boundaries

This work does not implement the UI or the missing steering kernel capability. It documents the product problem and produces high-fidelity mockup decks suitable for choosing a prototyping direction.
