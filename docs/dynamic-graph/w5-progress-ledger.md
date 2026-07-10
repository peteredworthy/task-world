# W5 Typed Payloads Progress Ledger

Seed branch: `main`
Seed SHA: `bd41b5b24756fec7441cbfd0ee150739b9afede7`
Work branch: `codex/w5-typed-payloads`

## Phase 0 - Corpus Replay Parity Safety Net

Status: complete in working tree, pending commit.

Changes:
- Added a corpus-level replay parity test over the graph YAML fixtures.
- Fixed compact summary rebuild payload extraction so checkpoint replay matches
  full event replay for the current fixture corpus.

Verification:
- `uv run pytest tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py -q`
  - Result: passed, 11 tests.
- `uv run pytest tests/integration/test_graph_read_models.py tests/integration/test_graph_event_store.py -q`
  - Result: passed, 26 tests.
- `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_graph_payload_field_allowlists.py -q`
  - Result: passed, 131 tests.
- `uv run ruff check tests/unit/test_fixture_corpus.py src/orchestrator/graph_runtime/store.py`
  - Result: passed.
- `uv run pyright tests/unit/test_fixture_corpus.py src/orchestrator/graph_runtime/store.py`
  - Result: passed, 0 errors.

Notes:
- No typed payload migration work has started.
- The safety net must remain green before any event-family slice begins.

## Phase 1 - Event Payload Inventory

Status: complete in working tree, pending commit.

Artifact:
- `docs/dynamic-graph/w5-event-payload-inventory.md`

Notes:
- Surveyed `_commands.py` producer `make_event(...)` sites, confirmed
  `compiler.py` has no `make_event(` sites, and grouped reducer-consumed event
  payloads into implementation families.
- No production code or test changes were made for the inventory.

## Cleanup Event Payload Slice

Status: complete in working tree, pending commit.

Scope:
- Added typed event payload models for `cleanup_requested` and
  `cleanup_applied` in `src/orchestrator/graph/models.py`.
- Routed gatekeeper `cleanup_requested` producer emission and
  `record_cleanup_applied` producer emission through those payload models.
- Routed cleanup projection reducer consumption through typed payload models
  instead of raw `event.payload.get(...)` access.

Legacy normalization:
- `authority` remains a typed string field for current producer behavior.
- Legacy non-string `authority` values are moved under `extra["authority"]`.
- Legacy unknown top-level cleanup payload keys are moved under `extra`.
- `paths` is normalized to string entries only.

Dropped write-only keys:
- None. Legacy free-form top-level keys are preserved under `extra`.

RED:
- `uv run pytest tests/unit/test_cleanup_event_payloads.py -q`
  - Result: failed during collection with
    `ImportError: cannot import name 'CleanupAppliedPayload' from 'orchestrator.graph'`.

GREEN:
- `uv run pytest tests/unit/test_cleanup_event_payloads.py -q`
  - Result: passed, 4 tests.
- `uv run pytest tests/unit/test_fixture_corpus.py::test_fixture_corpus_replay_matches_checkpoint_and_compact_projection -q`
  - Result: passed, 1 test.
- `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_cleanup_event_payloads.py -q`
  - Result: passed, 142 tests.
- `uv run ruff check src/orchestrator/graph tests/unit`
  - Result: passed.
- `uv run pyright src/orchestrator/graph tests/unit`
  - Result: passed, 0 errors.
- `uv run pytest tests/ -k graph -q`
  - Result: passed, 837 tests.
- `uv run ruff check .`
  - Result: passed.

## Lease Event Payload Slice

Status: complete in working tree, pending commit.

Scope:
- Added typed event payload models for `lease_granted`, `lease_renewed`,
  `lease_released`, `lease_revoked`, `lease_expired`, and replay-only
  `lease_suspended` in `src/orchestrator/graph/models.py`.
- Routed current lease producers in `src/orchestrator/graph/_commands.py`
  through typed payload validation/dump for grant, renewal, release, revoke,
  and expiry events. `lease_suspended` remains replay-only.
