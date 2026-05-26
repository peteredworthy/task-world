# Step 00 — Pydantic Event Conversion

## Purpose

Convert all existing event dataclasses (~20 `WorkflowEvent` subclasses) from
Python `@dataclass` to Pydantic `BaseModel`. This is a preparatory step that
must complete before the main event-sourcing migration begins, because later
steps rely on Pydantic's `model_dump_json()` / `model_validate_json()` for
event serialization into the new SQLite event store.

## Prerequisites / Dependencies

- None. This is the first step in the migration sequence.

## Functional Contract

### Inputs

- Existing `WorkflowEvent` base class and all subclasses (currently Python
  dataclasses) located under `src/orchestrator/`.
- All call sites that construct, serialize, or pattern-match on these events.

### Outputs

- `WorkflowEvent` base and all subclasses are Pydantic `BaseModel` classes.
- All event construction sites use keyword arguments (Pydantic style).
- `model_dump_json()` and `model_validate_json()` round-trip correctly for
  every event type.
- No behavioral changes; all existing tests pass.

### Errors

- Pydantic's stricter validation may surface latent type mismatches in
  existing event payloads (e.g., `None` where a `str` was expected). These
  must be fixed on encounter — they are bugs in the current code, not
  regressions.
- Positional argument usage at construction sites will fail; convert to
  keyword arguments.

## Verification Strategy

1. **Type checking**: `uv run pyright` passes — confirms all construction
   sites and field accesses are type-correct after conversion.
2. **Unit tests**: Add `tests/unit/test_pydantic_events.py` — construct,
   serialize (`model_dump_json`), and deserialize (`model_validate_json`)
   every event type. Assert round-trip fidelity.
3. **Existing test suite**: `uv run pytest` — full suite passes with no
   modifications (or minimal import-path changes).
4. **Manual spot-check**: Verify that JSONL journal entries written by the
   converted events are readable by existing tooling (same JSON shape).

## Deliverables

| Artifact | Location |
|----------|----------|
| Converted `WorkflowEvent` base + subclasses | `src/orchestrator/` (in-place) |
| Pydantic round-trip tests | `tests/unit/test_pydantic_events.py` |
