# Domain And Persistence Audit

## Purpose

Audit the implemented domain and persistence boundaries in the assigned source
scope. This report inventories entities, identities, lifecycle carriers,
ownership, cardinality, aliases, and persistence tables without minting
canonical IDs or treating similarly named run/step/task/attempt/node/record/
event/requirement concepts as equivalent.

Status labels mean:

- **implemented**: established by executable schema or current implementation in
  the bounded source.
- **tested**: exercised by a cited test; this does not by itself establish every
  production reachability path.
- **documented-only**: asserted by a docstring, migration narrative, or required
  project document without matching decisive implementation in this scope.
- **inferred**: a constrained interpretation from implemented fields and
  relationships, not an explicit contract.
- **unclear**: the bounded evidence cannot settle the claim.

## Scope inspected

Primary assigned source, read schemas/ORM before implementation and tests:

- `src/orchestrator/db/`, including ORM, migrations, repositories, event store,
  outbox, bootstrap, and projectors.
- `src/orchestrator/state/`, including runtime models, factory, and optional JSON
  session persistence.
- `src/orchestrator/config/models.py` and
  `src/orchestrator/config/enums.py`.
- `src/orchestrator/api/schemas/`.

Required framing inputs:

- `docs/superpowers/specs/2026-07-23-ui-foundation-phase-0-3-design.md`.
- `research/ui-foundation/catalog/scope.yaml`.
- `research/ui-foundation/agent-reports/00-delegation-plan.md`.
- `AGENTS.md`.

Tests were inspected only after the source pass, principally:

- `tests/integration/test_database.py`.
- `tests/integration/test_full_persistence.py`.
- `tests/integration/test_session_persistence.py`.
- `tests/integration/test_event_sourced_workflow.py`.
- `tests/integration/test_event_log_durability.py`.
- `tests/integration/test_graph_read_models.py`.
- `tests/integration/test_graph_node_detail_read_models.py`.
- `tests/integration/test_migrations.py`.
- `tests/integration/test_jsonl_rotation_recovery.py`.
- `tests/integration/test_api_model_profiles.py`.
- `tests/integration/test_clarification_repository.py` and
  `tests/integration/test_clarification_workflow.py`.
- `tests/unit/test_run_factory.py`, `tests/unit/test_state_models.py`,
  `tests/unit/test_projectors.py`, `tests/unit/test_run_schemas.py`, and
  `tests/unit/test_config_models.py`.
- `tests/unit/test_backup.py` and `tests/unit/test_jsonl_rotation.py`.

Out of scope: graph-kernel entity definitions, workflow event-class definitions,
API route/presenter reachability, runner profile resolution, and product/UI
implementation. This report cites their values only where they cross an assigned
schema or persistence boundary; it does not audit their internals.

This isolation statement is worker-scoped: this Task 3 worker did not expand its
implementation audit beyond the assigned source. It does not assert that the
runtime modules are architecturally isolated, or prevent other bounded workers
from inspecting overlapping tests and boundary symbols.

## Key findings

### Entity and identity inventory

