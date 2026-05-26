# Dynamic Intent Graph Feature Dry Run

## Purpose

This is a manual dry run of the dynamic intent graph model against a deliberately generic feature. The feature and code are placeholders. The purpose is to test graph behavior when planning, research, verification failure, gap analysis, proposal handling, invalidation, and recovery all occur in one run.

The dry run assumes:

- The initial intent maps to five requirements: `R1` through `R5`.
- `R2` is initially unclear and requires research before implementation can be trusted.
- The implementation plan has three steps, each with three tasks.
- At least one task fails verification and must be repaired in place.
- At least one task passes verification but still requires further work after gap analysis.
- Activity executions are stateless. Durable state lives in context nodes and edges.

---

## 1. Event Types That Need To Be Handled

These are the event classes exercised by this run.

| Event Type | Trigger | Graph Effect | Routing |
|---|---|---|---|
| `intent_received` | User request starts routine | Create `I0`, root edges, initial planner activity | `initial_planner` |
| `requirements_extracted` | Planner maps intent to requirements | Create `R1`-`R5` with source, authority, priority, allocation placeholders | Continue planning unless invariant fails |
| `requirement_ambiguous` | Requirement cannot be implemented or verified yet | Mark requirement `blocked` or `needs_discovery`; create discovery task/activity | `discovery` before implementation |
| `research_completed` | Discovery produces usable finding | Create evidence and proposal to define or revise requirement | Orchestrator proposal decision |
| `proposal_accepted` | Orchestrator accepts graph mutation | Apply mutation, preserve old state, update edges | Run invalidation policy if semantic change |
| `proposal_deferred` | Proposal is plausible but scope/authority unclear | Keep proposal open, block affected final acceptance | User, planner, or requirement reconciler |
| `plan_created` | Planner allocates requirements to steps/tasks | Create `S1`-`S3`, `T1.1`-`T3.3`, validation definitions | Builder/validation loop |
| `context_changed` | Requirement, decision, assumption, validation, or ordering changes | Mark direct dependents suspect, mark old evidence edges stale | `impact_analyzer` when lateral review is required |
| `task_started` | Builder packet is generated | Create activity execution consuming graph snapshot | Builder executes against explicit context |
| `builder_completed` | Builder emits artifacts/evidence/proposals | Add artifact/evidence/proposal nodes and `produces` edges | Validation runner or verifier |
| `auto_validation_failed` | Command validation fails | Add failing evidence; task remains open | Builder revision, usually same task |
| `verification_failed` | Verifier grades requirement below pass threshold | Mark artifact/evidence support edge invalid or insufficient | `repair_in_place` if requirement unchanged |
| `verification_passed` | Verifier grades task as acceptable | Add verification evidence | Gap planner unless skipped by policy |
| `gap_found` | Gap planner finds intent not covered by explicit requirements/validation | Add gap evidence and proposals | Strengthen validation, add requirement, append work, or replan |
| `append_corrective_work` | Existing work is valid but incomplete | Add corrective task/activity after current work | Builder -> verifier -> gap planner |
| `revalidate_only` | Validation definition changes but implementation may still be valid | Mark evidence stale; rerun validation | Validation runner |
| `step_completed` | All tasks in step satisfied with current evidence | Mark step satisfied | Next step |
| `final_acceptance_check` | Routine appears complete | Run invariant sweep across requirements, steps, tasks, evidence, and proposals | Complete or block |

---

## 2. Synthetic Intent and Requirements

### Intent

```yaml
id: I0
type: intent
status: active
body: "Implement Feature F0 in a way that is correct, safe, observable, tested, and documented."
source:
  type: initial_request
```

### Requirements

