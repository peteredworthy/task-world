# Projection simplification completion ledger

Updated 2026-08-14. Baseline: `9f7c8df07571d5e4215deaa0a064e78d6dcb6f1e`
(`9f7c8df07`). This is the final gap-closure ledger for every Finding 1–7 and
Stage 0–5 in `projection-simplification-report-2026-08-05.html`.

## Reading rules and verified product evidence

Statuses are deliberately distinct:

- **validated** means the merged implementation and its regression contract were
  independently confirmed here;
- **rejected / blocked by current policy** means the report's proposed change
  conflicts with the current repository contract and is not implemented;
- **gated by product decision** means the code may be changed only after the
  explicitly recorded external/API/product decisions are answered; and
- **not applicable** means the report item is already satisfied by a prior
  merged slice or is not an executable gap in this checkout.

The live product proof for this run is the orchestrator API readback for Codex
graph run `55b6e44d-3ca0-41ba-8ca7-0f9056e9be0e`, using `codex_server`,
`gpt-5.6-luna`, high reasoning, REST callbacks, and source SHA
`9f7c8df07`. Activity records accepted planner callbacks
`graph_patch_accepted` for patches `patch-01-discovery-region` through
`patch-08-corrective-failure-recovery-corrected` at graph positions 17–24
(activity event IDs 66883, 66888, 66893, 66903, 66909, 66924, 66928, and
66938). At the independent live readback, `/api/runs/<id>/graph` reported 125
events, 14 known nodes, 7 known tasks, the discovery worker and its verifier
completed, the implementation worker running, and no ready nodes. This proves
the current Codex callback and graph readback path; it does not claim that a
worker implementation callback has already been accepted.

The inherited product-real evidence is also retained where relevant: Wave 1
checkpoint run `8e677613-36c1-4a96-a73e-46b5a678955b` accepted two patches and
archival run `b598c0d2-f8b5-46bd-b037-000ab4132414` recorded a real patch
callback safely rejected for a forbidden cycle. Stage 5's actual React
Query/client path proves the graph panel no longer invokes the archival request
bundle. These are evidence records, not substitutes for the current source
and test checks below.

## Findings ledger

### Finding 1 — Collapse the query/export compatibility surface

- **Acceptance criteria:** Remove only projection query/projector/export names
  with no production consumer; retain consumer-shaped queries, public imports,
  behavior tests, replay/API shapes, and boundary imports; prove the removed
  names have no production import or call root.
- **Current evidence:** The query-surface inventory and current source agree
  that the dead convenience vocabulary was removed. The remaining
  `projection_queries.py` functions are consumer-shaped; current source starts
  with canonical record query views (`projection_queries.py:67-107`) and the
  package still exports the supported projection vocabulary (`graph/__init__.py:
  246-266`, `500-530`). Repository search found no removed-name production
  consumer. The one stale prose reference to schema 13 is
  `docs/dynamic-graph/graph-projection-map-inventory.md:5,28`; it is
  documentation drift, not a live schema contract.
- **Product-real proof:** The current Codex graph run's accepted planner
  callbacks and graph readback above exercised the retained graph query/patch
  path. No claim is made that dead query names are product APIs.
- **Regression proof:** Baseline immutable closure was `745/745` on 2026-08-14.
  The focused query, public-export, replay, duplicate-ID, codec, and boundary
  tests are included in this run's acceptance command; prior merged validation
  also reported the full Python suite passing.
- **Status:** **validated**.
- **Remaining gap:** Correct the stale non-executable schema-13 prose in a
  separately authorized documentation slice; no executable query simplification
  remains under this authority.

### Finding 2 — Treat the checkpoint as a disposable cache

- **Acceptance criteria:** The checkpoint stores schema version, event position,
  serialized grouped state, and checksum; load validation is direct and
  corruption/schema/staleness rebuilds from authoritative events; producer and
  reducer validation remain authoritative.
- **Current evidence:** `projection_codec.py:51,129-162` defines the validated
  checksum envelope and rebuild-facing codec path. The source retains producer
  validation and reducer/index checks rather than a policy compiler. Runtime
  recovery is checkpoint plus bounded tail, not an ad-hoc full-history command
  scan.
