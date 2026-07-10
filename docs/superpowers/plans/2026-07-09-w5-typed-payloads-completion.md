# W5 Typed Payloads Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete W5 by typing every remaining graph event and command payload, deriving persistence allowlists from a typed registry, typing verification grade rows, and closing the W5 documentation with reproducible verification evidence.

**Architecture:** Event payload models remain in `graph/models.py`; producers validate and JSON-dump them, and reducers parse them before reading fields. A new command-model module and `CommandSpec` registry validate all 23 command handlers while preserving `command_rejected` behavior for internal callers and FastAPI 422 behavior for public patch/decision routes. Work proceeds in independently tested, independently reviewed slices with the progress ledger as durable state.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, pytest/pytest-asyncio, Ruff, Pyright, `uv`, git worktrees.

## Global Constraints

- Work only in `/Users/peter/code/task-world/worktrees/w5-typed-payloads-completion` on `codex/w5-typed-payloads-completion`.
- Use `uv run` for every Python command; do not use bare `python`, `python3`, or `pip`.
- Never edit or delete `orchestrator.db`, and never rewrite durable `events_v2` history.
- Each event payload has fixed typed fields plus at most one `extra: dict[str, Any]`; legacy unknown top-level keys migrate under `extra` through `mode="before"` normalization.
- Preserve every reducer-read key and every replay-only alias; malformed historical events retain current skip/default behavior.
- Keep patch ops/macros, command definitions, diagnostics/read-set diffs, edge metadata/policy, decision `scope`/`decider`, and `TypedRecordBase.payload`/`provenance` intentionally flexible.
- Use real objects and files in tests; no patching, `MagicMock`, or monkeypatching.
- Do not bump `PROJECTION_SCHEMA_VERSION` unless stored projection shape or reducer semantics actually change.
- A slice is accepted only after a fresh verifier reports exact green output for its targeted tests, corpus parity, `tests/ -k graph`, Ruff, Pyright, and a ground-rule diff review.
- Commit each accepted slice and append exact RED/GREEN evidence, compatibility normalization, and the commit SHA to `docs/dynamic-graph/w5-progress-ledger.md`.
- Implementation agents may run concurrently only when their write sets are disjoint; edits to `models.py`, `_commands.py`, or `projections.py` are serial by default.

---

### Task 1: Decision Event Payloads