```yaml
requirements:
  - id: R1
    type: api_design_requirement
    title: "User-visible behavior"
    priority: must
    status: active
    desc: "Feature F0 exposes the intended user-visible behavior through the existing product surface."
    source: { type: initial_request, parent_context: I0 }
    authority: { owner: user, requires_approval_to_change: true }
    verification:
      criteria:
        - "The behavior can be exercised through the expected entry point."
        - "The response or result matches the contract defined in the plan."

  - id: R2.v1
    type: data_consistency_requirement
    title: "Data consistency semantics"
    priority: must
    status: blocked
    desc: "Feature F0 preserves data consistency, but the correct implementation strategy is unknown."
    source: { type: initial_request, parent_context: I0 }
    authority: { owner: user, requires_approval_to_change: true }
    routing:
      if_ambiguous: ACT-DISCOVER-R2
    verification:
      criteria:
        - "Research must determine the existing consistency model before implementation."

  - id: R3
    type: logging_observability_requirement
    title: "Operational visibility"
    priority: expected
    status: active
    desc: "Feature F0 emits useful errors, logs, and metrics for operational diagnosis."
    source: { type: planning, parent_context: I0 }
    authority: { owner: planner, requires_approval_to_change: false }
    verification:
      criteria:
        - "Failures are diagnosable without exposing sensitive data."
        - "At least one relevant metric or structured log is emitted."

  - id: R4.v1
    type: test_strategy_requirement
    title: "Testing and validation"
    priority: must
    status: active
    desc: "Feature F0 has automated tests and quality gates."
    source: { type: planning, parent_context: I0 }
    authority: { owner: planner, requires_approval_to_change: false }
    verification:
      criteria:
        - "Unit or integration tests cover the primary success path."
        - "Configured validation commands pass."

  - id: R5
    type: documentation_requirement
    title: "Maintainer documentation"
    priority: expected
    status: active
    desc: "Feature F0 is documented for future maintainers."
    source: { type: planning, parent_context: I0 }
    authority: { owner: planner, requires_approval_to_change: false }
    verification:
      criteria:
        - "Documentation explains behavior, constraints, and verification commands."
```

### Initial Invariant Result

```yaml
invariant_check_after_requirement_extraction:
  status: fail
  failures:
    - "R2.v1 is blocked and not yet implementable."
    - "R2.v1 does not have a concrete validation definition."
    - "Planner cannot safely mark all must requirements ready for implementation."
  routing: ACT-DISCOVER-R2
```

---

## 3. Plan Structure

The planner still creates a provisional three-step plan, but marks the regions dependent on `R2.v1` as suspect until discovery completes. This is useful for testing invalidation behavior.

```yaml
steps:
  - id: S1
    title: "Discovery and plan anchoring"
    status: active
    addresses: [R1, R2.v1, R4.v1]
    expected_to_satisfy: []
    completion_criteria:
      - "Implementation surface is known."
      - "R2 is clarified or explicitly blocked."
      - "Validation definitions exist for active must requirements."
    tasks:
      - id: T1.1
        title: "Map existing feature surface and patterns"
        addresses: [R1]
      - id: T1.2
        title: "Research data consistency strategy for R2"
        addresses: [R2.v1]
      - id: T1.3
        title: "Define validation strategy and task boundaries"
        addresses: [R1, R2.v1, R4.v1]

  - id: S2
    title: "Core implementation"
    status: suspect
    suspect_reason: "Created while R2 was unresolved."
    addresses: [R1, R2.v1, R3]
    expected_to_satisfy: [R1, R2.v1, R3]
    completion_criteria:
      - "Core behavior is implemented."
      - "Data consistency path passes verification."
      - "Operational visibility exists."
    tasks:
      - id: T2.1
        title: "Implement user-visible entry path"
        addresses: [R1]
      - id: T2.2
        title: "Implement data consistency path"
        addresses: [R2.v1]
        status: suspect
      - id: T2.3
        title: "Implement errors, logs, and metrics"
        addresses: [R3]

  - id: S3
    title: "Hardening and delivery"
    status: active
    addresses: [R4.v1, R5, R1, R2.v1]
    expected_to_satisfy: [R4.v1, R5]
    completion_criteria:
      - "Validation commands pass."
      - "Tests cover the agreed behavior."
      - "Documentation is updated."
      - "Final invariant sweep passes."
    tasks:
      - id: T3.1
        title: "Add automated tests and validation wiring"
        addresses: [R4.v1]
      - id: T3.2
        title: "Add maintainer documentation"
        addresses: [R5]
      - id: T3.3
        title: "Run final integration and acceptance pass"
        addresses: [R1, R2.v1, R3, R4.v1, R5]
```

---

## 4. Dry Run Trace

### Turn 0: Routine Start

```yaml
activity:
  id: ACT-000
  activity_type: initial_planner
  status: complete
  consumed: [I0]
  produced: [R1, R2.v1, R3, R4.v1, R5, S1, S2, S3, T1.1, T1.2, T1.3, T2.1, T2.2, T2.3, T3.1, T3.2, T3.3]
result_summary: "Initial graph expanded. R2 is blocked because implementation strategy is unknown. S2 and T2.2 are suspect because they were planned against unresolved R2."
```

Routing decision: run discovery before implementation.

