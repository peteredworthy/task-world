# Archival Graph View Consumer Audit

Date: 2026-08-13
Scope: Wave 1 requirements `W1-AR-1` and `W1-AR-2` only
Method: read-only source, test, and documentation audit; no production behavior was changed

## Executive recommendation

Do **not** delete all three archival endpoints or all four archival tables as one
change. The product UI does not consume the detailed topology, blocker, or region
rows, but the endpoints are documented public contracts and are deliberately used
by the graph acceptance suite. External clients and production route telemetry are
not represented in this repository, so immediate removal would be an unmeasured
compatibility break.

Use the following product decision:

| Surface | Decision | Recommendation |
|---|---|---|
| Topology | **Narrow; retirement candidate** | Stop fetching it when the graph panel opens. Keep the bounded, paginated endpoint during a deprecation/telemetry window because it is the only public aggregate view of edges, port contracts, binding policy, and bound-record positions. If no external consumer is found, move this capability to an explicit diagnostics export or retire it after migrating the acceptance proofs. |
| Final blockers | **Keep and decouple** | Keep a bounded detailed operator readback and an exact count, including failed-outbox rows. It is the only current surface for failed-outbox visibility and the most actionable of the three views. It must no longer depend on a shared topology/region generation. |
| Regions | **Retire after deprecation** | Stop fetching it in the graph panel and plan endpoint retirement. Current task states are already rendered from `/graph`; region-associated blocker detail is present in final blockers through `task_region_id`. Migrate the few tests that genuinely prove region semantics before removal. |

The first implementation slice should therefore remove the graph panel's coupled
four-request archival load (one extra `/graph` anchor plus the three archival
requests), not remove server contracts. A later server slice can decouple final
blockers and remove region materialization. Topology removal remains conditional on
the external-consumer gate.

This recommendation is intentionally more conservative than deleting the complete
archival feature. A prior recorded human steer retained the diagnostic routes after
their acceptance-suite consumption was discovered
(`docs/dynamic-graph/re-evaluation-2026-07-18.md:205-218`). The 5 August review
reopens that decision because the production UI now fetches all three views but
renders only counts; it does not provide evidence that external API use disappeared.

## Audit boundary and evidence standard

The inventory covers:

- UI clients, hooks, rendering, and UI tests;
- FastAPI schemas, route handlers, public exports, and route documentation;
- graph projection producers and runtime/store publication/read paths;
- ORM owners and database exports;
- the application lifespan maintenance worker;
- CLI and MCP source trees;
- unit, integration, acceptance, and schema tests; and
- architecture, status, proof, product, and prior decision documents.

Line references below describe the checkout inspected on 2026-08-13 after the
runtime checkpoint split was inserted. They were rebased against the final source;
symbol names are included so evidence remains locatable after future edits.

Repository evidence can prove in-repository consumers. It cannot prove that a
deployed REST client, ad-hoc operator script, dashboard, or external integration is
absent. No API access telemetry, client registry, or published compatibility policy
is present in the checkout.

## Producer and consumer matrix