- **Product-real proof:** Wave 1 checkpoint run
  `8e677613-36c1-4a96-a73e-46b5a678955b` dispatched its real planner and
  accepted two patches; its graph position advanced 21 to 28. The current run
  also confirms the same graph callback/readback path remains live.
- **Regression proof:** Focused codec, integrity, flexible-JSON, replay,
  event-store, read-contract, cache-authority, and outbox recovery tests cover
  checksum/schema/malformed/stale checkpoint rebuild and bounded-tail parity.
  The run-health ledger records the exact oversized-history and failed-outbox
  regressions without enlarging caps or weakening validation.
- **Status:** **validated**.
- **Remaining gap:** None for the report's compliant checkpoint simplification.

### Finding 3 — Stop maintaining a shadow type system for projected records

- **Acceptance criteria:** Canonical accepted/output record models are the sole
  full-record values in `RecordStore.by_id`; remove duplicate projected record
  schemas/conversion dispatch while retaining canonical Pydantic validation,
  immutable ownership, IDs/summaries in secondary indexes, and replay parity.
- **Current evidence:** `projection_models.py:366-375` stores
  `AcceptedOutputRecordPayload` in `RecordStore.by_id` and stores only IDs or
  `GraphRecordSummaryProjection` in the secondary indexes. Current
  `projection_queries.py:67-107` revalidates independent canonical payload
  views. Repository search found no `Projected*` class hierarchy or
  `project_record`/`project_validated_record_for_reducer` conversion dispatch.
  Two projection-local `CandidateValue` and `CheckResultValue` models remain
  under compatibility aliases, but they are not full record values in
  `RecordStore.by_id`; reducer writes preserve canonical records and persistent
  replacement updates (`projections.py:1263-1314`).
- **Product-real proof:** The current run's accepted planner callbacks and graph
  readback show graph records are still being accepted/read through the retained
  canonical path; Wave 1's accepted checkpoint/archival callbacks provide the
  prior real-run record path.
- **Regression proof:** Canonical record model tests, output-record payload
  tests, duplicate-ID tests, projection replay/checkpoint parity, and the 745
  test immutable closure cover identity, validation, and every-split replay.
- **Status:** **validated**.
- **Remaining gap:** None for Finding 3.

### Finding 4 — Move immutability to the ownership boundary

- **Acceptance criteria:** The report proposes a private mutable builder,
  removal of `FrozenMap` and freeze/thaw, and replacement of persistent updates;
  any implementation would have to preserve no-alias leakage, deterministic
  replay, optimistic concurrency, and checkpoint/query immutability.
- **Current evidence:** This proposal conflicts with the current repository
  contract. `AGENTS.md` requires deeply immutable grouped `GraphProjection`
  state, `FrozenMap` indexes, identity-preserving reducers, canonical records,
  and the permanent boundary hook. Source confirms that contract:
  `projection_collections.py:14-147` defines `FrozenMap` and persistent map
  operations; `projection_models.py:876-881` defines grouped frozen storage;
  `projections.py:661-667,1134-1142,1297-1314` uses `model_copy`/`map_set`.
- **Product-real proof:** The current Codex graph readback proves the graph
  runner remains active under the immutable contract. No product-real evidence
  authorizes alias leakage or a mutable builder.
- **Regression proof:** The immutability, flexible-JSON, replay-equivalence,
  boundary, duplicate-ID, and performance tests are in the configured closure;
  the boundary script is a required acceptance gate.
- **Status:** **rejected / blocked by current policy**.
- **Remaining gap:** None under current authority. A future policy change would
  need a new decision and a new independent implementation/verification run;
  this run must not introduce a mutable builder, remove `FrozenMap`, or weaken
  alias/boundary checks.

### Finding 5 — Separate the runtime checkpoint from the bounded API snapshot

- **Acceptance criteria:** Runtime checkpoint and public `/graph` snapshot have
  separate owners; the runtime owner retains complete schema/position/state/
  checksum/terminal metadata without response-size packing; public responses
  stay compact and bounded; checkpoint-plus-tail recovery remains deterministic.
