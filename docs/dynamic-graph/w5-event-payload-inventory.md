# W5 Event Payload Inventory

Scope: read-only survey of events emitted by `src/orchestrator/graph/_commands.py` and `src/orchestrator/graph/compiler.py` through `make_event(...)`, and events consumed by `src/orchestrator/graph/projections.py::reduce_event`. `compiler.py` currently has no `make_event(` sites.

Allowlist legend: `G` = `GRAPH_PROJECTION_PAYLOAD_FIELDS`; `L` = `LIGHT_GRAPH_PAYLOAD_FIELDS`; `R` = `SUMMARY_REBUILD_PAYLOAD_FIELDS`; `D` = `NODE_DETAIL_PAYLOAD_FIELDS`. Because `R` includes `L` plus summary fields, most `L` fields are also `R`.

## Store Allowlist Coverage

- `G`: `appeal_type`, `attempt_number`, `approved`, `base_snapshot_id`, `candidate_id`, `classification`, `command_binding`, `decision`, `execution_id`, `expires_at`, `failed_candidate_id`, `from_node_id`, `from_port`, `from_state`, `gate_id`, `generation`, `kind`, `lease_id`, `membership`, `new_state`, `node_id`, `outcome`, `port`, `producer_node_id`, `record_id`, `record_kind`, `record_type`, `recovery_of_record_id`, `recovery_reason`, `role`, `session_id`, `state`, `status`, `supersedes_task_region_id`, `supersedes_task_region_ids`, `task_region_id`, `to_node_id`, `to_port`, `to_state`, `verdict`, `verifier_node_id`.
- `L`: broad event/API payload fields used by light graph rows; notable non-`G` fields include `accepted_record_selector`, `active`, `allowed_actions`, `appeal_node_id`, `appealed_node_id`, `authority`, `authority_required_reason`, `binding_policy`, `blocker`, `bound_at_position`, token/cost fields, `cleanup_id`, `command_definition`, `confidence`, `deleted_snapshot_ref`, `dependency_type`, `edge_id`, `evidence_id`, `file_state_record_id(s)`, `from_node_kind`, `from_node_role`, `generation_index`, `input`, `metadata`, `model_id`, `path`, `patch_id`, `planner_chain`, `planner_generation_budget`, `previous_version_id`, `reason`, `record_ids`, `required`, `requirement_id`, `requirement_version_id`, `resource_claims`, `revision_index`, `revision_type`, `schema`, `semantic_change`, `stale_reason`, `successor_planner_node_ids`, `superseding_record_id`, `support_id`, `validation_strengthening`, `verdicts`, `version_id`.
- `R`: all `L`, all summary fields, plus `attempt_number`, `blockers`, `decider`, `decision_type`, `graph_verifier_grades`, `grades`, `idempotency_key`, `operations`, `ops`, `payload`, `patch_ops`, `patch_rejection_reasons`, `provenance`, `run_id`, `snapshot_id`, `tokens_by_node`, `tokens_by_node_kind`, `value`.
- `D`: node-detail subset, including routing/record fields such as `accepted_record_selector`, `allowed_actions`, `authority`, `base_snapshot_id`, `binding_policy`, `candidate_id`, `command_definition`, `edge_id`, `execution_id`, `file_state_record_ids`, `from_node_*`, `generation`, `input`, `kind`, `lease_*`, `new_state`, `node_id`, `outcome`, `port`, `producer_node_id`, `record_id(s)`, `record_kind`, `resource_claims`, `role`, `schema`, `session_id`, `state`, `supersedes_record_id`, `task_region_id`.

## Lease Events

