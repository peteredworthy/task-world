# Dynamic Intent Graph Dry Run Model

## Purpose

This document defines a dry-run model for solving software issues through a governed, mutable graph of intent, requirements, context, activity, evidence, and proposals.

The goal is to make the constructs usable before building a mechanistic orchestrator. An expensive model can act as the orchestrator by maintaining graph state in files, invoking sub-agents with generated packets, collecting their outputs, and applying the rules in this document.

Core framing:

> Activity nodes should not remember. They read the graph, act, and emit evidence or proposed changes. The graph remembers.

---

## 1. Core Model

The workflow is not a tree of tasks. It is a governed, mutable graph.

```text
Intent
  -> Requirements
      -> Assumptions
      -> Decisions
      -> Validation definitions
      -> Step allocations
          -> Tasks
              -> Activity executions
              -> Artifacts
              -> Evidence
```

The graph contains two major kinds of node:

1. **Context nodes**: stateful records that define what is true, required, assumed, decided, constrained, planned, or verified.
2. **Activity nodes**: stateless executable behaviors that consume context and produce evidence, artifacts, or proposals.

The graph itself owns state through context nodes and typed edges. Activity nodes do not own persistent state.

---

## 2. Definitions

### Graph

The source of truth for the routine. It contains nodes, edges, node versions, statuses, proposals, evidence, and activity execution history.

The graph answers:

- What is the intent?
- What requirements are active?
- Where did each requirement come from?
- Who has authority to change it?
- Which steps and tasks address it?
- Which validation proves it?
- Which evidence supports it?
- Which nodes are valid, suspect, stale, blocked, superseded, or complete?

### Context Node

A stateful record. It does not execute. It holds durable meaning.

Examples:

- Intent
- Requirement
- Assumption
- Decision
- Constraint
- Step
- Task
- Validation requirement
- Validation definition
- Test strategy
- Documentation requirement
- Evidence
- Artifact
- Proposal

### Activity Type

A stateless reusable behavior definition.

Examples:

- Planner
- Builder
- Verifier
- Gap planner
- Impact analyzer
- Validation runner
- Requirement reconciler
- Merge resolver

An activity type defines:

- Prompt template
- Allowed tools
- Allowed input context types
- Allowed outputs
- Proposal permissions
- Child creation permissions
- Routing behavior

### Activity Execution

A historical event saying an activity type was run with a specific graph snapshot and produced specific outputs.

Activity executions are records, not agents with memory.

### Evidence Node

A durable observation or result.

Examples:

- Test output
- Type-check output
- Verifier grade
- Build log
- Diff summary
- Human clarification
- API probe result
- Gap report

Evidence may become stale without being deleted.

### Proposal Node

A pending request to mutate the graph.

Examples:

- Add requirement
- Define requirement
- Revise requirement
- Add validation
- Define validation
- Add step
- Define step
- Add task
- Define task
- Invalidate assumption
- Strengthen validation
- Split task
- Replan step

A proposal is not automatically accepted. The orchestrator applies policy.

### Edge

A typed relationship between nodes. Edges may have their own state.

Examples:

- `depends_on`
- `addresses`
- `satisfies`
- `supports`
- `invalidates`
- `supersedes`
- `consumes`
- `produces`
- `allocated_to`
- `derived_from`
- `conflicts_with`

Many trust states belong on edges rather than nodes. For example, evidence can still be historically valid while the edge saying it supports a clarified requirement becomes stale.

---

## 3. Fundamental Rules

1. Activity nodes are stateless.
2. Context nodes hold state.
3. Edges hold relationship state.
4. Agents do not directly mutate active graph state unless their activity type grants that authority.
5. Agents may emit proposals.
6. The orchestrator applies or rejects proposals according to policy.
7. New requirements start as proposed unless created by an authority with explicit permission.
8. Every active requirement must have source, authority, priority, allocation, and verification.
9. Direct dependency invalidation is automatic.
10. Lateral impact invalidation is planned.
11. Invalidation does not delete nodes. It changes trust state.
12. Final acceptance requires all active must and expected requirements to be satisfied, rejected, deferred with authority, or blocked with accepted reason.

---

## 4. Graph Starting State

A routine instance starts small.

```yaml
routine_instance:
  id: ROUTINE-001
  status: active

  nodes:
    - id: ROOT
      type: routine_root
      class: context
      status: active

    - id: I0
      type: intent
      class: context
      status: active
      source:
        type: initial_request
      body: "Solve the user's issue."

    - id: A0
      type: activity_execution
      activity_type: initial_planner
      status: pending
      consumes: [I0]

  edges:
    - from: ROOT
      to: I0
      type: contains

    - from: I0
      to: A0
      type: consumed_by
```

The routine definition supplies the graph grammar: node type definitions, allowed edges, allowed proposal types, and routing rules.

The initial planner expands the graph by proposing or creating requirement, discovery, validation, step, task, and implementation-loop nodes.

---

## 5. Node Class Taxonomy

### Context Classes

