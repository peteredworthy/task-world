# Tests and Documentation Adjudication Audit

## Purpose

Adjudicate what the unit/integration tests and documentation can establish for
the grounded UI foundation. This report preserves source-document intent while
separating executable behavior evidence from documented requirements,
historical observations, and unsupported capability labels.

The governing rule is conservative: a test is behavior evidence only when its
body exercises the relevant real Orchestrator object or boundary. A test that
replaces the subject, uses a recording stand-in, or only validates a serialized
shape proves no more than that narrower seam. Test source was inspected, but the
suite was not executed as part of this audit; every item below therefore means
"covered by an executable test construction," not "freshly observed green."

## Scope inspected

- The approved Phase 0-3 design, Task 9 brief, `AGENTS.md`, closed
  `catalog/scope.yaml`, delegation plan, source map, and foundation validator.
- `tests/unit/`: 220 `test_*.py` files and 3,243 statically matched test
  function definitions.
- `tests/integration/`: 148 `test_*.py` files and 1,347 statically matched test
  function definitions.
- Shared test fixtures and boundary enforcement in `tests/conftest.py`,
  `tests/unit/conftest.py`, and `tests/integration/conftest.py`.
- Representative high-value behavior paths covering lifecycle, graph runtime,
  events/replay, actions/authority, prompts/evidence, usage/cost, worktrees,
  clarifications, approvals, activity streaming, and foundation validation.
- `docs/ARCHITECTURE.md`, all files under `docs/intent/`, and the five unchanged
  JTBD source documents.
- All four files under `research/system/`.

The static counts are inventory aids, not collection or pass counts. Parameter
expansion, skipped cases, import failures, and runtime selection are not
represented. Slow, E2E, UI, and external-provider suites are outside Task 9's
declared test scope.

## Key findings

### Evidence qualification

