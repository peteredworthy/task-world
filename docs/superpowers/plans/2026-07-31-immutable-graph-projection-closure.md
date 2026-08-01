# Immutable Graph Projection Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the immutable `GraphProjection` cutover with executable pure-behavior, replay, immutability, boundary, and direct performance contracts, then remove one-time migration evidence and historical comparison tooling.

**Architecture:** Build one canonical in-memory event-case matrix and reuse it across reducer behavior, replay, generation identity, query isolation, and typed-failure tests. Derive flexible-JSON coverage from the immutable Pydantic model graph, keep checkpoint integrity as the broken-reference boundary, make the permanent source guard independent of migration inventory, and replace historical performance ratios with a direct pure-replay test.

**Tech Stack:** Python 3.12+, Pydantic v2, `immutables.Map` through `FrozenMap`, pytest, ruff, pyright, pre-commit.

## Global Constraints

- Work only in `/Users/peter/code/task-world/worktrees/immutable-graph-projection`; use `uv run` for every Python or pytest command.
- Preserve all existing REST, MCP, CLI, and public `orchestrator.graph` contracts. Do not redesign event schemas or split the reducer into a handler registry.
- Acceptance is pure `events -> reduce_event -> immutable GraphProjection -> queries/checkpoint data`; add no SQL-, HTTP-, startup-, repository-, or database-backed closure test.
- Tests use real Pydantic models, immutable values, and in-memory event tuples. Do not use `patch`, `MagicMock`, monkeypatching, or process-global mutable state.
- Import graph APIs from `orchestrator.graph` outside `src/orchestrator/graph`; code inside the graph package may use direct sibling imports.
- Every model reachable from `GraphProjection` stays frozen. Reducers use `model_copy(update={...})` plus `map_set`, `map_delete`, or `map_update`, never in-place mutation.
- `RecordStore.by_id` remains the sole complete projected-record owner; other groups retain IDs or summaries only.
- Preserve identity for unchanged immutable groups and entities. Replace only changed groups/entities, and never mutate an earlier projection generation.
- Treat broken references as `ProjectionCheckpointIntegrityError` from `validate_projection_integrity()` / `projection_from_checkpoint()`, and malformed checkpoint shape as Pydantic `ValidationError`. Do not invent a general reducer-time referential policy. Add a reducer reference check only if an already-existing explicit reducer invariant test requires it.
- Invalid canonical event payloads must fail with Pydantic `ValidationError`; conflicting stable IDs must fail with `ProjectionReplayConflictError`; unsupported event names retain the existing `ValueError` public behavior.
- Every canonical event is either behavior-tested as state-changing or listed in `PROJECTION_NEUTRAL_EVENT_TYPES`; neutral events still validate their payload strictly before returning the unchanged projection.
- Flexible JSON coverage is derived from reachable immutable model annotations, not from the migration manifest. Checkpoint output contains only ordinary JSON dict/list/scalar/null values and decode reconstructs equal deeply immutable values.
- Performance gates replay deterministic `general`, `edge-heavy`, and `record-heavy` streams of exactly 10,000 events. Each scenario gets exactly one unmeasured warmup and three timed folds from `initial_projection()`; median elapsed seconds must be strictly `< 1.0`.
- Do not retain occurrence IDs, source revisions, old-field ownership, codemod reproduction, generated migration counts, mutable-baseline ratios, memory ratios, hardware metadata, or protocol hashes as closure evidence.
- Historical files under `docs/superpowers/specs/`, `docs/superpowers/plans/`, and `docs/dynamic-graph/complete/` remain unchanged as history.
- Follow strict RED/GREEN sequencing. Commit only after each task's focused tests are green; never skip hooks or amend a failed commit.

---

## File Map

- `tests/unit/graph_projection_behavior_cases.py`: shared immutable event builders, the exact 48-row canonical behavior matrix, group/entity identity metadata, and query probes.
- `tests/unit/test_graph_projection_behavior.py`: matrix coverage, direct reducer outcomes, neutral payload validation, unknown-event behavior, and matrix-level invariants.
- `tests/unit/test_graph_projection_flexible_json.py`: model-derived flexible-JSON inventory and event-driven checkpoint round trips for all reachable fields.
- `tests/unit/test_graph_projection_replay_equivalence.py`: every-split direct and checkpoint-plus-tail replay using matrix streams.
- `tests/unit/test_graph_projection_immutability.py`: earlier-generation stability and changed/shared identity assertions driven by matrix metadata.
- `tests/unit/test_graph_projection_queries.py`: public query mutation-isolation probes driven by matrix cases; existing public result shapes remain unchanged.
- `tests/unit/test_graph_projection_duplicate_ids.py`, `tests/unit/test_graph_projection_codec.py`, `tests/unit/test_graph_projection_integrity.py`: representative typed conflict, malformed checkpoint, and broken-reference outcomes.
- `src/orchestrator/graph/projections.py`: strict neutral-event payload validation only; no new referential checks or dispatch redesign.
- `src/orchestrator/graph/projection_models.py`: missing recursive-freeze validators for approval scope and oversight decider.
- `scripts/graph_projection_boundary_provenance.py`: permanent, migration-independent source-provenance analysis used by the boundary checker.
- `scripts/check_graph_projection_boundaries.py`: permanent grouped-storage/import/immutability/sole-owner/event-coverage guard wired to the new provenance helper.
- `tests/unit/test_graph_projection_boundaries.py`: guard behavior and explicit decoupling contract.
- `tests/unit/test_graph_projection_performance.py`: deterministic direct 10,000-event service-level gate; no artifact or historical baseline.
- `Makefile`, `pyproject.toml`, `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/dynamic-graph/graph-projection-map-inventory.md`, `tests/fixtures/graph/COVERAGE.md`, and `scripts/profile_graph_readback.py`: active references after retirement.
- Migration-only scripts, tests, fixtures, marker, generated diagnostics, and historical benchmark assets listed in Task 6: deleted.

### Task 1: Canonical Event Behavior Matrix And Strict Neutral Validation

**Files:**
- Create: `tests/unit/graph_projection_behavior_cases.py`
- Create: `tests/unit/test_graph_projection_behavior.py`
- Modify: `src/orchestrator/graph/projections.py:25,1782-1801`

**Interfaces:**
- Consumes: public `Actor`, `ActorKind`, `CANONICAL_EVENT_TYPES`, `EVENT_PAYLOAD_MODELS`, `EventEnvelope`, `GraphProjection`, `PROJECTION_NEUTRAL_EVENT_TYPES`, `ProjectionReplayConflictError`, `build_projection`, query functions, `initial_projection`, `projection_to_checkpoint`, and `reduce_event` from `orchestrator.graph`.
- Produces: frozen test-only `ProjectionBehaviorCase`; `behavior_cases() -> tuple[ProjectionBehaviorCase, ...]`; `fold_events(events: tuple[EventEnvelope, ...], projection: GraphProjection | None = None) -> GraphProjection`; and `case_projection(case: ProjectionBehaviorCase) -> tuple[GraphProjection, GraphProjection]` for Tasks 2, 3, and 5.

- [ ] **Step 1: Add the exact shared matrix types and event construction boundary**

Create `tests/unit/graph_projection_behavior_cases.py` with this interface. Keep all collections immutable and return fresh public query values only through the case callbacks.