```yaml
context_classes:
  intent:
    purpose: "Preserve the user's goal and success meaning."

  requirement:
    purpose: "A traceable obligation that must be satisfied or explicitly resolved."

  assumption:
    purpose: "A belief used by planning or implementation that may later be invalidated."

  decision:
    purpose: "A selected approach, tradeoff, or structural choice."

  constraint:
    purpose: "A limitation or rule that bounds valid solutions."

  validation_requirement:
    purpose: "What must be proven."

  validation_definition:
    purpose: "How something can be proven."

  test_strategy:
    purpose: "The testing approach, coverage goals, and validation philosophy."

  step:
    purpose: "A planned satisfaction boundary for a group of requirements."

  task:
    purpose: "A scoped implementation or verification unit inside a step."

  artifact:
    purpose: "Produced material, such as code, docs, config, or generated files."

  evidence:
    purpose: "Observation used to support or reject trust in graph state."

  proposal:
    purpose: "A requested graph mutation awaiting policy decision."
```

### Activity Classes

```yaml
activity_classes:
  planner:
    purpose: "Construct or revise the graph."

  discovery:
    purpose: "Reduce unknowns through inspection, research, or experiments."

  builder:
    purpose: "Produce or modify artifacts to satisfy task requirements."

  verifier:
    purpose: "Grade artifacts and evidence against explicit requirements."

  gap_planner:
    purpose: "Check whether the explicit requirements and verification are sufficient for the intent."

  impact_analyzer:
    purpose: "Assess direct and lateral impact of a changed context node."

  validation_runner:
    purpose: "Run defined validation commands and record evidence."

  requirement_reconciler:
    purpose: "Resolve conflicts, ambiguity, duplication, or scope issues between requirements."

  merge_resolver:
    purpose: "Resolve branch or artifact integration conflicts."
```

---

## 6. Node Type Definition Schema

Node type definitions describe what kinds of graph growth are valid.

```yaml
node_type_definition:
  id: string
  class: context | activity
  subclass: string | null
  description: string

  lifecycle:
    allowed_statuses:
      - proposed
      - active
      - pending
      - running
      - complete
      - satisfied
      - blocked
      - suspect
      - stale
      - invalid
      - superseded
      - rejected
      - abandoned
      - historical
    initial_status: proposed | active | pending

  structure:
    allowed_parents: [node_type_id]
    allowed_children: [node_type_id]
    required_incoming_edges: [edge_type]
    allowed_outgoing_edges: [edge_type]

  permissions:
    may_create: [node_type_id]
    may_propose: [proposal_type]
    may_modify: [node_type_id]
    may_invalidate: [node_type_id]
    may_mark_suspect: [node_type_id]

  prompts:
    prompt_template: string | null
    packet_sections: [string]

  tools:
    allowed_tools: [tool_id]

  inputs:
    required_context_types: [node_type_id]
    optional_context_types: [node_type_id]

  outputs:
    allowed_output_types: [node_type_id]
    required_output_types: [node_type_id]

  change_policy:
    on_change:
      direct_dependents: mark_suspect | mark_stale | invalidate | none
      lateral_review: none | optional | required
      impact_activity: activity_type_id | null

  routing_policy:
    on_blocked: route_id
    on_invalid: route_id
    on_suspect: route_id
    on_stale_evidence: route_id
```

---

## 7. Context Node Schema

```yaml
context_node:
  id: string
  type: node_type_id
  class: context
  version: integer
  title: string
  body: string | object

  status: proposed | active | satisfied | blocked | suspect | stale | invalid | superseded | rejected | abandoned | historical

  source:
    type: initial_request | user_clarification | planning | discovery | builder_discovery | verifier_feedback | gap_analysis | auto_check | integration | external_constraint | replanning
    origin_node: node_id | null
    origin_activity: activity_execution_id | null
    parent_context: node_id | null
    rationale: string
    evidence_refs: [node_id]

  authority:
    owner: user | planner | orchestrator | verifier | gap_planner | external | unknown
    can_accept: [role_or_activity_type]
    can_modify: [role_or_activity_type]
    can_reject: [role_or_activity_type]
    requires_approval_to_change: boolean

  scope:
    level: routine | feature | step | task | artifact | validation | global
    applies_to: [node_id]
    excludes: [node_id]

  relationships:
    depends_on: [node_id]
    conflicts_with: [node_id]
    supersedes: [node_id]
    superseded_by: node_id | null
    derived_from: [node_id]

  verification:
    criteria: [string]
    validation_requirements: [node_id]
    validation_definitions: [node_id]
    rubric_refs: [string]
    evidence_refs: [node_id]
    evidence_status: none | partial | sufficient | stale | contradicted

  lifecycle_history:
    - timestamp: string
      event: string
      actor: string
      reason: string
      evidence_refs: [node_id]
```

---

## 8. Requirement Node Schema

Requirements deserve a stricter schema because they govern routing, verification, and completion.

