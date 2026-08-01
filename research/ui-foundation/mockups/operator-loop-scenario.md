# Operator Loop Scenario: r314

Scenario version: `operator-loop-r314-v1`
Purpose: Compare one complete operator-loop concept using implementation-shaped synthetic data.

This is an offline, synthetic fixture. It is shaped like current graph evidence, but it is not a live run or proof that proposed controls exist.

## Capability Legend

| Label | Meaning in this fixture |
|---|---|
| Current | The repository has an implemented source capability for the represented fact or action, subject to the stated evidence boundary. |
| Derived | A calculation or presentation from current inputs; it must remain labeled and linked to its sources. |
| Proposed | A design target with no current end-to-end command or delivery proof. |
| Unavailable | The control must not dispatch because the required capability is absent. |
| Synthetic | A fixed scenario value for comparing concepts, not production telemetry. |

`Live` means event-stream connected only. It does not claim that graph projections, activity, usage, or other visible data are current.

## Expected Operator Answers

1. `r314` needs attention because it has one pending authority decision, two failed verification outcomes for `R-17`, and a blocked final check.
2. The current frontier is the ready authority request `gate-01`; there is no active lease. `gap-plan-01` and `final-check` are blocked.
3. `R-17: Preserve request identity across retries` received grade C on both attempts.
4. Attempt 2 did not solve the problem because its fallback ID is still generated inside the retry branch, at the wrong lifecycle boundary.
5. Derived: a blind retry has no demonstrated information delta; no current retry-information-delta detector exists. The proposed instruction is intended to create a delta only if a future typed-steering path delivers it.
6. Candidate, verification, and file-state records support the comparison, while file-state paths are whole-worktree observations and do not prove node-exclusive causality.
7. The only current decision is whether to grant authority for one constrained recovery attempt. The represented refreshed projection reaches position 190 with `gap-plan-01` ready, `max_grants_reached` recorded, and no active lease.
8. The proposed intervention is scoped to `gap-plan-01 and its future descendants`, cites three evidence records, and has a proposed estimated correction budget of `$3.00`.
9. The fixture cannot verify that steering reached corrective work or compare its outcome with prior runs because typed steering and delivery proof are unavailable.

## Fleet

Status: Synthetic fixture values using current run-state, freshness, human-wait, and graph-usage shapes. The attention conclusion is Derived.

| Run | Observed state | Frontier / final gate | Freshness | Human wait | Usage |
|---|---|---|---|---|---|
| `r311` | active; lease on `api-contracts` | frontier emitting; final gate waiting on downstream work | event 24s ago | none | `$1.84`, graph executions, fully priced |
| `r312` | active; `verify-schema` running | verifier running; final gate not ready | event 51s ago | none | `$3.06`, graph executions, fully priced |
| `r313` | completed | final invariant passed | settled 12m ago | none | `$5.72`, graph executions, 92% priced |
| `r314` | active; no active lease | authority request `gate-01` ready; `final-check` blocked | event 2m 14s ago | one decision | `$8.42` known across graph executions plus one unpriced graph execution |

No fleet health labels are assigned. Derived selection reason: `r314 has one pending authority decision, two failed verification outcomes for R-17, and a blocked final check.` Run r314 is the only fixture row with a human wait or pending authority decision; r311-r313 show no pending human action. This does not classify any row as healthy.

## Graph For r314

Status: Synthetic fixture values using current graph node, state, edge, binding, and scheduler shapes.

| Node ID | Kind | State | Meaning |
|---|---|---|---|
| `plan-01` | planner | completed | initial graph proposal accepted |
| `build-01` | worker | completed | attempt 1 produced `candidate-01` |
| `verify-01` | verifier | completed | `R-17` graded C |
| `build-02` | worker | completed | attempt 2 produced `candidate-02` |
| `verify-02` | verifier | completed | `R-17` graded C again |
| `gate-01` | authority_request | ready | asks whether to grant one constrained recovery attempt |
| `gap-plan-01` | gap_planner | blocked | requires authority granted by `gate-01` |
| `final-check` | check | blocked | requires `R-17` to pass |

Directed topology/order: `plan-01 -> build-01 -> verify-01 -> build-02 -> verify-02 -> gate-01 -> gap-plan-01 -> final-check`.

