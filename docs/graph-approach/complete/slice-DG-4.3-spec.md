# Slice DG-4.3 Spec: Comparison Metric Export

## Objective

Make `scripts/compare_carriers.py` export dynamic-graph-specific comparison metrics from the actual graph event stream so the true comparison plan can compare static and dynamic carriers on more than terminal status and token totals.

## Scope

This slice is limited to the comparison exporter and its tests.

In scope:

- Parse real `/api/runs/{run_id}/graph/events` payloads emitted by accepted dynamic graph slices.
- Export compact counts for planner patches, accepted/rejected patches, patch operations, rejection reasons, appended/suspect/superseded regions, gap/blocker findings, proposal decisions, final invariant gate failures, verifier grades, and token usage by node kind when present.
- Keep the CLI output backward compatible for existing summary rows.
- Add deterministic unit coverage using literal event fixtures and pure parsing/aggregation functions.
- Avoid mocks, monkeypatching, and live network in unit tests.

Out of scope:

- Changing graph runtime behavior.
- Changing graph API payload contracts.
- Adding UI panels.
- Running a full comparison campaign.
- Editing historical comparison result documents except durable status notes.

## Required Behavior

`scripts/compare_carriers.py` must:

1. Fetch `/api/runs/{run_id}/graph/events` as an optional source. Missing or malformed graph payloads must leave dynamic metric fields at zero/defaults rather than failing the whole comparison.
2. Prefer exact graph event types and payload keys over fuzzy substring inference.
3. Recognize at least these accepted event forms:
   - `graph_patch_accepted`
   - `graph_patch_rejected`
   - `command_rejected`
   - `verification_passed`
   - `verification_failed`
   - `node_created`
   - `node_state_changed`
   - `node_deferred`
4. Count patch rejection reasons from `graph_patch_rejected.payload.reason` and from structured rejection reason maps/lists if present.
5. Count final invariant gate failures from `command_rejected` events that reject completion because unresolved final invariant blockers remain.
6. Count graph verifier grades from structured requirement-grade payloads, especially verifier payloads with `value.grades`.
7. Count tokens by node kind only when token usage data is present in graph events; do not synthesize token counts.
8. Expose a pure parsing path that tests can call without replacing module globals.

## Verification

Run and record:

```bash
uv run pytest tests/unit/test_compare_carriers.py -q
uv run ruff check scripts/compare_carriers.py tests/unit/test_compare_carriers.py
uv run pyright scripts/compare_carriers.py
rg -n "monkeypatch|MagicMock|patch\\(|vi\\.mock|jest\\.mock" tests/unit/test_compare_carriers.py scripts/compare_carriers.py
```

The no-mocks scan should return no matches, except ordinary non-test text if clearly unrelated.

## Acceptance Evidence

Update `docs/graph-approach/dynamic-graph-operational-plan.md` with:

- run id and runner used,
- files changed,
- validation commands and results,
- remaining risks,
- next selected slice.
