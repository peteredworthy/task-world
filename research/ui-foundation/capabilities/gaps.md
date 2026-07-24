# Capability classifications

Generated from `capabilities/registry.yaml`; do not edit by hand.

## Current (2)

- `CAP-69` **Command validator result** — The command validator result demand is current only for reachable graph patch and decision validation paths that return accepted or rejected diagnostics.
- `CAP-86` **Approve deny or defer a gate or patch** — The approve, deny, or defer a gate or patch demand is current only as split graph approval or denial and patch-validation paths; no unified defer command exists.

## Derived (12)

- `CAP-5` **Last-event age** — Last-event age is a deterministic, carrier-qualified projection for the source demand jobs.J1.last-event-age; it is not a direct product fact.
- `CAP-12` **Attempts left** — Attempts left is a deterministic, carrier-qualified projection for the source demand jobs.J2.attempts-left; it is not a direct product fact.
- `CAP-22` **Ordered events** — Ordered events is a deterministic, carrier-qualified projection for the source demand jobs.J4.ordered-events; it is not a direct product fact.
- `CAP-24` **Requirement-grade changes** — Requirement-grade changes is a deterministic, carrier-qualified projection for the source demand jobs.J4.requirement-grade-changes; it is not a direct product fact.
- `CAP-30` **Prompt size** — Prompt size is a deterministic, carrier-qualified projection for the source demand jobs.J5.prompt-size; it is not a direct product fact.
- `CAP-46` **Spend and tokens by node kind** — Spend and tokens by node kind is a deterministic, carrier-qualified projection for the source demand jobs.J7.spend-tokens-by-node-kind; it is not a direct product fact.
- `CAP-47` **Unpriced share** — Unpriced share is a deterministic, carrier-qualified projection for the source demand jobs.J7.unpriced-share; it is not a direct product fact.
- `CAP-48` **Prompt size** — Prompt size is a deterministic, carrier-qualified projection for the source demand jobs.J7.prompt-size; it is not a direct product fact.
- `CAP-57` **Price coverage** — Price coverage is a deterministic, carrier-qualified projection for the source demand jobs.J8.price-coverage; it is not a direct product fact.
- `CAP-58` **Patch count** — Patch count is a deterministic, carrier-qualified projection for the source demand jobs.J8.patch-count; it is not a direct product fact.
- `CAP-59` **Retry count** — Retry count is a deterministic, carrier-qualified projection for the source demand jobs.J8.retries; it is not a direct product fact.
- `CAP-68` **Decision wait age** — Decision wait age is a deterministic, carrier-qualified projection for the source demand journeys.B.wait-age; it is not a direct product fact.

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

## Gap (39)

