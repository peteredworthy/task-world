# Immutable Entity-Store Graph Projection - Design

## Objective

Replace the current 73-field `GraphProjection` `TypedDict` with a deeply immutable,
entity-grouped Pydantic projection that preserves replay performance, removes duplicated
payload ownership, validates runtime state, and can be migrated reliably by LLM agents.

The event stream remains canonical. Projection checkpoints are disposable caches. Old or
invalid checkpoints are rejected and rebuilt from events rather than migrated or salvaged.

## Problem

The current projection combines topology, scheduling, records, planning, verification,
governance, cleanup, and usage in one flat structure. Node facts are spread across many maps
keyed by `node_id`, while `node_creation_payloads` retains many of the same facts. Accepted
record payloads are indexed in several places. A field can require coordinated edits to the
`TypedDict`, defaults, clone logic, checkpoint conversion, checkpoint restoration, reducer,
schema version, and tests.

Structural sharing removed expensive deep copies, but shared Pydantic leaves still contain
mutable lists and dictionaries. Pydantic `frozen=True` blocks attribute replacement but not
nested mutation. A reducer or caller can therefore mutate an older projection generation
through a shared child.

The projection is also exported as a zero-runtime-validation `TypedDict`. Normal production
paths generally contain typed Pydantic leaves, but defensive dict-or-model normalizers and
silent checkpoint filtering are necessary because the root cannot enforce that contract.

## Design Constraints

- The event stream is the source of truth. Projection snapshots require no backward
  compatibility.
- Replay must not return to deep-copying accumulated projection state.
- Every object reachable from a published projection must be deeply immutable.
- Public JSON remains ordinary objects and arrays.
- Pydantic validates all persisted and external data boundaries.
- Event and transport models are not stored directly unless their complete reachable value
  graph satisfies the projection immutability contract.
- Projection models remain passive data. Reducers and query functions contain behavior.
- Consumers must not depend on the immutable collection library or physical storage layout.
- Each broad production call site should be transformed once by deterministic automation.
- Migration completeness must be proved by inventories, static checks, and tests rather than
  manual review of a large diff.
- Production must never dual-write old and new projection representations.
- Direct graph projection access is an internal Python API, not a compatibility contract for
  external consumers. REST, MCP, CLI, and serialized read models remain stable contracts.

## Target Architecture

The projection becomes a frozen Pydantic root composed of frozen domain stores:

```python
class GraphProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lifecycle: LifecycleProjection = Field(default_factory=LifecycleProjection)
    nodes: FrozenMap[str, NodeProjection] = Field(default_factory=empty_frozen_map)
    tasks: FrozenMap[str, TaskProjection] = Field(default_factory=empty_frozen_map)
    topology: TopologyProjection = Field(default_factory=TopologyProjection)
    records: RecordStore = Field(default_factory=RecordStore)
    scheduling: SchedulingProjection = Field(default_factory=SchedulingProjection)
    planning: PlanningProjection = Field(default_factory=PlanningProjection)
    verification: VerificationProjection = Field(default_factory=VerificationProjection)
    governance: GovernanceProjection = Field(default_factory=GovernanceProjection)
    requirements: RequirementsProjection = Field(default_factory=RequirementsProjection)
    execution: ExecutionProjection = Field(default_factory=ExecutionProjection)
    usage: UsageProjection = Field(default_factory=UsageProjection)
```

The exact ownership of every current field is declared in a machine-validated migration
manifest generated from the normative ownership table in this design. The model above defines
the architectural groups; the table and generated manifest are the exhaustive source of truth
during migration. The completed generated manifest must receive design review before any query
codemod or destination model is written.

### Entity Stores

`nodes`, `tasks`, topology edges, records, leases, planner sessions, and requirements are
canonical projected entities. Secondary indexes store identifiers, not duplicate payloads.

This is not a pure two-map nodes-and-edges model. Records, leases, tasks, planner sessions,
requirements, and decisions have independent identities and lifecycles. Forcing them into
node metadata would create oversized, high-churn node values and obscure ownership.

### Node Projection

