# Slice 4.2 Oversight Retirement Inventory

## Legacy Modules

Deletion order, leaves first:

1. `src/orchestrator/workflow/child_templates.py`
2. `src/orchestrator/workflow/oversight.py`
3. `src/orchestrator/workflow/oversight_projection.py`
4. `src/orchestrator/workflow/delegation/super_parent.py`
5. `src/orchestrator/workflow/parent_oversight.py`
6. `src/orchestrator/workflow/oversight_facts.py`

The generic delegation reducer remains for fan-out task bookkeeping. Its
super-parent policy export is removed.

## Live Entry Points Removed

- HTTP routes:
  - `POST /api/runs/{parent_run_id}/children`
  - `GET /api/runs/{parent_run_id}/children`
  - `POST /api/runs/{parent_run_id}/children/{child_run_id}/accept`
  - `POST /api/runs/{parent_run_id}/children/{child_run_id}/resolve`
  - `GET /api/runs/{run_id}/oversight`
  - `PATCH /api/runs/{run_id}/oversight`
  - `POST /api/runs/{run_id}/oversight/refresh`
- MCP tools:
  - `orchestrator_create_child_run`
  - `orchestrator_create_child_from_template`
  - `orchestrator_list_child_runs`
  - `orchestrator_accept_child_run`
  - `orchestrator_resolve_child_run`
  - `orchestrator_get_parent_oversight`
  - `orchestrator_update_parent_oversight`
  - `orchestrator_refresh_parent_oversight`
- UI API helpers and hooks for parent oversight refresh/read.

## Historical Compatibility

The following read-model/event-log surface remains read-only because existing
event logs may contain it:

- `Run.parent_run_id`, `Run.parent_slice_id`, and `Run.oversight_state`
- `ParentOversightFactsUpdated`
- `merge_oversight_patch` in the run-state projector

Historical runs therefore still load and replay their recorded facts, but no
live route, MCP tool, service hook, or UI panel can mutate the retired subsystem.