| Provisional key | Finding | Status | Evidence |
|---|---|---|---|
| DP-ENT-run-config | `RoutineConfig` is a template/configuration shape with `id`, nested `StepConfig` and `TaskConfig`, but is not the persisted run instance. | implemented, tested | `src/orchestrator/config/models.py::RoutineConfig`; `tests/unit/test_run_factory.py::simple_routine` |
| DP-ENT-run | A run instance has an independently generated `Run.id`; `routine_id` is a reference value, while `routine_sha`, `routine_commit`, `source_branch_sha`, and `intended_seed_sha` are separate provenance fields. | implemented, tested | `src/orchestrator/state/models.py::Run`; `src/orchestrator/db/orm/models.py::RunModel`; `src/orchestrator/state/factory.py::create_run_from_routine`; `tests/integration/test_full_persistence.py::test_routine_fixture_roundtrip` |
| DP-ENT-step | A runtime/persisted step has UUID-like `id` plus template `config_id`; neither is an alias for list position. `order_index` is persisted only on `StepModel`. | implemented, tested | `src/orchestrator/state/models.py::StepState`; `src/orchestrator/db/orm/models.py::StepModel`; `tests/unit/test_run_factory.py::test_create_run_deterministic_ids`; `tests/integration/test_database.py::test_step_ordering` |
| DP-ENT-task | A runtime/persisted task has independent `id`, template `config_id`, mutable status, embedded checklist, attempt counters, and optional fan-out lineage. | implemented, tested | `src/orchestrator/state/models.py::TaskState`; `src/orchestrator/db/orm/models.py::TaskModel`; `tests/integration/test_full_persistence.py::test_full_lifecycle_survives_restart` |
| DP-ENT-attempt | Runtime `Attempt.id` and `AttemptModel.id` are the identity actually round-tripped by `run_model_to_domain`/`run_to_model`. `attempt_num` orders attempts inside a task but is not constrained unique. | implemented, tested | `src/orchestrator/state/models.py::Attempt`; `src/orchestrator/db/access/repositories.py::run_model_to_domain`, `run_to_model`; `tests/integration/test_event_sourced_workflow.py::test_empty_database_can_be_rebuilt_from_events_v2` |
| DP-ENT-attempt-record | `AttemptRecord` is a dataclass described as a canonical cross-task shape with globally unique `attempt_id`, but it is not exported from `orchestrator.db`, referenced by repository conversion, or an ORM table. | documented-only, unclear | `src/orchestrator/db/orm/models.py::AttemptRecord`; `src/orchestrator/db/__init__.py::__all__` |
| DP-ENT-requirement | `RequirementConfig.id` is converted to runtime/persisted `ChecklistItem.req_id`; requirement state and grades live in `TaskModel.checklist` JSON and attempt `grade_snapshot` JSON, not a requirement table. | implemented, tested | `src/orchestrator/config/models.py::RequirementConfig`; `src/orchestrator/state/factory.py::create_checklist_from_requirements`; `src/orchestrator/state/models.py::ChecklistItem`, `GradeSnapshotItem`; `tests/unit/test_run_factory.py::test_create_checklist_from_requirements`; `tests/integration/test_full_persistence.py::test_full_lifecycle_survives_restart` |
| DP-ENT-node | A graph node is not a task row. In this scope it appears only as `node_id` in disposable `GraphNodeDetailSummaryModel` rows and JSON projections; `task_region_id` is an optional string, not an FK or proven task identity. | implemented, tested | `src/orchestrator/db/orm/models.py::GraphNodeDetailSummaryModel`; `tests/integration/test_graph_node_detail_read_models.py::test_append_creates_and_updates_node_detail_summaries` |
| DP-ENT-record | A graph record is not an event or requirement row. Output/file-state records are JSON values embedded in per-node summaries; input ports contain record-ID lists. There is no record ORM/table in this scope. | implemented, tested | `src/orchestrator/db/orm/models.py::GraphNodeDetailSummaryModel.output_records`, `.file_state_records`, `.input_ports`; `tests/integration/test_graph_node_detail_read_models.py::test_append_creates_and_updates_node_detail_summaries`, `test_node_detail_summary_accumulates_bind_all_input_ports` |
| DP-ENT-event | On normal writes, the authoritative scoped transaction is the `EventV2Model` row plus synchronous SQL projections; the row is identified for global ordering by integer `position` and for per-aggregate duplicate/order protection by `(aggregate_id, version)`. It deliberately has no `event_id` column. When `events_v2` is empty, `bootstrap_from_jsonl` reverses the direction by importing archived/active JSONL records and rebuilding known projections. | implemented, tested | `src/orchestrator/db/orm/models.py::EventV2Model`; `src/orchestrator/db/access/event_store_v2.py::StoredEvent`, `SqliteEventStore`; `src/orchestrator/db/bootstrap.py::bootstrap_from_jsonl`; `tests/integration/test_database.py::test_event_v2_metadata_exposes_durability_contract`, `test_events_v2_retry_identity_is_aggregate_version_not_payload_identity`; `tests/integration/test_jsonl_rotation_recovery.py::test_bootstrap_replays_archives_and_active_in_global_position_order` |
| DP-ENT-graph-event | Graph event-envelope identity remains distinct: `GraphEventSummaryModel` stores `event_id` alongside the source event `position`; node-detail `events` JSON also retains graph `event_id`. | implemented, tested | `src/orchestrator/db/orm/models.py::GraphEventSummaryModel`, `GraphNodeDetailSummaryModel.events`; `tests/integration/test_graph_node_detail_read_models.py::test_deleted_node_detail_rows_do_not_partially_rebuild_on_append` |
| DP-ENT-clarification | Clarification request and response are separately identified records. A request belongs to a run by FK, names task and attempt number without FKs, and has at most one response by unique `request_id`. | implemented, tested | `src/orchestrator/db/orm/models.py::ClarificationRequestModel`, `ClarificationResponseModel`; `src/orchestrator/db/access/repositories.py::get_clarification_history`; `tests/integration/test_clarification_repository.py`; `tests/integration/test_clarification_workflow.py` |
| DP-ENT-artifact | “Artifact” has multiple non-equivalent carriers: configured expected path (`ArtifactSpec`), evidence bundle paths (`RunEvidenceItem`), interaction log artifact row (`InteractionLogArtifactModel`), and graph output/file-state record JSON. | implemented, unclear as one vocabulary | `src/orchestrator/config/models.py::ArtifactSpec`; `src/orchestrator/api/schemas/runs.py::RunEvidenceItem`; `src/orchestrator/db/orm/models.py::InteractionLogArtifactModel`, `GraphNodeDetailSummaryModel` |
| DP-ENT-model-profile | A model profile is an enum/config selection and runner-default mapping; an execution attempt stores resolved `agent_model` and runner snapshot but no profile field. | implemented, tested | `src/orchestrator/config/enums.py::ModelProfile`; `src/orchestrator/config/models.py::TaskConfig.profile`; `src/orchestrator/db/orm/models.py::AgentRunnerModelProfileDefaultModel`, `AttemptModel`; `tests/integration/test_api_model_profiles.py::test_set_and_get_model_defaults_roundtrip` |
| DP-ENT-backup | `BackupMetadata` is an in-memory/sidecar metadata record, not a DB row. `backup_id` is a UTC timestamp string at one-second resolution and names both the copied DB and `.backup-meta.json` sidecar; no stronger uniqueness or collision guard is implemented. | implemented, tested, limitation inferred | `src/orchestrator/db/recovery/backup.py::BackupMetadata`, `create_backup`; `tests/unit/test_backup.py::test_create_backup_copies_db_and_writes_metadata` |
| DP-ENT-backup-db | A backup database artifact is a `shutil.copy2` copy at `orchestrator-<backup_id>.db`; metadata `db_path` names this copy, not the source DB. Creation does not use SQLite's backup API and does not copy `-wal`/`-shm` sidecars. | implemented, unit-tested with a fake text file; live consistency unclear | `src/orchestrator/db/recovery/backup.py::create_backup`, `restore_backup`; `tests/unit/test_backup.py::test_restore_backup_copies_db_back` |
| DP-ENT-backup-sidecar | The sibling `orchestrator-<backup_id>.backup-meta.json` sidecar stores timestamp, copied DB path, external journal path, journal marker, backup ID, and notes. It is distinct from the copied DB and journal segments; `restore_backup` consumes it and copies only the DB. | implemented, tested | `src/orchestrator/db/recovery/backup.py::create_backup`, `restore_backup`; `tests/unit/test_backup.py` |
| DP-ENT-journal-segment | Active JSONL and immutable range-named archive files are secondary event artifacts keyed/deduplicated by global position. Rotation hard-links the active file to an archive, fsyncs, then unlinks active; recovery detects a linked active/archive inode and finishes the unlink before appending. | implemented, tested | `src/orchestrator/db/access/jsonl_outbox.py::JournalSegment`, `discover_journal_segments`, `_rotate`, `_recover_linked_rotation`; `tests/unit/test_jsonl_rotation.py::test_rotation_syncs_active_then_links_fsyncs_unlinks_and_fsyncs_parent`, `test_linked_rotation_recovery_syncs_before_and_after_unlink`, `test_rotation_recovers_linked_active_file_before_appending` |

### Ownership and cardinality