| Owner / surface | Producer and lifecycle | In-repository consumers | Current evidence | Decision impact |
|---|---|---|---|---|
| Canonical topology projection | `project_graph_topology` and `iter_archival_graph_topology_entries` derive nodes, edges, contracts, bindings, and bound records from the folded projection (`src/orchestrator/graph/projections.py:3826-3867`, `:3870-3903`, `:3906-3975`). | Runtime archival rebuild, pure API builders, unit tests, and public HTTP acceptance tests. Kernel scheduling does **not** read the archival table. | `src/orchestrator/graph_runtime/store.py:5099-5117`; `src/orchestrator/api/routers/graph.py:1132-1198`; `tests/unit/test_graph_archival_queries.py:33-116`; `tests/unit/test_graph_api_projection.py:362-517`. | Preserve canonical topology and runtime graph indexes. Only the archival copy/API lifecycle is a retirement candidate. |
| Topology archival owner | `rebuild_archival_views` deletes and rewrites `GraphTopologyViewEntryModel` rows in batches, then publishes the shared checkpoint (`store.py:5001-5117`, `:5307-5310`). | `read_current_archival_view_page(..., "topology")`, then `GET /graph/topology`. | ORM table/index at `src/orchestrator/db/orm/models.py:428-440`; page count/read at `store.py:4458-4584`; route at `src/orchestrator/api/routers/graph.py:3376-3421`. | Stop eager UI use now. Keep during deprecation; remove table/worker branch only after the external-contract gate. |
| Canonical final-invariant calculation | `final_invariant_blockers_for_events` / `iter_final_invariant_blockers` computes blockers from the folded projection (`projections.py:2922-2949`). | Lifecycle `complete` rejection and explicit final-gate evaluation use the canonical calculation directly (`src/orchestrator/graph/_commands.py:354-370`, `:551-572`). `project_run_state` also refuses to present a blocked completed graph as completed (`projections.py:2889-2910`). | These paths do not read `GraphFinalBlockerViewEntryModel`. | Non-negotiable: archival simplification must not change this code or its semantics. |
| Final-blocker archival owner | The rebuild streams bounded final-invariant blockers into `GraphFinalBlockerViewEntryModel` and indexes `task_region_id` (`store.py:5119-5140`). | `/graph/final-blockers`; region materialization also queries this table to group blocker counts and prefixes (`store.py:5142-5305`). | ORM table/indexes at `models.py:442-461`; archival page read/count at `store.py:4556-4566`; route at `graph.py:3525-3690`. | Keep the public capability but sever its dependency on topology/regions and their shared checkpoint. A final-blocker-only read owner is acceptable if bounded paging remains required. |
| Failed-outbox overlay | The final-blocker route counts failed `GraphOutboxModel` rows, selects only bounded scalar fields, and appends them after the archival blocker cursor namespace (`graph.py:3525-3690`). | Public final-blocker clients and tests. No graph-panel detail is rendered; only combined `total_known` is shown. | Typed failed-row fields at `graph.py:647-675`; overlay construction at `:1737-1846`; SQL read at `:3554-3599`; paging at `:3601-3689`; tests at `tests/integration/test_graph_api.py:1914-2144`. | Must survive. Removing the route without a replacement would make exhausted outbox work invisible to operators. |
| Region archival owner | During the same rebuild, task states are unioned with blocker-associated region IDs, blocker counts/prefixes are read from the final-blocker table, and rows are written to `GraphRegionViewEntryModel` (`store.py:5142-5305`). | `/graph/regions`, acceptance tests, and the UI count. Kernel task acceptance does not read this table. | ORM table/indexes at `models.py:463-476`; page read/count at `store.py:4567-4577`; route at `graph.py:3724-3760`. | Retire after tests and clients migrate. Preserve canonical task state and blocker `task_region_id`, not the duplicate grouped rows. |
| Shared archival publication checkpoint | Every projection persistence marks a target position dirty in O(1), and a rebuild publishes topology, blockers, and regions together (`store.py:4964-5000`, `:5001-5310`). | Page reader rejects missing, stale, or in-progress generations with retryable unavailable status (`store.py:4478-4490`). | ORM owner at `models.py:418-425`. Append keeps old rows while dirty; savepoint replacement and position-last publication are tested in `test_graph_api.py:1357-1409` and `:1760-1858`. | Replace with only the owner(s) still retained. Do not leave topology/region dirty tracking running after their routes are retired. |
| Background maintenance worker | App lifespan selects one dirty archival checkpoint and rebuilds its complete generation continuously (`src/orchestrator/api/app.py:319-361`, task lifecycle at `:618-640`). | All archival owners and their route freshness guarantees. | `test_product_worker_publishes_coupled_archival_views` at `test_graph_api.py:1314-1355`. | Remove or rename only after retained final-blocker maintenance has a replacement. |
| Public schemas and routes | Pydantic response models expose full typed node/edge, blocker, and region payloads plus pagination/partial metadata (`graph.py:200-257`, `:647-692`). FastAPI registers three GET routes (`:3376`, `:3525`, `:3724`). | Generated OpenAPI, UI API client, any external REST client, route-enumeration tests. | `docs/ARCHITECTURE.md:744-762` describes all three as public, bounded routes with shared publication. `tests/integration/test_cache_authority_recovery_durability.py:651-680` asserts the exact route set. | Treat changes as API deprecations, not internal cleanup. Do not silently change meanings of `total_known`, cursor, 409, 503, or partial metadata while routes exist. |
| Python package exports | Pure topology, region, and blocker response builders are exported from `orchestrator.api` (`src/orchestrator/api/__init__.py:105-116`, `:145-159`, `:182-197`). Archival ORM classes are re-exported by `orchestrator.db` (`src/orchestrator/db/__init__.py:8-30`, `:189-209`) and its compatibility shim. | Tests and potential Python library consumers. No other production importer was found beyond the owning modules/re-export layers. | Repository-wide import/name search on 2026-08-13. | Include Python exports in the deprecation/removal checklist; HTTP removal alone does not close the public surface. |
| Product UI | `useArchivalGraphSnapshot` obtains a fresh `/graph` anchor, then fetches topology, final blockers, and regions concurrently at that position (`ui/src/hooks/useApi.ts:87-123`). | `GraphPanel` only (`ui/src/components/GraphPanel.tsx:550-568`). | Render use is limited to `position`, each response's `total_known`, and the OR of three `partial` flags (`GraphPanel.tsx:665-698`). | Remove the hook from panel-open behavior first. The detailed bodies provide zero current user value. |
| UI client/types | Client methods implement all cursors/limits/expected-position parameters (`ui/src/api/client.ts:574-607`); response types include full item arrays and all paging metadata (`ui/src/types/runs.ts:318-360`). | The archival hook and tests. No second UI caller was found. | `rg` finds only `useApi.ts`, `GraphPanel.tsx`, their tests, and client tests. | Delete only after server deprecation needs are decided; a deprecated server client may remain temporarily without being invoked by the product UI. |
| CLI and MCP | No CLI command, orchestrator MCP tool, graph MCP registry/tool, or runner MCP scope references these routes or their response types. | None found. | Searches of `src/orchestrator/cli/`, `src/orchestrator/api/mcp/`, `src/orchestrator/graph_runtime/graph_mcp_*`, and `src/orchestrator/runners/mcp_scope.py` returned no endpoint/name consumer. | Strong evidence of no in-repository CLI/MCP dependency, but not evidence about external REST clients. |
| Documentation/product proof | Architecture and graph status documents name the routes as supported readbacks. FR-06, FR-13, FR-14, FR-17, and FR-18 use topology/region/blocker responses as observable acceptance evidence. | Developers, reviewers, and release expectations. | `docs/ARCHITECTURE.md:744-762`; `docs/dynamic-graph/status.md:1636-1648`; extensive historical product proof in `docs/dynamic-graph/complete/dynamic-graph-proof-ledger-validated-2026-06-26.md`. | Update the functional proof contract when routes migrate. Deleting assertions without replacement would weaken validated behavior. |

