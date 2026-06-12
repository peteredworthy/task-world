# Slice 1.2 — Fixture Harness (loop mode, small)

Phase 1 slice: a scenario runner for the §27.3 fixture format. The harness
makes fixtures executable — it loads YAML, replays events through an in-memory
event store, applies a when_command, and asserts then_events and then_projection.
Done when one hand-written scenario executes end-to-end and fails for the right
reason (i.e. a bad fixture is caught, not silently ignored).

## Ground truth

- `docs/graph-approach/execution-graph-prd-plus.md` §27.3 (fixture format),
  §27.5 (test boundaries), §14 (projection rules), §15 (node lifecycle)
- `src/orchestrator/graph/models.py` — the Pydantic models from slice 1.1

## Scope

### 1. In-memory event store

`src/orchestrator/graph/store.py` — `InMemoryEventStore`:
- `append(event: EventEnvelope) -> EventEnvelope` — assigns next position,
  validates `(run_id, position)` uniqueness, raises `DuplicateEventError` on
  conflict.
- `read_from(run_id: str, from_position: int = 0) -> list[EventEnvelope]`
- `snapshot_position(run_id: str) -> int` — highest committed position, or -1

### 2. Injected clock + ID generator

`src/orchestrator/graph/clock.py`:
- `FakeClock` — `now() -> datetime`, `advance(seconds: float)`; starts at a
  fixed epoch (e.g. `2026-01-01T00:00:00Z`).
- `SequentialIdGenerator` — `next_id(prefix: str = "") -> str`; yields
  `{prefix}-1`, `{prefix}-2`, … deterministically.

### 3. Scenario runner

`src/orchestrator/graph/scenario.py` — `ScenarioRunner`:

```python
@dataclass
class ScenarioResult:
    scenario_name: str
    passed: bool
    events_produced: list[EventEnvelope]
    projection_snapshot: dict
    failures: list[str]  # human-readable failure reasons

def run_scenario(scenario: dict, store: InMemoryEventStore, ...) -> ScenarioResult
```

The runner:
1. Parses `given_events` — constructs minimal `EventEnvelope` objects (using
   the given payload dict, injected IDs/clock, assigned sequential positions)
   and appends them to the store.
2. Dispatches `when_command` — for v1 this just records the command as an event
   (full command handling is slice 1.4+). The runner must record that the
   command was received without silently succeeding.
3. Reads back `then_events` — for each expected event type in `then_events`,
   checks that at least one event with that `event_type` exists in the store
   after the given_events position. If `then_events` item is a dict with
   payload fields, those fields must match.
4. Checks `then_projection` — calls the projection stub (see below) and asserts
   the projected values match.

**Fail loudly**: missing expected events or mismatched projection values must
appear in `ScenarioResult.failures`, not silently pass.

### 4. Minimal projection stub

`src/orchestrator/graph/projections.py` — enough to make one scenario work:
- `project_node_states(events: list[EventEnvelope]) -> dict[str, str]`
  — replays `node_state_changed` events to build `{node_id: state}` mapping.
- `project_task_states(events: list[EventEnvelope]) -> dict[str, str]`
  — for v1: returns empty dict (task projection is slice 1.4). Acceptable to
  return a stub that always matches if `then_projection` keys are not yet
  implemented — but the match failure must be visible in failures if a key
  is present but the stub can't resolve it.

### 5. Hand-written scenario (the "fails for the right reason" test)

`tests/unit/test_scenario_harness.py`:

- `test_scenario_with_all_expected_events_passes` — a scenario whose
  `then_events` are all present in the store after given+command; asserts
  `result.passed is True` and `result.failures == []`.
- `test_scenario_detects_missing_then_event` — `then_events` lists an event
  type that was never appended; asserts `result.passed is False` and
  `result.failures` mentions the missing event type.
- `test_scenario_detects_wrong_payload_in_then_event` — `then_events` has a
  dict with a field that doesn't match; asserts failure is detected.
- `test_fake_clock_advances` — `FakeClock.advance(60)` moves time forward.
- `test_sequential_id_generator` — yields `"pfx-1"`, `"pfx-2"` deterministically.
- `test_in_memory_store_append_and_read` — append two events, read_from(0)
  returns both; read_from(1) returns only the second.
- `test_duplicate_event_raises` — duplicate `(run_id, position)` raises
  `DuplicateEventError`.

7 tests total. No mocks, no IO, no app imports.

## Done when

All 7 tests pass. One real §27.3-format scenario (the one in test 1) runs
end-to-end through the harness and produces a `ScenarioResult`. Missing events
cause visible failures (tests 2–3 confirm this).

## Standards

- Pure Python + Pydantic v2. No IO, no DB, no app layer imports.
- `src/orchestrator/graph/` only imports from itself and stdlib/pydantic.
- NO mocks, NO monkeypatching. All tests use the real harness classes.
- Regular commits; run `uv run pytest tests/unit/test_scenario_harness.py -v`
  before each commit.
