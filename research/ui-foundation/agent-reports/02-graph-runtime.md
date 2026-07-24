# Graph Kernel and Runtime Audit

## Purpose

Bounded implementation-reality audit of the execution-graph kernel and its
runtime adapter. This report is evidence for later normalization, not a
canonical entity/action model. Status labels are **implemented**, **tested**,
**documented-only**, **inferred**, or **unclear**; they do not make graph terms
aliases of workflow terms.

## Scope inspected

- `src/orchestrator/graph/`: models, contracts, command models/applier,
  patch validator, scheduler, projections, event registry, and test store.
- `src/orchestrator/graph_runtime/`: controller, durable store, dispatch,
  outbox, recovery, and horizon templates.
- Graph-focused unit/integration coverage, particularly
  `tests/unit/test_graph_{models,commands,scheduler_view,dynamic_contract,event_registry,runtime_store_mirror_guards}.py` and
  `tests/integration/test_graph_{controller_transactions,outbox_crash_points}.py`.
- Required brief, approved design, `catalog/scope.yaml`, and delegation plan.

## Key findings

- **[implemented, tested] Topology and direction.** `NodeModel`/`EdgeModel`
  (`graph/models.py`) define directed `from_node_id.from_port ->
  to_node_id.to_port` edges. `EdgeModel.dependency_type` distinguishes
  `input_binding` from `state_dependency`; the latter is completion ordering,
  whereas the former carries selected output records. `GraphProjection` keeps
  edges, input bindings, node states, leases, and output-record summaries
  separately (`graph/projections.py::GraphProjection`). Therefore an edge is
  neither a record nor a task dependency in the core workflow sense.
- **[implemented, tested] Cardinality/binding.**
  `contracts.py::PortContract.cardinality` is `one|many|latest|all` and limits
  legal binding policies. `merge_bound_record_ids` implements first/latest/all
  and supersession replacement; `InputBindingProjection` records the resulting
  record IDs and graph positions. Required ports gate readiness, not merely
  topology. Covered by `test_graph_models.py`, `test_graph_commands.py`, and
  `test_graph_scheduler_view.py`.
- **[implemented, tested] Typed node/record contracts.**
  `NodeKind` and `NodeState` enumerate graph-local kinds/states. Contract
  registry `DEFAULT_NODE_CONTRACTS` validates node roles, ports, record types,
  schemas, selectors, hydration and binding policies. Typed records include
  candidate, verification report, check result, file state, requirement,
  artifact reference, gap classification, join result, completion decision,
  and graph-patch proposal (`graph/models.py`; validation in
  `graph/_commands.py::_output_record_contract_conflict`). Output acceptance
  emits `output_record_accepted`, then `input_bound` events for matching
  outgoing edges; projection reduces both into records/bindings.
- **[implemented, tested] Complete inventories.** `NodeKind` contains exactly
  `root`, `run_root`, `routine_snapshot`, `task_projection`, `worker`,
  `verifier`, `check`, `planner`, `gap_planner`, `summarizer`, `join`,
  `final_gate`, `human_gate`, `authority_request`, `oversight`, `appeal`,
  `gate`, `recovery`, `review`, `artifact`, `artifact_index`, `requirement`,
  `file_state`, and `session` (`graph/models.py::NodeKind`). `GraphRecordKind`
  is the separate legacy/general event-like inventory: `node_created`,
  `edge_created`, `node_retired`, `node_state_changed`, `lease_granted`,
  `lease_suspended`, `lease_revoked`, `callback_received`,
  `callback_accepted`, `callback_rejected_stale`, `verification_passed`,
  `verification_failed`, `revision_created`, `appeal_opened`,
  `oversight_decision_recorded`, `approval_decision_recorded`,
  `graph_patch_accepted`, and `file_state_accepted`
  (`graph/models.py::{GraphRecordKind,GraphRecord}`). It is not the typed
  output-record inventory.
