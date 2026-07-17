# W5 Typed Payloads Progress Ledger

> **Compatibility-era sections superseded 2026-07-15:** The database and durable
> event history were reset. Historical descriptions below of payload `extra`
> maps, replay aliases, tolerant normalization, and pending commits record the
> state at the time only; they are not current requirements. The authoritative
> current state is the queue summary immediately below and the final closeout
> section. The residual execution plan is
> `docs/superpowers/plans/2026-07-15-w5-residual-completion.md`.

## Authoritative Current Queue

Status: **W5 closed; no W5 tasks remain queued.**

- [x] Canonical ownership for all 46 event names.
- [x] Exact strict payload models and explicit retention specs for all 46 events.
- [x] Producer-boundary validation and canonical JSON serialization.
- [x] Compatibility aliases, payload `extra`, generic record fallbacks, mapping
  facades, and graph before validators removed.
- [x] All 22 output-record discriminators and strict file-state/gatekeeper
  envelopes validated.
- [x] Four generated model-owned retention tuples verified.
- [x] All 23 commands use strict payloads, exact typed handlers, separate
  runtime context, and shared API/domain schemas.
- [x] Strict exported `GradeRow` and typed verification grades.
- [x] Batch 1, Batch 2, and final full verification gates passed.
- [x] Event/projection inventories refreshed and W5 specification closed.
- [x] Final whole-branch review correction: canonical model dumping, exact
  producer-required event cores, strict shared identifiers, bounded redacted
  command validation details, and `StoredArtifactRef` digest consistency.

W5.5 durable artifact storage and truncation recovery are a separate pending
project, not an open W5 queue item.

The final-review correction does not reopen W5 and does not implement W5.5.
Generated retention is now 105/144/160/92 after retaining newly required reducer
identities. Exact RED/GREEN and gate evidence is recorded in
`.superpowers/sdd/final-review-fix-report.md`.

## Final Whole-Branch Review Fix

Status: implemented and verified locally; **final approval is not yet claimed**.

- Design: `ArtifactRootResolver` resolves each run's linked worktree to its
  owning main checkout. `ArtifactStoreResolver` serves authenticated range reads,
  graph dispatch uses that same resolver, and `ProjectArtifactGarbageCollector`
  marks only surviving runs that resolve to the deleted run's root. Request,
  lifespan/background/MCP factory, and graph runner composition inject the same
  resolver/coordinator.
- Publication safety: `ArtifactRootLock` is an advisory filesystem `flock` held
  from check-output externalization through durable callback append. GC acquires
  the same lock before loading retained events; failed append releases it and
  leaves a grace-eligible orphan.
- RED evidence:
  - `uv run pytest tests/unit/test_artifact_gc.py -q` — collection failed with
    `ImportError: cannot import name 'ArtifactRootLock'`.
  - `uv run pytest tests/integration/test_artifact_api.py::test_multi_project_artifact_read_and_delete_gc_use_the_run_project_root -q`
    — failed `assert 404 == 206`, proving the server-rooted CAS was used instead
    of the project-B run CAS.
- GREEN evidence:
  - `uv run pytest tests/unit/test_artifact_gc.py tests/integration/test_artifact_api.py tests/integration/test_check_output_artifacts.py tests/integration/test_workflow_service.py -q`
    — `61 passed`.
- Commits: `0770197e6 Fix artifact project-root lifecycle coordination`.
- Remaining status: complete local implementation and verification only; no final
  approval statement.

## Second Final Review Fix

Status: implemented; final approval pending. The durable resolver falls back to
the persisted repository identity after linked-worktree removal, and root locks
use a stable private `.orchestrator` metadata parent even before CAS creation.
RED: absent-root lock regression failed because publication and sweep used
different paths. GREEN: `uv run pytest tests/unit/test_artifact_gc.py tests/integration/test_artifact_api.py -q` — `17 passed`.
The real linked-worktree removal API/GC regression subsequently passed in the
focused suite (`10 passed in 3.86s`). Final gates: graph/artifact selection
`1023 passed in 60.78s`; full suite `4821 passed, 3 skipped, 3 warnings in
104.90s`; Ruff, Pyright, format check, and `git diff --check` passed. Final
approval remains pending; commit evidence follows.
Implementation commit: `36129a3ae Harden artifact root fallback and locking`.

## Historical Execution Evidence

Unless a section explicitly says it is authoritative current state, every
status line below this heading reports status at the time that slice or gate was
run. In particular, `pending commit` text is historical and is fully superseded
by the closed queue above. Historical test commands and results are preserved
unchanged.

Seed branch: `main`
Seed SHA: `bd41b5b24756fec7441cbfd0ee150739b9afede7`
Work branch: `codex/w5-typed-payloads`

## Phase 0 - Corpus Replay Parity Safety Net

Historical status at the time: complete in working tree, pending commit.

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

Historical status at the time: complete in working tree, pending commit.

Artifact:
- `docs/dynamic-graph/w5-event-payload-inventory.md`

Notes:
- Surveyed `_commands.py` producer `make_event(...)` sites, confirmed
  `compiler.py` has no `make_event(` sites, and grouped reducer-consumed event
  payloads into implementation families.
- No production code or test changes were made for the inventory.

## Cleanup Event Payload Slice

Historical status at the time: complete in working tree, pending commit.

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

Historical status at the time: complete in working tree, pending commit.

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
- `resource_claims` uses strict `ResourceClaimProjection` values with canonical
  `paths` only. A malformed legacy singular `path` claim fails validation and
  is dropped during checkpoint restoration; no legacy path normalization occurs.
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

Historical status at the time: complete in working tree, pending commit.

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

Historical status at the time: complete in working tree, pending commit.

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

## Requirement and Evidence Event Payload Slice

Status: complete.

Implementation commit:
- `73c68b75a84d88855533124175a6296e4ae51835` — typed requirement, support
  evidence, and authority-resolution payloads with compact replay retention.

Scope:
- Added `RequirementRevisionPayload`, `SupportEvidencePayload`, and
  `RequirementAuthorityResolutionPayload` and exported them through the graph
  public API.