```python
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeAlias

from orchestrator.graph import (
    Actor,
    ActorKind,
    EVENT_PAYLOAD_MODELS,
    EventEnvelope,
    GraphProjection,
    initial_projection,
    reduce_event,
)

ProjectionPath: TypeAlias = tuple[str, ...]
OutcomeAssertion: TypeAlias = Callable[[GraphProjection, GraphProjection], None]
QueryProbe: TypeAlias = Callable[[GraphProjection], object]
MutationProbe: TypeAlias = Callable[[object], None]


@dataclass(frozen=True)
class ProjectionBehaviorCase:
    event_type: str
    prefix: tuple[EventEnvelope, ...]
    event: EventEnvelope
    changed_groups: frozenset[str]
    replaced_paths: tuple[ProjectionPath, ...]
    shared_paths: tuple[ProjectionPath, ...]
    assert_outcome: OutcomeAssertion
    query: QueryProbe
    mutate_query_result: MutationProbe | None = None

    @property
    def stream(self) -> tuple[EventEnvelope, ...]:
        return (*self.prefix, self.event)


def event(event_type: str, payload: dict[str, object], position: int) -> EventEnvelope:
    canonical = EVENT_PAYLOAD_MODELS[event_type].model_validate(payload).model_dump(
        mode="json", by_alias=True
    )
    return EventEnvelope(
        event_id=f"matrix-{event_type}-{position}",
        run_id="matrix-run",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical,
    )


def fold_events(
    events: tuple[EventEnvelope, ...], projection: GraphProjection | None = None
) -> GraphProjection:
    current = projection if projection is not None else initial_projection()
    for item in events:
        current = reduce_event(current, item)
    return current


def case_projection(case: ProjectionBehaviorCase) -> tuple[GraphProjection, GraphProjection]:
    before = fold_events(case.prefix)
    return before, reduce_event(before, case.event)
```

The `event()` function validates only fixture construction. The malformed-neutral tests below must use `case.event.model_copy(update={"payload": {"__unexpected__": True}})` so the invalid payload reaches `reduce_event()`.

- [ ] **Step 2: Populate all 48 independently asserted behavior rows**

Implement `behavior_cases()` as one tuple with exactly one row per event type. Use minimal prefixes that are themselves checkpoint-valid: create referenced nodes before edges/leases/decisions, accept referenced records before bindings/cleanup/support/verification, and create a task candidate before verification events. Do not make the reducer reject a temporary missing reference merely to simplify a case.

Use these exact state-changing rows and observable outcomes:

| Event | Required prefix | Changed root groups | Direct outcome/query assertion |
|---|---|---|---|
| `run_lifecycle_changed` | empty | `lifecycle` | `run_state(after) == "active"` |
| `node_created` | empty | `nodes` | `node_exists(after, "worker-1")`; creation position retained |
| `node_state_changed` | planned node | `nodes`, `scheduling` | state becomes `ready`; ready query contains node |
| `node_retired` | running node | `nodes` | state becomes `retired` |
| `node_deferred` | node | `nodes` | deferred reason becomes `waiting` |
| `node_ready` | deferred node | `nodes` | deferred reason is cleared; authoritative runtime state is unchanged |
| `runtime_retry_scheduled` | node | `nodes` | retry-not-before equals the payload timestamp |
| `plan_region_marked_suspect` | node | `nodes` | runtime suspect reason equals `requirement_changed` |
| `node_authority_changed` | node | `nodes` | allowed actions, claims, and preconditions match payload |
| `edge_created` | source and target nodes | `topology` | `edge_by_id()` returns the exact endpoints/ports |
| `input_bound` | nodes, edge, accepted record | `topology` | `bound_record_ids()` returns that record ID |
| `output_record_accepted` | producer node | `records` | record payload and node/port index are present; use a `fan_out_inputs` record without task IDs |
| `file_state_accepted` | producer node | `records` | `file_state_record()` returns the accepted snapshot |
| `gatekeeper_verdict_recorded` | producer plus unresolved file-state record | `records` | projected classification is replaced with the recorded verdict |
| `session_state_changed` | empty | `planning` | session state equals `detached` |
| `graph_patch_accepted` | planner node plus accepted graph-patch-proposal record with the same patch ID | `planning`, `governance` | accepted patch query contains ID and resolved-patch fact is true |
| `verification_passed` | producer, task candidate, and matching verification record whose prefix task is not accepted | `verification`, `tasks` | verdict is `passed`; passed result/candidate query contains IDs; task becomes `accepted` |
| `verification_failed` | producer, task candidate, and matching verification record whose prefix task is not already `needs_revision` | `verification`, `tasks` | verdict is `failed`; failed result/candidate query contains IDs; task becomes `needs_revision` |
| `appeal_opened` | appealed node | `governance` | pending appeal for the appealed node is true; use a non-`invalid_test` appeal so no unrelated task fixture is required |
| `approval_decision_recorded` | gate node | `governance` | approval query returns `approved` and node gate decision is true |
| `authority_decision_recorded` | authority node | `governance` | authority query returns `granted` |
| `oversight_decision_recorded` | oversight node | `governance` | oversight query returns `accepted` at event position |
| `requirement_revision_recorded` | empty | `requirements` | revision exists and active-version query points to it |
| `support_evidence_recorded` | accepted evidence record plus active requirement revision | `requirements` | support query returns evidence/requirement/version IDs |
| `node_usage_recorded` | node | `usage` | recorded key is true and token totals equal input + output |
| `lease_granted` | node | `execution` | lease state is `active` and grant order contains the ID once |
| `lease_renewed` | granted lease | `execution` | expiry changes and state is `active` |
| `lease_suspended` | granted lease | `execution` | lease state is `suspended` |
| `lease_revoked` | granted lease | `execution` | lease state is `revoked` |
| `lease_expired` | granted lease | `execution` | lease state is `expired` |
| `lease_released` | granted lease | `execution` | lease state is `released` |
| `cleanup_requested` | node plus file-state record | `execution` | cleanup request contains paths and source record ID |
| `cleanup_applied` | cleanup request prefix | `execution` | `cleanup_applied()` is true |
| `callback_accepted` | node | `execution` | callback query returns accepted outcome and payload |

Use these exact valid neutral payload shapes; each row must assert `after is before`, unchanged checkpoint data, and the same representative public query result before/after:

```python
NEUTRAL_PAYLOADS: dict[str, dict[str, object]] = {
    "agent_died": {"lease_id": "lease-1", "node_id": "worker-1", "reason": "agent_exit"},
    "agent_dispatch_requested": {
        "lease_granted_event_id": "lease-granted-1",
        "lease_id": "lease-1",
        "node_id": "worker-1",
        "generation": 1,
        "execution_id": "execution-1",
        "base_snapshot_id": "snapshot-1",
        "resource_claims": [],
    },
    "callback_duplicate_returned": {
        "node_id": "worker-1", "lease_id": "lease-1", "lease_generation": 1,
        "execution_id": "execution-1", "idempotency_key": "callback-1",
        "payload": None, "reason": "duplicate", "prior_result": None,
    },
    "callback_rejected_conflict": {
        "node_id": "worker-1", "lease_id": "lease-1", "lease_generation": 1,
        "execution_id": "execution-1", "idempotency_key": "callback-1",
        "payload": None, "reason": "conflict",
    },
    "callback_rejected_stale": {
        "node_id": "worker-1", "lease_id": "lease-1", "lease_generation": 1,
        "execution_id": "execution-1", "idempotency_key": "callback-1",
        "payload": None, "reason": "stale",
    },
    "command_recorded": {"command_type": "start", "command_payload": {}},
    "command_rejected": {"command_type": "start", "reason": "invalid"},
    "dead_input_detected": {
        "node_id": "worker-1", "from_node_id": "source-1",
        "to_port": "input", "reason": "upstream_failed",
    },
    "file_state_rejected": {
        "record_id": "rejected-file-state", "record_type": "file_state",
        "record_kind": "file_state", "producer_node_id": "worker-1",
        "port": "file_state", "schema": "FileStateRecord", "reason": "residue",
    },
    "gatekeeper_cost_recorded": {
        "execution_id": "execution-1", "file_state_record_id": "file-state-1",
        "consult_id": "consult-1",
    },
    "graph_patch_rejected": {"patch_id": "patch-1", "reason": "invalid"},
    "heartbeat_recorded": {
        "lease_id": "lease-1", "node_id": "worker-1",
        "observed_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-01-01T00:05:00+00:00",
    },
    "outbox_requeued": {
        "run_id": "matrix-run", "outbox_id": 1, "event_id": "event-1",
        "kind": "callback", "previous_status": "failed", "previous_attempts": 1,
        "previous_last_error": "transient", "operator": "operator-1", "graph_position": 1,
    },
    "revision_created": {
        "node": {"node_id": "revision-1", "kind": "worker"},
        "worker_node": {"node_id": "worker-1", "kind": "worker"},
        "verifier_node": {"node_id": "verifier-1", "kind": "verifier"},
    },
}
```

Use explicit assertion functions, not occurrence counts or reducer-branch inspection. For mutable public query results, record `mutate_query_result`; for immutable/scalar results leave it `None`. Include `replaced_paths` for the changed node, edge, record, decision, requirement, support, lease, cleanup, callback, or session value and `shared_paths` whenever the prefix contains a sibling entity that must retain identity.

- [ ] **Step 3: Add matrix coverage and malformed-neutral RED tests**

Create `tests/unit/test_graph_projection_behavior.py`:

```python
import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    CANONICAL_EVENT_TYPES,
    PROJECTION_NEUTRAL_EVENT_TYPES,
    initial_projection,
    projection_to_checkpoint,
    reduce_event,
)
from tests.unit.graph_projection_behavior_cases import behavior_cases, case_projection


CASES = behavior_cases()


def test_behavior_matrix_exactly_covers_every_canonical_event_once() -> None:
    event_types = tuple(case.event_type for case in CASES)
    assert len(event_types) == len(set(event_types))
    assert frozenset(event_types) == CANONICAL_EVENT_TYPES
    assert {
        case.event_type for case in CASES if not case.changed_groups
    } == PROJECTION_NEUTRAL_EVENT_TYPES


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.event_type)
def test_each_canonical_event_owns_its_declared_behavior(case) -> None:
    before, after = case_projection(case)
    case.assert_outcome(before, after)
    if case.event_type in PROJECTION_NEUTRAL_EVENT_TYPES:
        assert after is before
    else:
        assert after is not before


@pytest.mark.parametrize(
    "case",
    tuple(case for case in CASES if case.event_type in PROJECTION_NEUTRAL_EVENT_TYPES),
    ids=lambda case: case.event_type,
)
def test_projection_neutral_events_reject_malformed_payloads_without_changing_state(case) -> None:
    before, _ = case_projection(case)
    snapshot = projection_to_checkpoint(before)
    malformed = case.event.model_copy(update={"payload": {"__unexpected__": True}})

    with pytest.raises(ValidationError):
        reduce_event(before, malformed)

    assert projection_to_checkpoint(before) == snapshot


def test_unsupported_event_name_still_fails_loudly() -> None:
    source = CASES[0].event
    unsupported = source.model_copy(
        update={"event_id": "unsupported", "event_type": "not_canonical", "payload": {}}
    )
    with pytest.raises(ValueError, match="unsupported graph projection event type"):
        reduce_event(initial_projection(), unsupported)
```

- [ ] **Step 4: Run RED and confirm the strict neutral defect**

Run:

```bash
uv run pytest tests/unit/test_graph_projection_behavior.py -q
```

Expected: the 48-row coverage and valid behavior tests collect, while every malformed neutral row fails with `DID NOT RAISE ValidationError` because `reduce_event()` currently returns neutral events without validating `EVENT_PAYLOAD_MODELS[event.event_type]`.

- [ ] **Step 5: Validate neutral payloads at the narrow reducer boundary**

In `src/orchestrator/graph/projections.py`, import `EVENT_PAYLOAD_MODELS` beside `PROJECTION_NEUTRAL_EVENT_TYPES` and make only this change:

```python
if event.event_type in PROJECTION_NEUTRAL_EVENT_TYPES:
    EVENT_PAYLOAD_MODELS[event.event_type].model_validate(event.payload)
    return state
```

Do not call `validate_projection_integrity()` from `reduce_event()`, do not add node/record/edge existence checks, and do not change unknown-event behavior.

- [ ] **Step 6: Run GREEN behavior tests and broader reducer tests**

Run:

```bash
uv run pytest tests/unit/test_graph_projection_behavior.py tests/unit/test_graph_projections.py tests/unit/test_graph_event_registry.py -q
```

