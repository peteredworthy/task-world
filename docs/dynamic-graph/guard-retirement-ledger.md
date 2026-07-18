# Dynamic Graph Guard Retirement Ledger

This ledger records why incident-driven graph guards exist and what evidence is
required before changing them. Event-triggered driving is **not** a retirement
condition or prerequisite for any guard below. A guard retires only when its
specific behavior is replaced at the owning boundary and the cited incident
shape remains covered.

| Guard | Source | Incident | Behavior | Regression | Retirement condition | Disposition |
| --- | --- | --- | --- | --- | --- | --- |
| Recovery no-op assignment | Former `graph_runtime/recovery.py`; deletion recorded in W8 | A recovery assignment cancelled itself and created the appearance of recovery work without changing state. | None; it was dead code. | Full graph collection and recovery suites; source evidence in W8. | Already met: deletion leaves recovery outcomes unchanged. | **Retired.** Deleted before this ledger. |
| Progress-signature detector | Former `workflow/graph_driver.py` signature comparison; replacement `0b725a463` | Silent stalls required bounded detection, but a hand-built state signature duplicated projection facts. | Previously inferred progress from a tuple of selected projection fields. | `tests/unit/test_graph_driver_logic.py::test_driver_uses_event_position_to_detect_stuck_ready_node` | Already met: durable event position is the complete progress signal and preserves the same bounded stall behavior. | **Retired.** Replaced by the event-position guard. |
| Driver-owned pure outcome policy | `graph/projections.py::project_graph_projection_snapshot`, `project_graph_outcome`, `project_graph_completion_eligible`, `project_active_lease_wait_plan`; relocation `f0b6c237d`, duplicate removal `2ccd20bce` | Pure completion, blocker, retry-budget, and wait classification accumulated in the effectful driver and diverged from kernel projections. | Kernel projection APIs now classify graph outcome and driver wait policy; the driver only coordinates effects. | `tests/unit/test_graph_projections.py::test_graph_projection_snapshot_builds_driver_policy_views`, `::test_graph_outcome_policy_covers_completed_blocked_and_failed_runs`, `::test_active_lease_wait_policy_uses_nearest_deadline_and_execution_ids` | Already met: every driver caller uses the kernel API and no private compatibility copy remains. | **Retired from driver; retained as kernel policy.** |
| Full-projection fold mirrors | `graph/projections.py::_clone_projection`; `graph_runtime/store.py::_projection_from_events`; consolidation `23fa05e80` | Independently folded/cloned projection shapes omitted new fields and allowed read-model drift. | Reducer cloning is centralized and runtime rebuild delegates to canonical `build_projection`. | `tests/unit/test_graph_projections.py`, `tests/integration/test_graph_event_store.py`, `tests/integration/test_graph_node_detail_read_models.py` | Replace a mirror as soon as the canonical builder can serve the same boundary with parity coverage. | **Replaced.** Do not reintroduce hand-maintained folds. |
| Projection field-list mirrors | `graph/payload_registry.py`; `graph/projections.py::GRAPH_PROJECTION_PAYLOAD_FIELDS`; runtime store allowlists | Hand-maintained compact-read field mirrors previously omitted projection facts, including scheduler data. | Field sets are generated/guarded against actual projection consumers rather than accepted as compatibility lists. | `tests/unit/test_graph_payload_field_allowlists.py` | Replace whenever typed payload schemas can generate the set directly; until then exhaustive AST parity is mandatory. | **Replaceable/guarded.** No unguarded mirror is acceptable. |
| Main-worktree contamination detector | `workflow/graph_driver.py` around `dirty_paths` / `find_leaked_paths`; `git/contamination.py` | Agents escaped run worktrees (including repository-symlink cases) and dirtied the main checkout. | Snapshots pre-drive dirtiness and logs newly leaked paths as an isolation breach. | `tests/unit/test_git_contamination.py` | A mandatory execution sandbox must make writes outside the run worktree impossible, with a real escape-attempt regression. | **Load-bearing; retain.** Event-triggered driving is irrelevant. |
| Operator reopen marker | `workflow/graph_driver.py::GRAPH_OPERATOR_REOPEN_PAUSE_REASON` and `_reopen_failed_graph_lifecycle` | A failed kernel could either be explicitly reopened or be crash-window stranded while the run row was active; conflating them silently un-failed autonomous failures. | A persisted, consume-once marker authorizes only an operator resume to reopen the failed kernel. | `tests/integration/test_graph_run_driver.py::test_operator_resume_reopens_failed_graph_run`, `::test_driver_does_not_reopen_crash_window_stranded_active_run`, `::test_operator_reopen_marker_is_consumed_once` | Run-row and graph lifecycle become one atomic state machine with explicit durable operator identity and equivalent crash-window tests. | **Load-bearing; retain.** |
| Driver crash bridge | `workflow/graph_driver.py::GraphRunDriver.run` exception bridge | An escaping drive-loop error was logged and discarded, leaving an ACTIVE run with no driver or re-arm reason. | Persists `graph_driver_crashed` pause/error before re-raising so the failure is visible and resumable. | `tests/integration/test_graph_run_driver.py::test_driver_crash_bridge_persists_pause_and_reraises`; incident replay in `project_driver_db_locked_crash.md` | Executor supervision must durably transition every lost driver task and prove the stranded-ACTIVE crash window cannot recur. | **Load-bearing; retain.** |
| Stale-position and SQLite-write retries | `workflow/graph_driver.py::_handle_command_at_head`, `_drive_with_transient_retries`; `graph_runtime/dispatch.py::_handle_command_retry_stale` | Concurrent callbacks moved event heads and SQLite writers returned transient locked/busy errors, killing otherwise valid drive/callback work. | Re-reads stale positions and applies bounded backoff only for classified transient SQLite conflicts. | `tests/unit/test_graph_driver_logic.py::test_drive_with_transient_retries_retries_sqlite_locked_error`, `::test_driver_retries_locked_heartbeat_renewal_at_new_head`; `tests/unit/test_graph_dispatch_on_output.py::test_handle_command_retry_stale_retries_locked_operational_error_then_succeeds` | Storage/command APIs must absorb these races transactionally and retain bounded contention/replay tests; changing database engines alone is not proof. | **Load-bearing; retain.** |
| Future-outbox retry wait | `workflow/graph_driver.py::drive_to_quiescence`; `graph_runtime/outbox.py::earliest_pending_retry_at` | Deferred outbox rows were mistaken for no progress, causing hot loops or premature `graph_blocked`. | Sleeps until the earliest due retry before classifying a repeated event position as blocked. | `tests/unit/test_graph_driver_logic.py::test_driver_waits_for_future_outbox_backoff_before_declaring_blocked`; `tests/integration/test_graph_outbox_crash_points.py::test_recovery_preserves_future_backoff_until_due` | Dispatcher scheduling must wake the coordinator at the durable due time and preserve backoff across restart, with equivalent timing tests. | **Load-bearing; retain.** Event-triggered driving alone does not satisfy this. |
| Event-position no-progress guard | `workflow/graph_driver.py::drive_to_quiescence` (`previous_position`) | A runner could finish without callback/death evidence, leaving an active lease and a silently spinning coordinator. | Compares durable heads after a full pass, attempts bounded orphan recovery, then returns a blocked outcome. | `tests/unit/test_graph_driver_logic.py::test_driver_uses_event_position_to_detect_stuck_ready_node`, `::test_driver_recovers_orphaned_lease_and_reschedules_node` | Kernel/runtime must durably terminalize every dispatched execution and prove missing-callback and missing-process incident shapes cannot spin or strand a lease. | **Load-bearing; retain.** Event-triggered driving is explicitly not the prerequisite. |
| Lease renewal and recovery bounds | `workflow/graph_driver.py::_renew_running_expired_leases`, `_recover_orphaned_active_leases`, `MAX_NODE_RECOVERIES_PER_DRIVE` | Long W3 verifier replay exceeded the old TTL and valid callbacks were rejected stale; persistent orphaning generated fresh lease IDs and could retry forever. | Renews live executions and bounds orphan recovery by lease and node, preserving operator-visible `graph_blocked` on exhaustion. | `tests/unit/test_graph_driver_logic.py::test_driver_renews_expired_lease_when_execution_is_still_running`, `::test_driver_recovers_orphaned_lease_and_reschedules_node`, `::test_driver_stops_recovering_node_when_fresh_lease_ids_keep_orphaning` | Runtime liveness and kernel retry budgets must cover dynamically created nodes and long executions without stale rejection or unbounded spend. | **Load-bearing; retain.** |
| Submit-callback rejection surfacing | `graph_runtime/dispatch.py::_callback_conflict_reason` and `_submit_outputs` | Dispatch treated rejected or duplicate-of-rejected callbacks as successful submission, hiding lost agent output. | Converts conflict, stale, command, and duplicate prior-result rejection events into an execution error. | `tests/unit/test_graph_dispatch_on_output.py::test_callback_conflict_reason_reports_submit_rejection`, `::test_callback_conflict_reason_raises_on_duplicate_of_stale_rejection`; `tests/integration/test_graph_fr16_acceptance.py::test_fr16_stale_callback_rejection_is_readable` | The callback API must return a typed accepted/rejected result that the executor cannot misinterpret, including replayed idempotency outcomes. | **Load-bearing; retain.** |
| Compromised file-state binding guard | `graph_runtime/dispatch.py::_guard_no_pending_compromised_file_state_bindings` | Secret-bearing/compromised snapshots could be bound downstream while cleanup and supersession were still pending. | Refuses prompt/runtime hydration from a compromised, cleanup-pending file-state record. | `tests/integration/test_graph_outbox_crash_points.py::test_compromised_file_state_binding_is_refused_before_cleanup_completes`; `tests/integration/test_graph_gatekeeper_flow.py::test_gatekeeper_secret_verdict_scrubs_compromised_snapshot` | Binding selection must exclude compromised records by construction and prove cleanup-crash/restart cannot expose their snapshot identities. | **Load-bearing; retain.** |
| Startup process recovery | `graph_runtime/dispatch.py::reconcile_runtime`; `workflow/graph_recovery.py::select_graph_runs_to_rearm` | After restart, durable active leases referred to processes absent from the new process registry; stranded ACTIVE graph rows also needed selective re-arm. | Re-arms only progressed/recoverable graph runs, checks current process liveness, and records `agent_died` for still-active missing executions. | `tests/unit/test_graph_startup_rearm_selection.py::test_select_graph_startup_rearm_only_includes_graph_runs_with_progress`; `tests/integration/test_graph_runner_e2e.py::test_graph_runner_restart_marks_missing_builder_dead_and_redispatches`, `::test_reconcile_runtime_skips_lease_already_recovered_by_another_driver` | Durable runner ownership must transfer across restart or atomically emit death, with concurrent-recovery and stale-report regressions. | **Load-bearing; retain.** |
| Outbox redispatch | `graph_runtime/recovery.py::recover`; `graph_runtime/outbox.py::OutboxDispatcher` | Crashes after event append or side-effect start left pending/dispatching durable work without completion. | Redispatches eligible pending/dispatching rows idempotently, scoped by run and respecting retry due times. | `tests/integration/test_graph_outbox_crash_points.py::test_crash_after_append_before_outbox_starts_agent_restarts_dispatch`, `::test_recover_run_dispatches_only_matching_outbox_rows`, `::test_crash_after_agent_starts_before_start_ack_reports_awaiting_start_ack` | A replacement delivery system must provide equivalent durable at-least-once delivery, idempotency, run scoping, and crash-point proofs. | **Load-bearing; retain.** |
| Terminal recovery filtering | `graph_runtime/recovery.py::_run_ids` and `_TERMINAL_RUN_STATES` | Global startup replay could revisit completed/failed/cancelled runs, redispatch work, or parse obsolete/corrupt tails unnecessarily. | Skips terminal checkpoints and, when absent, filters by rebuilt terminal projection before recovery. | `tests/integration/test_graph_outbox_crash_points.py::test_recover_without_run_id_skips_terminal_snapshot_without_replay`, `::test_recover_without_run_id_skips_terminal_run_when_snapshot_missing` | Recovery enumeration must become terminal-exclusive at the storage query/index boundary with both checkpoint and checkpoint-missing tests. | **Load-bearing; retain.** |