- Routed current requirement/support producers through typed validation and
  JSON dumping.
- Routed recorded and replay-only requirement, support, and authority aliases
  through typed parsing in both normal reduction and the separate full-history
  authority blocker scan.
- Retained authority/classification inputs needed by light and summary replay.

Legacy normalization:
- Preserved requirement, revision, version, proposal, patch, support, and edge
  identifier aliases; classification aliases; strict authority/behavior
  booleans; prior-version metadata; nested legacy requirement identity; and
  support status metadata.
- Invalid typed scalars and unknown top-level keys move under the single
  inherited `extra` map.
- Sparse and malformed history keeps the prior skip/default behavior.
- `change_classification` is retained in light/summary payloads and SQLite
  integer `new_behavior` values are normalized to booleans before strict model
  validation.

Dropped write-only keys:
- None. Legacy free-form top-level keys are preserved under `extra`.

RED:
- `uv run pytest tests/unit/test_requirement_evidence_event_payloads.py -q`
  - Result: failed during collection with
    `ImportError: cannot import name 'RequirementRevisionPayload' from 'orchestrator.graph'`.
- Compact replay regression tests initially demonstrated that an omitted
  `change_classification` produced `initial`/`False`, and integer
  `new_behavior=1` was moved under `extra` instead of projecting authority.

GREEN (independently rerun by a fresh final verifier):
- `uv run pytest tests/unit/test_requirement_evidence_event_payloads.py -q`
  - Result: passed, 9 tests.
- `uv run pytest tests/unit/test_fixture_corpus.py -q`
  - Result: passed, 7 tests.
- `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_requirement_evidence_event_payloads.py -q`
  - Result: passed, 147 tests.
- `uv run pytest tests/ -k graph -q`
  - Result: passed, 844 tests.
- `uv run ruff check .`
  - Result: passed.
- `uv run pyright src/orchestrator/graph tests/unit`
  - Result: passed, 0 errors.
- `git diff --check`
  - Result: passed.
- Commit hooks:
  - Result: 4,508 backend tests passed, 4 skipped; Ruff, formatting, secret
    detection, Pyright, module-import, signal-routing, UI lint, and UI
    typecheck hooks passed.

## Lifecycle, Callback, Retry, and Audit Event Payload Slice

Status: complete.

Implementation commit:
- `ad25bfa9b4c4a34fc7d88b1ec8c84fcebfd57aec` — typed lifecycle,
  command-rejection, callback, retry, heartbeat, agent-death, and dead-input
  event payloads.

Scope:
- Added and exported `RunLifecycleChangedPayload`, `CommandRejectedPayload`,
  `CallbackAcceptedPayload`, `CallbackRejectedPayload`,
  `CallbackDuplicateReturnedPayload`, `RuntimeRetryScheduledPayload`,
  `HeartbeatRecordedPayload`, `AgentDiedPayload`, and
  `DeadInputDetectedPayload`.
- Routed all ten current event names through typed validation and JSON dumping.
- Parsed lifecycle, accepted-callback, and runtime-retry payloads in reducers;
  audit-only and rejected/duplicate events remain projection-neutral.
- Retained `retry_not_before` across graph, light, summary-rebuild, and
  node-detail reconstruction.

Legacy normalization:
- All historical fields remain optional and unknown/malformed top-level keys
  move under the single inherited `extra` map.
- Explicit callback `payload=None` remains present in JSON output.
- Malformed blocker lists remain preserved under `extra`.
- `CommandRejectedPayload.base_graph_position` intentionally accepts integer
  or string rejected-submit evidence; boolean impostors move under `extra`.
- Sparse lifecycle/callback/retry history retains its prior skip/default
  behavior.

Dropped write-only keys:
- None. Legacy top-level evidence is preserved under `extra`.

RED:
- `uv run pytest tests/unit/test_lifecycle_event_payloads.py -q`
  - Result: failed during collection with
    `ImportError: cannot import name 'AgentDiedPayload' from 'orchestrator.graph'`.
- Focused malformed-blocker replay test initially failed with a Pydantic
  validation error before whole-list preservation was added.

GREEN (independently rerun on the final formatted diff):
- `uv run pytest tests/unit/test_lifecycle_event_payloads.py -q`
  - Result: passed, 11 tests.
- `uv run pytest tests/unit/test_fixture_corpus.py -q`
  - Result: passed, 7 tests.
- `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_lifecycle_event_payloads.py -q`
  - Result: passed, 149 tests.
- `uv run pytest tests/ -k graph -q`
  - Result: passed, 844 tests.
- `uv run ruff check .`
  - Result: passed.
- `uv run ruff format --check src/orchestrator/graph/__init__.py src/orchestrator/graph/_commands.py src/orchestrator/graph/models.py src/orchestrator/graph/projections.py src/orchestrator/graph_runtime/store.py tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_lifecycle_event_payloads.py`
  - Result: 7 files already formatted.
- `uv run pyright src/orchestrator/graph tests/unit`
  - Result: passed, 0 errors.
- `git diff --check`
  - Result: passed.
- Commit hooks:
  - Result: backend pytest, Ruff, formatting, secret detection, Pyright,
    module-import, signal-routing, UI lint, and UI typecheck hooks passed.

## Node Created Event Payload Slice

Status: complete.

Scope:
- Added and exported `NodeCreatedPayload`; compiler seeding and command-side
  node producers now validate and JSON-dump the typed payload.
- Reducers parse the typed envelope while retaining all node creation,
  planner, recovery, authority, and compact-replay fields.
- Retained node-created fields across projection, light, summary, and
  node-detail reconstruction. Recovery nodes are indexed exactly once.

Legacy normalization:
- Malformed and unknown legacy top-level values remain under the inherited
  single `extra` map; no durable history was rewritten.

RED:
- `uv run pytest tests/unit/test_node_created_event_payloads.py -q`
  - Result: 1 failed, 13 passed; the regression asserted that recovery index
    entries were duplicated (`['recovery-1', 'recovery-1']`).

