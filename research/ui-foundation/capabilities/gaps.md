# Capability classifications

Generated from `capabilities/registry.yaml`; do not edit by hand.

## Current (2)

- `CAP-69` **Command validator result** — The command validator result demand is current only for reachable graph patch and decision validation paths that return accepted or rejected diagnostics.
- `CAP-86` **Approve deny or defer a gate or patch** — The approve, deny, or defer a gate or patch demand is current only as split graph approval or denial and patch-validation paths; no unified defer command exists.

## Derived (0)

- None

## Proposed (25)

- `CAP-82` **Derived claims expose evidence and freshness** — Derived claims expose evidence and freshness is a future product or evaluation-policy demand from journeys.continuity.derived-evidence-freshness, not an observed current capability.
- `CAP-83` **Actions expose scope consequence reversibility authority and confirmation** — Actions expose scope consequence reversibility authority and confirmation is a future product or evaluation-policy demand from journeys.continuity.action-safety-fields, not an observed current capability.
- `CAP-84` **Responsive layout preserves decision context** — Responsive layout preserves decision context is a future product or evaluation-policy demand from journeys.continuity.responsive-context, not an observed current capability.
- `CAP-95` **Show timestamp or age for live health inputs** — Show timestamp or age for live health inputs is a future product or evaluation-policy demand from honesty.live-input-age, not an observed current capability.
- `CAP-96` **Label detectors and derived claims and expose evidence** — Label detectors and derived claims and expose evidence is a future product or evaluation-policy demand from honesty.derived-label-evidence, not an observed current capability.
- `CAP-97` **Unpriced usage remains explicit and is not zero** — Unpriced usage remains explicit and is not zero is a future product or evaluation-policy demand from honesty.unpriced-not-zero, not an observed current capability.
- `CAP-98` **Do not imply fixed completion percentage for a growing plan** — Do not imply fixed completion percentage for a growing plan is a future product or evaluation-policy demand from honesty.no-growing-plan-percent, not an observed current capability.
- `CAP-99` **Distinguish observed fact from inference** — Distinguish observed fact from inference is a future product or evaluation-policy demand from honesty.fact-versus-inference, not an observed current capability.
- `CAP-100` **Mark approximate values** — Mark approximate values is a future product or evaluation-policy demand from honesty.approximate-values, not an observed current capability.
- `CAP-101` **Do not imply directive delivery without packet binding evidence** — Do not imply directive delivery without packet binding evidence is a future product or evaluation-policy demand from honesty.directive-binding-proof, not an observed current capability.
- `CAP-118` **Distinct semantic vocabulary remains stable across projections** — Distinct semantic vocabulary remains stable across projections is a future product or evaluation-policy demand from ia.vocabulary.distinct-entities, not an observed current capability.
- `CAP-119` **Attention clarity** — Attention clarity is a future product or evaluation-policy demand from rubric.attention-clarity, not an observed current capability.
- `CAP-120` **Position and blast radius** — Position and blast radius is a future product or evaluation-policy demand from rubric.position-blast-radius, not an observed current capability.
- `CAP-121` **Causal comprehension** — Causal comprehension is a future product or evaluation-policy demand from rubric.causal-comprehension, not an observed current capability.
- `CAP-122` **Decision readiness** — Decision readiness is a future product or evaluation-policy demand from rubric.decision-readiness, not an observed current capability.
- `CAP-123` **Evidence access** — Evidence access is a future product or evaluation-policy demand from rubric.evidence-access, not an observed current capability.
- `CAP-124` **Context continuity** — Context continuity is a future product or evaluation-policy demand from rubric.context-continuity, not an observed current capability.
- `CAP-125` **Complexity control** — Complexity control is a future product or evaluation-policy demand from rubric.complexity-control, not an observed current capability.
- `CAP-126` **Action safety and feedback** — Action safety and feedback is a future product or evaluation-policy demand from rubric.action-safety-feedback, not an observed current capability.
- `CAP-127` **Capability honesty** — Capability honesty is a future product or evaluation-policy demand from rubric.capability-honesty, not an observed current capability.
- `CAP-128` **Responsive integrity** — Responsive integrity is a future product or evaluation-policy demand from rubric.responsive-integrity, not an observed current capability.
- `CAP-129` **No selection resets or manual reselection** — No selection resets or manual reselection is a future product or evaluation-policy demand from rubric.no-selection-resets, not an observed current capability.
- `CAP-130` **Every derived claim has one-step evidence access** — Every derived claim has one-step evidence access is a future product or evaluation-policy demand from rubric.derived-evidence-access, not an observed current capability.
- `CAP-131` **Every action visibly confirms resulting state** — Every action visibly confirms resulting state is a future product or evaluation-policy demand from rubric.result-state-confirmation, not an observed current capability.
- `CAP-132` **Viability floor for decision evidence action safety and honesty** — Viability floor for decision evidence action safety and honesty is a future product or evaluation-policy demand from rubric.viability-floor, not an observed current capability.