| Relationship | Implemented boundary | Status and tests |
|---|---|---|
| Run -> steps | One `RunModel` owns ordered zero-to-many `StepModel` rows. `steps.run_id` is non-null, `ON DELETE CASCADE`; ORM uses `delete-orphan`. | implemented, tested by `tests/integration/test_database.py::test_crud_with_steps_and_tasks`, `test_cascade_delete` |
| Step -> tasks | One step owns ordered zero-to-many task rows. `tasks.step_id` is non-null, `ON DELETE CASCADE`; ORM uses `delete-orphan`. | implemented, tested by the same tests and `tests/integration/test_full_persistence.py::test_state_survives_restart` |
| Task -> attempts | One task owns ordered zero-to-many attempts. `attempts.task_id` is non-null, `ON DELETE CASCADE`; ORM uses `delete-orphan`. No uniqueness enforces `(task_id, attempt_num)`. | implemented, partially tested by `tests/integration/test_database.py::test_cascade_delete`; uniqueness is untested/absent |
| Run -> child runs | `runs.parent_run_id` is an optional self-FK; one parent can have many children. `parent_task_id` and `parent_slice_id` are plain strings, so the database does not enforce their referenced entity or ownership. | implemented, projection-tested by `tests/unit/test_projectors.py` parent fields |
| Task -> fan-out children | `tasks.parent_task_id` is an optional self-FK; one parent may have many child task rows. `child_id` is another optional string described as stable, while task `id` remains the row identity. No ORM self-relationship or uniqueness on `(parent_task_id, fan_out_index)`/`child_id` is declared. | implemented, partially tested by `src/orchestrator/db/access/repositories.py::count_fan_out_children` and `tests/unit/test_projectors.py`; stable alias semantics unclear |
| Run/task/attempt -> cost record | `CostRecordModel` requires run and task FKs and optionally references `attempts.id`; uniqueness is execution tuple `(run_id, task_id, attempt_num, agent_runner_type, phase)`, not `attempt_id`. | implemented; migration behavior tested in `tests/integration/test_migrations.py` |
| Cost/run/task/attempt -> interaction log artifact | `InteractionLogArtifactModel` optionally references cost and attempt PK, requires run/task FKs, and has the same execution-tuple uniqueness. | implemented; migration behavior tested in `tests/integration/test_migrations.py` |
| Run -> clarification requests | Request has run FK with cascade. `task_id` and `attempt_num` are attribution values without referential constraints. | implemented, tested by clarification integration tests |
| Clarification request -> response | Zero-or-one response per request, enforced by unique `request_id` and ORM `uselist=False`; response is deleted with request. | implemented, tested by clarification integration tests |
| Run -> events | `events_v2.aggregate_id` is not a run FK. Legacy/workflow streams use run IDs while graph activity can use `graph:<run-id>`; one event table therefore stores multiple aggregate namespaces. | implemented, tested by `src/orchestrator/db/access/event_store_v2.py::get_events_paginated` and graph/event-store integration tests |
| Run -> graph read models | Graph summary/snapshot/node-detail rows carry `run_id` but declare no FK to `runs`. They are disposable projections and require explicit delete/rebuild behavior. | implemented, tested by `tests/integration/test_graph_read_models.py::test_graph_read_models_are_rebuildable_and_idempotent` and node-detail rebuild tests |
| Routine -> routine metadata | No primary routine row exists. `RoutineMetaModel` stores supplementary metadata uniquely by `(routine_id, source)` and explicitly says routines are discovered from YAML. | implemented; migration narrative and ORM agree; API reachability not audited |
| Runner/profile -> default model | At most one default per `(runner_type, profile)` by unique constraint; no FK constrains either enum string. | implemented, tested by model-profile API integration tests |
| Backup metadata -> copied DB | One sidecar points to one copied DB path. Identity is filename-derived `backup_id`, not content identity; restore falls back to a DB with the recorded basename beside a moved sidecar. | implemented, tested by `tests/unit/test_backup.py::test_create_backup_copies_db_and_writes_metadata`, `test_restore_backup_copies_db_back` |
| Backup metadata -> journal | Metadata references one active journal path and stores one maximum position/legacy-sequence marker, but owns or copies no active/archive journal file. The marker is a replay-cut hint returned by restore, not a DB FK or enforced replay action. | implemented, scan tested by `tests/unit/test_backup.py::test_create_backup_with_journal_captures_sequence` and `tests/integration/test_jsonl_rotation_recovery.py::test_backup_scans_all_archives_and_active_for_maximum_position` |
| Active journal -> archive segments | Archives are sibling hard-linked rotation artifacts named from minimum/maximum contained positions. Discovery treats filename ranges as candidate indexes and reads actual positions for deduplication; archives remain distinct from backup sidecars. | implemented, tested by `tests/unit/test_jsonl_rotation.py::test_archive_range_is_only_a_candidate_index_for_gaps` and rotation recovery tests |

### Temporal relationship behavior