GREEN (independently rerun by a fresh verifier):
- `uv run pytest tests/unit/test_node_created_event_payloads.py -q`
  - Result: passed, 14 tests.
- `uv run pytest tests/unit/test_fixture_corpus.py -q`
  - Result: passed, 7 tests.
- `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_node_created_event_payloads.py -q`
  - Result: passed, 152 tests.
- `uv run pytest tests/ -k graph -q`
  - Result: passed (exit 0; 844 selected).
- `uv run ruff check .`
  - Result: passed.
- `uv run pyright src/orchestrator/graph tests/unit/test_node_created_event_payloads.py`
  - Result: passed, 0 errors.
- `git diff --check`
  - Result: passed.

## Remaining Node Lifecycle Event Payload Slice

Status: complete.

Scope:
- Added and exported typed payloads for node state, retirement, readiness,
  deferral, authority, and all suspect replay aliases.
- Producers validate and JSON-dump typed payloads; normal reduction and the
  suspect/deferral auxiliary scans parse typed payloads before use.

Legacy normalization:
- Membership and nested authority fallbacks are retained. Malformed
  `retry_not_before` and `prompt_summary` values relocate to inherited
  `extra` rather than rejecting durable history.

RED:
- `uv run pytest tests/unit/test_node_lifecycle_event_payloads.py -q`
  - Result: failed during collection with missing `NodeAuthorityChangedPayload`.
- Added replay regressions for malformed retry timing and prompt summaries;
  before the normalizer fix, malformed values raised validation errors.

GREEN (independently rerun by a fresh final verifier):
- `uv run pytest tests/unit/test_node_lifecycle_event_payloads.py -q`
  - Result: passed, 8 tests.
- Combined corpus/projection/allowlist/lifecycle checks
  - Result: passed, 13 tests.
- `uv run pytest tests/ -k graph -q`
  - Result: passed, 844 tests (112.09s).
- `uv run ruff check .`
  - Result: passed.
- `uv run pyright src/orchestrator/graph tests/unit/test_node_lifecycle_event_payloads.py`
  - Result: passed, 0 errors.
- `git diff --check`
  - Result: passed.

## W5 Residual Verification Benchmarks (2026-07-15)

The representative focused, graph, repository, lint, and scoped type-check
gates were each run with `/usr/bin/time -p`. Serial and xdist graph selections
collected the same 844 tests and both passed.

| Command | Result | real | user | sys |
|---|---|---:|---:|---:|
| `uv run pytest tests/unit/test_node_lifecycle_event_payloads.py -q` | 8 passed | 2.15s | 6.11s | 1.34s |
| `uv run pytest tests/unit/test_fixture_corpus.py -q` | 7 passed | 8.17s | 13.36s | 5.02s |
| `uv run pytest tests/ -k graph -q` | 844 passed | 125.11s | 249.87s | 42.54s |
| `uv run pytest tests/ -k graph -q -n auto --dist worksteal` | 844 passed | 52.24s | 262.82s | 40.61s |
| `uv run pytest tests/ -q -n auto --dist worksteal` | 4542 passed, 3 skipped, 3 warnings | 100.64s | 438.17s | 135.70s |
| `uv run ruff check .` | passed | 0.15s | 0.03s | 0.07s |
| `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime` | 0 errors, 0 warnings, 0 informations | 3.93s | 6.62s | 0.30s |

## W5 Residual Verification Matrix

| Stage | Builder gate | Fresh verifier gate |
|---|---|---|
| Batch 1 iteration | Changed focused files + fixture corpus | none |
| Batch 1 candidate | none | focused aggregate, fixture corpus, graph selection with xdist, Ruff, scoped Pyright |
| Batch 2 iteration | Changed command/API/model files | none |
| Batch 2 candidate | none | command aggregate, API integration, graph selection with xdist, Ruff, scoped Pyright |
| Closeout | none | full backend with xdist, Ruff, final Pyright |

## Canonical Event Ownership And Fixtures

Status: complete.

Scope:
- Added the immutable canonical event registry, deriving canonical names from
  current producers plus the explicit external `lease_suspended` ingress.
- Migrated graph fixtures and projection coverage from replay-only aliases to
  canonical check-result and requirement-revision events.
- Removed replay-only proposal, environment-failure, requirement/support/
  authority, and suspect-resolution consumer branches.

RED:
- `uv run pytest tests/unit/test_graph_event_registry.py -q`
  - Result: failed during collection because `CANONICAL_EVENT_TYPES` was not
    exported from `orchestrator.graph`.

GREEN:
- `uv run pytest tests/unit/test_graph_event_registry.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_projections.py tests/unit/test_patch_validator.py -q`
  - Result: passed, 189 tests.

## Batch 1 Verification Gate (2026-07-16)

Status: complete.

Verified head:
- `f837206d12a6e7f9c2c0086b72c276d237b45d7b` (`Remove legacy selector compatibility`).

Fresh verifier verdict:
- PASS. Every required command exited 0, and the source review found no surviving
  Batch 1 compatibility layer or W5.5 implementation leakage.

Commands and timings:

| Command | Result | real | user | sys |
|---|---|---:|---:|---:|
| `uv run pytest tests/unit/test_graph_event_registry.py tests/unit/test_w5_compatibility_removal.py tests/unit/test_output_record_event_payloads.py tests/unit/test_record_routing_event_payloads.py tests/unit/test_file_state_gatekeeper_event_payloads.py tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_fixture_corpus.py -q -n auto --dist worksteal` | 82 passed in 4.01s | 4.38s | 17.38s | 2.72s |
| `uv run pytest tests/ -k graph -q -n auto --dist worksteal` | 904 passed in 56.72s | 57.06s | 276.49s | 41.49s |
| `uv run ruff check .` | all checks passed | 0.06s | 0.03s | 0.05s |
| `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime tests/unit` | 0 errors, 0 warnings, 0 informations | 3.54s | 6.49s | 0.26s |
| `git diff --check` | passed, no output | 0.01s | 0.00s | 0.00s |

Event ownership:
- The immutable registry contains 46 canonical names: 45 are owned by the
  declared internal producers and `lease_suspended` is the sole external name.
