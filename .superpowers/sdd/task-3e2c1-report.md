# Task 3e2c1 Report

## Status

In progress. Source reanchoring and composition ownership were split into Task
3e2c1a and independently approved. Exact semantic query recipes remain.

## Evidence boundary failure

The approved operation stream contains six reviewed `query_transform` diagnostic
sites whose `MigrationSite.old_field_name` is null and whose
`CstAnchorEvidence.context` is null. Their available structural keys are only
`unsupported_call` with `call` operation shapes.  They therefore do not carry
the manifest old field or stored physical context required to select a public
query API under the task's finite-rule constraint.

The six expressions span distinct fields (`last_deferred_reasons`,
`accepted_graph_patches_by_node`, `callback_idempotency_events`, `node_roles`,
and `file_state_records`). Selecting a recipe for them would require using a
raw source substring, path, function name, or site ID, all forbidden by the
brief. A fail-closed compiler consequently leaves four structural keys,
covering six sites, unmatched.

## Predecessor repair evidence

The collector now derives a reusable physical signature from recognized direct
projection operations and propagates it through an outer diagnostic call only
when its CST descendants contain exactly one distinct signature. The signature
contains the physical receiver expression, old field, access kind, and
operation shape. Zero or multiple descendants continue to produce no context.

The repaired reviewed diagnostic families are:

- `last_deferred_reasons`: two `get` descendants;
- `accepted_graph_patches_by_node`: one `get` descendant;
- `callback_idempotency_events`: one `get` descendant;
- `node_roles`: one `get` descendant; and
- `file_state_records`: one literal-subscript descendant.

A live operation-stream probe reports
`query_transform_missing_context=0`. The checked ledger identities,
disposition counts, and diagnostic artifact remain unchanged; the explicit
migration gate verifies the 201 `query_transform` closure against the fresh
repository inventory.

## Stronger review gate

Every reviewed `query_transform` now requires complete collector-owned receiver
physical context, regardless of whether its `MigrationSite.old_field_name` is
already populated: a nonempty projection expression, receiver role, physical
old field, access kind, and operation shape. The live pre-gate probe found zero
occurrence or diagnostic families missing those facts, so no additional
collector family repair was required.

The compiler enforces the same pure guard while planning reviewed dispositions.
A focused synthetic occurrence test removes the otherwise valid context and
proves refusal without repository setup. The multiple-descendant collector test
now identifies the normalized outer call expression explicitly rather than
selecting the first call diagnostic.

## Checks run

- Focused RED/GREEN collector tests cover the five field families and a
  multiple-descendant fail-closed case.
- `uv run pytest tests/unit/test_graph_projection_inventory.py
  tests/unit/test_migrate_graph_projection_queries.py -v` — 150 passed.
- `make test-graph-projection-migration` — 9 passed (the explicit gate was run
  once).
- Stronger pure guard and focused collector/codemod suite — 151 passed.

## Composition predecessor

Task 3e2c1a now provides shared occurrence/diagnostic reanchoring and 187
nonoverlapping outer CST actions consuming all 201 reviewed IDs. The remaining
scope is a finite field/access recipe registry and exact in-memory replacement
expressions; no source-writing behavior is implemented yet.