## Exact UI usage versus response payloads

Opening the graph panel currently starts `useGraphProjection(runId)` and also starts
`useArchivalGraphSnapshot(runId)`. The latter does not reuse the already queried
React Query projection value; it calls `api.getRunGraphProjection` itself as an
anchor (`useApi.ts:77-84`, `:99-112`). The archival feature therefore adds four
requests per initial assembly and repeats the full four-request assembly after an
expected-position mismatch or retryable failure.

| Response | Payload returned | Fields the product renders | Payload discarded by the product UI |
|---|---|---|---|
| `/graph/topology` | `nodes[]` with kind/role/state/contract; `edges[]` with endpoint/port/schema/dependency/binding/bound-record detail; pagination and per-field metadata (`graph.py:200-257`). | `total_known`, `partial`; the shared anchor position is rendered. | Every node and edge, `truncated`, `next_cursor`, and `collection_meta`. The UI never requests page 2. |
| `/graph/final-blockers` | Typed blocker rows including node/edge/requirement/region and failed-outbox identity, error, kind, and attempts; pagination and per-field metadata (`graph.py:647-675`). | `total_known`, `partial`. | Every blocker reason and identity—including the failed-outbox details needed to diagnose or remediate work—plus cursor and metadata. The UI never requests page 2. |
| `/graph/regions` | Region ID, state, nested blocker rows, pagination and per-field metadata (`graph.py:678-692`). | `total_known`, `partial`. | Every region state and blocker. The UI never requests page 2. |

The hook tests do inspect returned arrays to prove coherent retry behavior
(`ui/src/hooks/useApi.graphEvents.test.tsx:125-230`), but that is regression
coverage of the hook, not a rendered product use. The sole rendering assertion
checks only `3 topology entries · 1 final blockers · 2 regions`
(`ui/src/components/__tests__/GraphPanel.decisions.test.tsx:111-125`, `:205-211`).

## Counts available elsewhere—and gaps