- Routed lease projection reducer consumption in
  `src/orchestrator/graph/projections.py` through typed payload models before
  reading lease fields.

Legacy normalization:
- Unknown top-level lease payload keys are moved under `extra`.
- Legacy top-level `lease_granted.task_region_id` and `lease_granted.kind`
  are moved under `extra` and still consumed for replay compatibility before
  falling back to node projection state.
- `resource_claims` keeps using the existing typed
  `ResourceClaimProjection` shape; legacy scalar `path` is normalized to
  `paths`, and non-dict claim entries are dropped.
- Partial legacy lease events remain tolerant: reducer parsing still accepts
  old events that only carry `lease_id` and the minimum historical fields.

Dropped write-only keys:
- None. Legacy free-form top-level keys are preserved under `extra`.
- `observed_at` remains a typed audit field on `lease_renewed`; it is not
  consumed into the lease projection.

RED:
- `uv run pytest tests/unit/test_lease_event_payloads.py -q`
  - Result: failed during collection with
    `ImportError: cannot import name 'LeaseExpiredPayload' from 'orchestrator.graph'`.

GREEN:
- `uv run pytest tests/unit/test_lease_event_payloads.py -q`
  - Result: passed, 4 tests.
- `uv run pytest tests/unit/test_fixture_corpus.py::test_fixture_corpus_replay_matches_checkpoint_and_compact_projection -q`
  - Result: passed, 1 test.
- `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_lease_event_payloads.py -q`
  - Result: passed, 142 tests.
- `uv run ruff check src/orchestrator/graph tests/unit`
  - Result: passed.
- `uv run pyright src/orchestrator/graph tests/unit`
  - Result: passed, 0 errors.
- `uv run pytest tests/ -k graph -q`
  - Result: passed, 837 tests.
- `uv run ruff check .`
  - Result: passed.

## Planner / Session Event Payload Slice

Status: complete in working tree, pending commit.

Scope:
- Added a typed event payload model for `session_state_changed` in
  `src/orchestrator/graph/models.py`.
- Routed current `session_state_changed` producers through typed payload
  validation and JSON dumping, retaining explicit `carryover_record_id: null`
  so stale carryovers are cleared.
- Routed projection reducer consumption through the typed payload model instead
  of raw `event.payload.get(...)` access.
- Added `carryover_record_id` to the graph projection payload field allowlist so
  checkpoint/compact replay preserves reducer-read planner session carryovers.

Legacy normalization:
- Unknown top-level session payload keys are moved under `extra`.
- Legacy non-string `session_id`, `state`, `node_id`, and
  `carryover_record_id` values are moved under `extra`.
- Legacy non-integer `lease_generation` values are moved under `extra`.
- Explicit historical `carryover_record_id: null` continues to clear/set the
  carryover slot to `None`.

Dropped write-only keys:
- None. Legacy free-form top-level keys are preserved under `extra`.
- `lease_generation` remains a typed audit/detail field; it is not consumed into
  the planner session projection.

RED:
- `uv run pytest tests/unit/test_planner_session_event_payloads.py -q`
  - Result: failed during collection with
    `ImportError: cannot import name 'PlannerSessionStateChangedPayload' from 'orchestrator.graph'`.

GREEN:
- `uv run pytest tests/unit/test_planner_session_event_payloads.py -q`
  - Result: passed, 5 tests.
- `uv run pytest tests/unit/test_fixture_corpus.py::test_fixture_corpus_replay_matches_checkpoint_and_compact_projection -q`
  - Result: passed, 1 test.
- `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_planner_session_event_payloads.py tests/unit/test_lease_event_payloads.py -q`
  - Result: passed, 147 tests.
- `uv run pytest tests/ -k graph -q`
  - Result: passed, 837 tests.
- `uv run ruff check .`
  - Result: passed.
- `uv run pyright src/orchestrator/graph tests/unit/test_planner_session_event_payloads.py`
  - Result: passed, 0 errors.

## Patch Event Payload Slice