```yaml
requirement_node:
  id: R1
  type: requirement
  class: context
  version: 1
  title: string
  desc: string

  priority: must | expected | optional
  status: proposed | active | satisfied | blocked | suspect | invalid | superseded | rejected | deferred

  source:
    type: initial_request | planning | discovery | builder_discovery | verifier_feedback | gap_analysis | integration | external_constraint | replanning
    origin_node: node_id | null
    origin_activity: activity_execution_id | null
    parent_requirement: requirement_id | null
    rationale: string
    evidence_refs: [node_id]

  authority:
    owner: user | planner | orchestrator | external
    can_accept: [user, planner, orchestrator]
    can_modify: [user, planner]
    can_reject: [user, planner]
    requires_approval_to_change: true

  allocation:
    addressed_by_steps: [step_id]
    satisfied_by_steps: [step_id]
    contributing_tasks: [task_id]
    satisfying_tasks: [task_id]

  verification:
    criteria:
      - string
    validation_requirements: [validation_requirement_id]
    validation_definitions: [validation_definition_id]
    auto_checks: [command_id]
    rubric_refs: [rubric_id]
    evidence_refs: [evidence_id]

  routing:
    if_blocked: route_id
    if_ambiguous: route_id
    if_conflicting: route_id
    if_unverifiable: route_id
    if_too_large: route_id
    if_impossible: route_id

  change_policy:
    on_clarified:
      direct_dependents: mark_suspect
      lateral_review: required
      impact_activity: impact_analyzer
    on_rejected:
      direct_dependents: mark_suspect
      lateral_review: optional
    on_superseded:
      evidence_edges: mark_stale
      dependents: mark_suspect
```

---

## 9. Validation Schemas

Validation should be split into four separate concepts.

### Validation Requirement

What must be proven.

```yaml
validation_requirement:
  id: VR1
  type: validation_requirement
  class: context
  title: "Retry behavior must be proven."
  body:
    target_requirements: [R3]
    proof_goal: "Show transient failures are retried and permanent failures are not retried."
    required_for_completion: true
  status: active
```

### Validation Definition

How it can be proven.

```yaml
validation_definition:
  id: VD1
  type: validation_definition
  class: context
  title: "Retry behavior tests"
  body:
    command_id: retry_tests
    command: "uv run pytest tests/test_retry.py -q"
    must: true
    artifact_dir: "run/evidence"
    tail_lines: 100
  validates: [VR1, R3]
  status: active
```

### Validation Execution

The act of running the validation.

```yaml
activity_execution:
  id: ACT-VALIDATE-1
  type: activity_execution
  activity_type: validation_runner
  status: complete
  consumed: [VD1, R3]
  produced: [E1]
```

### Validation Evidence

The result of running it.

```yaml
evidence_node:
  id: E1
  type: evidence
  class: context
  title: "retry_tests passed"
  body:
    command_id: retry_tests
    status: pass
    stdout_path: "run/evidence/retry_tests.stdout.log"
    stderr_path: "run/evidence/retry_tests.stderr.log"
  supports: [R3, VR1]
  status: active
```

---

## 10. Edge Schema

```yaml
edge:
  id: EDGE-001
  from: node_id
  to: node_id
  type: contains | depends_on | addresses | satisfies | contributes_to | verifies | supports | contradicts | consumes | produces | supersedes | invalidates | allocated_to | derived_from | conflicts_with

  status: active | stale | suspect | invalid | historical

  source:
    origin_activity: activity_execution_id | null
    reason: string
    evidence_refs: [node_id]

  trust:
    confidence: none | low | medium | high
    stale_reason: string | null
    invalid_reason: string | null

  history:
    - timestamp: string
      event: string
      reason: string
```

---

## 11. Proposal Schema

```yaml
proposal_node:
  id: P1
  type: proposal
  class: context
  proposal_type: add_requirement | define_requirement | revise_requirement | split_requirement | merge_requirements | add_validation | define_validation | revise_validation | strengthen_validation | add_step | define_step | revise_step | split_step | add_task | define_task | revise_task | split_task | invalidate_assumption | add_decision | revise_decision | replan_step | append_corrective_work

  status: proposed | accepted | rejected | deferred | merged | superseded

  proposed_by:
    activity_execution: activity_execution_id
    activity_type: planner | builder | verifier | gap_planner | impact_analyzer | validation_runner

  target:
    node_id: node_id | null
    edge_id: edge_id | null

  reason: string

  proposed_change:
    before: object | null
    after: object

  impact_claim:
    direct_impacts: [node_id]
    possible_lateral_impacts: [node_id]
    requires_impact_analysis: boolean
    suggested_recovery_mode: repair_in_place | jump_back | append_corrective_work | full_replan | revalidate_only

  acceptance_policy:
    required_authority: user | planner | orchestrator | external
    auto_accept_if: string | null
    reject_if: string | null

  decision:
    decided_by: string | null
    decision_reason: string | null
    resulting_events: [string]
```

---

## 12. Activity Execution Schema

```yaml
activity_execution:
  id: ACT1
  type: activity_execution
  activity_type: planner | discovery | builder | verifier | gap_planner | impact_analyzer | validation_runner | requirement_reconciler | merge_resolver

  status: pending | running | complete | failed | abandoned

  objective: string

  consumed:
    context_nodes: [node_id]
    evidence_nodes: [node_id]
    artifacts: [node_id]

  produced:
    context_nodes: [node_id]
    evidence_nodes: [node_id]
    proposals: [node_id]
    artifacts: [node_id]
    activity_nodes: [node_id]

  prompt_packet_path: string | null
  output_path: string | null

  result_summary: string

  policy_notes:
    allowed_tools_used: [tool_id]
    disallowed_actions_attempted: [string]

  history:
    - timestamp: string
      event: string
      details: string
```

---

## 13. Activity Type Definitions

### Initial Planner

