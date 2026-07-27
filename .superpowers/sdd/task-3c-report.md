# Task 3c Report: Graph Projection Queries

## Completed scope

- Added public immutable query APIs for output/file-state records and output-port IDs;
  planner generations, successors, patch histories, sessions, carryover, and routine
  snapshots; approval, authority, oversight, and pending decision requests; proposal
  and authority-revision blockers; requirements, support evidence, cleanup, callback
  idempotency, and environment failures.
- Added defensive deep-copy boundaries for payload and model queries, and tuple ID
  boundaries for ordered indexes.
- Replaced approved-core catch-all classification with closed reviewed site keys.
- Reviewed and checked every Task 3c disposition in the strict YAML ledger, added
  independent physical-read assertions for all four target domains, and regenerated
  the inventory diagnostic fixture.

## Inventory result

- Dispositions: 58 `approved_core`, 58 `query_transform`, 65 `projection_neutral`.
- Unclassified Task 3c target sites: 0.
- **Authoritative final deferred inventory:** 349 `test_fixture`; 151
  `verification_recovery`.
- The earlier `321` `test_fixture` count is superseded by the added fixture/query
  inventory below; it is retained only as historical context in prior drafts.

## Verification

- `uv run pytest tests/unit/test_graph_projection_queries.py tests/unit/test_graph_projection_inventory.py tests/unit/test_graph_public_exports.py tests/unit/test_graph_projections.py -q`
  - 251 passed.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed (744 files already formatted).
- `uv run pyright` — 0 errors, 0 warnings, 0 informations.
- `make test` — 4981 passed, 3 skipped, 3 existing aiosqlite datetime-adapter warnings.

## Scope controls

No broad consumer was changed and no codemod was applied. The scratch execution plan
and progress ledger are intentionally excluded from this commit.

## Review-follow-up

- Added `environment_failures()`, returning insertion-ordered immutable tuple pairs
  with independently deep-copied `EnvironmentFailureProjection` values; the keyed
  `environment_failure()` query remains available.
- Strengthened representative-read tests to assert the fresh inventory site tuple
  (path, qualified function, normalized expression, and domain), alongside source
  text assertions.
- Extended positive and isolation coverage for output payloads, approval and authority
  decisions, requirement/support records, cleanup requests, and environment failures.
- Updated closure after the added test inventory: 0 Task 3c target sites remain
  unclassified. The earlier follow-up count is superseded by the authoritative
  final inventory summary above.

## Final blocker closure

- Enriched the shared FR-17 readback fixture with a nondefault planner budget
  (`13`) and a positive latest routine snapshot record.
- Added explicit isolation regressions for oversight decisions, pending decision
  requests, authority-revision blockers, requirement revisions, support evidence,
  keyed environment failures, and the ordered environment-failure collection;
  nested mutable values are deep-copy checked and frozen models reject assignment.
- The Task 3c query-family coverage now also asserts the positive snapshot and
  budget values from the shared fixture while preserving the default/missing cases.

## Final verification

- Focused graph/query, inventory, export, projection, and fixture suites: **252 passed**.
- Public parity and golden suites after regenerating the enriched FR-17 readback: **7 passed**.
- `uv run ruff check .` and `uv run ruff format --check .`: passed.
- `uv run pyright`: 0 errors, 0 warnings, 0 informations.
- `make test`: **4,981 passed, 3 skipped**, with the same 3 aiosqlite datetime-adapter warnings.