Node declaration, runtime state, and scheduling annotations have separate immutable values:

```python
class NodeProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: NodeSpecProjection
    runtime: NodeRuntimeProjection = Field(default_factory=NodeRuntimeProjection)
    scheduling: NodeSchedulingProjection = Field(default_factory=NodeSchedulingProjection)
```

`NodeSpecProjection` owns stable facts such as ID, kind, role, task region, resource claims,
allowed actions, preconditions, and command definition. `NodeRuntimeProjection` owns state,
attempt and candidate IDs, and failure or suspect state. `NodeSchedulingProjection` owns
retry, deferral, and related scheduler annotations.

The complete `NodeCreationProjection` event payload is validated at the event boundary and
then projected into this canonical node value. It is not retained as a second copy of the
same node facts.

Node IDs identify one logical node. For repeated `node_created` events, creation position and
stable declaration facts are first-write-wins. A later declaration with the same non-null fact
is idempotent; a conflicting non-null declaration fails replay. A later declaration may fill a
previously absent optional declaration fact. Runtime fields are initialized only when absent
and are subsequently owned by their dedicated state-change events. `max_attempts` remains the
first non-null configured value. Characterization fixtures must cover every repeated-creation
case before cutover.

Usage totals do not belong on the node entity. They remain in `UsageProjection` because they
are independently aggregated telemetry.

### Topology Projection

Topology owns canonical edges, input bindings, and adjacency or port indexes justified by hot
queries:

```python
class TopologyProjection(GraphBaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    edges: FrozenMap[str, EdgeProjection] = Field(default_factory=empty_frozen_map)
    input_bindings: FrozenMap[str, FrozenMap[str, InputBindingProjection]] = Field(
        default_factory=empty_frozen_map
    )
    inbound_edge_ids: FrozenMap[str, tuple[str, ...]] = Field(
        default_factory=empty_frozen_map
    )
    outbound_edge_ids: FrozenMap[str, tuple[str, ...]] = Field(
        default_factory=empty_frozen_map
    )
```

Bindings remain separate from edges unless cardinality and destination-port lookup semantics
prove that one binding can be owned by one edge without another index. The migration must not
change those semantics merely to make the object shape look graph-like.

Nested string-keyed maps represent `node_id -> port -> binding`. Projection checkpoint maps do
not use tuple, object, or delimiter-composed keys because JSON object keys must be strings and
node or port IDs may contain any allowed identifier character.

### Record Store

Full accepted record payloads have one canonical home:

```python
class RecordStore(GraphBaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    by_id: FrozenMap[str, ProjectedRecord] = Field(
        default_factory=empty_frozen_map
    )
    ids_by_node_port: FrozenMap[str, FrozenMap[str, tuple[str, ...]]] = Field(
        default_factory=empty_frozen_map
    )
    summaries_by_id: FrozenMap[str, GraphRecordSummary] = Field(
        default_factory=empty_frozen_map
    )
```

`ProjectedRecord` is a discriminated union of projection-specific frozen record models. Every
list becomes a tuple, every map becomes `FrozenMap`, every nested Pydantic model is frozen, and
every flexible JSON field uses `FrozenJsonValue`. Existing event record models are converted at
the reducer boundary rather than stored by reference until their full reachable type graph has
the same guarantees.

Indexes contain record IDs only. Compact `summaries_by_id` remains a deliberate materialized
secondary index because topology and evidence views repeatedly consume it; referential and
derivation tests tie it to `by_id`. Checkpoints must never serialize the same full payload under
multiple indexes.

Record IDs globally identify immutable record payloads. Re-accepting an identical record is
idempotent and does not append a duplicate index entry. Reusing an ID for a different payload
fails replay. This rule prevents an ID-only historical index from resolving an earlier entry to
a later conflicting payload.

### Secondary Indexes

An index is stored only when a measured or clearly hot query requires it. Each index has one
canonical entity store, a documented derivation, and a referential-integrity test. Public
views may derive additional dictionaries and lists without storing them in the projection.

### Normative Field Ownership

The generated migration manifest must reproduce this ownership table exactly before adding
type, default, merge, ordering, and access-occurrence details:

| Current field | Final owner | Disposition |
|---|---|---|
| `run_state` | `lifecycle.run_state` | Canonical |
| `node_states` | `nodes.*.runtime.state` | Canonical entity field |
| `task_states` | `tasks.*.state` | Canonical entity field |
| `leases` | `execution.leases` | Canonical entity store |
| `ready_nodes` | `scheduling.ready_node_ids` | Derived ordered index |
| `node_kinds` | `nodes.*.spec.kind` | Canonical entity field |
| `node_roles` | `nodes.*.spec.role` | Canonical entity field |
| `node_creation_positions` | `nodes.*.spec.creation_position` | Canonical entity field |
| `node_task_regions` | `nodes.*.spec.task_region_id` | Canonical entity field |
| `node_attempts` | `nodes.*.runtime.attempt_number` | Canonical entity field |
| `node_candidates` | `nodes.*.runtime.candidate_id` | Canonical entity field |
| `node_failed_candidates` | `nodes.*.runtime.failed_candidate_id` | Canonical entity field |
| `node_resource_claims` | `nodes.*.spec.resource_claims` | Canonical entity field |
| `node_allowed_actions` | `nodes.*.spec.allowed_actions` | Canonical entity field |
| `node_preconditions` | `nodes.*.spec.preconditions` | Canonical entity field |
| `node_command_definitions` | `nodes.*.spec.command_definition` | Canonical entity field |
| `node_output_ports` | `records.ids_by_node_port` | Secondary ID index |
| `accepted_output_records_by_node_port` | `records.ids_by_node_port` | Remove duplicate payload wrapper |
| `accepted_record_summaries_by_id` | `records.summaries_by_id` | Materialized secondary index |
| `output_records_by_node_port` | `records.ids_by_node_port` | Remove duplicate payload index |
| `edges` | `topology.edges` | Canonical entity store |
| `input_bindings` | `topology.input_bindings` | Canonical entity store |
| `node_pending_appeals` | `governance.pending_appeals_by_node` | Canonical decision state |
| `node_gate_decisions` | `governance.node_gate_decisions` | Canonical decision state |
| `task_candidates` | `tasks.*.candidates` | Canonical entity field |
| `verifier_verdicts` | `verification.verdicts_by_node` | Canonical entity store |
| `completion_decision_passed` | `lifecycle.completion_decision_passed` | Canonical |
| `passed_verification_results_by_record_id` | `verification.passed_results_by_record_id` | Canonical entity store |
| `failed_verification_results_by_record_id` | `verification.failed_results_by_record_id` | Canonical entity store |
| `passed_verification_candidate_ids` | `verification.passed_candidate_ids` | Derived ordered index |
| `failed_verification_candidate_ids` | `verification.failed_candidate_ids` | Derived set index |
| `recovery_nodes_by_record_id` | `verification.recovery_nodes_by_record_id` | Secondary ID index |
| `check_results` | `verification.check_results_by_node` | Canonical entity store |
| `invalid_test_blocks` | `verification.invalid_test_blocks_by_task` | Canonical entity store |
| `configured_gates` | `governance.configured_gates_by_task` | Secondary ID index |
| `gate_decisions` | `governance.gate_decisions_by_task` | Canonical decision state |
| `environment_failures` | `execution.environment_failures_by_task` | Canonical entity store |
| `file_state_records` | `records.by_id` | Canonical projected file-state record |
| `planner_generation_budget` | `planning.generation_budget` | Canonical |
| `planner_successors` | `planning.successor_by_node` | Canonical relation |
| `accepted_graph_patches_by_node` | `planning.accepted_patch_ids_by_node` | Secondary ordered ID index |
| `accepted_no_successor_patches_by_node` | `planning.no_successor_patch_ids_by_node` | Secondary ordered ID index |
| `accepted_no_successor_patch_ids_by_node` | `planning.latest_no_successor_patch_id_by_node` | Derived latest-value index |
| `latest_routine_snapshot_record` | `planning.latest_routine_snapshot` | Canonical entity |
| `planner_generations` | `planning.generation_by_node` | Canonical planner state |
| `planner_sessions` | `planning.session_id_by_node` | Canonical relation |
| `planner_session_states` | `planning.sessions.*.state` | Canonical entity field |
| `planner_session_current_nodes` | `planning.sessions.*.current_node_id` | Canonical entity field |
| `planner_session_carryovers` | `planning.sessions.*.carryover_record_id` | Canonical entity field |
| `planner_region_labels` | `planning.region_label_by_node` | Canonical planner state |
| `requirement_revisions` | `requirements.revisions_by_id` | Canonical entity store |
| `active_requirement_versions` | `requirements.active_version_id_by_requirement` | Secondary ID index |
| `support_evidence` | `requirements.support_by_id` | Canonical entity store |
| `last_deferred_reasons` | `nodes.*.scheduling.last_deferred_reason` | Canonical entity field |
| `retry_not_before_by_node` | `nodes.*.scheduling.retry_not_before` | Canonical entity field |
| `node_creation_payloads` | `nodes` | Remove duplicate payload after projection |
| `output_record_payloads` | `records.by_id` | Canonical entity store |
| `approval_decisions` | `governance.approval_decisions_by_node` | Canonical entity store |
| `authority_decisions` | `governance.authority_decisions_by_node` | Canonical entity store |
| `oversight_decisions` | `governance.oversight_decisions_by_node` | Canonical entity store |
| `decision_request_details` | `governance.decision_requests_by_node` | Canonical entity store |
| `callback_idempotency_events` | `execution.callback_events_by_key` | Canonical entity store |
| `open_proposal_blockers` | None | Remove dormant checkpoint-only state with no event producer |
| `suspect_node_reasons` | `nodes.*.runtime.suspect_reason` | Canonical entity field |
| `authority_revision_blockers` | `governance.authority_revision_blockers` | Canonical entity store |
| `cleanup_requested_events` | `execution.cleanup_requests_by_id` | Canonical entity store |
| `cleanup_applied_ids` | `execution.applied_cleanup_ids` | Derived set index |
| `tokens_by_node` | `usage.tokens_by_node` | Canonical aggregate |
| `tokens_by_node_kind` | `usage.tokens_by_node_kind` | Canonical aggregate |
| `latency_ms_by_node_kind` | `usage.latency_ms_by_node_kind` | Canonical aggregate |
| `execution_count_by_node_kind` | `usage.execution_count_by_node_kind` | Canonical aggregate |
| `num_actions_by_node_kind` | `usage.action_count_by_node_kind` | Canonical aggregate |
| `recorded_node_usage_keys` | `usage.recorded_keys` | Idempotency set index |