**Files:**
- Create: `docs/dynamic-graph/w5-slices/decisions.md`
- Create: `tests/unit/test_decision_event_payloads.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/_commands.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `src/orchestrator/graph_runtime/store.py` only if summary reconstruction needs `scope`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Produces: `AppealOpenedPayload`, `ApprovalDecisionRecordedPayload`, `AuthorityDecisionRecordedPayload`, `OversightDecisionRecordedPayload`.
- Consumes: current `GraphEventPayloadBase`, decision projection models, `_apply_raise_appeal`, `_apply_record_decision`, and the decision reducer helpers.

- [ ] **Step 1: Write the slice brief**

Record the four events, producer/reducer sites, legacy membership fallback, optional legacy oversight `node_id`, opaque `decider`/`scope`, and the six named tests below in `w5-slices/decisions.md`.

- [ ] **Step 2: Write the failing tests**

Add these tests: `test_appeal_opened_payload_normalizes_membership_and_patch_extras`, `test_decision_payloads_normalize_legacy_outcome_verdict_and_approved`, `test_decision_payloads_preserve_opaque_decider_scope_and_unknown_extra`, `test_decision_reducers_preserve_legacy_appeal_and_invalid_test_behavior`, `test_decision_producers_emit_typed_payloads`, and `test_sparse_oversight_decision_without_node_id_remains_replayable`.

Use direct model/reducer assertions such as:

```python
payload = OversightDecisionRecordedPayload.model_validate(
    {"task_region_id": "task-1", "verdict": "failed", "legacy": 1}
)
assert payload.node_id is None
assert payload.verdict == "failed"
assert payload.extra == {"legacy": 1}
```

- [ ] **Step 3: Record RED**

Run: `uv run pytest tests/unit/test_decision_event_payloads.py -q`

Expected: collection fails because the new payload exports do not exist.

- [ ] **Step 4: Implement the models and typed producer/reducer flow**

Give `AppealOpenedPayload` optional `run_id`, `node_id`, `appealed_node_id`, `candidate_id`, `task_region_id`, `appeal_type`, `lease_id`, and `membership`. Give the three decision payloads optional `run_id`, `decision_type`, `node_id`, `decision`, `outcome`, `verdict`, `approved`, `task_region_id`, `gate_id`, `appeal_node_id`, `appealed_node_id`, `candidate_id`, `appeal_type`, `expires_at`, `reason`, `record_id`, `membership`, `decider`, and `scope`. Normalize membership identifiers and legacy decision aliases without typing `decider` or `scope` more deeply. Route all producers through `model_validate(...).model_dump(mode="json")`; parse once in `reduce_event` and pass typed values to every decision helper.

- [ ] **Step 5: Verify, independently review, update ledger, and commit**

Run:

```bash
uv run pytest tests/unit/test_decision_event_payloads.py -q
uv run pytest tests/unit/test_fixture_corpus.py::test_fixture_corpus_replay_matches_checkpoint_and_compact_projection -q
uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_decision_event_payloads.py -q
uv run pytest tests/ -k graph -q
uv run ruff check .
uv run pyright src/orchestrator/graph tests/unit/test_decision_event_payloads.py
```

Expected: all pass. After a fresh verifier PASS, append evidence and commit with `git commit -m "Add typed decision event payloads"`.

### Task 2: Requirement and Evidence Event Payloads

**Files:**
- Create: `docs/dynamic-graph/w5-slices/requirements-evidence.md`
- Create: `tests/unit/test_requirement_evidence_event_payloads.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/_commands.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `src/orchestrator/graph_runtime/store.py`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Produces: `RequirementRevisionPayload`, `SupportEvidencePayload`, `RequirementAuthorityResolutionPayload`.
- Covers: produced `requirement_revision_recorded`/`support_evidence_recorded` and replay aliases `requirement_amended`, `requirement_revision_proposed`, `support_edge_recorded`, `authority_resolution_recorded`, `authority_resolved`, `requirement_revision_authorized`.

- [ ] **Step 1: Write the brief and failing tests**

Name these cases: `test_requirement_revision_payload_preserves_all_authority_classification_inputs`, `test_requirement_revision_payload_normalizes_invalid_scalars_and_unknown_keys_to_extra`, `test_support_evidence_payload_supports_edge_and_version_aliases`, `test_requirement_reducers_tolerate_recorded_and_replay_only_aliases`, `test_authority_resolution_aliases_clear_full_history_and_checkpoint_blockers`, `test_requirement_and_support_producers_emit_typed_payloads`, and `test_validation_strengthening_still_stales_prior_support`.

Include the critical full-history assertion:

```python
assert project_final_invariants(full_events) == project_final_invariants_from_checkpoint(
    checkpoint, tail_events
)
```

- [ ] **Step 2: Record RED**

Run: `uv run pytest tests/unit/test_requirement_evidence_event_payloads.py -q`

Expected: import/collection failure for `RequirementRevisionPayload`.

- [ ] **Step 3: Implement models and both reducer paths**

`RequirementRevisionPayload` retains identifier aliases (`requirement_id`, `id`, `node_id`, `revision_id`, `version_id`, `requirement_version_id`, `proposal_id`, `patch_id`), classification aliases, strict optional authority/behavior booleans, `revision_index`, prior-version metadata, and nested legacy `requirement`. `SupportEvidencePayload` retains support/edge and version aliases plus status metadata. `RequirementAuthorityResolutionPayload` retains every identifier used by the existing revision-id resolver. Parse these models in both `reduce_event` and the separate full-history `_authority_revision_blockers` scan so checkpoint/full-history behavior cannot diverge.

