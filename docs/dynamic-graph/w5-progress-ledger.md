# W5 Typed Payloads Progress Ledger

## Strict Cutover Task 5 — Records, Verification, Join, Final Gate

Status: complete. Committed as `d12908002` after independent verification.

Changes: completed the existing `output_record_accepted` strict specification
in place, added strict verification outcomes and grade rows, moved typed join
and final-gate commands into the records domain, and migrated eligible raw
record-acceptance producers through the records codemod.

Prior verification evidence is superseded by the follow-up entry below. Fresh
focused, corpus, broad graph, architecture, codemod, lint, and type evidence
is required before this slice can be marked complete.

D3: strict-path parsing was deleted while legacy-only replay remains deferred.
The retained sites are `reduce_legacy_event`,
`reduce_compact_output_record_accepted`, `_checkpoint_output_record_payload`,
`_parse_output_record_payload`, `_record_verification_result`,
`_verification_payload_outcome`, `_check_result_payload_status`, and
`_gap_classification_payload_classification`. Per the user's governing
decision, deletion occurs in Task 13 after database backup/reset, not Task 9.
Commit SHA: `d12908002`.

Seed branch: `main`
Seed SHA: `bd41b5b24756fec7441cbfd0ee150739b9afede7`
Work branch: `codex/w5-typed-payloads`

### Follow-up replay/producer verification (2026-07-12; incomplete)

The prior green claim above is stale after the requested fresh broad replay.
Investigation reproduced 17 original graph failures (`879 passed, 17 failed`) and
classified them as active producer/fixture incompatibilities, not a reason to
weaken strict payloads. A narrower replay boundary test was added and observed
RED: a schema-generation-2 malformed `output_record_accepted` event was
incorrectly replayed through the legacy reducer. The named
`reduce_d3_legacy_record_replay` boundary now accepts only schema generation 1
record events; its focused regression set passed (`4 passed`).

The records LibCST codemod was extended with a RED→GREEN fixture conversion
test for explicit verification outcomes, but its candidate fixture
idempotency test remains failing. The current broad graph command is
`uv run pytest tests/ -k graph -q --tb=short --log-level=CRITICAL` and reports
`879 passed, 18 failed`; the added failure is the codemod-test regression.
Remaining failures are: one active file-state cleanup producer with no strict
`record_type`; eight node-detail fixture replays with undeclared candidate
`value.body`/`grades`; one light-read fixture with undeclared candidate
`body`/`node_creation_context`; four fixtures missing strict verification
outcomes; and two callback producers with undeclared candidate `value.node_id`.
The focused suite currently reports `479 passed, 2 failed`, both in
`test_w5_strict_payload_codemod.py` (raw output-record nesting and candidate
idempotency). `records --assert-clean`, records inventory (44 events / 23
commands), architecture guard, and `git diff --check` exited zero. No commit
was made, and the user-modified continuation prompt remains untouched.

### Bounded producer/replay completion evidence (2026-07-12)

Resolved the follow-up list without relaxing strict validation: the cleanup
producer now provides the file-state discriminator; strict candidates use
closed optional detail fields for `body`, `grades`, `node_creation_context`,
and `node_id`; callback candidates and read-model fixtures use only those
declared fields; and verification fixtures now state both record and nested
outcomes. The records codemod's nested-record and idempotency regressions are
covered and fixed. Current-schema records remain strict and do not use D3.

Fresh evidence (all exit 0):
- `uv run pytest tests/unit/test_w5_strict_payload_codemod.py ... -q` —
  `482 passed` (records codemod plus focused Task 5 suites).
- `uv run pytest tests/unit/test_fixture_corpus.py -q` — `7 passed`.
- `uv run pytest tests/ -k graph -q --tb=short --log-level=CRITICAL` —
  `897 passed`.
- Architecture guard; records `--assert-clean`; records inventory check —
  passed, catalog baseline `44 events / 23 commands`.
- `uv run ruff check .`,
  `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime`, and
  `git diff --check` — passed (Pyright: `0 errors`).

The slice remains intentionally uncommitted and is not marked complete here:
there is no independent fresh verifier report.

### Final model-hardening follow-up (2026-07-12; complete)

The strict union now uses independent frozen, `extra="forbid"` models rather
than narrowing mutable permissive record subclasses. The final producer
alignment declares the exact active artifact-reference, decision-request,
verification-report, and file-state fields. File-state bridge serialization
also preserves its concrete entry fields and fixed discriminator fields.
Checkpoint hydration retains strict records, and dynamic check binding accepts
the strict routine-snapshot variant.

Fresh final evidence (all exit 0):
- Task 5 focused contracts: `413 passed`.
- Direct producer/checkpoint consequences: `245 passed`.
- Fixture corpus: `7 passed`.
- Broad graph matrix: `897 passed`.
- Architecture guard, records `--assert-clean`, and records inventory: passed,
  baseline `44 events / 23 commands`.
- Ruff, graph/runtime Pyright (`0 errors`), and `git diff --check`: passed.

Independent final verification at commit `d12908002` (all exit 0):
- Targeted post-format suite: `569 passed`.
- Strict/D3 probes: `6 passed`.
- Fixture corpus: `7 passed`.
- Broad graph matrix: `899 passed`.
- Catalog baseline: `44 events / 23 commands`.
- Architecture guard, records `--assert-clean`, inventory, Ruff format,
  Pyright, and `git diff --check`: passed.
- Commit hooks: passed.