- `CAP-1` **Health class** — Health class is a source demand from jobs.J1.health-class; the audited implementation does not provide the demanded capability contract.
- `CAP-6` **Budget pace** — Budget pace is a source demand from jobs.J1.budget-pace; the audited implementation does not provide the demanded capability contract.
- `CAP-7` **Blast radius** — Blast radius is a source demand from jobs.J1.blast-radius; the audited implementation does not provide the demanded capability contract.
- `CAP-10` **Planner horizon** — Planner horizon is a source demand from jobs.J2.planner-horizon; the audited implementation does not provide the demanded capability contract.
- `CAP-13` **Final-invariant progress** — Final-invariant progress is a source demand from jobs.J2.final-invariant-progress; the audited implementation does not provide the demanded capability contract.
- `CAP-17` **Affected scope** — Affected scope is a source demand from jobs.J3.affected-scope; the audited implementation does not provide the demanded capability contract.
- `CAP-20` **Downstream effect** — Downstream effect is a source demand from jobs.J3.downstream-effect; the audited implementation does not provide the demanded capability contract.
- `CAP-21` **Reversibility** — Reversibility is a source demand from jobs.J3.reversibility; the audited implementation does not provide the demanded capability contract.
- `CAP-38` **Retry information delta** — Retry information delta is a source demand from jobs.J6.retry-information-delta; the audited implementation does not provide the demanded capability contract.
- `CAP-42` **Authority** — Authority is a source demand from jobs.J6.authority; the audited implementation does not provide the demanded capability contract.
- `CAP-43` **Intervention budget** — Intervention budget is a source demand from jobs.J6.budget; the audited implementation does not provide the demanded capability contract.
- `CAP-44` **Intervention reversibility** — Intervention reversibility is a source demand from jobs.J6.reversibility; the audited implementation does not provide the demanded capability contract.
- `CAP-49` **Retries without new information** — Retries without new information is a source demand from jobs.J7.retries-without-new-information; the audited implementation does not provide the demanded capability contract.
- `CAP-50` **Repeated tools and work** — Repeated tools and work is a source demand from jobs.J7.repeated-work; the audited implementation does not provide the demanded capability contract.
- `CAP-51` **Verifier churn** — Verifier churn is a source demand from jobs.J7.verifier-churn; the audited implementation does not provide the demanded capability contract.
- `CAP-52` **Comparable cohort** — Comparable cohort is a source demand from jobs.J8.comparable-cohort; the audited implementation does not provide the demanded capability contract.
- `CAP-60` **Grade churn** — Grade churn is a source demand from jobs.J8.grade-churn; the audited implementation does not provide the demanded capability contract.
- `CAP-63` **Prompt pressure** — Prompt pressure is a source demand from jobs.J7.prompt-pressure; the audited implementation does not provide the demanded capability contract.
- `CAP-64` **Final-gate effect** — Final-gate effect is a source demand from design.initial-claims.final-gate-effect; the audited implementation does not provide the demanded capability contract.
- `CAP-66` **Explicit empty needs-you state** — Explicit empty needs-you state is a source demand from journeys.A.positive-empty-needs-you; the audited implementation does not provide the demanded capability contract.
- `CAP-67` **No runaway signal** — No runaway signal is a source demand from journeys.A.no-runaway-signal; the audited implementation does not provide the demanded capability contract.
- `CAP-71` **Cost of another attempt** — Cost of another attempt is a source demand from journeys.C.cost-of-another-attempt; the audited implementation does not provide the demanded capability contract.
- `CAP-72` **Candidate delta** — Candidate delta is a source demand from journeys.C.candidate-delta; the audited implementation does not provide the demanded capability contract.
- `CAP-73` **Causal gap** — Causal gap is a source demand from journeys.C.causal-gap; the audited implementation does not provide the demanded capability contract.
- `CAP-74` **Directive binding** — Directive binding is a source demand from journeys.C.directive-binding; the audited implementation does not provide the demanded capability contract.
- `CAP-77` **Missing node attribution** — Missing node attribution is a source demand from journeys.E.missing-node-attribution; the audited implementation does not provide the demanded capability contract.
- `CAP-78` **Detector drill-through evidence** — Detector drill-through evidence is a source demand from journeys.E.detector-evidence; the audited implementation does not provide the demanded capability contract.
- `CAP-81` **Restore prior ranking filter and scroll position** — Restore prior ranking filter and scroll position is a source demand from journeys.continuity.restore-return-state; the audited implementation does not provide the demanded capability contract.
- `CAP-85` **Ignore or keep watching** — Ignore or keep watching is a source demand from decisions.ignore-watch; the audited implementation does not provide the demanded capability contract.
- `CAP-92` **Steer with new context** — Steer with new context is a source demand from decisions.steer-context; the audited implementation does not provide the demanded capability contract.
- `CAP-93` **Apply a steering patch** — Apply a steering patch is a source demand from decisions.apply-steering-patch; the audited implementation does not provide the demanded capability contract.
- `CAP-106` **Next expected system activity** — Next expected system activity is a source demand from feedback.next-activity; the audited implementation does not provide the demanded capability contract.
- `CAP-108` **Evidence convergence** — Evidence convergence is a source demand from ia.health.evidence-convergence; the audited implementation does not provide the demanded capability contract.
- `CAP-110` **Degraded classification** — Degraded classification is a source demand from ia.health.degraded; the audited implementation does not provide the demanded capability contract.
- `CAP-111` **Stalled classification** — Stalled classification is a source demand from ia.health.stalled; the audited implementation does not provide the demanded capability contract.
- `CAP-112` **Runaway classification** — Runaway classification is a source demand from ia.health.runaway; the audited implementation does not provide the demanded capability contract.
- `CAP-113` **Steered classification** — Steered classification is a source demand from ia.health.steered; the audited implementation does not provide the demanded capability contract.
- `CAP-116` **Active comparison target** — Active comparison target is a source demand from ia.selection.comparison-target; the audited implementation does not provide the demanded capability contract.
- `CAP-117` **Freshness and capability annotations persist with selection** — Freshness and capability annotations persist with selection is a source demand from ia.selection.freshness-annotations; the audited implementation does not provide the demanded capability contract.

## Unknown (54)

