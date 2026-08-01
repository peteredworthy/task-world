# Task 1 report: Canonical Event Behavior Matrix And Strict Neutral Validation

## Implementation

- Added a frozen 48-row canonical behavior matrix and direct outcome tests, including all 14 explicitly neutral events.
- Made neutral reduction validate through the canonical Pydantic payload model before returning the original projection.
- Preserved all required neutral payload fields in compact replay modes so compact `EventEnvelope` values remain canonical.
- Corrected invalid callback and dispatch test fixtures exposed by strict validation.
- Fixed incremental node-detail compaction to use the event-specific retention set instead of the global union, preventing heavy unrelated payload leakage.

## TDD Evidence

- RED: `uv run pytest tests/unit/test_graph_projection_behavior.py -q` failed all 14 malformed-neutral rows with `DID NOT RAISE ValidationError`, proving neutral events bypassed payload validation.
- RED: the normal commit hook then exposed non-canonical neutral producers and compact-retention omissions. Targeted failures covered heartbeat production, callback rejection, command rejection, dispatch requests, compact replay, and node-detail payload leakage.
- GREEN: `uv run pytest tests/unit/test_graph_projection_behavior.py tests/unit/test_graph_projections.py tests/unit/test_graph_event_registry.py -q` passed.
- GREEN: the final focused regression command passed 94 tests.
- GREEN: the normal commit completed with every pre-commit hook passing, including full pytest, Ruff, Ruff format, Pyright, graph projection boundaries, import checks, signal routing, enum drift, and frontend checks.

## Files Changed

- `src/orchestrator/graph/payload_registry.py`
- `src/orchestrator/graph/projections.py`
- `src/orchestrator/graph_runtime/store.py`
- `tests/integration/test_graph_event_store.py`
- `tests/integration/test_graph_outbox_crash_points.py`
- `tests/unit/graph_projection_behavior_cases.py`
- `tests/unit/test_callbacks.py`
- `tests/unit/test_graph_payload_field_allowlists.py`
- `tests/unit/test_graph_projection_behavior.py`

## Commit

- `80c381d3d fix(graph): validate canonical projection behavior`

## Self-Review

- Unknown-event behavior and reducer-time reference policy are unchanged.
- Matrix fixture construction validates canonical payloads; malformed tests intentionally bypass only fixture construction.
- Compact retention is complete for required neutral fields while per-event node-detail filtering still excludes unrelated heavy bodies.
- No mocks, mutable projection state, compatibility parsing, or migration evidence was added.

## Concerns

None.

---

## Review Fix: Direct Outcomes And Valid Matrix Prefixes

### RED evidence

- Added event-specific assertions for every state-changing matrix row and checkpoint/integrity validation for the folded prefix and resulting projection.
- `uv run pytest tests/unit/test_graph_projection_behavior.py -q` initially failed because the `input_bound` prefix accepted a candidate whose producer node was absent, and the new `verification_passed` assertion showed that the candidate lacked its required file-state relationship.
- After repairing those fixtures, the integrity check exposed a second invalid fixture: `support_evidence_recorded` referred to `evidence-1` without an accepted evidence record. Added the accepted `evidence-1` prefix event.
- No reducer defect was exposed: all failures were invalid test fixture relationships, so production code was intentionally unchanged.

### GREEN evidence

- `uv run pytest tests/unit/test_graph_projection_behavior.py -q` — **64 passed**.
- `uv run pytest tests/unit/test_graph_projection_behavior.py tests/unit/test_graph_projections.py tests/unit/test_graph_event_registry.py -q` — **91 passed**.
- Commit hooks passed: Ruff, Ruff format, secret detection, Pyright, graph-projection boundaries, full pytest, module-import checks, signal routing, enum drift, UI lint, and UI typecheck.

### Files

- `tests/unit/graph_projection_behavior_cases.py`
  - Replaced generic changed-group identity checks with event-specific direct state and public-query assertions.
  - Repaired all referenced-node/record prefixes for graph patches, decisions, input bindings, verification, support evidence, and cleanup application.
- `tests/unit/test_graph_projection_behavior.py`
  - Validates prefix/result relationship integrity and checkpoint serializability, while retaining neutral identity, checkpoint, and public-query equality assertions.

### Commit

- `4fe87486e test(graph): strengthen projection behavior matrix`

### Self-review

- Each changing assertion verifies its event's concrete domain value rather than only root object replacement.
- Every prefix and resulting projection is checked with `validate_projection_integrity()` and `projection_to_checkpoint()`.
- Neutral event behavior remains strict: original projection identity, unchanged checkpoint, and representative public query equality.
- Deliberately excluded `replaced_paths`, `shared_paths`, `mutate_query_result`, and compact-retention concerns, as assigned separately.

### Concerns

- None.

---

## Review Fix: Matrix Interface Metadata And Query Probes

### RED evidence