This edge chain describes topology and ordering. Adjacency or event order alone is not proven business causality.

Canonical graph selection: `(run_id=r314, node_id=verify-02)`. Requirement `R-17`, attempt 2, evidence records, and the pending decision are retained context, not one joined identity. Graph nodes are distinct from legacy tasks and there is no identity join.

### Required Bindings At Position 184

Status: Synthetic fixture values using current required-input binding semantics. A required input blocks readiness until its accepted record is bound.

| Node | Required input bindings at graph position 184 |
|---|---|
| `plan-01` | synthetic run-context and routine-snapshot records were bound; node completed |
| `build-01` | synthetic accepted plan output and `R-17` requirement record were bound; node completed |
| `verify-01` | `candidate-01`, `file-state-01`, and the `R-17` requirement record were bound; node completed |
| `build-02` | `verification-01`, `candidate-01`, and the `R-17` requirement record were bound; node completed |
| `verify-02` | `candidate-02`, `file-state-02`, and the `R-17` requirement record were bound; node completed |
| `gate-01` | `authority-request-01` is bound with `requested_authority: [graph:gap-plan-01:execute]` and target node `gap-plan-01`; node ready |
| `gap-plan-01` | `verification-02` is bound; the state dependency on `gate-01` keeps it waiting until authority is granted, rather than binding an authority-decision record to a planner input |
| `final-check` | the `R-17` requirement is bound; required passing support for `R-17` is absent, so it remains blocked |

### Scheduler And Prompt Snapshot

Status: Synthetic fixture values using current scheduler buckets and graph prompt-summary metadata shapes.

Synthetic `SchedulerView` at graph position 184, represented in exactly its four executable buckets:

```yaml
ready: [gate-01]
blocked: [{node_id: final-check, reason: required input R-17 has no passing verification}]
waiting_resources: []
waiting_gates: [{node_id: gap-plan-01, reason: authority_not_granted:gate-01}]
```

Completed node state, separate from `SchedulerView`: `plan-01`, `build-01`, `verify-01`, `build-02`, and `verify-02` are completed.

Synthetic current `LeaseView`, separate from scheduler data:

```yaml
active: []
suspended: []
```

There is no active or suspended lease and no leased/running node at position 184.

Synthetic structured prompt-summary metadata captured for the earlier `verify-02` execution:

```yaml
node_id: verify-02
node_kind: verifier
node_role: verifier
packet_type: verifier
packet_keys: [bound_records, candidate_id, evaluated_record_citations, node_id, required_report_schema, requirements, rubric, task_region_id]
prompt_sections: [rubric, verifier_context_packet]
available_tools: [graph_grade]
lease: {lease_id: lease-verify-02, generation: 1, execution_id: exec-verify-02, base_snapshot_id: snapshot-r314-176}
input_ports:
  candidate: [candidate-02]
  file_state: [file-state-02]
  requirements: [requirement-R-17]
bound_records:
  candidate: [{record_id: candidate-02, record_kind: output, record_type: candidate, producer_node_id: build-02, port: candidate, record_summary: {candidate_id: candidate-02, attempt: 2}}]
  file_state: [{record_id: file-state-02, record_kind: output, record_type: file_state, producer_node_id: build-02, port: file_state, record_summary: {boundary: callback_time, changed_paths: [graph.py, dispatch.py]}}]
  requirements: [{record_id: requirement-R-17, record_kind: output, record_type: requirement, producer_node_id: plan-01, port: requirement, record_summary: {requirement_id: R-17, title: Preserve request identity across retries}}]
required_report_schema:
  record_kind: verification
  port: verification_report
  schema: VerificationReport
  required_fields: [candidate_id, outcome, value.outcome, value.grades, evidence.evaluated_record_ids]
  outcome_values: [passed, failed]
```

These are plausible synthetic values matching the current carrier shape, not values read from a live run. Exact prompt bytes, delivery proof, model ingestion, and a complete transcript are unavailable.

## Repeated Requirement And Attempts

Status: Synthetic fixture values using current candidate, verification, and file-state record shapes. The cross-attempt comparison is Derived.