- **[implemented, tested] Typed graph-record inventory.** The concrete
  semantic `TypedRecordBase` output/evidence types are `OutputRecord` (generic
  `fan_out_inputs`), `RunContextRecord`, `RoutineSnapshotRecord`,
  `ArtifactReferenceRecord`, `VerificationReportRecord`,
  `CompletionDecisionRecord`, `JoinResultRecord`, `CheckResultRecord`,
  `CandidateRecord`, `GapClassificationRecord`, `DecisionRecord`,
  `AuthorityDecisionRecord`, `AnalysisSummaryRecord`,
  `GraphPatchProposalRecord`, `RequirementRecord`, `DecisionRequestRecord`,
  `AuthorityRequestRecord`, `FailureRecord`, `RecoveryPlanRecord`, and
  `FileStateRecord` (`graph/models.py`, classes named above). Concrete
  file-state validation/canonical variants are `CanonicalFileStateRecord`
  (forbids extra fields for accepted payload) and `FileStateRejectedPayload`
  (canonical variant plus reason); `StrictFileStateRecord` in
  `graph/command_models.py` is the strict command-input variant used by
  `RecordCleanupAppliedCommand`. Accepted output facts use
  `output_record_accepted`; accepted/rejected file-state facts use their
  dedicated events. This is a semantic record-type inventory, not a claim that
  every validation wrapper is a distinct durable record type.
- **[implemented, tested] Relationship/cardinality facts.** Per run, the
  graph stream has `0..N` ordered `EventEnvelope`s and a disposable `0..1`
  current projection checkpoint. A run projection has `0..N` nodes, edges,
  leases, and output records. A run also has associated durable `0..N` graph
  outbox rows, but they are runtime persistence state (`GraphOutboxModel`),
  not owned fields of `GraphProjection`. Each edge has exactly one source
  node/port and one target node/port; a node may have `0..N` inbound/outbound
  edges. An accepted output record has exactly one producer node/port and may
  bind to `0..N` edges; an input binding is one target node/port/edge with
  record cardinality controlled by its target `PortContract` (`one` => one,
  `latest` => one replacing latest, `many|all` => `0..N`). A lease identifies
  one node/execution/generation at a time; a node has `0..N` historical leases
  and scheduler denies a second active lease for the same node. `task_region_id`
  is optional on node/record payloads, so its `0..1` string reference is not a
  proven Region relationship. Evidence: `models.py::{EdgeModel,InputBinding,
  NodeMembership,LeaseProjection}`, `contracts.py::PortContract`,
  `scheduler.py::{evaluate_readiness,schedule}`.
- **[implemented, tested] Dynamic expansion.** A planner/gap planner submits
  `SubmitPatchCommand`; `apply_command` expands macros then validates and
  emits `graph_patch_accepted`/`graph_patch_rejected` plus topology events
  (`graph/_commands.py`, `patch_validator.py::validate_patch`). Legal ops are
  create node/edge, retire, revision attempt, appeal/gate, authority/resource
  changes, and suspect-region marking. Validator rejects unknown/unauthorized
  ops, duplicate IDs, incompatible ports/selectors, cycles, invalid resource
  paths/escalation, executable nodes without roles, invalid check bindings,
  poisoned pass-gated invariant paths, and missing corrective/gap dependencies.
  `horizon_templates.py` supplies deterministic *planner prompt templates*,
  not pre-created runtime regions.
- **[implemented, tested] Stale patches and callback races.** For
  `base_graph_position < current_position`, a patch is rejected only if an
  intervening *invalidating* event touches its op-derived read set; otherwise
  the older base is accepted. For `== current_position`, no stale check is
  needed. For `> current_position`, `_validate_staleness` returns no rejection
  (`>=` short-circuit), so a future base is currently accepted unless another
  validator rejects the patch; that intent is **[unclear]**.
  `patch_validator.py::_validate_staleness` supplies rejection
  `read_set_diff`/conflicting IDs. Separately and correctly, controller
  `expected_position` is optimistic-concurrency input: `GraphController`
  compares it before planning and inside `BEGIN IMMEDIATE`, then
  `GraphEventStore.append_events`/unique `(aggregate_id, version)` is final
  backstop. Dispatch retries stale/SQLite-lock controller races up to five
  times (`graph_runtime/dispatch.py::_handle_command_retry_stale`).
  **Correction:** callback `observed_graph_position` is required by
  `SubmitCallbackCommand` and copied into `CallbackRequest`, but
  `graph/callbacks.py::validate_callback` does not read or compare it, and
  `_apply_callback_command` does not put it in any callback outcome event
  payload. It is therefore neither validated nor persisted as callback-outcome
  evidence.
  Callback rejection is instead lease existence/state, execution ID, base
  snapshot ID, lease generation, run/node state, expired-lease replacement,
  and accepted-callback idempotency payload conflict. Thus it must not be
  described as callback position validation; it is distinct from controller
  expected-position concurrency.