| Relationship or carrier | Temporal behavior | Status and evidence |
|---|---|---|
| Requirement config -> mutable checklist -> attempt grade snapshot | `RequirementConfig` seeds `TaskState.checklist`. `TaskStateProjector` mutates the task's current checklist JSON on checklist/grade events. Each attempt can separately retain `grade_snapshot` JSON at attempt update/completion. The current checklist is therefore a mutable latest projection, while an attempt snapshot is attempt-scoped historical evidence; no SQL constraint guarantees that the two agree. | implemented, tested by `src/orchestrator/state/factory.py::create_checklist_from_requirements`, `src/orchestrator/db/projections/task_state.py::TaskStateProjector`, and `tests/integration/test_full_persistence.py::test_full_lifecycle_survives_restart` |
| Task `current_attempt` -> attempt ordinal/identity | `current_attempt` is a mutable integer on the task and is updated by attempt/task events. It can select an ordinal conceptually, but there is no FK from it to an attempt row and no uniqueness on `(task_id, attempt_num)`. Durable attempt lookup uses `AttemptModel.id`; the competing nullable `attempt_id` contract remains unresolved. | implemented, tested for increments/status projection; durable identity relation unclear. Evidence: `TaskModel.current_attempt`, `TaskStateProjector.handle(TaskAttemptCreated)`, DP-CON-01 |
| Event global position -> aggregate version -> timestamp | `position` is the database-wide append/cursor order. `version` is sequence and duplicate protection only within one `aggregate_id`. `timestamp` is an ISO event value and is neither unique nor the ordering key. Normal append assigns versions per aggregate before flush; empty-DB bootstrap sorts/deduplicates by recorded position, preserves timestamps, and regenerates per-aggregate versions in global-position order. These values are not aliases and timestamp order must not be treated as causal order. | implemented, tested by `SqliteEventStore.append`, `bootstrap_from_jsonl`, `tests/integration/test_database.py::test_events_v2_retry_identity_is_aggregate_version_not_payload_identity`, and `tests/integration/test_jsonl_rotation_recovery.py::test_bootstrap_replays_archives_and_active_in_global_position_order` |
| SQL transaction -> post-commit JSONL -> empty-DB bootstrap | During normal writes, event rows and synchronous SQL projections share a transaction; JSONL is queued and emitted after commit. If that secondary output fails, SQL remains authoritative and can drain missing positions to JSONL. Conversely, only when `events_v2` is empty, bootstrap can import archive+active JSONL, recreate event rows, and rebuild projections for deserializable event types; unknown event types remain rows but do not project. | implemented, tested by `commit_with_event_outbox`, `drain_committed_events_to_journal`, `bootstrap_from_jsonl`, event-log durability tests, and JSONL rotation recovery integration tests |
| DB backup copy -> metadata timestamp -> journal marker | `backup_timestamp` and second-resolution `backup_id` are captured first; the DB file is copied next; active/archive journals are scanned afterward for their maximum `position` or legacy `sequence_number`. This is not one atomic recovery cut: concurrent writes can move the journal marker beyond the copied DB, and a live WAL-mode database may have state in sidecars not copied by `shutil.copy2`. `restore_backup` only restores the DB file and returns metadata; it does not replay after the marker. | implemented ordering; unit-tested with fake files and integration-tested for marker scanning; crash-consistent live backup unclear. Evidence: `create_backup`, `restore_backup`, `scan_max_sequence` |
| Journal active tail -> archive rotation/recovery | Rotation archives the active file by hard link, fsyncs the parent, unlinks active, and later creates a fresh active file. Startup/write recovery completes an interrupted link-before-unlink state by inode equality. Before append, a valid unterminated final JSON record gets a delimiter; an invalid final fragment is truncated. Position deduplication spans actual active/archive content, including sparse archive ranges. | implemented, tested by `JsonlOutboxObserver`, `_recover_linked_rotation`, `_repair_active_append_boundary`, `tests/unit/test_jsonl_rotation.py`, and `tests/integration/test_event_log_durability.py::test_journal_drain_repairs_partial_final_record_before_replacement` |
| Graph event history -> node detail summary | `GraphNodeDetailSummaryModel` is a mutable latest projection keyed by `(run_id, node_id)` with a latest applied `position`; its record/event arrays are compact materializations and may omit heavy values. Rows can be deleted and rebuilt from graph events, so they are not immutable historical node/record entities or a backup substitute. | implemented, tested by `tests/integration/test_graph_node_detail_read_models.py::test_deleted_node_detail_rows_rebuild_on_summary_read`, `test_deleted_node_detail_rows_do_not_partially_rebuild_on_append` |

### Lifecycle boundaries

- **DP-LIFE-run (implemented, tested):** `RunStatus` declares `draft`, `active`,
  `paused`, `stopping`, `completed`, `failed`, and `cancelled`.
  `TERMINAL_RUN_STATUSES` contains completed/failed/cancelled, while its comment
  documents a graph-specific reopen exception for failed. Persistence stores an
  unconstrained string. `RunStateProjector.handle(RunStatusChanged)` sets
  `started_at` only on draft-to-active and sets `completed_at` for terminal
  statuses. Restart survival is exercised by
  `tests/integration/test_full_persistence.py`.
- **DP-LIFE-run-index (implemented, tested):** run progress also has
  `current_step_index` and `TransitionTracker`; those are not run status and do
  not identify a step. Step completion moves the index, and backward events can
  rewind it. Evidence: `RunStateProjector`, `TransitionTracker`, and projector
  tests.
- **DP-LIFE-step (implemented, tested):** no step-status enum exists. Step
  lifecycle is represented by `completed`, `skipped`, `skip_reason`, optional
  human approval, and condition JSON. Completed and skipped are separate booleans
  and can both be true.
- **DP-LIFE-task (implemented, tested):** `TaskStatus` declares pending,
  building, pending-user-action, verifying, recovering, fan-out-running,
  completed, and failed. Persistence/API response statuses are strings. Task
  `current_attempt` is a counter/current ordinal and is not an attempt identity.
- **DP-LIFE-attempt (implemented, partially tested):** an attempt has timestamps
  and free-form `outcome`; comments enumerate passed, revision-needed, failed,
  paused, and reverted, but neither state nor ORM/API schema constrains values.
  `paused_at` is omitted from `AttemptSchema`, even though state and ORM persist
  it. Attempt outcomes and restart persistence are tested; complete outcome-enum
  behavior is not.
- **DP-LIFE-requirement (implemented, tested):** requirement/checklist lifecycle
  uses `ChecklistStatus`; grade is a separate nullable string. Config `must` and
  priority are template properties, but persisted checklist JSON has no SQL
  shape constraint and `run_model_to_domain` expects `req_id`, `desc`, and
  `priority` keys.
- **DP-LIFE-event-projection (implemented, tested):** workflow read models are
  mutable projections of append operations to `events_v2`. `ProjectionRegistry`
  applies projectors in the same SQLAlchemy session before commit and stores
  projector checkpoints. Rebuild parity is tested in
  `tests/integration/test_event_sourced_workflow.py` and
  `tests/integration/test_event_log_durability.py`.
- **DP-LIFE-session-json (implemented, tested, unclear reachability):**
  `SessionStateManager` is a second, optional whole-run JSON persistence
  mechanism with in-memory-first mutation semantics. Save/load is tested in
  `tests/integration/test_session_persistence.py`; its current production role
  relative to SQL/event persistence is not established in this scope.

### Alias and non-alias map