---

### Turn 1: Discovery for R2

```yaml
activity:
  id: ACT-DISCOVER-R2
  activity_type: discovery
  objective: "Determine how Feature F0 should preserve data consistency."
  status: complete
  consumed: [I0, R2.v1, T1.2]
  produced:
    evidence_nodes: [E-DISC-R2]
    proposals: [P-001, P-002, P-003]

evidence:
  - id: E-DISC-R2
    type: evidence
    status: active
    title: "R2 discovery report"
    body:
      finding: "Existing system uses transactional writes plus idempotency token checks. Feature F0 must use the same boundary."
      confidence: high
      implication: "R2 can be defined. T2.2 must use transactional update plus idempotency guard."

proposals:
  - id: P-001
    proposal_type: define_requirement
    source: ACT-DISCOVER-R2
    target: R2.v1
    status: proposed
    reason: "R2 was blocked by missing implementation strategy. Discovery identified the consistency model."
    proposed_change:
      before:
        id: R2.v1
        status: blocked
        desc: "Feature F0 preserves data consistency, but the correct implementation strategy is unknown."
      after:
        id: R2.v2
        status: active
        desc: "Feature F0 must perform writes inside the existing transactional boundary and must prevent duplicate application through the existing idempotency token mechanism."
    impact_claim:
      direct_impacts: [S1, S2, T1.3, T2.2, VD-R2-v1]
      possible_lateral_impacts: [R1, R4.v1, T3.1, T3.3]
      requires_impact_analysis: true
      suggested_recovery_mode: jump_back

  - id: P-002
    proposal_type: define_validation
    source: ACT-DISCOVER-R2
    target: R2.v2
    status: proposed
    proposed_change:
      after:
        id: VD-R2-v2
        command_id: data_consistency_tests
        command: "run data consistency and idempotency validation"
        validates: [R2.v2]

  - id: P-003
    proposal_type: revise_task
    source: ACT-DISCOVER-R2
    target: T2.2
    status: proposed
    reason: "T2.2 was planned before R2 was concrete."
    proposed_change:
      after:
        title: "Implement transactional update with idempotency guard"
        addresses: [R2.v2]
```

### Orchestrator Decision

```yaml
decisions:
  - proposal: P-001
    decision: accepted
    reason: "Defines a previously blocked must requirement without changing the user intent."
    actions:
      - "Supersede R2.v1 with R2.v2."
      - "Mark direct dependents suspect."
      - "Schedule impact analyzer because semantic requirement changed."

  - proposal: P-002
    decision: accepted
    reason: "Required validation definition for an active must requirement."
    actions:
      - "Create VD-R2-v2."

  - proposal: P-003
    decision: accepted_pending_impact
    reason: "Task update appears correct, but S2 and T3.1 may also need adjustment."
```

Graph effect:

```yaml
nodes_updated:
  - { id: R2.v1, status: superseded, superseded_by: R2.v2 }
  - { id: R2.v2, status: active, source: discovery, evidence_refs: [E-DISC-R2] }
  - { id: S2, status: suspect, reason: "R2 semantic clarification" }
  - { id: T2.2, status: suspect, reason: "R2 semantic clarification" }
edges_updated:
  - { from: R2.v1, to: S2, type: allocated_to, status: stale }
  - { from: R2.v1, to: T2.2, type: addresses, status: stale }
edges_added:
  - { from: R2.v2, to: S2, type: allocated_to, status: active }
  - { from: R2.v2, to: T2.2, type: addresses, status: active }
```

---

### Turn 2: Impact Analysis for R2 Change

```yaml
activity:
  id: ACT-IMPACT-R2
  activity_type: impact_analyzer
  objective: "Assess direct and lateral impact of defining R2.v2."
  status: complete
  consumed: [R2.v1, R2.v2, S1, S2, S3, T1.3, T2.2, T3.1, T3.3]
  produced:
    evidence_nodes: [E-IMPACT-R2]
    proposals: [P-004, P-005]

evidence:
  - id: E-IMPACT-R2
    type: evidence
    title: "Impact report for R2.v2"
    status: active
    body:
      direct_impact_set: [T1.3, T2.2, VD-R2-v1]
      lateral_impact_set: [T3.1, T3.3, R4.v1]
      unaffected_set: [T2.1, T2.3, T3.2, R5]
      recovery_plan:
        - "Update T2.2 to consume R2.v2."
        - "Ensure T3.1 has tests for idempotency and duplicate application."
        - "Ensure T3.3 final integration includes R2.v2 validation."

proposals:
  - id: P-004
    proposal_type: revise_task
    target: T3.1
    status: proposed
    reason: "R4 validation must include R2.v2 consistency tests."
    proposed_change:
      after:
        addresses: [R4.v1, R2.v2]
        validation_definitions: [VD-R2-v2]

  - id: P-005
    proposal_type: revise_task
    target: T3.3
    status: proposed
    reason: "Final integration must consume the new R2.v2 validation evidence."
```

