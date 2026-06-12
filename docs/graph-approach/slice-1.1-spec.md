# Slice 1.1 — Graph Models (loop mode, small)

Phase 1 foundation: pure Pydantic models for the execution-graph kernel. No IO,
no DB, no app dependencies — importable standalone. All from PRD ground truth.

## Ground truth

`docs/graph-approach/execution-graph-prd-plus.md` — every JSON example and
every table is authoritative. When in doubt, the PRD wins over intuition.

## Scope

Create `src/orchestrator/graph/` package with `models.py` containing Pydantic
v2 models for all types defined in PRD §6, §10–§12, §16, §19.

### Required models

**§10.1 Run**
- `RunLifecycleState` enum: `draft`, `queued`, `active`, `pausing`, `paused`,
  `resuming`, `cancelling`, `cancelled`, `completed`, `failed`
- `RunModel` — all fields from the PRD JSON example; `lifecycle_state` typed

**§10.2 Node**
- `NodeKind` enum: all 15 kinds from the PRD table (`root`, `task_projection`,
  `worker`, `verifier`, `check`, `planner`, `oversight`, `appeal`, `gate`,
  `recovery`, `review`, `artifact`, `requirement`, `file_state`, `session`,
  `command`)
- `NodeState` enum: `planned`, `blocked`, `ready`, `leased`, `running`,
  `suspended`, `completed`, `failed`, `retired`, `cancelled`
- `ResourceClaim` — `mode` (read/write/graph_write/review_write/external),
  `scope`, optional `paths`, optional `external_resource_key`
- `Authority` — `allowed_actions: list[str]`, `resource_claims: list[ResourceClaim]`
- `PortSpec` — `port`, `required` (for inputs) or `schema` (for outputs)
- `NodeModel` — required fields from PRD example; `kind` typed; `authority` typed;
  `inputs`/`outputs` typed

**§10.3 Membership fields** (for executable nodes)
- `NodeMembership` — `task_region_id`, `attempt_number`, `candidate_id`,
  `execution_id`

**§10.4 Port**
- `PortModel` — `node_id`, `port`, `direction` (input/output), optional `schema`,
  optional `record_layers`

**§10.5 Edge**
- `RecordSelector` — `record_kinds: list[str]`, optional `schema`
- `EdgeModel` — all fields from PRD example; `required: bool`
- `InputBinding` — `edge_id`, `to_node_id`, `to_port`, `record_ids`,
  `bound_at_position`

**§11.1 OutputRecord**
- `OutputRecord` — `record_id`, `record_kind` (literal "output"), `producer_node_id`,
  `port`, `schema`, `value: dict`

**§11.2 FileStateRecord**
- `GitRef` — `commit_sha: str | None`, `tree_sha: str | None`,
  `no_commit_reason: str | None`
- `FileEntry` — `path`, `status`
- `FileStateRecord` — all fields from PRD example; `record_kind` literal "file_state"

**§11.3 GraphRecord** (discriminated union or base + typed subclasses)
- `GraphRecordKind` enum covering all ~18 kinds listed in PRD §11.3
- `GraphRecord` base — `record_id`, `record_kind: GraphRecordKind`, `payload: dict`

**§12.1 Event envelope**
- `ActorKind` enum: `controller`, `agent`, `human`, `system`
- `Actor` — `kind: ActorKind`, optional `node_id`, optional `user_id`
- `EventEnvelope` — `event_id`, `run_id`, `position: int`, `event_type: str`,
  `schema_version: int`, `actor: Actor`, optional `causation_id`,
  optional `correlation_id`, `timestamp: datetime`, `payload: dict`

**§16 Patch envelope**
- `PatchOp` — `op: str`, `**kwargs` (allow extra for op-specific fields)
- `PatchEnvelope` — `patch_id`, `proposed_by_node_id`, `base_graph_position: int`,
  `ops: list[PatchOp]`, optional `rationale_record_id`

**§19 Lease**
- `LeaseState` enum: `active`, `suspended`, `revoked`, `expired`, `released`
- `LeaseModel` — all fields from PRD example; `state: LeaseState`

**§19 Callback envelope**
- `CallbackEnvelope` — `run_id`, `node_id`, `execution_id`, `lease_id`,
  `lease_generation: int`, `base_snapshot_id`, `observed_graph_position: int`,
  `idempotency_key: str`, optional `payload: dict`

### Module structure

```
src/orchestrator/graph/
    __init__.py        # re-export all public models
    models.py          # all models above
```

### Tests

`tests/unit/test_graph_models.py` — one test per PRD JSON example, each doing:
1. Parse the PRD example dict into the model (`Model.model_validate(example)`)
2. Serialize back to dict (`model.model_dump()`)
3. Re-parse the serialized form
4. Assert the re-parsed model equals the first parse (round-trip)

Required round-trip tests (one per PRD example):
- `test_run_model_round_trip`
- `test_node_model_round_trip`
- `test_node_membership_round_trip`
- `test_port_model_round_trip`
- `test_edge_model_round_trip`
- `test_input_binding_round_trip`
- `test_output_record_round_trip`
- `test_file_state_record_round_trip`
- `test_event_envelope_round_trip`
- `test_patch_envelope_round_trip`
- `test_lease_model_round_trip`
- `test_callback_envelope_round_trip`

Also add `test_node_kind_enum_complete` — assert every kind from the PRD table
is in `NodeKind`; and `test_run_lifecycle_state_complete` — all 10 states present.

## Done when

All 14 tests pass. `from orchestrator.graph.models import RunModel` works.
No app imports — `orchestrator.graph` must be importable without starting the server.

## Standards

- Pydantic v2 (`from pydantic import BaseModel`). Use `model_validate` and
  `model_dump`. Use `Literal` for discriminated fields where helpful.
- `datetime` fields: use `datetime` with `timezone` aware type. Accept ISO strings
  (Pydantic v2 does this by default).
- NO mocks, NO monkeypatching. Tests are pure data — no real IO, no tmp repos.
- Regular commits on branch; run `uv run pytest tests/unit/test_graph_models.py -v`
  before each commit.
- No imports from `orchestrator.db`, `orchestrator.api`, `orchestrator.runners`,
  or `orchestrator.workflow`. Pure data models only.
