# API, Actions, And Authority Audit

## Purpose

Audit the reachable REST, CLI, public orchestrator MCP, and per-execution graph
MCP surfaces as transports over domain capabilities. This report inventories
implemented command contracts, request validation, actors, enforced authority,
domain eligibility, durable effects, failures, races, reversibility, and audit
evidence. It uses scoped provisional keys only; it does not allocate canonical
IDs or design absent commands.

Status labels mean:

- **implemented**: reachable wiring and implementation were inspected.
- **tested**: repository tests exercise the stated behavior.
- **documented-only**: a source describes the behavior without sufficient
  reachability evidence.
- **inferred**: the conclusion follows from implementation but is not directly
  asserted or exercised.
- **unclear**: inspected evidence does not settle the proposition.

## Scope inspected

- Approved boundary and action rules:
  `docs/superpowers/specs/2026-07-23-ui-foundation-phase-0-3-design.md`, especially
  `Source Authority`, `Reality Investigations`, and `Action Contracts`.
- Closed demands owned by `api-actions-authority` in
  `research/ui-foundation/catalog/scope.yaml`.
- Decision demands in `docs/jtbd/jobs.md` and
  `docs/jtbd/decision-information.md`.
- REST assembly, authentication, schemas, errors, and mutable routers under
  `src/orchestrator/api/`.
- CLI commands under `src/orchestrator/cli/`.
- Public orchestrator MCP definitions and dispatch in
  `src/orchestrator/api/mcp/`, MCP scoping in
  `src/orchestrator/runners/mcp_scope.py`, and per-execution graph MCP tools in
  `src/orchestrator/graph_runtime/graph_mcp_tools.py`.
- Called workflow methods where needed to establish durable effect and evidence,
  principally `src/orchestrator/workflow/service.py`.
- API, CLI, MCP, graph-command, clarification, approval, recovery, review, and
  auth tests under `tests/integration/`, plus focused unit tests.

Read-only projections were inventoried where they provide action context or
confirmation. This report does not treat REST, CLI, and MCP as separate domain
capabilities merely because their envelopes differ.

## Key findings

### Authority model

| Provisional key | Status | Finding |
|---|---|---|
| `api-authn-jwt` | implemented, tested | All `/api/*` routers share one optional Bearer JWT dependency in `api.app.create_app`; `/mcp`, `/mcp-scoped`, and `/mcp-graph` use equivalent middleware. Auth is disabled by default. When enabled, possession of any valid token grants every read and mutation. Exact tests: `tests/integration/test_api_auth.py::test_auth_disabled_allows_all`, `::test_auth_enabled_rejects_missing_token`, `::test_auth_enabled_accepts_valid_token`, `::test_auth_enabled_rejects_invalid_token`, `::test_websocket_auth_with_query_param`, `::test_websocket_auth_rejects_bad_token`, `::test_mcp_auth_rejects_no_token`, `::test_mcp_auth_with_bearer`, and `::test_mcp_auth_rejects_invalid_token`. |
| `api-authz-roles` | implemented as absent, inferred | No endpoint checks JWT subject, role, scope, ownership, run membership, or action-specific permission. `auth.validate_token` returns claims, but router dependencies discard them. The system has authentication when enabled, not authorization. The auth tests above prove one token crosses the global gate; they do not independently test the absence of every possible role check. |
| `api-operator-assumption` | implemented | REST graph patch, decision, scheduling-after-decision, and requeue endpoints construct `Actor(kind=human, id="human-operator", role="operator")`; this is an endpoint assumption, not an authenticated product role. |
| `api-identity-attribution` | implemented, tested, conflicting | Legacy clarification endpoints use fixed identity `"user"`; task approve/reject/force-accept use `deps.get_current_user`; step approval accepts caller-supplied `approved_by`; graph decisions accept caller-supplied `decider`; requeue records fixed `human-operator`. These are incompatible attribution mechanisms and none is bound to JWT claims. Exact persistence/readback tests: `tests/integration/test_api_human_approval.py::test_approve_step_audit_trail`, `tests/integration/test_graph_decisions_api.py::test_record_authority_decision_updates_decision_readback`, `tests/integration/test_api_clarifications.py::test_respond_to_clarification`, and `tests/integration/test_graph_api.py::test_operator_requeues_failed_outbox_row_with_audit_event`. |
| `mcp-tool-scope` | implemented, tested | `/mcp-scoped/{tool-set}` limits registered tool names, and runner setup derives a phase/task allowlist. This is capability exposure, not actor authorization. The unscoped `/mcp` server registers all 11 tools regardless of phase. Exact tests: `tests/integration/test_mcp.py::test_tool_names`; `tests/integration/test_mcp_sse.py::test_scoped_mcp_sse_endpoint_exists_with_encoded_commas` and `::test_scoped_mcp_messages_endpoint_stays_under_scope`; `tests/unit/test_cli_tool_hints.py::TestCLIMCPInfo::test_orchestrator_mcp_json_scoped_to_available_tools`, `::test_orchestrator_mcp_json_scoped_to_workflow_tools_by_default`, and `::test_orchestrator_mcp_json_verifier_uses_verifier_workflow_tools`; `tests/unit/test_openhands_tool_filtering.py::TestOpenHandsMCPConfig::test_orchestrator_url_scoped_to_available_tools` and `::test_orchestrator_url_verifier_scoped_to_verifier_tools`. The transport tests establish scoped routing; they do not perform a full JSON-RPC forbidden-tool call. |
| `graph-mcp-execution-scope` | implemented, tested | `/mcp-graph/{token}` uses a generated live-execution token and closures bound to one execution. Planner/builder instances omit `graph_grade`; verifier instances include it. Token possession and closure binding constrain execution, while outer JWT auth remains global and optional. Exact tests: `tests/unit/test_graph_mcp_tools.py::test_builder_server_has_submit_graph_patch_and_macro_tools_but_not_grade`, `::test_verifier_server_has_graph_grade_tool`, `::test_submit_graph_patch_tool_calls_the_closure`, and `::test_create_work_region_tool_normalizes_and_calls_the_closure`; `tests/integration/test_graph_mcp_dispatcher.py::test_unknown_token_returns_404`, `::test_registered_token_forwards_to_its_app`, and `::test_unregistering_then_calling_returns_404`; `tests/integration/test_graph_mcp_second_runner_smoke.py::test_real_graph_mcp_server_is_reachable_through_the_real_dispatcher` and `::test_unknown_token_is_never_reachable`; `tests/unit/test_graph_dispatch_on_output.py::test_graph_mcp_route_mounted_during_execute_and_unmounted_after` and `::test_graph_mcp_route_unmounted_when_runner_execute_raises`. "Unguessable" follows token generation, not these fixed-token tests. |