## Immutable Collections

Use `immutables.Map` for persistent maps and built-in tuples for ordered sequences. Hide the
dependency behind a graph-owned generic `FrozenMap[K, V]` type and update functions.

Add `immutables>=0.21,<1` as a direct production dependency with `uv add`; do not rely on a
transitive package or add it only to the development group.

The initial synthetic comparison for 5,000 point updates was:

| Initial map size | Dict spread | `immutables.Map.set` | `pyrsistent.PMap.set` |
|---:|---:|---:|---:|
| 100 | 1.59 ms | 0.89 ms | 4.99 ms |
| 1,000 | 14.36 ms | 1.43 ms | 5.91 ms |
| 10,000 | 166.63 ms | 1.81 ms | 7.04 ms |

`pyrsistent.PVector` was substantially faster than repeated tuple copying in an append-only
microbenchmark. The production design nevertheless starts with tuples because the current
projection is map-dominated and most sequences are expected to be short. A representative
replay benchmark must verify that assumption before the semantic cutover. If long append-heavy
histories dominate, the sequence implementation may change behind the graph-owned boundary
without changing consumers.

`MappingProxyType` is not the primary store. It provides a read-only view rather than
persistent path-copying, and updating a copied dictionary would retain map-size-dependent
copy cost.

`immutables.Map` does not preserve dictionary insertion order. The access inventory classifies
every iteration as order-sensitive or order-insensitive. An order-sensitive query must use a
stored ordered ID tuple justified as an index or sort explicitly in its query function.
Scheduler and command choices must never depend on backend map iteration order. Determinism
tests run the same fixture corpus in separate processes with different hash seeds.