| Provisional key | Classification | What the test construction establishes | Important limit | Evidence |
|---|---|---|---|---|
| `tests-doc.test-boundary` | tested invariant | Unit collection rejects full ASGI/test-client imports; integration fixtures construct a real FastAPI app, in-memory SQLite, ASGI transport, and real temporary git repositories. | Directory placement does not itself prove integration depth. Some integration tests still call private methods or inject stand-ins. | `tests/unit/conftest.py::_check_unit_test_file`; `tests/integration/conftest.py::_shared_app_fixture` |
| `tests-doc.graph-command-safety` | tested behavior | Real `GraphController`, event store, DB, patch validator, and HTTP readbacks reject stale, unauthorized, duplicate, hidden-command, resource-escalating, and active-retire patches without mutating topology. | This proves command validation and readback, not that a product UI explains each rejection safely. | `tests/integration/test_graph_fr08_acceptance.py::test_fr08_invalid_patch_matrix_rejected_and_readable` |
| `tests-doc.authority-denial` | tested behavior | A real graph decision endpoint records a human authority denial, releases the lease, binds the decision record, defers downstream work, and exposes scheduler/node/topology/event readbacks. | The request supplies a decider identity; the test does not prove authentication or authorization enforcement for that identity. | `tests/integration/test_graph_fr08_acceptance.py::test_fr08_authority_denial_and_rejection_readbacks` |
| `tests-doc.graph-completion` | tested invariant | Real graph driver/controller/store/git paths with deterministic protocol agents require accepted verification and a passed deterministic final check before completion; a failed final check prevents completion and pauses the run. | In-process agents prove orchestration, not live LLM behavior, provider callbacks, or production availability. | `tests/integration/test_graph_dynamic_e2e.py::test_dynamic_full_happy_path_completes`; `::test_dynamic_run_does_not_complete_while_final_invariant_check_fails` |
| `tests-doc.replay-parity` | tested invariant | Real SQLite graph event/read-model paths roll back atomically, rebuild idempotently, and preserve full/compact/checkpoint parity, including the July 4 corrective-supersession incident topology. | Synthetic event fixtures prove reducer/read-model behavior for represented histories, not every production history or legacy mutable path. | `tests/integration/test_graph_read_models.py::test_graph_read_models_are_rebuildable_and_idempotent`; `::test_july_4_incident_replay_preserves_supersession_and_completion_parity` |
| `tests-doc.node-evidence` | tested behavior | Real graph event storage builds node detail for identity, authority, resource claims, inputs, outputs, file state, leases, callbacks, and events; compact summaries omit heavy bodies while full mode retains them. | Prompt summaries and records are available projections, not a proof that every live runner supplies a complete transcript/tool trace. | `tests/integration/test_graph_node_detail_read_models.py::test_append_creates_and_updates_node_detail_summaries`; `::test_full_node_detail_path_keeps_heavy_output_and_file_state_detail` |
| `tests-doc.prompt-hydration` | partially tested | Real graph scheduling, dispatch construction, persistence, and artifact store produce readable summarizer/gap-planner prompt packets with bound records. | `_UnusedAgentFactory` and context capture stop before a real runner receives or acts on the packet. This proves packet construction, not delivery or comprehension. | `tests/integration/test_graph_fr09_acceptance.py::test_fr09_execution_packets_and_prompt_hydration_are_readable_for_less_used_nodes` |
| `tests-doc.activity-output` | partially tested | Real graph driver, file DB, git repo, output batcher, event store, and projection paths persist node-attributed worker/verifier output. | `OutputAgent` and `FakeConnectionManager` are injected stand-ins. The tests prove orchestration/persistence and manager fan-out, not a network WebSocket or external runner transcript. | `tests/integration/test_graph_activity_stream.py::test_graph_run_emits_agent_output_activity_events`; `::test_graph_run_broadcasts_output_via_connection_manager` |
| `tests-doc.activity-sse` | tested behavior | Real ASGI app and SQLite paths expose activity SSE, event delivery, cursor resumption, filtering, enrichment, not-found handling, and disconnect tolerance. | ASGI transport is in-process; no browser/network reconnect or long-duration backpressure claim follows. | `tests/integration/test_api_activity.py::test_sse_stream_endpoint_exists` through `::test_sse_stream_client_disconnect` |
| `tests-doc.usage-persistence` | tested invariant | Real graph controller and SQLite persist append-oriented node usage idempotently, rebuild run totals, retain exact provenance internally, and tolerate concurrent appends. | Fixtures create usage facts directly; producer coverage for every selectable live runner remains separate. | `tests/integration/test_graph_usage_persistence.py::test_controller_persists_usage_event_and_replays_run_usage_read_model`; `::test_concurrent_usage_appends_retry_and_persist_without_agent_death` |
| `tests-doc.cost-honesty` | tested invariant | Pure rollup logic plus a real API/SQLite read path groups graph usage, counts an execution once, bounds input/group cardinality, and exposes missing-rate execution/token coverage without inventing missing cost. | The endpoint reads graph `node_usage_recorded` facts only. It is not total fleet cost coverage and does not define budget pace or retry cost. | `tests/unit/test_cost_rollup.py`; `tests/integration/test_api_cost_rollup.py`; `tests/unit/test_model_costs.py` |
| `tests-doc.lifecycle-idempotency` | tested behavior | Real API, workflow, signal-drain, and persistence paths make duplicate submit, verification completion, and cancellation safe for the represented legacy workflow. | In-memory signal transport does not establish cross-process delivery semantics or all race cases. | `tests/integration/test_idempotency.py` |
| `tests-doc.agent-resume` | tested behavior | A real API/persistence/activity path can resume with changed runner configuration and emits `agent_changed`; unchanged resume preserves configuration and emits no change event. | The main switch test injects a no-op runner executor, so it proves control-plane state/audit behavior, not successful execution by the replacement runner. | `tests/integration/test_api_runs.py::test_resume_with_agent_change`; `::test_resume_without_agent_change`; `::test_resume_with_config_only_change` |
| `tests-doc.backward-transition` | tested behavior | Real API/workflow/DB paths move a legacy run to an earlier step, reject invalid/forward targets, and emit an auditable `run_step_backward` event. | This is a legacy run transition, not typed graph steering or planner replanning. | `tests/integration/test_api_backward_transitions.py` |
| `tests-doc.clarification` | tested behavior | Real service/repository/event-store paths persist clarification request/response, block submit while unanswered, preserve stale completed task state, resume building, and replay the represented projection. | It does not prove the full JTBD decision packet, downstream-effect explanation, or UI continuity. | `tests/integration/test_clarification_workflow.py::test_full_clarification_cycle`; `::test_pending_clarification_blocks_submit`; `::test_respond_to_legacy_stale_clarification_does_not_reopen_completed_task` |
| `tests-doc.approval` | partially tested | Real endpoint, DB, and event store persist step approval identity, comment, timestamp, and reject nonexistent/future targets. | The endpoint accepts approval without a configured-required comment, notes that the GET summary omits approval, and private executor tests do not prove a complete safe decision surface. Multiple approvals are last-write-wins. | `tests/integration/test_api_human_approval.py::test_approve_step_endpoint`; `::test_approve_step_without_comment`; `::test_approve_step_multiple_times` |
| `tests-doc.requeue` | tested behavior | Real API, outbox row, graph event store, dispatcher, and audit readback requeue a failed outbox item, reject invalid states, detect stale append, and dispatch it. | The dispatcher uses a recording executor; downstream external side-effect idempotency is not proved. | `tests/integration/test_graph_api.py::test_operator_requeues_failed_outbox_row_with_audit_event`; `::test_requeue_audit_append_translates_stale_position_to_conflict` |
| `tests-doc.locking` | contradicted/partial | Real lock and engine objects reject a second holder, expire passively, release on terminal completion/failure, and retain the lock through revision. | `LockTimeoutError` is tested only by manually raising it; the manager returns false or permits reacquisition and the engine also works without a lock manager. This does not satisfy a blanket claim that pessimistic locking is enforced in practice. | `tests/unit/test_locks.py`; `docs/ARCHITECTURE.md` TD-06 |
| `tests-doc.worktree` | tested behavior | Real git repositories exercise create/delete/list/isolation and dirty-worktree handling. | Tests establish git mechanics, not every completion-action or merge policy. | `tests/integration/test_worktree.py`; `tests/integration/test_branch_ops.py`; `tests/integration/test_conflict_back_merge.py` |
| `tests-doc.foundation-guard` | tested invariant | The real foundation validator, run as a subprocess over temporary packages, rejects unsupported current/derived/action/causal classifications, stale/unsafe evidence, unresolved references, and current/future leakage. | These checks govern foundation artifacts. They do not prove that the current product UI labels facts, inferences, approximation, or freshness correctly. | `tests/integration/test_ui_foundation_tools.py` |
| `tests-doc.mock-exclusion` | not qualifying | `test_make_graph_runner.py` verifies partial wiring by replacing `GraphRunDriver` and using `MagicMock`/`AsyncMock`. | It conflicts with the repository's no-mocking rule and cannot establish graph-run behavior. Exclude it from capability evidence. | `tests/unit/test_make_graph_runner.py` |