Orchestrator accepts `P-004` and `P-005` because they repair planning after a clarified must requirement. `S2` returns to active. `T2.2`, `T3.1`, and `T3.3` remain open but no longer suspect.

---

### Turn 3: Step 1 Completes

```yaml
activity_results:
  - id: ACT-BUILD-T1.1
    activity_type: builder
    status: complete
    produced: [A-T1.1, E-T1.1]
  - id: ACT-VERIFY-T1.1
    activity_type: verifier
    status: complete
    produced: [E-V-T1.1]
  - id: ACT-GAP-T1.1
    activity_type: gap_planner
    status: complete
    produced: [E-G-T1.1]
  - id: ACT-BUILD-T1.3
    activity_type: builder
    status: complete
    produced: [A-T1.3, E-T1.3]

step_update:
  id: S1
  status: satisfied
  reason: "Discovery completed, R2.v2 defined, initial validation strategy established."
```

No open blockers remain before implementation.

---

### Turn 4: Core Implementation Starts

`T2.1` and `T2.3` complete normally.

```yaml
task_updates:
  - id: T2.1
    status: satisfied
    satisfying_evidence: [E-V-T2.1, E-G-T2.1]
  - id: T2.3
    status: satisfied
    satisfying_evidence: [E-V-T2.3, E-G-T2.3]
```

`T2.2` fails verification.

```yaml
activity:
  id: ACT-BUILD-T2.2-A1
  activity_type: builder
  objective: "Implement transactional update with idempotency guard."
  status: complete
  consumed: [I0, R2.v2, T2.2, VD-R2-v2]
  produced:
    artifacts: [A-T2.2-A1]
    evidence_nodes: [E-AUTO-T2.2-A1]

activity:
  id: ACT-VERIFY-T2.2-A1
  activity_type: verifier
  status: complete
  consumed: [R2.v2, T2.2, A-T2.2-A1, E-AUTO-T2.2-A1]
  produced:
    evidence_nodes: [E-V-T2.2-A1]
    proposals: [P-006]

evidence:
  - id: E-V-T2.2-A1
    type: evidence
    title: "Verifier failure for T2.2 attempt 1"
    status: active
    body:
      grades:
        R2.v2: C
      reason: "Implementation uses the transaction boundary but idempotency guard is applied after the write, allowing duplicate side effects under retry."
      remediation: "Move idempotency guard before side effect or make the side effect conditional inside the same transaction."

proposals:
  - id: P-006
    proposal_type: append_corrective_work
    source: ACT-VERIFY-T2.2-A1
    target: T2.2
    status: proposed
    reason: "Artifact failed against unchanged R2.v2."
    impact_claim:
      direct_impacts: [T2.2, A-T2.2-A1]
      possible_lateral_impacts: []
      requires_impact_analysis: false
      suggested_recovery_mode: repair_in_place
```

### Orchestrator Decision

```yaml
decision:
  proposal: P-006
  decision: accepted_as_repair_in_place
  reason: "Verifier found a defect against unchanged requirements. No scope or plan semantics changed."
  actions:
    - "Mark A-T2.2-A1 insufficient."
    - "Mark support edge A-T2.2-A1 -> R2.v2 invalid."
    - "Create ACT-BUILD-T2.2-A2."
    - "Create ACT-VERIFY-T2.2-A2 after builder revision."
```

Graph effect:

```yaml
nodes_updated:
  - { id: A-T2.2-A1, status: invalid }
  - { id: T2.2, status: active, retry_count: 1 }
edges_updated:
  - { from: A-T2.2-A1, to: R2.v2, type: supports, status: invalid }
  - { from: E-AUTO-T2.2-A1, to: R2.v2, type: supports, status: contradicted }
activity_created:
  - ACT-BUILD-T2.2-A2
  - ACT-VERIFY-T2.2-A2
```

---

### Turn 5: T2.2 Repair Passes