```yaml
activity_type:
  id: initial_planner
  class: activity
  description: "Extract intent, requirements, unknowns, validation needs, and initial execution structure."

  tools:
    allowed_tools: [read_files, search_repo, graph.propose]

  inputs:
    required_context_types: [intent]
    optional_context_types: [constraint, external_context]

  outputs:
    allowed_output_types:
      - requirement
      - assumption
      - decision
      - validation_requirement
      - validation_definition
      - step
      - task
      - proposal
      - activity_execution

  permissions:
    may_create:
      - requirement
      - assumption
      - decision
      - validation_requirement
      - validation_definition
      - step
      - task
      - activity_execution
    may_propose:
      - add_requirement
      - define_requirement
      - add_validation
      - define_validation
      - add_step
      - define_step
      - add_task
      - define_task

  required_checks_before_completion:
    - every_active_requirement_has_source
    - every_must_requirement_has_allocation
    - every_must_requirement_has_validation_strategy
    - every_step_has_completion_boundary
```

### Planner

```yaml
activity_type:
  id: planner
  class: activity
  description: "Construct, revise, or extend the graph while preserving intent."

  tools:
    allowed_tools: [read_graph, read_files, search_repo, graph.propose]

  inputs:
    required_context_types: [intent, requirement]
    optional_context_types: [assumption, decision, validation_requirement, validation_definition, evidence, proposal]

  outputs:
    allowed_output_types: [requirement, assumption, decision, validation_requirement, validation_definition, step, task, proposal, activity_execution]

  permissions:
    may_create: [step, task, activity_execution, decision, assumption]
    may_propose: [add_requirement, define_requirement, revise_requirement, split_requirement, merge_requirements, add_validation, define_validation, add_step, define_step, add_task, define_task, replan_step, append_corrective_work]
    may_modify: [step, task, decision, assumption]
```

### Builder

```yaml
activity_type:
  id: builder
  class: activity
  description: "Modify artifacts to satisfy task-scoped requirements."

  tools:
    allowed_tools: [read_files, edit_files, run_commands, verify.run, graph.propose]

  inputs:
    required_context_types: [intent, requirement, task, validation_definition]
    optional_context_types: [assumption, decision, constraint, prior_evidence, verifier_feedback]

  outputs:
    allowed_output_types: [artifact, evidence, proposal]

  permissions:
    may_create: [artifact, evidence]
    may_propose: [add_requirement, define_requirement, add_validation, define_validation, split_task, revise_task, invalidate_assumption]
    may_modify: []

  restrictions:
    - "Must not silently redefine requirements."
    - "Must emit a proposal if implementation reality changes the plan."
    - "Must provide evidence for completed work."
```

### Verifier

```yaml
activity_type:
  id: verifier
  class: activity
  description: "Grade artifacts and evidence against explicit requirements."

  tools:
    allowed_tools: [read_files, read_graph, run_commands, verify.submit, graph.propose]

  inputs:
    required_context_types: [requirement, task, artifact, evidence]
    optional_context_types: [intent, validation_definition, grading_guidelines]

  outputs:
    allowed_output_types: [evidence, proposal]

  permissions:
    may_create: [evidence]
    may_propose: [revise_requirement, add_validation, strengthen_validation, revise_task, append_corrective_work]
    may_invalidate: [artifact, evidence]

  restrictions:
    - "Can invalidate builder output against existing requirements."
    - "Can propose new or revised requirements."
    - "Cannot silently expand scope."
```

### Gap Planner

```yaml
activity_type:
  id: gap_planner
  class: activity
  description: "Check whether the explicit requirements, plan, validation, and verifier judgment are sufficient for the intent."

  tools:
    allowed_tools: [read_graph, read_files, graph.propose]

  inputs:
    required_context_types: [intent, requirement, step, task, evidence]
    optional_context_types: [artifact, verifier_feedback, validation_definition, assumption, decision]

  outputs:
    allowed_output_types: [evidence, proposal, activity_execution]

  permissions:
    may_create: [evidence]
    may_propose: [add_requirement, define_requirement, revise_requirement, add_validation, define_validation, strengthen_validation, add_step, define_step, add_task, define_task, replan_step, append_corrective_work]
    may_mark_suspect: [verifier, builder, evidence, task, step]

  restrictions:
    - "Should detect missing intent coverage."
    - "Should distinguish actual gaps from optional expansion."
    - "Should not automatically accept its own scope-expanding requirements unless explicitly authorized."
```

### Impact Analyzer

```yaml
activity_type:
  id: impact_analyzer
  class: activity
  description: "Analyze direct and lateral impact of a changed context node."

  tools:
    allowed_tools: [read_graph, graph.propose]

  inputs:
    required_context_types: [changed_context_node]
    optional_context_types: [requirement, step, task, validation_definition, evidence, assumption, decision]

  outputs:
    allowed_output_types: [evidence, proposal]

  permissions:
    may_create: [evidence]
    may_propose: [revise_requirement, revise_step, revise_task, strengthen_validation, replan_step, append_corrective_work]

  required_output:
    - impact_set
    - unaffected_set
    - suspect_set
    - recovery_plan
```

### Validation Runner

```yaml
activity_type:
  id: validation_runner
  class: activity
  description: "Run validation definitions and record evidence."

  tools:
    allowed_tools: [run_commands, read_artifacts]

  inputs:
    required_context_types: [validation_definition]
    optional_context_types: [artifact, requirement]

  outputs:
    allowed_output_types: [evidence]

  permissions:
    may_create: [evidence]
    may_propose: [revise_validation, strengthen_validation]
```

---

## 14. Common Context Node Types