| Terms | Finding | Status |
|---|---|---|
| `runner_type` / `agent_runner_type` | ORM column versus state/API name; repository conversion explicitly maps them. Historical `claude_sdk` normalizes to `retired` only at read/migration boundaries. | implemented, tested |
| `runner_config` / `agent_runner_config` | ORM versus state/API names mapped by repository conversion. | implemented, tested |
| `runner_started_at` / `agent_runner_started_at` | ORM versus state/API names mapped by repository conversion. | implemented, partially tested |
| `RequirementConfig.id` / `ChecklistItem.req_id` | Explicit conversion in `create_checklist_from_requirements`; this is a per-task lineage mapping, not evidence that requirement is a task or record. | implemented, tested |
| `Run.id` / `routine_id` | Not aliases. Run identity is generated independently; routine ID identifies the source template reference. | implemented, tested |
| step/task `id` / `config_id` | Not aliases. Runtime IDs are generated; config IDs retain template identity. | implemented, tested |
| `Attempt.id` / `AttemptModel.attempt_id` | Conflicting semantics; see DP-CON-01. Equality occurs on event-projected creation, but legacy conversion does not establish it globally. | unclear/conflicting |
| event `position` / `(aggregate_id, version)` / graph `event_id` | Not aliases. Position is global ordering/API activity cursor; aggregate/version is retry/order identity; graph event ID is an envelope identifier retained in payload/projections. | implemented, tested |
| task / graph node | Not aliases. A node can carry `task_region_id`, but no FK/equivalence exists. | implemented distinction, relationship unclear |
| step / graph region | No graph-region schema is in the assigned scope. `task_region_id` cannot prove a region equals a step or task. | unclear |
| graph record / event | Not aliases. Accepted-record facts arrive in events, while record summaries have their own `record_id` embedded in JSON. | implemented distinction, tested |
| graph record / requirement | Not aliases. Verification-record JSON may contain `requirement_id`; task checklist uses `req_id`; no conversion is defined in this scope. | implemented distinction, relation unclear |
| artifact / output record | Not aliases. Some records can describe artifacts, while `ArtifactSpec`, interaction logs, evidence paths, and graph records have different identity/lifecycle boundaries. | implemented distinction, unclear umbrella vocabulary |
| backup ID / backup timestamp | Related but not aliases: both originate from the same `now`, while `backup_id` truncates to whole-second filename form and `backup_timestamp` retains the serialized datetime precision/value. Neither is content identity. | implemented, tested |
| backup DB / metadata sidecar / journal segment | Not aliases and not one owned bundle. The DB copy and metadata sidecar share a filename stem; metadata only references an external journal path and marker, and no journal segment is copied by backup creation. | implemented distinction, tested |
| journal marker / event timestamp | Not aliases. The marker is the maximum integer global position or legacy sequence found during a later scan; event and backup timestamps do not define that recovery cut. | implemented distinction, tested |
| model / profile | Not aliases. Profile selects a cognitive role/default; model is the resolved provider/model string captured on attempts or defaults. | implemented distinction, tested |
| routine SHA / routine commit / branch SHA / attempt commits | Not aliases. They occupy separate fields and refer to routine content/version, repository read point, run source branch, seed intent, or builder/verifier handoff. | implemented; some round-trips tested |

### Persistence table inventory

Current ORM-declared tables:

| Table | Identity and role | Authority/ownership status |
|---|---|---|
| `runs` | PK `id`; root mutable run read model and provenance/config carrier. | owned root; self-parent FK |
| `steps` | PK `id`; ordered step read model. | run-owned cascade |
| `tasks` | PK `id`; ordered task read model, checklist JSON, fan-out fields, optimistic `version`. | step-owned cascade; optional self-parent FK |
| `attempts` | PK `id`; ordered attempt read model plus nullable `attempt_id`. | task-owned cascade |
| `cost_records` | PK `id`; unique execution tuple, immutable-usage-shaped fields. | run/task FKs, optional attempt-PK FK |
| `interaction_log_artifacts` | PK `id`; prompt/output/action-log artifact for an execution tuple. | run/task FKs, optional cost/attempt-PK FKs |
| `events_v2` | PK global `position`; unique `(aggregate_id, version)`; raw JSON text payload. | normal-write transactional authority with SQL projections; empty-DB import target for JSONL bootstrap; no run FK |
| `graph_event_summaries` | Composite PK `(run_id, position)` and retained graph `event_id`. | disposable projection, no run FK |
| `graph_projection_snapshots` | PK `run_id`; latest graph projection JSON. | disposable projection, no run FK |
| `graph_node_detail_summaries` | Composite PK `(run_id, node_id)`; compact node/record/event JSON. | disposable projection, no run FK |
| `graph_node_detail_summary_checkpoints` | PK `run_id`; latest applied graph position. | disposable projection checkpoint |
| `graph_outbox` | Integer PK `outbox_id`; event-linked side-effect intent, unique `event_id`. | no FK; retry/status lifecycle |
| `projection_checkpoints` | PK `projector_name`; last global event position. | global workflow projection progress |
| `clarification_requests` | PK `id`; run/task/attempt-number attribution and question JSON. | run-owned FK only |
| `clarification_responses` | PK `id`; unique request FK, answers and respondent. | request-owned cascade, zero-or-one |
| `agent_runner_model_profile_defaults` | PK `id`; unique `(runner_type, profile)` mapping. | independent configuration table |
| `routine_meta` | integer PK; unique `(routine_id, source)`. | supplementary metadata; no routine FK |

Migration-declared current or residual tables not represented by ORM classes in
the assigned DB module:

- **implemented, migration-backed:** `agent_configs` stores named prompts and a
  model profile. The table is created in
  `b1c2d3e4f5a6_add_agent_configs_table.py`; its ORM/service lies outside this
  audit, so current use is unclear here.
- **implemented, migration-backed:** `replay_checkpoints` stores a unique journal
  path, last sequence/time, optional backup snapshot ID, and update time. It is
  created in `e5fe8c18b483_add_replay_checkpoints_table.py`; no assigned ORM
  symbol uses it, so reachability is unclear.
- **implemented, residual migration schema:** legacy `events` is created by the
  initial migration and no upgrade migration in this scope drops it. It has a
  run FK and integer ID, unlike `events_v2`. It is absent from current ORM
  metadata, so file-backed Alembic databases and in-memory `Base.metadata`
  databases have different table inventories. No current writer was found in
  the assigned source.
- **implemented removal:** `pending_signals` is explicitly dropped by
  `w1a2b3c4d5e6_drop_pending_signals_table.py` after signal persistence moved to
  events. It is historical, not a current entity table.
- **implemented rename:** `runner_profile_defaults` is historical and renamed to
  `agent_runner_model_profile_defaults` by
  `t1a2b3c4d5e6_rename_runner_profile_defaults_table.py`.

Recovery filesystem artifacts are not persistence tables:

- **implemented, tested:** `orchestrator-<backup_id>.db` is the copied database
  file, created and restored with `shutil.copy2`.
- **implemented, tested:** `orchestrator-<backup_id>.backup-meta.json` is a
  separately readable sidecar and the input identity for `restore_backup`.
- **implemented, tested:** active `history.jsonl` and range archives such as
  `history.<first>-<last>.jsonl` are separate secondary/recovery artifacts.
  `create_backup` records their path/maximum observed cut but does not own or copy
  them.

### Closed-scope demand findings for `domain-persistence`