| Event | Producer-written keys | Reducer-read keys | Shape notes | Allowlists |
|---|---|---|---|---|
| `lease_granted` | `lease_id`, `node_id`, `generation`, `execution_id`, `base_snapshot_id`, `expires_at`, `resource_claims`, optional `session_id`; schedule source omits `task_region_id`/`kind` and reducer derives them from node projection | same plus derived `task_region_id`, `kind` fallback | `resource_claims` nested list | `lease_id` G/L/R/D; `node_id` G/L/R/D; `generation` G/L/R/D; `execution_id` G/L/R/D; `base_snapshot_id` G/L/R/D; `expires_at` G/L/R/D; `resource_claims` L/R/D; `session_id` G/L/R/D |
| `lease_renewed` | `lease_id`, `node_id`, `observed_at`, `expires_at`, optional `generation`, `execution_id` | `lease_id`, `node_id`, `generation`, `execution_id`, `expires_at` | scalar only | `observed_at` in none; others in G/L/R/D except `node_id` etc as above |
| `heartbeat_recorded` | same as `lease_renewed` | not consumed by `reduce_event` | audit event | `observed_at` in none |
| `lease_released` | `node_id`, `lease_id`, optional `generation` | `lease_id` only; state becomes `released` from event type | scalar only | all in G/L/R/D |
| `lease_revoked` | `lease_id`, `node_id`, optional `generation`, `execution_id`, `trigger`, `reason` | `lease_id` only; state becomes `revoked` | scalar only | `trigger` L/R, `reason` L/R; other keys mostly G/L/R/D |
| `lease_expired` | `lease_id`, `node_id`, `generation`, `execution_id`, `expires_at`, `reason` | `lease_id` only; state becomes `expired` | scalar only | `reason` L/R; rest in G/L/R/D |
| `lease_suspended` | no current producer found; consumed as lease terminal/suspended state | `lease_id` only | latent/event-log compatibility | `lease_id` G/L/R/D |
| `runtime_retry_scheduled` | `node_id`, `retry_not_before`, plus retry metadata from runtime-death path | `node_id`, `retry_not_before` | scalar; retry time nullable string | `node_id` G/L/R/D; `retry_not_before` in none |
| `agent_died` | runtime death `event_payload` including at least `node_id`, `lease_id`, `generation`, `reason`, often `execution_id` | not consumed by `reduce_event` | audit event | common fields allowed; any runtime-specific keys depend on payload |

Candidate drops: `heartbeat_recorded.observed_at` and all `heartbeat_recorded` payload fields are not reducer-read. `lease_revoked.trigger/reason`, `lease_expired.reason`, and most `agent_died` keys are audit-only for projection. Latent bug/report: reducer consumes `lease_suspended`, but no producer was found in the surveyed files.

## Node Lifecycle

| Event | Producer-written keys | Reducer-read keys | Shape notes | Allowlists |
|---|---|---|---|---|
| `node_created` | direct/patch/recovery forms write `node_id`, `kind`, `role`, `state`, `task_region_id`, `recovery_reason`, `recovery_of_node_id`, `recovery_of_record_id`, `command_binding`, `inputs`, `outputs`, `guarded_planner_node_id`, `rejected_patch_id`, `reason`; patch node payload can also carry `attempt_number`, `candidate_id`, `failed_candidate_id`, `membership`, `authority`, `resource_claims`, `allowed_actions`, `preconditions`, `planner_generation_budget`, `generation_index`, `region_label`, `session_id`, request records, `command_definition(_id)` | `NodeCreationProjection` fields: `node_id`, `kind`, `role`, `state`, `task_region_id`, `attempt_number`, `candidate_id`, `failed_candidate_id`, `resource_claims`, `allowed_actions`, `preconditions`, planner fields, request/gate prompt fields, command fields; recovery index reads `recovery_reason`, `recovery_of_record_id`; later helpers read `planner_chain.regions[].generation_index/region_label` | nested `authority`, `resource_claims`, `command_definition`, request records, `planner_chain`, `inputs`, `outputs` | most core fields in G/L/R/D; `authority`, `allowed_actions`, `preconditions`, `command_definition`, `planner_chain`, `planner_generation_budget`, `generation_index`, `region_label` in L/R or D subsets; `inputs`, `outputs`, `recovery_of_node_id`, `guarded_planner_node_id`, `rejected_patch_id`, request fields not consistently allowlisted |
| `node_state_changed` | `node_id`, `new_state`, `trigger`, optional `reason`, `attempt_number`, `max_attempts`, `completion_status`, `completion_decision_record_id`, `join_result_record_id` | `node_id`, `new_state`, `attempt_number` via top-level or `membership` | scalar plus legacy `membership` possible | `node_id`, `new_state`, `attempt_number` G/L/R/D-ish; `trigger`, `reason` L/R; status/record ids partly not allowlisted |
| `node_retired` | `node_id`, optional `reason` | `node_id` | scalar | `node_id` G/L/R/D; `reason` L/R |
| `node_ready` | `node_id` | `node_id` clears last deferral | scalar | `node_id` G/L/R/D |
| `node_deferred` | `node_id`, `reason` | `node_id`, `reason` | scalar | `node_id` G/L/R/D; `reason` L/R |
| `dead_input_detected` | `node_id`, dead-input fields from readiness such as source/edge identifiers, `reason` | not consumed by `reduce_event` | audit/policy event | `node_id` allowed; dead-input fields vary |
| `node_authority_changed` | `node_id`, either `resource_claims` or `allowed_actions` | `node_id`, `resource_claims`, `allowed_actions`, `preconditions` including nested `authority.*` fallback | nested list fields | `node_id` G/L/R/D; `resource_claims`, `allowed_actions`, `preconditions`, `authority` L/R/D |
| `plan_region_marked_suspect` / `node_marked_suspect` | patch op writes op payload minus `op`; expected keys include `node_id` or region identifiers, `reason` | suspect helper reads `node_id`/region fields and `reason` | scalar plus patch-op extras | `node_id` G/L/R/D; `reason` L/R; region fields partially L/R |
| `plan_region_suspect_resolved` / `node_suspect_resolved` / `plan_region_suspect_cleared` / `node_suspect_cleared` | no current producer found | suspect helper reads target identifiers | scalar | varies |