### API Design Requirement

```yaml
node_type:
  id: api_design_requirement
  class: context
  subclass: requirement
  description: "Requirement governing API shape, contract, routes, schemas, compatibility, or client behavior."
  change_policy:
    on_change:
      direct_dependents: mark_suspect
      lateral_review: required
      impact_activity: impact_analyzer
```

### Data Consistency Requirement

```yaml
node_type:
  id: data_consistency_requirement
  class: context
  subclass: requirement
  description: "Requirement governing correctness, idempotency, migrations, concurrency, transactions, or data preservation."
  change_policy:
    on_change:
      direct_dependents: mark_suspect
      lateral_review: required
      impact_activity: impact_analyzer
```

### Logging and Observability Requirement

```yaml
node_type:
  id: logging_observability_requirement
  class: context
  subclass: requirement
  description: "Requirement governing logs, metrics, traces, alerts, or debuggability."
  change_policy:
    on_change:
      direct_dependents: mark_suspect
      lateral_review: optional
      impact_activity: impact_analyzer
```

### Test Strategy

```yaml
node_type:
  id: test_strategy
  class: context
  subclass: validation_context
  description: "Defines testing approach, coverage goals, risk areas, and limits of automatic verification."
  change_policy:
    on_change:
      direct_dependents: mark_stale
      lateral_review: optional
      impact_activity: impact_analyzer
```

### Existing Validation Command

```yaml
node_type:
  id: existing_validation_command
  class: context
  subclass: validation_definition
  description: "Reusable command definition for automatic verification."
  change_policy:
    on_change:
      direct_dependents: mark_stale
      lateral_review: none
      impact_activity: validation_runner
```

### Step Ordering Rule

```yaml
node_type:
  id: step_ordering_rule
  class: context
  subclass: planning_constraint
  description: "Constraint that defines required ordering between steps."
  change_policy:
    on_change:
      direct_dependents: mark_suspect
      lateral_review: required
      impact_activity: impact_analyzer
```

### Documentation Requirement

```yaml
node_type:
  id: documentation_requirement
  class: context
  subclass: requirement
  description: "Requirement governing user-facing or maintainer-facing documentation."
  change_policy:
    on_change:
      direct_dependents: mark_suspect
      lateral_review: optional
      impact_activity: impact_analyzer
```

---

## 15. Implementation Loop Pattern

The common loop is planned as graph expansion.

```text
Planner
  -> Builder
  -> Verifier
  -> Gap Planner
```

The planner creates an implementation attempt bundle:

```yaml
implementation_attempt:
  id: IA1
  type: implementation_attempt
  class: context
  objective: "Implement requirement R3 within step S2."
  addresses: [R3]
  status: active

activity_executions:
  - id: B1
    activity_type: builder
    consumes: [I0, R3, S2, T1]
    produces: [artifact, evidence, proposal]

  - id: V1
    activity_type: verifier
    depends_on: [B1]
    consumes: [R3, artifact, evidence]
    produces: [verification_evidence, proposal]

  - id: G1
    activity_type: gap_planner
    depends_on: [V1]
    consumes: [I0, R3, S2, T1, artifact, verification_evidence]
    produces: [gap_evidence, proposal]
```

### Verifier Failure

If verifier invalidates builder output against unchanged requirements:

```text
Recovery mode: repair in place
```

Graph action:

```yaml
result:
  mark:
    artifact: invalid_or_insufficient
    builder_output_edge: invalid
  add:
    - builder_revision_activity
    - verifier_activity_after_revision
```

### Gap Planner Failure

If gap planner finds the verifier passed work that does not satisfy intent:

```text
Recovery mode depends on classification
```

Possible actions:

```yaml
possible_recovery:
  - strengthen_validation_and_revalidate
  - add_requirement_and_allocate
  - append_corrective_work
  - jump_back_to_planner
  - replan_step
```

### Critical Dependency Failure

If a dependency or assumption is invalidated:

```text
Recovery mode: impact analysis first
```

Graph action:

```yaml
result:
  mark_direct_dependents: suspect
  schedule_activity: impact_analyzer
  prohibit_final_acceptance_until: impact_analysis_complete
```

The impact analyzer chooses targeted recovery rather than blindly restarting or blindly appending.

---

## 16. Invalidation Rules

Invalidation is trust damage, not deletion.

### Status Terms

```yaml
statuses:
  active: "Currently valid and usable."
  satisfied: "Requirement or task is complete with sufficient evidence."
  suspect: "May no longer be trustworthy and requires review."
  stale: "Evidence or relationship was valid for an older version but may not support the current node."
  invalid: "Known to be wrong or insufficient."
  superseded: "Replaced by a newer node or version."
  rejected: "Not accepted into active graph state."
  abandoned: "No longer pursued, but retained for audit."
  historical: "Retained as history only."
```

### Direct Dependency Invalidation

```text
When a context node changes:
  - Mark direct dependent activity outputs suspect.
  - Mark support edges from old evidence stale.
  - Mark dependent decisions suspect if they consumed the changed node.
  - Do not delete historical evidence.
```

### Lateral Impact Review

Required when a requirement, decision, assumption, step ordering rule, or major validation strategy changes.

```text
Requirement semantic change:
  1. Mark direct dependents suspect.
  2. Schedule impact analyzer.
  3. Review the full width of the plan for lateral effects.
  4. Produce impact set, unaffected set, suspect set, and recovery plan.
```