The current checkout does **not** provide three drop-in equivalent counts. A safe UI
change must account for these semantic differences rather than relabeling a partial
count.

| Desired UI fact | Existing compact source | Equivalence assessment |
|---|---|---|
| Node count | `/graph.node_states` and `collection_meta.node_states.total_known`; the snapshot stores node states at `store.py:6228-6268`, and the API exposes collection metadata at `graph.py:985-1013`. | Exact node-state owner count. It is **not** equal to topology `total_known`, which counts nodes plus edges (`store.py:4545-4555`). If the UI changes the label from “topology entries” to “nodes,” this is a valid replacement. |
| Edge count | None in `/graph`, `/graph/health`, scheduler, or decision response. | Not available elsewhere today. Add a compact scalar if the product truly needs it, or stop displaying “topology entries.” Do not infer it from nodes. |
| Task/region count | `/graph.task_states` and `collection_meta.task_states.total_known`; `TaskStatesSection` already renders task states from `/graph` (`GraphPanel.tsx:393-423`). | Usually the desired product count, but not contractually identical: the archival region owner unions task-state IDs with blocker-only region IDs (`store.py:5142-5203`). Prefer the user-facing label “tasks” or add an explicit compact `region_count`. |
| Final-blocker count | `/graph/health.counts.final_blockers` exists in the schema and UI (`graph.py:366-380`; `GraphPanel.tsx:63-68`). | For a non-empty graph, bounded health currently reports this count as `None`/unavailable (`graph.py:2164-2221`). An exact replacement must be implemented before removing the archival count. It must add failed-outbox rows to the canonical projection blocker count. |
| Failed-outbox count | A scalar SQL count already exists inside the final-blocker route (`graph.py:3558-3567`). | Reusable for a compact health/stat owner. It is not presently returned anywhere else. |

Recommended panel result: remove the “Archival graph views” card; show the existing
node/task state UI and existing Graph Health card. Make health's final-blocker count
exact and available by combining the retained final-blocker owner count with the
failed-outbox scalar count. Do not add an edge count unless users have a concrete
need for it.

## Public-contract and external-consumer assessment

Evidence that these are public contracts:

1. FastAPI registers typed response models and query parameters, so the routes are
   present in generated OpenAPI (`graph.py:3376-3421`, `:3525-3703`, `:3724-3760`).
2. `docs/ARCHITECTURE.md:744-762` advertises their bounds, shared position,
   retryable 503, and `expected_position` behavior.
3. The UI exposes named client methods for all three routes (`client.ts:574-607`).
4. The route enumeration test asserts their presence
   (`test_cache_authority_recovery_durability.py:651-680`).
5. Fifteen integration test files contain direct requests to at least one of the
   three routes. `test_graph_api.py` alone contains 20 route literals and owns the
   archival pagination/publication/corruption/rollback/outbox contract. Fourteen
   additional cache/decision/FR acceptance files contain 34 route literals.
6. The July re-evaluation records an explicit prior decision to keep the diagnostic
   endpoints rather than weaken HTTP-path acceptance proof
   (`re-evaluation-2026-07-18.md:205-218`).

Evidence against additional in-repository production consumers:

- the only UI execution path is `GraphPanel -> useArchivalGraphSnapshot`;
- no backend production module calls the HTTP handlers or page reader except the
  router/store ownership chain;
- no CLI or MCP source references these routes; and
- no other first-party API client is present in the repository.

Unknowns that block immediate hard removal:

- deployed API access logs and route-level request counts;
- external scripts, SDKs, dashboards, support tools, or bookmarked URLs;
- whether API compatibility is promised across releases and for how long;
- whether topology edge/binding diagnostics are used during live incident response;
- whether another checkout or private repository consumes the Python API builder or
  ORM re-exports; and
- whether failed-outbox visibility has an out-of-repository operator workflow.

The absence of a repository consumer must therefore be recorded as “not found,” not
“does not exist.”

## Invariant and failed-outbox guardrails

### Final invariants

- Events remain authoritative; archival rows remain disposable.
- Runtime command handling continues to use one folded projection and checkpoint
  plus tail, never an ad-hoc request-time full replay.
- `complete` must continue to call `final_invariant_blockers_for_events` and reject
  while blockers remain (`_commands.py:354-370`).
- Explicit final-gate evaluation must continue to produce `blocked` while blockers
  remain (`_commands.py:551-572`).