| Scope key | Audit result | Status |
|---|---|---|
| `jobs.J3.proposer` | Graph activity compaction preserves `proposed_by_node_id` for patch events; clarification and approval persistence instead records respondents/approvers. No universal proposer entity or actor FK exists in this scope. | partial implementation, tested indirectly; equivalence unclear |
| `jobs.J4.attempt-lineage` | Task owns ordered attempts and stores current/max counters; event-projected attempts use event `attempt_id` as both columns. No previous-attempt/supersession FK, no unique task+ordinal, and legacy persistence can leave `attempt_id` null. | partial, tested; identity conflict |
| `jobs.J5.artifacts` | Interaction-log artifacts are typed rows; expected artifacts/evidence files are paths; graph artifact-like outputs are embedded records. Backup DB copies, metadata sidecars, and journal segments are operational recovery artifacts, not execution output aliases. No single artifact inventory or shared artifact ID exists. | partial, tested in separate paths; umbrella identity unclear |
| `jobs.J5.output-records` | Graph node detail summaries persist compact output-record JSON with `record_id`, kind, producer, and port; heavy value may be deliberately omitted. No normalized output-record table exists. | implemented projection, tested; source-of-truth lies outside scope |
| `jobs.J8.routine-sha` | `routine_sha` is persisted and exposed on run responses and survives restart. It remains distinct from `routine_commit`. | implemented, tested |
| `jobs.J8.model-profile` | Model defaults and task profile exist; attempts persist resolved model but not profile. A run/attempt cohort cannot read both model and profile directly from the core attempt row. | partial, profile persistence for execution unclear |
| `journeys.B.recorded-identity-timestamp` | Clarification response records ID, respondent, and timestamp; step approval JSON records approver/time; event rows record position/timestamp; no universal decision-record entity was found. | partial, tested; decision-type-specific |
| `journeys.D.execution-unit-identity` | Run, task, attempt, and graph execution IDs are distinct. Attempt and graph execution identity mappings are not fully represented in assigned core tables; cost/log rows use task, attempt PK/number, runner, and phase. | partial/unclear |
| `journeys.continuity.canonical-selection` | Stable runtime run/step/task/attempt IDs exist and APIs expose them; graph node, record, event, requirement, time, and decision do not form one persisted canonical selection key. | gap/unclear; no implemented chain in scope |
| `feedback.durable-identity` | Multiple durable IDs exist: event position+aggregate version, graph event ID, clarification request/response IDs, outbox event ID, and record IDs embedded in graph projections. No evidence proves one universal action-feedback identity. | partial; must remain typed by carrier |
| `ia.selection.identity-chain` | The demanded run-region-step-node-task-attempt-record-event-requirement chain is not an implemented relational chain. The only enforced core hierarchy is run->step->task->attempt; node/record/event/requirement links are strings or JSON and region is undefined here. | absent as a single chain; component identities partial |

### Test-evidence boundary

- **tested:** Core run/step/task/attempt persistence survives real file-backed
  restart and full lifecycle in `test_full_persistence.py`.
- **tested:** Core ownership cascades and ordered relationships are exercised in
  `test_database.py`.
- **tested:** Event rows and core projections rebuild from `events_v2`, including
  attempts, in `test_event_sourced_workflow.py` and
  `test_event_log_durability.py`.
- **tested:** `events_v2` intentionally has no event ID and accepts duplicate
  payloads at different aggregate versions in `test_database.py`.
- **tested:** Graph summaries/node-detail projections are transactional,
  rebuildable, and preserve separate node/record/event IDs in graph read-model
  integration tests.
- **tested:** Model profile enumeration/default mappings round-trip through API
  integration tests. This does not test profile attribution on attempts because
  no such field exists.
- **tested:** Requirement config IDs convert to checklist `req_id`, checklist
  grades survive persistence, and attempt grade snapshots are projected.
- **tested:** Empty-database bootstrap reads archived and active JSONL in global
  position order, deduplicates repeated positions, and recreates `events_v2`;
  malformed records are skipped in `test_jsonl_rotation_recovery.py`.
- **tested:** Backup helpers copy a DB-shaped file, write/read the metadata
  sidecar, restore the copy, and scan active plus archived journals for the
  maximum position/legacy sequence in `test_backup.py` and
  `test_jsonl_rotation_recovery.py`.
- **tested:** JSONL rotation durability, hard-link interruption recovery, actual
  position deduplication across sparse archives, concurrent writers, and partial
  active-tail repair are exercised in `test_jsonl_rotation.py` and
  `test_event_log_durability.py`.
- **untested in inspected evidence:** distinct non-null values for
  `AttemptModel.id` and `.attempt_id`, global uniqueness of `attempt_id`,
  uniqueness of attempt ordinal within task, a canonical cross-projection
  selection identity, relational integrity from node/record/requirement IDs to
  core rows, a crash-consistent backup of a live WAL-mode SQLite database, backup
  ID collision behavior, or automatic journal replay from `BackupMetadata`.

## Important uncertainties

- **DP-Q-01 (blocking identity):** Which attempt identifier is canonical for new
  semantic contracts: `Attempt.id`/`attempts.id`, nullable `attempts.attempt_id`,
  or a typed pair with explicit conversion? Current paths do not agree.
- **DP-Q-02 (blocking selection):** No bounded source defines a canonical key
  spanning run, region, step, node, task, attempt, record, event, requirement,
  decision, and time. Region is absent; several other links are untyped JSON.
- **DP-Q-03:** Does `routine_sha` mean content hash, git revision, or routine
  repository version in every routine source mode? The field round-trips but its
  derivation is outside scope. `routine_commit` coexists without a scoped
  conversion rule.
- **DP-Q-04:** How should execution profile be attributed historically? Task
  config has a profile and runner defaults map profile to model, but attempts
  persist model/runner only and mutable defaults cannot safely reconstruct the
  original profile.
- **DP-Q-05:** Is `SessionStateManager` still a production persistence boundary
  or only compatibility/test infrastructure? Its in-memory-first semantics differ
  from the SQL event/projection path.
- **DP-Q-06:** Is the legacy `events` table intentionally retained in migrated
  databases? It is absent from ORM metadata and current scoped writers, creating
  file-backed versus in-memory schema drift.
- **DP-Q-07:** Are graph output/file-state records authoritative records or
  deliberately lossy projections? `GraphNodeDetailSummaryModel` is explicitly
  disposable and tests verify heavy record `value` is omitted.
- **DP-Q-08:** What entity, if any, owns `parent_task_id` on a child run and
  `task_region_id` on a graph node? The database does not enforce either.