## Gap (49)

- `CAP-1` **Health class** — Health class has state inputs but no shared thresholds, producer, or explanation record.
- `CAP-5` **Last-event age** — Last-event age lacks a common event clock across legacy and graph carriers.
- `CAP-6` **Budget pace** — Budget pace has no budget window, denominator, or pace computation contract.
- `CAP-7` **Blast radius** — Blast radius has topology fragments but no affected-work closure contract.
- `CAP-10` **Planner horizon** — Planner horizon has task and graph records but no common planned-work horizon.
- `CAP-12` **Attempts left** — Attempts left cannot join per-task limits with graph retry and recovery boundaries.
- `CAP-13` **Final-invariant progress** — Final-invariant progress has checks and states but no monotonic completion projection.
- `CAP-17` **Affected scope** — Affected scope has local records but no authoritative cross-run or graph scope closure.
- `CAP-20` **Downstream effect** — Downstream effect has event adjacency but no causal consequence contract.
- `CAP-21` **Reversibility** — Reversibility is action-specific; no shared undo, compensation, or residue result exists.
- `CAP-24` **Requirement-grade changes** — Requirement-grade changes lack a normalized grade history and comparison rule.
- `CAP-30` **Prompt size** — Prompt size is split between retained text and graph summaries without one size fact.
- `CAP-38` **Retry information delta** — Retry information delta lacks a durable before-and-after comparison rule.
- `CAP-42` **Authority** — Authority has route-local permissions and graph checks but no uniform actor binding.
- `CAP-43` **Intervention budget** — Intervention budget has no durable limit, consumption, or exhaustion contract.
- `CAP-44` **Intervention reversibility** — Intervention reversibility is action-specific with no shared undo or compensation result.
- `CAP-47` **Unpriced share** — Graph rollups expose missing-rate counts but no complete unpriced-share denominator.
- `CAP-48` **Prompt size** — Prompt size remains split between legacy retained text and graph summary metadata.
- `CAP-49` **Retries without new information** — Retry actions exist, but no retry taxonomy or cross-carrier new-information test exists.
- `CAP-50` **Repeated tools and work** — Structured traces expose repetitions, but no durable cross-run repeated-work finding exists.
- `CAP-51` **Verifier churn** — Verifier results are retained per carrier without a churn aggregation contract.
- `CAP-52` **Comparable cohort** — Comparable cohort has no implemented selection criteria, population, or exclusion rules.
- `CAP-57` **Price coverage** — Price coverage lacks a persisted priced-versus-unpriced population denominator.
- `CAP-58` **Patch count** — Patch attempts are graph-local and have no cross-mode count definition.
- `CAP-59` **Retry count** — Retry count differs among revision, recovery, and graph retry carriers.
- `CAP-60` **Grade churn** — Grade records do not define a comparable sequence or churn threshold.
- `CAP-63` **Prompt pressure** — Prompt pressure lacks capacity, tokenization, and threshold semantics across runners.
- `CAP-64` **Final-gate effect** — Final-gate records do not establish the downstream work caused or prevented.
- `CAP-66` **Explicit empty needs-you state** — Explicit empty needs-you state has no positive, durable no-attention-needed contract.
- `CAP-67` **No runaway signal** — No runaway signal has no timeout, rate, or observation-window contract.
- `CAP-68` **Decision wait age** — Decision wait age lacks a shared pending-decision clock across graph and legacy flows.
- `CAP-71` **Cost of another attempt** — Cost of another attempt has incomplete history but no cohort estimator or uncertainty rule.
- `CAP-72` **Candidate delta** — Candidate delta lacks a stable before-and-after candidate comparison boundary.
- `CAP-73` **Causal gap** — Causal gap cannot be resolved from observer events without producer causality.
- `CAP-74` **Directive binding** — Directive binding has no durable link from instruction to resulting action or artifact.
- `CAP-77` **Missing node attribution** — Missing node attribution lacks an expected-execution denominator for absent telemetry.
- `CAP-78` **Detector drill-through evidence** — Detector drill-through evidence lacks a durable finding-to-source evidence bundle.
- `CAP-81` **Restore prior ranking filter and scroll position** — Restore prior ranking filter and scroll position has no durable return-state contract.
- `CAP-85` **Ignore or keep watching** — Ignore or keep watching has no command recording identity, scope, expiry, or later attention.
- `CAP-92` **Steer with new context** — Steer with new context has no admitted command with durable context-to-work binding.
- `CAP-93` **Apply a steering patch** — Apply a steering patch has no unified command joining context, topology, and outcome.
- `CAP-106` **Next expected system activity** — Next expected system activity lacks a cross-carrier prediction and timing contract.
- `CAP-108` **Evidence convergence** — Evidence convergence has no rule for reconciling divergent carrier observations.
- `CAP-110` **Degraded classification** — Degraded classification has signals but no shared threshold or class producer.
- `CAP-111` **Stalled classification** — Stalled classification lacks an inactivity threshold and cross-carrier clock.
- `CAP-112` **Runaway classification** — Runaway classification lacks a rate threshold, window, and durable class result.
- `CAP-113` **Steered classification** — Steered classification lacks a durable directive-to-outcome classification contract.
- `CAP-116` **Active comparison target** — Active comparison target has no persisted second-run identity across projections.
- `CAP-117` **Freshness and capability annotations persist with selection** — Freshness and capability annotations have no selection-bound persistence contract.

