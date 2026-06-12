# Slice 2.6 — Compat API + UI Projection

Size: M. Touches API routers, response models, React UI. Does NOT start runs
or drive the dispatch executor — read-only projection from existing graph events.

## Ground truth

- §25 API Shape — representative graph API endpoints
- §26 UI and Observability Requirements — projection vs fact visible
- §32 Migration Approach steps 2 + 5 — introduce graph projections behind
  compat APIs; move task status UI to task projection
- `src/orchestrator/graph/projections.py` — pure projection functions
  (already implemented): `project_run_state`, `project_task_states`,
  `project_node_states`, `project_leases`, `project_ready_nodes`,
  `project_residue_report`, `project_gatekeeper_report`
- `src/orchestrator/graph_runtime/store.py` — `GraphEventStore.read_run()`,
  `current_position()` (already implemented)

## Scope — what to build

### 1. DI helper — `get_graph_store`

Add to `src/orchestrator/api/deps.py`:

```python
async def get_graph_store(
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> GraphEventStore:
    from orchestrator.graph_runtime.store import GraphEventStore
    return GraphEventStore(session)
```

### 2. New router — `src/orchestrator/api/routers/graph.py`

Three read-only endpoints.

**`GET /api/runs/{run_id}/graph`** → `GraphProjectionResponse`

```python
@dataclass / Pydantic
class GraphProjectionResponse:
    run_id: str
    event_count: int          # GraphEventStore.current_position(run_id)
    run_state: str | None     # project_run_state(events)
    node_states: dict[str, str]
    task_states: dict[str, str]
    leases: dict[str, dict]
    ready_nodes: list[str]
```

Returns HTTP 200 with empty projection if run has zero events (not a graph run).
Never 404 on missing events — returns zeroed projection.

**`GET /api/runs/{run_id}/graph/events`** → `list[GraphEventResponse]`

```python
class GraphEventResponse:
    event_id: str
    event_type: str
    run_id: str
    position: int
    timestamp: str
    payload: dict[str, object]
```

Supports `?from_position=N` query param (default 0) to allow polling/paging.

**`GET /api/runs/{run_id}/graph/nodes/{node_id}`** → `NodeDetailResponse`

```python
class NodeDetailResponse:
    run_id: str
    node_id: str
    state: str | None
    output_records: list[dict]  # from projection["output_records"][node_id]
    file_state_records: list[dict]  # projection["file_state_records"] where producer_node_id==node_id
    active_lease: dict | None   # from project_leases if node has active lease
    events: list[GraphEventResponse]  # subset of run events where node_id appears
```

Returns HTTP 404 if run has zero graph events (not a graph run). Returns HTTP
404 if node_id does not appear in any event payload.

**Wire the router** in `src/orchestrator/api/app.py`:
```python
from orchestrator.api.routers.graph import router as graph_router
app.include_router(graph_router, dependencies=auth_deps)
```

### 3. `is_graph_backed` on RunResponse

In `src/orchestrator/api/routers/runs.py` (or `schemas/`), add
`is_graph_backed: bool = False` to the run response schema. Populate it for
the `GET /api/runs/{run_id}` and `GET /api/runs` endpoints: if the run's
`run_id` has `current_position > 0` in the graph store, set `True`.

Batch-loading for list view: query `MAX(version) GROUP BY aggregate_id` for
the set of run_ids in the page — one extra query, not N queries.

### 4. UI — Graph indicator + drill-down panel

**`ui/src/components/GraphIndicator.tsx`** (new, simple):

A small badge rendered inside the run detail header: `[Graph]`. Shown only
when `run.is_graph_backed`. Clicking it opens a side panel.

**`ui/src/components/GraphPanel.tsx`** (new):

Fetches `GET /api/runs/{run_id}/graph` and renders:
- Run state chip (e.g. `running`, `completed`)
- Node states table: columns `node_id | state | lease`
- Task states section: task_id → state (cross-reference against the existing
  task list)
- "Events" link → opens a modal with the raw event list from
  `/api/runs/{run_id}/graph/events`

Task cards in the run detail (`ui/src/components/TaskCard.tsx` or equivalent):
- When `run.is_graph_backed` and `graphProjection.task_states[task.id]` exists,
  show a secondary label under the legacy status: `graph: <state>`.
- This makes projection vs fact visible side-by-side (§26 requirement).