Expected: all pass; the matrix has exactly 48 unique rows and exactly the registry's 14 neutral names.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/orchestrator/graph/projections.py tests/unit/graph_projection_behavior_cases.py tests/unit/test_graph_projection_behavior.py
git commit -m "fix(graph): validate canonical projection behavior"
```

### Task 2: Model-Derived Flexible JSON Coverage And Codec Fixes

**Files:**
- Create: `tests/unit/test_graph_projection_flexible_json.py`
- Modify: `src/orchestrator/graph/projection_models.py:472-523`

**Interfaces:**
- Consumes: `ProjectionModel`, `GraphProjection`, `FrozenJsonValue`, `FrozenMap`, `build_projection`, `freeze_json`, `projection_to_checkpoint`, and `projection_from_checkpoint` from `orchestrator.graph`; event builders from `tests/unit/graph_projection_behavior_cases.py`.
- Produces: test-only `discover_flexible_json_fields(root: type[ProjectionModel]) -> frozenset[tuple[str, str]]`; `FlexibleJsonCase`; and exact event-backed `FLEXIBLE_JSON_CASES` keyed by `(declaring_model_name, field_name)`.

- [ ] **Step 1: Add model-graph discovery with an exact field inventory**

Create a recursive annotation walker that handles `Annotated`, unions, PEP 695 `TypeAliasType`, tuples, and `FrozenMap`, tracks active aliases/models, and examines each reachable model's declaring class (`__annotations__`) so inherited `ProjectedRecordBase.payload` and `.provenance` are counted once. A field is flexible when its annotation contains `FrozenJsonValue` before crossing into another `ProjectionModel`.

The discovered set must equal these 29 declaring fields:

```python
EXPECTED_FLEXIBLE_JSON_FIELDS = frozenset(
    {
        ("ApprovalDecisionValue", "scope"),
        ("AuthorityDecisionValue", "scope"),
        ("CallbackEventValue", "payload"),
        ("CommandDefinitionValue", "value"),
        ("EdgeValue", "accepted_record_selector"),
        ("EdgeValue", "binding_policy"),
        ("EdgeValue", "description"),
        ("EdgeValue", "freshness_policy"),
        ("EdgeValue", "metadata"),
        ("EdgeValue", "prompt_hydration_policy"),
        ("EdgeValue", "purpose"),
        ("EdgeValue", "selection"),
        ("OversightDecisionValue", "decider"),
        ("OversightDecisionValue", "scope"),
        ("ProjectedAuthorityDecisionRecordValue", "scope"),
        ("ProjectedCheckResultRecordValue", "command"),
        ("ProjectedCheckResultRecordValue", "command_binding"),
        ("ProjectedCheckResultRecordValue", "environment_policy"),
        ("ProjectedCompletionDecisionValue", "blockers"),
        ("ProjectedDecisionRecordValue", "scope"),
        ("ProjectedFanOutInputsRecord", "value"),
        ("ProjectedGitRef", "diff_summary"),
        ("ProjectedGraphPatchProposalValue", "macro_invocations"),
        ("ProjectedGraphPatchProposalValue", "ops"),
        ("ProjectedRecordBase", "payload"),
        ("ProjectedRecordBase", "provenance"),
        ("ProjectedRecoveryPlanValue", "graph_changes"),
        ("ProjectedRoutineSnapshotValue", "dynamic_feature"),
        ("ProjectedVerificationReportRecord", "evidence"),
    }
)
```

Do not read `scripts/codemods/graph_projection_manifest.yaml`, migration fixtures, or generated reports.

- [ ] **Step 2: Define event-backed cases for every discovered field**

Use a frozen test case with exact shape adapters:

```python
@dataclass(frozen=True)
class FlexibleJsonCase:
    owner: str
    field: str
    events: Callable[[object], tuple[EventEnvelope, ...]]
    projected_value: Callable[[GraphProjection], object]
    checkpoint_value: Callable[[dict[str, object]], object]
    container: Literal["direct", "map-value", "tuple-map-value"]
```

Map producers as follows:

- `node_created`: `CommandDefinitionValue.value`.
- `edge_created`: all eight `EdgeValue` fields.
- `approval_decision_recorded`: `ApprovalDecisionValue.scope`.
- `authority_decision_recorded`: `AuthorityDecisionValue.scope`.
- `oversight_decision_recorded`: `OversightDecisionValue.decider` and `.scope`.
- `callback_accepted`: `CallbackEventValue.payload`.
- `output_record_accepted` with the matching concrete record: all projected-record fields, including base `payload`/`provenance`, decision scopes, check command fields, completion blockers, fan-out value, file-state git diff summary, graph-patch ops/macro invocations, recovery graph changes, routine dynamic feature, and verification evidence.

Use the canonical JSON probes below. For `direct`, install the probe directly. For `map-value`, install `{"probe": probe}`. For `tuple-map-value`, install `[{"probe": probe}]`. Thus required outer objects/tuples stay valid while every open JSON leaf receives object/array/scalar/null coverage.

```python
JSON_PROBES = (
    {"nested": [{"array": [1, True, None]}, "text"]},
    [1, {"nested": [False, None]}],
    "scalar",
    7,
    False,
    None,
)
```

All 29 fields have an event producer, so do not use direct model fixtures in the current inventory. If discovery later finds a passive field without an event path, require an explicitly named direct model case instead of weakening discovery.

- [ ] **Step 3: Add RED round-trip tests for every field/probe pair**

```python
def assert_plain_json(value: object) -> None:
    assert type(value) in {dict, list, str, int, float, bool, type(None)}
    if type(value) is dict:
        assert all(type(key) is str for key in value)
        for child in value.values():
            assert_plain_json(child)
    elif type(value) is list:
        for child in value:
            assert_plain_json(child)


def test_flexible_json_cases_exactly_match_reachable_model_fields() -> None:
    assert discover_flexible_json_fields(GraphProjection) == EXPECTED_FLEXIBLE_JSON_FIELDS
    assert frozenset(FLEXIBLE_JSON_CASES) == EXPECTED_FLEXIBLE_JSON_FIELDS


@pytest.mark.parametrize("probe", JSON_PROBES, ids=("object", "array", "str", "int", "bool", "null"))
@pytest.mark.parametrize("case", FLEXIBLE_JSON_CASES.values(), ids=lambda case: f"{case.owner}.{case.field}")
def test_every_flexible_json_field_round_trips_through_plain_checkpoint_json(case, probe) -> None:
    projection = build_projection(list(case.events(probe)))
    checkpoint = projection_to_checkpoint(projection)
    assert_plain_json(case.checkpoint_value(checkpoint))

    restored = projection_from_checkpoint(deepcopy(checkpoint))

    assert restored == projection
    assert case.projected_value(restored) == case.projected_value(projection)
```

- [ ] **Step 4: Run RED and confirm the two reproduced failures**

Run:

```bash
uv run pytest tests/unit/test_graph_projection_flexible_json.py -q
```

Expected: approval scope cases fail during checkpoint decode because `ApprovalDecisionValue.scope` lacks a before-validator, and oversight object/array decider cases fail because `OversightDecisionValue.decider` is not recursively frozen on checkpoint reconstruction. The discovery-to-case equality must already pass; do not delete probes or fields to obtain green.

- [ ] **Step 5: Add the minimal model-boundary freeze validators**

In `ApprovalDecisionValue`, add the same scope validator already used by `AuthorityDecisionValue`. In `OversightDecisionValue`, freeze both open JSON fields:

```python
class ApprovalDecisionValue(ProjectionModel):
    # existing fields unchanged

    @field_validator("scope", mode="before")
    @classmethod
    def freeze_scope(cls, value: object) -> FrozenJsonValue | None:
        return None if value is None else _freeze_json_input(value)


class OversightDecisionValue(ProjectionModel):
    # existing fields unchanged

    @field_validator("decider", "scope", mode="before")
    @classmethod
    def freeze_open_json(cls, value: object) -> FrozenJsonValue | None:
        return None if value is None else _freeze_json_input(value)
```

Keep the existing `AuthorityDecisionValue` validator. Do not add compatibility checkpoint parsing or convert JSON back to mutable containers inside the projection.

- [ ] **Step 6: Run GREEN codec coverage**

```bash
uv run pytest tests/unit/test_graph_projection_flexible_json.py tests/unit/test_graph_projection_codec.py tests/unit/test_graph_projection_models.py -q
```

Expected: all pass; every checkpoint probe is ordinary JSON and every restored projected value is deeply immutable and equal.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/orchestrator/graph/projection_models.py tests/unit/test_graph_projection_flexible_json.py
git commit -m "fix(graph): freeze all flexible projection json"
```

### Task 3: Every-Split Replay, Generation Identity, Query Isolation, And Typed Failures

**Files:**
- Modify: `tests/unit/graph_projection_behavior_cases.py`
- Modify: `tests/unit/test_graph_projection_replay_equivalence.py`
- Modify: `tests/unit/test_graph_projection_immutability.py`
- Modify: `tests/unit/test_graph_projection_queries.py`
- Modify: `tests/unit/test_graph_projection_duplicate_ids.py`
- Modify: `tests/unit/test_graph_projection_codec.py`
- Modify: `tests/unit/test_graph_projection_integrity.py`

