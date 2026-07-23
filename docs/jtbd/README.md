# Jobs to Be Done and User Journeys

This section is the product grounding for a new Task World UI. It describes the progress an operator is trying to make, the decisions they must take, the evidence required to take them safely, and the interface constraints that follow.

Use it before drawing screens. A screen, field, metric, or action belongs in the product only when it helps a documented job, decision, or journey.

## What this review found

The supplied UI blueprint has a strong core:

- The eight jobs cover the complete operating loop: triage, position, decide, diagnose, verify, act, learn, and compare.
- The journeys are outcome-oriented and use measurable success conditions such as “confident nothing needs me without opening a run” and “recover without cancel-and-restart.”
- A single health model gives fleet ranking, color, and action priority the same meaning everywhere.
- The diagnose-to-steer journey tests the hardest product problem: keeping position, evidence, consequences, and actions together while a growing execution graph changes beneath the operator.
- The proposed persistent inspector directly addresses repeated switching because selection and evidence survive changes of lens.

The blueprint also reveals important risks:

- Some jobs assume derived signals that are not yet exposed as product data, such as repeated-finding detection, no-progress classification, budget pace, and cross-run churn.
- “Steer” is not a current capability. The existing human channels answer predefined questions or accept expert-authored graph patches; they do not inject typed instructions and context for replanning.
- A map can explain topology but become an end in itself. It must earn its space by answering position, dependency, and blast-radius questions faster than a simpler representation.
- The original job statements say what users want, but a buildable UI also needs a decision-information contract: what must be known, its provenance, its freshness, uncertainty, consequence, and available action.
- “Avoid switching views” must not become “show everything at once.” The design needs stable context, selection, and progressive disclosure—not permanent density.

## Canonical documents

| Document | Purpose |
|---|---|
| [Jobs](./jobs.md) | Eight jobs, triggers, desired progress, frequency, success, current pain, and home surface |
| [Journeys](./journeys.md) | Five end-to-end journeys with decisions, information, evidence, actions, and recovery paths |
| [Decision information](./decision-information.md) | What the operator must know before each consequential decision |
| [Information architecture](./information-architecture.md) | Shared health semantics, screen responsibilities, selection behavior, and complexity controls |
| [Evaluation rubric](./evaluation-rubric.md) | A consistent method for comparing UI concepts and prototypes |

## Product vocabulary

| Term | Meaning in this section |
|---|---|
| Operator | The human supervising, diagnosing, approving, or steering one or more runs |
| Fleet | All current runs, ordered by need for human attention |
| Workspace | The stable operating surface for one run |
| Selection | The run, node, record, requirement, attempt, or event currently in focus |
| Evidence | The event, record, prompt packet, transcript, artifact, file boundary, or cost record supporting a claim |
| Constraint | The most important condition currently limiting progress |
| Lens | An alternative projection of the same selected run, not a separate destination |
| Steering | Operator-authored instruction/context that can be bound into future work and optionally trigger replanning; proposed, not current |

## Capability status labels

The documentation uses three labels so concept designs do not turn proposals into facts.

| Label | Meaning |
|---|---|
| **Current** | The repository already stores or exposes the capability or source data |
| **Derivable** | Existing data can support the claim, but a join, detector, aggregation, or UI/API projection is still required |
| **Gap** | The underlying command, record, lifecycle, or telemetry does not yet exist |

## Source and review status

Primary source: `task-world UI blueprint — jobs, journeys, steering.html`, supplied 2026-07-18. Its kernel claims were made against repository commit `60ca04f96`, which is also the reviewed HEAD.

Repository grounding:

- [Product requirements](../intent/03-PRD.md)
- [Existing UI description](../intent/08-UI-DESCRIPTION.md)
- [Human interaction design](../intent/28-HUMAN-INTERACTION-DESIGN.md)
- [Architecture and API inventory](../ARCHITECTURE.md)
- Current UI components under `ui/src/`
- Graph API, records, commands, validation, prompt hydration, and telemetry under `src/orchestrator/`

Mock names, timestamps, costs, token totals, and outcomes in the source blueprint are illustrative. The jobs, journeys, capability analysis, and interface requirements are the reusable product artifacts.

## Maintenance rules

1. Give each new job a durable ID and an observable success condition.
2. Add a journey only when it represents a distinct trigger-to-outcome path; do not duplicate screen flows.
3. Add new displayed information through the decision-information matrix first.
4. Mark capability status whenever a UI depends on backend or derived behavior.
5. Keep a job independent of a particular screen. Home surfaces may change; desired progress should not.
6. Validate prototypes with the rubric and record evidence, not preference alone.