### Pydantic Integration

Third-party persistent maps are not directly JSON serializable by Pydantic. `FrozenMap`
provides one reusable validation and serialization integration that:

- Validates keys and values through their declared Pydantic types.
- Builds a new persistent map from validated input.
- Serializes recursively to ordinary dictionaries.
- Uses persistent empty-map defaults.
- Exposes `Mapping` behavior to readers.
- Keeps backend update methods private to projection internals.

Tuples serialize as JSON arrays. Arbitrary JSON metadata is recursively frozen into
`FrozenMap` and tuple values and recursively thawed for JSON output. Non-JSON custom mutable
objects are rejected rather than shared.

`FrozenJsonValue` accepts only `None`, strict booleans, strict finite integers and floats,
strings, tuples of frozen JSON values, and `FrozenMap[str, FrozenJsonValue]`. Validation accepts
JSON arrays and objects, rejects non-string object keys, detects cycles, and enforces a maximum
nesting depth of 100. Serialization thaws it to ordinary JSON arrays and objects. Every
projection-reachable field currently annotated as `Any`, `dict`, or `list` must either use this
type or a stricter frozen model.

All nested Pydantic models reachable from the root use `ConfigDict(frozen=True)`. Deep
immutability is established by both frozen models and immutable child containers.

## Query Boundary

All non-core consumers use permanent pure query functions rather than storage fields:

```python
node_kind(projection, node_id)
node_state(projection, node_id)
iter_node_states(projection)
record_by_id(projection, record_id)
records_for_node_port(projection, node_id, port)
```

Only these production files may inspect physical grouped stores:

```text
src/orchestrator/graph/projection_models.py
src/orchestrator/graph/projection_collections.py
src/orchestrator/graph/projection_queries.py
src/orchestrator/graph/projection_codec.py
src/orchestrator/graph/projections.py
```

The static check uses this exact allowlist and rejects additions by default. Symbols needed
outside the `graph` module are exported through `orchestrator.graph.__init__`; external modules
must not import graph submodules directly.

This boundary is permanent, not a temporary compatibility facade. It lets the model layout,
indexes, or persistent-map implementation change without another repository-wide consumer
rewrite. It also gives hot queries named locations where indexes can be added or removed.

Public topology, scheduler, API, MCP, and CLI views remain presenter outputs. They continue to
use ordinary JSON-compatible dictionaries and lists.

## Reducer Updates

Reducers are pure functions from one immutable projection and an event to another immutable
projection. They validate event payloads first, construct typed changed entities, update the
relevant persistent stores, and install only already validated immutable values.

Bare `model_copy(update=...)` with raw dictionaries or lists is forbidden because Pydantic v2
does not validate updates. A valid update is conceptually:

```python
new_node = NodeProjection.model_validate(node_data)
new_nodes = map_set(state.nodes, new_node.spec.node_id, new_node)
next_state = replace_projection_group(state, nodes=new_nodes)
```

`replace_projection_group` accepts only typed immutable values. It may use a shallow Pydantic
copy internally because the supplied value has already crossed the validation and freeze
boundary.

A reducer-local transient builder may batch several changes made by one event. It must never
escape the reducer, and `finish()` must return a frozen `GraphProjection`. Published
projections and their groups never expose mutation methods.

The current reducer branch chain remains in place during the representation cutover so
semantic and file-movement changes do not occur together. Handler extraction into domain
modules happens only after parity is established.

## Checkpoint Policy

The checkpoint codec becomes strict and small:

```python
def projection_to_checkpoint(projection: GraphProjection) -> dict[str, Any]:
    return projection.model_dump(mode="json")


def projection_from_checkpoint(raw: object) -> GraphProjection:
    projection = GraphProjection.model_validate(raw)
    validate_projection_integrity(projection)
    return projection
```