Requirement: `R-17: Preserve request identity across retries`

| Attempt | Builder output | Files observed at callback | Verification outcome |
|---|---|---|---|
| 1 | `candidate-01`: preserved payload but not request identity | `graph.py` changed | grade C; `Retry creates a fresh request identity after the first transport failure.` |
| 2 | `candidate-02`: added a fallback ID at the wrong lifecycle boundary | `graph.py` and `dispatch.py` changed | grade C; `The generated fallback ID is still regenerated inside the retry branch.` |

The file-state boundaries are whole-worktree observations at callback time, not node-exclusive causal deltas. The observed files support inspection but do not prove that either node alone caused every change or the grade.

## Evidence Inventory

Status: Synthetic fixture values using current typed graph-record and file-state shapes; limits are factual carrier boundaries.

| Evidence ID | Type | What it supports | Limit |
|---|---|---|---|
| `candidate-01` | candidate record | attempt 1 output identity and summary | summary is not a content diff |
| `file-state-01` | file-state record | whole-worktree paths observed after attempt 1 | not node-exclusive causality |
| `verification-01` | verification report | attempt 1 grade C and exact reason | verdict evidence, not proof of file causality |
| `candidate-02` | candidate record | attempt 2 output identity and summary | summary is not a content diff |
| `file-state-02` | file-state record | whole-worktree paths observed after attempt 2 | not node-exclusive causality |
| `verification-02` | verification report | attempt 2 grade C and exact reason | verdict evidence, not proof of prompt delivery |
| `authority-request-01` | authority request | `requested_authority: [graph:gap-plan-01:execute]`, target node `gap-plan-01`, reason, and pending state | command choices come from the authority decision contract; recorded decider text is provenance only |

Record IDs, node IDs, event positions, execution IDs, and attempt identities remain distinct. Selection of `verify-02` may reveal its cited records, but matching strings or temporal adjacency must not be presented as a cross-model identity join.

## Current Decision

Status: Synthetic fixture value using the Current graph decision request/state/action shape.

- Question: `Grant authority for one constrained recovery attempt after recording the request-identity requirement?`
- Display choices: Grant, Deny, Defer; command values: `granted`, `denied`, `deferred`.
- Recorded decider text is provenance only, not authenticated identity or permission evidence.
- Confirmation action: `Grant recovery authority`.
- Accepted feedback: `accepted, applying...`.
- Applying receipt: `Expected event 185 - accepted, applying...; projection not yet observed.` Current and last-confirmed projection position remain 184; 185 is expected receipt only.
- Projection-confirmed result: `Decision recorded; gap-plan-01 is ready.` at position 190, with `max_grants_reached` recorded and no lease granted.
- Projection-confirmed denial: `Decision recorded; recovery authority denied; gap-plan-01 remains blocked.`.
- Projection-confirmed deferral: `Decision recorded; recovery authority deferred; gap-plan-01 remains blocked.`.
- Stale variant: `Graph advanced from position 184 to 186. Refresh before deciding.`.
- Rejection variant: `Decision rejected: authority request is no longer pending.`.

The accepted response is not optimistic success. The represented result is complete only when the refreshed projection shows the recorded decision, `gap-plan-01` ready, the position-190 scheduler deferral audit, and no active lease.

## Proposed Steering

Status: Proposed steering capability; delivery proof is Unavailable because typed steering is not implemented.

- Instruction: `Preserve the original request_id outside the retry loop and prove both attempts share it.`
- Evidence references: `verification-02`, `candidate-02`, `file-state-02`.
- Scope: `gap-plan-01 and its future descendants`.
- Correction budget: `$3.00 estimated, proposed`.
- Primary control: `Send to planner - not available` (disabled).
- Delivery proof: explicitly unavailable because typed steering is not implemented.

This proposal must not be represented as sent, bound to a prompt packet, accepted by a planner, or applied as a graph patch. The current authority decision can permit constrained recovery; it does not create a steering command.

## Event Window

Status: Synthetic fixture values using current graph event-position and projection shapes.

This compact window is ordered evidence, not a complete causal ledger. It omits events outside positions 176-190 and does not claim that adjacent events caused one another.

