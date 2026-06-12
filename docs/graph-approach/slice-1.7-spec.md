# Slice 1.7 — Patch Validator (routine, medium)

Phase 1 slice: implement `validate_patch` — a pure deterministic function that applies
§16 patch validation rules with semantic staleness detection per evaluation §6.2.
Per-op read-sets. Invalidating vs neutral event classification. Structured rejection
deltas.

Done when: "stale by N neutral events → accept" and "stale by requirement amendment →
reject with delta" fixtures pass; authority-escalation patches are rejected.

## Ground truth

- `docs/graph-approach/execution-graph-prd-plus.md` §16 — Graph Patch Model (8 rules)
- `docs/graph-approach/execution-graph-evaluation.md` §6.2 — Semantic patch revalidation

## Scope

### 1. Create `src/orchestrator/graph/patch_validator.py`

#### Data structures

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class PatchValidationResult:
    accepted: bool
    rejection_reason: str | None = None          # None when accepted
    conflicting_events: list[EventEnvelope] = field(default_factory=list)
    read_set_diff: dict[str, Any] | None = None  # for structured rejection
```

#### Event classification

```python
def classify_event(event: EventEnvelope) -> str:
    """Return 'invalidating' or 'neutral' for use in revalidation."""
```

Invalidating events (PRD §16 + evaluation §6.2):
- `node_state_changed` with `new_state` in (`retired`, `cancelled`) — node gone
- `requirement_amended` — requirement changed
- `authority_narrowed` — authority reduced
- `candidate_superseded` — candidate replaced
- `region_marked_suspect` — region suspect
- `graph_patch_accepted` — another patch changed the graph
- `run_lifecycle_changed` with `to_state` in (`cancelling`, `cancelled`, `failed`) — terminal

Neutral events (never reject a patch):
- `lease_granted`, `lease_renewed`, `lease_suspended`, `lease_expired`, `lease_released`
- `cost_record_appended`, `log_record_appended`
- `heartbeat_recorded`
- `callback_rejected_stale`, `callback_duplicate_returned`
- `node_state_changed` with `new_state` NOT in terminal states (progress events)
- `run_lifecycle_changed` with `to_state` NOT in terminal states
- All other unrecognised events → `neutral` (safe default)

#### Per-op read-sets

```python
def op_read_set(op: dict[str, Any]) -> set[str]:
    """Derive the set of node_ids and record_ids this op depends on."""