The projection models use strict scalar types. The `FrozenMap`, tuple, and `FrozenJsonValue`
validators intentionally accept only canonical JSON dictionaries, arrays, and scalars and
then freeze them. They reject coercions such as numeric strings, booleans as integers,
non-finite numbers, arbitrary mapping implementations, and non-JSON objects.

After structural validation, pure `validate_projection_integrity()` verifies that map keys
match entity IDs, secondary IDs resolve to canonical stores, and required edge endpoints and
cross-group references exist. It raises `ProjectionCheckpointIntegrityError`.

The store applies this policy:

```text
checkpoint version mismatch -> discard checkpoint and replay events
checkpoint validation failure -> discard checkpoint and replay events
```

The snapshot-store boundary catches only Pydantic checkpoint `ValidationError`, checkpoint
codec errors, and `ProjectionCheckpointIntegrityError`. It converts them to an invalid-cache
result, replays the complete event stream, and transactionally rewrites the snapshot. Reducer,
event-validation, and programming errors are not caught by this fallback.

The cutover increments `PROJECTION_SCHEMA_VERSION`. No old-checkpoint migration functions,
field-level salvage parsers, or Alembic migration are added. The existing JSON snapshot row is
rewritten after successful replay.

The version remains an explicit reducer/checkpoint compatibility version. Pydantic schema
validation catches structural incompatibility, but reducer semantic changes can require a
version bump without changing the model schema.

## LLM-Optimized Migration

The branch uses green scaffolding steps followed by one core-only semantic cutover. Broad
consumer edits happen once through LibCST automation.

### Migration Artifacts

Add:

```text
scripts/graph_projection_inventory.py
scripts/check_graph_projection_boundaries.py
scripts/codemods/graph_projection_manifest.yaml
scripts/codemods/migrate_graph_projection_queries.py
tests/fixtures/graph_projection_migration/access_inventory.json
tests/fixtures/graph_projection_migration/public_view_goldens.json
tests/fixtures/graph_projection_migration/replay_goldens.json
```

The YAML manifest is parsed into a strict Pydantic model. Each of the 73 current fields records
its final owner, value type, default, checkpoint policy, access patterns, public output keys,
merge or collision policy, ordering policy, and whether it is canonical, an index, derived, or
removed. It is generated from and checked against the normative ownership appendix in this
design. The migration stops if the two differ.

### Phase 1: Baseline Inventory

Use LibCST metadata to seed values from `GraphProjection` annotations, imports, known function
returns, and enumerated intra-procedural assignment and alias forms. Pyright output supplements
the inventory where static types are required. This is a bounded analysis, not a claim that
LibCST provides sound inter-procedural data flow. Classify literal field reads, `.get`,
membership, iteration, assignment, nested assignment, `setdefault`, append, deletion,
unpacking, casts, fixture construction, and escapes through untyped values.

The baseline records the source revision. Every occurrence receives an ID based on that
revision, repository-relative path, qualified function, normalized expression hash, and its
ordinal among identical expressions in that function. Line and column are report metadata,
not identity. The inventory fails if it finds computed keys, reflection, unsupported aliases,
or escapes through `Any`. Such a site must first be refactored in a green commit into an
enumerated form and the baseline regenerated deliberately.

The manifest must cover the old `GraphProjection` annotation exactly: no missing old fields,
no extra old fields, and exactly one disposition for every old field. Multiple duplicate old
fields may deliberately converge on one canonical destination.

### Phase 2: Characterization Oracles

Generate deterministic golden outputs from current behavior for representative event streams.
Capture public topology, scheduler, node detail, records, planner, verification, governance,
recovery, and API views. Cover full replay, checkpoint plus tail, incremental reduction,
unknown or audit-only events, and all canonical event families.

These fixtures preserve public behavior, not the old projection shape. They may be removed
after the cutover when equivalent permanent assertions exist.

### Phase 3: Access And Fixture Codemod

Create the permanent pure query API and codemod all non-core projection reads to it while the
old representation still runs. Non-core production mutations are moved to approved graph
update functions. Test construction and mutation are converted to typed fixture factories so
tests do not retain dictionary-style projection access. The codemod therefore gives every
classified read, write, construction, mutation, cast, and unpacking occurrence an explicit
transformation or reviewed allowlist disposition. The codemod:

