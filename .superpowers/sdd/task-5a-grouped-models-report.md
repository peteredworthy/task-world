# Task 5a: Grouped Immutable Projection Models

## Delivered

- Replaced the placeholder grouped scaffold with the unused, frozen
  `ImmutableGraphProjection` root containing exactly the twelve manifest groups.
- Added explicit node specification, runtime, and scheduling models. Every
  `node_creation_ownership` destination in the canonical manifest is represented
  directly; node payload catch-alls and `NodeSpecProjection.details` are absent.
- Added explicit task, topology, record-store, planning, verification,
  governance, requirements, execution, usage, lifecycle, and supporting value
  models. Secondary record indexes contain only IDs, while `RecordStore.by_id`
  remains the one full-record-payload location for this bounded subtask.
- Added frozen projection counterparts for graph record summaries and final
  invariant blockers.
- Kept the current `ProjectedRecord` union unchanged, as required for Task 5a;
  Task 5b will replace its generic record envelopes.
- Exported the new scaffold groups and supporting projection values from
  `orchestrator.graph`.

## Review-Finding Corrections

- Replaced abbreviated support values with immutable counterparts that retain
  source projection fields, requiredness, literals, and defaults for resource
  claims, candidates, edges, bindings, leases, verification values, requirement
  revisions/support evidence, decisions, callbacks, cleanup requests, planner
  snapshots, and environment failures.
- Edge projections now retain selector, dependency, node-kind/role, purpose,
  selection, binding, freshness, hydration, and metadata facts; `required`
  preserves its canonical `True` default.
- `latest_routine_snapshot` now uses `LatestRoutineSnapshotProjection` with its
  required `record_id`, `producer_node_id`, and `port` identity fields.
- Source list/dict payload children are accepted at the conversion boundary and
  frozen into tuples, `FrozenMap`, or `FrozenJsonValue`; no source transport
  model is stored by reference.

## Contract Coverage

`tests/unit/test_graph_projection_models.py` now verifies:

- exact root-group names and defaults;
- unknown-field rejection and frozen model/map behavior;
- manifest destination ownership derived from the canonical YAML;
- ownership of every retained node-creation fact and absence of a node catch-all;
- recursive annotation reachability checks for mutable containers, `Any`, and
  non-frozen or extra-permitting Pydantic models;
- record-store sole payload ownership and ID-only index shape; and
- public graph-module exports.
- exact legacy-field/manifest ownership coverage, root groups derived from the
  manifest, and source-model compatibility examples for edge, binding,
  candidate, and support-evidence projection values.

## Verification

Executed successfully:

```text
uv run pytest tests/unit/test_graph_projection_models.py tests/unit/test_graph_public_exports.py -q
16 passed in 5.70s

uv run ruff check src/orchestrator/graph/projection_models.py \
  src/orchestrator/graph/__init__.py tests/unit/test_graph_projection_models.py
All checks passed!

uv run pyright src/orchestrator/graph/projection_models.py \
  src/orchestrator/graph/__init__.py
0 errors, 0 warnings, 0 informations
```

## Boundary and Follow-up

Production still uses the old `GraphProjection`; this scaffold remains unused.
No production reducer, checkpoint, query, compatibility, or cutover behavior was
changed. The progress ledger remains intentionally uncommitted. Task 5b owns the
replacement of the temporary projected-record envelope union.
