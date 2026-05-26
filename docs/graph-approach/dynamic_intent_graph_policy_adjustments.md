# Dynamic Intent Graph Policy Adjustments

## Purpose

This document captures the structural adjustments suggested by the feature dry run.

The dry run showed that the graph model has the right primitives. The missing pieces are not more conceptual node types. The missing pieces are deterministic policies for routing, proposal authority, evidence trust, and final acceptance.

The goal is to move from:

```text
graph + prose guidance + model judgment
```

to:

```text
graph + policy kernel + invariant checks
```

These adjustments are intended to make the dynamic graph usable by either:

1. an expensive manual orchestrator model, or
2. a future deterministic runner that applies routing and mutation rules mechanically.

---

## 1. Core Judgment From The Dry Run

The structure is sufficient as a reasoning model.

The existing model already has the necessary primitives:

- `intent`
- `requirement`
- `step`
- `task`
- `validation_definition`
- `artifact`
- `evidence`
- `proposal`
- `activity_execution`
- typed `edge`

The dry run did not reveal a missing primitive. It revealed missing policy boundaries.

The system broke down in places where the orchestrator had to decide:

- whether a requirement change was semantic or merely definitional
- whether a validation change expanded scope or only proved existing scope
- whether downstream plan regions were active, draft, or suspect
- whether evidence remained valid for a superseded requirement version
- whether gap-planner output could directly append work
- whether final acceptance should use sequence completion or invariant satisfaction

Those are policy problems, not graph-shape problems.

---

## 2. Minimum Runtime Node Set

Avoid adding many specialized node types too early.

Use a compact runtime node set and express specialization through fields such as `kind`, `subtype`, `priority`, `authority`, and `change_policy`.

```yaml
minimum_runtime_nodes:
  context_nodes:
    - intent
    - requirement
    - step
    - task
    - validation_definition
    - artifact
    - evidence
    - proposal

  activity_records:
    - activity_execution

  relationship_records:
    - edge
```

Specialized requirement types may remain useful as `subtype` values:

```yaml
requirement_subtypes:
  - api_design
  - data_consistency
  - logging_observability
  - test_strategy
  - documentation
  - security
  - performance
  - migration
  - compatibility
```

Do not make each subtype a separate runtime class unless the runner needs different lifecycle rules for it.

---

## 3. Add Explicit Task Kinds

### Problem

The dry run used `T1.2` as a discovery task, but it sat in the same structure as implementation tasks.

That created ambiguity:

- Does discovery satisfy a requirement?
- Does it only unblock a requirement?
- Does it produce evidence?
- Does it produce proposals?
- Does it route to builder, verifier, or planner?

### Adjustment

Add `task.kind`.

```yaml
task:
  id: T1.2
  type: task
  kind: discovery
  title: "Research data consistency strategy"
  status: active
  addresses: [R2]
```

### Allowed Task Kinds

```yaml
task_kinds:
  discovery:
    purpose: "Reduce an unknown through research, inspection, probing, or experiment."
    may_satisfy_requirement: false
    usual_outputs: [evidence, proposal]
    next_activity: discovery

  planning:
    purpose: "Create or revise decomposition, validation, or allocation."
    may_satisfy_requirement: false
    usual_outputs: [step, task, validation_definition, proposal]
    next_activity: planner

  implementation:
    purpose: "Modify artifacts to satisfy active requirements."
    may_satisfy_requirement: true
    usual_outputs: [artifact, evidence, proposal]
    next_activity: builder

  validation:
    purpose: "Add or improve tests, checks, or validation definitions."
    may_satisfy_requirement: true
    usual_outputs: [artifact, evidence, validation_definition, proposal]
    next_activity: builder_or_validation_runner

  documentation:
    purpose: "Produce maintainer-facing or user-facing documentation."
    may_satisfy_requirement: true
    usual_outputs: [artifact, evidence, proposal]
    next_activity: builder

  integration:
    purpose: "Combine work, run final validation, and check invariants."
    may_satisfy_requirement: true
    usual_outputs: [evidence, proposal]
    next_activity: validation_runner_or_verifier
```

### Policy

```text
Discovery tasks do not directly satisfy must requirements unless the requirement is explicitly a discovery requirement.
Discovery tasks can unblock, define, revise, or invalidate requirements by producing evidence and proposals.
```