- **[implemented, tested] Readiness, leasing, and execution.**
  `scheduler.py::evaluate_readiness` requires active run, eligible state,
  unsatisfied-required-input absence, valid upstream/gate/precondition state,
  and non-conflicting resources. `schedule` deterministically orders ready
  nodes by priority, kind (check/final gate/join first), region, creation
  position, and ID. `schedule_tick` grants leases; controller turns each grant
  into `agent_dispatch_requested`, atomically writes event/outbox rows, and
  dispatch maps it to at-least-once `agent_dispatch`.
  `lease_granted/renewed/released/revoked/expired/suspended` project lease
  state/generation/execution identity. Heartbeats renew only active leases;
  completion releases them; cancellation revokes active/suspended leases.
- **[implemented, tested] Runtime durability/recovery.** Graph events use the
  separate `events_v2` aggregate `graph:<run_id>` with ordered graph-local
  positions (`graph_runtime/store.py::GraphEventStore`). Appends transactionally
  maintain compact summaries, node-detail summaries, projection checkpoint,
  usage read model, JSONL secondary outbox, and graph side-effect outbox.
  Projections are disposable/rebuilt if missing, stale, or schema-version
  mismatched. Outbox dispatch is at-least-once: startup resets `dispatching` to
  pending; failure backs off deterministically and ultimately marks failed.
  Recovery identifies active leases awaiting start acknowledgement or callback;
  `reconcile_runtime` turns absent processes into `agent_died`.
- **[implemented, tested] Final-invariant and command behavior.** Check nodes
  require a concrete command, hidden-oracle command, or known binding; the
  dynamic hidden-oracle binding falls back to acceptance command
  (`command_bindings.py`). Join/final-gate evaluation emits typed output record,
  completes node, and releases its scoped lease. `complete` is rejected while
  `final_invariant_blockers_for_events` remains. Lifecycle transitions are
  graph-local and role-gate reopening `failed -> resuming` to human/operator
  (`graph/_commands.py::RUN_LIFECYCLE_TRANSITIONS`).
- **[implemented, tested] Events and projections.**
  `event_registry.py` has a closed producer ownership map and strict payload
  model coverage; unregistered/retired internal names fail at emission/import.
  Command outcome is an event sequence, not a single state mutation: examples
  are patch accepted/rejected, command rejected, callback accepted/rejected or
  duplicate, node/lease changes, output/input binding, and dispatch intent.
  `GraphEventStore` stores sequence order and projection state, but no source
  establishes that adjacent positions alone prove business causality.
- **[tested] Focused verification run.**
  `PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_commands.py tests/unit/test_graph_scheduler_view.py tests/unit/test_graph_dynamic_contract.py tests/unit/test_graph_event_registry.py tests/unit/test_graph_runtime_store_mirror_guards.py tests/integration/test_graph_controller_transactions.py tests/integration/test_graph_outbox_crash_points.py -q -p no:cacheprovider` → **339 passed in 12.83s**.

### COMMAND_SPECS exhaustive command-to-effect table

**[implemented; focused commands/runtime tests exercised representative paths]**
All 23 entries below are from `graph/commands/__init__.py::COMMAND_SPECS`.
Every command first has strict Pydantic payload validation; unknown command,
invalid payload, or missing `PatchCommandContext` for `submit_patch` emits
`command_rejected`. “CR” below means command-specific `command_rejected`.
“Projection” names the primary `GraphProjection` fields, not every derived
read-model column. Only `agent_dispatch_requested` and `cleanup_requested`
map to graph outbox effects (`agent_dispatch`, `snapshot_cleanup` respectively);
other rows have no direct graph-runtime outbox side effect unless stated.