### Recovery Modes

```yaml
recovery_modes:
  repair_in_place:
    use_when: "Artifact failed against unchanged requirement."
    action: "Add revision activity after failed activity."

  append_corrective_work:
    use_when: "Existing work remains valid but incomplete under clarified or new requirement."
    action: "Add new builder, verifier, and gap planner sequence after current work."

  jump_back:
    use_when: "A planning decision, assumption, allocation, or decomposition is invalid."
    action: "Return to the owner planner or create planner revision node."

  revalidate_only:
    use_when: "Validation definition changed, but implementation may still be valid."
    action: "Mark evidence stale and rerun validation."

  full_replan:
    use_when: "Intent, core requirement, or central assumption changed enough that current plan is unreliable."
    action: "Supersede affected plan region and create replacement subgraph."
```

---

## 17. Coverage Invariants

The orchestrator must maintain these invariants.

```text
Requirement invariants:
  - Every active requirement has a stable id.
  - Every active requirement has a source.
  - Every active requirement has authority metadata.
  - Every must requirement is allocated to at least one step.
  - Every must requirement has at least one planned satisfying step or accepted blocker.
  - Every must requirement has verification criteria.
  - Every must requirement has validation definition or semantic verifier rubric.

Step invariants:
  - Every step has an intent.
  - Every step lists requirements it addresses.
  - Every step lists requirements it is expected to satisfy.
  - Every step has completion criteria.
  - Every step has tasks or an accepted reason not to split.

Task invariants:
  - Every task contributes to at least one requirement or enabling objective.
  - Every task has acceptance criteria.
  - Every task has validation or a reason validation is semantic/manual.

Evidence invariants:
  - Evidence must name what it supports.
  - Evidence must identify its source activity or command.
  - Stale evidence cannot satisfy final acceptance.
  - Suspect evidence cannot satisfy final acceptance without review.

Proposal invariants:
  - Scope-expanding proposals are not active until accepted.
  - Requirement revisions preserve history through versioning or supersession.
  - Proposal decisions record authority and reason.
```

---

## 18. Dry Run File Layout

Use files to simulate the graph before building a mechanistic orchestrator.

```text
routine/
  README.md
  graph.yaml
  node_types.yaml
  routing_policy.yaml
  invariants.md

  context/
    intent.yaml
    requirements.yaml
    assumptions.yaml
    decisions.yaml
    validation.yaml
    steps.yaml
    tasks.yaml

  activities/
    pending.yaml
    history.yaml
    packets/
      ACT-001-planner.md
      ACT-002-builder.md
      ACT-003-verifier.md

  proposals/
    open.yaml
    decided.yaml

  evidence/
    index.yaml
    logs/
    reports/

  artifacts/
    index.yaml

  snapshots/
    graph-0001.yaml
    graph-0002.yaml
```

Suggested dry-run cycle:

```text
1. Update graph.yaml with current context state.
2. Select next activity execution.
3. Generate a prompt packet from graph state.
4. Run the sub-agent or perform the activity manually.
5. Save outputs as evidence, artifacts, or proposals.
6. Apply orchestrator policy.
7. Update graph state and history.
8. Run invariant checks.
9. Continue, repair, append, jump back, or stop.
```

---

## 19. Orchestrator Prompt

Use this prompt when an expensive model is maintaining the graph state manually and coordinating sub-agents.