The source demand `jobs.J6.authority` is therefore only partly supported. The
graph decision projection can show `requested_authority`, node detail can show
resource claims and allowed actions, and command validation enforces some graph
actor/domain rules. There is no implemented operator-role policy or per-action
authorization. An assumed operator must not be represented downstream as an
enforced permission.

### Transport and capability inventory

#### Run and lifecycle capability

| Provisional key | Surface and request | Domain eligibility and effect | Failure, race, evidence, reversibility |
|---|---|---|---|
| `action-run-create` | REST `POST /api/runs` with `CreateRunRequest`; CLI `runs create` with Click options and key/value maps. | Creates a draft run. REST requires exactly one routine source, selectable runner types, valid execution/merge modes, runner config fields, and selected Codex model. CLI discovers local routines and persists directly. | REST returns 422/404/runner errors. CLI validation is narrower and bypasses API request validation. Durable run row and creation events are available. Deletion is separate and status-limited. |
| `action-run-start` | REST `POST /runs/{id}/start`; CLI `runs start`. | REST enqueues `RUN_START` and returns 202 before transition. CLI calls `WorkflowService.apply_start_run` directly and commits synchronously. | **Transport divergence:** the CLI bypasses the lifecycle signal queue. REST response is command acceptance/current read model, not proof of resulting active state. Domain transition rejects illegal state. No request source version. |
| `action-run-pause` | REST and CLI wrapper. | Cancels the active executor first, then enqueues pause through `WorkflowService.pause_run`; rejects `STOPPING`. | 202 acceptance precedes consumer-applied state. Cancellation-before-enqueue creates an observable interval. Child cancellation helper is currently a no-op. Resume is the operational inverse, but work lost during process cancellation is not reversed. |
| `action-run-resume` | REST `ResumeRunRequest` optionally selects a new runner/config and `continue` or `reset_worktree`; CLI exposes runner/config but not strategy. | Requires resumable domain state and enqueues resume. A retired runner requires explicit replacement. | 409 for stopping/invalid transition. Reset-worktree may discard file state and is not itself undoable through this command. No expected run version. |
| `action-run-cancel` | REST and CLI wrapper, no body/reason from these surfaces. | Rejects `STOPPING`, cancels executors, enqueues cancellation; graph mode additionally drives graph cancellation to terminal. | Terminal/destructive. No confirmation contract at API level, no client source version, and no direct uncancel. Recovery is a different capability and does not make cancellation reversible. Graph and legacy timing differ. |
| `action-run-recover` | REST `RecoverRequest`: target task, additional attempts, optional runner, checklist preservation, guidance, branch reset. | Only failed or paused legacy runs; rewinds target/downstream tasks, optionally resets branch, adds attempt budget, records guidance, and leaves run paused as `recovered`. | 404/409 for missing task, illegal state, or worktree reset. Emits `run_step_backward`, `task_reverted`, task/attempt snapshots, and run status evidence. This is a compensating rewind, not restoration of all external effects. |
| `action-run-delete` | REST `DELETE /runs/{id}`. | Deletes non-active/non-paused runs, with one narrow startup-orphan exception. | 409 otherwise. Destructive and no undo. No action-specific authorization or expected version. |
| `action-transition-back` | REST `BackwardTransitionRequest(target_step_index >= 0, reason?)`. | Rewinds to an earlier legacy step and resets skipped tasks according to workflow service. | Domain errors; no expected version. Durable workflow events provide evidence. Not a general undo because produced files/external effects are not promised to revert. |

CLI `pause`, `resume`, `cancel`, `status`, `branch-status`, `back-merge`, and
`merge-back` are REST wrappers, but they do not accept a Bearer token. `runs
watch` likewise does not add the WebSocket `?token=` required when auth is
enabled. These commands work in the default auth-disabled deployment and fail
against an auth-enabled server unless transport behavior is changed outside the
implemented CLI.

#### CLI database maintenance capability

These commands are local process/operator surfaces. They bypass REST auth,
domain authorization, the signal queue, and API action evidence.

