# Slice 3.4 — Scheduler & leases view

Size: M. §26 requires a scheduler view (ready / blocked / waiting-resources /
waiting-gates) and a leases view (active + suspended). The pure projection
functions exist (`project_ready_nodes`, `project_leases`, `project_node_states`,
plus readiness/deferral reasons from `schedule_tick`'s `node_deferred` events);
no API/UI surfaces them yet.

## Ground truth

- execution-graph-prd-plus.md §26 — "Active and suspended leases";
  "Scheduler view: ready, blocked, waiting resources, waiting gates".
- §17 Readiness and Scheduling (deferral reasons), §18 resource/parallelism,
  §19 lease lifecycle (active/suspended).
- Existing kernel projections: `project_ready_nodes`, `project_leases`,
  `project_node_states`; `node_deferred` events carry `reason`
  (e.g. `missing_required_input:*`, resource/gate waits).

## Scope — what to build

### 1. Scheduler/leases projection helper (pure, in `graph/projections.py`)

- Add a pure `project_scheduler_view(events)` →
  `{ready: [...], blocked: [{node_id, reason}], waiting_resources: [...],
  waiting_gates: [...]}` derived from node states + the latest `node_deferred`
  reason per node (classify the deferral reason into the four buckets).
- Add `project_lease_view(events)` → active + suspended leases with
  `{lease_id, node_id, generation, state, execution_id, expires_at}` (extend
  `project_leases` output if needed; keep it pure).

### 2. API — extend the graph router

- `GET /api/runs/{run_id}/graph/scheduler` → `SchedulerViewResponse`
  (ready/blocked/waiting_resources/waiting_gates) and a `leases` section, built
  from the pure projections over the run's graph events. Read-only; 200 with
  empty buckets for non-graph runs.

### 3. UI — scheduler & leases panel

- Add a "Scheduler" tab/section to `GraphPanel` (or a `SchedulerView.tsx`):
  four columns/lists (Ready, Blocked w/ reason, Waiting resources, Waiting
  gates) + a leases table (lease id, node, generation, state, expiry).
- `useSchedulerView(runId)` hook.

## Tests

### Unit — `tests/unit/test_graph_scheduler_view.py` (new)

Pure, over hand-built event lists:
- `test_scheduler_view_buckets_deferral_reasons()` — nodes deferred for
  missing-input / resource / gate map to the correct buckets; ready nodes listed.
- `test_lease_view_reports_active_and_suspended()` — active and suspended leases
  surface with their fields.

### Integration — `tests/integration/test_graph_scheduler_api.py` (new)

- `test_scheduler_endpoint_reflects_seeded_run()` — seed a run with a leased
  worker + a deferred verifier; the endpoint shows the verifier blocked with its
  reason and the worker's active lease.
- `test_scheduler_endpoint_empty_for_non_graph_run()` — 200, empty buckets.

### Frontend — vitest

- `SchedulerView` renders the four buckets + leases table from fixture data.

## Done when

1. Pure `project_scheduler_view` / `project_lease_view` classify readiness,
   deferral reasons, and lease states correctly (unit-tested).
2. `GET /graph/scheduler` returns the scheduler + leases view for graph runs and
   an empty-but-valid response for non-graph runs.
3. UI scheduler/leases view renders the four buckets and the leases table.
4. Full suites green (unit + integration + vitest); ruff/pyright clean; kernel
   purity (new projections are pure) + `graph_runtime` boundary unchanged.

## Hard constraints (same as all slices)

- NO mocks/monkeypatching; hand-written fakes; frontend uses fixtures.
- Real SQLite tmp dirs; never touch `orchestrator.db`.
- New projection functions live in the pure kernel (`graph/`) — zero IO imports;
  keep kernel tests fast. Read-only; no graph mutations (§28 rule 1).
