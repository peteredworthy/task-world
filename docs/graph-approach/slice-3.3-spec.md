# Slice 3.3 — Node-detail drill-down

Size: M. The heart of §26's "projection vs fact" principle: a task card may
summarize, but must link to the immutable worker/verifier/check facts beneath.
2.6 shipped the `GET /api/runs/{id}/graph/nodes/{node_id}` endpoint
(`NodeDetailResponse`: state, output_records, file_state_records, active_lease,
events) but no UI consumes it. This slice builds the drill-down.

## Ground truth

- execution-graph-prd-plus.md §26 — "Node detail: inputs, outputs, file-state,
  prompt packet, callback history"; "task card … must link to the immutable
  worker/verifier/check facts underneath".
- Existing endpoint `routers/graph.py` `GET /graph/nodes/{node_id}` →
  `NodeDetailResponse`; `GraphPanel.tsx` node-states table; `useGraphProjection`.
- §19 callback semantics (callback history), §11 record model (output/file-state
  records), §10.4 ports (inputs).

## Scope — what to build

### 1. Extend `NodeDetailResponse` if needed

- Ensure the node-detail endpoint returns: node kind/role/state, bound **input
  ports** (port → bound record ids), **output records**, **file-state records**
  (with verdict + classification summary), **active/suspended lease**, and the
  **callback history** (the subset of events touching the node, including
  `acknowledge_start`, `submit_callback`, accept/reject, `agent_died`). If the
  prompt packet is recoverable for the node, include a `prompt_summary`
  (capability-gated; omit if not stored). Add only fields that are derivable
  from existing events/projection — no new graph mutations.

### 2. UI — `ui/src/components/NodeDetailPanel.tsx` (new)

- Clicking a node row in `GraphPanel`'s node-states table opens a node-detail
  view (drawer/expansion) fetching `GET /graph/nodes/{node_id}`.
- Sections: header (node id, kind, role, state, lease badge), Inputs
  (port → bound record ids), Outputs (output records), File-state (records with
  verdict/classification, link to 3.5 diff viewer when present), Callback
  history (chronological event list with type + timestamp).
- A node-detail hook in `useApi.ts` (`useGraphNodeDetail(runId, nodeId)`),
  mirroring `useGraphProjection`.
- The task card's `graph: <state>` label (from 2.6) links into the relevant
  node detail, realising the §26 "link to facts" requirement.

## Tests

### Integration — `tests/integration/test_graph_node_detail.py` (extend or new)

Real SQLite tmp + seeded graph events (reuse `test_graph_api.py` seeding):
- `test_node_detail_returns_inputs_outputs_filestate_callbacks()` — seed a run
  through a worker→verifier cycle; assert the endpoint returns bound inputs,
  output records, file-state records, active lease, and an ordered callback
  history for the worker and verifier nodes.
- `test_node_detail_404_for_unknown_node()` — preserved from 2.6.

### Frontend — `ui/src/components/**/__tests__`

- `NodeDetailPanel` renders each section from fixture node-detail data; clicking
  a node row opens it; the task-card label links to it. No network (mock data).

## Done when

1. The node-detail endpoint returns inputs (bound ports), outputs, file-state
   records, lease, and ordered callback history for a node — all derived from
   existing events.
2. `NodeDetailPanel` renders those sections; node rows in `GraphPanel` open it;
   the task-card `graph:` label links to the node's facts.
3. 404 for unknown node preserved.
4. Full suites green (unit + integration + frontend vitest); ruff/pyright clean;
   import boundary + kernel purity unchanged.

## Hard constraints (same as all slices)

- NO mocks/monkeypatching in Python tests; hand-written fakes only. Frontend
  tests use fixture data, no live network.
- Real SQLite tmp dirs; never touch `orchestrator.db`.
- Read-only projection: the endpoint derives everything from events; it appends
  no graph mutations (§28 rule 1). Kernel purity + `graph_runtime` boundary
  unchanged.