Candidate drops: `node_state_changed.completion_status`, `completion_decision_record_id`, `join_result_record_id`, `max_attempts`, and `trigger/reason` are not used by projection except for audit/detail rows. `dead_input_detected` is not projection-consumed. Latent bugs/report: reducer consumes suspect-resolved/cleared variants and `node_marked_suspect`, but producers in surveyed files only emit `plan_region_marked_suspect`.

## Records

| Event | Producer-written keys | Reducer-read keys | Shape notes | Allowlists |
|---|---|---|---|---|
| `output_record_accepted` | typed record dumps for `OutputRecord`, `CandidateRecord`, `VerificationReportRecord`, `CompletionDecisionRecord`, `JoinResultRecord`, `CheckResultRecord`, `DecisionRecord`, `AuthorityDecisionRecord`, `AnalysisSummaryRecord`, `GraphPatchProposalRecord`, `RoutineSnapshotRecord`, `ArtifactReferenceRecord`, `RequirementRecord`, `DecisionRequestRecord`, `AuthorityRequestRecord`, `FailureRecord`, `RecoveryPlanRecord`; common keys `record_id`, `record_kind`, `record_type`, `producer_node_id`, `port`, `schema`, `value`, `provenance`; subtype fields include `candidate_id`, `membership`, record-id lists, `supersedes_*` | common discriminator keys plus model-specific validation; projection helpers read `record_id`, `record_kind`, `record_type`, `schema`, `producer_node_id`/`node_id`, `port`, `value`, `provenance`, `candidate_id`, `membership`, `attempt_number`, `task_region_id`, `candidate_record_ids`, `file_state_record_ids`, `evaluated_record_ids`, `supersedes_task_region_id(s)`, `supersedes_record_id` | `value`, `provenance`, `evidence`, `membership` nested; typed records already exist | common fields in G/L/R/D; `value`, `payload`, `provenance`, `evidence`, `grades`, `blockers` mostly R; record-id lists L/R/D |
| `verification_passed` / `verification_failed` | `node_id`, `verifier_node_id`, `candidate_id`, `verdict`, `outcome`, `record_id`, `evidence`, `value`, optional `task_region_id` | `candidate_id`, `verifier_node_id` or `node_id`, `record_id`, `task_region_id` | nested `evidence`, `value` | scalar fields G/L/R/D; `evidence` not in four allowlists; `value` R |
| `revision_created` | patch op payload minus `op`, `node`, `worker_node`, `verifier_node` | not consumed by `reduce_event` | patch-op extras | varies |
| `input_bound` | from routing: `edge_id`, `to_node_id`, `to_port`, `record_ids`, `bound_at_position`, optional `binding_policy`, `supersedes_record_id`; legacy may include `input`, `record_bound_positions`, `trigger` | `to_node_id`, `to_port` or `edge_id` fallback or legacy `input`, `record_ids`, `bound_at_position`, `trigger`, `supersedes_record_id`, `record_bound_positions`, derived `binding_policy` | nested `record_bound_positions` map | core route fields L/R/D; `to_node_id`, `to_port` G/L/R; `record_bound_positions` in none |

