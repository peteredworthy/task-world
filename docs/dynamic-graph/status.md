# Dynamic Graph Proof Ledger

This is the source of truth for current dynamic graph work. Progress is measured
by validated functional requirements from
`docs/dynamic-graph/typed-work-graph-requirements.md`, not by implementation
slices, clean tests, or static checks.

Tests are regression evidence only. A row is not `validated` unless the dynamic
graph feature has been used through the product path it is meant to support: an
orchestrator-created graph run, driven through the graph workflow/API/runtime
surface, with observable graph events/readbacks showing the required behavior.

Older status logs, run ledgers, and comparison plans are archived in
`docs/dynamic-graph/complete/`.

The current remaining-work and proof-scenario update is available as
`docs/dynamic-graph/remaining-fr-validation-plan.html`. It summarizes the
remaining FR proof clusters, the systemic testing gaps that let product-path
bugs escape isolated tests, and the minimal state-pack/product scenarios needed
to close the ledger without repeatedly rerunning broad dogfood tasks.

## Current Regression Evidence

Regression checks are useful guardrails, not validation:

```bash
uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 716 passed in 13.97s, before the latest dispatch fix

uv run pytest tests/unit/test_scheduler.py tests/unit/test_graph_commands.py tests/unit/test_graph_scheduler_view.py -q
# 145 passed, before the latest dispatch fix

uv run pytest tests/unit/test_graph_dispatch_on_output.py -q
# 28 passed in 2.18s, after the latest dispatch fix

uv run pytest tests/unit/test_graph_dispatch_on_output.py::test_execute_check_command_cites_bound_verification_and_region_file_state tests/unit/test_graph_projections.py::test_check_result_candidate_id_does_not_replace_latest_task_candidate tests/integration/test_graph_event_store.py::test_read_run_light_preserves_projection_fields_without_heavy_payloads -q
# 3 passed in 2.12s

uv run pytest tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/integration/test_graph_outbox_crash_points.py tests/integration/test_graph_event_store.py -q
# 215 passed in 6.02s

uv run ruff check src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/file_state.py src/orchestrator/graph_runtime/store.py src/orchestrator/graph/commands.py src/orchestrator/graph/projections.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/integration/test_graph_outbox_crash_points.py tests/integration/test_graph_event_store.py
# All checks passed

uv run pyright src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/file_state.py src/orchestrator/graph_runtime/store.py src/orchestrator/graph/commands.py src/orchestrator/graph/projections.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/unit/test_graph_scheduler_view.py::test_scheduler_view_buckets_ready_resource_deferral -q
# 1 passed in 0.93s

uv run pytest tests/integration/test_graph_node_detail_read_models.py::test_append_creates_and_updates_node_detail_summaries -q
# 1 passed in 2.31s

uv run ruff check src/orchestrator/api/routers/graph.py src/orchestrator/graph_runtime/store.py tests/integration/test_graph_node_detail_read_models.py
# All checks passed

uv run pyright src/orchestrator/api/routers/graph.py src/orchestrator/graph_runtime/store.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/integration/test_graph_runner_e2e.py::test_reconcile_runtime_skips_lease_already_recovered_by_another_driver tests/integration/test_graph_runner_e2e.py::test_graph_runner_restart_marks_missing_builder_dead_and_redispatches -q
# 2 passed in 2.92s

uv run ruff check src/orchestrator/graph_runtime/controller.py src/orchestrator/graph_runtime/dispatch.py tests/integration/test_graph_runner_e2e.py
# All checks passed

uv run pyright src/orchestrator/graph_runtime/controller.py src/orchestrator/graph_runtime/dispatch.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/integration/test_graph_api.py::test_graph_projection_uses_paused_run_row_as_effective_state tests/integration/test_graph_api.py::test_graph_projection_reflects_seeded_events -q
# 2 passed in 2.53s

uv run ruff check src/orchestrator/api/routers/graph.py tests/integration/test_graph_api.py
# All checks passed

uv run pyright src/orchestrator/api/routers/graph.py
# 0 errors, 0 warnings, 0 informations
```