| Command | Validation / rejection | Emitted event sequence on success (or rejection) | Typed records | Projection fields | Runtime / outbox |
|---|---|---|---|---|---|
| `accept_run` | effective state `run_state or draft`; accepts unset/`draft` only | `run_lifecycle_changed` / CR | none | `run_state` | none |
| `start` | effective state `run_state or draft`; accepts known `queued` only | `run_lifecycle_changed` / CR | none | `run_state` | enables scheduler only after active |
| `pause` | effective state `run_state or draft`; accepts known `active→pausing` or `pausing→paused` | `run_lifecycle_changed` / CR | none | `run_state` | no direct cancellation |
| `resume` | effective state `run_state or draft`; accepts known paused/resuming; known failed reopen requires human/operator | `run_lifecycle_changed` / CR | none | `run_state` | active re-enables scheduling |
| `cancel` | effective state `run_state or draft`; accepts known active/paused/cancelling transition | `run_lifecycle_changed`, then per active/suspended lease `lease_revoked`,`node_state_changed(cancelled)` / CR | none | `run_state`,`leases`,`node_states` | no outbox; dispatch must observe revoke |
| `complete` | effective state `run_state or draft`; accepts known active and no final-invariant blockers | optional `output_record_accepted(CompletionDecisionRecord)`, `run_lifecycle_changed` / CR | `CompletionDecisionRecord` | `completion_decision_passed`,`run_state`, output records | none |
| `fail` | effective state `run_state or draft`; accepts every nonterminal effective state, including unset→draft | `run_lifecycle_changed` / CR | none | `run_state` | none |
| `record_heartbeat` | known active lease, active run, matching node/generation | `heartbeat_recorded`,`lease_renewed` / CR | none | lease expiry/state | none |
| `seed_compiled_events` | empty topology; same run; only node/edge/binding/output seed shapes | supplied validated `node_created`/`edge_created`/`input_bound`/`output_record_accepted` / CR | supplied typed verification record where applicable | topology, bindings, records | none |
| `schedule_tick` | active run; readiness/resource/precondition checks; grant cap | expired active lease: `lease_expired`, `output_record_accepted(FailureRecord)`, `node_state_changed(failed)`; then readiness/grant events | `FailureRecord` for expired lease | leases,node states,generic accepted-output/node-port summaries and output payloads plus readiness fields | controller appends `agent_dispatch_requested`; durable `agent_dispatch` outbox |
| `reconcile` | terminal run → CR; otherwise reads verification/check indexes as repair guards and may produce topology/retirement/terminal-failure events, or none | no new typed record directly | nodes/node states,edges,bindings,retirement fields, and possibly `run_state` | none directly |
| `submit_callback` | callback payload identity; idempotency; lease/execution/snapshot/generation/run/node state; output provenance/contracts/authority | `callback_accepted`, validated payload-selected record acceptance/bindings, optional node state/release/session; or `callback_rejected_stale`/`callback_rejected_conflict`/`callback_duplicate_returned` | validated payload-selected output-record model(s) | callback idempotency, records, bindings, node/lease/session state | accepted file-state may lead to later gatekeeper command, not direct outbox |
| `submit_patch` | only known/non-`None` non-active run state is rejected by its run guard; unset `None` passes it, then macro/patch/role/topology/stale/resource/cycle/dynamic/final/budget/request checks apply | `graph_patch_accepted` then op events/bindings/repair; or `graph_patch_rejected` (budget additionally creates/ready gate) | no required record; may consume rationale/carryover references | accepted/rejected patches, topology, sessions, nodes/edges/bindings | none |
| `acknowledge_start` | matching active lease/node/generation/execution | `node_state_changed(running)` with optional prompt-summary event payload / CR | none | `node_states`; this event carries no attempt number, so it does not update `node_attempts`; prompt summary is event evidence, not a projection target | none |
| `agent_died` | known active lease plus matching required execution and retry policy | `agent_died`,`lease_revoked`, then completed, failure, or retry events as policy selects | direct `FailureRecord` or `RecoveryPlanRecord` as policy selects | leases,node states,retry/deferred reasons,output records | none |
| `raise_appeal` | strict invalid-test appeal payload | `appeal_opened`,`node_created(oversight)` | none | pending appeals,nodes | none |
| `record_decision` | decision type/value and target-kind checks; rejects target only at `completed|failed|cancelled|retired`, and run only at `cancelled|failed` | approval/authority/oversight decision event and state updates / CR | `DecisionRecord` or `AuthorityDecisionRecord` projection facts | approval/authority/oversight decisions, gate state | none |
| `record_gatekeeper_verdicts` | known file-state record; unique verdict paths that are unresolved residue | one `gatekeeper_verdict_recorded` containing accepted verdict list, always `gatekeeper_cost_recorded`, and optional secret-triggered `cleanup_requested` | gatekeeper payload rows, not `TypedRecordBase` output | file-state entry resolution; secret cleanup marks record compromised/pending and adds `cleanup_requested_events` | `cleanup_requested` creates associated durable `snapshot_cleanup` outbox row |
| `record_node_usage` | nonempty typed usage; dedupe `execution_id:index` | `node_usage_recorded` per new usage fact | immutable usage payloads, not graph output record | usage keys/tokens/latency/actions by node/kind | store updates run usage read model |
| `record_requirement_revision` | strict IDs/optional revision metadata | `requirement_revision_recorded` | requirement revision projection/evidence, not `RequirementRecord` output | revisions, active requirement versions, authority blockers | none |
| `record_support_evidence` | strict support/evidence/requirement IDs | `support_evidence_recorded` | support evidence projection | support evidence/freshness/final blockers | none |
| `evaluate_join` | node kind `join`; bound source records required; scoped lease pair validated if supplied | `output_record_accepted(JoinResultRecord)`,`node_state_changed(completed)`, optional `lease_released` / CR | `JoinResultRecord` | output records,node state,leases | dispatch executor runs join after lease |
| `evaluate_final_gate` | node kind `final_gate`; scoped lease pair validated if supplied | `output_record_accepted(CompletionDecisionRecord)`,`node_state_changed(completed)`, optional `lease_released` / CR | `CompletionDecisionRecord` | completion decision,node state,leases | dispatch executor runs final gate after lease |
| `record_cleanup_applied` | known unapplied matching cleanup/snapshot; strict superseding file-state record with different clean snapshot | `cleanup_applied`,`output_record_accepted`,`file_state_accepted` / CR | command `StrictFileStateRecord`; emitted canonical `FileStateRecord` | file-state lineage, cleanup applied IDs, output records | completes at-least-once `snapshot_cleanup` intent; no new outbox intent |