## Review rule

Retirement requires source-bound replacement evidence and the incident-shaped
regression named in the row. Polling versus event-triggered coordination is an
orthogonal implementation choice: converting the driver to event-triggered
driving neither permits guard deletion nor must happen before a guard can retire.

## Independent verifier evidence

Task 11 Step 6 passed at source
`2aa951c5c8217866afff8171668835f7c5334b9e`: the full suite reported **4847
passed, 3 skipped, 3 warnings in 118.78s**; all three warnings were Python 3.12
`aiosqlite` default-datetime-adapter deprecations. `uv run ruff check .` was clean; `uv run
pyright` reported **0 errors, 0 warnings, 0 informations** plus the advisory
`v1.1.408 -> v1.1.411` update notice; and `git diff --check` was clean. The
verifier report lists only the pre-existing SDD scratch files as dirty.

## Final branch evidence

The fresh no-context Task 17 verifier, recorded at
`.superpowers/sdd/task-17-verifier-report.md`, passed exact source and final
evidence-commit predecessor `4da2e64e631b537b5bb69f4f2bb10c9db807316b`.
The earlier W8 guard evidence remains source-bound to baseline
`2ccd20bce78c8cb5620813c840bcff8b9d2bf304`, implementation
`8ad825cf259f2fc7f42ec886616085cab08703ce`, and independent verifier source
`2aa951c5c8217866afff8171668835f7c5334b9e`.

