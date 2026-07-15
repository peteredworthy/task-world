# Residual Task 2 Report: Canonical Event Ownership And Fixtures

## Status

Completed and committed as `4fdefe14d Canonicalize W5 event names`.

## RED Evidence

Command:

```bash
uv run pytest tests/unit/test_graph_event_registry.py -q
```

Result: collection failed as intended because `CANONICAL_EVENT_TYPES` was not
yet exported from `orchestrator.graph`.

```text
ImportError: cannot import name 'CANONICAL_EVENT_TYPES' from 'orchestrator.graph'
```

## GREEN Evidence

Focused ownership, fixture, projection, and patch-validation checks:

```bash
uv run pytest tests/unit/test_graph_event_registry.py \
  tests/unit/test_fixture_corpus.py \
  tests/unit/test_graph_projections.py \
  tests/unit/test_patch_validator.py -q
```

Result: `189 passed`.

Expanded directly affected coverage after removing alias expectations:

```bash
uv run pytest tests/unit/test_graph_event_registry.py \
  tests/unit/test_fixture_corpus.py \
  tests/unit/test_graph_projections.py \
  tests/unit/test_patch_validator.py \
  tests/unit/test_patch_event_payloads.py \
  tests/unit/test_graph_driver_logic.py \
  tests/unit/test_requirement_evidence_event_payloads.py \
  tests/unit/test_node_lifecycle_event_payloads.py \
  tests/unit/test_graph_planner_packet.py \
  tests/unit/test_graph_api_projection.py \
  tests/integration/test_graph_read_models.py -q
```

Result: `260 passed`.

Commit hooks also passed Ruff, formatting, secret detection, Pyright, the full
pytest hook, module-import enforcement, signal routing, UI lint, and UI
typecheck.

## Changed Files

- Added `src/orchestrator/graph/event_registry.py` with producer-derived
  canonical ownership, explicit `lease_suspended` external ingress, and the
  incremental payload-model mapping.
- Exported registry symbols through `src/orchestrator/graph/__init__.py`.
- Removed replay-only alias consumers from projections, planner prompts, and
  patch validation; environment failures now derive from check-result records.
- Canonicalized graph fixtures and updated affected unit/integration coverage
  to use check-result, requirement-revision, and produced suspect/patch events.
- Added the ownership/fixture guard and recorded evidence in the W5 ledger.

## Self-Review

- Confirmed all specified removed event names have no graph consumer path.
- Confirmed every graph fixture event name is a subset of
  `CANONICAL_EVENT_TYPES`.
- Kept `lease_suspended` as the only external canonical event and retained its
  existing projection/presenter consumers.
- Verified `EVENT_PAYLOAD_MODELS` remains deliberately incomplete, per staged
  payload-task scope.
- Ran `git diff --check`; it passed before commit.

## Concerns

No implementation concerns. The pre-existing, user-owned
`.superpowers/sdd/progress.md` modification was deliberately left uncommitted.
The expensive Batch 1 verifier gates were not independently invoked; commit
hooks supplied the required repository checks.

## Review Fixes (Needs-Fixes Follow-up)

Committed as `2d8bde199 Enforce canonical event ownership`.

- Replaced the uncoupled event-name set with immutable producer metadata.
  `CANONICAL_EVENT_TYPES` derives from that metadata, command-factory and
  runtime-controller emission paths validate their declared producer ownership,
  and scenario command events use their explicit harness producer declaration.
- Added ownership tests for unregistered emission, stale registry entries,
  canonical omissions, and removed names with no producer owner.
- Removed the stale `region_marked_suspect`, `authority_narrowed`, and
  `candidate_superseded` ownership/invalidation entries. The only retained
  suspect event is `plan_region_marked_suspect`.
- Restored authority revision resolution through granted
  `authority_decision_recorded` events. The reducer now obtains the matching
  revision identifier from canonical decision scope (`revision_id`,
  `requirement_version_id`, or `version_id`) or `record_id`, and clears the
  blocker in both full-history and checkpoint-tail replay.

### Follow-up RED/GREEN Evidence

RED initially exposed the absent producer-metadata public API and showed that a
canonical authority decision did not clear a requirement revision blocker.

GREEN:

```bash
uv run pytest tests/unit/test_graph_event_registry.py \
  tests/unit/test_patch_validator.py \
  tests/unit/test_requirement_evidence_event_payloads.py \
  tests/unit/test_graph_projections.py \
  tests/unit/test_fixture_corpus.py -q
```

Result: `201 passed`.

```bash
uv run ruff check src/orchestrator/graph/event_registry.py \
  src/orchestrator/graph/__init__.py src/orchestrator/graph/_commands.py \
  src/orchestrator/graph/patch_validator.py src/orchestrator/graph/projections.py \
  src/orchestrator/graph/scenario.py src/orchestrator/graph_runtime/controller.py \
  tests/unit/test_graph_event_registry.py \
  tests/unit/test_requirement_evidence_event_payloads.py
```

Result: passed.

## Final Retired Event Tombstone Fix

Committed as the follow-up retired-event tombstone fix.

The immutable `RETIRED_EVENT_TYPES` tombstone now contains exactly
`region_marked_suspect`, `authority_narrowed`, and `candidate_superseded`.
Ownership validation rejects any producer declaration or canonical set that
overlaps the tombstones, and validates the current immutable declaration during
module initialization. The tombstone is exported through `orchestrator.graph`
for direct invariant tests.

RED:

```bash
uv run pytest tests/unit/test_graph_event_registry.py tests/unit/test_patch_validator.py -q
```

Result: collection failed because `RETIRED_EVENT_TYPES` was not exported.

GREEN:

```bash
uv run pytest tests/unit/test_graph_event_registry.py tests/unit/test_patch_validator.py -q
```

Result: `63 passed`.

Relevant Ruff:

```bash
uv run ruff check src/orchestrator/graph/event_registry.py \
  src/orchestrator/graph/__init__.py tests/unit/test_graph_event_registry.py
uv run ruff format --check src/orchestrator/graph/event_registry.py \
  src/orchestrator/graph/__init__.py tests/unit/test_graph_event_registry.py
```

Result: both passed; all three files were already formatted.