### Executable invariant index

The following invariants have qualifying real-object test constructions, subject
to a fresh green run:

1. Graph patch commands reject stale bases, unauthorized operations, invalid
   topology, hidden commands, resource escalation, and retirement of active
   nodes before accepted state changes become visible.
2. A final invariant does not resolve from verifier prose alone; accepted typed
   evidence and a passing deterministic check are required on the tested graph
   paths.
3. Event append and graph read-model updates share rollback behavior; graph
   summaries can be rebuilt idempotently from retained events.
4. Compact graph projections preserve tested lifecycle/task/final-gate outcomes
   while deliberately omitting heavy evidence bodies.
5. Accepted callbacks and usage records are idempotent under their tested keys;
   rejected/stale work remains explicit rather than silently accepted.
6. Missing pricing remains machine-visible through `rate_missing` counts/tokens;
   an unknown rate is not converted into a priced cost fact.
7. Clarification blocks submission until answered, and a stale answer cannot
   regress an already-completed task.
8. Invalid or stale operator graph actions return explicit rejection/conflict
   outcomes and qualifying actions create durable audit events.
9. Legacy submit, verification completion, cancellation, agent resume changes,
   and backward transitions are idempotent or state-validated on the represented
   API paths.
10. Foundation artifacts cannot label a capability current from documentation
    alone, admit an incomplete derivation, substitute proposed role policy for
    authorization, or retain unsupported causal labels.