- [ ] **Step 4: Verify, review, ledger, and commit**

Run the targeted file, corpus parity, graph projections plus allowlist guard, `uv run pytest tests/ -k graph -q`, `uv run ruff check .`, and `uv run pyright src/orchestrator/graph tests/unit/test_requirement_evidence_event_payloads.py`. Expected: all pass. Fresh-verifier PASS is required. Commit with `git commit -m "Add typed requirement and evidence payloads"`.

### Task 3: Lifecycle, Callback, Retry, and Audit Event Payloads

**Files:**
- Create: `docs/dynamic-graph/w5-slices/lifecycle-command-rejection.md`
- Create: `tests/unit/test_lifecycle_event_payloads.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/_commands.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `src/orchestrator/graph_runtime/store.py`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Produces: `RunLifecycleChangedPayload`, `CommandRejectedPayload`, `CallbackAcceptedPayload`, `CallbackRejectedPayload`, `CallbackDuplicateReturnedPayload`, `RuntimeRetryScheduledPayload`, `HeartbeatRecordedPayload`, `AgentDiedPayload`, `DeadInputDetectedPayload`.

- [ ] **Step 1: Write tests and record RED**

Create `test_run_lifecycle_payload_accepts_sparse_legacy_and_recovery_shapes`, `test_command_rejected_payload_preserves_blockers_and_patch_diagnostics`, `test_callback_payloads_preserve_explicit_none_and_duplicate_prior_result`, `test_callback_accepted_reducer_records_idempotency_through_typed_payload`, `test_runtime_retry_payload_preserves_retry_backoff_projection`, `test_audit_payloads_normalize_unknown_keys_without_affecting_projection`, `test_lifecycle_callback_and_runtime_producers_emit_typed_payloads`, and `test_sparse_fixture_lifecycle_and_callback_events_remain_replayable`. Pin explicit `None`:

```python
dumped = CallbackAcceptedPayload(
    node_id="n", idempotency_key="k", payload=None
).model_dump(mode="json")
assert "payload" in dumped
assert dumped["payload"] is None
```

Run `uv run pytest tests/unit/test_lifecycle_event_payloads.py -q`; expect import failure.

- [ ] **Step 2: Implement compatibility-first optional models**

Keep every historical field optional. Preserve callback `payload=None` even though the shared event base normally excludes `None`. Type retry timing (`retry_after_seconds`, `retry_not_before`), lifecycle recovery metadata, rejection blockers, heartbeat lease metadata, agent-death metadata, and dead-input routing fields. Route every current producer through the model; parse lifecycle, accepted callback, and runtime retry in the reducer while retaining audit-only events without projection mutations.

- [ ] **Step 3: Update retention and verify**

Retain `retry_not_before` in light/summary reconstruction and node detail where scheduler retry state is reconstructed. Run the targeted file, corpus parity, graph projections/allowlist guard, graph suite, Ruff, and Pyright. Require fresh-verifier PASS, ledger the explicit-`None` compatibility rule, and commit with `git commit -m "Add typed lifecycle and callback event payloads"`.

### Task 4: `node_created` Payload

**Files:**
- Create: `docs/dynamic-graph/w5-slices/node-created.md`
- Create: `tests/unit/test_node_created_event_payloads.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/compiler.py`
- Modify: `src/orchestrator/graph/_commands.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Produces: `NodeCreatedPayload` around the existing `NodeCreationProjection` shape.
- Covers compiler seed nodes plus patch, recovery, appeal, and direct node creation.

- [ ] **Step 1: Write brief and RED tests**

