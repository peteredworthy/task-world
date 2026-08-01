# Immutable GraphProjection Inventory

## Current representation

`GraphProjection` is schema 13 and has twelve frozen groups: `lifecycle`,
`nodes`, `tasks`, `topology`, `records`, `scheduling`, `planning`,
`verification`, `governance`, `requirements`, `execution`, and `usage`.
`FrozenMap` owns every dynamic index and tuples own ordered values. Every
reachable projection Pydantic model inherits the frozen `ProjectionModel`;
open JSON is recursively frozen to `FrozenMap` and tuples before it enters the
projection.

| Concern | Owner and policy |
|---|---|
| Full records | `records.by_id` is the only full projected-record store. Other indexes contain record IDs or summaries. |
| Nodes and tasks | `nodes` and `tasks` own immutable entity values; scheduling/planning indexes refer to them by ID. |
| Topology and execution | `topology` owns edges and input bindings; `execution` owns leases, callbacks, cleanup, and authoritative runtime facts. |
| Verification, governance, requirements, usage | Each group owns its typed facts and identifier indexes; public views are constructed by queries. |

## Query and checkpoint boundaries

Only `projection_models.py`, `projection_collections.py`,
`projection_queries.py`, `projection_codec.py`, and `projections.py` may access
grouped storage. Consumers import public types and query functions through
`orchestrator.graph`; queries return immutable values or fresh public copies.

Checkpoints are disposable. `projection_codec.py` validates their structure and
relationships; graph runtime accepts only schema 13. Missing, malformed, or
version-mismatched checkpoints are rebuilt from durable events.

## Current executable evidence

- `test_graph_projection_behavior.py` covers the canonical event matrix,
  including every explicit neutral event.
- `test_graph_projection_replay_equivalence.py` covers full replay,
  every-split incremental replay, and every-split checkpoint-tail replay.
- `test_graph_projection_flexible_json.py` covers all model-derived flexible
  JSON fields through event-driven checkpoint round trips.
- `test_graph_projection_performance.py` is the direct gate: each 10,000-event
  scenario uses one warmup and three samples, asserts exact behavior cardinality,
  and requires a median below one second.
- `scripts/check_graph_projection_boundaries.py` enforces the exact five-file
  storage allowlist, public-import boundary, and no legacy projection access.
  It runs as the permanent `graph-projection-boundaries` pre-commit hook.