D3 retains `reduce_legacy_event`, `reduce_compact_output_record_accepted`,
`_checkpoint_output_record_payload`, `_parse_output_record_payload`,
`_record_verification_result`, `_verification_payload_outcome`,
`_check_result_payload_status`, and
`_gap_classification_payload_classification`. Their deletion is governed by
Task 13 after database backup/reset, not Task 9.

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

### Task 7 strict cutover

Status: complete. Committed as `1bd87831b` after independent PASS.

- Replaced decision, appeal, requirement-revision, and support-evidence strict paths with frozen, strict, extra-forbid event/command payloads and catalog-owned reducers/handlers.
- Independent evidence: 339 focused, 7 fixture corpus, 897 broad graph,
  and full suite 4,768 passed / 5 skipped / 3 warnings. Catalog baseline
  remained 44 events / 23 commands; decisions and requirements were both
  assert-clean and inventory-clean; architecture, Ruff, format, Pyright,
  `git diff --check`, and commit hooks were green.
- D4 retained sites/categories: `reduce_legacy_event`, authority-blocker scans,
  and `_requires_authority_resolution(dict)` compatibility handling. Per the
  user's decision, deletion is Task 13 after database backup/reset.

Legacy decision payload slice status: complete.

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

# Strict Payload Architecture Cutover (plan: docs/superpowers/plans/2026-07-10-w5-strict-payload-architecture-cutover.md)

The entries below supersede the compatibility-first slices above where they
overlap. Task 0–2 evidence lives in `.superpowers/sdd/progress.md`; slice
reports live in `.superpowers/sdd/`.

## Strict-cutover Task 3: topology, nodes, sessions, inputs, revisions

Status: complete. Committed as `a2885ae1c` (corrected 2026-07-12; an earlier
version of this entry said "not committed or final-reviewed" and was stale).

The twelve topology specifications are strict and catalog-owned; compiler
output and `seed_compiled_events` carry `HydratedEvent` values. The minimal
strict `output_record_accepted` specification is registered early in
`events/records.py` solely to hydrate compiler output; its full records-domain
projection semantics remain deferred to Task 5. The strict suite rejects
historical aliases, unknown fields, and malformed nested values rather than
salvaging them.

Evidence: topology assert-clean, second apply with zero changes, inventory
domain check, architecture check, 250 focused tests, compiler 23 tests, Ruff,
Pyright, and `git diff --check` all passed; verification at completion was 886
broad graph, 187 focused, inventory 28, and baseline 44/23. Task 3.5 consumer
readback follow-up: full suite 4,732 passed, 5 skipped.

## Strict-cutover Tasks 4 and 6: lease/scheduling and patch domains

Status: complete. Committed as `14c32a73c` (single combined commit; the plan
prescribed one commit per domain — deviation accepted, recorded here).

Scope:
- `events/leases.py` with five strict lease specs; `events/patches.py` with
  two strict patch specs.
- `ScheduleTickCommand`, empty `ReconcileCommand`, and `SubmitPatchCommand`
  own their domains; scheduling logic moved out of `_commands.py` into
  `commands/schedule.py`; `commands/lease_bridge.py` deleted.
- No `lease_suspended` or proposal-alias specification exists in the catalog.

Deferred (NOT deleted here — see the plan's Deferred Compatibility Cleanup
Register, entries D1 and D2, swept in Task 9):
- `lease_suspended` branches in `reduce_legacy_event` and
  `_planner_generation_state`, and `GraphRecordKind.LEASE_SUSPENDED`.
- `graph_patch_proposed`/proposal-status bookkeeping helpers
  (`_graph_patch_payload_for_event`, `_open_proposal_blockers`,
  `_record_open_proposal_blocker`, attempt/record-port branches).
These are retained deliberately: durable history must replay until the Task 13
database cutover. The builder report's claim that "`lease_suspended` remains
absent" is true of the catalog only.

GREEN (independently rerun by a fresh verifier, 2026-07-12, at `14c32a73c`):
- Lease and patch codemod `--assert-clean`: pass, both domains.
- `uv run python scripts/w5_payload_ast_inventory.py --check-domain leases` /
  `--check-domain patches`: pass; baseline 44 events / 23 commands.
- `uv run python scripts/check_graph_payload_architecture.py`: exit 0.
- Targeted suites (lease/patch payloads, scheduler, graph commands, callbacks,
  fixture corpus, patch validator, prompt generation, graph planner):
  passed, 416 tests.
- `uv run ruff check .`: passed.
- `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime`:
  passed, 0 errors.
- `uv run pytest tests/ -q`: 4,733 passed, 5 skipped (67s).

## Strict-cutover Task 8: file-state, gatekeeper, and cleanup

Status: complete. Committed as `f8e0717cf` after independent PASS.

Typed commands and catalog events now own file-state, gatekeeper-verdict, and
cleanup behavior. The domain uses one strict `GatekeeperVerdict` model, and
runtime dispatch/gatekeeper boundaries accept typed values rather than
duplicate or permissive payload shapes.

Independent evidence: 234 focused tests, 7 fixture-corpus tests, 926 broad
graph tests, and the full suite at 4,845 passed / 5 skipped / 3 warnings.
Catalog baseline remained 44 events / 23 commands. Architecture, file-state
`--assert-clean` and inventory, Ruff format/check, Pyright, `git diff --check`,
and commit hooks were green.

D5 retained legacy categories are exactly the
`environment_failure_accepted` / `check_result_classified` branch in
`src/orchestrator/graph/projections.py:2281` and the environment/check-result
classification scan at `src/orchestrator/graph/projections.py:5449`. Delete
both in Task 13 after database backup/reset.