### Documented-only and unsupported capability claims

| Provisional key | Preserved user intent | Adjudication |
|---|---|---|
| `tests-doc.comparable-cohort` | J8 requires an explainable cohort for predecessor comparison. | No cohort-selection algorithm, eligibility contract, comparison endpoint, or relevant unit/integration test was found. `routine_sha` round-trip tests prove one possible input only. Treat the JTBD `Derivable` label as unsupported; classification needs implementation evidence and a complete derivation or remains gap/unknown. |
| `tests-doc.health-classifiers` | J1 and the shared IA health model require honest, explained attention states. | Tests expose scheduler, blocker, event, usage, and final-gate inputs, but no tested shared classifier for Healthy/Needs decision/Degraded/Stalled/Runaway/Steered/Settled was found. These labels are documented product semantics, not current behavior. |
| `tests-doc.retry-information-delta` | J6/J7 require evidence that another retry adds information. | Attempt, grade, packet, and usage evidence exists in tested paths, but no deterministic information-delta detector was found in unit/integration tests. Do not infer it from repeated attempts. |
| `tests-doc.causal-narrative` | J4 needs ordered evidence that helps locate a causal moment. | Ordered events and joined readbacks are tested. A causal narrative or causal-gap detector is not; the foundation validator correctly rejects temporal evidence as a causal mechanism. Preserve the diagnostic goal but label current evidence as ordered/attributed, not causal. |
| `tests-doc.planner-horizon-blast-radius` | J2/J3/J6 need position, horizon, downstream effect, and final-gate impact. | Topology, regions, edges, scheduler buckets, patches, and final blockers are exercised. No single tested derivation for planner horizon, blast radius, or downstream effect was found. Inputs do not make those labels derived. |
| `tests-doc.detectors` | J7 requires prompt pressure, repeated work/tools, verifier churn, and retries without new information. | No matching behavior tests were found. Repetition-monitor internals or raw activity, where present, do not establish these named cross-run detectors. |
| `tests-doc.budget-pace` | J1/J6/J7 require burn, budget, and approximate retry cost. | Cost facts and graph rollups are exercised; budget pace, enforcement, alert threshold, and retry-cost algorithms are not. `docs/ARCHITECTURE.md` explicitly leaves budget blocking/thresholds for later work. |
| `tests-doc.honesty-product-ui` | JTBD honesty rules require freshness, derived labels/evidence, no growing-plan percentage, fact/inference separation, and approximate-value marking. | The foundation validator enforces semantic artifact honesty, but Task 9 found no unit/integration product-UI test establishing these presentation rules. They remain mandatory design/evaluation requirements, not current UI capability evidence. |
| `tests-doc.rubric-outcomes` | The evaluation rubric defines decision readiness, continuity, action safety, evidence access, and responsive integrity. | These are falsification criteria. No Task 9 test scope executes the scenario tasks or measures the stated thresholds. Never convert rubric text into implemented capability. |
| `tests-doc.typed-steering` | Journey C needs durable, scoped new knowledge and corrective replanning. | The JTBD documents themselves mark steering directives and steering planner support as a gap. Raw graph patch and backward-transition tests are not equivalent to typed steering. |
| `tests-doc.action-feedback-completeness` | Every action should show acceptance, validation, durable identity, resulting state, next activity, and race recovery. | Individual endpoints exercise subsets, especially graph decisions/requeue. No test establishes the complete six-part feedback bundle across all actions. Approval tests expose concrete omissions. |

### Documentation drift and stale claims