---

## 4. Add Plan Region Status

### Problem

The planner created `S2` and `T2.2` while `R2` was still unclear.

That was useful for a dry run, but unsafe for execution. The graph needed to distinguish between:

- planned and trusted
- planned but provisional
- active but suspect
- superseded by later planning

### Adjustment

Add `plan_region.status` to steps and tasks.

```yaml
plan_region_statuses:
  draft:
    meaning: "Allowed to exist for planning visibility, but not trusted for execution."

  active:
    meaning: "Ready for execution. Required inputs are sufficiently defined."

  suspect:
    meaning: "Previously active or draft region may no longer be trustworthy. Requires review."

  stale:
    meaning: "Region was valid against an older context version. Needs refresh before use."

  superseded:
    meaning: "Replaced by a newer plan region. Retained for audit."

  abandoned:
    meaning: "No longer pursued. Retained for audit."
```

### Example

```yaml
step:
  id: S2
  title: "Core implementation"
  status: draft
  draft_reason: "R2 is blocked pending discovery."
  execution_allowed: false
```

After discovery defines `R2.v2` and impact analysis repairs the plan:

```yaml
step:
  id: S2
  status: active
  execution_allowed: true
```

### Policy

```text
A task may not enter builder execution unless:
- task.status is active
- parent step.status is active
- all must requirements it addresses are active, defined, and have validation strategy
- no blocking proposals target the task, step, or addressed must requirements
```

---

## 5. Requirement Change Classification

### Problem

The system needs a deterministic way to decide whether a requirement change requires impact analysis.

The dry run had an obvious semantic change:

```text
R2.v1: preserve data consistency, strategy unknown
R2.v2: use transactional boundary plus idempotency token
```

But many real changes will be less obvious.

### Adjustment

Add `requirement_change.classification`.

```yaml
requirement_change_classifications:
  editorial:
    impact_analysis_required: false
    examples:
      - "Fix wording without changing meaning."
      - "Clarify grammar."

  definitional:
    impact_analysis_required: optional
    examples:
      - "Make implicit acceptance criteria explicit."
      - "Name an existing validation target more clearly."

  semantic:
    impact_analysis_required: true
    examples:
      - "Change implementation strategy."
      - "Change behavior expected by user or system."
      - "Change data consistency semantics."
      - "Change safety or security expectation."
      - "Change validation meaning."

  priority_change:
    impact_analysis_required: true
    examples:
      - "Expected becomes must."
      - "Must becomes optional."

  scope_expansion:
    impact_analysis_required: true
    requires_authority: true
    examples:
      - "Add a new user-visible behavior."
      - "Add a new supported mode."

  scope_reduction:
    impact_analysis_required: true
    requires_authority: true
    examples:
      - "Remove an expected behavior."
      - "Defer a must requirement."
```

### Semantic Change Trigger List

A requirement change is semantic if it changes any of the following:

```yaml
semantic_change_triggers:
  - implementation_strategy
  - validation_semantics
  - step_allocation
  - safety_behavior
  - data_consistency_behavior
  - security_behavior
  - external_contract
  - compatibility_boundary
  - performance_obligation
  - failure_behavior
  - authority_or_priority
```

### Policy

```text
If classification is semantic, priority_change, scope_expansion, or scope_reduction:
  - preserve old requirement version
  - create new requirement version or superseding node
  - mark direct dependents suspect
  - mark old support edges stale
  - schedule impact analyzer
  - block final acceptance until impact analysis completes
```

---

## 6. Proposal Authority Matrix

### Problem

The graph allows agents to emit proposals, but the runner needs deterministic acceptance rules.

The dry run depended on judgment for proposals such as:

- define `R2.v2`
- revise `T2.2`
- strengthen `R4.v1` into `R4.v2`
- append corrective work `T3.1b`

### Adjustment

Add a proposal authority matrix.

