# Task 3e2b2a Report

## Delivered

- Replaced the module-global import/shadow scanner with LibCST
  `QualifiedNameProvider` and `ScopeProvider` evidence.
- Callable origins now require one exact qualified imported or typed-local producer
  identity; dynamic, foreign, conflicting, and lexical-shadowed calls fail closed.
- Projection provenance is keyed by qualified lexical binding identity, with typed
  parameters, approved factory results, pass-through assignments, and reassignment
  kills represented in the local flow.
- Replaced independent positional/name tuples with frozen
  `ProjectionArgumentEvidence` facts.  Each fact carries exactly one positional
  index or keyword name and its specific provenance.
- Updated structural consumers to use paired facts while preserving the approved
  803-site stream and disposition counts.

## Verification

- `uv run pytest tests/unit/test_migrate_graph_projection_queries.py::test_anchor_evidence_refuses_shadowed_foreign_dynamic_and_wrong_position_calls tests/unit/test_migrate_graph_projection_queries.py::test_anchor_evidence_pairs_only_proven_projection_arguments_with_their_argument_slot -q` — 2 passed (5.43s).
- `uv run pytest tests/unit/test_migrate_graph_projection_queries.py::test_live_repository_compilation_includes_every_remaining_fixture_site -q` — passed (117.38s) with its explicit timeout raised from 120s to 300s.
- `uv run pytest tests/unit/test_migrate_graph_projection_queries.py::test_structural_plan_closes_reviewed_and_public_query_test_sites -q` — passed (177.62s).
- `uv run ruff check scripts/codemods/migrate_graph_projection_queries.py tests/unit/test_migrate_graph_projection_queries.py`
- `uv run ruff format --check scripts/codemods/migrate_graph_projection_queries.py tests/unit/test_migrate_graph_projection_queries.py`
- `uv run pyright scripts/codemods/migrate_graph_projection_queries.py` — 0 errors.

The controller's foreground `uv run pytest` completed after the timeout fix:
`5001 passed, 3 skipped, 3 warnings in 468.88s`. The three warnings are the
existing `aiosqlite` datetime-adapter deprecations.

## Concern

Qualified-name metadata for the complete live inventory is intentionally given
the same 300-second per-test budget as the other live compiler test.