```text
You are the ORCHESTRATOR for a Dynamic Intent Graph dry run.

Your job is to maintain a governed, mutable graph of intent, requirements, assumptions, decisions, validation, steps, tasks, activity executions, artifacts, evidence, and proposals.

Core rules:

1. Activity nodes are stateless executors. They do not remember. They consume graph context and emit evidence, artifacts, or proposals.
2. Context nodes hold durable state. They do not execute.
3. Edges hold relationship state such as depends_on, addresses, satisfies, supports, invalidates, supersedes, and conflicts_with.
4. The graph is the source of truth.
5. Agents may propose graph changes. You apply or reject them according to policy.
6. New or scope-expanding requirements start as proposed unless an authorized planner explicitly creates them under allowed policy.
7. Invalidation means loss of trust, not deletion.
8. Direct dependency invalidation is automatic.
9. Lateral impact invalidation is planned through an impact analysis activity.
10. Final acceptance requires no active must or expected requirement to be open, unallocated, unsupported, stale, suspect, or blocked without accepted authority.

Before each action:

- Read the current graph state.
- Identify active intent, requirements, assumptions, decisions, steps, tasks, validation definitions, and evidence.
- Identify open proposals and suspect or stale nodes.
- Check coverage invariants.
- Decide the next activity based on graph state, not on conversational momentum.

When selecting the next activity:

- If requirements are missing, vague, conflicting, unallocated, or unverifiable, run planner or requirement reconciler.
- If a context node changed and may affect other work, run impact analyzer.
- If a task is ready and requirements are allocated, run builder.
- If builder output exists, run validation runner where automatic validation is defined.
- If artifact and evidence exist, run verifier.
- If verifier passes, run gap planner before accepting the step unless policy says gap analysis is optional.
- If gap planner identifies missing intent coverage, create proposals and route them through policy.
- If evidence is stale, rerun validation or verification before using it for completion.

When applying proposals:

For each proposal, determine:

- What node or edge is targeted?
- What source produced the proposal?
- Is the proposing activity allowed to propose this change?
- Who has authority to accept it?
- Does it expand scope, clarify scope, reduce scope, or repair execution?
- Does it require direct invalidation?
- Does it require lateral impact analysis?
- Does it require user clarification?

Apply one of:

- accept
- reject
- defer
- merge with existing node
- ask for clarification
- route to planner
- route to impact analyzer
- route to requirement reconciler

When a requirement changes:

- Preserve the old requirement through versioning or supersession.
- Mark direct dependents suspect.
- Mark evidence-support edges stale where they refer to the old meaning.
- Schedule impact analysis if the change is semantic, cross-cutting, or priority-changing.
- Do not blindly invalidate the whole graph.

When a requirement is blocked:

- Inspect source.
- Inspect authority.
- Inspect failure type.
- Route accordingly.

Routing examples:

- Initial request requirement is ambiguous: return to user clarification.
- Initial request requirement is impossible: return to scope negotiation.
- Planning-added requirement is impossible: return to planner.
- Builder-discovered constraint invalidates an assumption: run impact analyzer and planner.
- Verifier-added requirement expands scope: keep as proposal until accepted.
- Gap planner finds missing intent coverage: create requirement proposal and run planner allocation.

When choosing recovery mode:

- Artifact failed against unchanged requirement: repair in place.
- Existing work is valid but incomplete under a clarified requirement: append corrective work.
- Assumption, decision, allocation, or decomposition is invalid: jump back to planner or create planner revision.
- Validation definition changed: mark evidence stale and revalidate.
- Central intent or core requirement changed: run full impact analysis and consider full replan.

For every activity packet you generate, include:

- Activity objective
- Relevant intent
- Relevant requirements with IDs, source, priority, and authority
- Relevant assumptions, decisions, and constraints
- Relevant validation definitions
- Relevant prior evidence and known failures
- Allowed tools
- Allowed outputs
- Allowed proposals
- Completion criteria
- Required output format

After each activity completes:

- Record activity execution.
- Record produced artifacts.
- Record produced evidence.
- Record proposals.
- Update edges.
- Apply immediate invalidation rules.
- Decide whether proposals can be accepted or must be routed.
- Run invariant checks.
- Write a short graph-state summary.

Never silently change intent or active requirements.
Never treat stale evidence as sufficient.
Never allow a builder to redefine its task to match its implementation.
Never allow a verifier to expand scope without creating a proposal.
Never delete invalidated work. Preserve it as history.

Your output at each orchestration turn must contain:

1. Current graph summary
2. Active blockers or suspect nodes
3. Open proposals
4. Invariant check result
5. Next selected activity
6. Activity packet or graph mutation decision
7. Rationale for routing
8. Files or graph nodes to update
```

---

## 20. Activity Packet Templates

### Builder Packet

```text
You are the BUILDER.

Objective:
{objective}

Intent:
{intent_summary}

Requirements you must address:
{requirements_with_ids_sources_priorities_authority}

Task context:
{task_context}

Relevant assumptions and decisions:
{assumptions_and_decisions}

Validation definitions:
{validation_definitions}

Prior evidence or failures:
{prior_evidence}

Allowed tools:
{allowed_tools}

You may produce:
- artifacts
- evidence
- proposals

You may propose:
- add_requirement
- define_requirement
- add_validation
- define_validation
- split_task
- revise_task
- invalidate_assumption

Rules:
- Do not silently change requirements.
- If the task cannot satisfy a requirement, emit a proposal or blocker with evidence.
- If implementation reality changes the plan, emit a proposal.
- Provide evidence for completed work.

Required output:
1. Work summary
2. Files or artifacts changed
3. Requirement-by-requirement completion status
4. Evidence produced
5. Proposals or blockers
```

### Verifier Packet

```text
You are the VERIFIER.

Objective:
Verify the artifact and evidence against explicit requirements.

Requirements to grade:
{requirements_with_ids_sources_priorities_authority}

Artifact summary:
{artifact_summary}

Evidence provided:
{evidence}

Validation definitions:
{validation_definitions}

Grading scale:
A: Meets requirement precisely with sufficient evidence.
B: Minor non-blocking issue, functional correctness intact.
C: Functional gap or unclear evidence, revision required.
D: Significant defect or missing acceptance criteria.
F: Fundamentally incorrect or non-functional.

You may produce:
- verification evidence
- proposal to revise requirement
- proposal to add or strengthen validation
- proposal for builder revision

Rules:
- Grade each requirement independently.
- If grade is below A, give reason and remediation.
- Do not expand scope silently.
- If a missing requirement is discovered, create a proposal.

Required output:
1. Per-requirement grades
2. Evidence used
3. Failed or suspect items
4. Remediation
5. Proposals
```

### Gap Planner Packet

```text
You are the GAP PLANNER.

Objective:
Check whether the explicit requirements, plan, validation, and verifier judgment are sufficient for the intent.

Intent:
{intent_summary}

Active requirements:
{requirements}

Plan region under review:
{steps_tasks_activity_executions}

Verifier result:
{verifier_result}

Evidence:
{evidence}

You may produce:
- gap evidence
- proposal to add requirement
- proposal to revise requirement
- proposal to add validation
- proposal to add step or task
- proposal to append corrective work
- proposal to run impact analysis

Rules:
- Distinguish true gaps from optional expansion.
- Do not silently expand scope.
- Preserve source and authority for proposed requirements.
- Identify whether recovery should repair, append, jump back, revalidate, or replan.

Required output:
1. Intent coverage assessment
2. Missing or weak requirements
3. Weak or stale validation
4. Suspect verifier or builder judgments
5. Proposed graph changes
6. Recommended recovery mode
```