```yaml
proposal_authority_matrix:
  add_requirement:
    proposer_allowed: [planner, verifier, gap_planner, builder]
    auto_accept: false
    required_authority: user_or_planner
    impact_analysis_default: true

  define_requirement:
    proposer_allowed: [planner, discovery, gap_planner]
    auto_accept_if: "requirement is already active but blocked/ambiguous and proposal narrows ambiguity without expanding user scope"
    required_authority: planner
    impact_analysis_default: true

  revise_requirement:
    proposer_allowed: [planner, verifier, gap_planner, impact_analyzer]
    auto_accept: false
    required_authority: planner_or_user
    impact_analysis_default: depends_on_change_classification

  strengthen_validation:
    proposer_allowed: [verifier, gap_planner, impact_analyzer, validation_runner]
    auto_accept_if: "strengthening proves an already-active must requirement and does not create new behavior scope"
    required_authority: orchestrator
    impact_analysis_default: false

  add_validation:
    proposer_allowed: [planner, verifier, gap_planner, impact_analyzer, builder]
    auto_accept_if: "validation targets an active requirement with insufficient proof"
    required_authority: orchestrator
    impact_analysis_default: false

  revise_task:
    proposer_allowed: [planner, verifier, gap_planner, impact_analyzer, builder]
    auto_accept_if: "revision keeps same requirement scope and improves alignment"
    required_authority: orchestrator
    impact_analysis_default: false

  split_task:
    proposer_allowed: [planner, builder, verifier, gap_planner]
    auto_accept_if: "split preserves scope and improves executability"
    required_authority: orchestrator
    impact_analysis_default: false

  append_corrective_work:
    proposer_allowed: [verifier, gap_planner, impact_analyzer]
    auto_accept_if: "existing work remains valid but incomplete against active requirement"
    required_authority: orchestrator
    impact_analysis_default: false

  replan_step:
    proposer_allowed: [planner, gap_planner, impact_analyzer]
    auto_accept: false
    required_authority: planner
    impact_analysis_default: true

  invalidate_assumption:
    proposer_allowed: [builder, verifier, discovery, gap_planner, impact_analyzer]
    auto_accept_if: "proposal includes direct evidence contradicting assumption"
    required_authority: orchestrator
    impact_analysis_default: true
```

### Policy

```text
A proposal may be auto-accepted only when:
- the proposer is allowed to propose that mutation
- the target node is within the proposer's authority boundary
- the change does not silently expand user scope
- required evidence is present
- required impact analysis is either not needed or has already completed
```

---

## 7. Scope Expansion vs Validation Strengthening

### Problem

The gap planner often finds that validation is too weak. Some validation improvements are merely proof improvements. Others are hidden scope expansion.

The runner must distinguish these.

### Classification

```yaml
validation_change_classification:
  proof_strengthening:
    definition: "Adds or improves proof for an already-active requirement."
    can_auto_accept: true
    examples:
      - "Add idempotency regression test for active data consistency requirement."
      - "Add negative test for documented failure behavior."
      - "Add type-check command for typed API requirement."

  scope_expansion:
    definition: "Introduces a new behavior, guarantee, supported case, or user-visible obligation."
    can_auto_accept: false
    examples:
      - "Add support for a new input mode."
      - "Require behavior that was not implied by any active requirement."
      - "Add compatibility with an unmentioned external system."

  scope_clarification:
    definition: "Makes implicit scope explicit without changing behavior."
    can_auto_accept: sometimes
    examples:
      - "Define retryable errors after discovery finds existing retry policy."
      - "Name exact event emitted for already-required observability."
```

### Decision Rule

```text
If the proposed validation proves an already-active must or expected requirement:
  classify as proof_strengthening.

If the proposed validation requires new behavior not implied by active requirements:
  classify as scope_expansion.

If unclear:
  keep as proposal and route to planner or user authority.
```

---

## 8. Routing Table

### Purpose

The orchestrator should select the next activity from graph state, not from conversational momentum.

### Deterministic Routing Table

