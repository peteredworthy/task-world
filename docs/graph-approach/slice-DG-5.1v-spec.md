# Slice DG-5.1v Spec: Compact Graph Event Readback

## Objective

Make completed dynamic graph runs readable by metrics and validation tools even
when callback/file-state events contain very large dependency snapshots.

## Scope

In scope:

- Add a compact graph event API mode that preserves event identity, event type,
  position, and metric-relevant payload fields while omitting large nested
  callback/file-state payloads.
- Keep full `/graph/events` behavior available by default for existing UI/debug
  callers.
- Update `scripts/compare_carriers.py` to use compact event payloads.
- Validate the completed DG-5.1 run can be compared without timing out.

Out of scope:

- Mutating stored graph events.
- Rewriting file-state capture.
- Full five-arm comparison.

## Live Failure Evidence

Run `0c053df6-1702-4d67-94de-628a4e2ee256` completed with final invariant
evidence, but default completed-run readback remained too heavy:

- `/graph/scheduler` timed out at 20 seconds in one probe.
- `/graph` timed out at 30 and 60 seconds.
- `scripts/compare_carriers.py dynamic=0c053df6-1702-4d67-94de-628a4e2ee256`
  timed out fetching `/graph/events`.
- Full graph events included large callback/file-state payloads with ignored
  `.venv` and `ui/node_modules` trees.

## Required Behavior

- `/api/runs/{run_id}/graph/events?payload_mode=summary` returns compact event
  payloads and validates unsupported modes with 422.
- Summary payloads retain fields needed by `compare_carriers.py` dynamic metrics:
  node ids, node kinds/roles/states, patch ids/roles/reasons/op counts,
  verification grades, token metric fields, and final-invariant blocker fields.
- Default `/graph/events` remains full fidelity.
- `compare_carriers.py` uses summary mode for graph events.

## Validation Commands

```bash
uv run pytest tests/integration/test_graph_api.py tests/unit/test_compare_carriers.py -q
uv run ruff check src/orchestrator/api/routers/graph.py scripts/compare_carriers.py tests/integration/test_graph_api.py tests/unit/test_compare_carriers.py
uv run pyright src/orchestrator/api/routers/graph.py scripts/compare_carriers.py tests/integration/test_graph_api.py tests/unit/test_compare_carriers.py
```

Then verify:

```bash
uv run python scripts/compare_carriers.py dynamic=<completed-dg-5.1-run-id>
curl -sS --max-time 20 'http://127.0.0.1:8000/api/runs/<completed-dg-5.1-run-id>/graph/events?payload_mode=summary'
```

## Durable Update

Update `docs/graph-approach/dynamic-graph-operational-plan.md` with validation
and live comparison evidence before moving to DG-5.2.