**Interfaces:**
- Consumes: `ProjectionBehaviorCase.stream`, `changed_groups`, `replaced_paths`, `shared_paths`, `query`, and `mutate_query_result` from Task 1; checkpoint APIs and typed exceptions from `orchestrator.graph`.
- Produces: `replay_streams() -> tuple[tuple[str, tuple[EventEnvelope, ...]], ...]`, made from matrix cases only; complete replay/identity/isolation contracts with no new production API.

- [ ] **Step 1: Add RED tests against the not-yet-defined replay stream interface**

First import `replay_streams` from the shared case module and add this every-split test:

```python
STREAMS = replay_streams()


@pytest.mark.parametrize(
    ("name", "stream"),
    STREAMS,
    ids=[name for name, _stream in STREAMS],
)
def test_matrix_streams_match_full_incremental_and_checkpoint_tail_replay_at_every_split(
    name: str, stream: tuple[EventEnvelope, ...]
) -> None:
    full = fold_events(stream)
    for split in range(len(stream) + 1):
        prefix = fold_events(stream[:split])
        assert fold_events(stream[split:], prefix) == full, (name, split)

        checkpoint = projection_to_checkpoint(prefix)
        restored = projection_from_checkpoint(deepcopy(checkpoint))
        assert fold_events(stream[split:], restored) == full, (name, split)
```

Run:

```bash
uv run pytest tests/unit/test_graph_projection_replay_equivalence.py -q
```

Expected RED: collection fails with `ImportError: cannot import name 'replay_streams'`.

- [ ] **Step 2: Implement matrix-derived replay streams and make every prefix valid**

Add this exact public test-helper shape:

```python
def replay_streams() -> tuple[tuple[str, tuple[EventEnvelope, ...]], ...]:
    return tuple((case.event_type, case.stream) for case in behavior_cases())
```

If a checkpoint split exposes a broken reference, repair that case's prefix ordering/data so the referenced entity is represented before the reference. Do not add a reducer-time repair or existence check. Keep the existing retired-callback and bounded Hypothesis replay tests as additional coverage.

- [ ] **Step 3: Prove all earlier generations and identity metadata**

Add matrix-driven tests to `test_graph_projection_immutability.py`:

```python
ROOT_GROUPS = tuple(GraphProjection.model_fields)


def value_at(projection: GraphProjection, path: tuple[str, ...]) -> object:
    value: object = projection
    for part in path:
        value = getattr(value, part) if isinstance(value, BaseModel) else value[part]
    return value


@pytest.mark.parametrize("case", behavior_cases(), ids=lambda case: case.event_type)
def test_matrix_reduction_preserves_prior_generation_and_shares_only_unchanged_values(case) -> None:
    before, after = case_projection(case)
    before_checkpoint = deepcopy(projection_to_checkpoint(before))

    assert projection_to_checkpoint(before) == before_checkpoint
    for group in ROOT_GROUPS:
        if group in case.changed_groups:
            assert getattr(after, group) is not getattr(before, group), (case.event_type, group)
        else:
            assert getattr(after, group) is getattr(before, group), (case.event_type, group)
    for path in case.replaced_paths:
        assert value_at(after, path) is not value_at(before, path), (case.event_type, path)
    for path in case.shared_paths:
        assert value_at(after, path) is value_at(before, path), (case.event_type, path)
```

Also fold every replay stream while saving `(generation, checkpoint)` after each event; after completing the stream, assert every saved generation still serializes to its saved checkpoint. Neutral rows must retain root identity; state-changing rows must replace the root.

- [ ] **Step 4: Prove public query mutation isolation with matrix query probes**

In `test_graph_projection_queries.py`, parameterize cases that define `mutate_query_result`:

```python
@pytest.mark.parametrize(
    "case",
    tuple(case for case in behavior_cases() if case.mutate_query_result is not None),
    ids=lambda case: case.event_type,
)
def test_matrix_public_query_results_cannot_mutate_projection_storage(case) -> None:
    _, projection = case_projection(case)
    checkpoint = deepcopy(projection_to_checkpoint(projection))
    original = case.query(projection)

    assert case.mutate_query_result is not None
    case.mutate_query_result(original)

    assert projection_to_checkpoint(projection) == checkpoint
    case.assert_outcome(fold_events(case.prefix), projection)
```

Mutation probes should mutate nested lists/dicts in fresh legacy public models/views. For query results intentionally returned as frozen projection models, the probe must assert `ValidationError`, `AttributeError`, or `TypeError` and then verify the same checkpoint. Do not change return types or response shapes.

- [ ] **Step 5: Consolidate representative typed failure assertions**

Keep exhaustive existing tests, and add one clearly named representative at each boundary:

```python
# test_graph_projection_duplicate_ids.py
with pytest.raises(ProjectionReplayConflictError, match="conflicts during replay"):
    reduce_event(state_with_matrix_node, conflicting_same_node_id_event)

# test_graph_projection_codec.py
with pytest.raises(ValidationError, match="checkpoint root keys"):
    projection_from_checkpoint(checkpoint_missing_lifecycle)

# test_graph_projection_integrity.py
with pytest.raises(ProjectionCheckpointIntegrityError) as raised:
    projection_from_checkpoint(checkpoint_with_missing_edge_target)
assert any(item.path == "topology.edges.edge-1.to_node_id" for item in raised.value.diagnostics)
```

The malformed neutral `ValidationError` and unsupported-name `ValueError` remain in `test_graph_projection_behavior.py`. Build broken references by changing plain checkpoint data, not by expecting `reduce_event()` to reject an event whose schema is otherwise valid.

- [ ] **Step 6: Run GREEN replay, immutability, query, and typed-failure suites**

```bash
uv run pytest \
  tests/unit/test_graph_projection_behavior.py \
  tests/unit/test_graph_projection_replay_equivalence.py \
  tests/unit/test_graph_projection_immutability.py \
  tests/unit/test_graph_projection_queries.py \
  tests/unit/test_graph_projection_duplicate_ids.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_integrity.py -q
```

Expected: all pass at every split. If a newly demonstrated production defect appears, fix only the narrow model/reducer/codec/query boundary and rerun this command; never weaken the matrix or defer a known failure.

- [ ] **Step 7: Commit Task 3**

```bash
git add tests/unit/graph_projection_behavior_cases.py \
  tests/unit/test_graph_projection_replay_equivalence.py \
  tests/unit/test_graph_projection_immutability.py \
  tests/unit/test_graph_projection_queries.py \
  tests/unit/test_graph_projection_duplicate_ids.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_integrity.py
git commit -m "test(graph): close immutable projection contracts"
```

### Task 4: Permanent Boundary Guard Independent Of Migration Inventory

**Files:**
- Create: `scripts/graph_projection_boundary_provenance.py`
- Modify: `scripts/check_graph_projection_boundaries.py:16-36,599-623,765-844`
- Modify: `tests/unit/test_graph_projection_boundaries.py:12-19,279-319,898-915`

**Interfaces:**
- Consumes: Python `ast`/`tokenize`, exact approved graph symbol/producer tables, and tracked Python paths from `git ls-files`.
- Produces: `ProjectionProvenanceFact(line: int, column: int, expression: str, certainty: Literal["definite", "possible"])`; `projection_provenance(source: str, *, relative_path: str) -> tuple[ProjectionProvenanceFact, ...]`; `projection_provenance_seed_tokens() -> frozenset[str]`; unchanged `check_projection_boundaries()` and hook CLI behavior.