The table is a command/kernel mapping, not evidence that every command is a
reachable public UI action. Exact event multiplicity remains data-dependent
(for example, one callback can contain many output records and one scheduling
tick can grant many leases).

### Authoritative COMMAND_SPECS matrix (source correction)

This matrix supersedes the compact table above where they differ. It was traced
against every `_apply_*` applier in `graph/_commands.py`; `CR` is the common
strict-payload/unknown-command/context rejection described above. Projection
fields are the reducer targets for the named events.

| Command | Concrete rejection / data-dependent emitted events | Typed record(s) | Exact primary projection effects | Runtime/outbox |
|---|---|---|---|---|
| `accept_run` | effective `run_state or draft`: unset/`draft` emits lifecycle; every other known state → CR | — | `run_state` | — |
| `start` | effective `run_state or draft`: only known `queued` emits lifecycle; unset has effective `draft` and → CR | — | `run_state` | scheduler becomes eligible only at active |
| `pause` | effective `run_state or draft`: only known `active`/`pausing` transitions emit lifecycle | — | `run_state` | — |
| `resume` | effective `run_state or draft`: only known `paused`/`resuming`, plus human/operator `failed`, emit lifecycle | — | `run_state` | active permits scheduling |
| `cancel` | effective `run_state or draft`: only known `active`/`paused`/`cancelling` emits lifecycle then revoke/cancel events | — | `run_state`,`leases`,`node_states` | no graph outbox |
| `complete` | effective `run_state or draft`: only known active with no final blockers emits optional decision record then lifecycle | `CompletionDecisionRecord` | output records,`completion_decision_passed`,`run_state` | — |
| `fail` | effective `run_state or draft`: every nonterminal effective state emits failed lifecycle; terminal effective states → CR | — | `run_state` | — |
| `record_heartbeat` | unknown/inactive/nonmatching lease/node/generation or inactive run → CR; else `heartbeat_recorded`,`lease_renewed` | — | lease expiry/state | — |
| `seed_compiled_events` | nonempty topology, wrong run, unsupported seed type, malformed node/edge/verification record → CR; else supplied validated `node_created`,`edge_created`,`input_bound`,`output_record_accepted` only | seeded `VerificationReportRecord` when applicable | topology,bindings,records | — |
| `schedule_tick` | no command rejection for ordinary nonready nodes. Every expired active lease emits `lease_expired`; if its node ID is a string it additionally emits `output_record_accepted(FailureRecord(error_class=lease_expired_without_callback))` and `node_state_changed(failed)`. Then each changed nonready node yields `node_deferred` (and `dead_input_detected` for upstream failure); each newly ready node `node_ready`,`node_state_changed(ready)`; selected nodes `node_ready` as needed,`lease_granted`, optional `session_state_changed`,`node_state_changed(leased)`; capacity/resource deferrals yield `node_deferred` | `FailureRecord` only for expiry-with-node | `leases`,`node_states`,`accepted_output_records_by_node_port`,`output_records_by_node_port`,`accepted_record_summaries_by_id`,`output_record_payloads`,`ready_nodes`,`last_deferred_reasons`,sessions/retry fields | controller adds `agent_dispatch_requested` after every grant; only that event creates associated durable `agent_dispatch` outbox rows (not a projection field) |
| `reconcile` | terminal run → CR; otherwise reads verification/check indexes as guards. Failed check/failed verification with active run, no active lease/ready work, unsettled task and routine snapshot create gap-planner `node_created`, evidence/context `edge_created`, possible `input_bound`; passed verification may create final invariant check/edge/binding and retire unreachable failure branch (`node_retired`,`node_state_changed(retired)`); passed check retires unreachable check-failure branch; completed no-successor recovery with no live work and non-environment failure emits `run_lifecycle_changed(...failed)` | no new typed record directly | node topology/state,edges,bindings,retirement fields, and possibly `run_state` | — |
| `submit_callback` | callback validator produces `callback_rejected_stale`,`callback_rejected_conflict`, or `callback_duplicate_returned`; accepted callback emits `callback_accepted`, optional `file_state_rejected`, accepted output events and their bindings, optional completion `node_state_changed`,`lease_released`, optional session state, then source-repair families | payload-selected output record models; `FileStateRecord`/`VerificationReportRecord` produce dedicated acceptance/outcome events as applicable | callback idempotency,records,bindings,node/lease/session,verification/check/file-state fields | no direct graph outbox |
| `submit_patch` | only known/non-`None` non-active `run_state` → CR; unset `None` passes this guard. Malformed macro/patch → CR; validator/budget/request/extra-successor failure → `graph_patch_rejected` (budget also `node_created(gate)`,`node_state_changed(ready)`); accepted → `graph_patch_accepted`, each op’s node/edge/retire/revision/appeal/gate/authority events, optional carryover `input_bound`, source repair | no command-created typed record; references rationale/carryover | patches,nodes,edges,bindings,authority/sessions | — |
| `acknowledge_start` | unknown/nonactive/incompatible lease/generation/execution → CR; else `node_state_changed(running)` whose payload may carry `prompt_summary` | — | `node_states`; no `attempt_number` is emitted, so `node_attempts` is unchanged; `prompt_summary` is event-payload evidence only, not a `GraphProjection` reducer target | — |
| `agent_died` | unknown/inactive/missing-or-mismatched execution → CR; accepted-patch planner → `agent_died`,`lease_revoked`,`node_state_changed(completed)`; rate-limit/nonretryable/max-attempts → those first two plus `output_record_accepted(FailureRecord)`,`node_state_changed(failed)`; retry → first two plus `runtime_retry_scheduled`,`output_record_accepted(RecoveryPlanRecord)`,`node_state_changed(ready|blocked)` | `FailureRecord` or `RecoveryPlanRecord` | leases,node state/retry timing,output records | — |
| `raise_appeal` | strict payload only; else `appeal_opened`,`node_created(oversight)` | — | pending appeals,node topology | — |
| `record_decision` | unknown target; target state exactly `completed|failed|cancelled|retired`; run state exactly `cancelled|failed`; or wrong authority/approval target → CR. Known completed run is not rejected by this run-state guard. Accepted decision event is approval/authority/oversight. Rejected approval adds `node_state_changed(failed)` and release events; otherwise valid gate/authority record adds `output_record_accepted` + bindings then `node_state_changed(completed)` + release. A decision-record construction failure returns CR after decision event was already assembled. | `DecisionRecord` or `AuthorityDecisionRecord` (oversight has no output record) | decision maps/gates,records/bindings,node/lease state | — |
| `record_gatekeeper_verdicts` | unknown file state, duplicate path, or path not unresolved residue → CR. Success always emits one `gatekeeper_verdict_recorded` containing the whole accepted list and always `gatekeeper_cost_recorded`; any accepted `secret` additionally emits `cleanup_requested`. | gatekeeper payload rows; no `TypedRecordBase` output | reducer rewrites matching entries in `file_state_records[record_id].classifications/residue/untracked/ignored/external`; secret cleanup additionally populates `cleanup_requested_events` and marks the file-state record compromised/pending | `cleanup_requested` maps to associated durable `snapshot_cleanup` outbox row; neither outbox row nor cost event is a `GraphProjection` field |
| `record_node_usage` | strict nonempty usage; duplicates are skipped, not rejected; each new entry emits `node_usage_recorded` | immutable `NodeUsageRecordedPayload` facts | usage keys,tokens/latency/actions by node/kind | durable store also updates run usage read model |
| `record_requirement_revision` | strict payload only; emits `requirement_revision_recorded` | revision payload, not `RequirementRecord` output | requirement revisions,active version/authority blockers | — |
| `record_support_evidence` | no supplied/active requirement version → CR; else `support_evidence_recorded` | support payload, not output record | support evidence/freshness/final blockers | — |
| `evaluate_join` | wrong node kind or no bound records → CR; else `output_record_accepted(JoinResultRecord)`,`node_state_changed(completed)`, optional scoped `lease_released` | `JoinResultRecord` | output records,node state,leases | executor invokes after dispatch |
| `evaluate_final_gate` | wrong node kind → CR; else `output_record_accepted(CompletionDecisionRecord)` with passed/blocked blockers,`node_state_changed(completed)`, optional scoped release | `CompletionDecisionRecord` | output records,completion/node/lease fields | executor invokes after dispatch |
| `record_cleanup_applied` | absent/already-applied cleanup, unknown/mismatched target snapshot, wrong supersession/cleanup IDs, same snapshot, or retained secret path → CR; else `cleanup_applied`,`output_record_accepted`,`file_state_accepted` | strict command `StrictFileStateRecord`, emitted canonical `FileStateRecord` | file-state lineage,`cleanup_applied_ids`,cleanup request state,records | completes previously dispatched `snapshot_cleanup`; this command itself adds no new outbox intent |

