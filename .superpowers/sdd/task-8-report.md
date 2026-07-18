# Backlog Closeout Task 8 Report

## Status

Steps 1–2 completed on branch `codex/backlog-closeout` at source
`9c0a1ee8f16019df957a785c9b7e87242208f86a`. Step 3 was not run, per the brief;
the fresh full-suite verifier is deferred to the separate no-context agent.

## Exact focused checks

```text
uv run pytest tests/integration/test_graph_read_models.py \
  tests/unit/test_graph_scheduler_view.py tests/integration/test_graph_event_store.py \
  tests/unit/test_cli_agent.py tests/unit/test_graph_commands.py \
  tests/integration/test_graph_decisions_api.py tests/integration/test_cli_approve.py -q -n 0
258 passed in 2.33s

npm --prefix ui test -- src/components/__tests__/GraphPanel.decisions.test.tsx
Test Files  1 passed (1)
Tests       5 passed (5)
```

Refreshed per-surface GREEN counts:

| Surface | GREEN command/count | RED observation and source evidence |
| --- | --- | --- |
| July 4 supersession incident replay | `uv run pytest tests/integration/test_graph_read_models.py::test_july_4_incident_replay_preserves_supersession_and_completion_parity -q -n 0` — `1 passed` | `1 failed` during fixture characterization: sparse `classified_gap.value` produced `node_unfulfilled`, not supersession residue. Baseline `61ed9f5abd55e6578b5928a6d562fec71b88fa08`; test `6796b1a77e5c141eb030971459586ce2f0173fdd`; fixture/review fix `349f4a74808c8a880a4f9495cab4d5276380c105`. |
| Scheduler snapshot parity | `uv run pytest tests/unit/test_graph_scheduler_view.py tests/integration/test_graph_event_store.py -q -n 0` — `25 passed` | `1 failed`: incremental snapshot included ready `max_grants_reached` in `blocked`. Baseline `349f4a74808c8a880a4f9495cab4d5276380c105`; fix `c2aac1e9fd9f428eaccee324a714ba9a18c61018`. |
| Codex CLI argv | `uv run pytest tests/unit/test_cli_agent.py -q -n 0` — `39 passed` | `2 failed, 37 passed`: `--model` appeared before `exec`. Baseline `c2aac1e9fd9f428eaccee324a714ba9a18c61018`; fix `852db41d80a1aed25ac1b8895de0382ae0f6ad77`. |
| Kernel/API human-gate approval | `uv run pytest tests/unit/test_graph_commands.py tests/integration/test_graph_decisions_api.py -q -n 0` — `183 passed` | `2 failed`: worker-target approval was accepted and the typed human actor payload was rejected. Baseline `852db41d80a1aed25ac1b8895de0382ae0f6ad77`; fix `30d2b96c4846b810996fce0a4c186d7508c02c39`. |
| UI human-gate approval | `npm --prefix ui test -- src/components/__tests__/GraphPanel.decisions.test.tsx` — `1 file / 5 tests passed` | Initial `3 failed` because no `Review decision` action existed; focus follow-up `1 failed, 4 passed`. Baselines `30d2b96c4846b810996fce0a4c186d7508c02c39` and `aaa730922afa3ba21387bd447e0189db6054d3fc`; fixes `aaa730922afa3ba21387bd447e0189db6054d3fc` and `64cd469f0f3f8d262cab846625f0db36f27f6c26`. |
| CLI human-gate approval | `uv run pytest tests/integration/test_cli_approve.py -q -n 0` — `4 passed` | Import failure: `_graph_approval_payload` was absent. Baseline `64cd469f0f3f8d262cab846625f0db36f27f6c26`; fix `9c0a1ee8f16019df957a785c9b7e87242208f86a`. |

## Files

- `docs/dynamic-graph/status.md`
- `docs/dynamic-graph/dynamic-graph-implementation-review.html`

Both documents received dated append-only evidence sections; prior history was
preserved. The pre-existing changes to `.superpowers/sdd/progress.md` and
`.superpowers/sdd/task-2-report.md` were not touched.

## Concerns

- The incident RED is a fixture-shape characterization failure and should not be
  described as a production supersession regression.
- Step 3 full-suite, Ruff, Pyright, and diff verification were intentionally not
  run because a separate no-context verifier owns that step.
