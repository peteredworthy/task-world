# Task 6: Immutable Checkpoint Codec Report

## Delivered

- Added temporary public immutable checkpoint codec functions and explicit codec/integrity errors.
- Added a frozen public `ProjectionIntegrityDiagnostic` model; integrity failures contain one sorted tuple of diagnostics.
- Checkpoint writes use JSON-mode Pydantic dumping. Reads structurally validate the exact immutable root, then run pure referential validation with no salvage or repair.
- Reads first reject every non-canonical transport value (including tuple, non-exact mapping, model value, cycle, nonfinite number, non-string key, and over-depth payload) before immutable model conversion.
- JSON checkpoint arrays are frozen to tuples only at the immutable root validation boundary; production checkpoint APIs, store handling, reducer behavior, and schema version remain unchanged.
- Integrity validation covers entity/map-key consistency, replay-owned record-index membership and summaries, topology/endpoints/adjacency/bindings, ready nodes, task and planner relations, candidate/task ownership, verification, governance, requirements, execution, leases, cleanup, and usage-node references. Runtime policy matching is anchored against escaped static patterns, so concrete identifiers may contain dots and brackets without becoming structural separators.
- Oversight decisions now resolve `candidate_id` against their `task_region_id`, and record indexes require exact canonical outer node keys even when an extra represented node has no indexed ports.
- Static runtime patterns are compiled once per dispatcher and indexed by their literal root. The exhaustive matrix reuses one immutable complete projection and applies persistent `model_copy`/`FrozenMap` path updates, preserving public integrity outcomes without repeated checkpoint reconstruction.

## Tests and checks

`uv run pytest tests/unit/test_graph_projection_integrity.py tests/unit/test_graph_projection_codec.py tests/unit/test_graph_projection_models.py tests/unit/test_graph_public_exports.py -q -n 0`

- 358 passed in 5.03s pytest time / 8.02s measured wall time.

Focused Ruff check and format check passed. Focused Pyright passed with 0 errors and 0 warnings.

## Scope confirmation

No production cutover, schema bump, checkpoint-store change, reducer change, or compatibility/defaulting behavior was introduced. The progress ledger was not modified.