```yaml
routing_table:
  - condition: "active must requirement is ambiguous, blocked, or unverifiable"
    next_activity: discovery_or_requirement_reconciler
    final_acceptance_allowed: false

  - condition: "requirement changed semantically"
    next_activity: impact_analyzer
    final_acceptance_allowed: false

  - condition: "impact analysis complete and plan region suspect"
    next_activity: planner
    final_acceptance_allowed: false

  - condition: "task is active, unstarted, and execution_allowed"
    next_activity: builder
    final_acceptance_allowed: false

  - condition: "builder produced artifact and auto-validation is defined but not current"
    next_activity: validation_runner
    final_acceptance_allowed: false

  - condition: "auto-validation failed"
    next_activity: builder_revision
    recovery_mode: repair_in_place
    final_acceptance_allowed: false

  - condition: "artifact and validation evidence exist but no verifier evidence exists"
    next_activity: verifier
    final_acceptance_allowed: false

  - condition: "verifier failed against unchanged requirement"
    next_activity: builder_revision
    recovery_mode: repair_in_place
    final_acceptance_allowed: false

  - condition: "verifier failed because requirement is unclear or contradictory"
    next_activity: requirement_reconciler
    recovery_mode: jump_back
    final_acceptance_allowed: false

  - condition: "verifier passed and gap analysis required but missing"
    next_activity: gap_planner
    final_acceptance_allowed: false

  - condition: "gap planner found existing work valid but incomplete"
    next_activity: planner_or_append_corrective_work
    recovery_mode: append_corrective_work
    final_acceptance_allowed: false

  - condition: "gap planner found validation too weak"
    next_activity: strengthen_validation_then_revalidate
    recovery_mode: revalidate_only_or_append_corrective_work
    final_acceptance_allowed: false

  - condition: "evidence support edge is stale for an active requirement"
    next_activity: validation_runner_or_verifier
    recovery_mode: revalidate_only
    final_acceptance_allowed: false

  - condition: "open proposal targets active requirement, step, task, validation, or evidence"
    next_activity: proposal_decision
    final_acceptance_allowed: false

  - condition: "all active requirements satisfied with current evidence and no blockers"
    next_activity: final_acceptance_check
    final_acceptance_allowed: true
```

---

## 9. Recovery Mode Decision Table

```yaml
recovery_mode_decision_table:
  repair_in_place:
    use_when:
      - "Artifact failed against unchanged requirement."
      - "Auto-validation failed for current task."
      - "Verifier gave C/D/F due to implementation defect."
    graph_actions:
      - "Mark failed artifact insufficient or invalid."
      - "Mark support edge invalid or contradicted."
      - "Create builder revision activity."
      - "Preserve failed attempt as history."

  append_corrective_work:
    use_when:
      - "Existing work is valid but incomplete."
      - "Gap planner finds missing proof or missing subcase."
      - "Requirement clarification requires additional work but does not invalidate completed work."
    graph_actions:
      - "Create new task after current work."
      - "Connect new task to active requirement."
      - "Keep prior evidence valid for what it still proves."
      - "Block final acceptance until corrective work passes."

  jump_back:
    use_when:
      - "Assumption, allocation, task decomposition, or planning decision is invalid."
      - "Verifier failure indicates the task was wrongly defined."
      - "Requirement conflict or ambiguity prevents implementation."
    graph_actions:
      - "Mark affected plan region suspect."
      - "Route to planner or requirement reconciler."
      - "Do not continue downstream execution until repaired."

  revalidate_only:
    use_when:
      - "Validation definition changed but implementation may still be valid."
      - "Evidence is stale only because command/rubric changed."
    graph_actions:
      - "Mark old support edge stale."
      - "Run validation again."
      - "Do not rebuild unless validation fails."

  full_replan:
    use_when:
      - "Intent changed."
      - "Core requirement changed enough that plan is unreliable."
      - "Multiple central assumptions invalidated."
    graph_actions:
      - "Supersede affected plan region."
      - "Create replacement steps and tasks."
      - "Preserve old region as historical."
```

---

## 10. Edge-Level Evidence Trust

### Problem

Evidence can remain historically valid while no longer supporting the current requirement version.

Example:

```text
E-V-T3.1-A1 supports R4.v1.
R4.v1 is superseded by R4.v2.
E-V-T3.1-A1 may not support R4.v2.
```

The evidence node should not necessarily become invalid. The support edge should become stale.

### Adjustment

Make support edges first-class trust records.

```yaml
support_edge:
  id: EDGE-EV-001
  from: E-V-T3.1-A1
  to: R4.v2
  type: supports
  status: stale
  trust:
    confidence: low
    stale_reason: "Evidence was produced for R4.v1 and does not prove strengthened R4.v2."
    invalid_reason: null
```

### Edge Status Semantics

