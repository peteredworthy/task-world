# Available Model

The underlying model already contains much more information than the UI currently displays. The main type is `ParentOversightSnapshot` in `src/orchestrator/workflow/oversight.py`, mirrored in frontend types at `ui/src/types/runs.ts`.

## Parent Oversight Fields

| Field | What it can explain | Current UI coverage |
| --- | --- | --- |
| `parent_status` | Whether the snapshot believes the parent is active, paused, completed, or failed. | Not shown directly. |
| `current_understanding` | Parent summary, next action, ready slices, blocked slices, required human action. | Not shown. |
| `target_inventory` | Tracked bugs, tests, files, artifacts, status, scope class, unresolved work. | Not shown. |
| `final_validation` | Final validation marker, report status, completion evidence. | Not shown. |
| `decisions` | Parent decisions such as selected slice, launch choices, accept/reject choices. | Not shown. |
| `slices` | Parent-created slice records and child links. | Legacy fallback count only. |
| `child_waits` | Waiting windows and child polling context. | Not shown. |
| `accepted_child_run_ids` | Which child runs have been accepted. | Used to disable accept action. |
| `accepted_children` | Acceptance records and metadata. | Not shown. |
| `rejected_child_run_ids` | Rejected child runs. | Not shown. |
| `abandoned_child_run_ids` | Abandoned child runs. | Not shown. |
| `merge_conflicts` | Conflict files/counts after attempted acceptance. | Not shown except action response path. |
| `max_child_runs` | Child run budget. | Not shown. |
| `child_count` | Total child runs. | Shown. |
| `child_counts` | Counts by child status. | Shown. |
| `child_summaries` | Child slice/status/evidence/blocking summaries. | Partially shown in a table. |
| `attempt_counts_by_slice` | Retry and attention distribution by slice. | Not shown. |
| `active_child_run_ids` | Children currently active. | Not shown. |
| `merge_queue` | Children eligible for acceptance. | Used for accept button. |
| `attention_items` | Child, slice, and parent attention reasons. | Partially shown, first five only. |
| `stalled_slices` | Slices over the stalled attempt threshold. | Not shown. |
| `illegal_state_reasons` | State integrity problems. | Not shown. |
| `terminal_guard` | Whether parent can complete and why not. | Partially shown. |
| `next_parent_action` | Deterministic next parent action. | Shown. |

## Run Fields Relevant to Hierarchy

| Field | What it can explain | Current UI coverage |
| --- | --- | --- |
| `parent_run_id` | This run is a child of another run. | Shown only in child detail banner. |
| `parent_slice_id` | The parent slice that created the child. | Shown only in child detail banner. |
| `routine_id` | Whether the run is the `super-parent` routine or a child routine. | Shown as routine metadata. |
| `pause_reason` and `last_error` | Why a run needs attention. | Shown in run detail, not grouped with oversight attention. |
| `worktree_path` and merge strategy | Where child work happened and how it can merge. | Standard run metadata only. |

## APIs Already Present

- `GET /api/runs/{run_id}/oversight` returns the computed parent oversight state.
- `POST /api/runs/{run_id}/oversight/refresh` refreshes deterministic oversight state.
- `GET /api/runs/{run_id}/children` returns child run summaries for a parent.
- `POST /api/runs/{parent_run_id}/children/{child_run_id}/accept` accepts a child run into the parent path.
- The general run list and detail endpoints already include `parent_run_id`, `parent_slice_id`, and `oversight_state`.

## Model-to-UI Implication

Most of the missing UI does not require inventing new backend concepts. The largest gap is presentation and workflow framing: the UI currently has enough data to expose parent mission state, child hierarchy, terminal blockers, inventory coverage, and evidence readiness, but only a compact subset is rendered.