The latest code fix in `src/orchestrator/graph_runtime/dispatch.py` is driven by
product evidence from the dogfood run, not by a blind implementation slice:
dynamic feature verifier packets now fall back to the feature acceptance
requirement when no explicit requirement nodes are bound, and rejected submit
callbacks are surfaced instead of being treated as successful agent submission.
Follow-up fixes from the same product proof prevent check results from becoming
synthetic task candidates, preserve nested check status in light graph readbacks,
and propagate check-result citations from bound verification/file-state evidence.

## Product-Path Evidence

Dogfood run `e2c81109-ea77-496c-9d62-7f35fb17f296` used the real
`dynamic-graph-feature` routine, `/api/runs`, graph execution mode, a worktree,
and the `codex_server` runner. It reached planner, worker, and verifier nodes;
the worker changed the actual worktree artifact. The verifier received no real
requirement packet, submitted without grades, and the graph correctly rejected
the callback with `verification record at index 0 missing grades`. The run then
paused with an active verifier lease and no accepted callback. This is product
evidence for callback validation and blockers, and also evidence of a real
packet/dispatch bug.

Dogfood run `2aa3be3b-7900-49c8-8cc3-06e9b0eb99c6` re-ran the scenario after
the dispatch fix. It created planner-authored worker/verifier/gap/corrective
nodes and typed edges, accepted a worker candidate and file-state record, gave
the verifier a requirement fallback, accepted a real grade callback
(`R-01=A`), bound verification evidence into the gap planner, rejected a
duplicate gap edge patch, accepted a corrected gap patch, emitted gap records,
dispatched a corrective worker that updated the worktree artifact and ran the
configured acceptance command, recovered a dead final-check lease after restart,
ran the deterministic hidden-oracle check, and reached run status `completed`.
After the readback fixes, product API readbacks show `/graph/final-blockers`
returns `[]`, `/graph/regions` returns `region-dynamic-feature-2=accepted`,
and `/graph/scheduler` returns no ready/blocked work and no active leases.

Dogfood run `f85e3af1-297f-4966-9a5f-51d20c173456` was a fresh post-fix run
created to validate the final check citation change through the product path. It
created topology, exposed typed blockers for pending corrective/final nodes, and
eventually completed. Its final check ran before the corrective candidate and
did not cite candidate/file-state/evaluated records, proving the previous
ledger claim was too strong and exposing a stale-check acceptance gap.

Dogfood run `395b07e6-2048-496e-a56f-1d2d213f46f1` was run after tightening
check acceptance to require citations to the latest candidate/file-state
evidence. It proved the dispatch-side citation expansion by producing verifier
output with both candidate and file-state IDs, but the command validator
rejected it because validator-side citation derivation still expected only
directly bound candidate IDs. The same run also exposed two separate product
gaps: callback staging attempted to include the worktree `.venv`, and resume
after startup pause reported `is_graph_backed=false` instead of cleanly
recovering the graph run.

Dogfood run `b213b5df-b30e-4584-bb6f-a90b8c6ec277` was a fresh patched run
after aligning command validation with dispatch citation expansion. It used the
real `/api/runs` product path, graph execution mode, worktree `worktrees/r313`,
and the `codex_server` runner. The planner created worker, verifier, gap
planner, and final-check nodes; the worker produced candidate
`dogfood-smoke-5-candidate` and file-state
`file-state-exec-0be7fbaeeadf468799636aef6bd53113`; the verifier accepted
`verification-exec-3aa73ea6f44d4922a7a4d553e3fa1f45` with both
`candidate_record_ids` and `file_state_record_ids`; the deterministic final
check accepted `check-exec-e1e4e0f0830d492a9e889712febed5a9` with
`evaluated_record_ids` containing the verifier record, candidate record, and
file-state record; `/graph/scheduler` returned no ready/blocked/leased work;
`/graph/final-blockers` returned `[]`; and the run reached status `completed`.
After this product proof, `capture_file_state_boundary` was narrowed so ignored
`tool_cache` paths such as `.venv` remain classified in file-state evidence but
are not force-included into snapshot staging; that fix is regression-proven and
needed a follow-up product run to prove the broad callback-staging issue was
closed.