```yaml
activity:
  id: ACT-BUILD-T2.2-A2
  activity_type: builder
  status: complete
  consumed: [I0, R2.v2, T2.2, E-V-T2.2-A1, VD-R2-v2]
  produced:
    artifacts: [A-T2.2-A2]
    evidence_nodes: [E-AUTO-T2.2-A2]

activity:
  id: ACT-VERIFY-T2.2-A2
  activity_type: verifier
  status: complete
  consumed: [R2.v2, T2.2, A-T2.2-A2, E-AUTO-T2.2-A2]
  produced:
    evidence_nodes: [E-V-T2.2-A2]

evidence:
  - id: E-V-T2.2-A2
    type: evidence
    title: "Verifier pass for T2.2 attempt 2"
    status: active
    body:
      grades:
        R2.v2: A
      reason: "Transactional boundary and idempotency guard now satisfy R2.v2."

updates:
  - { id: T2.2, status: satisfied, satisfying_evidence: [E-AUTO-T2.2-A2, E-V-T2.2-A2] }
  - { id: R2.v2, evidence_status: partial }
  - { id: S2, status: satisfied, reason: "T2.1, T2.2, and T2.3 are satisfied." }
```

This is the cleanest recovery case in the dry run: unchanged requirement, invalid artifact, repair in place.

---

### Turn 6: Step 3 Testing Passes Verification But Fails Gap Analysis

`T3.1` builds tests and passes verifier against `R4.v1`.

```yaml
activity:
  id: ACT-BUILD-T3.1-A1
  activity_type: builder
  status: complete
  consumed: [R4.v1, T3.1, VD-QUALITY-BASE]
  produced:
    artifacts: [A-T3.1-A1]
    evidence_nodes: [E-AUTO-T3.1-A1]

activity:
  id: ACT-VERIFY-T3.1-A1
  activity_type: verifier
  status: complete
  consumed: [R4.v1, T3.1, A-T3.1-A1, E-AUTO-T3.1-A1]
  produced:
    evidence_nodes: [E-V-T3.1-A1]

evidence:
  - id: E-V-T3.1-A1
    type: evidence
    title: "Verifier pass for T3.1 attempt 1"
    status: active
    body:
      grades:
        R4.v1: A
      reason: "Tests cover the primary success path and quality commands pass."
```

Gap planner then reviews against the full intent and the updated R2 requirement.

```yaml
activity:
  id: ACT-GAP-T3.1-A1
  activity_type: gap_planner
  status: complete
  consumed: [I0, R1, R2.v2, R3, R4.v1, T3.1, A-T3.1-A1, E-V-T3.1-A1, E-IMPACT-R2]
  produced:
    evidence_nodes: [E-GAP-T3.1-A1]
    proposals: [P-007, P-008]

evidence:
  - id: E-GAP-T3.1-A1
    type: evidence
    title: "Gap report for T3.1"
    status: active
    body:
      assessment: "Verifier was correct against R4.v1, but R4.v1 is too weak after R2.v2. Tests prove happy path but do not prove duplicate application prevention or failure behavior."
      gap_classification: "Explicit validation insufficient for intent"
      recovery_mode: append_corrective_work

proposals:
  - id: P-007
    proposal_type: strengthen_validation
    source: ACT-GAP-T3.1-A1
    target: R4.v1
    status: proposed
    reason: "R4.v1 validation does not cover the safety behavior introduced by R2.v2."
    proposed_change:
      before:
        id: R4.v1
        desc: "Feature F0 has automated tests and quality gates."
      after:
        id: R4.v2
        desc: "Feature F0 has automated tests and quality gates covering success path, duplicate application prevention, and failure behavior relevant to R2.v2."
    impact_claim:
      direct_impacts: [T3.1, T3.3, VD-QUALITY-BASE]
      possible_lateral_impacts: [R2.v2, S3]
      requires_impact_analysis: false
      suggested_recovery_mode: append_corrective_work

  - id: P-008
    proposal_type: append_corrective_work
    source: ACT-GAP-T3.1-A1
    target: S3
    status: proposed
    reason: "Existing T3.1 work is valid but incomplete under strengthened validation."
    proposed_change:
      after:
        new_task:
          id: T3.1b
          title: "Add negative and idempotency regression tests"
          addresses: [R4.v2, R2.v2]
```

### Orchestrator Decision