Candidate drops: `verification_* .evidence` is not read by reducers; `revision_created` is not consumed. Latent bugs/report: reducer supports legacy `input_bound.input` and `record_bound_positions`; no current direct producer found for `record_bound_positions`.

## Patches

| Event | Producer-written keys | Reducer-read keys | Shape notes | Allowlists |
|---|---|---|---|---|
| `graph_patch_accepted` | `patch_id`, `base_graph_position`, `actor_role`, `proposed_by_node_id`, `successor_planner_node_ids`, `session_id`, `carryover_record_id` | `proposed_by_node_id`, `patch_id`, `successor_planner_node_ids`; proposal blocker helper reads proposal status keys | `successor_planner_node_ids` list | `patch_id`, `proposed_by_node_id`, `successor_planner_node_ids`, `session_id` L/R; only `session_id` G/D |
| `graph_patch_rejected` | `_patch_rejected_payload`: `patch_id`, `base_graph_position`, `actor_role`, `proposed_by_node_id`, `reason`/`rejection_reason`, optional `read_set_diff`; budget rejection adds `budget`, `count` | proposal blocker helper reads `patch_id`, `proposed_by_node_id`, status/reason fields | nested `read_set_diff` | `patch_id`, `reason`, `rejection_reason`, `proposed_by_node_id`, `actor_role` L/R; `read_set_diff`, `budget`, `count` in none |
| `graph_patch_proposed`, `planner_proposal_opened`, `proposal_opened`, `proposal_recorded`, `proposal_accepted`, `proposal_rejected`, `proposal_resolved`, `proposal_closed` | no current producers found in surveyed files | proposal blocker helper reads `patch_id`/node ids/status-like fields | compatibility/legacy | varies |

Candidate drops: `graph_patch_accepted.base_graph_position`, `actor_role`, `session_id`, `carryover_record_id` are not directly projection-read except for summaries/detail; `graph_patch_rejected.read_set_diff`, `budget`, `count` are not reducer-read. Latent bugs/report: reducer consumes proposal lifecycle event aliases with no producers in surveyed files.

## Decisions

| Event | Producer-written keys | Reducer-read keys | Shape notes | Allowlists |
|---|---|---|---|---|
| `appeal_opened` | raise-appeal writes `node_id`, `appealed_node_id`, `candidate_id`, `task_region_id`, `appeal_type`, `lease_id`; patch op can write arbitrary create-appeal op fields and defaults `node_id` | `appealed_node_id` or `node_id`, `task_region_id` via top-level/membership, `candidate_id`, `appeal_type` | scalar plus patch extras | all listed fields L/R; most in G except `appealed_node_id`, `lease_id` etc; `lease_id` D |
| `approval_decision_recorded` | full command payload plus normalized `decision`, `decider`, optional derived `task_region_id`; may include `approved`, `outcome`, `scope`, `expires_at`, `reason`, `record_id`, `gate_id` | latest decision model reads `node_id`, `decision`/`outcome`/`approved`, `task_region_id`, `gate_id`, `appeal_node_id`, `decider`, `scope`, `expires_at`, `reason`; gate projection reads `node_id`, `decision`, `approved`, `task_region_id`, `gate_id` | nested `decider`, `scope` | many scalar fields G/L/R/D; `decider`, `scope` R only or none; `reason` L/R |
| `authority_decision_recorded` | same decision command payload shape, authority-normalized | latest authority model reads `node_id`, `decision`/`outcome`/`approved`, `task_region_id`, `appeal_node_id`, `decider`, `scope`, `expires_at`, `reason`; authority gate reads `node_id`, `decision` | nested `decider`, `scope` | same as approval |
| `oversight_decision_recorded` | same decision command payload shape, oversight-normalized | latest oversight model and appeal resolution read `node_id`, `decision`/`outcome`/`verdict`/`approved`, `appealed_node_id`, `task_region_id`, `candidate_id`, `appeal_type`, `gate_id`, `appeal_node_id`, `decider`, `scope`, `expires_at`, `reason` | nested `decider`, `scope` | scalar decision fields mostly G/L/R; `appealed_node_id`, `appeal_node_id` L/R; `decider` R |