Dogfood run `5268031d-2b1a-415e-bead-7d364c10eb59` was the fresh product run
after the `.venv`/tool-cache staging fix. It used the real `/api/runs` graph
path, graph execution mode, worktree `worktrees/r314`, and the `codex_server`
runner. The worktree had an ignored `.venv/` directory. Worker file-state
`file-state-exec-0e05ad8d6a974e6f921a7385fbc73ad6` was accepted with ignored
`.venv` and `ui/node_modules` entries classified as `tool_cache`; its snapshot
commit `a892b000f444191fe7b171cabe112ba5037f1880` contained
`docs/dynamic-graph/dogfood-smoke-output-6.txt` and zero `.venv/` paths. The
artifact content was read back from the worktree as exactly
`dynamic graph dogfood ok 6`. The verifier accepted
`verification-exec-29e9863403fa4a2a8ebd8b4b12897d95` with
`candidate_record_ids=[dogfood-smoke-6-candidate]` and
`file_state_record_ids=[file-state-exec-0e05ad8d6a974e6f921a7385fbc73ad6]`; the
final check accepted `check-exec-33e408ffa16c462f9aecc3418e7d4c9a` with
`evaluated_record_ids` containing the verifier, candidate, and file-state
records, and it ran against snapshot
`dd529579652f448c825a467aa368688b`. `/graph` showed all runtime nodes
completed and `region-dogfood-smoke-6=accepted`; `/graph/scheduler` had no
ready, blocked, or leased work; `/graph/final-blockers` returned `[]`; and the
run reached status `completed`.

Dogfood run `3c5bfc81-9f0c-4cfb-bab5-cb0877ce86bd` was a resource-conflict
probe for FR-15. It used the real `/api/runs` graph path, graph execution mode,
worktree `worktrees/r315`, and the `codex_server` runner. The planner created
two independent workers in `region-resource-conflict-1` with repo write claims.
`worker-resource-conflict-a` received lease
`lease-b0cdb1a25b54474a9661ce7b062f45f5` at graph position 54 while
`worker-resource-conflict-b` was ready; the scheduler emitted
`node_deferred` at position 57 with `resource_conflict:write:write`. After
worker A accepted `candidate-rcf-a` and file-state
`file-state-exec-34de2b4cafc941b59d3456c7842bce5c`, the lease was released at
position 65. The next useful scheduler sequence re-readied worker B at position
76, granted lease `lease-830534fbd1ac49aabc39d57626ad1f07` at position 77, and
worker B accepted `candidate-rcf-b` with file-state
`file-state-exec-cf181eded15740ff95205e7cfd262b7c` before completing at
position 96. The worktree files were read back as exact contents
`resource conflict A` and `resource conflict B`. This product run also exposed
that the scheduler API did not bucket a ready-but-resource-deferred node under
`waiting_resources`; `project_scheduler_view` has been fixed and regression
tested, but that readback fix still needs a fresh product readback at the live
conflict moment. After an operator restart, resume produced recovery events
`agent_died`, `lease_revoked`, `runtime_retry_scheduled`, a recovery-plan
record, and `verifier-resource-conflict-b` returning to `ready`; subsequent
full `/run` and `/graph` readbacks timed out under load, so this run is not
terminal-completion proof.

During the 2026-06-22 temporary server session, startup recovery for the same
`3c5bfc81...` run also logged a duplicate-position append failure
(`UNIQUE constraint failed: events_v2.aggregate_id, events_v2.version`) and a
later SQLite `database is locked` error while recovering/driving the stale run.
This is product-path evidence that graph recovery/re-entry still has an
idempotency or concurrency gap; it strengthens, rather than closes, the FR-12
remaining work.