Status: complete in working tree, pending commit.

Scope:
- Added typed event payload models for `graph_patch_accepted`,
  `graph_patch_rejected`, and replay-only proposal/status aliases in
  `src/orchestrator/graph/models.py`.
- Routed current `graph_patch_accepted` and `graph_patch_rejected` producers
  through typed payload validation and JSON dumping.
- Routed projection consumption for accepted patches, proposal blockers, and
  graph patch attempts through typed patch payload models instead of raw event
  payload reads.
- Removed stale allowlist-guard exclusions for raw patch fields no longer read
  directly by the `reduce_event` closure.

Legacy normalization:
- Unknown top-level patch event keys are moved under `extra`.
- `successor_planner_node_ids` is normalized to string entries only.
- Sparse historical `graph_patch_accepted` events with only `patch_id` still
  close open proposal blockers; accepted-patch planner indexes are updated only
  when `proposed_by_node_id` is present.
- Replay-only proposal/status aliases accept `proposal_id` or `patch_id` and
  preserve free-form compatibility keys under `extra`.

Dropped write-only keys:
- None. Legacy free-form top-level keys are preserved under `extra`.
- Diagnostic rejected-patch fields such as `read_set_diff`, `diagnostics`,
  `budget`, and `count` remain typed event fields; they are not
  reducer-critical.

RED:
- `uv run pytest tests/unit/test_patch_event_payloads.py -q`
  - Result: failed during collection with
    `ImportError: cannot import name 'GraphPatchAcceptedPayload' from 'orchestrator.graph'`.

GREEN:
- `uv run pytest tests/unit/test_patch_event_payloads.py -q`
  - Result: passed, 6 tests.
- `uv run pytest tests/unit/test_fixture_corpus.py::test_fixture_corpus_replay_matches_checkpoint_and_compact_projection -q`
  - Result: passed, 1 test.
- `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_patch_event_payloads.py -q`
  - Result: passed, 144 tests.
- `uv run ruff check src/orchestrator/graph tests/unit/test_patch_event_payloads.py tests/unit/test_graph_payload_field_allowlists.py`
  - Result: passed.
- `uv run pyright src/orchestrator/graph tests/unit/test_patch_event_payloads.py`
  - Result: passed, 0 errors.

## Decision Event Payload Slice

Status: complete.

Implementation commits:
- `6a6686ab8c18e15c472b27f6c0e88e3c457936f8` — typed decision event payloads.
- `9402c3f5d64fa29140f3eeeb29d629c232689c58` — preserve legacy decision alias fallback.

Scope:
- Added typed payloads for `appeal_opened`, `approval_decision_recorded`,
  `authority_decision_recorded`, and `oversight_decision_recorded`.
- Routed current decision/appeal producers through model validation and JSON
  dumping, and reducers through typed payload parsing.

Legacy normalization:
- Membership identifiers, legacy `decision`/`outcome`/`verdict` aliases, and
  boolean `approved` fallback remain replay-compatible.
- Unknown top-level keys move under the single `extra` map; `decider` and
  `scope` remain intentionally flexible.
- An obsolete earlier decision alias no longer masks a recognized later alias.

Dropped write-only keys:
- None.

RED:
- `uv run pytest tests/unit/test_decision_event_payloads.py -q`
  - Result: failed during collection with missing `AppealOpenedPayload` export.

GREEN (independently rerun by a fresh verifier):
- `uv run pytest tests/unit/test_decision_event_payloads.py -q`
  - Result: passed, 7 tests.
- `uv run pytest tests/unit/test_fixture_corpus.py::test_fixture_corpus_replay_matches_checkpoint_and_compact_projection -q`
  - Result: passed, 1 test.
- `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_decision_event_payloads.py -q`
  - Result: passed, 145 tests.
- `uv run pytest tests/ -k graph -q`
  - Result: passed.
- `uv run ruff check .`
  - Result: passed.
- `uv run pyright src/orchestrator/graph tests/unit/test_decision_event_payloads.py`
  - Result: passed, 0 errors.
