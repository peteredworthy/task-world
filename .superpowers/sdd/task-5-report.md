# Backlog Closeout Task 5 Report

## Status

Implemented symmetric approval target validation in the graph kernel and API
product-path coverage for durable human-gate approval, lease release, and
successor readiness.

## Files

- `src/orchestrator/graph/_commands.py`
- `tests/unit/test_graph_commands.py`
- `tests/integration/test_graph_decisions_api.py`

## Test-driven evidence

RED run:

```text
uv run pytest tests/unit/test_graph_commands.py::test_record_decision_rejects_approval_for_non_gate_target tests/integration/test_graph_decisions_api.py::test_record_approval_decision_is_durable_and_releases_waiting_successor -q
2 failed
```

The worker-target approval emitted an approval decision instead of
`command_rejected`. The exact human decider payload with a role also exposed
that the existing typed decision record accepts only the decision actor's kind
and ID.

GREEN run:

```text
uv run pytest tests/unit/test_graph_commands.py tests/integration/test_graph_decisions_api.py -q
183 passed
```

## Verification

```text
uv run ruff check src/orchestrator/graph/_commands.py tests/unit/test_graph_commands.py tests/integration/test_graph_decisions_api.py
All checks passed!

uv run pyright
0 errors, 0 warnings, 0 informations

git diff --check -- src/orchestrator/graph/_commands.py tests/unit/test_graph_commands.py tests/integration/test_graph_decisions_api.py
passed with no output
```

## Self-review

- Approval target validation mirrors the existing authority target validation
  and remains inside `_apply_record_decision` before event creation.
- Existing terminal-target, terminal-run, and Pydantic request validation are
  unchanged.
- Human actor payloads are reduced to the existing `DecisionActor` fields for
  typed decision records; no decision schemas were duplicated or broadened.
- The API test uses real event storage and shared integration fixtures, proving
  durable approval readback, pending-gate removal, lease release, input binding,
  and successor readiness without mocks.
- The non-gate API rejection returns 409 and leaves node and lease state
  unchanged.
- Pre-existing `.superpowers/sdd/progress.md` and `task-2-report.md` changes were
  not included in the task diff.

## Concerns

None identified within the requested scope.