| Provisional key | Input validation and preconditions | Effect and failures | Concurrency, reversibility, and audit evidence |
|---|---|---|---|
| `cli-db-create-backup` | `orchestrator [--db PATH] db create-backup [--notes TEXT] [--backup-dir PATH]`. Click parses paths but does not require the backup directory to pre-exist. The command and `db.recovery.backup.create_backup` both reject a missing source DB. It resolves the default JSONL journal path from the DB path. | Creates the backup directory, uses `shutil.copy2` to copy the SQLite file, then scans active/archived journal segments and writes `orchestrator-{UTC-second}.backup-meta.json` with source backup path, timestamp-derived ID, journal marker, journal path, and free-form notes. CLI catches `BackupError`; ordinary copy/write `OSError` is not wrapped by the implementation. Primitive tests: `tests/unit/test_backup.py::test_create_backup_copies_db_and_writes_metadata`, `::test_create_backup_with_journal_captures_sequence`, and `::test_create_backup_missing_db_raises_error`. No test invokes the Click command. | No SQLite online-backup API, transaction, server-lock check, or quiescence is used. The DB copy occurs before journal scanning, so concurrent writes can make the copied DB and later marker describe different instants. UTC-second IDs can collide/overwrite under same-second calls. The operation does not mutate the source; reversal means deleting the backup manually. Backup file plus metadata are audit artifacts, but there is no event, authenticated actor, checksum, or durable command record. |
| `cli-db-restore-backup` | `db restore-backup BACKUP_META_PATH [--target-db PATH]`; Click requires only that the metadata path exists. `restore_backup` parses JSON, takes `db_path` from metadata, falls back to the metadata directory by basename, and rejects missing/unreadable metadata or backup. It does not validate a checksum, SQLite integrity, schema version, journal continuity, or containment of either path. | Creates target parent directories and `shutil.copy2` overwrites the target DB. It returns source metadata and tells the operator to replay after the marker, but performs no journal replay. CLI catches `BackupError`; malformed required metadata keys and copy errors may escape that type. Primitive tests: `tests/unit/test_backup.py::test_restore_backup_copies_db_back` and `::test_restore_backup_missing_meta_raises_error`. No test invokes the Click command. | Unlike rebuild, restore does not inspect `.orchestrator/server.lock`; replacing a DB used by a running server is not prevented. Copy is not staged to a temporary file plus atomic rename, and no automatic pre-restore backup exists. Reversibility requires restoring another independently retained backup. Metadata is provenance for the source backup, not evidence that replay occurred or that the target safely reopened; no operator/event record is written. |
| `cli-db-rebuild-projections` | `db rebuild-projections [--db PATH]`. It refuses execution only if `<db-parent>/.orchestrator/server.lock` exists; it does not validate lock ownership/freshness or independently verify no process has the DB open. It does not explicitly require an existing DB before creating an engine. | Reads all `events_v2`, attempts `deserialize_event`, silently drops every event that raises, registers only `RunLifecycleProjector`, `RunStateProjector`, and `TaskStateProjector`, deletes projection checkpoints/tasks/runs, rebuilds, and commits. The clear/replay is in one SQLAlchemy transaction, so a raised rebuild error should roll it back; engine disposal is guaranteed. Underlying registry behavior is tested by `tests/unit/test_projection_rebuild.py::test_rebuild_all_restores_run_status`, `::test_rebuild_all_restores_run_lifecycle_projector`, and `::test_rebuild_resets_checkpoint_to_zero`. No test invokes this CLI orchestration, its lock check, table deletion, or malformed-event skipping. | A stale lock blocks safe work and a missing lock does not prove exclusivity. Concurrent server writes/processes can race if the advisory file is absent. Re-running can reconstruct these selected projections from the same deserializable stream, but it cannot recover silently skipped/unsupported events and is not an inverse of a bad rebuild. Source events remain the recovery evidence; stdout counts are ephemeral, and no rebuild event/report, skipped-event list, backup prerequisite, or operator identity is persisted. |

#### Remaining CLI surface inventory

| CLI surface | Classification and boundary |
|---|---|
| `serve --host --port [--reload]` | Operational process launcher, not a domain command. It invokes `uvicorn.run("scripts.serve:app", ...)`, may bind a network listener and spawn reload processes, and persists whatever the app subsequently persists. Click validates `port` as an integer but imposes no range; auth behavior comes from app configuration, not CLI options. Only registration/help is tested by `tests/integration/test_cli.py::test_serve_command_is_registered`; startup, bind failure, shutdown, and reload races are unexercised here. |
| `agents detect` / `agents list` | Observational runner discovery (`list` invokes `detect`), returning availability, detail, and install hints from a real `ToolDetector`. It may inspect local executables/services but writes no orchestrator domain state in this command. No command-level test was found; detector logic has separate tests outside this CLI contract. |
| `runs list` | Reads the selected SQLite DB directly through `RunRepository`, but also calls `init_db`, so a read-looking command can create/migrate the DB. Repo filter wins over status when both are supplied; status is converted to `RunStatus` only when repo is absent. Exact smoke tests: `tests/integration/test_cli.py::test_runs_list_empty` and `::test_runs_list_json`. |
| `runs status`, `runs watch`, `runs branch-status` | Read-only remote projections/stream after connection: run JSON, WebSocket events, and git branch status. They do not mutate domain state, but lack Bearer/query-token options and therefore are unavailable against auth-enabled endpoints as implemented. `test_runs_status_via_api` explicitly does not invoke the status command; no command-level watch/branch-status test was found. |
| `routines list`, `routines show`, `routines validate` | Local file discovery/read/validation, except `show --url` is an unauthenticated REST read. They do not edit/archive routine source. Exact command tests: `tests/integration/test_cli.py::test_routines_list`, `::test_routines_show_local`, `::test_routines_validate`, and `::test_routines_validate_invalid`. |
| `repos list`, `repos show`, `repos branches` | Local filesystem/git reads only; CLI has no add/remove command. `--repos-dir`, repository name, glob pattern, `--local-only`, and `--limit` shape readback; `limit` is not constrained positive by Click. Exact tests include `tests/integration/test_cli_repos.py::test_repos_list_empty`, `::test_repos_list_with_repo`, `::test_repos_show`, `::test_repos_show_not_found`, `::test_repos_branches`, `::test_repos_branches_with_pattern`, `::test_repos_branches_local_only`, and `::test_repos_branches_not_found`. |

JSON versus human formatting, aliases, and help-only group commands are not
separate capabilities. All consequential CLI mutations are covered above or in
the run/approval/branch tables; the remaining exclusions are bounded to process
launch or observational reads/validation.

#### Legacy task, approval, clarification, and retry capability