- `lease_suspended` remains justified because stale callback/worker ingress can
  surface it even though no current command producer emits it. It has a strict
  payload model and explicit retention spec.
- No removed event name occurs under `src/`; retired names are disjoint from
  canonical and producer-owned names. Fixtures contain canonical event names
  only, and ownership validation rejects omissions, stale registrations, and
  retired-name reintroduction.

Compatibility deletion:
- Source searches found none of `LegacyOutputRecord`, `GraphPatchStatusPayload`,
  `RequirementAuthorityResolutionPayload`, `_legacy_output_record_payload`,
  `_generic_output_record_payload`, `_legacy_requirement_evidence_blockers`,
  `_DictCompatibleProjection`, or `normalize_legacy_membership`.
- The removed selector symbols `_LEGACY_SELECTOR_KIND_MAP` and
  `_normalize_legacy_selector`, legacy `record_kinds`/`value_matches` handling,
  and `RecordSelector`'s historical `mode="before"` validator are absent.
  `RecordSelector` now accepts only its strict discriminated canonical union.
- The only `mode="before"` validator under `orchestrator.graph` is the separate
  planner macro invocation boundary (`name`/`tool` to `macro`); no event payload,
  record, selector, or projection uses a historical pre-validator.
- Strict event payloads forbid unknown top-level fields; strict typed-record
  roots do the same. No event payload model or generated retention allowlist
  exposes a top-level `extra` field.
- `EdgeProjection`, `InputBindingProjection`, and `LeaseProjection` are
  attribute-only models and define no mapping facade (`get`, `keys`, `items`,
  `values`, `__getitem__`, `__iter__`, or `__contains__`).

Records:
- Output acceptance dispatches through the explicit 22-entry
  `OUTPUT_RECORD_MODELS_BY_TYPE` discriminator map. Missing and unknown nonempty
  discriminators are rejected; no generic output-record fallback survives.
- Canonical record fields are parsed into typed record models before projection;
  nested verification values and grade rows reject unknown fields.
- `gap_plan`, `gap_classification`, and `classified_gap` are explicit current
  discriminators in `GapClassificationRecord` and the output-record model map.
  Their full record contracts require `record_kind`, `record_type`, producer,
  port, `GapClassification` schema, and typed value. They are current dynamic
  gap-planner record shapes, not selector aliases or selector normalization.
  The canonical selector remains `record_type="gap_classification"`; current
  `GapClassification` schema recognition only matches those typed records.

File-state and gatekeeper:
- Accepted/rejected file-state events use strict flat canonical file-state
  records and require the exact `file_state` discriminator.
- Gatekeeper verdict and cost models reject unknown, negative, fractional
  integer, and wrong-type values. Summary retention preserves `consult_id`,
  `model_id`, input/output/cache token counts, `item_count`, `cost_usd`, and
  `wall_time_ms`; the reconstruction parity test confirms no canonical or cost
  field is dropped.

Allowlists and artifact boundary:
- Immutable per-event specs exactly generate the sorted unique projection,
  light, summary, and node-detail allowlists with 98, 138, 157, and 81 fields,
  respectively. Every modeled event has a spec, retained keys are model-owned,
  `extra` is absent, and the reducer AST guard has no uncovered or stale entry.
- `StoredArtifactRef` is identity-only: `artifact_id`, `content_hash`,
  `size_bytes`, `media_type`, `encoding`, and `storage_uri`. It is exported but
  is not attached to `CheckResultValue.stdout`/`stderr` or any producer/storage
  path.
- W5.5 remains deferred atomically: no artifact file store, reference-field
  cutover, persistence, hydration, garbage collection, event-aware SQL, or
  check-output cutover was added. Current `stdout`/`stderr` complete-value and
  truncation behavior remains unchanged. Complete nested `value` retention and
  its read amplification are explicitly deferred to the W5.5 artifact cutover.

## Batch 2 Verification Gate (2026-07-16)

Status: complete.

Verified head:
- `3282dee88c0f8227bf0984e3046d1a9404e892db` (`Add strict verification grade rows`).

Fresh verifier verdict:
- PASS. Every required command exited 0. Independent source review confirmed
  the exact 23-spec command registry, typed handlers and attribute access,
  shared API/domain validation, strict exported grade rows, preserved HTTP-only
  request constraints, and no command compatibility or artifact implementation
  leakage.

Commands, counts, and wall-clock timings:

| Command | Result | elapsed |
|---|---|---:|
| `uv run pytest tests/unit/test_lifecycle_command_payloads.py tests/unit/test_scheduling_command_payloads.py tests/unit/test_callback_patch_command_payloads.py tests/unit/test_decision_record_command_payloads.py tests/unit/test_graph_commands.py tests/unit/test_graph_models.py tests/integration/test_graph_api.py tests/integration/test_graph_decisions_api.py -q -n auto --dist worksteal` | 379 passed in 4.77s | 6.26s |
| `uv run pytest tests/ -k graph -q -n auto --dist worksteal` | 934 passed in 60.24s | 64.59s |
| `uv run ruff check .` | all checks passed | 0.13s |
| `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime src/orchestrator/api src/orchestrator/workflow tests/unit tests/integration` | 0 errors, 0 warnings, 0 informations | 6.48s |
| `git diff --check` | passed, no output | 0.02s |

Command registry and handler groups:
- `COMMAND_SPECS` contains exactly the required 23 names and maps each name to
  one `StrictCommandPayload` subclass with `extra="forbid"` and strict scalar
  validation. `apply_command` performs the sole raw ingress validation and
  passes the resulting model to the registered handler.
- Lifecycle, scheduling, callback, patch, and record/evaluation handlers each
  annotate `payload` with their concrete registered model. Their delegates in
  `_commands.py` consume model attributes; no registered handler accepts a raw
  command dictionary or installs a dictionary compatibility adapter.
- `GraphCommandContext` owns run/head/actor state and `PatchCommandContext` owns
  proposer/role provenance. Controller, runtime, API, scenario, and workflow
  callers pass context separately. Strict payloads reject `run_id`,
  `_current_graph_position`, actor/proposer fields, and ignored patch runtime
  identity fields.