- [ ] **Step 1: Add an explicit RED decoupling contract**

Add to `test_graph_projection_boundaries.py`:

```python
def test_permanent_boundary_guard_does_not_import_migration_inventory() -> None:
    source = (_ROOT / "scripts/check_graph_projection_boundaries.py").read_text()
    assert "graph_projection_inventory" not in source


def test_boundary_provenance_has_no_migration_bookkeeping_vocabulary() -> None:
    source = (_ROOT / "scripts/graph_projection_boundary_provenance.py").read_text()
    for retired_name in (
        "baseline_revision",
        "occurrence_id",
        "graph_projection_manifest",
        "MigrationDisposition",
    ):
        assert retired_name not in source
```

Run:

```bash
uv run pytest tests/unit/test_graph_projection_boundaries.py::test_permanent_boundary_guard_does_not_import_migration_inventory -q
```

Expected RED: assertion fails because `check_graph_projection_boundaries.py` imports `ProjectionProvenanceFact`, `projection_provenance`, and `projection_provenance_seed_tokens` from `graph_projection_inventory`.

- [ ] **Step 2: Implement a focused permanent provenance module**

Create `scripts/graph_projection_boundary_provenance.py` with only source-boundary concepts. Preserve these exact finite origins:

```python
GRAPH_PROJECTION_TYPES = frozenset({"orchestrator.graph.GraphProjection"})
PROJECTION_FUNCTIONS = frozenset(
    {
        "orchestrator.graph.initial_projection",
        "orchestrator.graph.build_projection",
        "orchestrator.graph.reduce_event",
        "orchestrator.graph_runtime.controller.rebuild_projection",
    }
)
PROJECTION_METHODS = {
    ("GraphController", "read_projection"): "value",
    ("GraphEventStore", "load_projection_with_tail"): "first_tuple_item",
    ("GraphEventStore", "read_projection_checkpoint"): "GraphProjectionCheckpoint",
}
PROJECTION_FIELDS = {
    "GraphDispatchContext": frozenset({"graph_projection"}),
    "GraphProjectionCheckpoint": frozenset({"projection"}),
}
```

Use an AST scope visitor that:

- resolves absolute and relative imports to their full origin;
- seeds parameters/annotated assignments typed as `GraphProjection`;
- recognizes unshadowed calls to the approved projection functions;
- recognizes the three typed producer methods and the two typed fields above;
- propagates definite aliases through assignments and `await`;
- merges `if`/`else` aliases as `possible` when only one branch carries projection provenance;
- records source-order facts for the exact subscript/attribute/call expression consumed by `_BoundaryVisitor`;
- isolates lexical scopes and respects parameter/local/import/pattern-capture shadowing;
- raises `SyntaxError` for malformed input so the existing boundary script remains fail-closed.

The model and function signatures are:

```python
class ProjectionProvenanceFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    line: int
    column: int
    expression: str
    certainty: Literal["definite", "possible"]


def projection_provenance(
    source: str, *, relative_path: str
) -> tuple[ProjectionProvenanceFact, ...]:
    tree = ast.parse(source, filename=relative_path)
    collector = ProjectionProvenanceCollector(source, relative_path)
    collector.visit(tree)
    return tuple(sorted(collector.facts.values(), key=lambda item: (item.line, item.column)))


def projection_provenance_seed_tokens() -> frozenset[str]:
    origins = (*GRAPH_PROJECTION_TYPES, *PROJECTION_FUNCTIONS)
    typed_names = {name for name, _ in PROJECTION_METHODS} | set(PROJECTION_FIELDS)
    return frozenset({*(origin.rpartition(".")[2] for origin in origins), *typed_names})
```

This module must not import LibCST, YAML, a manifest, or any migration script.

- [ ] **Step 3: Switch the guard and preserve the permanent contract checks**

Import the new helper in package and direct-script modes:

```python
if __package__:
    from scripts.graph_projection_boundary_provenance import (
        ProjectionProvenanceFact,
        projection_provenance,
        projection_provenance_seed_tokens,
    )
else:
    from graph_projection_boundary_provenance import (
        ProjectionProvenanceFact,
        projection_provenance,
        projection_provenance_seed_tokens,
    )
```

Leave these permanent checks intact and independently tested:

- exact `ALLOWED_STORAGE_READERS` five-file set;
- frozen/deeply immutable annotation graph;
- no `_clone_projection` and no old projection `TypedDict` root;
- external graph imports only through `orchestrator.graph`;
- complete-record owner exactly `records.by_id`;
- canonical event dispatch union explicit neutral events exactly equals `CANONICAL_EVENT_TYPES`;
- existing `graph-projection-boundaries` pre-commit hook definition.

- [ ] **Step 4: Run GREEN boundary tests and standalone guard**

```bash
uv run pytest tests/unit/test_graph_projection_boundaries.py -q
uv run python scripts/check_graph_projection_boundaries.py
```

Expected: tests pass and the script exits 0 without output. Any provenance regression must be fixed in the new focused helper, not by allowing an extra storage reader.

- [ ] **Step 5: Commit Task 4**

```bash
git add scripts/graph_projection_boundary_provenance.py scripts/check_graph_projection_boundaries.py tests/unit/test_graph_projection_boundaries.py
git commit -m "refactor(graph): isolate projection boundary guard"
```

### Task 5: Direct Deterministic 10,000-Event Performance Gate

**Files:**
- Create: `tests/unit/test_graph_projection_performance.py`

**Interfaces:**
- Consumes: public `Actor`, `ActorKind`, `EventEnvelope`, `accepted_record_summaries_by_id_view`, `edges_view`, `initial_projection`, `node_states_view`, and `reduce_event` from `orchestrator.graph`.
- Produces: test-only `_performance_event_stream(scenario: Literal["general", "edge-heavy", "record-heavy"], size: int) -> tuple[EventEnvelope, ...]` and `_replay(events) -> GraphProjection`; no script, artifact schema, baseline, CLI, or production API.

- [ ] **Step 1: Write the direct gate before its stream generator**

Create the imports, `_replay()`, and parameterized test below, but do not define `_performance_event_stream` yet:

```python
from statistics import median
from time import perf_counter

import pytest


SCENARIOS = ("general", "edge-heavy", "record-heavy")
EVENT_COUNT = 10_000


def _replay(events: tuple[EventEnvelope, ...]) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_ten_thousand_event_replay_median_is_strictly_subsecond(scenario: str) -> None:
    events = _performance_event_stream(scenario, EVENT_COUNT)
    assert len(events) == EVENT_COUNT
    assert len({event.event_id for event in events}) == EVENT_COUNT
    assert tuple(event.position for event in events) == tuple(range(EVENT_COUNT))

    warmup = _replay(events)
    samples: list[float] = []
    results: list[GraphProjection] = []
    for _ in range(3):
        started = perf_counter()
        results.append(_replay(events))
        samples.append(perf_counter() - started)

    expected_nodes = sum(event.event_type == "node_created" for event in events)
    expected_edges = sum(event.event_type == "edge_created" for event in events)
    expected_records = sum(event.event_type == "output_record_accepted" for event in events)
    assert all(result == warmup for result in results)
    assert len(node_states_view(warmup)) == expected_nodes
    assert len(edges_view(warmup)) == expected_edges
    assert len(accepted_record_summaries_by_id_view(warmup)) == expected_records
    assert expected_nodes > 0
    if scenario != "record-heavy":
        assert expected_edges > 0
    if scenario != "edge-heavy":
        assert expected_records > 0
    assert median(samples) < 1.0, (scenario, samples)
```