Create `test_node_created_payload_normalizes_membership_authority_and_unknown_keys_to_extra`, `test_node_created_payload_preserves_compiler_recovery_and_command_fields`, `test_node_created_reducer_preserves_planner_recovery_and_authority_indexes`, `test_node_created_producers_emit_payloads_validated_by_typed_model`, and `test_node_created_compact_replay_matches_full_replay`. Use a full-shape assertion that includes `node_id`, `kind`, `role`, `state`, `task_region_id`, attempt/candidate fields, claims/actions/preconditions, planner fields, request/gate prompt fields, command fields, recovery fields, `inputs`, and `outputs`. Run `uv run pytest tests/unit/test_node_created_event_payloads.py -q`; expect missing export.

- [ ] **Step 2: Implement the strong node model**

Reuse typed nested models already accepted by `NodeCreationProjection`; do not invent types for `command_definition` or request metadata that the W5 scope keeps flexible. Normalize legacy scalar/type mismatches into the single `extra`; ensure recovery and planner-chain secondary indexes read named model fields. Update compiler `_node` output and all command-side node producers to dump `NodeCreatedPayload`.

- [ ] **Step 3: Verify and commit**

Run targeted node tests, compiler tests, corpus parity, graph projections/allowlists, full graph suite, Ruff, and Pyright. Expect all pass. A fresh strongest-available verifier must explicitly review reducer-read key coverage and compiler parity. Append ledger evidence and commit with `git commit -m "Add typed node created payload"`.

### Task 5: Remaining Node Lifecycle Payloads

**Files:**
- Create: `docs/dynamic-graph/w5-slices/node-lifecycle.md`
- Create: `tests/unit/test_node_lifecycle_event_payloads.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/_commands.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Produces: models for `node_state_changed`, `node_retired`, `node_ready`, `node_deferred`, `node_authority_changed`, and suspect marked/resolved/cleared aliases.

- [ ] **Step 1: Test and record RED**

Create `test_node_state_changed_payload_normalizes_legacy_membership_and_audit_fields`, `test_simple_node_lifecycle_payloads_move_unknown_keys_to_extra`, `test_node_authority_changed_payload_normalizes_nested_authority`, `test_node_suspect_payload_supports_all_replay_aliases`, `test_node_lifecycle_reducers_tolerate_legacy_payloads_through_typed_models`, and `test_node_lifecycle_producers_emit_payloads_validated_by_typed_models`. These cover membership fallback, retirement/ready/deferral, authority claims/actions/preconditions, and node/plan-region suspect aliases. Run the new test file; expect missing model imports.

- [ ] **Step 2: Implement and verify**

Use optional fields for replay tolerance; keep `membership`, `authority`, and suspect region identifiers named. Route current producers through models and reducer aliases through typed parsing. Run targeted tests, corpus parity, graph projection/allowlist tests, full graph suite, Ruff, and Pyright. Require fresh-verifier PASS and commit with `git commit -m "Add typed node lifecycle payloads"`.

### Task 6: Output and Verification Record Event Envelopes

**Files:**
- Create: `docs/dynamic-graph/w5-slices/output-verification-records.md`
- Create: `tests/unit/test_output_record_event_payloads.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/_commands.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Produces: `OutputRecordAcceptedPayload` and shared `VerificationOutcomePayload` for `verification_passed`/`verification_failed`.
- Reuses existing typed output record/value models without typing their intentionally flexible payload/provenance fields.

- [ ] **Step 1: Test all accepted record variants and RED**

Create `test_output_record_accepted_payload_normalizes_legacy_node_alias_and_extra`, `test_output_record_accepted_payload_validates_every_typed_record_variant`, `test_output_record_accepted_payload_preserves_legacy_scalar_value_fallback`, `test_verification_outcome_payload_normalizes_pass_fail_aliases_and_extra`, `test_output_record_reducer_preserves_candidate_check_summary_and_recovery_indexes`, `test_output_record_and_verification_producers_emit_typed_payloads`, and `test_output_record_compact_replay_matches_full_replay`. Parameterize the typed-variant case over every accepted record kind. Run `uv run pytest tests/unit/test_output_record_event_payloads.py -q`; expect missing export.