Candidate drops: `record_id` in decision event payload is only used to create the companion output record, not by decision reducers. Latent bugs/report: none found for the three produced decision event types.

## Cleanup

| Event | Producer-written keys | Reducer-read keys | Shape notes | Allowlists |
|---|---|---|---|---|
| `cleanup_requested` | `cleanup_id`, `file_state_record_id`, `snapshot_id`, `paths`, `authority`, `reason`, `execution_id`, `producer_node_id` | same plus projection `position` | `paths` list | all but `paths` mostly L/R; `cleanup_id`, `file_state_record_id`, `authority`, `reason`, `execution_id`, `producer_node_id` L/R; `paths` not in four allowlists |
| `cleanup_applied` | `cleanup_id`, `file_state_record_id`, `superseding_record_id`, `old_snapshot_id`, `new_snapshot_id`, `paths`, `authority`, `reason`, `execution_id`, `deleted_snapshot_ref` | `cleanup_id`, `file_state_record_id`, `superseding_record_id`, `deleted_snapshot_ref` | `paths` list | `cleanup_id`, `file_state_record_id`, `superseding_record_id`, `deleted_snapshot_ref`, `authority`, `reason`, `execution_id` L/R; old/new snapshot ids and `paths` not in four allowlists |

Candidate drops: `cleanup_applied.old_snapshot_id`, `new_snapshot_id`, `paths`, `authority`, `reason`, `execution_id` are not reducer-read; `cleanup_requested.snapshot_id`, `authority`, `execution_id`, `producer_node_id` only feed the stored cleanup-request projection/details. Latent bugs/report: none.

## Planner / Session

| Event | Producer-written keys | Reducer-read keys | Shape notes | Allowlists |
|---|---|---|---|---|
| `session_state_changed` | `session_id`, `state`, `node_id`, `lease_generation`, `carryover_record_id` | `session_id`, `state`, `node_id`, `carryover_record_id`; `lease_generation` not read | scalar nullable carryover | `session_id`, `state`, `node_id` G/L/R/D; `lease_generation` L/R/D; `carryover_record_id` in none |
| planner chain through `node_created` | planner nodes may include `session_id`, `generation_index`, `region_label`, `planner_chain`, `planner_generation_budget`, `carryover_record_id` | `session_id`, `generation_index`, `region_label`, `planner_generation_budget`; helper reads `planner_chain.regions[].generation_index/region_label` | nested `planner_chain` | planner fields L/R; only `session_id` G/D |

Candidate drops: `session_state_changed.lease_generation` is not reducer-read. `carryover_record_id` is read for session carryovers but is not in any store allowlist. Latent bugs/report: none.

## Requirements / Evidence

| Event | Producer-written keys | Reducer-read keys | Shape notes | Allowlists |
|---|---|---|---|---|
| `requirement_revision_recorded` | full command payload plus normalized `requirement_id`, `version_id`; common keys include `requirement_version_id`, `classification`/`change_classification`/`revision_type`, `requires_authority`, `explicit_authority_required`, `new_behavior`, `behavior_change`, `semantic_change`, `validation_strengthening`, `previous_version_id`, `revision_index`, `authority_required_reason`, `active` | `requirement_id`, `version_id` or `requirement_version_id`, classification keys, authority booleans, `previous_version_id`, `revision_index`, `authority_required_reason`, `validation_strengthening`, `active` | scalar only | most fields L/R; `classification` G/L/R; `version_id`, `requirement_version_id`, `active`, `previous_version_id`, `revision_index` L/R |
| `requirement_amended` | no current producer found | same reducer path as recorded | compatibility/legacy | same |
| `requirement_revision_proposed` | no current producer found | authority blocker helper reads requirement/proposal fields | compatibility/legacy | same-ish |
| `support_evidence_recorded` | full command payload plus normalized `support_id`, `evidence_id`, `requirement_id`, `requirement_version_id`; optional `version_id`, `status`, `stale_reason`, `confidence` | `support_id` or `edge_id`, `evidence_id`, `requirement_id`, `requirement_version_id` or `version_id`, `status`, `stale_reason`, `confidence` | scalar only | fields L/R; `status` G/L/R; `confidence` L/R |
| `support_edge_recorded` | no current producer found | same reducer path as support evidence | compatibility/legacy | same |
| `authority_resolution_recorded`, `authority_resolved`, `requirement_revision_authorized` | no current producers found | authority revision blocker helper reads requirement/proposal resolution fields | compatibility/legacy | varies |