- Command models reject scalar callback payloads, integer coercion, macro
  `name`/`tool`, `carryover_summary`, decision `approved`/`outcome`/`verdict`,
  `defer`/`grant`/`deny`, and requirement/support version aliases. No handler
  restores those historical command aliases or scalar coercion shims.

API reuse and HTTP constraints:
- `RecordGraphDecisionRequest` inherits `RecordDecisionCommand`; no API copy of
  its decision validator exists. `SubmitGraphPatchRequest` and
  `SubmitPatchCommand` share `PatchCommandFields`; no patch validator is
  duplicated between API and domain layers.
- HTTP-only constraints remain explicit: decision node/record IDs and values
  retain nonempty length bounds, patch/rationale IDs retain length and character
  patterns, HTTP patch positions remain nonnegative, and `ops` remains required.
  The focused API suite covers these constraints and removed aliases with 422s.
- Actor, proposer, run ID, and graph position are built from authenticated or
  server state and supplied through command context, never accepted from the
  request payload.

Grade rows and artifact boundary:
- `GradeRow` inherits `StrictNestedModel`, requires `requirement_id` and `grade`,
  rejects unknown fields, keeps `reason` optional and the grade string open,
  types `VerificationReportValue.grades`, and is exported from
  `orchestrator.graph`.
- The Batch 2 source diff contains no artifact-named file and adds no artifact
  store, persistence, hydration, garbage collection, reference cutover, or
  `stdout`/`stderr` cutover. Existing `StoredArtifactRef` remains an exported
  identity model only; artifact implementation remains deferred.

## Final W5 Closeout (2026-07-16)

Status: **complete**.

Verified source head:
- `b4da6182b` (`Remove validation locations from durable reasons`).
- The documentation closeout is the commit containing this update and does not
  self-reference its own hash.

Completion criteria:
- Canonical event ownership: 46 canonical names, 45 internally producer-owned
  and strict `lease_suspended` as the sole external-ingress event.
- Exact event coverage: `CANONICAL_EVENT_TYPES`, `EVENT_PAYLOAD_MODELS`, and
  `EVENT_PAYLOAD_SPECS` each contain the same 46 names. All 46 models reject
  unknown top-level fields; the two flat root envelopes delegate this invariant
  to their strict canonical record roots.
- Compatibility removal: obsolete event aliases, generic/legacy record paths,
  projection mapping facades, selector normalization, payload `extra`, and graph
  before validators are absent from production source.
- Record envelopes: the explicit 22-entry `OUTPUT_RECORD_MODELS_BY_TYPE` map
  validates complete canonical records and rejects missing/unknown
  discriminators. File-state accepted/rejected envelopes and nested gatekeeper
  verdict/cost rows are strict.
- Generated retention: projection/light/summary/node-detail allowlists are
  sorted, unique, model-owned, and contain 105/144/160/92 fields after the
  final-review required-identity correction.
- Commands: all 23 `COMMAND_SPECS` payloads inherit strict validation, and all
  23 handlers accept their exact registered payload model.
- Durable rejection safety: command ingress, callback output records, patch
  parsing/macro expansion, selector/request records, seed records, decisions,
  and gatekeeper payloads use one bounded graph-internal renderer. Validation
  output uses only caller-supplied static context, literal `payload`, safe error
  type, and fixed message (maximum 8 errors and 1,000 characters). It never
  persists rejected top-level or nested field names, discriminator values,
  input, or user-derived messages; arbitrary `TypeError`/`ValueError` paths use
  fixed codes and messages.
- Callback payload hashes use strict nonblank `CommandIdentifier`; decision
  string deciders use strict nonblank `ActorLabel` while valid `Actor` values
  remain accepted.
- API reuse: decision and patch HTTP schemas reuse command-domain fields while
  retaining HTTP-only constraints and server-owned context.
- Grade rows: `GradeRow` is strict and exported; verification report grades are
  typed.
- Fresh Batch 1 and Batch 2 verifier evidence remains recorded above. The final
  closeout independently reran focused and full gates at the corrected head.

Static compatibility evidence:

```bash
rg -n 'mode="before"|mode='"'"'before'"'"'|LegacyOutputRecord|_DictCompatibleProjection|payload\.extra' src/orchestrator/graph
```

Result: no matches.

```bash
rg -n 'environment_failure_accepted|check_result_classified|proposal_opened|requirement_amended|support_edge_recorded|node_suspect_resolved|node_suspect_cleared' src tests
```

Result: no matches under `src`. Matches under
`tests/unit/test_graph_event_registry.py` are negative-test data proving removed
names are not canonical or producer-owned. The
`tests/fixtures/graph/node_lifecycle_check.yaml` occurrence of
`environment_failure_accepted` is a current diagnostic `trigger` inside
canonical `node_state_changed`, not an event type or compatibility consumer.

The broader deleted-symbol search also returned no matches under `src` for
`GraphEventPayloadBase.extra`, `LeaseEventPayloadBase`,
`LifecycleEventPayloadBase`, `LegacyOutputRecord`, `GraphPatchStatusPayload`,
`RequirementAuthorityResolutionPayload`, `_DictCompatibleProjection`,
`_legacy_output_record_payload`, `_generic_output_record_payload`,
`_legacy_requirement_evidence_blockers`, `_LEGACY_SELECTOR_KIND_MAP`,
`_normalize_legacy_selector`, or `normalize_legacy_membership`.

Final commands, counts, and timings at `b4da6182b`:

| Command | Result | Timing |
|---|---|---:|
| `uv run pytest tests/unit/test_graph_gatekeeper.py tests/unit/test_graph_macros.py tests/unit/test_graph_commands.py tests/unit/test_final_review_contracts.py tests/unit/test_callback_patch_command_payloads.py tests/integration/test_graph_api.py tests/integration/test_graph_decisions_api.py tests/integration/test_graph_fr07_acceptance.py -q` | 307 passed | 5.87s |
| source commit pytest hook | passed | n/a |
| `uv run ruff check .` | all checks passed | n/a |
| `uv run ruff format --check .` | 702 files already formatted | n/a |
| `uv run pyright` | 0 errors, 0 warnings, 0 informations | n/a |
| `git diff --check` | passed, no output | n/a |
| source commit hooks | Ruff, format, secret detection, Pyright, pytest, module imports, signal routing, UI lint, and UI typecheck passed; enum drift skipped with no relevant files | n/a |

