TL;DR (what containers do + how they show up)

Containers are reconciliation/looping scopes: they repeatedly run a set of tasks (builder + verifier + optional gap analysis) until a done invariant holds (all obligations discharged + tests/verifier pass) or a budget is hit.

They enable monotonic refinement: gap analysis can only add obligations (requirements/tests/review checks), never remove—so “done stays done” via a scoped obligation ledger and fixpoint detection.

They enable step-level integration reasoning: a container can look across multiple tasks/steps, find cross-cutting gaps, and then assign work by re-running specific tasks or spawning new tasks/steps when something is missing.

They replace “jumping back” with a linear story: instead of time-travel edges, containers create rework items (rerun tasks or spawned follow-ups) while the pipeline still reads left-to-right.

They bound iteration safely: containers own retry limits, novelty/dedupe of obligations, and escalation (“unresolved obligations report”) when budgets are exceeded.

UI implication (brief): show containers as bands/badges with ↻ iter N/M, keep retries inside task history, and provide a container-focused view + outline to explain scope and spawned work.

---

Mini Feature Definition: Container Visualization for Agent Orchestrator UI
1) Summary

Introduce Containers as first-class, explainable constructs in the orchestrator UI without turning the board into a deeply nested “fractal.” Containers represent reconciliation scopes (looping constructs) that repeatedly run one or more tasks until a completion invariant (fixpoint) is satisfied or a budget is reached.

The UI will preserve the current mental model:

X axis: Steps (pipeline progression)

Y axis: Tasks (work items per step)

Containers will be represented as an overlay + outline, not as a new axis.

2) Problem Statement

The system currently displays Steps (columns) and Tasks (cards) with per-task builder/verifier activity. As orchestration evolves to include:

task-level gap analysis loops,

step-level reconciliation,

containers that spawn new tasks or steps,
…the UI needs to convey containment, iteration, and provenance clearly.

Key risk: Adding containers naïvely (especially nested containers) can encourage degeneracy toward “one mega-step with lots of nested loops,” making the board hard to reason about.

3) Goals

Make Containers legible as looping scopes (“a while-loop around work”) for developers.

Depict containment (which tasks/steps are in scope) and iteration (how many cycles, what changed per cycle).

Preserve the existing board’s usability for day-to-day progress tracking.

Support progressive disclosure: simple by default, detailed when needed.

Avoid hard nesting limits; instead apply soft pressure via UI mechanics.

4) Non-Goals

Full orchestration editor / graph editing UI.

Real-time performance profiling dashboard (can be a later extension).

Arbitrary freeform nesting visualization (we’ll support it, but not optimize for unbounded depth in the default view).

5) Concepts & Definitions

Task
A unit of work that may involve Builder/Verifier/Gap Analyzer runs. A Task has a stable identity and keeps attempt history.

Attempt
One execution cycle of a task (builder output + verification results + notes). Attempts are shown inside the task card, not as separate cards.

Container
A reconciliation scope that owns:

invariant / “done” condition,

obligation ledger (requirements/tests/checks) in scope,

loop control (budgets, iteration counters),

spawning behavior (may create follow-up tasks or new steps).

Obligation Ledger
Add-only, deduped set of requirements/tests/checks. Completion is defined by “all obligations discharged + no new obligations added.”

Fixpoint / Convergence
Container completes when no new obligations are discovered and verification gates pass.

6) User Stories

US1: Understand at a glance why the system is looping
As an engineer, I can see a container’s iteration count, status (converged/budget-hit), and what it is trying to satisfy.

US2: See what a container contains
As an engineer, I can select a container and immediately highlight all tasks/steps in its scope.

US3: Debug churn
As an engineer, I can open a container and see iteration-by-iteration diffs: newly added obligations, which tasks were re-run, and what changed.

US4: Preserve linear feel
As an engineer, I can read execution forward (left-to-right) without following “jump back” arrows, while still understanding that the container reconciled earlier work.

US5: See provenance for spawned work
As an engineer, I can tell that a task/step was spawned by a container, and from which iteration.

7) UX Proposal
7.1 Board View (Primary)

Keep the existing Step columns and Task cards.

Add: Container Bands (Overlay)

A container is drawn as a thin ribbon / bracket band that wraps the cards it contains.