- `project_run_state` must not advertise a blocked completed projection as completed
  (`projections.py:2889-2910`).
- Blocker identity, reason, `task_region_id`, and bounded support evidence must remain
  observable either through the retained final-blocker endpoint or its explicitly
  versioned replacement.
- Position and optimistic-concurrency semantics must remain coherent with `/graph`.
  A replacement multi-read UI must not combine facts from different positions.

### Failed outbox

- Preserve exact failed-row count and bounded details: run ID, outbox ID/event ID,
  kind, last error, and attempts (`graph.py:647-675`, `:1777-1812`).
- Preserve bounded, payload-free SQL reads. The route intentionally does not decode
  opaque outbox payloads (`graph.py:3558-3596`).
- Preserve stable pagination across the archival and `outbox:<id>` cursor namespaces
  until a versioned replacement exists (`graph.py:3601-3721`).
- Preserve the 262 KiB response ceiling and hashing/partial metadata for oversized
  errors (`test_graph_api.py:2097-2144`).
- Do not claim more than current code proves: canonical graph final invariants gate
  lifecycle completion, while failed outbox rows are currently a database overlay on
  the readback. The audit found no failed-outbox query in the pure `complete` command
  or `finalize_graph_run_completion`. Current W6 semantics establish visible
  blocking/diagnosis, not a proven hard lifecycle veto. If failed rows must prevent
  terminal completion, that is a separate product requirement and implementation
  slice.
- Historical documentation says operators can requeue arbitrary failed outbox rows,
  but the current source has no `/graph/outbox/requeue/{event_id}` route. Only failed
  snapshot-cleanup rows are automatically requeued during startup. Treat the W6
  requeue claim as documentation drift; do not use it to justify deleting failed-row
  visibility.

## Deprecation strategy

1. **Decouple the UI without changing the API.** Remove the archival hook from
   `GraphPanel`, remove the card, and make compact health provide the exact final
   blocker count. Measure panel-open network behavior. Leave the three route methods
   available for compatibility during this slice.
2. **Instrument and announce.** Obtain route-level production request counts broken
   down by authenticated caller/user-agent where policy permits. Mark topology and
   regions deprecated in OpenAPI and architecture docs. Return standard
   `Deprecation` and `Sunset` headers plus a replacement `Link` if this project has an
   agreed release date. Do not invent a date before the support window is decided.
3. **Migrate first-party proofs.** Replace region acceptance assertions with
   `/graph.task_states` plus retained final-blocker assertions. Decide whether edge
   binding proof remains an HTTP product contract; if yes, keep topology or create an
   explicit diagnostics export before migrating those tests.
4. **Decouple final blockers.** Replace the coupled archival checkpoint with a
   final-blocker-only owner or another bounded owner that publishes exact canonical
   blockers at the graph position. Overlay failed outbox facts as today. Health reads
   its exact count without loading blocker bodies.
5. **Retire regions after the gate.** Remove its route/client/types/builders/table and
   documentation only after the telemetry/support window is clean and all semantic
   proofs have replacements.
6. **Conditionally retire topology.** Remove it only if the external-consumer check is
   clean and the product owner accepts loss or relocation of edge/binding diagnostics.
7. **Remove dead coupled infrastructure last.** Once only retained owners remain,
   remove shared checkpoint/dirty tracking, background work, DB exports, and obsolete
   bounded/pagination tests. Existing databases may retain inert old tables: this
   project has no schema-upgrade/drop contract, and no implementation should delete
   or recreate `orchestrator.db`.

## Implementation slices and exact ownership