- `CAP-2` **Current constraint** — Current constraint is demanded by jobs.J1.current-constraint, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-3` **Human wait state** — Human wait state is demanded by jobs.J1.human-wait-state, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-4` **Frontier activity** — Frontier activity is demanded by jobs.J1.frontier-activity, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-8` **Active nodes and steps** — Active nodes and steps is demanded by jobs.J2.active-nodes-steps, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-9` **Dependency path** — Dependency path is demanded by jobs.J2.dependency-path, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-11` **Blocked reason** — Blocked reason is demanded by jobs.J2.blocked-reason, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-14` **Exact question** — Exact question is demanded by jobs.J3.exact-question, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-15` **Why now** — Why now is demanded by jobs.J3.why-now, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-16` **Proposer** — Proposer is demanded by jobs.J3.proposer, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-18` **Decision evidence** — Decision evidence is demanded by jobs.J3.evidence, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-19` **Alternatives** — Alternatives is demanded by jobs.J3.alternatives, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-23` **Attempt lineage** — Attempt lineage is demanded by jobs.J4.attempt-lineage, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-25` **Patch provenance** — Patch provenance is demanded by jobs.J4.patch-provenance, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-26` **State transitions** — State transitions is demanded by jobs.J4.state-transitions, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-27` **Retries and rejections** — Retries and rejections is demanded by jobs.J4.retries-rejections, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-28` **Bound input records** — Bound input records is demanded by jobs.J5.bound-input-records, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-29` **Omitted and referenced context** — Omitted and referenced context is demanded by jobs.J5.omitted-referenced-context, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-31` **Transcript** — Transcript is demanded by jobs.J5.transcript, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-32` **Tool activity** — Tool activity is demanded by jobs.J5.tools, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-33` **Artifacts** — Artifacts is demanded by jobs.J5.artifacts, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-34` **File delta** — File delta is demanded by jobs.J5.file-delta, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-35` **Output records** — Output records is demanded by jobs.J5.output-records, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-36` **Usage** — Usage is demanded by jobs.J5.usage, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-37` **Current failure** — Current failure is demanded by jobs.J6.current-failure, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-39` **Intervention alternatives** — Intervention alternatives is demanded by jobs.J6.alternatives, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-40` **Expected effect** — Expected effect is demanded by jobs.J6.expected-effect, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-41` **Intervention scope** — Intervention scope is demanded by jobs.J6.scope, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-45` **Validation path** — Validation path is demanded by jobs.J6.validation-path, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-53` **Routine SHA** — Routine SHA is demanded by jobs.J8.routine-sha, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-54` **Model and profile** — Model and profile is demanded by jobs.J8.model-profile, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-55` **Duration** — Duration is demanded by jobs.J8.duration, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-56` **Tokens** — Tokens is demanded by jobs.J8.tokens, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-61` **Interventions** — Interventions is demanded by jobs.J8.interventions, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-62` **Outcome** — Outcome is demanded by jobs.J8.outcome, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-65` **Data freshness and connection state** — Data freshness and connection state is demanded by journeys.A.freshness-and-connection, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-70` **Recorded decision identity and timestamp** — Recorded decision identity and timestamp is demanded by journeys.B.recorded-identity-timestamp, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-75` **Exact execution-unit identity** — Exact execution-unit identity is demanded by journeys.D.execution-unit-identity, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-76` **Repository file-state boundary** — Repository file-state boundary is demanded by journeys.D.file-state-boundary, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-79` **Canonical selection identity across projections** — Canonical selection identity across projections is demanded by journeys.continuity.canonical-selection, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-80` **Preserve run selection time attempt and decision context** — Preserve run selection time attempt and decision context is demanded by journeys.continuity.preserve-context, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-87` **Answer a clarification** — Answer a clarification is demanded by decisions.answer-clarification, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-88` **Retry** — Retry is demanded by decisions.retry, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-89` **Pause resume or cancel** — Pause resume or cancel is demanded by decisions.lifecycle, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-90` **Retire or supersede a strand** — Retire or supersede a strand is demanded by decisions.retire-supersede, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-91` **Requeue failed outbox or work** — Requeue failed outbox or work is demanded by decisions.requeue, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-94` **Change a routine prompt or policy** — Change a routine prompt or policy is demanded by decisions.change-source, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-102` **Command accepted or rejected** — Command accepted or rejected is demanded by feedback.command-accepted-rejected, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-103` **Validation result and reason** — Validation result and reason is demanded by feedback.validation-result-reason, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-104` **Durable event or record identity** — Durable event or record identity is demanded by feedback.durable-identity, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-105` **Resulting lifecycle topology or decision state** — Resulting lifecycle topology or decision state is demanded by feedback.resulting-state, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-107` **Recovery path for failure or stale-state race** — Recovery path for failure or stale-state race is demanded by feedback.failure-race-recovery, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-109` **Needs-decision classification** — Needs-decision classification is demanded by ia.health.needs-decision, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-114` **Settled classification** — Settled classification is demanded by ia.health.settled, but available carriers are partial, carrier-specific, or disputed and do not establish the demanded semantics.
- `CAP-115` **Run region step node task attempt record event requirement identity chain** — The demanded complete selection identity chain is unknown: only run to step to task to attempt is enforced, while region and graph or core joins remain untyped.