- Uses LibCST data flow rather than matching field-name strings globally.
- Matches only access shapes recorded by the inventory.
- Refuses ambiguous or unclassified transformations.
- Checks expected before and after occurrence counts.
- Preserves comments and formatting.
- Is idempotent.
- Produces no writes until all repository-wide postconditions pass in memory.
- Emits a one-to-one report from every baseline occurrence ID to exactly one transformed or
  allowlisted result.

If a generated transformation is wrong, fix the codemod and regenerate from the pre-cutover
state. Do not patch broad consumer call sites manually.

After this phase, a permanent static check rejects direct projection storage access outside
the approved core modules.

The baseline access inventory and one-to-one transformation report remain checked in through
cutover. A clean rerun from the recorded baseline revision must reproduce the same transformed
tree. Later phases may not regenerate or re-edit non-core consumer call sites.

### Phase 4: Destination Scaffolding

Add the final grouped models, `FrozenMap`, strict checkpoint codec, and immutable update
functions under unused internal names. Unit tests prove validation, deep immutability, JSON
round trips, deterministic output where required, and persistent update behavior before
production switches to them.

The representative replay benchmark compares the selected map and sequence implementation
against the current reducer under the explicit gates below. The cutover is blocked by a gate
failure.

### Phase 5: Core Semantic Cutover

Change only the core projection models, reducer/update helpers, query implementations, and
checkpoint store wiring. Non-core consumers remain untouched because they already use the
query boundary.

The cutover:

- Replaces the `TypedDict` root with the final grouped frozen Pydantic root.
- Projects node creation into one canonical node entity.
- Stores each full accepted record payload once.
- Converts duplicate payload indexes to identifier indexes.
- Replaces clone-before-mutate with persistent updates.
- Switches to strict checkpoint model validation and dumping.
- Increments the projection schema version.
- Deletes `_clone_projection`, old defaults, old checkpoint parsers, dict-or-model copy
  normalizers, and removed field definitions.
- Never writes both projection shapes.

### Phase 6: Reducer Extraction

After all parity and performance gates pass, extract reducer handlers by domain without
changing representation or behavior. A registry covers every canonical event or declares it
as an explicit projection no-op. Handler extraction is a separate refactor so failures can be
attributed to movement rather than the semantic cutover.

## Verification

### Static Completeness

- The migration manifest covers every old field exactly once.
- The access inventory has no unclassified dynamic access or untyped escape.
- Every inventoried occurrence is transformed or explicitly allowed.
- The query codemod is idempotent.
- No removed storage access remains outside historical documentation or golden public keys.
- Only approved core modules inspect grouped stores.
- Every new model field is owned by a reducer, default, codec, or explicit derived rule.
- No mutable `list` or `dict` annotation is reachable from `GraphProjection`.
- No non-frozen Pydantic model is reachable from `GraphProjection`.
- No full record payload exists outside `RecordStore.by_id`.
- Map/entity keys and every secondary reference pass `validate_projection_integrity()`.
- `pyright`, Ruff, and all repository guard scripts pass.

### Behavioral Tests

- Full replay is deterministic.
- Snapshot plus tail equals full replay.
- Incremental reduction equals rebuild.
- For every split position, folding the suffix from the prefix projection equals folding the
  complete stream from the initial projection.
- Every canonical event is handled or explicitly declared projection-neutral.
- Public view and API goldens are unchanged.
- Duplicate-identical and duplicate-conflicting node and record IDs follow their specified
  idempotency and conflict rules.
- Version-old and malformed checkpoints are discarded and rebuilt.
- Malformed canonical events fail loudly during replay.
- Empty and single-event streams behave correctly.

### Immutability Tests

- Root and nested model attribute assignment fails.
- Map assignment, deletion, and update fail.
- Nested sequence mutation is impossible.
- Arbitrary JSON metadata is recursively immutable.
- Reducing an event leaves the input generation unchanged.
- Unchanged groups and leaves are identity-shared where expected.
- Changed entities and groups receive replacement identities.