| Slice | Requirement rows advanced | Files owned | Tests owned / required proof | Parallelism and conflicts |
|---|---|---|---|---|
| AR-A — UI decoupling | W1-AR-2 implementation precursor | `ui/src/components/GraphPanel.tsx`, `ui/src/hooks/useApi.ts`, optionally `ui/src/api/client.ts` and `ui/src/types/runs.ts` if deprecated methods are removed immediately | `ui/src/components/__tests__/GraphPanel.decisions.test.tsx`, `ui/src/hooks/useApi.graphEvents.test.tsx`, `ui/tests/api/client.test.ts`; product proof that opening the panel emits no topology/regions archival requests and still shows truthful health | Could run parallel with the runtime-checkpoint split because it has no shared source files. Coordinate if health count is delivered in another slice. |
| AR-B — exact compact blocker count | W1-AR-2 | `src/orchestrator/api/routers/graph.py`; `src/orchestrator/graph_runtime/store.py` only if a scalar/read owner is needed; UI type/health test | Focused graph health tests, final-blocker failed-outbox tests at `test_graph_api.py:1914-2144`, GraphPanel health rendering | `store.py` overlaps the completed checkpoint split. Build this slice on the current W1-CP result, or constrain it to router/UI work against an already available owner. |
| AR-C — region retirement | W1-AR-2 after contract gate | `graph.py` region schema/builders/route; `store.py` region rebuild/read/delete branches; `models.py` region ORM; `db/__init__.py`, `db/models.py`; `client.ts`, `runs.ts`; `docs/ARCHITECTURE.md` | Region-specific builders in `tests/unit/test_graph_api_projection.py:671+`; archival query/store/API cases; route enumeration; FR-01/03/13/14/17/18 assertions migrated to `/graph` plus final blockers; fresh-schema test | Must follow checkpoint split because `store.py`, `models.py`, DB exports, delete/rebuild paths overlap. Can be separate from topology if final-blocker owner no longer depends on region grouping. |
| AR-D — topology narrow/conditional retirement | W1-AR-2 after external gate | `graph.py` topology schema/builders/route; topology iterators/exports only if no diagnostics replacement; `store.py` topology rebuild/read/delete branches; `models.py` topology ORM; DB exports; UI client/types; architecture docs | `tests/unit/test_graph_archival_queries.py:33+`, `test_graph_api_projection.py:362+`; archival API suite; route enumeration; FR-02/03/06/07/08/09/12/14/17 route assertions replaced by equivalent product-interface proof | Server portion must follow checkpoint split. The telemetry/deprecation work can run in parallel. Do not delete canonical topology indexes used by the kernel. |
| AR-E — final-blocker decoupling | W1-AR-2 | `store.py` final-blocker publication/page/count; `graph.py` final-blocker route/health; retained or replacement ORM owner; `api/app.py` maintenance task if still needed; DB exports/docs | Canonical command/projection tests remain unchanged; `test_graph_api.py:1914-2144`; bounded paging/rollback tests adapted to a single owner; W6 visibility proof | Highest semantic risk. Build on W1-CP and avoid mixing with topology removal in one patch. |
| AR-F — dead archival infrastructure cleanup | W1-AR-2 final cleanup | `api/app.py:319-361,618-640`; remaining `GraphArchivalViewCheckpointModel`; `store.py` dirty/rebuild/delete helpers; DB exports and compatibility shim; stale docs | `tests/integration/test_database.py:289-340`; worker and coupled-generation tests in `test_graph_api.py:1220-1911`; full graph acceptance suite | Last slice only. It shares the checkpoint-split hot files, so it must build on the completed W1-CP result rather than run against an older base. |

Recommended sequence is `W1-CP -> AR-A/telemetry -> AR-B -> AR-E -> AR-C ->
AR-D decision -> AR-F`. W1-CP is now present in the inspected source. AR-A and
telemetry preparation were the only implementation work cleanly parallel with it.

## Merge-conflict notes relative to the runtime-checkpoint split

The completed checkpoint change added `GraphProjectionCheckpointModel` adjacent to
the archival ORM owners and rewired checkpoint read/persist/delete/rebuild logic in
`GraphEventStore`. Any server-side archival removal will overlap these exact areas:

- `src/orchestrator/db/orm/models.py` around `GraphProjectionSnapshotModel` and
  `GraphArchivalViewCheckpointModel`;
- `src/orchestrator/db/__init__.py` and `src/orchestrator/db/models.py` exports;
- `src/orchestrator/graph_runtime/store.py` imports, `read_projection_checkpoint`,
  `persist_projection_snapshot`, `_mark_archival_views_dirty`,
  `rebuild_archival_views`, `delete_read_models`, and `rebuild_read_models`;
- schema tests that enumerate fresh database tables; and
- cache-authority tests that distinguish public snapshot from runtime checkpoint.

Avoid concurrent edits to those files. The audit document and AR-A UI-only change
have no such conflict. Every archival cleanup change must assert that it deletes
neither the new runtime checkpoint nor its recovery path.

## Measurable exit criteria

W1-AR-1 is complete when:

- a repeated repository search identifies no unclassified producer or consumer in
  UI, API, runtime/store, ORM, worker, docs, CLI/MCP, or tests;
- every current in-repository production caller is named above;
- public/test-only use is separated from product-rendered use; and
- external REST/Python use is explicitly recorded as unknown until telemetry/client
  owners answer it.

W1-AR-2 is sufficient to authorize implementation only under these gates:

- product owner accepts **topology narrow**, **final blockers keep**, and **regions
  retire**;
- an API support/deprecation window is selected;
- route telemetry or a documented client-owner sign-off covers topology and regions;
- GraphPanel open performs zero `/graph/topology` and `/graph/regions` requests and no
  extra anchor `/graph` request; it performs zero `/graph/final-blockers` request if
  exact health count is available;
- health reports an exact final-blocker count at the same graph position, including
  failed outbox rows, and never reports unavailable as zero;
- canonical `complete` and final-gate blocker behavior is byte/semantically unchanged
  for existing test fixtures;
- a failed outbox row remains discoverable with bounded details through a supported
  operator interface;
- region-state proof remains available through `/graph.task_states`, with blockers
  correlated by `task_region_id`;
- retained endpoints preserve pagination, byte caps, `expected_position` 409, and
  retryable-unavailable 503 behavior;
- fresh ORM metadata contains only the intentionally retained owners; existing DBs
  are not destructively modified;
- `uv run ruff check` and `uv run pyright` pass;
- focused UI, graph API, graph event-store, read-contract, cache-authority, database,
  command, projection, outbox, and affected FR acceptance tests pass; and
- one real graph/Codex run demonstrates that final-invariant failure still prevents
  completion and the graph panel remains usable without the archival request bundle.

## Risks and rollback

| Risk | Mitigation | Rollback |
|---|---|---|
| Unknown external client breaks | Telemetry and announced deprecation before route removal; retain response shape during window. | Restore route registration/client contract. Events remain authoritative, so rebuild disposable owners before serving them again. |
| Acceptance suite is weakened by deleting HTTP assertions | Migrate each semantic proof to a supported product interface; do not merely delete tests. | Keep topology/region endpoints until equivalent product-path proof exists. |
| Final-invariant behavior changes accidentally | Keep canonical blocker calculation and lifecycle command tests outside the archival patch. | Revert read-owner changes; canonical events/projection remain intact. |
| Failed outbox becomes invisible | Keep final-blocker details/count and their payload-free scalar SQL query. | Restore the final-blocker endpoint/overlay; failed outbox rows remain durable in `graph_outbox`. |
| UI shows misleading substitute counts | Rename topology to nodes/tasks where appropriate; treat `None` as unavailable; add exact scalars rather than inferred equality. | Restore the archival summary card temporarily while replacement counts are corrected. |
| Removal races the runtime-checkpoint split | Sequence all `store.py`/ORM cleanup after W1-CP and review the combined diff around persistence/deletion/rebuild. | Revert the archival slice without reverting the dedicated runtime checkpoint. |
| Existing databases retain retired tables | Accept inert disposable tables under the project's no-schema-upgrade contract; never delete the DB. | Reintroducing the ORM/worker can reuse or rebuild from events; stale rows must not be served until a current checkpoint is published. |
| Background work is removed too early | Keep maintenance until every retained owner has another publication path. | Re-enable worker and mark runs dirty for bounded rebuild. |

## Unresolved decisions

1. **External compatibility gate:** who can confirm deployed REST/Python consumers,
   what telemetry is available, and what deprecation window applies? Until answered,
   topology and regions may be deprecated and removed from first-party UI use but
   must not be hard-deleted.
2. **Topology diagnostics:** does the product require a supported aggregate edge and
   binding diagnostic after deprecation? If yes, keep the current endpoint or define
   an explicit export before removing its materialization.
3. **Failed-outbox terminal semantics:** current code makes failed rows visible in
   final blockers but does not prove they veto lifecycle completion. Decide separately
   whether “blocked” is an operator-health classification or a hard completion rule.
4. **Requeue drift:** current source lacks the historically documented arbitrary
   failed-outbox requeue endpoint. Decide whether to restore a supported remediation
   action; this audit does not authorize that expansion.

Subject to those decisions, this audit authorizes AR-A and deprecation/telemetry work.
It does not yet authorize destructive removal of the public routes or archival ORM
owners.
