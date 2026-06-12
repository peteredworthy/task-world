# Slice 1.5 — Readiness + Scheduler (loop mode, medium)

Phase 1 slice: implement `evaluate_readiness` and `schedule` as pure deterministic
functions with tie-break ordering per §17–§18. No IO. No agent dispatch. The
scheduler must explain every ready/deferred decision in its output.

Done when: all 12 readiness+scheduler tests pass; scheduler decision includes
`selected` and `deferred` with per-node reasons; resource conflict matrix tests
cover every cell of §18 that is testable without live paths (write/read/external).

## Ground truth

`docs/graph-approach/execution-graph-prd-plus.md`:
- §17 — Readiness and scheduling (readiness criteria, tie-break order)
- §18 — Resource and parallelism policy (conflict matrix)

## Scope

### 1. Create `src/orchestrator/graph/scheduler.py`

#### Data structures

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class ResourceClaim:
    mode: str           # "read" | "write" | "graph_write" | "review_write" | "external"
    scope: str          # "repo" | "snapshot" | ...
    paths: list[str] = field(default_factory=list)
    snapshot_id: str | None = None
    external_resource_key: str | None = None
    exclusive: bool = False

@dataclass(frozen=True)
class NodeScheduleInfo:
    node_id: str
    kind: str           # worker | verifier | check | gate | planner | ...
    state: str          # planned | blocked | ready | ...
    priority: int = 0   # explicit priority; higher = earlier
    region_order: int = 0   # graph region position; lower = earlier
    creation_position: int = 0  # event position when node was created
    resource_claims: list[ResourceClaim] = field(default_factory=list)

@dataclass(frozen=True)
class SchedulingDecision:
    projection_position: int    # event log position used for this decision
    candidates: list[str]       # node_ids in tie-break order (ready nodes)
    selected: list[str]         # node_ids to grant leases
    deferred: list[str]         # ready nodes not selected this tick
    deferred_reasons: dict[str, str]  # node_id -> reason string
```

#### `evaluate_readiness`

```python
def evaluate_readiness(
    node: NodeScheduleInfo,
    run_lifecycle_state: str,
    active_lease_node_ids: set[str],
    claimed_resources: list[tuple[str, ResourceClaim]],  # (node_id, claim) of active leases
) -> tuple[bool, str]:
    """Return (is_ready, reason). reason is '' when ready, explanation when not."""
