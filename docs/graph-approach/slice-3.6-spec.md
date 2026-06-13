# Slice 3.6 — Human decisions, appeals & review-readiness

Size: L. Closes the §26 observability list and is the UI bridge to Phase 4
convergence (where the parent/child oversight layer is deleted in favour of the
graph's gate/appeal/review nodes). Surfaces the human-in-the-loop and
merge-readiness facts.

## Ground truth

- execution-graph-prd-plus.md §26 — "Human decisions pending"; "Appeals and
  oversight decisions"; "Review readiness and merge blockers".
- §15.4 Gate, §15.5 Appeal/Oversight, §15.7 Review lifecycles; §16
  `create_gate`/`create_appeal` patch ops; the planner-budget human gate (3.1).
- Existing: gate/appeal/review nodes appear in `project_node_states`; decisions
  recorded via `record_decision` events.

## Scope — what to build

### 1. API — decisions/appeals/review projection + endpoint

- Pure `project_decision_view(events)` →
  `{pending_gates: [{node_id, gate_type, prompt}], appeals: [{node_id, state,
  outcome}], review: {ready: bool, blockers: [...]}}` derived from gate/appeal/
  review node states + `record_decision` events.
- `GET /api/runs/{run_id}/graph/decisions` → `DecisionViewResponse`. Read-only;
  empty for non-graph runs.
- If a decision-submission path is required for the UI to *act* (approve/reject a
  gate), route it through `GraphController.handle_command("record_decision", …)`
  — the controller remains the sole append path (§28 rule 1). Submission is
  optional for v1; the read view is the minimum.

### 2. UI — decisions panel

- A "Decisions" section in `GraphPanel`: pending human gates (with the planner
  budget-exhaustion gate from 3.1 surfaced), appeals + their outcomes, and a
  review-readiness summary with merge blockers.
- If submission is in scope, an approve/reject affordance on pending gates that
  POSTs through the controller-backed endpoint.
- `useDecisionView(runId)` hook.

## Tests

### Unit — `tests/unit/test_graph_decision_view.py` (new)

Pure, over hand-built events:
- `test_decision_view_lists_pending_gates_and_appeals()` — pending gates,
  resolved appeals with outcomes, and review readiness/blockers classify
  correctly.
- `test_planner_budget_gate_surfaces_as_pending_decision()` — the 3.1
  budget-exhaustion gate appears as a pending human decision.

### Integration — `tests/integration/test_graph_decisions_api.py` (new)

- `test_decisions_endpoint_reflects_seeded_gates_and_appeals()` — seed a run
  with a gate + an appeal; endpoint returns them with correct states.
- (If submission in scope) `test_gate_decision_submitted_through_controller()` —
  approving a gate appends an accepted `record_decision`/gate-resolution event
  via the controller and unblocks the downstream node.
- `test_decisions_endpoint_empty_for_non_graph_run()`.

### Frontend — vitest

- Decisions panel renders pending gates, appeals, and review-readiness from
  fixture data; (if in scope) the approve/reject affordance calls the hook.

## Done when

1. Pure `project_decision_view` classifies pending gates, appeals + outcomes,
   and review readiness/blockers (unit-tested), including the planner budget gate.
2. `GET /graph/decisions` returns the view for graph runs; empty for non-graph.
3. UI decisions panel renders the three groups; (if in scope) gate approve/reject
   routes through `GraphController.handle_command` only.
4. Full suites green (unit/integration/vitest); ruff/pyright clean; kernel
   purity + `graph_runtime` boundary unchanged.

## Hard constraints (same as all slices)

- NO mocks/monkeypatching; hand-written fakes; frontend fixtures only.
- Real SQLite tmp dirs; never touch `orchestrator.db`.
- New projection is pure (`graph/`). Any decision submission appends ONLY via
  `GraphController.handle_command()` (§28 rule 1). `graph_runtime` boundary +
  kernel purity unchanged.