- [ ] **Step 2: Implement envelope parsing**

Model the event envelope fields around existing record values: record identifiers/kinds/types, producer/port/schema, value/provenance, candidate/membership/attempt/task identifiers, record-id lists, and supersession identifiers. Preserve nested heterogeneous `value`, `payload`, `provenance`, and evidence. Route output/verification producers and all candidate/check/recovery helper consumers through typed fields.

- [ ] **Step 3: Verify and commit**

Run targeted record tests, existing graph model/record tests, corpus parity, projection/allowlist tests, full graph suite, Ruff, and Pyright. Require a fresh strongest-available verifier PASS. Ledger and commit with `git commit -m "Add typed output and verification event payloads"`.

### Task 7: Input Binding and Revision Event Payloads

**Files:**
- Create: `docs/dynamic-graph/w5-slices/input-binding-revisions.md`
- Create: `tests/unit/test_record_routing_event_payloads.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/_commands.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Produces: `InputBoundPayload` and replay-only `RevisionCreatedPayload`.

- [ ] **Step 1: Write compatibility tests and RED**

Create `test_input_bound_payload_normalizes_legacy_input_and_record_bound_positions`, `test_input_bound_payload_filters_invalid_record_ids_without_losing_legacy_data`, `test_revision_created_payload_preserves_patch_metadata_under_extra`, `test_input_bound_reducer_preserves_many_cardinality_and_supersession`, `test_record_routing_producers_emit_payloads_validated_by_typed_models`, and `test_input_bound_compact_replay_preserves_record_bound_positions`. Run the new file; expect import failure.

- [ ] **Step 2: Implement, verify, and commit**

Keep `record_ids` and bound-position maps typed, preserve legacy routing aliases as named fields, and keep revision node/worker/verifier structures flexible under the one containment rule. Add `record_bound_positions` to projection and light/summary retention because compact replay consumes it. Run targeted, corpus, projection/allowlist, graph, Ruff, and Pyright gates; obtain fresh PASS; ledger and commit with `git commit -m "Add typed binding and revision payloads"`.

### Task 8: File-State and Gatekeeper Event Payloads

**Files:**
- Create: `docs/dynamic-graph/w5-slices/file-state-gatekeeper.md`
- Create: `tests/unit/test_file_state_gatekeeper_event_payloads.py`
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/_commands.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `src/orchestrator/graph_runtime/store.py`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Covers `file_state_accepted`, `file_state_rejected`, `gatekeeper_verdict_recorded`, `gatekeeper_cost_recorded`, replay-only `environment_failure_accepted`, and `check_result_classified`.

- [ ] **Step 1: Test and record RED**

Create `test_file_state_accepted_payload_normalizes_membership_entries_and_extra`, `test_file_state_rejected_payload_preserves_rejection_evidence_and_extra`, `test_gatekeeper_verdict_payload_normalizes_entries_and_cost_defaults`, `test_gatekeeper_cost_payload_preserves_all_run_summary_fields`, `test_environment_failure_payload_supports_both_replay_aliases`, `test_file_state_gatekeeper_reducers_tolerate_legacy_payloads`, `test_file_state_gatekeeper_producers_emit_payloads_validated_by_typed_models`, and `test_gatekeeper_cost_projection_is_unchanged_after_typed_parsing`. Run the new test file; expect missing payload exports.

- [ ] **Step 2: Implement with cost retention**

Type `FileStateAcceptedPayload` around the existing `FileStateRecord`, plus `FileStateRejectedPayload`, `GatekeeperVerdictPayload`, `GatekeeperVerdictRecordedPayload`, `GatekeeperCostRecordedPayload`, and `EnvironmentFailureAcceptedPayload`. Preserve flexible nested file/check details and store-added durable decoration. Ensure every `gatekeeper_cost_recorded` identifier, token/cache count, item count, `cost_usd`, and `wall_time_ms` field read by run-summary logic remains named and retained by summary filtering.

- [ ] **Step 3: Verify and commit**

Run targeted tests, run-summary/read-model tests, corpus parity, projections/allowlists, graph suite, Ruff, and Pyright. Require fresh PASS; ledger and commit with `git commit -m "Add typed file state and gatekeeper payloads"`.

### Task 9: Generated Event Payload Retention Registry

**Files:**
- Create: `src/orchestrator/graph/payload_registry.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `src/orchestrator/graph_runtime/store.py`
- Modify: `tests/unit/test_graph_payload_field_allowlists.py`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Produces: event-type-to-model registry plus generated projection/light/summary/node-detail field tuples.
- Consumes: completed event payload models from Tasks 1–8 and earlier W5 slices.