```

Rules (§17):
1. Run lifecycle must be `active` — else `("run not active", ...)`
2. Node state must be `planned` or `blocked` — else not eligible
3. Node must not already have an active lease (`node_id in active_lease_node_ids`)
4. No resource conflict with existing active leases (see conflict matrix below)
5. Node state `retired` or `cancelled` → never ready

Returns `(True, "")` when all rules pass.

#### `schedule`

```python
def schedule(
    nodes: list[NodeScheduleInfo],
    run_lifecycle_state: str,
    active_leases: list[tuple[str, ResourceClaim]],  # (node_id, claim) currently active
    projection_position: int,
    max_grants: int = 10,
) -> SchedulingDecision:
```

Algorithm:
1. Filter to nodes with state `ready` (evaluate_readiness was applied upstream, or filter
   `planned`/`blocked` nodes where evaluate_readiness returns True).
   For slice 1.5, accept nodes in state `ready` as pre-evaluated.
2. Sort by tie-break order: `(-priority, region_order, creation_position, node_id)`.
3. Greedily select nodes: for each candidate in order, check if its resource claims
   conflict with already-selected claims. If no conflict → select; else → defer.
4. Return `SchedulingDecision` with full candidate list (sorted), selected, deferred,
   and reasons.

#### Resource conflict check

```python
def claims_conflict(
    existing: ResourceClaim,
    requested: ResourceClaim,
) -> bool:
```

Implement §18 conflict matrix for v1 (simplified — no live path globbing):

| existing \ requested | read | write | graph_write | review_write | external |
|---|---|---|---|---|---|
| read | False (compatible) | True | False | True | ext_conflict |
| write | True | True | False | True | ext_conflict |
| graph_write | False | False | True | False | False |
| review_write | True | True | False | True | ext_conflict |
| external | ext_conflict | ext_conflict | False | ext_conflict | ext_conflict if same key and either writes |

`ext_conflict`: True only if `existing.exclusive or requested.exclusive or (existing.mode=='write' or requested.mode=='write')` AND both are `external` with the same `external_resource_key`.

For path overlap (read vs write): True if `scope == "repo"` and paths overlap OR both have empty paths (meaning "all paths"). Path overlap check: if either side has `paths == []` treat as `["**"]` (whole repo). For v1, two `paths` lists overlap if they are both non-empty and share any element (no glob expansion — exact match suffices for tests).

### 2. `tests/unit/test_scheduler.py` — 12 tests, no mocks

**Readiness tests** (5):

- `test_evaluate_readiness_basic` — active run, planned node, no leases → ready
- `test_evaluate_readiness_run_not_active` — run in `paused` state → not ready
- `test_evaluate_readiness_already_leased` — node_id in active leases → not ready
- `test_evaluate_readiness_resource_conflict` — write claim conflicts with existing write → not ready
- `test_evaluate_readiness_read_read_compatible` — two read claims → both ready

**Scheduler tie-break tests** (3):

- `test_schedule_empty` — no ready nodes → empty selected and deferred
- `test_schedule_tie_break_priority` — two ready nodes with different priorities; higher priority selected first
- `test_schedule_tie_break_node_id` — two ready nodes, same priority/region/position; lexically first node_id selected first

**Resource conflict tests** (3):

- `test_claims_write_write_conflict` — two write/repo claims conflict
- `test_claims_read_write_conflict` — read/repo vs write/repo conflict
- `test_claims_read_read_compatible` — two read/repo with same snapshot_id compatible
- `test_claims_graph_write_not_conflict_with_write` — graph_write + write → compatible (per matrix)

Wait, that's 4. Use:
- `test_claims_write_write_conflict`
- `test_claims_read_write_conflict`
- `test_claims_read_read_compatible`

**Decision shape test** (1):

- `test_schedule_decision_has_deferred_reasons` — schedule 3 nodes where resource conflict defers 1; assert `deferred_reasons` has entry for deferred node with non-empty reason string

**Integration test** (0 additional — covered by fixture corpus integration):

**Total: 12 tests.**

### 3. Add readiness fixtures to `tests/fixtures/graph/readiness.yaml`

8 scenarios in §27.3 format that the existing harness can run. These scenarios use
`node_state_changed` events to set nodes to `ready`, then `when_command: null`, and
`then_projection` asserting the node is in state `ready`. They verify the projection
round-trip — not the scheduler function itself (that's in test_scheduler.py).

Scenarios:
- `readiness_single_node_planned_to_ready`
- `readiness_blocked_node_becomes_ready`
- `readiness_multiple_nodes_independent`
- `readiness_write_node_blocked_by_active_write`
- `readiness_read_node_compatible_with_read`
- `readiness_gate_blocked_until_input`
- `readiness_retired_node_not_eligible`
- `readiness_run_not_active_no_scheduling`

Add these to COVERAGE.md under a new `§17 readiness` section.

### 4. Update `tests/unit/test_fixture_corpus.py`

No changes needed — it auto-discovers all YAML files in `tests/fixtures/graph/`.
The new `readiness.yaml` will be picked up automatically.

## Implementation notes

- `scheduler.py` is a pure module: no imports from `orchestrator.db`, `orchestrator.api`,
  `orchestrator.runners`, or `orchestrator.config`.
- `NodeScheduleInfo` is a plain dataclass — no SQLAlchemy, no Pydantic.
- `claims_conflict` is a free function; call it from both `evaluate_readiness` and
  the `schedule` greedy loop.
- Deferred reason strings: use terse format like `"resource_conflict:write/write"`,
  `"run_not_active"`, `"already_leased"`.
- `schedule` accepts `nodes: list[NodeScheduleInfo]` already filtered to candidates;
  for v1 pass nodes with state `ready` — the readiness evaluation is upstream.
- No globbing library needed — exact path list intersection suffices for tests.

## Done when

- `tests/unit/test_scheduler.py` — all 12 tests pass.
- `tests/unit/test_fixture_corpus.py` — all 4 tests still pass (readiness.yaml included).
- `uv run pyright src/orchestrator/graph/` — no errors.
- No forbidden imports.
- `SchedulingDecision.deferred_reasons` always populated for every deferred node.