- **Current evidence:** `GraphProjectionSnapshotModel` at
  `db/orm/models.py:379-397` contains compact read fields only. Dedicated
  `GraphProjectionCheckpointModel` at `db/orm/models.py:399-416` owns position,
  schema version, terminal flag, checksum, and envelope. Runtime store paths
  read/write the two owners independently (`graph_runtime/store.py:4362-4390,
  4969-4978`).
- **Product-real proof:** Wave 1 checkpoint run `8e677613-36c1-4a96-a73e-46b5a678955b`
  crossed the real Codex callback boundary and advanced graph position 21 to 28
  through checkpoint-plus-tail recovery. The current run's graph readback
  remains readable with 125 events and bounded collection metadata.
- **Regression proof:** Fresh-schema/database tests, read-contract matrix,
  oversized checkpoint behavior, corrupt/schema/stale rebuild tests, event-store
  parity tests, and the immutable closure cover the split owners and lifecycle
  semantics.
- **Status:** **validated**.
- **Remaining gap:** None for Finding 5.

### Finding 6 — Retire the coupled archival-view feature conditionally

- **Acceptance criteria:** Remove only after external/API compatibility,
  diagnostics, exact blocker-count, failed-outbox, and semantic replacement
  decisions are resolved; preserve final-invariant calculation, failed-outbox
  visibility, position/pagination/byte-cap behavior, and canonical topology
  indexes. The safe first slice is UI decoupling plus non-destructive deprecation.
- **Current evidence:** Stage 5 removed the GraphPanel archival invocation/card
  but retained hook, clients, response types, routes, ORM owners, workers, and
  materializers. `graph.py:3376-3385` and `3726-3735` mark topology/regions
  deprecated and return `Deprecation: true`; final blockers remain non-deprecated
  and retain the failed-outbox overlay. The archival audit identifies 15
  integration consumers, one historical UI hook path, no CLI/MCP consumer, and
  unknown external REST/Python consumers.
- **Product-real proof:** Stage 5's real React Query/client test path proves the
  actual GraphPanel remains usable without `/graph` anchor, topology,
  final-blocker, or region requests. Wave 1 archival run
  `b598c0d2-f8b5-46bd-b037-000ab4132414` recorded a real patch callback; the
  current run adds the accepted callback/readback evidence recorded above.
- **Regression proof:** Stage 5 UI request/behavior tests, archival API
  pagination/position/partial/hash tests, final-blocker and failed-outbox tests,
  full graph acceptance, and the configured hidden oracle preserve compatibility.
- **Status:** **gated by product decision** for route/materializer retirement;
  **validated** for AR-A UI decoupling and topology/regions deprecation.
- **Remaining gap:** The Stage 5 ledger's four decisions remain unanswered:
  external consumer/telemetry and support window; topology edge/binding
  diagnostic replacement; failed-outbox terminal veto semantics; and arbitrary
  failed-outbox requeue policy. Do not delete routes, tables, workers, or
  `orchestrator.db` until those gates and replacement proofs exist.

### Finding 7 — Delete bespoke boundary enforcement after the boundary is small

- **Acceptance criteria:** The report proposes retiring the five-file AST
  allowlist/checker only after the projection boundary is private and all
  consumers have migrated; public top-level imports and focused architectural
  coverage must remain.
- **Current evidence:** The boundary is still an explicit current contract.
  `scripts/check_graph_projection_boundaries.py:39-47` defines the five allowed
  storage readers and its fail-closed source analysis still validates `FrozenMap`,
  grouped models, and reachable record ownership. The checker is invoked by the
  configured acceptance command and remains covered by
  `tests/unit/test_graph_projection_boundaries.py`.
- **Product-real proof:** The current Codex graph run's accepted callbacks and
  graph readback occurred while this permanent boundary guard was active; no
  product evidence supports removing it.
- **Regression proof:** The boundary test closure, direct checker, top-level
  import checks, and full acceptance command are required evidence.
- **Status:** **rejected / blocked by current policy**.
- **Remaining gap:** None under current authority. The boundary hook must remain
  permanent unless a future policy explicitly changes the contract and supplies
  equivalent invariant proof.