Candidate drops: none obvious on produced requirement/support events; reducers intentionally preserve authority and validation semantics. Latent bugs/report: several compatibility aliases are reducer-consumed but not produced in surveyed files.

## File-State / Gatekeeper

| Event | Producer-written keys | Reducer-read keys | Shape notes | Allowlists |
|---|---|---|---|---|
| `file_state_accepted` | `FileStateRecord` dump: `record_id`, `record_kind=file_state`, `snapshot_id`, `base_snapshot_id`, `producer_node_id`, `port`, `schema`, nested file lists (`git`, `tracked`, `untracked`, `ignored`, `external`, `classifications`, `residue`, `rejected_paths`), `verdict`, `patch_bundle_id`, `tree_snapshot_id`, `task_region_id`, `candidate_id`, lineage fields | `record_id`, all `FileStateRecord` fields through model validation; output-port/summary reads `producer_node_id`/`node_id`, `port`, `record_kind`, `schema`; gatekeeper and cleanup mutate file-list entries | nested file entry lists and `git` | common fields G/L/R/D; `snapshot_id`, `run_id` R; file lists and lineage fields mostly not in four allowlists except cleanup lineage fields in L/R |
| `file_state_rejected` | rejected file-state payload from validation | not consumed by `reduce_event` | audit/rejection event | varies |
| `gatekeeper_verdict_recorded` | `file_state_record_id`, `execution_id`, `producer_node_id`, `verdicts`, `resolved_count`; verdict entries include `path`, `classification`, `confidence`, `rationale`, `model_id`, token/cost fields, `wall_time_ms` | `file_state_record_id`, `verdicts[].path`, and per-verdict `classification`, `model_id`, `confidence`, `rationale` to update file entries | `verdicts` nested list | event fields L/R; `verdicts` L/R; nested token/cost fields L/R at top-level only, not nested-specific |
| `gatekeeper_cost_recorded` | cost payload from `_gatekeeper_cost_payload`, including `model_id`, token/cost totals, `wall_time_ms`, `execution_id`, likely `file_state_record_id`/consult identifiers | not in main `reduce_event` branch, but run summary cost reducer reads `model_id`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost_usd`, `wall_time_ms`, `execution_id` | scalar cost fields | cost fields L/R |
| `environment_failure_accepted` | no current producer found as event; environment failures usually inferred from output/check records | `_record_environment_failure` reads `task_region_id`, `node_id`, `classification`, `value.classification`, command/stdout/stderr/exit fields, `reason`, `record_id` | nested `value` allowed | mostly G/L/R/D for core, `value` R |
| `check_result_classified` | no current producer found | same as environment failure path | compatibility/legacy | same |

Candidate drops: `file_state_rejected` is not reducer-consumed. `gatekeeper_verdict_recorded.resolved_count` is not reducer-read. `gatekeeper_cost_recorded` is not graph-projection-read, but is read by cost summary logic; do not drop without checking store/run summary use. Latent bugs/report: `environment_failure_accepted` and `check_result_classified` are consumed but not produced in surveyed files.

## Lifecycle / Command Rejection

| Event | Producer-written keys | Reducer-read keys | Shape notes | Allowlists |
|---|---|---|---|---|
| `run_lifecycle_changed` | `command_type`, `from_state`, `to_state`, `trigger`; recovery failure adds `node_id`, `patch_id`, `recovery_of_record_id`, `recovery_reason` | `to_state` | scalar only | `from_state`, `to_state`, `node_id`, `recovery_*` G/L/R; `command_type`, `trigger`, `patch_id`, `reason` L/R |
| `command_rejected` | `command_type`, `reason`; variants add `blockers`, `patch_id`, `base_graph_position`, `actor_role`, `proposed_by_node_id` | not consumed by `reduce_event` | `blockers` nested list | mostly L/R; `blockers` R |
| `callback_accepted` | `node_id`, `lease_id`, `lease_generation`, `idempotency_key`, `payload`, `reason` | idempotency recorder reads `node_id`, `idempotency_key`, plus payload model stores `event_type`, `outcome`, likely `lease_id`, `lease_generation`, `reason`, `payload` | nested callback `payload` | `node_id`, `lease_id` G/L/R/D; `lease_generation` L/R/D; `idempotency_key`, `payload` R; `reason` L/R |
| `callback_rejected_stale`, `callback_rejected_conflict`, `callback_duplicate_returned` | same callback payload; duplicate adds `prior_result` | not consumed by `reduce_event` | nested `payload`, `prior_result` | common fields as above; `prior_result` in none |

Candidate drops: `command_rejected` and rejected/duplicate callback events are not projection-consumed. `run_lifecycle_changed.command_type/from_state/trigger` and recovery extras are not graph-projection-read except `to_state`.

## Cross-Cutting Mismatches

Written but not reducer-read candidates:

- Audit-only events: `heartbeat_recorded`, `agent_died`, `dead_input_detected`, `file_state_rejected`, `revision_created`, `command_rejected`, callback rejected/duplicate events.
- Specific fields: `observed_at`, `lease_revoked.trigger`, `session_state_changed.lease_generation`, `graph_patch_accepted.base_graph_position/actor_role/session_id/carryover_record_id`, `graph_patch_rejected.read_set_diff/budget/count`, `gatekeeper_verdict_recorded.resolved_count`, `cleanup_applied.old_snapshot_id/new_snapshot_id/paths/authority/reason/execution_id`, `node_state_changed.completion_status/completion_decision_record_id/join_result_record_id/max_attempts`.

Read but not currently written candidates:

- Event aliases consumed but not emitted in surveyed files: `lease_suspended`, `graph_patch_proposed`, `planner_proposal_opened`, `proposal_opened`, `proposal_recorded`, `proposal_accepted`, `proposal_rejected`, `proposal_resolved`, `proposal_closed`, `node_marked_suspect`, suspect resolved/cleared variants, `requirement_amended`, `requirement_revision_proposed`, `support_edge_recorded`, `authority_resolution_recorded`, `authority_resolved`, `requirement_revision_authorized`, `environment_failure_accepted`, `check_result_classified`.
- Fields read but rarely/no direct producer in surveyed files: `input_bound.record_bound_positions`, `node_authority_changed.preconditions` through reducer fallback, `requirement_revision_recorded.change_classification`, `support_evidence_recorded.edge_id` alias, `output_record_accepted` legacy `node_id` producer alias.

## Commands Run

- `sed -n '1,220p' /Users/peter/code/task-world/vendor/superpowers/skills/using-superpowers/SKILL.md`
- `sed -n '1,220p' /Users/peter/code/task-world/vendor/superpowers/skills/using-superpowers/references/codex-tools.md`
- `sed -n '1,220p' docs/dynamic-graph/w5-continuation-agent-prompt.md`
- `rg -n "make_event\\(" src/orchestrator/graph/_commands.py src/orchestrator/graph/compiler.py`
- `rg -n "def reduce_event|event_type|payload|get\\(|\\[\\\"|GRAPH_PROJECTION_PAYLOAD_FIELDS" src/orchestrator/graph/projections.py`
- `rg -n "LIGHT_GRAPH_PAYLOAD_FIELDS|SUMMARY_REBUILD_PAYLOAD_FIELDS|NODE_DETAIL_PAYLOAD_FIELDS|PAYLOAD_FIELDS" src/orchestrator/graph_runtime/store.py`
- `uv run python - <<'PY' ...` AST scan of `make_event(...)` call sites in `_commands.py` and `compiler.py`
- Targeted `sed` reads of relevant sections in `src/orchestrator/graph/_commands.py`, `src/orchestrator/graph/projections.py`, `src/orchestrator/graph_runtime/store.py`, and `src/orchestrator/graph/models.py`
