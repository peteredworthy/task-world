# Slice 1.6 — Lease & Callback Validation (loop mode, small)

Phase 1 slice: implement `validate_callback` — a pure function that applies the §19
stale callback matrix. All 9 stale cases must be detectable from the event log alone.
No IO. No network. No agent dispatch.

Done when: all 9 stale callback cases from `tests/fixtures/graph/stale_callbacks.yaml`
pass; duplicate-key idempotency conflict cases are covered.

## Ground truth

`docs/graph-approach/execution-graph-prd-plus.md` §19 — Lease and Callback Semantics:

| Callback Case | Required Outcome |
|---|---|
| Duplicate callback with same idempotency key and same payload | Return prior accepted/rejected result. |
| Duplicate callback with same key and different payload | Reject as idempotency conflict. |
| Callback for revoked lease | Append `callback_rejected_stale`; do not change node outcome. |
| Callback for old lease generation | Append `callback_rejected_stale`; do not change node outcome. |
| Success after node already retried | Reject stale; retry node remains authoritative. |
| Failure after node completed | Reject stale unless output-log-only and non-mutating. |
| Approval after cancellation | Reject; cancellation terminal state wins. |
| Resume after cancel | Reject; cancel is terminal. |
| Pause and callback race | Event position decides. If callback accepted first, pause applies after boundary. If pause accepted first and lease revoked/suspended, callback is stale. |

## Scope

### 1. Create `src/orchestrator/graph/callbacks.py`

#### Data structures

```python
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class CallbackRequest:
    run_id: str
    node_id: str
    execution_id: str
    lease_id: str
    lease_generation: int
    base_snapshot_id: str
    observed_graph_position: int
    idempotency_key: str
    payload: dict[str, Any] | None = None
    is_mutating: bool = True

class CallbackOutcome(str):
    ACCEPTED = "accepted"
    REJECTED_STALE = "rejected_stale"
    REJECTED_IDEMPOTENCY_CONFLICT = "rejected_idempotency_conflict"
    DUPLICATE_IDEMPOTENT = "duplicate_idempotent"  # return prior result

@dataclass(frozen=True)
class CallbackValidationResult:
    outcome: str   # one of CallbackOutcome values
    reason: str    # terse reason string
    prior_result: dict[str, Any] | None = None  # for DUPLICATE_IDEMPOTENT case
```

#### `validate_callback`

```python
def validate_callback(
    request: CallbackRequest,
    projection: GraphProjection,           # from projections.py
    events: list[EventEnvelope],           # full event log for the run
) -> CallbackValidationResult:
```

Algorithm — apply §19 matrix in order:

1. **Idempotency check** — scan events for a prior `callback_accepted` or
   `callback_rejected_*` event with the same `idempotency_key`:
   - If found with identical payload → `DUPLICATE_IDEMPOTENT` with `prior_result`
   - If found with different payload → `REJECTED_IDEMPOTENCY_CONFLICT`

2. **Lease state check** — look up `projection.leases[request.lease_id]`:
   - If not found → `REJECTED_STALE` ("unknown lease")
   - If state is `revoked` → `REJECTED_STALE` ("lease revoked")
   - If state is `expired` → `REJECTED_STALE` ("lease expired")
   - If state is `suspended` and `request.is_mutating` → `REJECTED_STALE` ("lease suspended, callback is mutating")
   - If state is `released` → `DUPLICATE_IDEMPOTENT` if idempotency key matches prior; else `REJECTED_STALE`

3. **Generation check** — look up `lease.generation` vs `request.lease_generation`:
   - If `request.lease_generation < lease.generation` → `REJECTED_STALE` ("old generation")

4. **Node state check** — look up `projection.node_states[request.node_id]`:
   - Node in terminal state (`completed`, `failed`, `cancelled`, `retired`) → `REJECTED_STALE` ("node terminal")
   - Exception: if `is_mutating=False`, allow non-mutating callbacks on `completed`/`failed` nodes

5. **Run lifecycle check** — `projection.run_state`:
   - `cancelled` → `REJECTED_STALE` ("run cancelled")

6. If all checks pass → `ACCEPTED`

### 2. `tests/unit/test_callbacks.py` — 14 tests, no mocks

**Basic acceptance** (1):
- `test_callback_accepted` — active lease, correct generation, active run → accepted

**Idempotency tests** (3):
- `test_duplicate_same_payload_returns_prior` — same key + same payload → duplicate_idempotent
- `test_duplicate_different_payload_rejected` — same key + different payload → rejected_idempotency_conflict
- `test_first_callback_not_duplicate` — no prior events → not duplicate

**Lease state tests** (4):
- `test_revoked_lease_rejected` — lease state revoked → rejected_stale
- `test_expired_lease_rejected` — lease state expired → rejected_stale
- `test_suspended_lease_mutating_rejected` — suspended + is_mutating=True → rejected_stale
- `test_suspended_lease_nonmutating_accepted` — suspended + is_mutating=False → accepted

**Generation test** (1):
- `test_old_generation_rejected` — request.lease_generation < current → rejected_stale

**Node/run state tests** (3):
- `test_node_terminal_rejected` — node in completed state → rejected_stale
- `test_run_cancelled_rejected` — run_state=cancelled → rejected_stale
- `test_nonmutating_on_completed_node_accepted` — is_mutating=False, node=completed → accepted

**Race condition test** (2):
- `test_pause_before_callback_stale` — lease_suspended event at lower position than callback → stale
- `test_callback_before_pause_accepted` — no suspend event, lease active → accepted

**Total: 14 tests.**

### 3. Update `tests/fixtures/graph/stale_callbacks.yaml`

The 9 existing scenarios already have the right structure. Ensure each has a
`then_projection` or `then_events` that the callback validator logic can satisfy.
The fixture harness (via `run_scenario`) will exercise these through event replay.

No structural changes to the YAML should be needed — the existing scenarios exercise
the event types. The `validate_callback` function is tested directly in
`test_callbacks.py`, not via the fixture harness (fixtures test event projection,
not the callback validator directly).

### 4. Export from `src/orchestrator/graph/__init__.py`

Add exports:
```python
from orchestrator.graph.callbacks import (
    CallbackRequest,
    CallbackOutcome,
    CallbackValidationResult,
    validate_callback,
)
```

## Implementation notes

- `validate_callback` is pure: takes projection snapshot + event list, returns result.
  No mutation, no IO.
- Scan events in reverse to find the most recent callback events (idempotency check).
- `prior_result` in `CallbackValidationResult` should be a dict with `outcome` and
  any payload from the prior accepted/rejected event.
- `CallbackOutcome` values are plain string constants — no Enum needed.
- `GraphProjection` import: `from orchestrator.graph.projections import GraphProjection`
- `EventEnvelope` import: `from orchestrator.graph.models import EventEnvelope`

## Done when

- `tests/unit/test_callbacks.py` — all 14 tests pass.
- `tests/unit/test_fixture_corpus.py` — all 4 tests still pass.
- `uv run pyright src/orchestrator/graph/` — no errors.
- No forbidden imports.