## Stage ledger

### Stage 0 — Baseline and external-consumer inventory

- **Acceptance criteria:** Capture event/replay/performance baseline and inventory
  UI, API, runtime/store, ORM, worker, docs, CLI/MCP, tests, and external graph
  diagnostic consumers before retirement decisions.
- **Current evidence:** Baseline is independently recorded as 745/745 in the
  ten-file immutable closure on 2026-08-14. The archival audit cites each
  in-repository surface and distinguishes “not found in this checkout” from
  “does not exist”; external REST/Python usage and telemetry remain unknown.
- **Product-real proof:** Current run `55b6e44d-3ca0-41ba-8ca7-0f9056e9be0e`
  has accepted callbacks and graph readback as recorded above; inherited Wave 1
  runs provide real checkpoint/archival callback evidence.
- **Regression proof:** Baseline focused closure, audit search/citation sampling,
  full graph API/read-contract/cache tests, and the current acceptance command.
- **Status:** **validated** for repository baseline/inventory; **gated by
  product decision** for external compatibility.
- **Remaining gap:** Obtain route telemetry/client-owner confirmation and select
  an API support/deprecation window. Repository absence alone is insufficient.

### Stage 1 — Prune queries, projectors, exports, and stale schema prose

- **Acceptance criteria:** Remove only dead production query/export names, retain
  all behavior coverage, preserve public import boundaries, and correct active
  schema-13 prose to schema 14 or version-neutral wording.
- **Current evidence:** Query/export pruning is merged and validated under
  Finding 1. Current active source and runtime use schema 14-era checkpoint
  behavior, but `graph-projection-map-inventory.md:5,28` still says schema 13.
- **Product-real proof:** Current graph callbacks/readback use the retained graph
  query surface; no removed name is asserted as product-real.
- **Regression proof:** Query/public-export/replay/duplicate-ID/codec/boundary
  closure and prior full-suite evidence pass; no behavior tests were removed
  outside the authorized query test surface.
- **Status:** **validated** for executable pruning; documentation sub-item is
  **not applicable** to this implementation-only authority.
- **Remaining gap:** A separately authorized documentation-only correction may
  remove the schema-13 drift; it is not a projection code gap here.

### Stage 2 — Separate runtime checkpoint storage

- **Acceptance criteria:** Large graphs continue snapshot+tail recovery; corrupt,
  stale, or missing disposable checkpoints rebuild; bounded public snapshots do
  not disable runtime command handling.
- **Current evidence:** Dedicated ORM owners and independent runtime store paths
  satisfy this exactly (Finding 5).
- **Product-real proof:** Wave 1 checkpoint run accepted two patches and advanced
  from graph position 21 to 28; the current run's accepted callback/readback
  path remains live.
- **Regression proof:** Event-store/read-contract/checkpoint corruption/schema,
  oversized-history, recovery, and parity tests plus the immutable closure.
- **Status:** **validated**.
- **Remaining gap:** None.

### Stage 3 — Canonical records and simpler checkpoint validation

- **Acceptance criteria:** Reuse canonical record models, preserve immutable
  ownership and strict producer/reducer checks, retire duplicate conversion and
  relation-policy machinery, and prove every-split replay/checkpoint parity.
- **Current evidence:** Canonical `RecordStore.by_id`, ID/summary secondary
  indexes, canonical query revalidation, and direct checksum codec are present;
  no projected full-record hierarchy or conversion dispatch remains. The two
  projection-local value models noted under Finding 3 are retained because they
  are grouped projection values, not duplicate full-record stores.
- **Product-real proof:** Wave 1 and current-run accepted callback/readback
  evidence exercised the graph's canonical record/patch path.
- **Regression proof:** Canonical model/output payload, integrity, replay,
  flexible-JSON, duplicate-ID, boundary, and full-suite evidence.
- **Status:** **validated**.
- **Remaining gap:** None.

### Stage 4 — Owned mutable builder and FrozenMap removal