```

For each v1 operation:
- `create_node` — no dependencies (pure append)
- `create_edge` — depends on `from_node_id`, `to_node_id`
- `retire_node` — depends on `node_id`
- `create_revision_attempt` — depends on `task_region_id`, `failed_candidate_id`
- `create_appeal` — depends on `appealed_node_id`
- `create_gate` — depends on referenced `predecessor_node_ids`
- `set_resource_claims` — depends on `node_id`
- `set_allowed_actions` — depends on `node_id`
- `mark_plan_region_suspect` — depends on `region_node_ids`

Returns a `set[str]` of IDs the op reads.

#### `validate_patch`

```python
def validate_patch(
    patch: PatchEnvelope,          # from models.py
    current_position: int,         # current event log position
    events_since_base: list[EventEnvelope],  # events with position > patch.base_graph_position
    projection: GraphProjection,
    actor_role: str,               # "planner" | "oversight" | "human" | "controller"
) -> PatchValidationResult:
```

Apply §16 rules in order:

**Rule 1 — Staleness with semantic revalidation (§6.2)**:
- If `patch.base_graph_position == current_position`: no staleness → skip rule 1
- Otherwise: compute `patch_read_set = union of op_read_set(op) for op in patch.ops`
  - For each event in `events_since_base`: call `classify_event`
  - Collect `invalidating_events` = those where event touches `patch_read_set`:
    - An event "touches" the read set if `event.payload.get("node_id") in patch_read_set`
      OR `event.payload.get("record_id") in patch_read_set`
      OR `event.payload.get("region_node_ids")` has overlap with `patch_read_set`
  - If `invalidating_events` is non-empty: return `PatchValidationResult(accepted=False,
    rejection_reason="stale: invalidating events in read-set",
    conflicting_events=invalidating_events,
    read_set_diff={"read_set": list(patch_read_set), "invalidating": [e.event_id for e in invalidating_events]})`
  - If only neutral events → patch is NOT stale → accept (proceed to other rules)

**Rule 2 — Actor authority**:
- `planner` may: `create_node`, `create_edge`, `retire_node`, `create_revision_attempt`,
  `create_appeal`, `mark_plan_region_suspect`, `set_resource_claims`, `set_allowed_actions`
- `oversight`/`human` may: all of the above plus `create_gate`
- `controller` may: all operations
- Unknown op for actor role → reject with `"authority: actor {role} cannot perform {op}"`

**Rule 3 — Authority escalation**:
- `set_resource_claims`: new claims must not be BROADER than existing claims
  (check that `mode` is not escalated: read→write→graph_write→review_write is escalation)
- `set_allowed_actions`: new actions must not exceed existing allowed actions
- If escalation detected: reject with `"authority_escalation: {op}"`

**Rule 4 — No retire-running-node**:
- `retire_node`: if `projection.node_states.get(op["node_id"])` in (`running`, `leased`) →
  reject with `"cannot retire running node"`

**Rule 5 — Executable node requirements**:
- `create_node` with `kind` in (`worker`, `verifier`, `check`, `planner`): must have
  `role` field in op → reject with `"executable node missing role"` otherwise

**All rules pass → `PatchValidationResult(accepted=True)`**

### 2. `tests/unit/test_patch_validator.py` — 14 tests, no mocks

**Staleness tests** (4):
- `test_patch_at_current_position_accepted` — base == current → no staleness check
- `test_patch_stale_neutral_events_only_accepted` — stale by 5 positions with only lease/cost events → accepted
- `test_patch_stale_invalidating_event_in_read_set_rejected` — stale + requirement_amended for a node in read-set → rejected with delta
- `test_patch_stale_invalidating_event_not_in_read_set_accepted` — invalidating event touches a different node → accepted (§6.2: read-set is per-op)

**Authority tests** (4):
- `test_planner_can_create_node` — planner + create_node → accepted
- `test_planner_cannot_create_gate` — planner + create_gate → rejected
- `test_oversight_can_create_gate` — oversight + create_gate → accepted
- `test_unknown_op_rejected` — unknown operation type → rejected

**Authority escalation tests** (2):
- `test_set_resource_claims_escalation_rejected` — planner tries to widen claims from read to write → rejected
- `test_set_resource_claims_narrowing_accepted` — planner narrows claims → accepted

**Node state tests** (2):
- `test_retire_running_node_rejected` — node in running state → rejected
- `test_retire_planned_node_accepted` — node in planned state → accepted

**Executable node test** (1):
- `test_create_worker_without_role_rejected` — create_node kind=worker, no role field → rejected

**Combined test** (1):
- `test_multi_op_patch_one_fails_rejected` — patch with 2 ops where one fails authority → whole patch rejected

**Total: 14 tests.**

### 3. Export from `src/orchestrator/graph/__init__.py`

```python
from orchestrator.graph.patch_validator import (
    PatchValidationResult,
    classify_event,
    op_read_set,
    validate_patch,
)
```

### 4. Add patch validator fixtures to `tests/fixtures/graph/patch_validator.yaml`

6 scenarios — each exercises one PRD table row or evaluation §6.2 requirement:
- `patch_stale_neutral_only` — given neutral events since base; then_events: `graph_patch_accepted`
- `patch_stale_requirement_amended` — given requirement_amended; then_events: `graph_patch_rejected`
- `patch_authority_escalation` — given node; when_command: set_resource_claims escalation; then_events: `graph_patch_rejected`
- `patch_retire_running_node` — given node in running state; then_events: `graph_patch_rejected`
- `patch_create_worker_accepted` — create_node worker with role; then_events: `graph_patch_accepted`
- `patch_oversight_creates_gate` — oversight actor; create_gate op; then_events: `graph_patch_accepted`

Note: these fixtures test the event replay path (the harness only checks `then_events` and
`then_projection` — not `validate_patch` directly). The actual validator logic is tested in
`test_patch_validator.py`. The fixtures ensure the graph events produced by accepted/rejected
patches are visible in projection.

Update COVERAGE.md with 6 new rows under `§16 patch model`.

## Implementation notes

- `PatchEnvelope` is already in `models.py` — import from there.
- `GraphProjection` is in `projections.py`.
- For the read-set "touches" check, use a simple payload key scan — no deep traversal needed.
- The authority table is a hardcoded dict `{role: set[allowed_ops]}` — no DB.
- For resource claim escalation: define mode ordering `read < write < graph_write < review_write`;
  escalation = requested mode has higher rank than existing mode.
- No globbing, no path expansion in rule 3 — compare mode strings only.

## Done when

- `tests/unit/test_patch_validator.py` — all 14 tests pass.
- `tests/unit/test_fixture_corpus.py` — all 4 tests still pass (patch_validator.yaml included).
- `uv run pyright src/orchestrator/graph/` — no errors.
- No forbidden imports.
- "stale by N neutral → accept" and "stale by requirement_amended → reject with delta" cases pass.