At the final predecessor, the full suite reported **4791 passed, 3 skipped, 3
warnings in 105.14s**; Ruff was clean; Pyright reported **0 errors, 0 warnings,
0 informations** plus the advisory `v1.1.408 -> v1.1.411` update notice; and
`git diff --check` was clean. Generated enums were current, Alembic head was
`zg1h2i3j4k5l`, **4794 tests** collected, and the targeted public-export/removal
checks reported **2 passed**. The warnings were the three Python 3.12
`aiosqlite/core.py:63` default-datetime-adapter deprecations named in the
verifier report.

Exact verifier dirtiness was modified `.superpowers/sdd/progress.md` and
untracked `docs/superpowers/plans/2026-07-18-migrate-claude-sdk-history.md`;
neither was in the verified source. The SDD verifier report has no separate
committed SHA, and this ledger does not invent the not-yet-created final
evidence commit SHA.

## Superseding post-whole-branch-review verification

The fresh post-review verifier report
`.superpowers/sdd/post-review-final-verifier-report.md` supersedes the
pre-final-review branch evidence above while preserving it as historical
evidence. It verified exact source
`b7e3b3f29f0d8e63d58ce2f1d0eb5b2d70cebb46`, whose final-review fix adds
corrected rejected-gate semantics, exact human-gate eligibility, nested
overflow restoration, and the corresponding fixture update.

At that source, the full suite reported **4792 passed, 3 skipped, and 3
deprecation warnings**; Ruff was clean; Pyright reported **0 errors, 0
warnings, and 0 informations** plus the advisory `v1.1.408 -> v1.1.411` update
notice; and `git diff --check` was clean. Generated enums were current,
Alembic reported the single head `zg1h2i3j4k5l`, **4795 tests** collected, the
targeted backend checks reported **20 passed**, and the UI GraphPanel decisions
suite reported **7 passed**. The three warnings were the Python 3.12
`aiosqlite/core.py:63` default-datetime-adapter deprecations named in the
verifier report.

The verifier's exact dirty state was only the untracked
`docs/superpowers/plans/2026-07-18-migrate-claude-sdk-history.md`; there were no
tracked dirty paths. The tested source is the SHA above, not the later
docs-only evidence commit. This note does not anticipate that commit's SHA.