| Provisional key | Surface and request | Domain eligibility and durable effect | Failure, race, evidence, reversibility |
|---|---|---|---|
| `action-task-phase` | REST start, submit, complete-verification; checklist `PATCH`; grade `PUT`. Public MCP get/update/submit/grade maps to the same workflow service family. | Legacy-only. Task state, checklist status, gate checks, and grades control progression. REST submit/check-verification enqueue signals after synchronous checks. MCP submit calls `submit_for_verification` directly. | 404/409/422 for identity, transition, gate, worktree commit, or validation errors. **Transport divergence:** REST signal application and MCP direct transition have different acceptance/result timing and race behavior. Workflow events and attempt snapshots are durable evidence. |
| `action-task-approval` | REST task `approve`, `reject`, `force-accept`; bodies contain optional comment/reason only. | Approve completes a pending task; reject returns it to building; force-accept bypasses grades from failed/building/verifying and may complete the run. | State transition checks provide domain eligibility. Fixed/injected `user` identity is not role authorization. ApprovalDecision events are durable. Force-accept has no undo and is high-consequence. |
| `action-step-approval` | REST step `approve` with caller-supplied `approved_by`; CLI interactive `runs approve`. | Current actionable step must have a human approval gate. Records `StepHumanApprovalRecorded`, may enqueue resume, and may spawn an executor. Repeated approval is tested as last-write-wins by `tests/integration/test_api_human_approval.py::test_approve_step_multiple_times`; audit fields are exercised by `::test_approve_step_audit_trail`. | 404/409 for absent/non-current/non-gated step. No expected version. **Tested contradiction:** on legacy runs, answering "no" in CLI still posts to the approve-only endpoint; `tests/integration/test_cli_approve.py::test_legacy_run_keeps_step_approval_no_answer_behavior` locks in this behavior. Graph approve/reject payloads are separately exercised by `::test_graph_run_approves_pending_human_gate` and `::test_graph_run_discovers_and_rejects_pending_human_gate`. There is no legacy step-deny/defer command. |
| `action-step-skip` | REST step `skip`, no body/reason. | Only a run paused at `manual_gate`, only current actionable step. Marks step skipped/completed and resumes or progresses to another gate. | 409 for stale/wrong context. Emits `StepSkipped` and status/progression events. No undo endpoint; transition-back is not documented as an exact inverse. |
| `action-clarification-create` | REST `CreateClarificationRequest`; public MCP `orchestrator_request_clarification`. | Builder/verifier creates typed questions, transitions task to pending user action, pauses the run, and records request. REST requires typed options by question type; MCP additionally rejects finite-choice prose disguised as free text. | Schema/service transition failures. Request ID, timestamps, questions, pending action, and event are evidence. MCP returns an explicit stop instruction. |
| `action-clarification-respond` | REST response with answer variants plus top-level skip fields; CLI interactive wrapper. | Records answers, appends a Q&A artifact, compresses decisions into run config, clears pending state, resumes only clarification-paused runs, and can respawn the agent. | `StaleDataError` maps to 409, but the artifact append occurs before event commit. Required-answer guard is an empty `pass`; answer schemas do not enforce that required questions are answered, selected values belong to options, or numeric bounds apply. There is no expected request version. Durable response event/config/artifact exist, but retries could duplicate file content before DB conflict settles. No answer revision/undo command. |
| `action-recovery-outcome` | REST/MCP `complete-recovery` with `retry`, `skip`, or `abandon` plus notes. REST body uses unconstrained string and returns 400; MCP schema enum and handler check it. | Only task state `recovering`. Retry creates an attempt and resumes; skip completes and advances; abandon fails. | 409 domain transition. Task/run status and attempt snapshot events are durable. Retry is not idempotent once state changes. Skip/abandon have no direct inverse. |
| `action-fanout-retry` | REST task `retry`, no body. | Failed fan-out child only; targeted SQL resets child/parent and may enqueue run pause. | Designed to avoid clobbering concurrent child sessions, but no client source version. Emits task status and oversight evidence. Not a generic failed-task retry and cannot carry changed conditions. |
| `action-escalate` | REST/MCP requirement escalation with requirement ID and reason. | Marks requirement escalated and pauses legacy run for human review. | 404/409 on missing identity/invalid phase. Events and pause reason are evidence. Resume/intervention is separate. |

`jobs.J3.exact-question` is current for clarification requests and partly current
for graph/legacy gates. `jobs.J3.alternatives` is present when clarification
options or graph gate options were recorded, but legacy step approval exposes
only approval and the CLI fabricates a reject choice that does not reject.
`jobs.J3.reversibility` is not a shared field or projection; it must be derived
per action from the concrete contracts above, and many decisions have no inverse.

#### Graph decision, patch, retire/supersede, and requeue capability