| Graph position | Evidence |
|---:|---|
| 176 | `build-02` completed. |
| 177 | `candidate-02` accepted from attempt 2. |
| 178 | `file-state-02` accepted as the callback-time worktree boundary. |
| 179 | `verify-02` received the candidate and cited evidence. |
| 180 | `verification-02` accepted with `R-17` grade C. |
| 181 | `verify-02` completed. |
| 182 | `gate-01` created for constrained recovery authority. |
| 183 | `gate-01` became ready. |
| 184 | Pending decision projection exposed `authority-request-01`. |
| 185 | Authority decision `granted` recorded. |
| 186 | `authority-decision-01` accepted as the authority decision output record. |
| 187 | `gate-01` completed. |
| 188 | Scheduler emitted readiness for `gap-plan-01`. |
| 189 | `gap-plan-01` entered the `ready` node state. |
| 190 | `gap-plan-01` deferred by scheduler: `max_grants_reached`; it remains ready and no lease is granted. |

The REST decision route immediately runs `schedule_tick` with `max_grants=0`. The position-190 `node_deferred` event is audit evidence that no lease was granted; `SchedulerView.ready` still lists `gap-plan-01` because its node state is ready, while `LeaseView.active` remains empty.

The denial and deferral variants use the same decision-record sequence through position 187, followed by a refreshed projection in which `gap-plan-01` remains blocked with `authority_not_granted:gate-01`; they are not represented as unknown outcomes.

## Usage And Cost

Status: Synthetic fixture values using current graph usage and missing-rate shapes; the partial-total interpretation is Derived.

| Scope | Usage fact | Price status |
|---|---|---|
| `build-02` | measured execution cost `$2.14` | priced, measured |
| `verify-02` | tokens and latency recorded | unknown price |
| Run r314 | `$8.42` known across graph executions plus one unpriced graph execution | partial known graph-execution total; not a complete total |

Unknown price is never rendered as `$0`. The `$3.00` correction budget is an estimate for a proposed capability and is visually and semantically distinct from measured spend.

## State Variants

Status: Synthetic fixture variants using current decision/error and stream-connection shapes; steering delivery remains Unavailable.

| Variant | Decision state | Stream state | Required presentation |
|---|---|---|---|
| `Nominal` | `gate-01` pending at position 184 | connected | Enable current authority choices; keep proposed steering disabled. |
| `Stale proposal` | graph advanced from 184 to 186 | connected | Show `Graph advanced from position 184 to 186. Refresh before deciding.` and prevent submission. |
| `Validation rejected` | authority request no longer pending | connected | Show `Decision rejected: authority request is no longer pending.` and retain evidence context. |
| `Stream disconnected` | last loaded decision remains visible but freshness is unknown | disconnected | Remove `Live`; preserve selection and label evidence stale or disconnected. |

`Live` means event-stream connected only in every variant. It is not a health, completeness, or freshness guarantee.

### Current Lifecycle Guard

Status: Synthetic fixture using the current lifecycle guard shape; it is not a fifth selectable variant.

| Run status | Lifecycle action state | Required presentation |
|---|---|---|
| `stopping` | `Cancel unavailable while stopping` | Disable Cancel with the reason `Internal sweep completes transition; operator cannot cancel again.` |

## Screen Contract

The same seven screens and answers must be used for every concept comparison.