- Added focused matrix-interface tests before changing the fixture metadata.
- `uv run pytest tests/unit/test_graph_projection_behavior.py -q` — **78 failed, 64 passed, 1 skipped**. Failures showed every row still used `projection_to_checkpoint` as its query, had placeholder root-group paths, or lacked mutation probes.

### GREEN evidence

- `uv run pytest tests/unit/test_graph_projection_behavior.py -q` — **170 passed**.
- `uv run pytest tests/unit/test_graph_projection_behavior.py tests/unit/test_graph_projections.py tests/unit/test_graph_event_registry.py -q` — **197 passed**.
- Focused Ruff and Pyright checks passed.
- Commit hooks passed: Ruff, Ruff format, secret detection, Pyright, graph-projection boundaries, full pytest, module imports, signal routing, enum drift, UI lint, and UI typecheck.

### Files

- `tests/unit/graph_projection_behavior_cases.py`
  - Replaced checkpoint fallback probes with event-relevant public `orchestrator.graph` queries.
  - Added replacement paths only for pre-existing values, relationship-valid shared sibling paths, and nested mutable public-result probes.
  - Added a valid sibling-node fixture only to the node-update rows so their shared-identity metadata names an actual unchanged entity.
- `tests/unit/test_graph_projection_behavior.py`
  - Proves declared paths identify replaced and shared values, probes are not checkpoint fallbacks, and mutation probes alter only fresh public results.

### Commit

- `3fbb15b92 test(graph): complete projection matrix interface`

### Concerns

- The focused tests deliberately validate the Task 1 matrix contract only; Task 3's full replay-generation and projection-wide identity suites remain unimplemented as requested.

---

## Review Fix: Replay-Only Neutral Payload Retention

### Caller trace

- `read_run_projection()` is a production replay reader. The graph API uses it for `/graph` task states, health, topology, final blockers, regions, and the post-decision scheduling check. Those helpers call `_project()`/`build_projection()` (directly or through `project_*`), so its `EventEnvelope` stream must retain every required neutral field.
- `read_run_summary_rebuild()` has no production route caller, but the fixture-corpus replay parity test passes its stream to `build_projection()`. It remains canonical for that replay contract.
- `read_run_light()` has no production caller. Its concrete callers are compact-reader tests; only the runtime-retry test folds its particular stream, whose declared fields remain sufficient. It is not a general reducer input.
- `read_run_node_detail()` is consumed by `rebuild_node_detail_summaries()` and node-detail parity tests. It flows through `_node_detail_summaries_from_events()` / `build_node_detail_response()`, not `reduce_event()` or `build_projection()`. The runtime-retry test folds a narrow test stream only; node-detail is not a general replay contract.

### Root cause and fix

- `_spec()` unioned `_required_neutral_fields()` into all four modes. This widened `light` and `node_detail`, including `callback_duplicate_returned.payload`, `prior_result`, and every `outbox_requeued` field despite those streams never being reducer inputs.
- Retention now unions required neutral fields only into `projection` and `summary`, the canonical replay modes. `light` and `node_detail` use their declared event-specific sets unchanged. `_same()` preserves the same split for future neutral events that use it.
- Strict `reduce_event()` validation, `EventEnvelope`, and public REST/MCP/CLI shapes are unchanged. The existing node-detail compactness test continues to prove output bodies are absent; the added SQLite regression proves heavy duplicate-callback bodies are absent from both non-replay compact readers.

### RED/GREEN evidence

- RED: `uv run pytest tests/unit/test_graph_payload_field_allowlists.py -q` — **1 failed, 8 passed**. The new non-replay compactness regression found `payload` in `callback_duplicate_returned` light retention, directly demonstrating the global-union leak.
- RED: `uv run pytest tests/integration/test_graph_event_store.py -q` — **1 failed, 25 passed**. The former all-modes expectation showed `light` retained the full `outbox_requeued` payload, confirming the compact contract had been widened.
- GREEN: `uv run pytest tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_lifecycle_event_payloads.py tests/integration/test_graph_event_store.py -q` — **44 passed**.
- GREEN: `uv run pytest tests/unit/test_fixture_corpus.py tests/integration/test_graph_node_detail_read_models.py tests/unit/test_graph_projection_behavior.py -q` — **189 passed**.
- GREEN: focused Ruff and formatting checks passed. The normal commit hooks also passed Ruff, formatting, secret detection, Pyright, graph-projection boundaries, full pytest, module-imports, signal routing, enum drift, UI lint, and UI typecheck.

### Files

- `src/orchestrator/graph/payload_registry.py`
- `tests/unit/test_graph_payload_field_allowlists.py`
- `tests/unit/test_lifecycle_event_payloads.py`
- `tests/integration/test_graph_event_store.py`

### Commit

- `18e26b358 fix(graph): narrow compact neutral payload retention`

### Concerns

- None. `light` and `node_detail` are intentionally compact, non-general-replay streams; callers that need to reduce arbitrary history continue to use `read_run()`, `read_run_projection()`, or `read_run_summary_rebuild()` as appropriate.