The event tuple is generated before timing. The only timed operation is a full fold from `initial_projection()`. There is exactly one call before timing and exactly three timed calls.

- [ ] **Step 2: Run RED for the missing deterministic stream interface**

```bash
uv run pytest tests/unit/test_graph_projection_performance.py -q
```

Expected RED: all three rows fail with `NameError: name '_performance_event_stream' is not defined`.

- [ ] **Step 3: Implement the three exact stream mixes**

Use the deterministic envelope builder below and the existing benchmark's canonical four-family payload shapes, without importing the benchmark script:

```python
def _performance_event(index: int, event_type: str, payload: dict[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"performance-{event_type}-{index}",
        run_id="performance-run",
        position=index,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
        payload=payload,
    )
```

Generate exactly these mixes:

- `record-heavy`: event 0 creates `performance-node-000000`; events 1..9999 each accept a unique `fan_out_inputs` record produced by that node.
- `edge-heavy`: event 0 creates node 0; odd events create the next node; even events create the unique edge from the previous node to that node.
- `general`: event 0 creates node 0; then repeat create-node, create-edge, mark-node-ready, accept-unique-record for the next node, truncating at exactly 10,000.

Use record payloads with unique `record_id`, `record_type="fan_out_inputs"`, `record_kind="output"`, `producer_node_id`, `producer_port="candidate"`, `port="candidate"`, `schema="ImplementationCandidate"`, and deterministic nested `value`, `payload`, and `provenance` objects. Validate scenario and positive size, and return a tuple.

- [ ] **Step 4: Run GREEN direct performance gate twice**

```bash
uv run pytest tests/unit/test_graph_projection_performance.py -q
uv run pytest tests/unit/test_graph_projection_performance.py -q
```

Expected: three passing scenario rows on each fresh run; each reports no assertion detail because its median is strictly below 1.0. A timing failure blocks completion; do not add warmups, relax the threshold, mark it slow, compare against a baseline, or omit behavior assertions.

- [ ] **Step 5: Commit Task 5**

```bash
git add tests/unit/test_graph_projection_performance.py
git commit -m "test(graph): enforce direct replay performance bound"
```

### Task 6: Retire Migration-Only Assets And Update Active Documentation

**Files:**
- Delete: `scripts/graph_projection_inventory.py`
- Delete: `scripts/generate_graph_projection_goldens.py`
- Delete: `scripts/codemods/migrate_graph_projection_queries.py`
- Delete: `scripts/codemods/graph_projection_manifest.yaml`
- Delete: `scripts/codemods/graph_projection_query_migration.yaml`
- Delete: `scripts/benchmark_graph_projection.py`
- Delete: `tests/unit/test_graph_projection_inventory.py`
- Delete: `tests/unit/test_migrate_graph_projection_queries.py`
- Delete: `tests/unit/test_graph_projection_migration.py`
- Delete: `tests/unit/test_graph_projection_goldens.py`
- Delete: `tests/unit/test_graph_projection_test_speed.py`
- Delete: `tests/unit/test_benchmark_graph_projection.py`
- Delete: `tests/integration/test_graph_projection_public_parity.py`
- Delete: `tests/fixtures/graph_projection_migration/access_inventory.json`
- Delete: `tests/fixtures/graph_projection_migration/query_migration_report.json`
- Delete: `tests/fixtures/graph_projection_migration/public_view_goldens.json`
- Delete: `tests/fixtures/graph_projection_migration/replay_goldens.json`
- Delete: `tests/fixtures/graph_projection_performance/baseline.json`
- Delete: `tests/fixtures/graph_projection_performance/scenarios.json`
- Delete: `docs/graph-projection-inventory-diagnostics.md`
- Modify: `tests/unit/test_graph_projection_queries.py:1-168,896-1188` (remove migration imports/constants/tests; preserve all query behavior tests)
- Modify: `scripts/profile_graph_readback.py:27,250-253,461-465` (remove dependency on deleted benchmark corpus while preserving the standalone readback profiler)
- Modify: `Makefile:5-9,60-74`
- Modify: `pyproject.toml:67-70`
- Modify: `AGENTS.md` (remove the migration marker/Make target paragraph; retain permanent immutable projection rules)
- Modify: `docs/ARCHITECTURE.md:392-421`
- Modify: `docs/dynamic-graph/graph-projection-map-inventory.md:31-48`
- Modify: `tests/fixtures/graph/COVERAGE.md:142-152`
- Preserve unchanged: every historical file under `docs/superpowers/specs/`, `docs/superpowers/plans/`, and `docs/dynamic-graph/complete/`

**Interfaces:**
- Consumes: green behavior, flexible JSON, replay, boundary, and direct performance suites from Tasks 1-5.
- Produces: no migration CLI/Make/pytest-marker surface; active docs point only to executable current contracts; permanent boundary hook remains unchanged in `.pre-commit-config.yaml`.

- [ ] **Step 1: Run an explicit RED retirement inventory**

```bash
test -z "$(git ls-files \
  scripts/graph_projection_inventory.py \
  scripts/generate_graph_projection_goldens.py \
  scripts/codemods/migrate_graph_projection_queries.py \
  scripts/codemods/graph_projection_manifest.yaml \
  scripts/codemods/graph_projection_query_migration.yaml \
  scripts/benchmark_graph_projection.py \
  tests/unit/test_graph_projection_inventory.py \
  tests/unit/test_migrate_graph_projection_queries.py \
  tests/unit/test_graph_projection_migration.py \
  tests/unit/test_graph_projection_goldens.py \
  tests/unit/test_graph_projection_test_speed.py \
  tests/unit/test_benchmark_graph_projection.py \
  tests/integration/test_graph_projection_public_parity.py \
  tests/fixtures/graph_projection_migration \
  tests/fixtures/graph_projection_performance \
  docs/graph-projection-inventory-diagnostics.md)"
```

Expected RED: exit status 1 because the listed one-time files are still tracked.

- [ ] **Step 2: Delete the retired tools, tests, fixtures, reports, and comparison assets**

Delete every path in the Files list. Do not delete `scripts/check_graph_projection_boundaries.py`, `scripts/graph_projection_boundary_provenance.py`, the boundary pre-commit hook, active behavior tests, or historical design/plan/complete documents.

The benchmark script, its ratio/protocol tests, and its baseline/scenario artifacts are deleted because Task 5 is now the direct release gate. The SQLite/API golden parity test is migration-only and is not replaced with a database-backed closure test.

- [ ] **Step 3: Remove migration-only code embedded in retained files**

In `test_graph_projection_queries.py`, remove:

- imports from `scripts.graph_projection_inventory`;
- `ROOT` / `MANIFEST_PATH` migration constants;
- tests beginning with `test_disposition_site_key_is_stable_without_source_position` through `test_manifest_rejects_blank_baseline_and_unclassified_domain`.

Retain every public query value/order/mutation-isolation test.