| Screen | Status | Operator question | Expected answer |
|---|---|---|---|
| 1. Fleet | Derived from synthetic fixture facts | What needs attention, based on observed facts? | Run r314 is the only fixture row with a human wait or pending authority decision; it has two failed `R-17` verification outcomes and a blocked final check. Runs r311-r313 show no pending human action. No row is called healthy. |
| 2. Position | Synthetic current-shape facts | Where is `r314`, and what is blocked? | At position 184, `SchedulerView.ready` contains `gate-01`, `blocked` contains `final-check`, `waiting_gates` contains `gap-plan-01`, and `waiting_resources` is empty. Completed nodes are stated separately, and `LeaseView.active` is empty. |
| 3. Attempts | Derived comparison | Why did attempt 2 fail, and was there a meaningful delta? | Both attempts received C. Attempt 2 still generated the fallback ID inside the retry branch. No current retry-information-delta detector exists; the judgment comes from the displayed records. |
| 4. Evidence | Synthetic current-shape facts with explicit limits | What is ground truth and what remains uncertain? | Candidate, verification, binding, prompt-summary, and file-state records establish fixture metadata and callback boundaries; they do not prove exclusive file causality, exact prompt bytes, delivery, model ingestion, or a complete transcript. |
| 5. Decision | Synthetic value using a Current action shape | What can the operator safely authorize now? | Grant, Deny, or Defer authority for the one constrained recovery attempt, mapping to `granted`, `denied`, or `deferred`. The Grant fixture reaches position 190 with `gap-plan-01` ready, `max_grants_reached`, and no lease; stale and rejected paths remain explicit. The compact Current lifecycle guard is `stopping`: Cancel unavailable while stopping because the internal sweep completes transition and the operator cannot cancel again. |
| 6. Steering | Proposed; delivery Unavailable | What new instruction should enter corrective work? | The proposed request-ID instruction is intended to create a delta only if a future typed-steering path delivers it. `Send to planner - not available` stays disabled and delivery cannot be verified. |
| 7. Ledger and cost | Synthetic current-shape facts; partial-total reading Derived | What ordered evidence and economic facts support the choice? | Positions 176-190 show the bounded sequence, including readiness followed by `max_grants_reached` with no lease; `build-02` cost `$2.14`, `verify-02` has an unknown price, and neither event order nor a partial graph-execution sum is overstated. |

Selection may change, but Comparison, Decision, and Steering evidence remains anchored to `(run_id=r314, node_id=verify-02)` and `verification-02`. If another node is selected, the concept must prominently state that graph selection and evidence anchor are distinct and provide `Select verify-02 evidence anchor`; that control selects `verify-02`, opens Audit, updates the hash, and removes the notice because selection then matches anchor. It must not imply the fixed evidence belongs to the other node. During one page session, full rerender restores semantic focus after screen navigation, variant change, node selection, and evidence-anchor selection; initial/hash load must not steal focus. Returning to Fleet may restore process-local scroll/focus; only screen, selected node, and variant are hash-restored, and scroll/focus do not survive reload. Attempt, pending decision, and freshness are fixture/projection-derived rather than URL-restored. Each Derived, Synthetic, Proposed, or Unavailable statement must retain its status and freshness label.

## Evidence Sources

Direct paths used as the factual and evaluation basis:

- Identity and selection boundaries: `research/ui-foundation/DECISIONS.md` (D1-D4) and `docs/jtbd/information-architecture.md` (Persistent context model).
- Directed topology, bindings, event order, and causality limits: `research/ui-foundation/agent-reports/02-graph-runtime.md` (Topology and direction; Events and projections; Important uncertainties).
- Action acceptance, resulting-state feedback, provenance-only decider text, and the absent typed steering command: `research/ui-foundation/DECISIONS.md` (D4, D8, D16) and `research/ui-foundation/agent-reports/04-api-actions-authority.md` (Graph decision, patch, retire/supersede, and requeue capability; Action feedback).
- File-state, prompt, transcript, event, usage, and causal evidence limits: `research/ui-foundation/agent-reports/05-evidence-telemetry.md` (Evidence inventory; Prompt, transcript, tool, and file boundaries; Usage, cost, pricing, and rollups).
- Current UI freshness, `Live`, continuity, cost-total, and result-feedback limitations: `research/ui-foundation/agent-reports/06-ui-projections.md` (Selection, URL, and continuity; Freshness, stale, error, and empty states; UI labels that exceed their evidence).
- Cost honesty and capability gaps: `research/ui-foundation/DECISIONS.md` (D9-D11, D16), `docs/jtbd/decision-information.md` (Confidence and honesty rules; Action feedback contract), and `docs/jtbd/jobs.md` (J6 and J7).
- Operator-loop questions, steering warning, and continuity requirements: `docs/jtbd/journeys.md` (Journeys B and C; Cross-journey continuity requirements).
- Same-scenario evaluation tasks, switching measures, capability honesty, and viability thresholds: `docs/jtbd/evaluation-rubric.md` (Required scenario tasks; Switching and clutter measures; Decision rule).