| Provisional key | Source conflict | Controlling evidence / disposition |
|---|---|---|
| `tests-doc.arch-router-count` | `docs/ARCHITECTURE.md` says 12 routers while listing 13. | Internal documentation contradiction; recount from current application wiring before using the directory map. |
| `tests-doc.arch-modules` | The same document says there are exactly nine canonical modules while its map includes top-level `artifacts`, `graph`, and `graph_runtime`. | Interpret "nine" only as the legacy import-discipline set, not the complete current architecture. The document must not establish entity or module completeness. |
| `tests-doc.arch-detector` | The directory map calls `runners/detection/detector.py` a wired legacy detector; TD-02 says it was deleted. | Treat the map entry as stale until source inspection. |
| `tests-doc.arch-codex-remote` | The production release gate says `codex_server_remote` exists and is exposed, contradicting the earlier four-selectable-runner contract and retired compatibility model. | Current runner contract in `AGENTS.md` and exercised API literals control; the remote release section is stale historical material. |
| `tests-doc.intent-agent-model` | Original intent/PRD/UI docs treat external MCP or `user_managed` as an always-selectable agent backend. | Current architecture distinguishes external REST/MCP clients from selectable runners. Preserve external-interaction intent, reject the selectable-backend label. |
| `tests-doc.intent-backward` | `docs/intent/22-REMAINING-GAPS.md` says backward transition has no engine method or endpoint. | Real API/workflow tests exercise `/api/runs/{id}/transition-back`; the gap statement is stale. |
| `tests-doc.intent-activity-sse` | The same document says no dedicated activity SSE endpoint exists. | Real ASGI tests exercise `/activity/stream`; the gap statement is stale. |
| `tests-doc.intent-agent-change` | Draft `25-AGENT-FLEXIBILITY.md` frames changing agent on resume as unavailable. | Real API tests exercise runner/config changes and `agent_changed`; retain the design history, not its opening current-state claim. |
| `tests-doc.intent-locking` | Intent/AGENTS describe pessimistic locking as non-negotiable or resolved. | Lock tests and Architecture TD-06 establish only process-local passive expiry and optional engine injection. Mark enforcement partial/conflicting. |
| `tests-doc.intent-event-source` | Original architecture and migration target describe event sourcing/reconstructibility as settled or desired. | Current Architecture explicitly says event-backed, not purely event-sourced. Graph rebuild tests qualify graph claims; legacy compatibility mutation paths prevent a system-wide sole-truth label. |
| `tests-doc.intent-configs` | Old PRD/examples/UI documents contain external routine sources, `project_id`, `user_managed`, queue-first lifecycle, model overrides, and CLI/API examples as if current. | These are design inputs and examples. They require endpoint/schema/source verification before any field/action is admitted to the semantic model. |
| `tests-doc.intent-test-analysis` | `docs/intent/test-analysis.md` is based on about 90 integration files, lists removed/renamed suites and historical runner modes, and recommends deleting a still-present stub. | Current inventory has 148 integration files. Use the document as 2026-04-09 test-debt history only. Its warning about private-method tests and timing remains relevant but must be remeasured. |
| `tests-doc.research-anchor` | All `research/system/` maps are anchored to HEAD `23746c228` from 2026-07-07, with line-number and commit claims; later runner updates do not refresh the base audit. | Treat every "current," "implemented," count, and gap claim as historical until checked against the present source/content snapshot. |
| `tests-doc.research-cost` | Historical research says no cross-run cost rollup and unmatched models silently become free. | Current real endpoint tests and model-cost tests establish a graph-only rollup with explicit missing-rate coverage. The old gap is stale, while producer and non-graph coverage remain open. |
| `tests-doc.research-incident` | Historical research says the July 4 supersession topology is unproven. | A named real SQLite replay/parity test now covers that represented incident history. It still requires a fresh run and does not prove all incident variants. |
| `tests-doc.research-prompt` | Historical graph research calls prompt compaction weakly tested. | FR-09 now adds real packet-construction coverage, but still stops before live runner receipt. Narrow the gap; do not erase it. |
| `tests-doc.no-mocking-conflict` | `AGENTS.md` and implementation notes prohibit mocking, yet `tests/unit/test_make_graph_runner.py` imports `AsyncMock`, `MagicMock`, and `patch`. | Exclude that file from behavior evidence and register it as a test-policy conflict for separate remediation. |

### Source-demand adjudication for the `tests-documentation` owner

- `jobs.J8.comparable-cohort`: gap/unknown from this audit; no executable
  definition or tested selection path.
- `honesty.derived-label-evidence`: documented mandatory policy; exercised for
  foundation artifacts, unexercised for current product UI.
