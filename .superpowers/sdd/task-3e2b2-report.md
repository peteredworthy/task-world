# Task 3e2b2 Report: Structural Neutral And Approved-Core Planning

## Result

Implemented structural operation-anchor evidence and a fail-closed unchanged-disposition plan.
The live closure test derives the required partition: 201 query transforms, 80 approved-core
operations, 173 projection-neutral operations (73 reviewed plus 100 generated), 349 deferred
fixtures, and no pending sites.

## Structural rules

- Imported public `orchestrator.graph` callable origins are matched only with an explicit approved
  projection argument position/name, or structurally proven nested projection provenance.
- The finite nonzero-position registry covers `validate_callback`, `validate_patch`, and
  `final_invariant_blockers_for_events`.
- Typed `GraphProjection` bindings, trusted projector results, local functions with an exact
  `GraphProjection` return annotation, and direct typed pass-through assignments are proven from
  CST facts.
- Projector-backed fixture-flow operations are accepted structurally. Shadowed, foreign,
  dynamic, and wrong-position call forms have no matching origin/projection evidence.
- Approved core remains constrained to the five existing storage files and rejects a public-call
  anchor in place of a physical storage operation.

## Machine-derived counts

| Partition | Count |
| --- | ---: |
| `query_transform` | 201 |
| `approved_core` | 80 |
| `projection_neutral` | 173 |
| deferred `test_fixture` | 349 |
| pending/unmatched | 0 |
| total | 803 |

## Verification

- `uv run pytest tests/unit/test_migrate_graph_projection_queries.py::test_structural_plan_closes_reviewed_and_public_query_test_sites -q` — passed (1 passed, 146.43s).
- `uv run pytest tests/unit/test_migrate_graph_projection_queries.py::test_anchor_evidence_refuses_shadowed_foreign_dynamic_and_wrong_position_calls -q` — passed (1 passed, 4.03s).
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed.
- `uv run pyright` — passed (0 errors, 0 warnings).
- `uv run pytest` — passed: `5000 passed, 3 skipped, 3 warnings in 407.83s`.

## Files changed

- `scripts/codemods/migrate_graph_projection_queries.py`
- `tests/unit/test_migrate_graph_projection_queries.py`
- `.superpowers/sdd/task-3e2b2-report.md`

## Self-review

No inventory identities, checked ledger entries, source consumers, or source imports were changed.
The operation stream remains read-only; all classifications use anchor evidence rather than site,
path, function, or source-text policy.