| Provisional key | Surface and request | Domain eligibility and durable effect | Failure, race, evidence, reversibility |
|---|---|---|---|
| `action-graph-decision` | REST `POST /graph/decisions` reuses strict `RecordDecisionCommand`: approval, authority, or oversight; typed decision set; node; decider; optional scope/expiry/reason/record ID. CLI handles pending human-approval gates only. | Graph controller validates target kind, decision type/value, graph state, and actor/domain rules. Accepted authority/approval can produce decision records, bind inputs, release leases, change node state, and make successors ready; rejection can dead-end required inputs. | 404 for no graph; 409 for stale projection or command rejection; 422 for malformed/invalid decision. Endpoint reads current position itself, so the client supplies no expected graph version. Durable graph events and decision records give identity/state evidence; response includes events and refreshed decision view. No decision-reversal command. Caller-supplied `decider` is not bound to auth. |
| `action-graph-patch` | REST operator `POST /graph/patch` with optional patch ID, optional nonnegative base position, strict ops, optional rationale record. Per-execution graph MCP exposes raw patch plus eight macros, including `retire_or_supersede`. | Controller validates patch and graph invariants. REST stamps human operator context; MCP callbacks bind a node execution and normalize macros into the same patch envelope. Accepted patch appends patch and topology events. | 404 no graph; 409 stale/rejected; 422 strict fields. Client base position supports stale-base validation for patches. Patch attempts projection exposes accepted/rejected event IDs, diagnostics, read-set differences, and created topology IDs. No generic patch rollback; corrective patches are new effects, not undo. |
| `action-retire-supersede` | Per-execution graph MCP macro; operator can express equivalent low-level ops through raw REST patch if validator permits. | Agent macro requires target/action and optional replacement ops/rationale, then graph validation controls legal topology effects. | This is not a standalone operator REST contract. Evidence is the normalized patch attempt/events. Reversibility depends on a subsequent validated patch and is not guaranteed. Assisted operator UI remains absent. |
| `action-outbox-requeue` | REST `POST /graph/outbox/requeue/{event_id}`, constrained path IDs. | Exact row must belong to run and be failed. One `session.begin()` transaction resets status/attempts/error/backoff and appends `outbox_requeued`; dispatcher may execute it again. `tests/integration/test_graph_api.py::test_operator_requeues_failed_outbox_row_with_audit_event` exercises the successful row change, audit event, and later dispatch. | 404/409/422 are exercised by `tests/integration/test_graph_api.py::test_operator_requeue_failed_outbox_row_rejects_invalid_requests`. `::test_requeue_audit_append_translates_stale_position_to_conflict` proves stale append translation in the helper, but no test injects that stale race through the full endpoint and then asserts row rollback. Endpoint-level rollback is therefore implemented/inferred from the enclosing transaction, not directly tested. Event records prior error/attempts and fixed operator. Requeue deliberately risks duplicate work according to downstream idempotency; no API preview or idempotency key. It is repeatable only after another failure, not reversible. |

Raw graph patches are **not** typed steering. `retire_or_supersede` is an
agent-scoped patch macro, not proof that an operator can inject new knowledge
into future prompt packets. No `steer`, `directive`, or steering-patch command
was found under `src/orchestrator/`.

#### Repository, review, source/configuration, and file effects

| Provisional key | Implemented commands | Safety and evidence boundary |
|---|---|---|
| `action-branch-sync` | REST/CLI back-merge, merge-back; REST review revert-back-merge. | Back-merge requires active/paused and may leave conflicts in progress. Merge-back requires completed and no failed readiness gates, then mutates source branch. Revert-back-merge only reverses a merge commit at worktree HEAD. These are git effects without per-action auth or client source version. |
| `action-review-prune` | REST prune preview/apply and revert-file. | Preview is non-mutating. Apply mutates files and creates commits; emits `PruneApplied`. The response `event_id` is a fresh UUID generated after emission and is not the persisted event ID, so it does not satisfy durable feedback identity. File revert creates a commit but emits no action event in the route. Git commits provide partial audit/reversal evidence. |
| `action-conflict-resolution` | REST per-block ours/theirs/manual resolution; agent conflict resolution dispatch. | Requires unresolved conflict file or existing conflicts. Manual route stages files and emits `ConflictResolved`; agent route emits `AgentFixStarted`. File path is checked against git's unresolved list. Agent dispatch accepts runner override. No actor authorization. |
| `action-test-run` | REST async review test using routine `auto_verify` commands. | Requires configured commands and no concurrent run; emits start/completion events and returns/polls by test-run ID. This validates work but does not authorize merge. |
| `action-env-files` | REST revert managed env files and copy snapshots to caller-supplied target. | Literal snapshot mode and snapshot ID pattern exist, but `worktree_path` and `target_dir` are caller-supplied filesystem paths. No route-level containment, run ownership, or role authorization is visible. Effects are filesystem writes; response lists files, with no durable action event established here. |
| `action-repository-admin` | REST add clone/symlink and destructive remove; CLI only lists/shows. | URL scheme and one-of URL/path validation exist. Repository name path parameter is joined directly to repos path; removal recursively deletes a non-symlink directory. No per-action authorization, confirmation token, active-run precondition, audit event, or undo. |
| `action-agent-policy` | REST agent create/update/delete/reset prompt and runner model-profile default replacement. | This is the current source-changing surface closest to "change prompt/policy." It affects future resolution, with ordinary schema/name checks. It does not preview cohort impact, version policy, or steer live runs. DB rows/timestamps are evidence, but no operator identity/audit event is established by the routes. |
| `action-routine-archive` | REST archive/unarchive only; CLI validates/reads routines. | Changes routine visibility metadata, not routine source content. Source routine/prompt/policy editing with preview/versioning is not implemented as one unified action. |

### Validation and failure contract

- **implemented, selected cases tested:** Shared Pydantic schemas validate many
  constrained values. Exact boundary tests include
  `tests/integration/test_cli.py::test_runs_create_rejects_non_selectable_agent_runner`,
  `::test_runs_create_explicit_legacy_opt_in`,
  `tests/integration/test_graph_api.py::test_operator_graph_patch_rejects_noncanonical_payload_fields`,
  `tests/integration/test_graph_decisions_api.py::test_record_decision_rejects_invalid_decision_at_api_boundary`,
  `::test_record_decision_rejects_removed_decision_aliases_at_api_boundary`,
  `::test_record_decision_restores_http_field_constraints`,
  `tests/integration/test_api_clarifications.py::test_create_clarification_multi_select_empty_options_returns_422`,
  `tests/integration/test_api_review_validation.py::test_diff_invalid_scope_returns_422`,
  and `::test_diff_files_invalid_scope_returns_422`.
- **implemented limitation:** `ApiModel` does not set `extra="forbid"`; strict
  rejection depends on inherited domain schemas such as graph command payloads.
  Several request models use free strings and endpoint-body conversion instead
  of boundary enums: complete-recovery outcome, review conflict choice, diff
  scope, run-list status, and legacy pending action type.