## Important uncertainties

- **[unclear] Region semantics/cardinality.** `task_region_id` is a string
  carried by nodes/records; no graph model establishes a first-class Region,
  its ownership, or exact region-to-node/task cardinalities. Horizon purposes
  are templates, not a durable Region aggregate.
- **[unclear] Workflow equivalence.** Graph run/node states, graph positions,
  graph leases, candidates, and records do not prove equivalence to core
  workflow run/task/attempt/checklist/requirement identities. `attempt_number`
  is present in graph payloads but is not evidence of a typed core attempt join.
- **[inferred] Causality limit.** Causation/correlation IDs and event sequence
  can support trace navigation; they do not by themselves prove that an earlier
  output caused a later business outcome. Only explicit mechanisms such as an
  input binding, required-edge readiness check, or command handler justify a
  bounded causal statement.
- **[unclear] Production reachability breadth.** Focused tests exercise kernel
  and integration transactions, but this audit did not independently execute
  every REST/MCP/runner configuration or prove that every registered node kind
  is reachable from every routine compiler path.

## Conflicts found

- **[conflicting] Event authority wording.** `AGENTS.md` describes JSONL-first
  event sourcing, while `GraphController.handle_command` and
  `GraphEventStore.append_events` commit authoritative SQL events/outbox first
  and treat JSONL as retriable secondary output. The executable behavior
  controls this audit; document conflict for synthesis.
