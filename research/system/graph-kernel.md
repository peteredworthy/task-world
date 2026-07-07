# Graph Kernel & Runtime — Current System Map

> Provenance: derived from direct code inspection at HEAD `23746c228` (2026-07-07).
> File/line references are anchored to that commit and will drift.

The dynamic graph subsystem is the default execution carrier for runs
(`execution_mode=graph` default since `36bf8b763`). It is split into a **pure
kernel** (`src/orchestrator/graph/`) and an **effect shell**
(`src/orchestrator/graph_runtime/`), with the drive loop still hosted in the
legacy module (`src/orchestrator/workflow/graph_driver.py`).

## Domain model

- **Storage is event-sourced.** Durable truth is an append-only event log
  (`EventV2Model`, aggregate id `graph::<run_id>` — `graph_runtime/store.py:287`).
  State is derived by folding events through the pure reducer `reduce_event`
  into a `GraphProjection` TypedDict (`graph/projections.py`, ~4900 lines —
  the largest kernel file).
- **Snapshots are an optimization only.** `load_projection_with_tail`
  (`store.py:807`) loads the latest valid snapshot and folds the event tail;
  schema-version mismatch or corruption triggers full rebuild
  (`PROJECTION_SCHEMA_VERSION`). `rebuild_projection` (`controller.py:209`)
  is the canonical full fold.
- **Types** (`graph/models.py`): `NodeKind` has 23 variants (worker, verifier,
  check, planner, gap_planner, join, final_gate, human_gate, authority_request,
  oversight, appeal, recovery, file_state, session, …). `NodeState` is a
  10-value lifecycle (planned→blocked→ready→leased→running→
  completed/failed/retired/cancelled). Edges carry a typed `RecordSelector`
  (discriminated union) gating which records satisfy a binding.
- **Two record taxonomies**: `GraphRecordKind` (18 internal event kinds) and
  the typed output-record payload union `OutputRecordPayload` (candidate,
  check_result, verification_report, gap_classification,
  graph_patch_proposal, decision/authority records, …), each a strict
  Pydantic model with cross-field validators.
- **Commands are pure**: `apply_command(projection, events, command_type,
  payload, clock, id_gen) -> list[EventEnvelope]` (`graph/_commands.py:103`,
  ~5500 lines; W4 split it into `graph/commands/{lifecycle,callbacks,patches,
  records,schedule}.py`). ~20 command types dispatched by string.

## Control loop

1. `GraphController.handle_command` (`controller.py:50`) is the single append
   path: loads projection+tail **outside** any lock, checks
   `expected_position` (optimistic concurrency → `StaleProjectionError`),
   calls `apply_command`, then a short `BEGIN IMMEDIATE` transaction re-checks
   head position and appends events + outbox rows atomically
   (`controller.py:123-144`). A UNIQUE `(aggregate_id, version)` constraint is
   the DB backstop.
2. Lease grants become explicit `agent_dispatch_requested` events
   (`controller.py:166`), which the **outbox** maps to side effects.
3. `OutboxDispatcher.dispatch_pending` (`graph_runtime/outbox.py`) claims
   pending rows (pending→dispatching→completed), at-least-once, keyed by
   `event_id`; startup `reset_dispatching_to_pending` (`outbox.py:181`)
   re-arms interrupted rows; exponential backoff with stable jitter (W6).
4. `GraphDispatchExecutor.dispatch` (`dispatch.py:182`) routes by node kind —
   check/join/final_gate run in-process; everything else spawns a real
   `AgentRunner` via `_run_agent` (`dispatch.py:245`). Runner callbacks
   (`on_submit`, `on_grade`, `on_submit_graph_patch`) drive `_submit_callback`
   (`dispatch.py:455`), which captures a file-state boundary and issues a
   `submit_callback` command with retry-on-stale.
5. **Drive loop** (`GraphRunDriver.drive_to_quiescence`,
   `workflow/graph_driver.py:586`): schedule_tick (lease_seconds=3600,
   max_grants=10) → dispatch_pending → wait → re-read projection → renew
   expired leases → detect quiescence/completion → no-progress orphan
   recovery.

## Prompt assembly

`graph_runtime/prompts.py` (~1600 lines): `_prompt_for_node` (`prompts.py:113`)
branches by node kind — verifier packet (rubric + candidate + context),
summarizer, planner (large mutation-contract preamble at `prompts.py:150-176`
plus `allowed_patch_operations`, `horizon_region_templates`,
`patch_examples`), else worker-like. Size caps: `MAX_GRAPH_PROMPT_CHARS=60_000`,
`MAX_GRAPH_JSON_SECTION_CHARS=36_000`, `MAX_GRAPH_PROMPT_FIELD_CHARS=8_000`.
Context between phases flows as **bound records** hydrated per edge
`prompt_hydration_policy` (`_hydrated_bound_record`, `prompts.py:734`), with
compaction of file-state and artifact payloads.

## Dynamic behavior