```yaml
decisions:
  - proposal: P-007
    decision: accepted_as_validation_strengthening
    reason: "This does not add a new user requirement. It strengthens proof required for an existing must requirement after R2 became concrete."
    actions:
      - "Supersede R4.v1 with R4.v2."
      - "Mark E-V-T3.1-A1 -> R4.v1 support edge historical."
      - "Mark E-V-T3.1-A1 -> R4.v2 support edge stale/insufficient."
      - "Create VD-R4-v2."

  - proposal: P-008
    decision: accepted_as_append_corrective_work
    reason: "Existing work remains valid but incomplete. Add corrective task rather than redoing all of S3."
    actions:
      - "Create T3.1b after T3.1 and before T3.3."
      - "Route to builder, verifier, and gap planner."
```

Graph effect:

```yaml
nodes_updated:
  - { id: R4.v1, status: superseded, superseded_by: R4.v2 }
  - { id: R4.v2, status: active }
  - { id: T3.1, status: satisfied_for_R4.v1_only }
  - { id: S3, status: active }
edges_updated:
  - { from: E-V-T3.1-A1, to: R4.v1, type: supports, status: historical }
  - { from: E-V-T3.1-A1, to: R4.v2, type: supports, status: stale, stale_reason: "Evidence proves old validation scope only." }
nodes_added:
  - id: T3.1b
    type: task
    title: "Add negative and idempotency regression tests"
    status: active
    addresses: [R4.v2, R2.v2]
  - id: VD-R4-v2
    type: validation_definition
    title: "Safety and failure behavior regression tests"
    validates: [R4.v2, R2.v2]
```

This is the key gap-planner case: nothing was wrong with the builder or verifier locally. The explicit requirement was too weak for the updated intent graph.

---

### Turn 7: Corrective Work Completes

```yaml
activity_sequence:
  - id: ACT-BUILD-T3.1B-A1
    activity_type: builder
    status: complete
    consumed: [R4.v2, R2.v2, T3.1b, VD-R4-v2]
    produced: [A-T3.1B-A1, E-AUTO-T3.1B-A1]
  - id: ACT-VERIFY-T3.1B-A1
    activity_type: verifier
    status: complete
    consumed: [R4.v2, R2.v2, T3.1b, A-T3.1B-A1, E-AUTO-T3.1B-A1]
    produced: [E-V-T3.1B-A1]
  - id: ACT-GAP-T3.1B-A1
    activity_type: gap_planner
    status: complete
    consumed: [I0, R1, R2.v2, R3, R4.v2, T3.1b, E-V-T3.1B-A1]
    produced: [E-G-T3.1B-A1]

evidence:
  - id: E-V-T3.1B-A1
    type: evidence
    status: active
    body:
      grades:
        R4.v2: A
        R2.v2: A
      reason: "Tests cover duplicate application prevention and failure behavior."
  - id: E-G-T3.1B-A1
    type: evidence
    status: active
    body:
      assessment: "Corrective work closes the gap introduced by R2.v2."

updates:
  - { id: T3.1b, status: satisfied }
  - { id: R4.v2, evidence_status: sufficient }
```

---

### Turn 8: Docs and Final Integration

```yaml
task_updates:
  - id: T3.2
    status: satisfied
    addresses: [R5]
    satisfying_evidence: [E-V-T3.2, E-G-T3.2]
  - id: T3.3
    status: satisfied
    addresses: [R1, R2.v2, R3, R4.v2, R5]
    satisfying_evidence: [E-FINAL-INTEGRATION]

final_validation:
  id: E-FINAL-INTEGRATION
  type: evidence
  status: active
  title: "Final integration and invariant sweep"
  body:
    commands: [quality, data_consistency_tests, safety_regression_tests, docs_check]
    result: pass
    invariant_check: pass
```

---

## 5. Final Graph Snapshot

