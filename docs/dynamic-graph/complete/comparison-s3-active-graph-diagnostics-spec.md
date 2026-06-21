# Scenario S3: Active Graph Diagnostics Snapshot

## Purpose

Build a user-facing diagnostic view for active or stuck graph-backed runs. The
operator should be able to answer: what is blocking this dynamic graph run, which
node owns the evidence, and can I inspect it without loading raw prompt-scale
payloads?

This is a comparison candidate because it couples backend graph read models,
activity summaries, scheduler and lease state, node detail, file-state evidence,
UI rendering, and performance constraints.

## User-Facing Behavior

On a graph-backed run, the Graph panel exposes a compact "Graph health" snapshot:
run state, ready/blocked/waiting counts, active/suspended/expired leases,
failed-node reasons, final-invariant blockers, recent patch decisions, verifier
pass/fail counts, and pending human gates. Selecting a blocker or node opens
node detail with inputs, summarized outputs, file-state evidence, callback
history, and diff links. Default views must not expose raw prompts, heavy output
bodies, or full event payloads.

## Requirements

1. Show a graph health summary, backed by
   `GET /api/runs/{run_id}/graph/health`, that combines projection, scheduler,
   decision, activity, and node-detail facts into one operator-readable status.
2. Surface expired active leases as explicit failed-node/blocker evidence,
   including node id and `lease_expired_without_callback`.
3. Keep default graph readback bounded: events and node detail use summary
   payloads by default; full payloads require explicit opt-in.
4. Preserve causal drilldown from a health blocker to the responsible node,
   including input ports, output summaries, file-state classification, and
   callback history.
5. Keep activity summaries coherent with the health counts for accepted/rejected
   patches, verifier results, command rejections, and final-invariant blockers.
6. Survive stale or deleted disposable read models by rebuilding summaries and
   projections while returning the same operator facts.
7. Add deterministic performance/readback coverage using a heavy synthetic graph
   stream; no live LLM, no live server, and no direct production DB mutation.
8. Export comparison metrics needed for A/C/E scoring: hidden-oracle result,
   requirement count, stale evidence count, corrective work, final blockers,
   patch counts, retries, cost, tool calls, and elapsed time.

## Repo-State Discovery Before Implementation

Before editing, inspect these surfaces and record what was found:

- `src/orchestrator/api/routers/graph.py` for graph projection, events,
  scheduler, decisions, file-state, and node-detail contracts.
- `src/orchestrator/graph_runtime/store.py`, graph read-model tests, and
  migrations for summary/projection/node-detail rebuild behavior.
- `tests/integration/test_graph_api.py`, `test_graph_read_models.py`,
  `test_graph_node_detail_read_models.py`, `test_api_activity.py`, and
  `test_graph_activity_stream.py`.
- `scripts/profile_graph_readback.py` and `scripts/compare_carriers.py`.
- `ui/src/components/GraphPanel.tsx`, `SchedulerView.tsx`,
  `NodeDetailPanel.tsx`, `FileStateViewer.tsx`, `ui/src/hooks/useApi.ts`, and
  related UI tests.
- Confirm the actual UI path is `ui/`, not `frontend/`.

## Weak Acceptance Command

A shallow implementation can pass this by keeping existing graph panel/readback
behavior green:

```bash
uv run pytest tests/integration/test_graph_api.py::test_active_graph_execution_readback_uses_bounded_summary_paths tests/integration/test_graph_api.py::test_node_detail_returns_inputs_outputs_filestate_callbacks tests/integration/test_api_activity.py::test_activity_includes_compact_graph_patch_decision_summaries -q
npm --prefix ui test -- GraphPanel.activity.test.tsx --run
```

## Hidden Oracle

Proposed hidden command, run outside all agents:

```bash
uv run pytest docs/dynamic-graph/oracles/test_graph_diagnostics_hidden_oracle.py -q
npm --prefix ui test -- GraphDiagnostics.hidden.test.tsx --run
```