Historical closeout evidence: the earlier source head
`29c5264d9` passed 4,779 tests with 3 skips and 3 existing warnings before the
final static-location correction. The still-earlier source head
`bafeb650d27884ae5584f1fb4b4378780b4f587f`, 145-test focused run, and 4,756
passed full run remain useful chronology but are superseded by the final source
head and evidence above.

Final metrics recomputed from current source:

| Metric | Baseline | Final | Delta |
|---|---:|---:|---:|
| `isinstance(` in `_commands.py` and `projections.py` | 603 | 465 | -138 |
| `dict[str, Any]` in `projections.py` | 174 | 136 | -38 |
| Direct `event.payload.get(` diagnostic | n/a | 28 | n/a |
| Total `payload.get(` diagnostic | n/a | 89 | n/a |
| Graph `mode="before"` diagnostic | n/a | 0 | n/a |

W5.5 deferral remains explicit and atomic. This closure does not claim durable
stdout/stderr artifact persistence, reference-field cutover, bounded hydration,
garbage collection, event-aware artifact SQL, or recovery of content beyond the
current 20,000-character truncation. Those remain pending in
`docs/superpowers/specs/2026-07-15-w5-artifact-output-design.md` and
`docs/superpowers/plans/2026-07-15-w5-artifact-output.md`.

## W5.5

Status: **all five implementation tasks complete; final whole-branch review pending**.

Execution identity:
- Seed branch: `main`.
- Seed SHA: `67f628ae590f0fbbb6edae45c80344e1b67c5e63`.
- Required W5 ancestor: `67f628ae590f0fbbb6edae45c80344e1b67c5e63`.
- Work branch: `codex/w5-artifact-output`.
- Isolated worktree: `worktrees/w5-artifact-output`.

Durable task queue:
- [x] Task 1: filesystem artifact store.
- [x] Task 2: atomic check-output externalization.
- [x] Task 3: explicit prompt and API hydration.
- [x] Task 4: mark-and-sweep garbage collection.
- [x] Task 5: final artifact verification and closeout.

Evidence:
- Setup: `uv sync` completed in the isolated worktree.
- Clean baseline: `uv run pytest tests/ -q -n auto --dist worksteal` passed
  with 4,781 tests passed, 3 skipped, and 3 existing warnings in 118.28s.

### Task 1: Filesystem Artifact Store

Status: complete; independent task review passed specification and code-quality
gates.

RED evidence:
- `uv run pytest tests/unit/test_artifact_store.py -q`
  - Result: collection failed as expected with
    `ModuleNotFoundError: No module named 'orchestrator.artifacts'`.

GREEN evidence:
- `uv run pytest tests/unit/test_artifact_store.py -q`
  - Result: passed, 5 tests.
- `uv run ruff check src/orchestrator/artifacts tests/unit/test_artifact_store.py`
  - Result: all checks passed.
- `uv run pyright src/orchestrator/artifacts tests/unit/test_artifact_store.py`
  - Result: 0 errors, 0 warnings, 0 informations (with only the available-update notice).
- `uv run ruff format --check src/orchestrator/artifacts tests/unit/test_artifact_store.py`
  - Result: all 5 files already formatted.
- `git diff --check`
  - Result: passed, no output.

Implementation commit: `550c45f6596c2b2049948dbbf3a23cd86b9ee1a2`
(`Implement filesystem artifact store`).

Review Fix evidence:
- Added a regression proving `FilesystemArtifactStore` construction does not
  create its root; root and hash-directory setup now runs inside `_put_sync`,
  which is dispatched through `asyncio.to_thread`.
- RED: `uv run pytest tests/unit/test_artifact_store.py -q` — 1 failed, 5
  passed; `test_store_construction_is_side_effect_free` observed the root
  created during construction.
- GREEN: `uv run pytest tests/unit/test_artifact_store.py -q` — 6 passed;
  focused Ruff and Pyright passed, format check reported 5 files already
  formatted, and `git diff --check` passed.
- Review-fix commit: `69e3f0a3babdfc9dc67be1cd1aa3124a01ac8318`
  (`Make artifact store construction side-effect free`).
- Independent review: no Critical, Important, or Minor findings after the fix;
  `Spec compliance: PASS` and `Code quality: APPROVED` over commits
  `297e2b52d..69e3f0a3b`.
- Deferred review observations were confirmed as out of Task 1 scope: production
  root composition and event/hydration/GC integration belong to later tasks;
  the pre-existing `StoredArtifactRef` invariant is established by W5.

### Task 2: Atomic Check-Output Externalization

Status: complete; independent task review and fresh verifier gate passed.

RED evidence:
- `uv run pytest tests/unit/test_graph_models.py -k check_output_artifact tests/integration/test_check_output_artifacts.py -q`
  - Result: 1 failed and collection had 1 error, as expected. The model rejected
    `stdout_tail`, `stdout_ref`, `stderr_tail`, and `stderr_ref` while requiring
    removed `stdout`/`stderr`; integration collection failed because
    `CHECK_OUTPUT_TAIL_CHARS` and artifact-store dispatch injection did not exist.

GREEN evidence:
- `uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_projections.py tests/integration/test_check_output_artifacts.py tests/integration/test_graph_runner_e2e.py -q`
  - Result: 249 passed in 19.23s.
- `uv run pytest tests/ -q -n auto --dist worksteal`
  - Result: 4,792 passed, 3 skipped, and 3 existing warnings in 102.45s.
- `uv run ruff check .`
  - Result: all checks passed.
- `uv run pyright`
  - Result: 0 errors, 0 warnings, 0 informations (with only the available-update notice).
- `uv run ruff format --check .`
  - Result: all 708 files already formatted.