The first targeted FR-12 fix after that product failure makes runtime
reconciliation re-read durable graph state before converting recovered leases
to `agent_died`; if another driver or restart path has already revoked the
lease, reconciliation skips it instead of appending a rejected command, and if
the graph position goes stale it retries only while the lease remains active.
This is regression-proven by an integration test with real DB/controller/outbox
objects, but not product-validated yet: it still needs a server recovery run
that shows the duplicate-position/lock class no longer occurs.

Follow-up product API probe on 2026-06-22 restarted the temporary server on the
same dogfood DB after the stale-report guard. Startup did not re-arm
`3c5bfc81...` because the run was already paused with
`pause_reason=graph_blocked`; no duplicate-position or SQLite-lock error
appeared during startup/readback, but this did not exercise the stale recovery
guard. The public `/api/runs/3c5bfc81...` readback returned quickly with
`status=paused`, `is_graph_backed=true`, and `last_error` listing failed
`gap-planner-resource-conflict` and `verifier-resource-conflict-b` nodes.
`/graph`, `/graph/scheduler`, `/graph/regions`, and `/graph/final-blockers`
also returned quickly instead of timing out. `/graph` returned `event_count=154`
and no ready nodes, but its projected `run_state` was still `active` while the
public run row was paused; that is a remaining API/readback coherence gap.
Node-detail summary readbacks for `worker-resource-conflict-a` and
`worker-resource-conflict-b` returned released leases and top-level
`resource_claims=[{"mode":"write","scope":"repo"}]`, proving resource-claim
summary readback for worker nodes. Topology readback returned 11 nodes and 10
edges, but the stale run's edge rows did not expose binding policy or bound
record positions, so FR-06 remains partial.

After adding the `/graph` effective-state fix, the temporary server was
restarted and the same product readback returned coherent state for
`3c5bfc81...`: public `/api/runs/{id}` reported `status=paused`,
`pause_reason=graph_blocked`, and `is_graph_backed=true`; `/graph` reported
`run_state=paused`, `event_count=154`, no ready nodes, and
`region-resource-conflict-1=pending`.

Follow-up product API readbacks on 2026-06-22 used the temporary server against
the same dogfood DB and exposed both proof and gaps. For completed run
`5268031d-2b1a-415e-bead-7d364c10eb59`, summary node-detail readbacks for
`planner-s-01`, `worker-implementation-dogfood-smoke-6`,
`verifier-validation-dogfood-smoke-6`, and
`check-final-invariant-dogfood-smoke-6` returned node kind/role/state,
contract keys, input ports, output/file-state record IDs, released lease data,
and callback history. `/graph/decisions` returned an empty pending-gate,
appeal, and review view for both `5268031d...` and `3c5bfc81...`.
`/graph/scheduler` and `/graph/regions` returned quiescent accepted state for
`5268031d...` and explicit missing-input blockers for the paused
`3c5bfc81...` run. Bounded full `/graph/events?from_position=45&limit=40`
readback on `3c5bfc81...` returned the raw product evidence for write-claim
resource behavior: `lease_granted` at positions 54 and 77 carried
`resource_claims=[{"mode":"write","scope":"repo"}]`, `node_deferred` at
position 57 carried `resource_conflict:write:write`, and releases/second lease
followed in order. Full node-detail readback on the existing DB timed out, and
old summary rows did not contain resource/control fields, so node-detail
resource/control readback remains a product gap. The code now preserves
`resource_claims`, `allowed_actions`, `preconditions`, and
`command_definition` in future node-detail summaries, but that is regression
evidence until a fresh product run exercises it.

Unsupported-runner product probe `b9621fcc-7094-4be1-b526-eb54f302f94a` was
created through `/api/runs` with `dynamic-graph-feature`, `execution_mode=graph`,
and `agent_runner_type=cli_subprocess`. Starting it through
`POST /api/runs/{id}/start` returned 202; public run readback then moved to
`status=paused` with `pause_reason=graph_runner_unsupported` and
`last_error="Graph execution requires a runner with native graph callback tools;
unsupported runner 'cli_subprocess'. Supported runners: claude_sdk,
codex_server."` The run reported `is_graph_backed=false` and
`/graph/events` returned zero events, proving unsupported graph runners fail
before graph seeding or agent execution.

