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

## Automation evidence

- `scripts/graph_projection_inventory.py --check` validates the checked-in
  ownership and source inventory.
- `scripts/check_graph_projection_boundaries.py` enforces the exact five-file
  storage allowlist, public-import boundary, and no legacy projection access.
  It runs as the permanent `graph-projection-boundaries` pre-commit hook.
- `scripts/codemods/migrate_graph_projection_queries.py --assert-clean` checks
  the current 936-site migration closure (historical inventory: 542 sites);
  goldens check query-output parity.
- `tests/fixtures/graph_projection_performance/baseline.json` is the checked-in
  legacy-mapping schema-12 comparison baseline. A measured schema-13 target run
  (two warmups, seven samples, requested sizes 100/1,000/10,000 plus probes)
  passed all hard gates; its subsecond scaling results remain diagnostics under
  the approved rule. Re-run `uv run python scripts/benchmark_graph_projection.py
  --baseline tests/fixtures/graph_projection_performance/baseline.json
  --check-gates` for performance changes. The generated target result is not a
  permanent repository artifact and the benchmark is not a default test gate.