- `git diff --check`
  - Result: passed, no output.

Ordering and failure evidence:
- Real callback/event-path integration tests prove over-threshold stdout and
  stderr blobs contain all 17,000 bytes before accepted events expose their
  references, while event values contain only 4,000-character tails.
- A real filesystem write failure leaves no accepted callback or check-result
  event. A real SQLite append failure after the write leaves a hash-verified,
  readable orphan in the temporary filesystem store.
- Reducers, projections, blockers, activity summaries, and prompts remain
  store-free and consume only canonical tails; production composition resolves
  the main git worktree before constructing `.orchestrator/artifacts`.

Implementation commits:
- `0c8b26a1b` (`Externalize large check output artifacts`).
- `2193185f0` (`Record check output artifact evidence`).

Boundary Coverage Review Fix:
- Added real producer/store regressions for inclusive 16,384-byte inline output,
  16,385-byte externalization with complete blob recovery, and a 16,385-byte
  multibyte output whose tail is the final 4,000 Unicode characters.
- Focused verification: 8 passed; Ruff and Pyright passed, both files were
  formatted, and `git diff --check` passed.
- Review-fix commit: `ae3b35f60` (`Cover check output artifact boundaries`).
- Evidence commit: `a80131c40` (`Record check output boundary coverage`).

Independent review:
- Complete range: `120c300f3..a80131c40`.
- Result after review fix: no Critical, Important, or Minor findings;
  `Spec compliance: PASS` and `Code quality: APPROVED`.

Fresh verifier gate at `a80131c40c1d93252113feb6ee33e3fc247c68b0`:
- `uv run pytest tests/ -k "graph or artifact" -q -n auto --dist worksteal`
  - Result: 998 passed in 57.15s.
- `uv run ruff check .`
  - Result: passed.
- `uv run pyright`
  - Result: 0 errors, 0 warnings, 0 informations.
- `git diff --check`
  - Result: passed, no output.
- Post-verification `git status --short` was clean.

### Task 3: Explicit Prompt and API Hydration

Status: complete; independent task review passed specification and code-quality
gates.

Implementation evidence:

- RED: `uv run pytest tests/unit/test_artifact_prompt_hydration.py tests/integration/test_artifact_api.py -q`
  failed as intended with 2 failed and 1 collection error: the explicit prompt
  hydration function was not exported and the artifact endpoint did not exist.
- GREEN: the same focused command passed 6 tests. The coverage uses a real
  temporary filesystem CAS, typed check-result references in a real in-memory
  graph event store, and an auth-enabled ASGI application. It proves JWT
  enforcement, run-scoped typed-reference authorization, range constraints,
  complete-blob integrity before slicing, and stable missing/integrity errors.
- Ordinary prompt packets remove check-output references and retain their tails;
  explicit hydration accepts an injected store and typed reference, decodes only
  a caller-bounded excerpt, and does not involve reducers, projections, or
  commands.
- API authorization evidence: an authenticated request for the same digest under
  a different run receives 404 before any blob read; a valid bearer token for the
  referenced run receives only the requested `206` byte range.
- Integrity evidence: a referenced deleted blob returns `404 Artifact blob not
  found`; a referenced tampered blob returns `409 Artifact blob failed integrity
  verification`. Both outcomes occur before slicing.

Review-fix evidence:

- RED: the two Task 3 test files produced 2 expected failures: `206` was
  incorrectly returned at EOF, and `create_app` lacked an injected main-project
  artifact-root boundary.
- GREEN: the same focused command passed 8 tests. A real linked-worktree test
  starts from a non-project CWD, injects its main checkout, and proves CAS writes
  only under that checkout's `.orchestrator/artifacts`; EOF, past-EOF, and empty
  authorized blobs return verified `416` responses with `Content-Range: bytes
  */<length>`.

Second-review evidence:

- RED: importing `planner_evidence` from the graph-runtime public API failed
  during focused unit-test collection because the intended public symbol was not
  exported.
- GREEN: the focused suite passed after exporting that public prompt API. A new
  real linked-worktree-CWD regression omits `artifact_project_root` and proves
  implicit resolution stores the blob only at the main checkout's
  `.orchestrator/artifacts` root.

Commits and review:
- `ab1da8c3a` (`Add bounded artifact hydration API`).
- `664c15626` (`Fix artifact API review findings`).
- `ae4049db1` (`Expose artifact prompt evidence API`).
- Independent review range: `0f26c0f14..ae4049db1`.
- Final result: no findings; `Spec compliance: PASS` and
  `Code quality: APPROVED`.
- The reviewer noted no specified malformed/unknown text-encoding policy; this
  is not a Task 3 requirement or demonstrated defect.

### W5.5 Task 4: Typed Artifact Mark-and-Sweep GC

Status: complete; independent task review and fresh verifier gate passed.

- **RED:** `uv run pytest tests/unit/test_artifact_gc.py -q` failed at collection
  with `ModuleNotFoundError: No module named 'orchestrator.artifacts.gc'`.
- **GREEN:** `uv run pytest tests/unit/test_artifact_gc.py tests/unit/test_command_handlers.py tests/integration/test_workflow_service.py -q`
  passed **64 tests**. The focused artifact-GC suite itself passed **2 tests**.
- **Retention:** typed recursive traversal recognizes only concrete
  `StoredArtifactRef` Pydantic values, including a strict typed
  `output_record_accepted` check-result payload; arbitrary mapping hash strings
  are not marks. Surviving (not projected-deleted) run graph events provide the
  retained set after the deletion tombstone has committed.
- **Grace:** valid unmarked CAS blobs are removed only when their injected UTC
  modification time is strictly older than the 86,400-second cutoff; a blob at
  the exact cutoff and a retained old blob survive. Malformed paths and
  non-regular files are ignored.
- **Idempotence:** a second sweep returns no deleted hashes after the first
  removes the old unmarked blob.
- **Purge failure:** the integration suite makes a real temporary CAS directory
  non-writable, receives `ArtifactGarbageCollectionError`, and verifies the
  already committed `run_deleted` tombstone remains in the event stream.