```yaml
routine_instance:
  id: DRYRUN-FEATURE-001
  status: complete_after_recovery
  final_acceptance: passed
  active_intent: I0

requirements:
  - id: R1
    status: satisfied
    priority: must
    satisfied_by_steps: [S2, S3]
    evidence_status: sufficient
    evidence_refs: [E-V-T2.1, E-G-T2.1, E-FINAL-INTEGRATION]

  - id: R2.v1
    status: superseded
    superseded_by: R2.v2
    historical_reason: "Discovery clarified implementation and verification semantics."

  - id: R2.v2
    status: satisfied
    priority: must
    satisfied_by_steps: [S2, S3]
    evidence_status: sufficient
    evidence_refs: [E-DISC-R2, E-V-T2.2-A2, E-V-T3.1B-A1, E-FINAL-INTEGRATION]

  - id: R3
    status: satisfied
    priority: expected
    satisfied_by_steps: [S2]
    evidence_status: sufficient
    evidence_refs: [E-V-T2.3, E-G-T2.3, E-FINAL-INTEGRATION]

  - id: R4.v1
    status: superseded
    superseded_by: R4.v2
    historical_reason: "Gap analysis found validation was too weak after R2.v2."

  - id: R4.v2
    status: satisfied
    priority: must
    satisfied_by_steps: [S3]
    evidence_status: sufficient
    evidence_refs: [E-V-T3.1B-A1, E-G-T3.1B-A1, E-FINAL-INTEGRATION]

  - id: R5
    status: satisfied
    priority: expected
    satisfied_by_steps: [S3]
    evidence_status: sufficient
    evidence_refs: [E-V-T3.2, E-G-T3.2]

steps:
  - id: S1
    status: satisfied
    tasks: [T1.1, T1.2, T1.3]
    note: "Discovery and plan anchoring completed."
  - id: S2
    status: satisfied
    tasks: [T2.1, T2.2, T2.3]
    note: "T2.2 required one repair cycle."
  - id: S3
    status: satisfied
    tasks: [T3.1, T3.1b, T3.2, T3.3]
    note: "Gap planner appended T3.1b, so final executed task count exceeded original plan."

tasks:
  - { id: T1.1, status: satisfied }
  - { id: T1.2, status: satisfied, kind: discovery }
  - { id: T1.3, status: satisfied }
  - { id: T2.1, status: satisfied }
  - { id: T2.2, status: satisfied, attempts: 2, failed_attempts: [ACT-BUILD-T2.2-A1] }
  - { id: T2.3, status: satisfied }
  - { id: T3.1, status: historical_satisfied_for_R4.v1 }
  - { id: T3.1b, status: satisfied, kind: appended_corrective_work }
  - { id: T3.2, status: satisfied }
  - { id: T3.3, status: satisfied }

open_proposals: []

historical_or_rejected_support:
  - edge: A-T2.2-A1 -> R2.v2
    status: invalid
    reason: "Verifier found idempotency defect."
  - edge: E-V-T3.1-A1 -> R4.v2
    status: stale
    reason: "Evidence proves R4.v1 only, not strengthened R4.v2."
```

---

## 6. Compact Graph Map

```text
I0
├── R1 satisfied
│   ├── S2 / T2.1 satisfied
│   └── S3 / T3.3 final integration evidence
├── R2.v1 superseded
│   └── R2.v2 satisfied
│       ├── E-DISC-R2 supports definition
│       ├── S2 / T2.2 attempt 1 invalid
│       ├── S2 / T2.2 attempt 2 satisfied
│       └── S3 / T3.1b regression evidence
├── R3 satisfied
│   └── S2 / T2.3 satisfied
├── R4.v1 superseded
│   └── R4.v2 satisfied
│       ├── T3.1 evidence stale against R4.v2
│       └── T3.1b corrective work satisfied
└── R5 satisfied
    └── S3 / T3.2 satisfied
```

---

## 7. Invariant Sweep

```yaml
final_invariant_check:
  requirement_coverage:
    status: pass
    notes:
      - "All active must requirements are satisfied with sufficient non-stale evidence."
      - "Superseded requirements are historical and not used for final acceptance."

  step_coverage:
    status: pass_with_note
    notes:
      - "S3 contains appended task T3.1b, so executed plan differs from original plan."
      - "Original plan remains auditable through proposal and history nodes."

  task_coverage:
    status: pass
    notes:
      - "Every active task contributes to at least one requirement or enabling objective."
      - "Failed attempt ACT-BUILD-T2.2-A1 remains historical and invalid, not deleted."

  validation_coverage:
    status: pass
    notes:
      - "R2.v2 and R4.v2 have validation definitions and evidence."
      - "R4.v1 evidence is not reused for R4.v2 final acceptance."

  evidence_coverage:
    status: pass
    notes:
      - "Stale and invalid evidence exists but does not satisfy active requirements."

  proposal_coverage:
    status: pass
    notes:
      - "All proposals are decided."
      - "Scope-affecting proposal P-007 was accepted as validation strengthening, not as a silent new requirement."
```

---

## 8. Where The System Broke Down

### 1. The planner created too much structure before R2 was defined

The initial planner created a full three-step plan even though `R2` was not implementable. This was useful for the dry run, but risky as a real system behavior. It immediately created suspect nodes and required impact analysis.

