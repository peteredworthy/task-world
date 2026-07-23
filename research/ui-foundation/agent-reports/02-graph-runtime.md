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
- **[implemented, tested] Stale patches and callback races.** A patch may name
  an older base position only when intervening invalidating events do not touch
  its op-derived read set (`patch_validator.py::_validate_staleness`);
  rejection includes `read_set_diff` and conflicting event IDs. Independently,
  `GraphController.handle_command` enforces expected stream position before
  planning and inside `BEGIN IMMEDIATE`; `GraphEventStore.append_events` plus
  unique `(aggregate_id, version)` is the final backstop. Dispatch retries
  stale/SQLite-lock command races up to five times
  (`graph_runtime/dispatch.py::_handle_command_retry_stale`). Callback
  validation rejects stale lease/generation/snapshot/position and conflicting
  idempotency payloads; duplicate same-key callbacks return prior result rather
  than reapply (`graph/callbacks.py::validate_callback`,
  `graph/_commands.py::_apply_callback_command`).
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