- **implemented limitation:** Several filesystem-affecting fields are raw paths:
  repo local path, env worktree/target paths, review file path, and git refs.
  Some are checked by downstream git/file functions, but a uniform boundary
  containment contract is absent.
- **implemented:** Domain exceptions generally map to 404 identity errors, 409
  state/gate/lock/stale conflicts, 422 request/gate-check failures, 503 runner
  unavailable, and 500 execution/git errors. Error bodies are not uniform:
  domain handlers use `error`, while endpoint exceptions use `detail`.
- **implemented limitation:** MCP tools return JSON strings and sometimes encode
  failure as a successful tool result with `error`/`hint`; REST uses HTTP status.
  Therefore "accepted/rejected" feedback is transport-specific.

### Race, idempotency, and action feedback

- **tested:** Graph append expected-position and race handling are exercised by
  `tests/integration/test_graph_event_store.py::test_unique_version_conflict`,
  `::test_unique_constraint_race_surfaces_stale_projection_error`, and
  `tests/integration/test_graph_controller_transactions.py::test_handle_command_raises_stale_projection_error_when_position_moves_before_write`.
  Atomic rejection/rollback is exercised by
  `tests/integration/test_graph_event_store.py::test_append_events_rejects_malformed_accepted_record_atomically`
  and `tests/integration/test_graph_read_models.py::test_graph_read_models_roll_back_with_event_append`.
  Patch requests can carry `base_graph_position`; graph decisions cannot carry a
  client-observed source position.
- **implemented, partly tested:** Requeue's row update and audit append share one
  DB transaction. `tests/integration/test_graph_api.py::test_operator_requeues_failed_outbox_row_with_audit_event`
  proves the successful effect/evidence/dispatch path, and
  `::test_requeue_audit_append_translates_stale_position_to_conflict` proves the
  helper's stale translation. Full endpoint rollback after an injected stale
  append is not tested. General event/outbox atomic rollback is separately
  exercised by `tests/integration/test_graph_outbox_crash_points.py::test_events_and_outbox_rows_commit_atomically_on_outbox_failure`
  and `::test_controller_rolls_back_events_when_dispatch_outbox_insert_fails`.
- **tested:** A stale legacy clarification does not reopen an advanced task in
  `tests/integration/test_clarification_workflow.py::test_respond_to_legacy_stale_clarification_does_not_reopen_completed_task`;
  response event persistence is exercised by `::test_clarification_responded_event_emitted`.
  The route's explicit `StaleDataError` to 409 branch has no direct injected-race
  test located. File append occurs outside the DB transaction before conflict
  resolution, so exact once-only artifact evidence is unclear.
- **tested contradiction:** Step approval is last-write-wins in
  `tests/integration/test_api_human_approval.py::test_approve_step_multiple_times`.
  This is not idempotency tied to a decision ID or source version.
- **implemented:** Lifecycle and REST task progression often return command
  acceptance/current status before queued signals apply. Polling activity/run
  state is needed for resulting state; responses do not consistently state next
  expected activity or a recovery path.
- **implemented:** Graph decision responses are the strongest feedback contract:
  accepted command, emitted durable event IDs, graph position, resulting
  decision view, and scheduler effects. Rejections return a reason but not a
  refreshed state/recovery object.
- **implemented limitation:** Most destructive REST actions do not accept an
  idempotency key, expected entity version, or confirmation token. Duplicate
  safety depends on current domain state, unique constraints, or git behavior.

### Closed-scope demand disposition

| Scope demand | Audit disposition |
|---|---|
| `jobs.J3.exact-question` | **partial/current by action:** clarification questions and graph gate prompts are implemented; some legacy approvals provide sparse context. |
| `jobs.J3.alternatives` | **partial:** clarification/graph options can exist; legacy step approval has no deny/defer endpoint and the CLI no-choice still approves. |
| `jobs.J3.reversibility` | **gap as a shared claim:** action-specific reality is known, but no consistent field/projection communicates it. Many effects are irreversible through current commands. |
| `jobs.J6.alternatives` | **partial:** lifecycle, recovery outcomes, graph decisions/patches, and requeue exist, but no unified eligible-action projection. |
| `jobs.J6.expected-effect` | **partial:** descriptions, some gate consequences, previews, and graph response events exist; many endpoints do not return predicted/next effects. |
| `jobs.J6.scope` | **partial:** run/task/node/patch/outbox identifiers scope commands, but filesystem/admin actions can accept broad caller paths and there is no common blast-radius contract. |
| `jobs.J6.authority` | **gap for operator policy/enforcement:** optional global auth and domain eligibility exist; role-based authorization does not. |
| `jobs.J6.reversibility` | **gap as a current projection:** per-command compensations vary and are not consistently declared. |
| `jobs.J8.interventions` | **partial evidence, no unified count:** graph/workflow/review events record several interventions, but no inspected API defines a complete cross-mode intervention taxonomy or count. |
| `journeys.continuity.action-safety-fields` | **gap:** no common action response exposes scope, consequence, reversibility, authority, and confirmation together. |
| `decisions.approve-gate-patch` | **current but split:** graph approval/authority decisions, raw graph patch, legacy task decisions, and approve-only step gates are separate. Deny/defer support is graph-specific. |
| `decisions.answer-clarification` | **current with validation gaps:** exact request/response records and resume behavior exist; required-answer and value-membership validation are incomplete. |
| `decisions.retry` | **current but plural:** recovery retry, run recovery, and fan-out retry are distinct; changed-condition evidence is not required. |
| `decisions.lifecycle` | **current:** pause/resume/cancel are reachable, with asynchronous acceptance and mode-specific effects. |
| `decisions.retire-supersede` | **partial/current machinery:** graph MCP macro and raw patch machinery exist; no dedicated operator action or guaranteed rollback. |
| `decisions.requeue` | **current for failed graph outbox rows:** no unified failed-work requeue action beyond that concrete endpoint. |
| `decisions.steer-context` | **gap:** no typed directive/context injection command found. |
| `decisions.apply-steering-patch` | **gap:** raw graph validation exists, but no steering proposal/provenance/binding command contract exists. |
| `decisions.change-source` | **partial:** agent prompt/default policy CRUD and routine archive exist; source routine editing, preview/versioning, and impact analysis are not unified. |
| `feedback.command-accepted-rejected` | **partial:** HTTP status/tool result usually indicates acceptance, but queued acceptance is not resulting state and error shapes vary. |
| `feedback.failure-race-recovery` | **gap/partial:** 409 stale/conflict reasons exist for selected actions; refreshed state and recovery guidance are not systematic. |