- Graph grows via **planner-proposed patches**: planner/gap_planner nodes call
  `submit_graph_patch` (`dispatch.py:558`) → `submit_patch` command. A planner
  node is not finalized until an *accepted* patch exists (`dispatch.py:263-274`).
- **Macros** (`graph/macros.py`) expand planner-facing region macros into
  low-level ops; `horizon_templates.py` provides standard
  discovery/implementation/validation/gap-analysis/corrective/final-invariant
  region templates.
- Verification gating: `evaluate_final_gate` / `evaluate_join` commands and
  `FinalInvariantBlocker` projections. Completion is a deterministic invariant
  over typed records, not prompt convention.
- **Supersession**: file-state records can be marked
  `compromised`/`superseded_by_record_id`; `cleanup_requested` →
  `snapshot_cleanup` outbox side effect.

## Invariants & guards

- **Patch validation** (`graph/patch_validator.py`): role allowlists
  (`ALLOWED_BY_ROLE`/`PLANNER_OPS`), **stale-base refusal**
  (`_validate_staleness` vs `INVALIDATING_EVENT_TYPES`), gap_planner cannot
  retire executable nodes, cannot retire running/leased nodes, typed-topology
  / forbidden-cycle / poisoned-final-invariant-edge checks.
- **Callback idempotency** (`graph/callbacks.py`): keyed by `idempotency_key`;
  only a prior *accepted* callback short-circuits — rejections never poison
  the key. Stale rejection via `observed_graph_position`.
- **Resource claims / scheduler** (`graph/scheduler.py`): `claims_conflict` +
  `evaluate_readiness` enforce write/read/external/graph_write exclusion and
  glob-aware path overlap; repo-escape rejection.
- **File-state boundary** guards secret/residue capture at every submit
  (`dispatch.py:463`); rejection reuses the process-death path.

## Fragility list (observed, not speculative)

| # | Issue | Where |
|---|---|---|
| F1 | Kernel-purity leak: real subprocess/git/filesystem I/O inside `graph_runtime/file_state.py`, conceptually twinned with the pure `graph/file_state.py` classifier — easy to confuse | `graph_runtime/file_state.py:9-15` |
| F2 | Deliberate code duplication: `graph_driver._node_max_attempts` / `_node_payload` re-implement `graph_runtime.dispatch._node_payload` ("first writer wins") rather than import; legacy-input port fallback duplicated in `store.py:1571` and `projections.py:3901` | `workflow/graph_driver.py:1126` |
| F3 | 30-entry legacy selector shim `_LEGACY_SELECTOR_KIND_MAP` + `_normalize_legacy_selector` — intricate compat surface, likely bug source | `graph/models.py:250-354` |
| F4 | Verification outcome/verdict dual representation (`outcome`, `verdict`, nested `value.outcome`) with a "compatibility_alias" note in prompts | `graph/models.py:660-710`, `prompts.py:82` |
| F5 | `ClaudeGatekeeperClassifier.classify` raises `NotImplementedError` — LLM residue classification unwired; verdict parsing untested | `graph_runtime/gatekeeper.py:82` |
| F6 | Drive loop is a graveyard of dated incident fixes (lease TTL 300→3600s, per-node recovery budgets, no-progress signatures) that interact subtly | `graph_driver.py:586-708` |
| F7 | ~~W7 glob-overlap safety bug~~ **Corrected on verification**: the segment comparator IS implemented (`_segments_may_overlap`, `scheduler.py:339`; commits `018483a3b`, `cea6282c9`) — the residual fragility is that `docs/dynamic-graph/w7-glob-overlap-spec.md` and the status ledger still describe it as open | `graph/scheduler.py:339`, stale spec doc |
| F8 | Prompt-assembly size/compaction behavior has no dedicated tests beyond `test_graph_planner_packet.py` | `graph_runtime/prompts.py` |

## Solid — do not disturb

- The pure kernel boundary (`apply_command`/`reduce_event`): deterministic,
  replayable; `scenario.py` is a clean pure-replay harness. Heavily covered by
  `test_graph_commands.py`, `test_graph_projections.py`, `test_graph_models.py`.
- Patch validator invariants (role/stale/topology) — well-pinned by
  `test_patch_validator.py`, `test_graph_payload_field_allowlists.py`,
  `test_graph_dynamic_contract.py`.
- Scheduler resource-claim logic — pure, thorough tests.
- Outbox + controller transactions — crash points covered by
  `test_graph_outbox_crash_points.py`, `test_graph_controller_transactions.py`,
  startup recovery tests.
- FR acceptance suite (`test_graph_fr01…fr18_acceptance.py`) + dynamic e2e —
  broad invariant coverage.

Weakest test coverage: effectful `graph_runtime/file_state.py` git paths,
gatekeeper classifier (stubbed), prompt-assembly compaction.

See also: [design-history](design-history.md) ·
[runtime-runners-cost](runtime-runners-cost.md) ·
[overview](overview.md)