- **DP-Q-09:** Proposer/respondent/approver are strings or node IDs with no actor
  entity/FK. Their identity namespace and whether they may be compared are
  unclear.
- **DP-Q-10:** API schemas frequently type statuses/outcomes/identity-bearing
  fields as plain strings. Their acceptance shape does not prove reachable
  values or persistence guarantees without route/presenter evidence from other
  audits.
- **DP-Q-11 (recovery integrity):** Is `create_backup` intended for a live
  WAL-mode database? The plain main-file copy excludes `-wal`/`-shm` and is not
  coordinated with the later journal scan, so the copied DB and recorded marker
  may not describe one atomic cut.
- **DP-Q-12:** Which runtime consumes `BackupMetadata.journal_sequence_marker`
  after `restore_backup`? Restore returns the marker but performs no replay, and
  no consumer is present in the assigned scope.
- **DP-Q-13:** Are second-resolution `backup_id` collisions acceptable? Two
  backups in the same second target the same DB and metadata filenames with no
  no-clobber check.

## Conflicts found

### DP-CON-01: Attempt identity contracts disagree

- **documented-only claim:**
  `src/orchestrator/db/migrations/versions/k1a2b3c4d5e6_add_attempt_id_to_attempts.py`
  says `attempt_id` is the globally unique semantic identity and `id` is only the
  DB primary key. `AttemptRecord` repeats the global-identity claim.
- **implemented counter-evidence:** `AttemptModel.attempt_id` is nullable and not
  unique; `Attempt` exposes only `id`; `run_model_to_domain` reads
  `AttemptModel.id`; `run_to_model` never sets `.attempt_id`; cost/log
  `attempt_id` FKs target `attempts.id`.
- **implemented/tested special path:** `TaskStateProjector` sets both columns to
  the event `attempt_id`, and projector/rebuild tests exercise equality.
- **Disposition:** unresolved. Do not alias `id` and `attempt_id` globally and do
  not infer lineage from ordinal alone.

### DP-CON-02: Event/journal authority ordering disagrees with required documentation

- **documented-only claim:** `AGENTS.md` says transitions are logged to JSONL
  first, then state is updated, and recovery reconstructs from history.
- **implemented counter-evidence:** `SqliteEventStore.append` flushes
  `events_v2`, applies projections in the same transaction, queues the journal,
  and `commit_with_event_outbox` commits SQL before writing JSONL.
  `drain_committed_events_to_journal` explicitly calls the event table
  authoritative after post-commit observer failure.
- **implemented reverse recovery path:** `bootstrap_from_jsonl` runs only when
  `events_v2` is empty, imports active and archived journal records, regenerates
  aggregate versions, and rebuilds projections for deserializable events.
- **tested evidence:** event-store wiring/durability tests verify normal DB-first
  writes and DB-to-JSONL drain; JSONL rotation recovery tests verify
  empty-database JSONL-to-DB bootstrap.
- **Disposition:** unresolved documentation conflict. Current scoped semantics
  are conditional: normal writes use SQL transactional authority with
  post-commit JSONL, while empty-database recovery may reconstruct SQL events and
  projections from JSONL. Later catalogs must preserve both directions rather
  than state an unconditional SQL-first or JSONL-first rule.

### DP-CON-03: Attempt outcome shape differs across layers

- **implemented state comment:** `Attempt.outcome` lists passed,
  revision-needed, failed, paused, and reverted.
- **documented-only dataclass comment:** `AttemptRecord.outcome` lists only
  passed, revision-needed, and failed.
- **implemented schema:** ORM and API accept nullable arbitrary strings.
- **Disposition:** unresolved vocabulary; do not create a closed attempt-outcome
  enum from comments alone.

### DP-CON-04: Run lifecycle vocabulary in required docs is stale/incomplete

- **documented-only claim:** `AGENTS.md` debugging guidance lists queued, active,
  paused, completed, and failed as `RunResponse.status` examples.
- **implemented counter-evidence:** `RunStatus` uses draft rather than queued and
  additionally includes stopping and cancelled; `RunResponse.status` is plain
  string.
- **Disposition:** current enum controls accepted domain vocabulary inside this
  scope; API reachability and transition legality remain for workflow/API audits.

### DP-CON-05: In-memory and migrated file databases do not have identical table sets

- **implemented file path:** `init_db` runs the full Alembic chain for file-backed
  databases; the initial chain creates legacy `events`, and no upgrade drops it.
- **implemented in-memory path:** `init_db` uses `Base.metadata.create_all`, which
  has `events_v2` but no legacy `events`, `agent_configs`, or
  `replay_checkpoints` ORM model in this module.
- **tested evidence:** tests exercise both paths but the inspected table test only
  requires the core/current tables.
- **Disposition:** unresolved schema-parity concern; do not infer current entity
  status from table existence alone.

### DP-CON-06: Backup marker terminology is legacy while implementation is dual-format

- **documented-only claim:** `BackupMetadata.journal_sequence_marker` and the
  `create_backup` docstring call the cut the maximum `sequence_number` and a
  replay start point.
- **implemented qualification:** `scan_max_sequence` prefers current `position`,
  falls back to legacy `sequence_number`, scans active plus archives, and returns
  only the maximum integer. `restore_backup` returns that value but does not
  replay anything.
- **tested evidence:** unit tests cover legacy sequence values; rotation recovery
  integration tests cover current positions and archive-only journals.
- **Disposition:** preserve the field as a dual-format observed journal marker,
  not proof of an automatically applied or atomic replay cut.

## Decisions required

No product decision should override the observed distinctions. Synthesis or
targeted engineering adjudication is required for:

1. Select and document the canonical attempt identity and conversion/migration
   rule; decide whether `attempts.attempt_id` is retained, made unique/non-null,
   or removed in favor of `attempts.id`.
2. Define typed links, or explicit absence, for the demanded persistent selection
   chain. In particular, decide whether region, node, record, event, requirement,
   and decision identities can be joined and under which namespace/version.
3. Decide whether execution profile must be persisted on each attempt/graph
   execution to support historical model-and-profile cohorts.
4. Reconcile normal-write SQL transactional authority plus post-commit JSONL and
   the empty-database JSONL bootstrap path with the unconditional JSONL-first
   project documentation.
5. Determine whether legacy `events`, `replay_checkpoints`, and JSON session
   persistence are current, compatibility-only, or removable; schema existence
   is insufficient classification.
6. Define whether “artifact” is an umbrella with typed variants or should remain
   several separate entities. Do not merge expected paths, interaction logs,
   evidence bundles, and graph records by name alone.