## Important uncertainties

- **unclear:** Whether production deployments normally enable auth. The default
  and tests establish that unauthenticated full access is supported, not how an
  operator deploys it.
- **unclear:** Whether all graph domain actor checks can be summarized as one
  stable product permission policy. They validate command legitimacy but do not
  establish human product roles.
- **unclear:** Exactly-once behavior for clarification artifact append when a DB
  race occurs after the file write.
- **unclear:** Whether every review/file helper fully confines user paths to the
  run worktree; route schemas alone do not prove it.
- **unclear:** Whether every mutation has event evidence in lower layers. This
  audit found strong evidence for workflow/graph decisions and weaker or absent
  action events for repo admin, env copy/revert, agent policy, model defaults,
  and some git operations.
- **unclear:** Whether an intervention count can be deterministically derived
  without first deciding which heterogeneous events count. No current API
  contract supplies that taxonomy.
- **unclear:** Whether operators externally quiesce SQLite before backup/restore.
  The CLI contracts do not enforce or record such a procedure.
- **unclear:** Which event types the projection rebuild silently skipped in any
  real invocation; the command emits no skipped-event report or durable rebuild
  record.

## Conflicts found

1. **CLI lifecycle versus signal-queue invariant.** `AGENTS.md` says all
   start/pause/resume/cancel transitions go through the signal queue, while
   `cli.runs.start_run` directly calls `apply_start_run`. The CLI and REST do not
   currently share one transition acceptance contract.
2. **MCP submit versus REST submit.** REST checks then enqueues
   `ACTIVITY_COMPLETED`; MCP calls `submit_for_verification` directly. Treating
   transports as equivalent without preserving this difference would invent
   common race/result semantics.
3. **Legacy CLI rejection versus implemented effect.** The CLI asks whether to
   approve but always posts to the step approval endpoint; the explicit test
   names this "no answer behavior." The displayed alternative contradicts the
   command effect.
4. **Authenticated identity versus recorded identity.** JWT subject can be
   validated, but legacy and graph mutations persist fixed or caller-supplied
   identities. Audit attribution must not be described as authenticated actor
   identity.
5. **Prune feedback event identity.** `prune_apply` emits a durable event and
   then returns an unrelated UUID as `event_id`. The response field must not be
   treated as a pointer to persisted evidence.
6. **JTBD capability wording versus implementation.** Source documents label
   several interventions "Current," but current support is mode- and
   subtype-specific: requeue means graph outbox row, retry has multiple narrow
   commands, and retire/supersede is agent macro/raw patch machinery. The source
   demand does not establish a unified current action.
7. **Database maintenance safety is inconsistent.** Projection rebuild refuses
   to run when the advisory server lock file exists, while backup and restore do
   not check it. Backup documentation implies a replay boundary, but the DB is
   copied before the journal marker is scanned without a common lock/snapshot;
   restore reports the marker but does not replay it.

## Decisions required

- Synthesis must decide whether missing per-action authorization is a blocking
  authority gap for J3/J6. This report provides no proposed product-role policy.
- Synthesis must decide whether transport-divergent start/submit behavior is one
  conflicted capability or multiple implementation variants under one domain
  intent.
- Human review should explicitly resolve whether the legacy CLI's false reject
  affordance blocks any current approval classification.
- Synthesis must define, from existing evidence only, which events qualify for
  `jobs.J8.interventions`; otherwise the claim remains unknown/gap.
- No decision should complete a steering command contract in this phase.

## Artifact paths

- `research/ui-foundation/agent-reports/04-api-actions-authority.md`
- `.superpowers/sdd/task-6-audit-report.md`

No canonical catalog, reality, capability, product, source, test, or git files
were modified by this task.

## Evidence pointers

Primary implementation:

- `src/orchestrator/api/app.py`: `create_app`, `_mount_mcp_sse`,
  `_SessionPerCallHandler`.
- `src/orchestrator/api/auth.py`: `AuthConfig`, `get_require_auth`,
  `get_require_ws_auth`, `validate_token`.
- `src/orchestrator/api/errors.py`: `register_error_handlers`.
- `src/orchestrator/api/schemas/runs.py`: `CreateRunRequest`, `ResumeRunRequest`,
  `RecoverRequest`, `MergeBackRequest`.
- `src/orchestrator/api/schemas/tasks.py`: `UpdateChecklistRequest`,
  `SetGradeRequest`, approval request models.
- `src/orchestrator/api/schemas/clarifications.py`: question/answer contracts.
- `src/orchestrator/api/routers/runs.py`: lifecycle, recovery, approval, skip,
  backward transition, branch operations.
- `src/orchestrator/api/routers/tasks.py`: legacy task phases, retry, checklist,
  grading, escalation, task decisions, force accept.
- `src/orchestrator/api/routers/clarifications.py`: fixed current user,
  clarification response race handling and constrained auto-resume.
- `src/orchestrator/api/routers/graph.py`: `SubmitGraphPatchRequest`,
  `RecordGraphDecisionRequest`, `submit_operator_graph_patch`,
  `record_graph_decision`, `requeue_failed_outbox_row`.
- `src/orchestrator/api/routers/review.py`: prune, revert, test, conflict, and
  back-merge reversal operations.
