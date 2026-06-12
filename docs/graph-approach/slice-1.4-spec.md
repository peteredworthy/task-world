# Slice 1.4 — Reducers + Projections (loop mode, medium)

Phase 1 slice: implement `reduce_event` and all five pure projection functions so
every scenario in the fixture corpus produces a meaningful `then_projection` result.
No IO. No network. No agent dispatch. Pure deterministic functions operating on
`EventEnvelope` sequences.

Done when: all fixture corpus tests pass (4/4), replay-determinism property test
passes, and every fixture `then_projection` key is satisfied by the real projection
(not stub `{}`).

## Ground truth

`docs/graph-approach/execution-graph-prd-plus.md`:
- §10.1 — run lifecycle states and transitions
- §14 — task projection formula (6 states)
- §15.1–15.5 — node lifecycle states
- §19 — lease states
- §27.2 — invariants (replay-determinism is invariant I-1)

## Scope

### 1. Extend `src/orchestrator/graph/projections.py`

Replace the two stubs with a full implementation:

```python
def reduce_event(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    """Apply one event to a projection snapshot; return new snapshot (immutable)."""

class GraphProjection(TypedDict):
    run_state: str | None           # current run lifecycle state
    node_states: dict[str, str]     # node_id -> NodeState
    task_states: dict[str, str]     # task_region_id -> TaskState (derived)
    leases: dict[str, LeaseRecord]  # lease_id -> current lease record
    ready_nodes: list[str]          # node_ids in state "ready"

def project_run_state(events: list[EventEnvelope]) -> str | None
def project_node_states(events: list[EventEnvelope]) -> dict[str, str]
def project_task_states(events: list[EventEnvelope]) -> dict[str, str]
def project_leases(events: list[EventEnvelope]) -> dict[str, dict]
def project_ready_nodes(events: list[EventEnvelope]) -> list[str]
```

All five projection functions must replay events using `reduce_event`. They share no
mutable state. Each is callable with an empty list and returns a sensible default.

#### Event types to handle

**Run lifecycle** (sets `run_state`):
- `run_created` → `draft`
- `run_queued` → `queued`
- `run_started` → `active`
- `run_pausing` → `pausing`
- `run_paused` → `paused`
- `run_resuming` → `resuming`
- `run_resumed` → `active`
- `run_cancelling` → `cancelling`
- `run_cancelled` → `cancelled`
- `run_completed` → `completed`
- `run_failed` → `failed`

**Node state** (sets `node_states[node_id]`):
- `node_state_changed` payload: `{node_id, from_state, to_state}` → set `node_states[node_id] = to_state`
- `node_created` payload: `{node_id, initial_state?}` → set `node_states[node_id] = initial_state or "planned"`
- Derived: `ready_nodes` = `[nid for nid, s in node_states.items() if s == "ready"]`

**Lease** (sets `leases[lease_id]`):
- `lease_granted` payload: `{lease_id, node_id, generation, ...}` → create lease record with state `active`
- `lease_suspended` payload: `{lease_id}` → set lease state `suspended`
- `lease_revoked` payload: `{lease_id}` → set lease state `revoked`
- `lease_expired` payload: `{lease_id}` → set lease state `expired`
- `lease_released` payload: `{lease_id}` → set lease state `released`

**Task projection** (§14 formula):
- Derived from node states and acceptance events. For v1, implement the formula
  over `task_region_id`:
  - `accepted` if there exists a `verifier_passed` event for the task region and
    all gates for the region are in state `completed`
  - `needs_revision` if latest verifier produced a `verifier_failed` event and no
    `appeal_accepted` event overrides
  - `blocked_invalid_test` if `appeal_accepted` exists with `appeal_type=invalid_test`
    and no subsequent `verifier_passed`
  - `blocked_environment` if latest check event is `check_failed` with
    `failure_category=environment`
  - `in_progress` if any node in the task region has an active lease
  - `pending` otherwise