## Functional Requirements Ledger

| ID | Required behavior | Acceptance criteria | Implementation evidence | Validation evidence | Status | Remaining gap / next proof needed |
|---|---|---|---|---|---|---|
| FR-01 Scope and bootstrap | A graph run starts from a feature goal/routine snapshot, creates typed planner/worker/verifier/check/control topology, routes records, schedules work, supports authorized mutation, and completes only by invariants. | Real orchestrator graph run reaches terminal completion through planner-authored topology and cannot complete while final invariants fail. | `src/orchestrator/graph/compiler.py`, `src/orchestrator/workflow/graph_driver.py`, `src/orchestrator/graph/commands.py`, `src/orchestrator/graph_runtime/dispatch.py`. | Product run `2aa3be3b...` completed through planner-authored topology, worker/verifier/gap/corrective/check path, recovery, accepted region, and empty final blockers. Fresh run `f85e3af1...` exposed typed blockers instead of false completion. | partial | Need explicit product proof that a failed final invariant prevents completion, plus non-smoke topology coverage before calling the bootstrap/completion contract validated. |
| FR-02 Canonical node taxonomy | Canonical graph node types are registered with contracts. | Product run creates/uses canonical node kinds and readback exposes their contracts. | `DEFAULT_NODE_CONTRACTS` in `src/orchestrator/graph/contracts.py`. | Product topology/events showed `root`, `artifact`, `planner`, `worker`, `verifier`, and `check` nodes created by planner/runtime. Decision/recovery families were not exercised. | partial | Inspect node-detail contract readback in a live run; separately prove decision/recovery node families when a scenario needs them. |
| FR-03 Node contract schema depth | Node contracts and runtime controls govern validation, scheduling, prompt rendering, tool exposure, lifecycle, completion, deterministic handlers, and readback shape. | Real graph run shows contract-derived tools/ports plus runtime controls such as resource claims, preconditions, command definitions, leases, and node detail readback. | `contracts.py`, `scheduler.py`, `dispatch.py`, `commands.py`, `api/routers/graph.py`. | Product run exercised graph patch tools, submit/grade callbacks, leases, scheduler readback, and command execution. 2026-06-22 product node-detail summary readbacks for completed planner/worker/verifier/check nodes returned contracts, ports, output/file-state record IDs, released leases, callbacks, and lifecycle state. Bounded full event readback on `3c5bfc81...` returned write resource claims and conflict deferral evidence; follow-up node-detail summary readbacks for both conflict workers returned top-level write `resource_claims` from released leases. | partial | Fresh product run must still prove node-detail summary readback includes non-resource control fields (`allowed_actions`, `preconditions`, `command_definition`) and completion-rule detail before marking schema depth validated. |
| FR-04 Universal typed record envelope | Records on graph edges have immutable IDs, type/schema metadata, producer identity/port, run/position/time enrichment, payload, and provenance. | Real run emits accepted bootstrap, candidate, file-state, verification, check, and completion records with enriched universal fields. | `models.py`, `store.py`, `commands.py`, `compiler.py`. | Product run emitted bootstrap, candidate, file-state, verification, gap, recovery, and check records with graph positions and producer identity. Completion is reflected in lifecycle/readbacks; no separate completion-decision record was produced in this scenario. | partial | Decide whether `completion_decision` is required for this routine shape or explicitly out of scope for check-gated dynamic feature runs. |
| FR-05 Record type catalog and producers | Required record types have concrete typed contracts and producer/callback validation paths. | Real run produces the required record families and rejects malformed/unsupported output paths through runtime callbacks. | `models.py`, `commands.py`, `compiler.py`, `projections.py`, `dispatch.py`. | Product runs rejected a malformed verifier record, accepted candidate/file-state/verification/gap/check/recovery records, and exposed missing-grade and pending-node diagnostics. | partial | Completion-decision and decision-node record families still need either product proof or explicit narrowing. |
| FR-06 Typed edges and bindings | Edges validate endpoints/ports/schema/cardinality/policies and bind accepted records deterministically. | Real topology readback shows typed edges, bound record IDs, policies, metadata, and no missing required inputs at completion. | `contracts.py`, `commands.py`, `projections.py`. | Product run bound candidate/file-state into verifier, verification into gap planner, classified gap into corrective work, corrective verification into final check, and ended with accepted region and no final blockers. Follow-up topology readback for `3c5bfc81...` returned 11 nodes and 10 edges, but edge rows did not expose binding policy or bound-record positions for this stale run. | partial | Need product topology/readback proof for bound record IDs, binding policies, metadata, cardinality, contract details, and broader fan-out/join/optional-edge shapes. |
| FR-07 Planner graph mutation tools and macros | Planner/gap-planner mutate topology through validated tools/macros, with raw ops only as validated patch expansion. | A real planner submits graph patches/macros through `submit_graph_patch`; accepted/rejected attempts are visible in patch readback. | `macros.py`, `runners/agents/codex/common.py`, `dispatch.py`, `commands.py`. | Product run accepted the initial planner patch, rejected a duplicate gap edge patch, accepted a corrected gap patch, and `/graph/patches` was used during proof gathering. | partial | Need product proof for the broader macro/tool catalog, including joins, gates, retire/supersede, and invalid macro/tool rejection paths. |
| FR-08 Mutation validation and authority | Patch acceptance enforces actor authority, freshness, topology safety, resource safety, active-node safety, hidden-command scrubbing, and diagnostics. | Real run shows authorized accepted patches and deterministic rejection for unsafe paths. | `commands.py`, `contracts.py`, `macros.py`, `dispatch.py`. | Product run proved authorized accepted patches and duplicate-edge rejection diagnostics. Authority/resource/active-node/hidden-command safeguards are regression-proven but not product-proven. | partial | Run bounded product invalid-patch probes for authority/resource/hidden-command cases, or mark specific probes out of scope with rationale. |
| FR-09 Execution packets and prompt hydration | Executable nodes receive packets derived from contracts and bound records; prompt hydration policies shape visible evidence. | Real graph runner receives planner/worker/verifier/gap/check packets with expected tools and hydrated references. | `dispatch.py`, `runners/agents/codex/common.py`, `projections.py`, `api/routers/graph.py`. | First product run proved verifier packets could miss requirements. The fallback fix produced real verifier grades in `2aa3be3b...`; final check resolved and executed the hidden-oracle binding. | partial | Node-detail packet readback for every node kind still needs explicit product capture. |
| FR-10 Scheduler readiness | Scheduler only marks nodes ready when lifecycle, lease, inputs, gates, authority, command bindings, resources, retry, and preconditions allow. | Real scheduler readback shows ready/deferred transitions matching graph state during a run. | `scheduler.py`, `commands.py`, `projections.py`. | Product scheduler/readback evidence showed missing-input deferrals, readiness after bindings, final check retry after recovery, then no ready/blocked/leased work after completion. Product run `3c5bfc81...` additionally proved overlapping repo write claims defer a ready worker with `resource_conflict:write:write` until the first write lease releases. | partial | Need product proof for gate, authority, command-binding, retry/precondition readiness and live `waiting_resources` API bucketing. |
| FR-11 Scheduler ordering and fairness | Ready nodes are deterministically ordered and controller/deterministic work can run before agent work without starvation. | Real run dispatch order reflects graph priorities/kinds and all eligible nodes progress. | `scheduler.py`, `dispatch.py`. | Product event order showed deterministic dependency order across planner -> worker -> verifier -> gap -> corrective worker. Fairness across competing ready nodes is not product-proven. | partial | Use a product scenario with multiple independent ready nodes and verify deterministic/fair dispatch order. |
| FR-12 Lease, execution, retry, heartbeat, cancellation, and recovery durability | Leases/executions/failures/recovery are durable and replayable. | Real run emits durable lease/execution facts; runner failure or retry path is exercised or explicitly not needed for the validated scenario. | `commands.py`, `projections.py`, `store.py`, `graph_driver.py`; `GraphController.read_projection` plus `reconcile_runtime` stale-report guard in `src/orchestrator/graph_runtime/dispatch.py`. | Product run `2aa3be3b...` recovered a dead final-check lease after server restart with `agent_died`, `lease_revoked`, `runtime_retry_scheduled`, `recovery_plan`, re-lease, check completion, and terminal run completion. Product run `3c5bfc81...` added recovery evidence for a stale verifier lease after restart/resume, but follow-up readbacks timed out before terminal completion; a later temporary server session logged duplicate-position recovery append and SQLite lock errors for the same stale run. Regression now proves stale recovery reports skip already-revoked leases instead of adding rejected commands. A follow-up product startup/readback probe after the guard had no duplicate/lock errors, but did not exercise recovery because the run was already paused `graph_blocked`. | partial | Product-run a recovery re-entry path that actually exercises the stale-report guard and prove no duplicate-position/SQLite-lock failure; heartbeat and cancellation remain unvalidated; the stale run is now readable but still blocked/failed. |
| FR-13 Progress safety and quiescence blockers | Graph cannot silently stop while work is possible; blockers explain non-terminal or impossible states. | Real run exposes blockers while incomplete and no blockers once complete; failed final invariant keeps run non-completed. | `commands.py`, `projections.py`, `graph_driver.py`, `api/routers/graph.py`. | Product evidence includes first-run callback blocker, fresh-run typed pending blockers, and completed-run `/graph/final-blockers` returning `[]` after accepted final check. | partial | Need a failed-final-invariant product probe proving the run remains non-completed with explicit blockers. |
| FR-14 Region and completion semantics | Task regions are completion groups and acceptance requires candidate/file-state/verifier/check/gate evidence. | Real region readback shows pending -> accepted transitions only after typed evidence exists. | `compiler.py`, `macros.py`, `projections.py`, `commands.py`. | Product readbacks showed pending/in-progress states before evidence and `region-dynamic-feature-2=accepted` only after corrective candidate, verifier pass, file-state, final check, and empty blockers. | partial | Need product proof for completion-decision/final-gate semantics or an explicit scope decision that check-gated dynamic feature runs do not emit separate completion decisions. |
| FR-15 File-state and worktree semantics | Worker authority, file-state capture, downstream consumption, resource conflicts, checks, citations, and cleanup are graph work. | Real worker changes a scoped file, file-state is captured, verifier/check cite candidate/file-state records, and final state is inspectable. | `commands.py`, `dispatch.py`, `file_state.py`, `projections.py`. | Product run `b213b5df...` completed with verifier citations to candidate/file-state and final check `check-exec-e1e4e0f0830d492a9e889712febed5a9` citing verifier, candidate, and file-state records. Product run `395b07e6...` exposed that callback staging can try to add worktree `.venv`. Product run `5268031d...` proved the fix through the product path: ignored `.venv` was classified as `tool_cache` in file-state evidence, the captured snapshot commit contained the target artifact and zero `.venv/` paths, verifier/check records cited candidate and file-state evidence, API readbacks showed accepted region/no blockers/completed run, and the artifact content was read back from the worktree. Product run `3c5bfc81...` proved overlapping write-claim behavior: worker B was deferred for `resource_conflict:write:write` while worker A held a write lease, then worker B was leased and completed after worker A released; both worker artifacts were read back with exact content. | partial | Need product proof for cleanup as explicit graph work, path-scoped non-conflicting write claims, and failed/revoked write-lease cleanup. |
| FR-16 Runner support and callback enforcement | Supported graph runners and callbacks enforce submit/grade/patch/heartbeat/artifact/output/failure paths; unsupported runners fail early. | Real graph run uses a supported runner and callback path; unsupported-runner behavior has product-path proof or remains unvalidated. | `graph_driver.py`, `runners/agents/codex/common.py`, `dispatch.py`, `commands.py`. | Product `codex_server` runner used `submit_graph_patch`, `submit`, and `grade`; callback rejection was observed and dispatch was fixed to surface it. Product probe `b9621fcc...` proved `cli_subprocess` graph runs pause with `graph_runner_unsupported` before graph seeding and emit zero graph events. Heartbeat/artifact/failure callback paths are not product-proven. | partial | Dogfood heartbeat, artifact/output, and failure callback paths remain unvalidated. |
| FR-17 API and readback | APIs expose topology, node details, scheduler, leases, patch attempts, regions, bindings, blockers, decisions, and rebuildable projections. | Real run readbacks from API return coherent graph state during/after execution. | `api/routers/graph.py`, `api/__init__.py`, `projections.py`, `store.py`; `/graph` now reports the effective paused/terminal run-row state when graph events exist. | Product proof used `/api/runs`, `/activity`, `/graph/events`, `/graph/scheduler`, `/graph/topology`, `/graph/regions`, `/graph/final-blockers`, and `/graph/patches`; restart readbacks were fixed to show accepted region and empty blockers from light events. 2026-06-22 API probes added node-detail summary proof for contracts/ports/records/leases/callbacks, empty decision-view proof for completed/paused runs, coherent scheduler/region readbacks for completed and paused runs, and bounded full event readback for resource-conflict facts. Follow-up stale-run readback proved `/run`, `/graph`, `/graph/scheduler`, `/graph/regions`, `/graph/final-blockers`, `/graph/topology`, and worker node-detail summaries return quickly instead of timing out, and worker node detail exposes resource claims. It then exposed and fixed a coherence gap; patched product readback returned `/run.status=paused` and `/graph.run_state=paused` for `3c5bfc81...`. Product run `3c5bfc81...` also exposed a scheduler readback gap for ready nodes deferred by resource conflicts; the projection fix is regression-proven but not yet product-readback-proven. | partial | Decision readback with actual pending gates/authority decisions, non-resource node-detail controls, edge binding metadata, and live `waiting_resources` readback remain unvalidated. |
| FR-18 End-to-end product proof | A dynamic feature scenario completes from planner-created topology through worker -> verifier -> gap planner -> corrective worker -> verifier -> check -> final gate, with blocked completion until evidence exists. | A real or dogfooded product run demonstrates the full behavior using the intended graph runner/workflow, not only a scripted test harness. | `tests/integration/test_graph_dynamic_e2e.py` mirrors the desired path; runtime code in graph driver/controller/dispatch. | Product run `2aa3be3b...` completed through planner -> worker -> verifier -> gap planner -> corrective worker -> verifier -> deterministic hidden-oracle check -> accepted region -> empty blockers -> run `completed`, including recovery after restart. Fresh run `f85e3af1...` shows typed blockers when a new planner shape does not reach completion. | partial | Need explicit final-gate/completion-decision proof, blocked-completion proof before final evidence, and a harder-than-smoke feature scenario before this is validated. |
| FR-19 Comparison-oracle admission | Carrier comparison oracles, hidden tests, and S3 admission are measurement harnesses, not product functionality. | Product completion is not blocked by comparison admission. | `docs/dynamic-graph/complete/comparison-s3-active-graph-diagnostics-spec.md`, `scripts/compare_carriers.py`. | Not required for product validation. | out of scope | Keep comparison status separate from typed-work-graph functional completion. |

## Smallest Incomplete Proof Set

Do not start another broad implementation slice. The next work must move these
rows:

1. FR-03/FR-17: product-prove node-detail resource/control readback from a
   fresh run, investigate full node-detail timeout, capture decision readbacks
   with actual pending gate/authority records, and product-prove the fixed
   `waiting_resources` bucket during a live resource conflict.
2. FR-12: investigate the post-resume `/run` and `/graph` readback timeouts
   seen in `3c5bfc81...`; heartbeat and cancellation remain unvalidated.
3. FR-08/FR-11/FR-16: run bounded product probes for authority/hidden-command
   rejection, multi-ready fairness, heartbeat/cancel, and graph callback
   heartbeat/artifact/failure paths.