- `src/orchestrator/api/routers/envfiles.py`, `agents.py`, `runners.py`,
  `repos.py`, and `routines.py`: administrative/file/source-adjacent mutations.
- `src/orchestrator/api/mcp/tools.py`: 11 public tools and `ToolHandler`.
- `src/orchestrator/api/mcp/server.py`: all-tools and allowlisted registration.
- `src/orchestrator/runners/mcp_scope.py`: phase/task exposure scoping.
- `src/orchestrator/graph_runtime/graph_mcp_tools.py`: execution-bound graph
  patch macros and verifier-only grade.
- `src/orchestrator/cli/runs.py` and `src/orchestrator/cli/approve.py`: direct DB
  and REST CLI behavior.
- `src/orchestrator/cli/db.py`: `create_backup_cmd`, `restore_backup_cmd`, and
  `rebuild_projections_cmd`.
- `src/orchestrator/cli/main.py`, `agents.py`, `routines.py`, and `repos.py`:
  serve, detection, local validation, and read-only inventory surfaces.
- `src/orchestrator/db/recovery/backup.py`: `create_backup`, `restore_backup`,
  `BackupMetadata`, and `scan_max_sequence`.
- `src/orchestrator/workflow/service.py`: `recover_run`,
  `retry_fan_out_child`, `respond_to_clarification`, task approval methods, and
  recovery outcomes.

Exact high-impact test pointers not already cited inline:

- Auth transport gate: `tests/integration/test_api_auth.py::test_auth_disabled_allows_all`,
  `::test_auth_enabled_rejects_missing_token`,
  `::test_auth_enabled_accepts_valid_token`,
  `::test_auth_enabled_rejects_invalid_token`,
  `::test_websocket_auth_with_query_param`,
  `::test_websocket_auth_rejects_bad_token`,
  `::test_mcp_auth_rejects_no_token`, `::test_mcp_auth_with_bearer`, and
  `::test_mcp_auth_rejects_invalid_token`.
- Public/scoped MCP: `tests/integration/test_mcp.py::test_tool_names`,
  `::test_full_workflow_through_mcp_server`,
  `tests/integration/test_mcp_sse.py::test_scoped_mcp_sse_endpoint_exists_with_encoded_commas`,
  `::test_scoped_mcp_messages_endpoint_stays_under_scope`, and
  `::test_mcp_handler_updates_database_state`.
- Graph MCP lifetime and phase scoping:
  `tests/unit/test_graph_mcp_tools.py::test_builder_server_has_submit_graph_patch_and_macro_tools_but_not_grade`,
  `::test_verifier_server_has_graph_grade_tool`,
  `tests/integration/test_graph_mcp_dispatcher.py::test_unknown_token_returns_404`,
  `::test_registered_token_forwards_to_its_app`,
  `::test_unregistering_then_calling_returns_404`, and
  `tests/unit/test_graph_dispatch_on_output.py::test_graph_mcp_route_mounted_during_execute_and_unmounted_after`.
- Graph decisions and durable effects:
  `tests/integration/test_graph_decisions_api.py::test_record_authority_decision_updates_decision_readback`,
  `::test_record_authority_decision_binds_and_recomputes_active_scheduler`,
  `::test_record_approval_decision_is_durable_and_releases_waiting_successor`,
  `::test_record_rejected_approval_is_durable_and_dead_inputs_successor`, and
  `::test_record_decision_rejects_invalid_decision_at_api_boundary`.
- Graph append/stale/atomicity:
  `tests/integration/test_graph_event_store.py::test_unique_version_conflict`,
  `::test_unique_constraint_race_surfaces_stale_projection_error`,
  `::test_append_events_rejects_malformed_accepted_record_atomically`,
  `tests/integration/test_graph_controller_transactions.py::test_handle_command_raises_stale_projection_error_when_position_moves_before_write`,
  `tests/integration/test_graph_read_models.py::test_append_keeps_graph_read_models_synchronized`,
  and `::test_graph_read_models_roll_back_with_event_append`.
- Requeue effect and stale boundary:
  `tests/integration/test_graph_api.py::test_operator_requeues_failed_outbox_row_with_audit_event`,
  `::test_operator_requeue_failed_outbox_row_rejects_invalid_requests`, and
  `::test_requeue_audit_append_translates_stale_position_to_conflict`.
- Clarification and approval races/evidence:
  `tests/integration/test_clarification_workflow.py::test_full_clarification_cycle`,
  `::test_respond_to_legacy_stale_clarification_does_not_reopen_completed_task`,
  `::test_clarification_responded_event_emitted`,
  `tests/integration/test_api_human_approval.py::test_approve_step_multiple_times`,
  `::test_approve_step_audit_trail`, and
  `tests/integration/test_cli_approve.py::test_legacy_run_keeps_step_approval_no_answer_behavior`.
- Backup/restore primitives:
  `tests/unit/test_backup.py::test_create_backup_copies_db_and_writes_metadata`,
  `::test_create_backup_with_journal_captures_sequence`,
  `::test_restore_backup_copies_db_back`,
  `::test_create_backup_missing_db_raises_error`, and
  `::test_restore_backup_missing_meta_raises_error`.
- Projection registry rebuild primitives:
  `tests/unit/test_projection_rebuild.py::test_rebuild_all_restores_run_status`,
  `::test_rebuild_all_restores_run_lifecycle_projector`, and
  `::test_rebuild_resets_checkpoint_to_zero`. No exact CLI DB-command test was
  found.

## Recommended next delegation

Normalize these provisional findings into action and permission contracts only
after the workflow-state and graph-runtime reports are reconciled. Preserve the
three authority dimensions separately: enforced authentication/authorization,
implemented domain eligibility, and any later approved product-role policy.
Carry typed steering and steering-patch demands forward only as gaps with their
required outcomes and evidence needs; delegate command design to a separately
approved future capability-design work package.