- **Acceptance criteria:** The report requires a private mutable accumulator and
  removal of `FrozenMap`, deep freeze/thaw, persistent update boilerplate, and
  the boundary checker without alias leakage or replay/concurrency regressions.
- **Current evidence:** Current AGENTS.md explicitly requires the opposite
  invariant set, and source implements it. No compliant narrower implementation
  of the report's mutable-builder proposal exists in this checkout.
- **Product-real proof:** Current Codex graph readback is healthy under the
  immutable implementation; no accepted callback authorizes policy relaxation.
- **Regression proof:** Immutable closure, identity-preserving reducer tests,
  flexible JSON, performance, and permanent boundary script.
- **Status:** **rejected / blocked by current policy**.
- **Remaining gap:** None under current authority; do not schedule Stage 4.

### Stage 5 — Conditional archival diagnostics retirement

- **Acceptance criteria:** Retain actionable graph health, node detail, events,
  decisions, final-invariant blocking, failed-outbox visibility, and coherent
  position semantics; retire only after the four Stage 5 decisions and
  replacement proofs.
- **Current evidence:** AR-A UI decoupling and non-destructive topology/regions
  deprecation are merged. Routes, tables, workers, final-blocker overlay,
  clients, exports, and materializers remain intentionally present.
- **Product-real proof:** Actual GraphPanel React Query/client behavior, Wave 1
  callbacks, and current Codex graph accepted callbacks/readback are recorded
  above. No browser or external telemetry claim is made.
- **Regression proof:** Stage 5 focused/full UI and graph API tests, hidden cache
  authority oracle, final-blocker/failed-outbox tests, and the configured full
  Python/projection gates.
- **Status:** **gated by product decision** for destructive retirement;
  **validated** for the merged non-destructive AR-A slice.
- **Remaining gap:** Resolve external compatibility/support window, topology
  diagnostics, failed-outbox terminal semantics, and requeue drift; then assign a
  new authorized implementation/verification run. No executable Stage 5
  retirement remains authorized now.

## Final disposition

The current main is mergeable with the projection-simplification work that is
permitted by the repository contract: query/export pruning, dedicated runtime
checkpoint storage, canonical record ownership, AR-A UI decoupling, and
non-destructive topology/regions deprecation are validated. The remaining
report proposals are either rejected by the immutable-boundary policy (Findings
4 and 7 / Stage 4) or gated by the four unresolved Stage 5 external/product
decisions (Finding 6 / Stage 5 retirement). Therefore no additional executable
projection-simplification change is authorized in this run; the only artifact
created by this run is this ledger.

## Verification record

Required acceptance command:

```text
uv run pytest --run-slow -n 0 tests/unit/test_graph_projection_behavior.py tests/unit/test_graph_projection_flexible_json.py tests/unit/test_graph_projection_replay_equivalence.py tests/unit/test_graph_projection_immutability.py tests/unit/test_graph_projection_queries.py tests/unit/test_graph_projection_duplicate_ids.py tests/unit/test_graph_projection_codec.py tests/unit/test_graph_projection_integrity.py tests/unit/test_graph_projection_boundaries.py tests/unit/test_graph_projection_performance.py && uv run python scripts/check_graph_projection_boundaries.py && uv run python scripts/check_signal_routing.py && uv run ruff check . && uv run ruff format --check . && uv run pyright
```

The final verification record below contains only observed results. No source
change was authorized by this ledger update.

| Check | Result | Scope |
| --- | --- | --- |
| Immutable projection closure | **745 passed** | Ten configured unit files; independently rerun in this worktree |
| Graph projection boundary check | **passed** | `scripts/check_graph_projection_boundaries.py` |
| Signal routing check | **passed** | `scripts/check_signal_routing.py` |
| Ruff / format / Pyright | **passed** | Repository-wide; format reported 723 files already formatted; Pyright 0/0/0 |
| Hidden oracle | **67 passed** | Event store, read contract, cache authority |
| Full Python suite | **5,415 passed, 4 skipped, 4 warnings** | `uv run pytest` |
| Full UI suite | not applicable | No UI source is touched in this run |
| `git diff --check` / exact scope | **passed** | One untracked ledger file; no source, UI, DB, or AGENTS.md change |