```yaml
edge_statuses:
  active:
    meaning: "Relationship currently trusted."
    can_satisfy_final_acceptance: true

  stale:
    meaning: "Relationship may have been valid for an older version but is not current proof."
    can_satisfy_final_acceptance: false

  suspect:
    meaning: "Relationship may be wrong and requires review."
    can_satisfy_final_acceptance: false

  invalid:
    meaning: "Relationship is known wrong."
    can_satisfy_final_acceptance: false

  contradicted:
    meaning: "Evidence actively disproves the target claim."
    can_satisfy_final_acceptance: false

  historical:
    meaning: "Relationship is preserved for audit only."
    can_satisfy_final_acceptance: false
```

### Policy

```text
Final acceptance may only use evidence connected to active requirements through active support edges.
Evidence nodes with stale, suspect, invalid, contradicted, or historical support edges cannot satisfy active requirements.
```

---

## 11. Progress Accounting

### Problem

The original plan had three steps with three tasks each. The final dry run executed ten tasks because the gap planner appended corrective work.

A simple progress tracker would report this as plan drift or failure.

### Adjustment

Track progress in separate dimensions.

```yaml
progress_accounting:
  original_planned_tasks: 9
  active_planned_tasks: 10
  appended_corrective_tasks: 1
  failed_attempts: 1
  superseded_requirements: 2
  active_requirements_satisfied: 5
  open_proposals: 0
  stale_support_edges_blocking_acceptance: 0
```

### Recommended Metrics

```yaml
progress_metrics:
  requirement_satisfaction:
    description: "How many active requirements are satisfied with current evidence."
    primary: true

  plan_completion:
    description: "How many current active tasks are complete."
    primary: false

  corrective_work_count:
    description: "How much work was appended after planning."
    primary: false

  failed_attempt_count:
    description: "How many execution attempts failed and required repair."
    primary: false

  evidence_freshness:
    description: "Whether active requirements are supported by non-stale evidence."
    primary: true

  proposal_closure:
    description: "Whether graph mutations are still pending."
    primary: true
```

### Policy

```text
The primary completion metric is active requirement satisfaction with current evidence.
Original task count is an audit metric, not an acceptance metric.
```

---

## 12. Final Acceptance Gate

### Problem

A sequential runner may believe the feature is complete after the final task runs.

A graph runner must complete only after invariant checks pass.

### Final Acceptance Conditions

```yaml
final_acceptance_gate:
  must_pass:
    - no_active_must_requirement_unsatisfied
    - no_active_expected_requirement_unsatisfied_without_accepted_reason
    - no_active_requirement_without_source
    - no_active_requirement_without_authority
    - no_active_must_requirement_without_validation_strategy
    - no_active_requirement_satisfied_only_by_stale_evidence
    - no_active_requirement_satisfied_only_by_suspect_evidence
    - no_active_step_suspect
    - no_active_task_suspect
    - no_open_proposal_targeting_active_acceptance_path
    - no_blocked_requirement_without_accepted_blocker
    - all_semantic_changes_have_impact_analysis_or_recorded_exception
```

### Final Acceptance Output

```yaml
final_acceptance_report:
  status: pass | fail
  active_requirements:
    - id: R1
      status: satisfied
      evidence_edges: [active]
    - id: R2.v2
      status: satisfied
      evidence_edges: [active]
  blockers: []
  stale_evidence_blockers: []
  suspect_nodes: []
  open_proposals: []
  accepted_exceptions: []
```

### Policy

```text
Final acceptance is invariant-driven, not sequence-driven.
Completing the last task is not sufficient.
```

---

## 13. Gap Planner Timing

### Problem

The dry run waited until `T3.1` passed verifier before the gap planner detected that validation was too weak after `R2.v2` was defined.

That was late.

### Adjustment

Run gap planning earlier after semantic changes.

```yaml
gap_planner_required_after:
  - semantic_requirement_change
  - scope_expansion_proposal_acceptance
  - safety_relevant_discovery
  - data_consistency_discovery
  - security_relevant_discovery
  - validation_strategy_change_for_must_requirement
```

### Policy

```text
After a must requirement becomes concrete through discovery, run gap planner before downstream implementation continues if the requirement affects safety, data consistency, security, external contract, or validation semantics.
```

### Intended Effect

This catches weak validation before implementation consumes the updated graph.

---

## 14. Suggested Deterministic Policy Kernel

A minimal deterministic runner can be organized around these policy modules.