- **[conflicting] “Graph patch” is not one semantic thing.** A
  `GraphPatchProposalRecord` is agent output evidence, `SubmitPatchCommand` is
  an attempted command, and accepted topology is represented by patch outcome
  plus node/edge events. Do not collapse proposal, command, and applied change.
- **[documented-only/inferred] “Planner horizon” and “blast radius.”** Templates
  and scheduler/projection facts support bounded topology inspection, but no
  current implementation named in scope computes a canonical planner-horizon
  or blast-radius capability.

## Decisions required

- Define whether `task_region_id` becomes a canonical entity and its typed
  links to graph nodes, core tasks/attempts, and candidate/record lineage.
- Preserve graph node/record/event/lease vocabulary as distinct from workflow
  task/attempt/event terminology unless a conversion contract is evidenced.
- Decide the UI-facing interpretation of temporal event order: show it as
  ordered evidence; require explicit binding/handler evidence before labelling
  causality.
- Reconcile JSONL-first documentation with SQL-authoritative implementation.
- Decide whether outbox exhaustion, callback/patch rejection, and stale-race
  retry visibility need separate operator-facing contracts; present code has
  durable events/errors but this audit did not establish a complete UI action
  contract.

## Artifact paths

- `research/ui-foundation/agent-reports/02-graph-runtime.md`
- `.superpowers/sdd/task-4-audit-report.md`
- Primary evidence: `src/orchestrator/graph/` and
  `src/orchestrator/graph_runtime/`.