**No routing changes needed.** The panel opens as an overlay/drawer within the
existing run detail view.

## Tests

### Unit tests — `tests/unit/test_graph_api_projection.py` (new)

Pure unit tests for the projection response-building helpers (if any are
extracted as standalone functions in the router module). No DB, no HTTP client.

- `test_build_graph_projection_response_empty()` — zero events → zeroed projection, not an error.
- `test_build_node_detail_filters_by_node_id()` — node detail only includes records/events for the target node.
- `test_batch_graph_backed_detection()` — the batch-query helper returns the correct set of graph-backed run_ids.

### Integration tests — `tests/integration/test_graph_api.py` (new)

Use the existing test app client pattern (see `tests/integration/test_*.py` for
how tests obtain an `AsyncClient` and db session). Real SQLite tmp DB.

- `test_graph_projection_empty_for_non_graph_run()` — create a legacy run (no
  graph events), `GET /api/runs/{run_id}/graph` → 200 with event_count=0,
  all projection fields empty/null.
- `test_graph_projection_reflects_seeded_events()` — seed a run via
  `src/orchestrator/graph_runtime/seeding.seed_run()` with a compiled routine,
  submit a `schedule_tick` command through `GraphController`, then:
  - `GET /api/runs/{run_id}/graph` → event_count > 0, run_state and
    node_states populated correctly.
  - `GET /api/runs/{run_id}/graph/events` → list includes seeded events,
    `?from_position=N` filters correctly.
  - `GET /api/runs/{run_id}/graph/nodes/{node_id}` → 200 with state matching
    projection.
  - `GET /api/runs/{run_id}/graph/nodes/nonexistent` → 404.
- `test_is_graph_backed_flag_in_run_response()` — after seeding, `GET
  /api/runs/{run_id}` returns `is_graph_backed: true`.
- `test_is_graph_backed_false_for_legacy_run()` — legacy run returns
  `is_graph_backed: false`.
- `test_graph_events_from_position()` — seed 3+ events, `?from_position=2`
  returns only events at position ≥ 2.

## Done when

1. `GET /api/runs/{run_id}/graph` returns a correct projection for graph-backed
   runs and a zeroed-but-valid response for legacy runs (no 500s).
2. `GET /api/runs/{run_id}/graph/events` returns events ordered by position;
   `?from_position` filtering works.
3. `GET /api/runs/{run_id}/graph/nodes/{node_id}` returns node-scoped facts;
   404 for unknown nodes in graph-backed runs.
4. `is_graph_backed` field correct in both `GET /api/runs/{run_id}` and list
   view; list view uses batch query (not N+1).
5. UI: `GraphIndicator` visible and clickable on a graph-backed run; `GraphPanel`
   renders node states and task states; task cards show secondary `graph: <state>`
   label when projection has data; "Events" link opens the raw event list.
6. All integration tests pass; no N+1 queries; no 500s on any graph endpoint.
7. Kernel purity unchanged; no new IO imports in `src/orchestrator/graph/`.
8. Full suite green: `uv run pytest tests/unit -q` + `tests/integration -q`.

## Hard constraints (same as all slices)

- NO unittest.mock / monkeypatching. Hand-written fake classes only.
- Real SQLite tmp dirs only. Never touch `orchestrator.db` / main repo git.
- Kernel purity: `src/orchestrator/graph/` zero IO/DB/HTTP imports.
- `graph_runtime` imports no FastAPI / workflow-service internals.
- §28 rule 1: only `GraphController.handle_command()` appends graph events.
- No N+1 DB queries in the list endpoint.

## Dogfood gate (immediately after this slice)

After 2.6 is committed, run a graph-backed routine end-to-end:
1. Start the orchestrator: `uv run orchestrator serve --reload`
2. Create a run using the `graph-kernel-slice` routine against any pending
   slice spec (or a trivial one-task test spec).
3. Start the run with the Codex runner.
4. Navigate to the run in the UI; verify `is_graph_backed` shows `[Graph]`.
5. Verify the Graph panel shows node/task states updating as the agent works.
6. Let it complete; verify the verifier phase runs and grades the work.

This is the v1 implementation acceptance: an existing routine compiles into
graph nodes, one builder/verifier cycle runs, task projection rebuilds from
events, and graph state is visible in the UI.