Property-based tests recursively inspect every reachable projection value and attempt the
relevant mutations. They also generate valid event sequences and compare incremental,
checkpointed, and full replay.

### Referential Integrity

- Every edge endpoint references an existing node where the graph contract requires it.
- Every record index references `records.by_id`.
- Every node, task, lease, planner, and verification index references its canonical entity.
- Removing or replacing an entity updates every owned secondary index in the same reduction.

### Performance Gates

Use the checked-in scenario corpus, a generated edge-heavy corpus, a generated record-heavy
corpus, and event-count distributions obtained through the orchestrator API. Include streams
of 100, 1,000, 10,000, and the maximum observed event count. Run two warmups followed by seven
measured runs on the same recorded hardware and compare medians:

- Full replay wall time and scaling.
- Per-event reduction time.
- Snapshot plus tail latency.
- Peak memory.
- Checkpoint JSON size.
- Checkpoint serialization and restoration time.
- Public view construction time.
- Longest and most frequently appended sequence indexes.

The release gates are:

- Full replay median is no more than 1.15 times the current baseline at every corpus size.
- Doubling a generated stream increases replay time by no more than 2.5 times once fixed
  startup cost is excluded.
- Peak memory is no more than 1.15 times baseline.
- Checkpoint JSON is no larger than baseline and must shrink for the record-heavy corpus.
- Checkpoint encode, decode, and public-view medians are each no more than 1.25 times baseline.
- Cold rebuild after schema invalidation is no more than 1.15 times current full replay.

A gate change requires an explicit design amendment with measured evidence. A result that
restores quadratic map copying or makes long tuple histories dominate replay blocks release.

## Error Handling

- Invalid event payloads remain domain errors and fail replay.
- Invalid current-version checkpoints are cache failures and trigger full replay.
- Failure to rebuild from canonical events is surfaced; it is not hidden by partial state.
- An unsupported codemod pattern aborts without writing files.
- An inventory count mismatch aborts migration automation.
- A static or behavioral gate failure is fixed in the model, reducer, query abstraction, or
  codemod and then regenerated. Broad generated call sites are not repaired ad hoc.

## Operational Considerations

The schema bump invalidates existing projection snapshots. Rebuilding may temporarily increase
replay load. Benchmark actual long streams before deployment. Add a bounded prewarm operation
only if measured deployment data shows that lazy rebuilding would be unsafe; do not add one by
default.

Rollback does not convert projection data. Both versions retain the same event stream and
reject checkpoint versions they do not understand, then rebuild their own cache format.

## Non-Goals

- Changing canonical event schemas.
- Preserving old projection checkpoint bytes or partial malformed snapshots.
- Preserving direct dictionary-style Python access to `GraphProjection`.
- Replacing public API response shapes.
- Introducing a general graph database.
- Folding every record, lease, task, or decision into node metadata.
- Splitting the reducer during the representation cutover.
- Retaining migration-only compatibility or dual-write code.

## Documentation Updates

The implementation updates `docs/ARCHITECTURE.md`, `AGENTS.md`, and the dynamic graph map
inventory for the new projection modules, query boundary, checkpoint policy, and immutable
collection invariant. The public graph module `__init__.py` exports every symbol used outside
the module.

## Acceptance Criteria

The design is complete when:

1. `GraphProjection` is a frozen grouped Pydantic model with no reachable mutable child.
2. Canonical node facts and full record payloads each have one owner.
3. Persistent map updates replace `_clone_projection` without replay regression.
4. Checkpoints use strict Pydantic validation and JSON dumping; old or invalid versions replay.
5. Non-core consumers use the permanent pure query API.
6. A LibCST inventory and codemod account for every old projection access.
7. Static checks prevent old storage access and future mutable projection fields.
8. Public views and APIs match characterization oracles.
9. Incremental, checkpointed, and full replay agree under scenario and property tests.
10. Performance and checkpoint-size gates pass on representative large streams.
11. Duplicate node and record IDs have tested idempotency and conflict behavior.
12. Current-version checkpoints pass strict shape and referential-integrity validation.