Band shows: Container Name, ↻ iter N/M, status (converged, running, budget-hit).

Clicking band highlights contained tasks and dims everything else.

Attempt history stays inside cards

Cards remain one-per-task.

Attempts are shown as an expandable timeline: #1 fail, #2 verifier notes, #3 pass.

7.2 Outline View (Secondary, synchronized)

Add a left-side tree outline (IDE-like):

Feature

Step S1

Container A

Task 1

Task 2

Step S2

Task 3

Selecting an outline node highlights the corresponding band/cards in the board.

7.3 Lens / Mode Toggle (Progressive disclosure)

Provide a top-level toggle:

Flat mode (default): no bands; containers appear as small badges on cards.

Structured mode: show bands + nesting.

Container focus: temporarily reflow/group view to emphasize containers as lanes (read-only “debug lens”).

7.4 Nested containers without hard limits

No explicit depth limit. Instead:

Depth > 2 collapses by default (“+2 nested containers”).

Hover/expand reveals deeper layers.

7.5 Promote-to-step affordance (soft pressure)

If a container spans “too much,” show a suggestion button:

“Promote container to step”
This is a refactor action (doesn’t have to auto-edit orchestration initially; can be “export suggestion” first).

Heuristics for suggestion (tunable):

spans > X tasks or > Y steps, OR

iterates > N times, OR

high churn rate (new obligations per iteration above threshold)

8) Data Model Additions (UI-facing)

Container

id, name, scope_type (task|step|feature)

span: list of (step_id, task_id) references included (or computed from task metadata)

iteration_count, iteration_budget

status: running|converged|budget_hit|failed

invariant_summary: short text (“All obligations discharged + tests pass”)

metrics: churn, rerun_count, time_in_container

parent_container_id (optional)

provenance: who/what created it (system, gap analyzer, user)

ContainerIteration

container_id, iteration_index

new_obligations[] (ids)

tasks_rerun[] (task ids)

notable_events[] (summaries, links to logs)

Task

id, step_id, title

container_ids[] (membership)

attempts[] (builder/verifier outcomes + notes)

spawned_by: {container_id, iteration_index} optional

Obligation

id, type (req|test|review_check)

status (open|discharged)

source: {container_id, iteration_index, analyzer}

9) Explanation UX (how users learn containers)

When clicking a container band:

Right panel shows:

“What this container is doing” (invariant)

Iteration summary: iter 2/5

Churn chart (optional later)

Timeline: Iteration 1/2/3 with diffs (obligations added, tasks rerun)

This makes the “looping construct” feel like a familiar control structure.

10) Acceptance Criteria

Users can identify containers and their scope from the board in <10 seconds.

Users can answer: “Why is this looping?” by opening container details and seeing iteration diffs.

Task retries do not create new cards; attempt history is contained inside the card.

Nested containers render without breaking the layout; deeper nesting collapses by default.

Spawned tasks show provenance (origin container + iteration).

Flat mode remains clean and comparable to today’s board experience.

11) Rollout Plan

Phase 1 (Read-only, minimal disruption)

Add container metadata support

Add container bands (structured mode)

Add card badges + provenance glyphs (flat mode)

Phase 2 (Debuggability)

Add outline view

Add container detail panel (iteration diffs)

Add lens toggle (container focus mode)

Phase 3 (Soft pressure & refactoring)

Add promote-to-step suggestions

Add churn metrics + “hotspot” surfacing

12) Key Risks & Mitigations

Risk: Visual clutter with many containers

Mitigation: Flat mode default; structured mode opt-in; collapse deep nesting.

Risk: Users overuse containers and hide pipeline structure

Mitigation: Promote-to-step suggestion; churn/hotspot indicators; visibility decay.

Risk: Confusion between “task loop” and “step loop”

Mitigation: Clear scope labeling on band (Task-scope, Step-scope), and consistent invariant language.

13) Open Questions (optional)

Should container bands be allowed to span non-contiguous tasks (likely yes, but visually it may need “multiple segments”)?

Do we want a dedicated “Container list” view sorted by churn/time (like CI runs)?

Should promote-to-step be purely advisory, or actually rewrite orchestration config?

If you want, I can also write a short “user-facing explainer” (two paragraphs + a diagram in text) that you can drop into the UI as the help tooltip for Containers.