```yaml
policy_kernel:
  proposal_policy:
    responsibilities:
      - "Check proposer permission."
      - "Check required authority."
      - "Classify scope impact."
      - "Accept, reject, defer, or route proposal."

  routing_policy:
    responsibilities:
      - "Select next activity from graph state."
      - "Prefer blockers and invalidation before new execution."
      - "Prevent execution from suspect plan regions."

  invalidation_policy:
    responsibilities:
      - "Mark direct dependents suspect."
      - "Mark old support edges stale."
      - "Schedule impact analysis for semantic changes."

  evidence_policy:
    responsibilities:
      - "Determine whether evidence can satisfy an active requirement."
      - "Manage edge-level trust state."
      - "Block final acceptance on stale or suspect support."

  recovery_policy:
    responsibilities:
      - "Choose repair, append, jump back, revalidate, or full replan."
      - "Preserve failed work as history."

  invariant_policy:
    responsibilities:
      - "Check requirement, step, task, validation, evidence, and proposal invariants."
      - "Produce acceptance or blocking report."
```

---

## 15. Minimal State Machine Overlay

The graph is not a linear state machine, but activity execution can use a small overlay.

```text
READY_FOR_BUILDER
  -> BUILDER_RUNNING
  -> BUILDER_OUTPUT_READY
  -> AUTO_VALIDATION_RUNNING
  -> AUTO_VALIDATION_PASSED
  -> VERIFIER_RUNNING
  -> VERIFIER_PASSED
  -> GAP_PLANNER_RUNNING
  -> GAP_PLANNER_PASSED
  -> TASK_SATISFIED
```

Failure transitions:

```text
AUTO_VALIDATION_FAILED -> BUILDER_REVISION
VERIFIER_FAILED_IMPLEMENTATION -> BUILDER_REVISION
VERIFIER_FAILED_SPEC -> REQUIREMENT_RECONCILER
GAP_FOUND_VALIDATION_WEAK -> STRENGTHEN_VALIDATION
GAP_FOUND_WORK_INCOMPLETE -> APPEND_CORRECTIVE_WORK
CONTEXT_CHANGED -> IMPACT_ANALYSIS
EVIDENCE_STALE -> REVALIDATE
```

This overlay should not replace the graph. It only helps route the current task region.

---

## 16. Updated Orchestrator Rule Summary

```text
1. Do not execute from draft or suspect plan regions.
2. Do not treat discovery as implementation.
3. Do not let builders redefine requirements.
4. Do not let verifiers silently expand scope.
5. Do not let gap planners activate new scope without authority.
6. Auto-accept validation strengthening only when it proves an active requirement.
7. Run impact analysis after semantic requirement changes.
8. Run gap planning after safety, security, data consistency, or validation semantics change.
9. Preserve failed and superseded work as history.
10. Put evidence trust on support edges.
11. Treat original task count as an audit metric, not a completion metric.
12. Complete only through final invariant acceptance.
```

---

## 17. Practical MVP Recommendation

For the first executable version, implement only the following hard mechanics:

```yaml
mvp_mechanics:
  required_fields:
    - node.id
    - node.type
    - node.status
    - node.source
    - node.authority
    - requirement.priority
    - task.kind
    - edge.status

  required_policies:
    - proposal_authority_matrix
    - routing_table
    - invalidation_policy
    - edge_evidence_policy
    - final_acceptance_gate

  required_recovery_modes:
    - repair_in_place
    - append_corrective_work
    - jump_back
    - revalidate_only

  defer_until_later:
    - large specialized node taxonomy
    - confidence scoring across all nodes
    - complex merge resolution
    - multi-agent concurrency
    - probabilistic routing
```

The MVP should prove that the runner can safely handle:

1. an ambiguous must requirement,
2. discovery that clarifies it,
3. a semantic requirement update,
4. an implementation failure,
5. a gap-planner validation failure,
6. appended corrective work,
7. final acceptance based on invariants.

---

## 18. Bottom Line

The graph structure is sufficient.

The next layer should not be a larger graph vocabulary. It should be a policy kernel that makes the following decisions deterministic:

- what can run next
- who can propose what
- who can accept what
- what becomes stale or suspect after a change
- what recovery mode applies
- what evidence can satisfy final acceptance

The graph should remain expressive.

The runner should be strict.

