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
  `TypedRecordBase` output/evidence types are `OutputRecord` (generic
  `fan_out_inputs`), `RunContextRecord`, `RoutineSnapshotRecord`,
  `ArtifactReferenceRecord`, `VerificationReportRecord`,
  `CompletionDecisionRecord`, `JoinResultRecord`, `CheckResultRecord`,
  `CandidateRecord`, `GapClassificationRecord`, `DecisionRecord`,
  `AuthorityDecisionRecord`, `AnalysisSummaryRecord`,
  `GraphPatchProposalRecord`, `RequirementRecord`, `DecisionRequestRecord`,
  `AuthorityRequestRecord`, `FailureRecord`, `RecoveryPlanRecord`, and
  `FileStateRecord` (`graph/models.py`, classes named above). Accepted output
  facts use `output_record_accepted`; accepted/rejected file-state facts use
  their dedicated events. This inventory deliberately excludes payload-only
  projections and event envelope models.
- **[implemented, tested] Relationship/cardinality facts.** Per run, the
  graph stream has `0..N` ordered `EventEnvelope`s and a disposable `0..1`
  current projection checkpoint. A run projection has `0..N` nodes, edges,
  leases, output records, and outbox items. Each edge has exactly one source
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
  **Correction:** callback `observed_graph_position` is required and carried
  from `SubmitCallbackCommand` into `CallbackRequest`/callback event payload,
  but `graph/callbacks.py::validate_callback` does not read or compare it.
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
| `accept_run` | lifecycle must be `draft` | `run_lifecycle_changed` / CR | none | `run_state` | none |
| `start` | lifecycle must be `queued` | `run_lifecycle_changed` / CR | none | `run_state` | enables scheduler only after active |
| `pause` | `active→pausing` or `pausing→paused` | `run_lifecycle_changed` / CR | none | `run_state` | no direct cancellation |
| `resume` | paused/resuming; failed reopen requires human/operator | `run_lifecycle_changed` / CR | none | `run_state` | active re-enables scheduling |
| `cancel` | active/paused/cancelling transition | `run_lifecycle_changed`, then per active/suspended lease `lease_revoked`,`node_state_changed(cancelled)` / CR | none | `run_state`,`leases`,`node_states` | no outbox; dispatch must observe revoke |
| `complete` | active and no final-invariant blockers | optional `output_record_accepted(CompletionDecisionRecord)`, `run_lifecycle_changed` / CR | `CompletionDecisionRecord` | `completion_decision_passed`,`run_state`, output records | none |
| `fail` | nonterminal run only | `run_lifecycle_changed` / CR | none | `run_state` | none |
| `record_heartbeat` | known active lease, active run, matching node/generation | `heartbeat_recorded`,`lease_renewed` / CR | none | lease expiry/state | none |
| `seed_compiled_events` | empty topology; same run; only node/edge/binding/output seed shapes | supplied validated `node_created`/`edge_created`/`input_bound`/`output_record_accepted` / CR | supplied typed verification record where applicable | topology, bindings, records | none |
| `schedule_tick` | active run; readiness/resource/precondition checks; grant cap | `node_ready`/`node_deferred`, `lease_granted` per selected eligible node | none | `ready_nodes`,`last_deferred_reasons`,`leases`,`node_states` | controller appends `agent_dispatch_requested`; durable `agent_dispatch` outbox |
| `reconcile` | kernel recovery conditions | reconciliation state/lease/node events, or none | none | failed/deferred/retry/lease fields as applicable | none directly |
| `submit_callback` | callback payload identity; idempotency; lease/execution/snapshot/generation/run/node state; output provenance/contracts/authority | `callback_accepted`, record acceptance/bindings, optional node state/release/session; or `callback_rejected_stale`/`callback_rejected_conflict`/`callback_duplicate_returned` | callback output records (candidate, verification, check, file state, gap, summary, patch proposal, artifact) | callback idempotency, records, bindings, node/lease/session state | accepted file-state may lead to later gatekeeper command, not direct outbox |
| `submit_patch` | active run, macro/patch shape, role/op/topology/stale/resource/cycle/dynamic/final checks, planner budget/request rules | `graph_patch_accepted` then op events/bindings/repair; or `graph_patch_rejected` (budget additionally creates/ready gate) | no required record; may consume rationale/carryover references | accepted/rejected patches, topology, sessions, nodes/edges/bindings | none |
| `acknowledge_start` | matching active lease/node/generation/execution | `node_state_changed(running)` and session state where relevant / CR | none | `node_states`, planner session state | none |
| `agent_died` | lease/execution and retry policy | `agent_died`, lease revoke/expire/release and node retry/failure/defer events as policy selects | `FailureRecord` where emitted by repair/recovery path | leases,node states,retry/deferred reasons | none |
| `raise_appeal` | strict invalid-test appeal payload | `appeal_opened`, appeal-node creation/state events | appeal/decision request records when patch/runtime path supplies them | pending appeals,nodes | none |
| `record_decision` | decision type/value; target decision node/state | approval/authority/oversight decision event and state updates / CR | `DecisionRecord` or `AuthorityDecisionRecord` projection facts | approval/authority/oversight decisions, gate state | none |
| `record_gatekeeper_verdicts` | file-state record/execution/verdict rows | `gatekeeper_verdict_recorded` per verdict plus `gatekeeper_cost_recorded` if cost | file-state-associated gatekeeper evidence, not `TypedRecordBase` output | file-state/gatekeeper summaries and usage rollups | invoked after accepted boundary; no direct outbox |
| `record_node_usage` | nonempty typed usage; dedupe `execution_id:index` | `node_usage_recorded` per new usage fact | immutable usage payloads, not graph output record | usage keys/tokens/latency/actions by node/kind | store updates run usage read model |
| `record_requirement_revision` | strict IDs/optional revision metadata | `requirement_revision_recorded` | requirement revision projection/evidence, not `RequirementRecord` output | revisions, active requirement versions, authority blockers | none |
| `record_support_evidence` | strict support/evidence/requirement IDs | `support_evidence_recorded` | support evidence projection | support evidence/freshness/final blockers | none |
| `evaluate_join` | node kind `join`; bound source records required; scoped lease pair validated if supplied | `output_record_accepted(JoinResultRecord)`,`node_state_changed(completed)`, optional `lease_released` / CR | `JoinResultRecord` | output records,node state,leases | dispatch executor runs join after lease |
| `evaluate_final_gate` | node kind `final_gate`; scoped lease pair validated if supplied | `output_record_accepted(CompletionDecisionRecord)`,`node_state_changed(completed)`, optional `lease_released` / CR | `CompletionDecisionRecord` | completion decision,node state,leases | dispatch executor runs final gate after lease |
| `record_cleanup_applied` | known pending cleanup; superseding strict file-state record | `cleanup_applied`, accepted superseding file-state/bindings as applicable / CR | `FileStateRecord` | file states, cleanup applied IDs | completes at-least-once `snapshot_cleanup` intent |

The table is a command/kernel mapping, not evidence that every command is a
reachable public UI action. Exact event multiplicity remains data-dependent
(for example, one callback can contain many output records and one scheduling
tick can grant many leases).

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