## Unknown (56)

- `CAP-2` **Current constraint** — Current constraint is unresolved because legacy and graph constraints have no typed precedence.
- `CAP-3` **Human wait state** — Human wait state is unresolved because clarification, approval, and graph waits have no common lifecycle.
- `CAP-4` **Frontier activity** — Frontier activity is unresolved because ready graph work, leased work, and legacy activity use different units.
- `CAP-8` **Active nodes and steps** — Active nodes and steps is unresolved because legacy steps/tasks and graph nodes are non-equivalent execution units.
- `CAP-9` **Dependency path** — Dependency path is unresolved because graph edges and legacy dependencies lack a shared path identity.
- `CAP-11` **Blocked reason** — Blocked reason is unresolved because lifecycle, scheduler, lease, and approval blockers have no priority rule.
- `CAP-14` **Exact question** — Exact question is unresolved because clarification and graph decisions do not share a question payload.
- `CAP-15` **Why now** — Why now is unresolved because timestamps show order but not one triggering cause.
- `CAP-16` **Proposer** — Proposer is unresolved because caller attribution, actor eligibility, and authorization disagree.
- `CAP-18` **Decision evidence** — Decision evidence is unresolved because decision evidence lacks a typed cross-carrier decision join.
- `CAP-19` **Alternatives** — Alternatives is unresolved because commands do not enumerate decision-specific feasible alternatives.
- `CAP-22` **Ordered events** — Ordered events is unresolved because workflow and graph streams have separate public ordering rules.
- `CAP-23` **Attempt lineage** — Attempt lineage is unresolved because attempt, recovery, fan-out, and graph-generation identities conflict.
- `CAP-25` **Patch provenance** — Patch provenance is unresolved because patch submission, validation, and effects are not one provenance record.
- `CAP-26` **State transitions** — State transitions is unresolved because legacy and graph state machines have distinct transition vocabularies.
- `CAP-27` **Retries and rejections** — Retries and rejections is unresolved because revision, recovery, fan-out, and patch rejection are distinct behaviors.
- `CAP-28` **Bound input records** — Bound input records is unresolved because bindings, verification, and prompt metadata expose different inputs.
- `CAP-29` **Omitted and referenced context** — Omitted and referenced context is unresolved because no packet manifest distinguishes omission from summary or absence.
- `CAP-31` **Transcript** — Transcript is unresolved because legacy traces and graph output have different retention boundaries.
- `CAP-32` **Tool activity** — Tool activity is unresolved because traces, repetition windows, and output lack durable common tool identity.
- `CAP-33` **Artifacts** — Artifacts is unresolved because commits, artifact references, and snapshots define different artifacts.
- `CAP-34` **File delta** — File delta is unresolved because snapshots and commits lack candidate-scoped before/after identity.
- `CAP-35` **Output records** — Output records is unresolved because trace, verification, artifact, and prompt outputs lack one schema.
- `CAP-36` **Usage** — Usage is unresolved because returned telemetry omits exception and non-reporting executions.
- `CAP-37` **Current failure** — Current failure is unresolved because failure states have no current-failure selector.
- `CAP-39` **Intervention alternatives** — Intervention alternatives is unresolved because action availability has no condition-specific feasibility projection.
- `CAP-40` **Expected effect** — Expected effect is unresolved because local action effects do not yield a complete consequence set.
- `CAP-41` **Intervention scope** — Intervention scope is unresolved because targets, topology, and workflow records have untyped joins.
- `CAP-45` **Validation path** — Validation path is unresolved because request, graph, and result validation are separate carriers.
- `CAP-46` **Spend and tokens by node kind** — Spend and tokens by node kind is unresolved because node-kind rollups exclude legacy, missing, and exception work.
- `CAP-53` **Routine SHA** — Routine SHA is unresolved because configuration identity does not persist one executable source SHA.
- `CAP-54` **Model and profile** — Model and profile is unresolved because defaults, runner selection, and telemetry can differ over time.
- `CAP-55` **Duration** — Duration is unresolved because start, stop, pause, and failure timestamps use different boundaries.
- `CAP-56` **Tokens** — Tokens is unresolved because token categories and telemetry coverage differ by runner and mode.
- `CAP-61` **Interventions** — Interventions is unresolved because patch, recovery, approval, merge, and lifecycle actions lack a taxonomy.
- `CAP-62` **Outcome** — Outcome is unresolved because completion, verification, merge, and node states have different finality.
- `CAP-65` **Data freshness and connection state** — Data freshness and connection state is unresolved because event freshness, connection, and UI selection have separate boundaries.
- `CAP-70` **Recorded decision identity and timestamp** — Recorded decision identity and timestamp is unresolved because clarification, approval, and graph decisions use different identities/clocks.
- `CAP-75` **Exact execution-unit identity** — Exact execution-unit identity is unresolved because attempts, nodes, executions, and usage rows are not one unit.
- `CAP-76` **Repository file-state boundary** — Repository file-state boundary is unresolved because commits, worktrees, and artifacts capture different repository moments.
- `CAP-79` **Canonical selection identity across projections** — Canonical selection identity across projections is unresolved because route, UI, run, task, attempt, and graph IDs lack typed selection joins.
- `CAP-80` **Preserve run selection time attempt and decision context** — Preserve run selection time attempt and decision context is unresolved because return state does not durably store full selection context.
- `CAP-87` **Answer a clarification** — Answer a clarification is unresolved because requests, answers, and outcomes are not consistently bound.
- `CAP-88` **Retry** — Retry is unresolved because revision, recovery, fan-out, and regeneration differ.
- `CAP-89` **Pause resume or cancel** — Pause resume or cancel is unresolved because lifecycle actions have mode-specific reachability and contradictory preservation.
- `CAP-90` **Retire or supersede a strand** — Retire or supersede a strand is unresolved because topology changes and recovery lack a durable strand/successor relation.
- `CAP-91` **Requeue failed outbox or work** — Requeue failed outbox or work is unresolved because outbox requeue and work recovery target different failure records.
- `CAP-94` **Change a routine prompt or policy** — Change a routine prompt or policy is unresolved because source edits, agent configuration, and packets are not durably bound.
- `CAP-102` **Command accepted or rejected** — Command accepted or rejected is unresolved because responses, graph events, and durable records differ in identity/coverage.
- `CAP-103` **Validation result and reason** — Validation result and reason is unresolved because validator families lack one result/reason schema.
- `CAP-104` **Durable event or record identity** — Durable event or record identity is unresolved because events, attempts, and batches use different identity/order rules.
- `CAP-105` **Resulting lifecycle topology or decision state** — Resulting lifecycle topology or decision state is unresolved because actions independently update workflow, graph, and decisions.
- `CAP-107` **Recovery path for failure or stale-state race** — Recovery path for failure or stale-state race is unresolved because retry, requeue, correction, and conflict recovery have separate contracts.
- `CAP-109` **Needs-decision classification** — Needs-decision classification is unresolved because clarification and graph wait states lack a common positive classifier.
- `CAP-114` **Settled classification** — Settled classification is unresolved because terminal states have different finality rules.
- `CAP-115` **Run region step node task attempt record event requirement identity chain** — Run region step node task attempt record event requirement identity chain is unresolved because run-step-task-attempt is enforced but region/graph-core joins are untyped.