- **Composition:** `create_app` owns a collector rooted beside its existing
  main-project artifact store, and the API dependency composition injects it
  into `WorkflowService`; command handlers and reducers remain store-free.
- **Review fix:** real symlinked `sha256` and prefix-directory regressions
  prove sweep never traverses outside its configured root; unknown and malformed
  typed graph envelopes now fail before sweep; deletion without GC fails before
  tombstone append; and a real retained run graph event preserves its old CAS
  artifact while another run is deleted. Focused workflow/API/GC verification
  passed 120 tests.
- **Second review fix:** GC now opens the configured root, `sha256`, and prefix
  directories with POSIX no-follow directory descriptors; listing, stat, and
  unlink operations are descriptor-relative, so parent replacement cannot
  redirect traversal. A real configured-root symlink/non-directory regression
  preserves the outside CAS blob. Focused verification passed 121 tests.
- **Static checks:** `uv run ruff check src/orchestrator/artifacts tests/unit/test_artifact_gc.py tests/integration/test_workflow_service.py`,
  `uv run pyright src/orchestrator/artifacts tests/unit/test_artifact_gc.py tests/integration/test_workflow_service.py src/orchestrator/workflow/service.py`,
  `uv run ruff format --check src/orchestrator/artifacts tests/unit/test_artifact_gc.py tests/integration/test_workflow_service.py`,
  and `git diff --check` passed.

Commits and independent review:
- `0a80651a1` (`Garbage collect unreferenced artifacts`).
- `c6b6d2c58` (`Wire artifact GC into API composition`).
- `024849c4a` (`Harden artifact GC review findings`).
- `29b8206d7` (`Harden artifact GC descriptor traversal`).
- Review range: `226973adc..29b8206d7`.
- Final result: no findings; `Spec compliance: PASS` and
  `Code quality: APPROVED`.

Fresh verifier gate at `29b8206d741aac58aadc23c85ce2a99b2315a2d6`:
- `uv run pytest tests/ -k "graph or artifact" -q -n auto --dist worksteal`
  - Result: 1,016 passed in 56.82s.
- `uv run ruff check .`
  - Result: passed.
- `uv run pyright`
  - Result: 0 errors, 0 warnings, 0 informations.
- `git diff --check`
  - Result: passed, no output.
- Post-verification `git status --short` was clean.

### W5.5 Task 5: Final Artifact Verification

Status: complete; independent task review and fresh closeout verifier passed.

- Existing focused coverage was first run without a manufactured RED:
  `uv run pytest tests/integration/test_check_output_artifacts.py tests/unit/test_artifact_gc.py -q`
  passed **13 tests**. It covered boundary externalization and GC but did not
  reproducibly combine 2 MiB persistence with replay after artifact removal.
- Added durable acceptance coverage in
  `test_two_mebibyte_outputs_replay_without_artifacts_and_keep_event_json_bounded`.
  Its first run passed immediately, as expected for verification of already
  implemented behavior: `uv run pytest tests/integration/test_check_output_artifacts.py -q`
  passed **8 tests**.
- The acceptance command produces exactly **2,097,152 bytes (2 MiB)** each of
  stdout (`x`) and stderr (`y`) through the real check-dispatch producer, real
  temporary filesystem CAS, and real SQLite event store. Complete CAS blobs
  were read and verified before removal:
  - stdout: `sha256:6932fd31e5daf4739b9fa78ff777b2831b0995cc1d0b0093cac80601902013bc`
    (2,097,152 bytes)
  - stderr: `sha256:a817acf98d9f6ef7656e3d474dc68bf8b1f7526f598958bb65a72a8db8a74608`
    (2,097,152 bytes)
- Actual SQLite `events_v2.payload` JSON for the check-result row measured
  **21,087 UTF-8 bytes** (the event JSON column only, excluding other SQLite
  row metadata), below the **32,768-byte** bound. Parsed JSON contains both
  typed refs and exactly 4,000-character stdout/stderr tails, and excludes any
  4,001-character body substring.
- Replay acceptance removes only the temporary test CAS root, then uses real
  `GraphEventStore.read_run` and `read_run_projection` paths. Full and compact
  replay have equal run state, node states, and task states with the artifact
  directory absent; neither replay path receives or reads an artifact store.
- GC evidence remains the Task 4 focused suite: typed references are retained;
  old unmarked blobs are swept only after the 86,400-second grace period;
  exact-cutoff, retained, malformed, non-regular, and symlink-traversal cases
  survive; a second sweep is idempotent; and a collection failure leaves the
  already-committed run-deletion tombstone intact.
- Final builder gates at the Task 5 candidate:
  - `uv run pytest tests/ -q -n auto --dist worksteal` — **4,815 passed, 3
    skipped, 3 existing SQLite datetime-adapter warnings** in 108.59s.
  - `uv run ruff check .` — all checks passed.
  - `uv run pyright` — 0 errors, 0 warnings, 0 informations (with the available
    version notice only).
  - `git diff --check` — passed with no output.
- Changed-file formatting gate:
  `uv run ruff format --check tests/integration/test_check_output_artifacts.py`
  reported 1 file already formatted.

Commits and independent review:
- `469c6358c` (`Verify durable check output artifacts`).
- `c2aca5d10` (`Clarify Task 5 review status`).
- Review range: `ff1f7898f..c2aca5d10`.
- Final result: no findings; `Spec compliance: PASS` and
  `Code quality: APPROVED`.

Fresh closeout verifier at `c2aca5d10cdf58840bac35d6d21688973e386f78`:
- `uv run pytest tests/ -k "graph or artifact" -q -n auto --dist worksteal`
  - Result: 1,017 passed in 58.24s.
- `uv run pytest tests/ -q -n auto --dist worksteal`
  - Result: 4,815 passed, 3 skipped, and 3 existing warnings in 99.78s.
- `uv run ruff check .`
  - Result: passed.
- `uv run pyright`
  - Result: 0 errors, 0 warnings, 0 informations.
- `git diff --check`
  - Result: passed, no output.
- Post-verification `git status --short` was clean.