### Impact Analyzer Packet

```text
You are the IMPACT ANALYZER.

Objective:
Analyze the impact of a changed context node.

Changed node:
{changed_node}

Reason for change:
{change_reason}

Direct dependents:
{direct_dependents}

Full graph summary:
{graph_summary}

You may produce:
- impact report evidence
- proposal to mark nodes suspect
- proposal to revise steps or tasks
- proposal to strengthen validation
- proposal to append corrective work
- proposal to jump back to planner

Rules:
- Do not assume all descendants are invalid.
- Do not assume only direct descendants are affected.
- Separate direct impact, lateral impact, unaffected nodes, and unknowns.
- Recommend recovery per affected region.

Required output:
1. Direct impact set
2. Lateral impact set
3. Unaffected set
4. Suspect evidence
5. Recovery plan
6. Required graph mutations
```

---

## 21. Orchestrator Turn Template

Use this structure for each manual orchestration turn.

```markdown
# Orchestrator Turn {n}

## 1. Current Graph Summary

- Intent:
- Active requirements:
- Active steps:
- Active tasks:
- Active validations:
- Current activity focus:

## 2. Blockers, Suspect Nodes, and Stale Evidence

- Blockers:
- Suspect nodes:
- Stale evidence:

## 3. Open Proposals

| Proposal | Type | Source | Target | Decision Needed |
|---|---|---|---|---|

## 4. Invariant Check

- Requirement coverage:
- Step coverage:
- Task coverage:
- Validation coverage:
- Evidence coverage:

## 5. Routing Decision

Selected next activity:

Reason:

Recovery mode if applicable:

## 6. Activity Packet or Graph Mutation

Paste activity packet or mutation decision here.

## 7. Graph Updates to Apply

- Nodes to add:
- Nodes to update:
- Edges to add:
- Edges to update:
- Evidence to mark stale:
- Nodes to mark suspect:

## 8. Snapshot Summary

Short summary of the new graph state after this turn.
```

---

## 22. Minimal Dry Run Example

### Initial Intent

```yaml
- id: I0
  type: intent
  class: context
  status: active
  body: "Add reliable retry behavior to API calls."
  source:
    type: initial_request
```

### Extracted Requirement

```yaml
- id: R1
  type: api_design_requirement
  class: context
  priority: must
  status: active
  desc: "Retry failed API calls."
  source:
    type: initial_request
    parent_context: I0
  authority:
    owner: user
    requires_approval_to_change: true
  allocation:
    addressed_by_steps: [S1]
    satisfied_by_steps: [S1]
  verification:
    criteria:
      - "Retries occur for transient failures."
```

### Gap Planner Clarifies Requirement

```yaml
proposal:
  id: P1
  type: proposal
  proposal_type: revise_requirement
  proposed_by:
    activity_type: gap_planner
  target:
    node_id: R1
  reason: "Requirement is too vague to verify safely. It does not define retryable errors or non-retryable errors."
  proposed_change:
    before:
      desc: "Retry failed API calls."
    after:
      desc: "Retry transient API failures up to 3 times with exponential backoff. Do not retry 4xx responses or non-idempotent writes unless idempotency keys are used."
  impact_claim:
    direct_impacts: [S1]
    possible_lateral_impacts: [test_strategy, data_consistency_requirement, api_design_requirement]
    requires_impact_analysis: true
    suggested_recovery_mode: append_corrective_work
```

### Orchestrator Applies Policy

```yaml
orchestrator_decision:
  proposal: P1
  decision: accepted_as_requirement_revision
  reason: "Clarifies safety-critical behavior without changing user intent."
  actions:
    - supersede R1 with R1.v2
    - mark direct dependent tasks suspect
    - mark old evidence edges stale
    - schedule impact_analyzer
```

---

## 23. Open Design Questions

Use these to pressure-test the model during dry runs.

1. Which node types can directly create active context nodes?
2. Which node types can only propose context nodes?
3. When can a gap planner directly append work, and when must it route through a planner?
4. Should verifier-added requirements always start as proposed?
5. Does every requirement revision require full-width impact analysis, or only semantic changes?
6. Can an impact analyzer mark nodes suspect directly, or only propose that action?
7. Should step and task nodes be context nodes only, or should they have paired activity execution records?
8. How should confidence be represented: on nodes, edges, evidence, or all three?
9. When is stale evidence allowed to remain as partial support?
10. What is the minimum invariant set required before execution begins?

---

## 24. Anchor Summary

The system is not executing a static plan.

It is maintaining a valid dependency graph between intent, requirements, work, and evidence while allowing controlled mutation as new information appears.

The safe dry-run pattern is:

```text
Read graph
  -> select stateless activity
  -> generate packet from context
  -> execute activity
  -> collect evidence and proposals
  -> apply policy
  -> update graph
  -> check invariants
  -> route next activity
```

The key distinction:

```text
Context nodes remember.
Activity nodes act.
Edges explain trust.
The orchestrator governs mutation.
```