In `scripts/profile_graph_readback.py`, remove the deleted `corpus_events` import, `_benchmark_corpus_replay()`, and the `benchmark.shared_general_corpus_projection_response` measurement. Do not otherwise change the profiler's CLI or database/readback measurements.

- [ ] **Step 4: Remove the command and marker, preserving dependencies used elsewhere**

Remove `test-graph-projection-migration` from `.PHONY` and delete its Makefile block. Remove only this pytest marker from `pyproject.toml`:

```toml
"graph_projection_migration: complete tracked-repository graph projection migration contracts",
```

Keep the `slow` and `e2e` markers. Keep `libcst>=1.5` because `scripts/codemods/r04_otel_vocab.py` still imports LibCST; keep PyYAML, Hypothesis, pytest-testmon, and all production dependencies because they remain used. Therefore do not edit `uv.lock` merely to claim dependency cleanup.

- [ ] **Step 5: Update active documentation to the closure contract**

Make these exact content changes:

- `AGENTS.md`: remove the paragraph directing agents to `make test-graph-projection-migration`; document the focused pure behavior/performance files and permanent boundary command instead.
- `docs/ARCHITECTURE.md`: replace inventory/codemod/golden/baseline prose with canonical matrix, every-split replay, model-derived JSON coverage, direct 10,000-event median gate, and permanent boundary hook references.
- `docs/dynamic-graph/graph-projection-map-inventory.md`: keep the current schema-13 representation and query/checkpoint sections; replace “Automation evidence” with the same current executable evidence.
- `tests/fixtures/graph/COVERAGE.md`: replace the migration-oracle row with rows for canonical event behavior (`test_graph_projection_behavior.py`), every-split replay (`test_graph_projection_replay_equivalence.py`), model-derived JSON (`test_graph_projection_flexible_json.py`), and direct performance (`test_graph_projection_performance.py`).

Do not rewrite old dates, commands, or decisions in preserved historical design/plan/complete documents.

- [ ] **Step 6: Run GREEN focused tests and prove retired names are absent from active surfaces**

```bash
uv run pytest \
  tests/unit/test_graph_projection_behavior.py \
  tests/unit/test_graph_projection_flexible_json.py \
  tests/unit/test_graph_projection_replay_equivalence.py \
  tests/unit/test_graph_projection_immutability.py \
  tests/unit/test_graph_projection_queries.py \
  tests/unit/test_graph_projection_duplicate_ids.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_integrity.py \
  tests/unit/test_graph_projection_boundaries.py \
  tests/unit/test_graph_projection_performance.py -q

git grep -n -E 'graph_projection_inventory|migrate_graph_projection_queries|generate_graph_projection_goldens|benchmark_graph_projection|graph_projection_migration|test-graph-projection-migration' -- \
  AGENTS.md Makefile pyproject.toml scripts src tests docs/ARCHITECTURE.md docs/dynamic-graph/graph-projection-map-inventory.md
```

Expected: focused tests pass. `git grep` exits 1 with no matches. Historical docs are deliberately outside this active-surface grep.

- [ ] **Step 7: Commit Task 6**

```bash
git add -A -- \
  AGENTS.md \
  Makefile \
  pyproject.toml \
  scripts/graph_projection_inventory.py \
  scripts/generate_graph_projection_goldens.py \
  scripts/codemods/migrate_graph_projection_queries.py \
  scripts/codemods/graph_projection_manifest.yaml \
  scripts/codemods/graph_projection_query_migration.yaml \
  scripts/benchmark_graph_projection.py \
  scripts/profile_graph_readback.py \
  tests/unit/test_graph_projection_inventory.py \
  tests/unit/test_migrate_graph_projection_queries.py \
  tests/unit/test_graph_projection_migration.py \
  tests/unit/test_graph_projection_goldens.py \
  tests/unit/test_graph_projection_test_speed.py \
  tests/unit/test_benchmark_graph_projection.py \
  tests/unit/test_graph_projection_queries.py \
  tests/integration/test_graph_projection_public_parity.py \
  tests/fixtures/graph_projection_migration \
  tests/fixtures/graph_projection_performance \
  tests/fixtures/graph/COVERAGE.md \
  docs/ARCHITECTURE.md \
  docs/dynamic-graph/graph-projection-map-inventory.md \
  docs/graph-projection-inventory-diagnostics.md
git commit -m "chore(graph): retire projection migration tooling"
```

## Final Verification

- [ ] Run the focused pure projection behavior suite from a fresh command:

```bash
uv run pytest \
  tests/unit/test_graph_projection_behavior.py \
  tests/unit/test_graph_projection_flexible_json.py \
  tests/unit/test_graph_projection_replay_equivalence.py \
  tests/unit/test_graph_projection_immutability.py \
  tests/unit/test_graph_projection_queries.py \
  tests/unit/test_graph_projection_duplicate_ids.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_integrity.py \
  tests/unit/test_graph_projection_boundaries.py \
  tests/unit/test_graph_projection_performance.py
```

- [ ] Run every design-required repository gate freshly and in this order:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run python scripts/check_graph_projection_boundaries.py
uv run pre-commit run --all-files
```

- [ ] Verify retired files/commands are absent and only historical documents retain history:

```bash
test -z "$(git ls-files \
  scripts/graph_projection_inventory.py \
  scripts/generate_graph_projection_goldens.py \
  scripts/codemods/migrate_graph_projection_queries.py \
  scripts/codemods/graph_projection_manifest.yaml \
  scripts/codemods/graph_projection_query_migration.yaml \
  scripts/benchmark_graph_projection.py \
  tests/fixtures/graph_projection_migration \
  tests/fixtures/graph_projection_performance)"

git grep -n -E 'graph_projection_migration|test-graph-projection-migration' -- \
  AGENTS.md Makefile pyproject.toml scripts src tests docs/ARCHITECTURE.md docs/dynamic-graph/graph-projection-map-inventory.md
```

Expected: the `test` command exits 0; `git grep` exits 1 with no active matches.

- [ ] Review the completion contract directly:

1. Matrix equals all 48 canonical event types; its neutral subset equals all 14 explicit neutral types.
2. Malformed neutral payloads raise `ValidationError` before no-op; unsupported names still raise `ValueError`.
3. Every matrix stream passes full, every-split incremental, and every-split checkpoint-tail replay.
4. All 29 model-derived flexible JSON fields cover nested object/array, scalar, and null leaves through event-driven checkpoint round trips.
5. Invalid event, conflicting duplicate, malformed checkpoint, and broken reference each have their expected typed outcome.
6. Earlier generations retain checkpoint data; changed values/groups are replaced; unchanged groups/siblings retain identity.
7. Public query mutation probes cannot alter projection storage or public result contracts.
8. Boundary guard independently enforces frozen reachability, exact storage readers, top-level imports, no legacy root/clone, sole record ownership, and canonical handled-or-neutral coverage.
9. Each direct 10,000-event scenario uses one warmup, three samples, median `< 1.0`, and exact behavior cardinality assertions.
10. Migration-only files, command, marker, fixtures, reports, and historical comparison gate are absent; preserved historical docs remain.

- [ ] Confirm the worktree is clean after all commits and hook execution:

```bash
git status --short
```

Expected: no output. Report completion only from these fresh command results and this direct contract review, never from a migration ledger or generated progress report.