- [ ] **Step 1: Add failing registry equality tests**

Assert each tuple equals its generated registry value, output is sorted/deduplicated, `extra` is absent, every retained field belongs to a model or named legacy exception, and no exception is stale. Pin `verdict`, `carryover_record_id`, grade/value rebuild fields, retry timing, and gatekeeper costs.

- [ ] **Step 2: Record RED**

Run: `uv run pytest tests/unit/test_graph_payload_field_allowlists.py -q`

Expected: failure because `payload_registry.py` and generated constants do not exist.

- [ ] **Step 3: Implement declarative retention**

Use an immutable specification:

```python
@dataclass(frozen=True)
class EventPayloadSpec:
    model: type[BaseModel]
    projection: frozenset[str] = frozenset()
    light: frozenset[str] = frozenset()
    summary: frozenset[str] = frozenset()
    node_detail: frozenset[str] = frozenset()
```

Generate each tuple from explicit per-event retention sets; do not union every model field into every read mode. Keep small named legacy/envelope exceptions and import generated constants through the public `orchestrator.graph` API.

- [ ] **Step 4: Verify and commit**

Run allowlist/corpus tests, projection/corpus tests, graph read-model/event-store integration tests, full graph suite, Ruff, and Pyright across graph/runtime and the guard test. Require fresh PASS and commit with `git commit -m "Generate graph payload retention allowlists"`.

### Task 10: Command Validation Infrastructure and Lifecycle Commands

**Files:**
- Create: `src/orchestrator/graph/command_models.py`
- Create: `tests/unit/test_lifecycle_command_payloads.py`
- Modify: `src/orchestrator/graph/commands/__init__.py`
- Modify: `src/orchestrator/graph/commands/lifecycle.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `src/orchestrator/graph_runtime/controller.py`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Produces: generic `CommandSpec`, `COMMAND_SPECS`, and models for `accept_run`, `start`, `pause`, `resume`, `cancel`, `complete`, `fail`, `record_heartbeat`.
- Preserves: internal validation failure → deterministic `command_rejected`; unknown command behavior unchanged.

- [ ] **Step 1: Write registry and lifecycle RED tests**

Assert registry/model names cannot drift, defaults match current handlers, bools fail integer fields, and failed-run resume retains actor semantics. Run the new test file; expect missing `CommandSpec`/models.

- [ ] **Step 2: Implement the typed registry**

Use:

```python
@dataclass(frozen=True)
class CommandSpec:
    payload_model: type[BaseModel]
    handler: CommandHandler