- `honesty.no-growing-plan-percent`: documented mandatory policy; no product
  behavior test found.
- `honesty.fact-versus-inference`: documented mandatory policy; causal-label
  rejection is exercised in the foundation validator, product presentation is
  unexercised.
- `honesty.approximate-values`: documented mandatory policy; no product behavior
  test found.
- `ia.vocabulary.distinct-entities`: documented invariant demand. Existing
  graph/workflow tests use distinct identifiers, but no cross-projection
  vocabulary invariant proves the JTBD identity chain or slash equivalences.
- `rubric.*`: evaluation demands only. They preserve user intent and should
  falsify later concepts; they establish no current or derived capability.
- `rubric.derived-evidence-access`: foundation semantic contracts require
  evidence, but one-step product access is untested.
- `rubric.result-state-confirmation`: exercised for selected API actions, not as
  a universal product invariant.
- `rubric.viability-floor`: a future review decision rule, not implementation
  evidence.

## Important uncertainties

1. No unit/integration tests were run in this audit. The 4,590 statically matched
   definitions are not a current pass count; import, collection, skip, and
   runtime status remain unknown.
2. The Phase 0 content-hash snapshot covers the five JTBD documents and approved
   design, not Task 9's tests, `docs/ARCHITECTURE.md`, `docs/intent/`, or
   `research/system/`. Drift control for this report's decisive sources is
   therefore not yet canonical.
3. FastAPI/SQLite integration tests commonly use `InMemorySignalTransport` and
   deterministic or recording collaborators. They qualify API/domain/persistence
   behavior at those seams, not cross-process delivery, live-provider behavior,
   or network resilience.
4. External runner availability and callback fidelity are not established by
   the declared unit/integration scope. Relevant real CLI/OpenHands tests live
   under slow/E2E suites or are credential/environment skipped.
5. Product UI honesty, continuity, responsiveness, and one-step evidence access
   cannot be inferred from backend tests. UI tests were outside Task 9 scope and
   require separate projection/UI audit evidence.
6. Synthetic graph event fixtures establish accepted event shapes and reducer
   outcomes, but not production reachability unless paired with controller/API
   command construction.
7. Some integration tests intentionally inspect private methods or direct ORM
   state. Those are narrower implementation-regression evidence and should not
   be generalized into user-visible behavior.
8. Approval and authority tests do not establish enforced authentication or
   authorization merely because actor/decider fields are persisted.

## Conflicts found

1. **Test policy conflict:** repository rules prohibit mocking, but
   `tests/unit/test_make_graph_runner.py` uses standard-library mocks and patches
   the subject's downstream driver.
2. **Locking conflict:** intent calls pessimistic locking implemented and
   non-negotiable; tests plus Architecture TD-06 show passive process-local
   expiry, no manager-raised timeout error, and optional engine injection.
3. **Event-source conflict:** original intent says event log sole truth and full
   reconstruction; current architecture admits compatibility mutations. Graph
   replay is strongly exercised, but a system-wide event-sourced label is false.
4. **Runner conflict:** original intent treats external MCP/user-managed as a
   selectable backend; current architecture treats REST/MCP as interaction
   surfaces and exposes four selectable runner types.
5. **Current-gap conflicts:** intent claims backward transition, activity SSE,
   and resume agent change are missing while real integration tests exercise
   them.
6. **Architecture self-conflicts:** router count, canonical module count,
   detector location, and remote Codex release text disagree within
   `docs/ARCHITECTURE.md`.
7. **Research conflicts:** commit-anchored research claims missing rollups and an
   unproven supersession incident while newer real-object tests cover those
   narrower behaviors.
8. **JTBD capability conflict:** jobs label several projections `Derivable`, but
   the approved design requires a deterministic algorithm, unknown behavior,
   freshness, and current inputs. Comparable cohort and the named health/waste
   detectors do not meet that bar.

## Decisions required

1. During normalization, classify comparable cohort and the named health,
   causal-gap, retry-delta, blast-radius, budget-pace, and waste detectors as
   gap/unknown unless another bounded audit supplies reachable implementation
   and complete derivation evidence.