The oracle seeds a deterministic graph run with heavy payloads, an expired
verifier lease, accepted and rejected planner patches, final-invariant deferral,
compact activity rows, file-state evidence, and deleted read models. It checks
behavior rather than a preferred internal shape:

- default API/UI paths do not fetch or render full raw payload sentinels;
- health summary identifies the expired verifier lease and final blocker;
- activity counts match compact graph activity;
- node drilldown shows causal evidence without heavy bodies;
- read-model rebuild preserves event count and facts;
- response size/latency stay under fixed deterministic thresholds;
- legacy runs are not misclassified as graph-backed.

## Public Graph Health Contract

The graph health endpoint is a scenario requirement, not an oracle-only
implementation preference. It should return a compact JSON object with these
operator facts and no raw event arrays, prompts, output bodies, or full payloads:

- `run_id`, `event_count`, `run_state`, and `status`.
- `counts` for ready, blocked, waiting resource, waiting gate, active lease,
  suspended lease, expired lease, failed node, final blocker, accepted patch,
  rejected patch, verifier pass, verifier fail, and pending human gate totals.
- `failed_nodes`: node id plus compact reason.
- `expired_leases`: lease id, node id, and reason, including
  `lease_expired_without_callback` when that is the cause.
- `blockers`: node id, kind, and compact reason for final invariant and other
  operator-actionable blockers.
- `recent_patch_decisions`: compact accepted/rejected patch rows.
- `verifier`: pass/fail totals and compact recent verifier rows.
- `pending_gates` and `review_blockers`.

## Why Arm A Should Plausibly Fail

A one-shot agent is likely to implement the visible UI or add one backend helper
and pass weak acceptance, while missing at least one hidden cross-cutting
obligation: expired-lease classification, stale read-model rebuild,
summary-only payload discipline, activity/count coherence, or heavy-stream
performance. That failure would still produce useful partial work: UI controls,
tests, an aggregation helper, or improved graph facts.

## Why Arm C And Arm E Differ

Arm C should use Mind-the-gap as an external adaptive loop: baseline, one chunk,
independent validation, compact durable state, then another chunk. Its adaptation
is in the human/agent workflow.

Arm E should adapt inside the graph: planner patches create future regions, gap
planner appends corrective nodes after local verification, rejected patches are
durable evidence, suspect/stale regions block final completion, and the final
invariant gate decides readiness.

## Admission Gate Before Live Tokens

No live A/C/E run until:

1. Weak and hidden oracle files exist and run deterministically.
2. Hidden oracle fails on the current pre-feature tree for real behavioral
   reasons.
3. A small hand-authored reference patch passes both commands.
4. The oracle does not require a preferred component shape.
5. DG-5.2e deterministic lease, prompt-budget, and active-readback checks remain
   green.
6. Only after that, run the one-shot Arm A baseline; C/E launch only if Arm A
   fails hidden materially while producing useful partial work.

## Scoring

Primary score, 100 points:

- 40 hidden oracle behavior.
- 20 active requirements satisfied.
- 15 adaptation evidence: discovery, correction, no stale evidence, final
  blockers resolved.
- 10 boundedness: response size, latency, no raw prompt/body leakage.
- 10 maintainability: typed models, public module imports, scoped changes, no
  mocking.
- 5 UX clarity.

Record separately: tokens, cost, tool calls, elapsed time, retries,
accepted/rejected patches, appended regions, verifier failures, stale evidence
links, and final review result.

## Invalid Scenario Exclusions

Reject scenarios that are only smoke/string artifacts, S2-style streaming parity
already solved by Arm A, pure backend refactors with no user-facing behavior,
UI-only polish, performance-only microbenchmarks, live-LLM/network/quota
dependent checks, direct production DB manipulation, hidden oracles that encode
a preferred component shape, or tasks passable by adding one label/string
without cross-feature discovery.