```

Make `COMMAND_SPECS` the single registry and derive `COMMAND_HANDLERS` only if compatibility imports require it. Lifecycle fields: optional triggers, `ResumeCommandPayload.actor_role`, completion identifiers, failure reason, and heartbeat lease/node/generation with `ttl_seconds=300`. Separate injected `run_id` and `_current_graph_position` from public fields or alias them in a shared internal context model.

- [ ] **Step 3: Verify and commit**

Run `tests/unit/test_lifecycle_command_payloads.py` plus `test_graph_commands.py`, graph suite, Ruff, and Pyright across graph/runtime. Fresh PASS required. Commit with `git commit -m "Add typed lifecycle command payloads"`.

### Task 11: Scheduling Command Payloads

**Files:**
- Create: `tests/unit/test_scheduling_command_payloads.py`
- Modify: `src/orchestrator/graph/command_models.py`
- Modify: `src/orchestrator/graph/commands/__init__.py`
- Modify: `src/orchestrator/graph/commands/schedule.py`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Covers `seed_compiled_events`, `schedule_tick`, and `reconcile`.

- [ ] **Step 1: Test RED and implement**

Test typed `list[EventEnvelope]` seeding, `max_grants=10`, `lease_seconds=300`, optional lease/base-snapshot/priorities/region-order values, strict integer-vs-bool behavior, and empty `ReconcileCommandPayload`. Run new tests RED, implement the three models/spec entries, then rerun with `test_graph_commands.py`.

- [ ] **Step 2: Verify and commit**

Run graph suite, Ruff, and Pyright; obtain fresh PASS; ledger and commit with `git commit -m "Add typed scheduling command payloads"`.

### Task 12: Callback and Patch Command Payloads

**Files:**
- Create: `tests/unit/test_callback_patch_command_payloads.py`
- Modify: `src/orchestrator/graph/command_models.py`
- Modify: `src/orchestrator/graph/commands/__init__.py`
- Modify: `src/orchestrator/graph/commands/callbacks.py`
- Modify: `src/orchestrator/graph/commands/patches.py`
- Modify: `src/orchestrator/api/routers/graph.py`
- Modify: `tests/integration/test_graph_api.py`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Covers `submit_callback`, `submit_patch`, and `acknowledge_start`.
- Reuses `SubmitPatchCommandPayload` in `SubmitGraphPatchRequest`; public validation failures remain 422.

- [ ] **Step 1: Write RED unit and API tests**

Cover required callback identity/lease/snapshot/idempotency fields, nested/top-level payload hash compatibility, callback defaults, patch op and macro-only forms, malformed ops/base position/identifiers, flexible ops/macros, and acknowledge-start identity fields. Run unit and targeted API tests; expect missing command models or 422 mismatches.

- [ ] **Step 2: Implement and reuse at API boundary**

Preserve raw patch ops/macros and callback record payloads. Reject wrong outer types and invalid constrained identifiers/integers. Keep runtime identity fields already accepted by dispatch. Compose or inherit the FastAPI patch request schema from the command model rather than duplicating validators.

- [ ] **Step 3: Verify and commit**

Run unit command tests, `tests/integration/test_graph_api.py`, graph suite, Ruff, and Pyright across graph/runtime/api. Fresh PASS required. Commit with `git commit -m "Add typed callback and patch commands"`.

### Task 13: Decision and Record Command Payloads

**Files:**
- Create: `tests/unit/test_decision_record_command_payloads.py`
- Modify: `src/orchestrator/graph/command_models.py`
- Modify: `src/orchestrator/graph/commands/__init__.py`
- Modify: `src/orchestrator/graph/commands/records.py`
- Modify: `src/orchestrator/api/routers/graph.py`
- Modify: `tests/integration/test_graph_decisions_api.py`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Covers `agent_died`, `raise_appeal`, `record_decision`, `record_gatekeeper_verdicts`, `record_requirement_revision`, `record_support_evidence`, `evaluate_join`, `evaluate_final_gate`, and `record_cleanup_applied`.
- Completes exactly 23 `COMMAND_SPECS` entries.

- [ ] **Step 1: Write RED tests for all nine commands**

Assert exact 23-name registry equality, minimal valid model resolution, missing/wrong type rejection, flexible decision scope/decider and evidence metadata, gatekeeper verdict rows/cost fields, requirement aliases, join/final identifiers, and typed superseding `FileStateRecord`. Extend decision API tests for malformed constrained fields while preserving successful requests.

- [ ] **Step 2: Implement all nine models and API reuse**

Use `Literal["invalid_test"]` for appeals, constrained decision type/value validation matching current API behavior, a typed `GatekeeperVerdictRow`, compatibility aliases for requirement/evidence commands, and typed cleanup file-state input. Compose `RecordGraphDecisionRequest` from `RecordDecisionCommandPayload` so the public route returns 422 before dispatch.

- [ ] **Step 3: Verify and commit**

Run all four command payload files, `test_graph_commands.py`, patch and decision API integration tests, graph suite, Ruff, and Pyright across graph/runtime/api. Confirm registry count/name equality is 23. Fresh PASS required. Commit with `git commit -m "Add typed decision and record commands"`.

### Task 14: Typed Verification Grade Rows

**Files:**
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Modify: `tests/unit/test_graph_models.py`
- Modify: `docs/dynamic-graph/graph-projection-map-inventory.md`
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`