2. Decide whether the locking contract is a blocking semantic conflict: current
   test evidence supports local exclusion behavior, not the documented robust
   pessimistic-locking claim.
3. Keep original external-agent, event-sourcing, and interaction documents as
   intent/history, but select current architecture/tests as controlling for
   availability and behavior labels.
4. Decide whether Task 9's non-snapshotted evidence sources must be added to a
   refreshed content-hash snapshot before report normalization. The approved
   design says changed hashes invalidate affected claims.
5. Determine whether the mock-based unit file is removed/reworked in a later
   product task. This audit must not treat it as evidence.
6. Require separate UI evidence before admitting universal action confirmation,
   one-step derivation evidence, responsive integrity, selection continuity, or
   honesty-rule presentation as current.

## Artifact paths

- `research/ui-foundation/agent-reports/07-tests-documentation.md`
- `.superpowers/sdd/task-9-audit-report.md`

No canonical catalog, reality, capability, product, test, architecture, intent,
or JTBD file was edited by Task 9.

## Evidence pointers

Primary executable evidence:

- `tests/unit/conftest.py::_check_unit_test_file`
- `tests/integration/conftest.py::_shared_app_fixture`
- `tests/integration/test_graph_fr08_acceptance.py`
- `tests/integration/test_graph_fr09_acceptance.py`
- `tests/integration/test_graph_dynamic_e2e.py`
- `tests/integration/test_graph_read_models.py`
- `tests/integration/test_graph_node_detail_read_models.py`
- `tests/integration/test_graph_usage_persistence.py`
- `tests/unit/test_cost_rollup.py`
- `tests/integration/test_api_cost_rollup.py`
- `tests/integration/test_api_activity.py`
- `tests/integration/test_api_runs.py`
- `tests/integration/test_api_backward_transitions.py`
- `tests/integration/test_clarification_workflow.py`
- `tests/integration/test_api_human_approval.py`
- `tests/integration/test_graph_api.py`
- `tests/integration/test_idempotency.py`
- `tests/unit/test_locks.py`
- `tests/integration/test_worktree.py`
- `tests/integration/test_ui_foundation_tools.py`

Primary documentation and historical evidence:

- `docs/ARCHITECTURE.md`
- `docs/intent/README.md`
- `docs/intent/01-ARCHITECTURE.md`
- `docs/intent/02-OPEN-QUESTIONS.md`
- `docs/intent/03-PRD.md`
- `docs/intent/05-IMPLEMENTATION-PLAN.md`
- `docs/intent/06-EXAMPLE-CONFIGS.md`
- `docs/intent/08-UI-DESCRIPTION.md`
- `docs/intent/22-REMAINING-GAPS.md`
- `docs/intent/25-AGENT-FLEXIBILITY.md`
- `docs/intent/28-HUMAN-INTERACTION-DESIGN.md`
- `docs/intent/30-EVENT-DRIVEN-MIGRATION.md`
- `docs/intent/test-analysis.md`
- `docs/jtbd/jobs.md`
- `docs/jtbd/journeys.md`
- `docs/jtbd/decision-information.md`
- `docs/jtbd/information-architecture.md`
- `docs/jtbd/evaluation-rubric.md`
- `research/system/overview.md`
- `research/system/graph-kernel.md`
- `research/system/runtime-runners-cost.md`
- `research/system/design-history.md`

## Recommended next delegation

1. Recheck content hashes for every source normalized from this report; add a
   canonical snapshot decision if Task 9 evidence is to control Phase 1/2.
2. Run fresh focused real-object tests for every admitted finding, followed by
   `uv run pytest tests/unit tests/integration -q`. Record actual collection,
   pass, skip, and failure counts; do not reuse static counts from this report.
3. Delegate targeted source verification for unresolved locking, legacy
   event-source completeness, authentication/authorization enforcement, and
   live-runner evidence production.
4. Normalize documented-only JTBD claims as demands, not capabilities. Require
   complete derivation contracts for any proposed `derived` classification.
5. Send the Architecture/intent/research drift list to a later documentation
   maintenance task. Do not repair those source documents during Phase 1 audit
   normalization.