Better rule:

```text
If a must requirement is blocked by discovery, allow only provisional planning past the blocked point.
Mark downstream steps draft/suspect, not active.
```

### 2. Discovery tasks and implementation tasks are not the same kind of work

`T1.2` was a discovery task inside the same task structure as implementation tasks. This worked, but it blurred lifecycle semantics. A discovery task produces evidence and proposals. It usually should not be expected to satisfy the original requirement by itself.

Better rule:

```text
Task.kind should be explicit: discovery | planning | implementation | validation | documentation | integration.
Only some task kinds can satisfy requirements directly.
```

### 3. Requirement clarification forced plan repair, but the system needs a clearer threshold for impact analysis

`R2.v1 -> R2.v2` clearly required impact analysis because it changed semantics. The dry run handled this well. The hard part is deciding when a change is merely definitional versus semantic.

Better rule:

```text
A requirement change requires lateral impact analysis when it changes:
- implementation strategy
- validation semantics
- step allocation
- safety/data consistency behavior
- priority
- external contract
```

### 4. Verifier failure was easy because the requirement did not change

`T2.2` failed against unchanged `R2.v2`. This made routing straightforward: repair in place. The graph did not need replanning, only a new builder attempt and verifier pass.

This part of the system held up well.

### 5. Gap analysis exposed a weaker class of failure

`T3.1` passed verification because `R4.v1` was too weak. The verifier was not wrong. The builder was not wrong. The explicit graph was wrong or incomplete after `R2` was clarified.

This is the most important breakdown:

```text
Verifier correctness is local to explicit requirements.
Gap planner correctness is global to intent sufficiency.
```

The gap planner found that the graph had allowed a shallow validation definition to survive after a safety-relevant requirement was clarified.

Better rule:

```text
Run a gap planner immediately after any semantic requirement clarification, before implementation continues.
Do not wait until the task-level verifier passes.
```

### 6. Proposal authority is still too subtle

`P-007` could be interpreted as either:

- strengthen validation for existing `R4`, or
- expand scope by requiring new negative/idempotency tests.

The dry run accepted it as validation strengthening because it was necessary to prove already-active `R2.v2`. This should be explicit policy, not an orchestration judgment call each time.

Better rule:

```text
A validation-strengthening proposal may be auto-accepted when it proves an already-active must requirement.
A new behavior requirement must remain proposed until accepted by the appropriate authority.
```

### 7. Evidence state belongs on edges, not just nodes

`E-V-T3.1-A1` remained valid historical evidence for `R4.v1`, but it was stale or insufficient for `R4.v2`. If evidence status only lived on the evidence node, this distinction would be lost.

The graph handled this well by making the support edge stale while preserving the evidence.

### 8. Original plan completion metrics became misleading

The original plan was three steps with three tasks each. After `T3.1b` was appended, the final plan had ten executed tasks. A naive progress tracker would say the plan deviated or failed. The graph should instead report:

```text
Original planned tasks: 9
Appended corrective tasks: 1
Failed attempts retained: 1
Final active requirements satisfied: yes
```

### 9. Final acceptance must be invariant-driven, not sequence-driven

A sequential runner might finish after `T3.3`. The graph runner must finish only after checking active requirements, stale evidence, suspect nodes, and open proposals.

This is the main reason the graph model is stronger than a simple builder-verifier state machine.

---

## 9. Design Adjustments Suggested By The Dry Run

1. Add `task.kind` to distinguish discovery, planning, implementation, validation, documentation, and integration tasks.
2. Add `plan_region.status = draft | active | suspect | superseded` so downstream work can exist before it is trusted.
3. Add a mandatory post-discovery gap-planner pass when a must requirement becomes concrete.
4. Make validation-strengthening authority explicit.
5. Track progress as planned tasks, appended tasks, failed attempts, and active requirement satisfaction separately.
6. Keep edge-level support state as a first-class concept.
7. Add a pre-final invariant gate that blocks on open proposals, stale support edges, suspect active nodes, and blocked must/expected requirements.

---

## 10. Dry Run Conclusion

The graph model recovered from both required failure modes:

- A verifier failure against unchanged requirements was repaired in place.
- A gap-planner failure caused validation strengthening and appended corrective work.

The largest weakness was not execution recovery. It was timing. The graph allowed a weak validation requirement to proceed too far after `R2` changed. The system needs an earlier gap-analysis pass after semantic requirement clarification, before implementation and task-level verification consume the updated graph.