### 2. `GraphProjection` TypedDict

Define in `projections.py` (do not add to `models.py`). Import existing enums
from `models.py` for string values.

### 3. Property test: replay determinism

Add to `tests/unit/test_graph_projections.py` (new file, 10 tests):

**Replay determinism tests** (3):
- `test_replay_determinism` — build an event list, project twice independently,
  assert equal. Events may include run lifecycle, node state, and lease events.
- `test_empty_projection` — empty event list returns sensible defaults
  (`run_state=None`, `node_states={}`, `leases={}`, `ready_nodes=[]`)
- `test_projection_is_immutable` — `reduce_event` must return a new object; mutating
  the returned state must not affect the input state

**Run lifecycle tests** (2):
- `test_run_state_transitions` — apply 10 run lifecycle events in sequence; assert
  `project_run_state` returns the expected state at each step
- `test_run_state_unknown_event_is_ignored` — unknown event type does not raise or
  change state

**Node state tests** (2):
- `test_node_state_transitions` — node_created + 3 node_state_changed events;
  assert final state
- `test_ready_nodes_derived` — nodes in state "ready" appear in `project_ready_nodes`;
  transitioning one out of ready updates the list

**Lease tests** (2):
- `test_lease_lifecycle` — granted → suspended → revoked sequence; assert final state
- `test_lease_unknown_id_ignored` — `lease_suspended` for unknown lease_id does not raise

**Fixture corpus integration test** (1):
- `test_fixture_corpus_then_projections_satisfied` — re-run all scenarios from
  `tests/fixtures/graph/` that have non-empty `then_projection`; assert
  `result.passed is True` for each. This is the main acceptance gate for 1.4.

Note: some fixture scenarios have `then_projection: {}` or no `then_projection`. Skip
those — only assert the ones with real expectations.

### 4. Update `scenario.py`

Scenario runner currently calls `project_node_states` + `project_task_states` stubs
and merges them. Update to call all five projection functions and return the merged
`GraphProjection` dict as `projection_snapshot`. Maintain backward compat: the
`projection_snapshot` field in `ScenarioResult` remains `dict[str, str]` for simple
key→value assertions in `then_projection`.

Map: flatten `GraphProjection` to `dict[str, str]` for assertion:
- `run_state` → key `"run_state"`
- each `node_states[k]` → key `k`
- each `task_states[k]` → key `k`
- each `leases[lease_id]["state"]` → key `lease_id`

### 5. Update fixture YAMLs (as needed)

If fixture `then_projection` keys don't match what the projections produce, update
the fixtures to use the correct keys and values. The fixtures are the contract — but
they must reflect the PRD, not invention. Document any discrepancy.

## Implementation notes

- Pure functions only. No `datetime.now()`, `random`, filesystem, or network calls.
- `reduce_event` is the canonical single-event step. All projection functions call it.
- `GraphProjection` is immutable in spirit: `reduce_event` returns a new copy.
  Use `copy.copy` or dict spread (`{**state, key: new_val}`) — not in-place mutation.
- Handle `payload` being `None` gracefully (treat as `{}`).
- No recursion depth issues — event lists are short in tests.

## Done when

- `tests/unit/test_graph_projections.py` — all 10 tests pass.
- `tests/unit/test_fixture_corpus.py` — all 4 tests still pass.
- `test_fixture_corpus_then_projections_satisfied` — all fixtures with non-empty
  `then_projection` pass (0 failures).
- `uv run pyright src/orchestrator/graph/` — no errors.
- No imports from `orchestrator.db`, `orchestrator.api`, `orchestrator.runners`.

## Standards

- NO mocks, NO monkeypatching. All tests use real functions.
- `uv run pytest tests/unit/test_graph_projections.py -v` before each commit.
- Regular commits: one per logical unit (core reducer, then projection functions, then
  scenario runner update, then fixture pass).