7. Decide whether backup requires a SQLite-consistent snapshot mechanism,
   collision-resistant identity, owned journal segments, and an executable replay
   procedure. Do not present the current timestamp plus max-position metadata as
   an atomic recovery point.

## Artifact paths

- Created report:
  `research/ui-foundation/agent-reports/01-domain-persistence.md`.
- Task handoff:
  `.superpowers/sdd/task-3-audit-report.md`.
- No canonical YAML, source documentation, product code, or other report was
  edited.

## Evidence pointers

Highest-value implementation pointers:

- `src/orchestrator/db/orm/models.py::RunModel`, `StepModel`, `TaskModel`,
  `AttemptModel`, `AttemptRecord`, `EventV2Model`, `GraphEventSummaryModel`,
  `GraphProjectionSnapshotModel`, `GraphNodeDetailSummaryModel`,
  `CostRecordModel`, `InteractionLogArtifactModel`,
  `ClarificationRequestModel`, and `ClarificationResponseModel`.
- `src/orchestrator/db/access/repositories.py::run_model_to_domain`,
  `run_to_model`, and `RunRepository`.
- `src/orchestrator/db/access/event_store_v2.py::StoredEvent`,
  `SqliteEventStore.append`, `get_events_paginated`, and
  `create_wired_event_store_v2`.
- `src/orchestrator/db/access/event_outbox.py::commit_with_event_outbox` and
  `src/orchestrator/db/access/jsonl_outbox.py::JournalSegment`,
  `discover_journal_segments`, `JsonlOutboxObserver`,
  `drain_committed_events_to_journal`, `_rotate`,
  `_recover_linked_rotation`, and `_repair_active_append_boundary`.
- `src/orchestrator/db/bootstrap.py::bootstrap_from_jsonl` and
  `_parse_jsonl_record`.
- `src/orchestrator/db/recovery/backup.py::BackupMetadata`, `create_backup`,
  `restore_backup`, and `scan_max_sequence`.
- `src/orchestrator/db/projections/task_state.py::TaskStateProjector` and
  `_attempt_values_from_snapshot`.
- `src/orchestrator/db/projections/run_state.py::RunStateProjector`.
- `src/orchestrator/db/projections/registry.py::ProjectionRegistry`.
- `src/orchestrator/state/models.py::Run`, `StepState`, `TaskState`, `Attempt`,
  `ChecklistItem`, and `ModelTokenUsage`.
- `src/orchestrator/state/factory.py::create_run_from_routine`,
  `create_step_state`, `create_task_state`, and
  `create_checklist_from_requirements`.
- `src/orchestrator/state/session.py::SessionStateManager`.
- `src/orchestrator/config/models.py::RoutineConfig`, `StepConfig`, `TaskConfig`,
  `RequirementConfig`, and `ArtifactSpec`.
- `src/orchestrator/config/enums.py::RunStatus`, `TaskStatus`,
  `ChecklistStatus`, `ModelProfile`, and `TERMINAL_RUN_STATUSES`.
- `src/orchestrator/api/schemas/runs.py::RunResponse`, `RunTraceAttempt`, and
  `RunEvidenceItem`; `src/orchestrator/api/schemas/tasks.py::AttemptSchema` and
  `TaskDetailResponse`; `src/orchestrator/api/schemas/activity.py::ActivityEvent`;
  `src/orchestrator/api/schemas/cost_rollup.py::CostRollupFact`.

Highest-value test pointers:

- `tests/integration/test_database.py::test_event_v2_metadata_exposes_durability_contract`.
- `tests/integration/test_database.py::test_events_v2_retry_identity_is_aggregate_version_not_payload_identity`.
- `tests/integration/test_full_persistence.py::test_full_lifecycle_survives_restart`.
- `tests/integration/test_event_sourced_workflow.py::test_empty_database_can_be_rebuilt_from_events_v2`.
- `tests/integration/test_event_log_durability.py::test_canonical_projection_snapshot_matches_after_events_v2_rebuild`.
- `tests/integration/test_graph_read_models.py::test_graph_read_models_are_rebuildable_and_idempotent`.
- `tests/integration/test_graph_node_detail_read_models.py::test_append_creates_and_updates_node_detail_summaries`.
- `tests/integration/test_jsonl_rotation_recovery.py::test_bootstrap_replays_archives_and_active_in_global_position_order`,
  `test_backup_scans_all_archives_and_active_for_maximum_position`, and
  `test_backup_scans_archives_when_the_active_journal_is_missing`.
- `tests/integration/test_event_log_durability.py::test_journal_drain_repairs_partial_final_record_before_replacement`.
- `tests/unit/test_backup.py::test_create_backup_copies_db_and_writes_metadata`,
  `test_create_backup_with_journal_captures_sequence`, and
  `test_restore_backup_copies_db_back`.
- `tests/unit/test_jsonl_rotation.py::test_rotation_syncs_active_then_links_fsyncs_unlinks_and_fsyncs_parent`,
  `test_linked_rotation_recovery_syncs_before_and_after_unlink`, and
  `test_rotation_recovers_linked_active_file_before_appending`.
- `tests/unit/test_run_factory.py::test_create_run_deterministic_ids` and
  `test_create_checklist_from_requirements`.
- `tests/integration/test_api_model_profiles.py::test_set_and_get_model_defaults_roundtrip`.

## Recommended next delegation

1. Domain synthesis should preserve run, routine, step, task, attempt, graph
   node, graph record, workflow event, graph event, requirement/checklist item,
   clarification, artifact variants, model, and profile as separate provisional
   entities until typed conversion evidence is merged from other reports.
2. Assign a narrow attempt-identity adjudication to inspect workflow event and
   command definitions plus all attempt creation paths; resolve DP-CON-01 before
   canonical entity IDs or persistent-selection contracts are allocated.
3. Have graph-runtime synthesis supply typed node/region/record relationships and
   identify the authoritative record store; this report proves only disposable
   relational projections.
4. Have workflow-state/API audits settle reachable lifecycle values, action
   feedback identities, and actor/proposer namespaces.
5. Have tests/documentation audit register DP-CON-02, DP-CON-04, DP-CON-05, and
   DP-CON-06 rather than smoothing them into architecture prose.
6. Delegate a narrow recovery-integrity audit/design decision for live SQLite
   backup consistency, backup identity collision, marker semantics, and replay
   ownership before presenting backups as recoverable points in UI contracts.