## Evidence pointers

- `src/orchestrator/graph/models.py::{NodeKind,NodeState,EdgeModel,OutputRecord,LeaseProjection}`.
- `src/orchestrator/graph/contracts.py::{PortContract,DEFAULT_NODE_CONTRACTS,merge_bound_record_ids,validate_edge_payload}`.
- `src/orchestrator/graph/patch_validator.py::{validate_patch,_validate_staleness,op_read_set}`.
- `src/orchestrator/graph/scheduler.py::{evaluate_readiness,schedule,claims_conflict}`.
- `src/orchestrator/graph/_commands.py::{RUN_LIFECYCLE_TRANSITIONS,_apply_callback_command,_apply_evaluate_final_gate}`.
- `src/orchestrator/graph/event_registry.py::{INTERNAL_EVENT_TYPES_BY_PRODUCER,EVENT_PAYLOAD_MODELS}`.
- `src/orchestrator/graph_runtime/controller.py::GraphController.handle_command`.
- `src/orchestrator/graph_runtime/store.py::{GraphEventStore.append_events,load_projection_with_tail}`.
- `src/orchestrator/graph_runtime/{dispatch.py,outbox.py,recovery.py}` and the
  focused tests listed under Key findings.

## Recommended next delegation

Normalize only evidenced graph relationships: directed typed edge,
node-to-output-record production, edge-to-input-binding selection,
lease-to-node/execution, and graph event-to-projection reduction. Delegate
cross-boundary identity adjudication (region/node/task/attempt and graph/core
event authority) to a joint domain/workflow audit; do not infer it from matching
strings or ordered event positions.

## Command result

`uv run python research/ui-foundation/tools/validate.py --report research/ui-foundation/agent-reports/02-graph-runtime.md`

Result: PASS (exit 0, no stdout/stderr).