**Interfaces:**
- Produces: `GradeRow`; changes `VerificationReportValue.grades` to `list[GradeRow]`.

- [ ] **Step 1: Write RED tests**

Test standard rows, omitted reason, unknown-field round-trip, partial legacy rows, top-level outcome normalization, and unchanged empty-grade command rejection. Run `uv run pytest tests/unit/test_graph_models.py -k grade_row -q`; expect missing `GradeRow`.

- [ ] **Step 2: Implement compatibility model**

```python
class GradeRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    requirement_id: str | None = None
    grade: str | None = None
    reason: str | None = None
```

Set `grades: list[GradeRow] = Field(default_factory=list)`. Keep grade values extensible (`A`, `C`, `F`, `pass`, and future strings).

- [ ] **Step 3: Verify and commit**

Run graph model/command/corpus tests, full graph suite, Ruff, and Pyright. Update the inventory row that calls grades intentionally raw. Fresh PASS required. Commit with `git commit -m "Add typed verification grade rows"`.

### Task 15: W5 Closeout and Final Verification

**Files:**
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`
- Modify: `docs/dynamic-graph/graph-projection-map-inventory.md`
- Move: `docs/dynamic-graph/w5-typed-payloads-spec.md` → `docs/dynamic-graph/complete/w5-typed-payloads-spec.md`

**Interfaces:**
- Produces: closed W5 specification, complete ledger, refreshed inventory, and reproducible final metrics.

- [ ] **Step 1: Audit the queue and handler registry**

Confirm ledger entries exist for decisions, requirements/evidence, lifecycle/rejection, both node slices, both record slices, file-state/gatekeeper, allowlists, four command groups, and `GradeRow`. Assert `COMMAND_SPECS` has the exact 23 command names listed in Tasks 10–13.

- [ ] **Step 2: Run final verification**

Run:

```bash
uv run pytest tests/ -q
uv run ruff check .
uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime src/orchestrator/api tests/unit tests/integration
```

Expected: all pass. A fresh final verifier must review the entire branch diff against the containment, compatibility, scope, API-validation, and event-log rules.

- [ ] **Step 3: Compute and record metrics**

Run:

```bash
rg -o 'isinstance\(' src/orchestrator/graph/_commands.py src/orchestrator/graph/projections.py | wc -l
rg -o 'dict\[str, Any\]' src/orchestrator/graph/projections.py | wc -l
```

Record each final count and delta from baselines 603 and 174. Do not report the surveyed interim counts (650 and 182) as final.

- [ ] **Step 4: Close documentation and commit**

Mark the W5 spec complete, move it into `docs/dynamic-graph/complete/`, refresh the projection inventory, append final test/metric evidence, and correct stale ledger status wording without altering historical results. Run `git diff --check`. Commit with `git commit -m "Close W5 typed payload migration"`.

- [ ] **Step 5: Confirm clean handoff**

Run `git status --short` and `git log --oneline --decorate -20`. Expected: clean worktree and a reviewable sequence of slice commits ending in the closeout commit.
