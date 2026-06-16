# Dynamic Graph Operational Plan

## Objective

Bring the dynamic execution graph from "working static carrier with kernel
planning primitives" to **full operational status**:

- a real planner agent can inspect graph state and submit validated graph
  patches;
- graph patches create executable future regions during a run;
- gap analysis can append corrective work after local verifier success;
- final completion is blocked by graph-wide invariants, not by the original
  routine sequence ending;
- the system is observable and measurable enough to run the true comparison in
  `true-comparison-plan.md`.

This plan deliberately combines two execution styles:

1. **Task-world orchestrator runs** for implementation slices, review, retries,
   durable run state, and evidence.
2. **Mind the Gap discipline** inside and between slices: baseline first,
   planner/gap-finder chooses the next independently verifiable chunk, builder
   implements only that chunk, validator independently verifies with relevant
   tests, and durable state records verified behavior, evidence, risks, and
   remaining gaps.

Use **Codex-backed runners by default** for orchestrator execution. Preferred
runner: `codex_server`. As of 2026-06-15, Claude CLI is also available again
and may be used for implementation slices when it is the pragmatic runner
choice. Avoid `claude_sdk` unless a slice explicitly calls for SDK behavior.

## Definition Of Full Operational Status

The dynamic graph system is operational when all of these are true:

1. A graph-mode run with a planner step dispatches a real planner agent.
2. The planner receives a compact graph packet containing active intent,
   requirement state, accepted evidence, open proposals, graph frontier, patch
   budget, and valid patch examples.
3. The planner submits structured graph patch operations through a fenced
   callback/tool path.
4. The controller validates and accepts/rejects those patches as durable graph
   events.
5. Accepted patches create future worker/verifier/check/gap/invariant regions.
6. Gap planner nodes run after discovery or semantic requirement changes and
   after local verifier success where required.
7. Gap findings can append corrective work or route proposals to human/policy
   authority.
8. Final run completion requires graph-wide invariant success: no open
   proposals, no suspect active regions, no stale support evidence satisfying
   active requirements, no blocked must/expected requirements, and no pending
   planner/gap nodes.
9. `/activity`, graph APIs, and comparison metrics expose patch decisions,
   appended work, gap findings, invariant failures, verifier grades, token usage,
   and final acceptance evidence.
10. A true comparison run can execute Arm E from
    `true-comparison-plan.md` end-to-end without manual graph mutation.

## Operating Rules

- Every slice starts by recording a relevant test baseline.
- Use real SQLite/tmp repos/files; never touch `orchestrator.db` directly.
- Preserve kernel purity: `src/orchestrator/graph/` remains IO/DB/HTTP-free.
- `graph_runtime` remains below API/workflow-service import boundaries.
- Controller remains the single accepted graph mutation path.
- For each slice, use the cheapest Codex model capable of the role. Planner and
  validator may need stronger reasoning than builders.
- Validators must protect already verified behavior, not just the newest chunk.
- Escalate when validation fails repeatedly, requirements conflict, or the next
  step would broaden authority.

## Orchestrator Execution Setup

Use the existing `graph-kernel-slice` routine for narrow implementation slices
unless a slice explicitly needs a new routine.

Create runs with:

```json
{
  "routine_id": "graph-kernel-slice",
  "project_path": "/Users/peter/code/task-world",
  "config": {
    "slice_id": "DG-X.Y",
    "spec_path": "docs/graph-approach/slice-DG-X.Y-spec.md"
  },
  "execution_mode": "graph",
  "agent_runner_type": "codex_server",
  "agent_runner_config": {
    "model": "gpt-5.3-codex-spark"
  }
}
```

If `gpt-5.3-codex-spark` is unavailable, use the best available Codex model from
`GET /api/agent-runners/local-models` / the Codex model list. Keep runner
selection Codex-backed unless a later durable note or user instruction allows
Claude CLI for the slice.

Mind-the-gap is used as the meta-process around these runs:

- Planner/gap-finder: choose the next slice from this plan and write/update the
  slice spec.
- Builder: orchestrator run implements that slice.
- Validator: orchestrator verifier plus local acceptance checks validate it.
- Durable state: update this plan, the slice spec, and evidence notes with what
  is now verified and what remains.

## Current Durable Status

- 2026-06-14: DG-0.1 baseline produced by Codex-backed graph run
  `2acb82b5-b58b-4cdf-afb5-0e1793521e20` and preserved in
  `docs/graph-approach/dynamic-graph-baseline.md`.
- Accepted DG-0.1 output is documentation-only. Later run-worktree source edits
  made by an auto-check node are rejected as out of scope and are not part of
  durable state.
- Current graph-control risk: after builder submission, the run paused as
  `graph_blocked`; after resume, an auto-check node exceeded its check scope and
  edited source files. Treat graph-mode verifier/auto-check routing as suspect
  until a follow-up slice or control-plane fix verifies it.
- 2026-06-14: DG-0.2 dynamic metrics schema implemented through embedded
  Codex-backed graph run `1c7c7fd6-c8c4-48b0-9d4d-6bd6a00218e8`. The standard
  `graph-kernel-slice` attempt `f9fba1df-1249-4117-9d5f-c530e16fa829` was
  cancelled after stale worktree docs caused legacy slice drift and an
  out-of-scope edit.
- Accepted DG-0.2 output is limited to `scripts/compare_carriers.py` and
  `tests/unit/test_compare_carriers.py`. Independent validation in the run
  worktree and main checkout passed:
  `uv run pytest tests/unit/test_compare_carriers.py -q`,
  `uv run ruff check scripts/compare_carriers.py tests/unit/test_compare_carriers.py`,
  and `uv run pyright scripts/compare_carriers.py`.
- New graph-control risk: the DG-0.2 verifier node could not execute under
  `codex_server`/`gpt-5.3-codex-spark` because the Codex server launched the
  model with unsupported tool `image_generation`, causing repeated 400 errors.
  DG-0.2 is accepted by independent validation, not by graph verifier grade.
- 2026-06-14: DG-1.1 planner graph packet implemented through embedded
  Codex-backed graph run `dba654d3-5213-48eb-8af7-6fbec0adf7ad`.
  The first verifier dispatch hit the known Codex server unsupported
  `image_generation` tool error, but the automatic retry ran, graded every
  requirement A, and completed the run.
- Accepted DG-1.1 output is limited to:
  - `src/orchestrator/graph/__init__.py`
  - `src/orchestrator/graph_runtime/dispatch.py`
  - `tests/unit/test_graph_planner_packet.py`
- Independent validation corrected two issues before promotion: `PLANNER_OPS`
  now goes through the `orchestrator.graph` public API, and accepted patches are
  no longer mislabeled as open proposals. The planner packet now carries
  `allowed_patch_operations` and `patch_examples` directly.
- DG-1.1 validation passed in the run worktree and main checkout:
  `uv run pytest tests/unit/test_graph_planner_packet.py tests/unit/test_graph_planner.py tests/unit/test_patch_validator.py tests/integration/test_graph_planner_flow.py tests/integration/test_graph_planner_session_flow.py -q`,
  `uv run ruff check src/orchestrator/graph_runtime src/orchestrator/graph/__init__.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_planner_flow.py tests/integration/test_graph_planner_session_flow.py`,
  `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime`, and a
  no-mocks scan of `tests/unit/test_graph_planner_packet.py`.
- 2026-06-14: DG-1.2 fenced planner patch tool implemented from run worktree
  `/Users/peter/code/task-world/worktrees/r263` for Codex-backed graph run
  `40839c41-316c-4627-a494-1c06ab3c7ded`.
- The DG-1.2 orchestrator worker was manually paused after the Codex builder
  entered a long read-only loop with only partial edits. The stale
  `codex app-server` worker process was stopped after pause; accepted output is
  from manager-completed work in the run worktree plus independent validation,
  not from a completed graph verifier grade.
- Accepted DG-1.2 output is limited to:
  - `src/orchestrator/runners/types.py`
  - `src/orchestrator/runners/agents/codex/common.py`
  - `src/orchestrator/runners/agents/codex/agent.py`
  - `src/orchestrator/graph_runtime/dispatch.py`
  - `src/orchestrator/graph/commands.py`
  - focused unit tests for Codex tool exposure/routing, graph dispatch, command
    rejection evidence, and the planner packet.
- DG-1.2 validation passed in the run worktree and main checkout:
  `uv run pytest tests/unit/test_codex_server_common.py tests/unit/test_codex_server_transport.py -q`,
  `uv run pytest tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py -q`,
  `uv run pytest tests/integration/test_graph_planner_flow.py tests/integration/test_graph_runner_e2e.py -q`,
  `uv run ruff check src/orchestrator/runners src/orchestrator/graph src/orchestrator/graph_runtime tests/unit/test_codex_server_common.py tests/unit/test_codex_server_transport.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_planner_flow.py tests/integration/test_graph_runner_e2e.py`,
  `uv run pyright src/orchestrator/runners src/orchestrator/graph src/orchestrator/graph_runtime`,
  and a targeted no-mocks scan over the touched Codex/graph tests.
- Remaining DG-1.2 risk: the callback and dispatch path are verified with fake
  agents and integration graph flows. A controlled real Codex planner has not
  yet produced a patch through the prompt/tool contract.
- 2026-06-14: DG-1.3 planner prompt contract accepted from run worktree
  `/Users/peter/code/task-world/worktrees/r264` for Codex-backed graph run
  `277ab91b-2569-4f6b-a3d3-3e0766b30a55`.
- The DG-1.3 orchestrator builder was paused after repeated read-only
  inspection. It left partial prompt/example edits, which were corrected by the
  manager before independent validation.
- Accepted DG-1.3 output is limited to:
  - `src/orchestrator/graph_runtime/dispatch.py`
  - `src/orchestrator/runners/agents/codex/common.py`
  - `src/orchestrator/runners/agents/codex/agent.py`
  - `tests/unit/test_graph_planner_packet.py`
  - `tests/unit/test_codex_server_common.py`
  - `tests/unit/test_codex_server_transport.py`
  - `tests/unit/test_codex_server_tool_filtering.py`
  - `docs/graph-approach/slice-DG-1.3-spec.md`
- DG-1.3 verified that generic planner prompts now require graph mutation
  through `submit_graph_patch`, disallow planner source edits, name
  `current_graph_position` as `base_graph_position`, restrict operations to
  `allowed_patch_operations`, and tell planners to repair rejected/stale
  patches before plain `submit`.
- A controlled live Codex planner session using `gpt-5.3-codex-spark` delivered
  a `submit_graph_patch` callback payload with no changed files via
  `uv run python /private/tmp/run_live_codex_planner.py`.
- DG-1.3 validation passed:
  `uv run pytest tests/unit/test_graph_planner_packet.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_transport.py tests/unit/test_codex_server_tool_filtering.py -q`,
  `uv run pytest tests/integration/test_graph_planner_flow.py tests/integration/test_graph_runner_e2e.py -q`,
  focused `ruff check`, `uv run pyright src/orchestrator/graph_runtime src/orchestrator/runners`,
  and a targeted no-mocks scan.
- Remaining DG-1.3 risk: the live Codex evidence used a direct
  `CodexServerAgent` harness rather than a full graph-dispatched planner node
  in a dynamic feature routine.
- 2026-06-15: DG-2.1 dynamic feature routine skeleton accepted from run
  worktree `/Users/peter/code/task-world/worktrees/r265` for Codex-backed graph
  run `4944cd08-bf5d-403b-bcbc-ce18fd895edf`.
- Accepted DG-2.1 output is limited to:
  - `routines/dynamic-graph-feature/routine.yaml`
  - `tests/integration/test_graph_routine_compile.py`
  - `docs/graph-approach/slice-DG-2.1-spec.md`
- DG-2.1 verified that `dynamic-graph-feature` loads through the normal routine
  loader, declares graph execution and required dynamic feature inputs, and
  compiles to `root`, `routine-snapshot`, and one generic planner head with
  graph-write authority rather than pre-seeded feature worker/verifier nodes.
- DG-2.1 validation passed in the run worktree and main checkout:
  `uv run pytest tests/integration/test_graph_routine_compile.py -q`,
  `uv run ruff check routines/dynamic-graph-feature tests/integration/test_graph_routine_compile.py`,
  `uv run pyright src/orchestrator/config src/orchestrator/graph`, and a
  targeted no-mocks scan.
- Remaining DG-2.1 risk: the Codex-backed graph run was manually paused after
  an auto-verify `no_mocks` check node entered a read-heavy loop. The slice is
  accepted by independent validation, not by a completed graph verifier grade.
- 2026-06-15: DG-2.2 horizon region templates accepted from run worktree
  `/Users/peter/code/task-world/worktrees/r266` for Codex-backed graph run
  `e3e47df2-a803-45fb-8f66-51132e997c18`.
- Accepted DG-2.2 output is limited to:
  - `src/orchestrator/graph_runtime/horizon_templates.py`
  - `src/orchestrator/graph_runtime/__init__.py`
  - `src/orchestrator/graph_runtime/dispatch.py`
  - `routines/dynamic-graph-feature/routine.yaml`
  - `tests/unit/test_graph_horizon_templates.py`
  - `tests/unit/test_graph_planner_packet.py`
  - `tests/integration/test_graph_routine_compile.py`
  - `docs/graph-approach/slice-DG-2.2-spec.md`
- DG-2.2 verified six compact standard horizon templates:
  `discovery_region`, `implementation_region`, `validation_region`,
  `gap_analysis_region`, `corrective_work_region`, and
  `final_invariant_region`. Planner packets now expose
  `horizon_region_templates`; planner prompts name the catalog; worker and
  verifier prompts remain free of graph patch and horizon-template instructions.
- DG-2.2 validation passed in the run worktree and main checkout:
  `uv run pytest tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner_packet.py -q`,
  `uv run pytest tests/integration/test_graph_routine_compile.py -q`,
  `uv run ruff check src/orchestrator/graph_runtime tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_routine_compile.py routines/dynamic-graph-feature`,
  `uv run pyright src/orchestrator/graph_runtime src/orchestrator/graph`, and a
  targeted no-mocks scan over the modified tests.
- Remaining DG-2.2 risk: the Codex-backed graph run repeatedly leased and
  dispatched the ready worker, then revoked each lease after the Codex server
  reported `gpt-5.3-codex-spark` usage-limit failures. The slice is accepted by
  independent validation, not by a completed graph verifier grade. Subsequent
  orchestrator runs should use `codex_server` with an available Codex model such
  as `gpt-5.5` while Spark is quota-limited.
- 2026-06-15: DG-3.1 gap planner node semantics accepted from Codex-backed
  graph run `0bcc76f8-545b-41e5-baaf-bc5e27263637` plus manager-completed
  main-compatible fixes after independent validation found the run worktree had
  implemented gap planner patch routing against a stale dispatch snapshot.
- Accepted DG-3.1 output is limited to:
  - `src/orchestrator/graph/patch_validator.py`
  - `src/orchestrator/graph_runtime/dispatch.py`
  - `tests/unit/test_graph_planner_packet.py`
  - `tests/unit/test_patch_validator.py`
  - `tests/unit/test_graph_dispatch_on_output.py`
  - `tests/unit/test_graph_commands.py`
  - `docs/graph-approach/slice-DG-3.1-spec.md`
- DG-3.1 verified that `gap_planner` uses the existing planner
  `submit_graph_patch` callback path, cannot plain-submit before an accepted or
  rejected patch attempt, can submit accepted no-op and corrective
  worker/verifier patches, cannot create planner successor nodes, and receives a
  compact `gap_analysis_contract` pointing at `corrective_work_region`.
- DG-3.1 validation passed in the run worktree after correction and in the main
  checkout:
  `uv run pytest tests/unit/test_graph_planner_packet.py tests/unit/test_patch_validator.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_commands.py -q`,
  `uv run pytest tests/integration/test_graph_planner_flow.py -q`,
  focused `ruff check`, `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime`,
  and a targeted no-mocks scan over the touched graph tests.
- Remaining DG-3.1 risk: the orchestrator run completed, but independent review
  found and corrected a spec gap before promotion. The accepted implementation
  is the main-compatible callback-path version, not the stale-output-parser
  version from the run worktree.
- 2026-06-15: DG-3.2 requirement/evidence revision policy accepted from
  Codex-backed graph run `69a2a41c-55bd-478d-87c4-51930fd057ff` plus
  main-compatible adaptation after independent validation.
- Accepted DG-3.2 output is limited to:
  - `src/orchestrator/graph/projections.py`
  - `src/orchestrator/graph/commands.py`
  - `src/orchestrator/graph/__init__.py`
  - `src/orchestrator/graph_runtime/dispatch.py`
  - `tests/unit/test_graph_projections.py`
  - `tests/unit/test_graph_commands.py`
  - `tests/unit/test_graph_planner_packet.py`
  - `docs/graph-approach/slice-DG-3.2-spec.md`
- DG-3.2 verified replayable requirement revision state, fresh/stale support
  evidence projection, validation-strengthening invalidation of older support,
  semantic/new-behavior authority flags, and compact planner packet freshness
  facts. The planner packet change was adapted onto the existing DG-3.1
  `submit_graph_patch` contract rather than copying the stale run-worktree
  dispatch snapshot.
- DG-3.2 validation passed in the run worktree and main checkout:
  `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_patch_validator.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py -q`,
  `uv run pytest tests/integration/test_graph_planner_flow.py -q`,
  focused `ruff check`, `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime`,
  and a targeted no-mocks scan over the touched graph tests.
- Remaining DG-3.2 risk: the Codex verifier submitted all six grades as `A`,
  but the run API still projected the run as `active` with the task `pending`.
  Treat this as a graph-run state projection/completion bookkeeping risk for
  later operational slices; the DG-3.2 code is accepted by independent evidence.
- 2026-06-15: DG-3.3 final invariant gate accepted from Codex-backed graph run
  `2e9da7e4-6beb-4c0c-90ac-aa04202c4bd5` plus manager-completed
  main-compatible correction after the verifier found a requirement freshness
  compatibility bug.
- Accepted DG-3.3 output is limited to:
  - `src/orchestrator/graph/projections.py`
  - `src/orchestrator/graph/commands.py`
  - `src/orchestrator/graph/__init__.py`
  - `tests/unit/test_graph_projections.py`
  - `tests/unit/test_graph_commands.py`
  - `docs/graph-approach/slice-DG-3.3-spec.md`
- DG-3.3 verified pure final invariant blockers for pending planner/gap nodes,
  unresolved planner proposals, suspect active nodes, blocked must/expected
  requirements, stale or unsupported active requirement evidence, unresolved
  authority-required revisions, and non-accepted task regions. `project_run_state`
  remains active while blockers exist, and graph lifecycle `complete` rejects
  with blocker evidence.
- Independent validation fixed the run verifier's R-05 finding: later fresh
  support for the active requirement version now clears stale/unsupported
  requirement blockers through the DG-3.2 freshness projection.
- DG-3.3 validation passed in main:
  `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner.py tests/unit/test_graph_planner_packet.py -q`,
  `uv run pytest tests/integration/test_graph_planner_flow.py -q`,
  focused `ruff check`, `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime`,
  and a targeted no-mocks scan over the touched graph tests.
- Remaining DG-3.3 risk: the Codex-backed graph run paused as `graph_blocked`
  with `last_error="graph quiescent without completion"` after verifier
  submission, and its stale worktree did not contain
  `tests/unit/test_graph_planner_packet.py`. The accepted result is the
  main-compatible implementation validated independently, not the raw r269
  output.
- 2026-06-15: DG-4.1 activity events for graph grades and patches accepted from
  Codex-backed graph run `f53c77ee-3619-426b-955a-3f8a6fa84e5e` plus
  main-compatible adaptation and independent validation.
- Accepted DG-4.1 output is limited to:
  - `src/orchestrator/db/access/activity_summaries.py`
  - `src/orchestrator/db/access/event_store_v2.py`
  - `tests/integration/test_api_activity.py`
  - `docs/graph-approach/slice-DG-4.1-spec.md`
- DG-4.1 verified that existing `/api/runs/{run_id}/activity` reads compact
  graph activity rows from the `graph:<run_id>` event stream for accepted and
  rejected graph patches, rejected graph commands, verifier pass/fail grades,
  deferred nodes, and filtered review-node final invariant blockers. Ordinary
  graph `node_created` payloads are not exposed, preserving compact
  no-transcript activity output.
- DG-4.1 validation passed in main:
  `uv run pytest tests/integration/test_graph_activity_stream.py tests/integration/test_api_activity.py -q`,
  `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py -q`,
  `uv run ruff check src/orchestrator/api src/orchestrator/db/access src/orchestrator/graph tests/integration/test_graph_activity_stream.py tests/integration/test_api_activity.py tests/unit/test_graph_projections.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner_packet.py`,
  `uv run pyright src/orchestrator/api src/orchestrator/db/access src/orchestrator/graph`,
  and the required no-mocks scan. The scan only matched existing
  `client.patch(...)` HTTP calls in `tests/integration/test_api_activity.py`.
- Remaining DG-4.1 risk: the run worktree is based on a stale committed branch,
  so it lacked DG-3.3 specs and `tests/unit/test_graph_planner_packet.py`.
  Orchestrator API polling for the run was stopped after the approval reviewer
  rejected further escalated local API calls due a usage-limit gate. The
  accepted result is the independently validated main-compatible implementation.
- 2026-06-15: DG-4.2 dynamic graph UI panels accepted from advisory Claude CLI
  graph run `b5974f52-7f4e-4bce-83ca-bd8baf2b0c6d` plus manager-completed
  main-compatible implementation and independent validation.
- Accepted DG-4.2 output is limited to:
  - `ui/src/components/GraphPanel.tsx`
  - `ui/src/components/__tests__/GraphPanel.activity.test.tsx`
  - `docs/graph-approach/slice-DG-4.2-spec.md`
- DG-4.2 verified that the existing GraphPanel now shows a compact operator
  summary with graph state, scheduler buckets, lease counts, decision counts,
  DG-4.1 patch counts, verifier pass/fail counts, and activity blocker counts.
  It also renders compact patch decision, verifier result, command rejection,
  and review-blocker rows from DG-4.1 activity events while ignoring ordinary
  raw `node_created` payloads and avoiding prompt/evidence transcript dumps.
- DG-4.2 validation passed in main:
  `npm --prefix ui test -- src/components/__tests__/GraphPanel.activity.test.tsx src/components/__tests__/SchedulerView.test.tsx`,
  `npm --prefix ui run lint -- --max-warnings=0`,
  `npm --prefix ui run typecheck`, and the required no-mocks scan over the
  modified UI tests.
- Remaining DG-4.2 risk: the Claude CLI graph run spent the attempt in
  read-heavy analysis against a stale worktree, initially missing the injected
  `slice-DG-4.2-spec.md`, and made no implementation edits. It was manually
  paused with `pause_reason="manual_pause"` after the main-compatible
  implementation passed independent validation.
- 2026-06-15: DG-4.3 comparison metric export accepted from Codex-backed graph
  run `4729ba3d-bf1b-4011-a10d-595c6d9b9094` plus manager-completed
  main-compatible implementation and independent validation.
- Accepted DG-4.3 output is limited to:
  - `scripts/compare_carriers.py`
  - `tests/unit/test_compare_carriers.py`
  - `docs/graph-approach/slice-DG-4.3-spec.md`
- DG-4.3 verified that the carrier comparison exporter now optionally reads
  `/api/runs/{run_id}/graph/events` and extracts exact dynamic graph event
  metrics for accepted/rejected graph patches, rejection reasons, proposal
  decisions, appended/suspect/superseded regions, final invariant blockers,
  verifier requirement grades, and explicit token totals by node kind. Missing
  or malformed graph event endpoints conservatively produce zero/default
  dynamic metrics for legacy runs.
- DG-4.3 validation passed in main:
  `uv run pytest tests/unit/test_compare_carriers.py -q`,
  `uv run ruff check scripts/compare_carriers.py tests/unit/test_compare_carriers.py`,
  `uv run pyright scripts/compare_carriers.py`, and
  `rg -n "monkeypatch|MagicMock|patch\\(|vi\\.mock|jest\\.mock" tests/unit/test_compare_carriers.py scripts/compare_carriers.py`.
  The no-mocks scan returned no matches.
- Remaining DG-4.3 risk: the graph run worktree was based on stale commit
  `4c8f6695935fe9174a25e8fda41a878f2ba2a5dc`; before the injected
  `slice-DG-4.3-spec.md` was observed, the builder followed older
  `docs/graph-approach/slice-4.3-spec.md` context and began out-of-scope
  wall-clock/ADR work. The run was manually paused with
  `pause_reason="manual_pause"` and its raw worktree output was not accepted.
- 2026-06-15: DG-5.1 dynamic smoke run attempted with Codex-backed graph run
  `07b6b694-ed44-488c-899a-541e108e57c6`.
- DG-5.1 partial evidence:
  - `dynamic-graph-feature` launched as `execution_mode="graph"` and became
    graph-backed in worktree `worktrees/r273`.
  - The planner node `planner-s-01` called `submit_graph_patch`; activity
    recorded `tool: submit_graph_patch (completed)`.
  - The graph event stream recorded one accepted planner patch:
    `planner-s-01-discovery-missing-evidence`.
  - The patch appended a discovery worker node
    `worker-discovery-dynamic-feature-execution-graph`.
  - DG-4.3 compact metrics for the run: `status=paused`,
    `planner_patches=1`, `accepted_patches=1`, `proposal_decisions=1`,
    `appended_regions=2`, `rejected_patches=0`,
    `invariant_gate_failures=0`, and no verifier grades.
- DG-5.1 was not accepted. The routine snapshot for `dynamic-graph-feature`
  has a planner step with zero tasks and does not put `feature_spec_path`,
  `acceptance_command`, or `hidden_oracle_command` into actionable worker
  context. The first appended discovery worker reported that its requirements
  section was empty, inferred an unrelated graph-kernel enhancement, and edited
  `src/orchestrator/config/models.py` in the run worktree. The run was manually
  paused with `pause_reason="manual_pause"`; no r273 worktree source edits are
  accepted.
- DG-5.1a was accepted for context wiring, then retry run
  `f26fb0f9-2c04-424a-9798-6aeccad90044` proved a stronger smoke path:
  the planner emitted an accepted graph patch; the appended dynamic worker
  created `docs/graph-approach/dynamic-smoke-output.txt`; and the local verifier
  passed all weak-validation rubric items. That run then paused with
  `pause_reason="graph_blocked"` because a planner-created verifier-to-gap edge
  used `from_port="verification_result"` while the runtime publishes verifier
  output records on `verification_report`, leaving the gap planner blocked on
  `missing_required_input:verification_evidence`.
- DG-5.1b canonicalized the verifier edge port, and retry run
  `83dafb47-c3aa-4e29-9b79-3b1f9753f5db` confirmed the planner-created edge
  used `from_port="verification_report"`. That run still paused as
  `graph_blocked` because accepted verification records were not routed through
  `_input_bound_events_for_record`, so no `input_bound` event was emitted for
  `planner-dynamic-smoke-gap.verification_evidence` after
  `verifier-dynamic-smoke-local` passed.
- DG-5.1c routed accepted verification records through downstream input
  binding. Retry run `9c7569af-5f55-4dc5-b1b1-016a24e8a652` proved both
  corrective and weak-local verifier records now bind downstream inputs:
  final invariant evidence at graph position 96 and gap-planner
  `verification_evidence` at position 119. The gap planner then became ready
  and running, but the run paused as `graph_blocked` with no gap-planner
  callback or `agent_died` event. This exposed a dispatch lease-recovery gap:
  a runner can exit without calling `submit`, leaving a lease active and the
  driver to classify the run as quiescent.
- The same retry also exposed a final-check precondition blocker:
  `check-dynamic-smoke-final-invariant` had `hidden_oracle_command` but no
  `command_definition`, so it remained deferred on
  `precondition_failed:has_command_definition`.
- DG-5.1d and DG-5.1e were then exercised together in retry run
  `80d31f6a-942b-427a-a06b-19ce5d9d50c9`: the final invariant check moved past
  the prior `has_command_definition` precondition and completed, and the gap
  planner no-submit case now emitted `agent_died` with reason
  `agent exited without submit` followed by retry scheduling.
- That retry still paused as `graph_blocked` after the gap planner repeatedly
  exited without a callback. The next selected slice is DG-5.1f — Gap Planner
  Mandatory Patch Discipline.
- DG-5.1f tightened the gap-planner prompt and packet contract, then retry run
  `fafa1c28-f745-4a22-bad8-8e4f675e1125` showed two useful facts before the
  development server reload paused it with `agent_not_running_on_startup`: the
  initial planner now defers corrective work on `missing_required_input:
  classified_gap`, but the gap planner still exited without submit at graph
  positions 90 and 102.
- The same retry exposed a packet hygiene blocker: planner evidence included a
  full file-state payload with large ignored `.venv` and `ui/node_modules`
  trees. The next selected slice is DG-5.1g — Planner Evidence Packet
  Compaction.
- DG-5.1g compacted planner file-state evidence, but retry run
  `64ef3aac-3d8c-4e45-b8b9-f3fba99b9b6c` still paused as `graph_blocked`
  after the gap planner exited without submit at positions 82 and 94. That run
  exposed the runner-side cause: Codex Server only exposed `submit_graph_patch`
  to `node_role="planner"`, while gap planners have `node_role="gap_planner"`.
  Its tool schema and payload normalizer also rejected `ops: []`, contradicting
  the no-op patch contract. The next selected slice is DG-5.1h — Gap Planner
  Codex Tool Exposure.
- DG-5.1h was live-proven by retry run
  `fd2728e8-a2dc-4b17-8c55-c0c031a33471`: the gap planner submitted
  `planner-dynamic-smoke-gap-no-op-1`, and the graph recorded
  `graph_patch_accepted` at position 56. That run still paused as
  `graph_blocked` because the root planner patch created the gap planner,
  corrective worker, and final invariant check without required evidence edges,
  making them ready/running before local verification and gap classification.
  The next selected slice is DG-5.1i — Dynamic Region Dependency Validation.
- DG-5.1i was live-proven by retry run
  `28d62e16-eff5-496a-aa9b-f360c77af779`: the root planner patch was accepted
  with required edges, and positions 40, 41, and 43 showed the gap planner,
  corrective worker, and invariant check correctly deferred until verification
  and classified-gap evidence existed. The run still paused as `graph_blocked`
  because the gap planner submitted a no-op patch while a required
  `classified_gap` successor edge existed, and gap planners emitted no
  `gap_classification` output record on submit. The next selected slice is
  DG-5.1j — Gap Classification Output Binding.

## Phase DG-0 — Baseline And Instrumentation

Goal: establish reliable measurement before changing behavior.

### Slice DG-0.1 — Baseline Matrix

Deliverables:

- A baseline doc recording current results for:
  - graph kernel unit tests;
  - graph runtime integration tests;
  - graph API/UI tests;
  - codex token capture tests;
  - true-comparison script metrics currently available.
- Known failures or gaps explicitly listed.

Done when:

- Baseline commands and outputs are recorded.
- Any failing checks are classified as pre-existing blockers or fixed before
  dynamic work starts.

### Slice DG-0.2 — Dynamic Metrics Schema

Deliverables:

- Extend comparison metric extraction to count:
  planner patches, patch ops, patch rejection reasons, appended regions,
  suspect/superseded regions, gap findings, proposal decisions, invariant-gate
  failures, graph verifier grades, and token usage by node kind.

Done when:

- A seeded/fake graph event stream produces expected metric totals.
- Existing carrier comparison metrics still pass.

## Phase DG-1 — Planner Patch Submission

Goal: make planner nodes operational with real agents, not only command-driven
tests.

### Slice DG-1.1 — Planner Graph Packet

Deliverables:

- A compact planner packet builder above the pure kernel boundary.
- Packet includes:
  active intent, requirement versions, accepted evidence, open proposals,
  current frontier, ready/blocked nodes, planner budget, allowed patch ops, and
  examples of valid patch JSON.

Mind-the-gap validation:

- Validator checks packet completeness against dynamic dry-run scenarios and
  ensures no unrelated full transcripts or noisy logs are included.

Done when:

- Unit tests cover packet shaping.
- Integration test dispatches a planner node and records the prompt/packet.

### Slice DG-1.2 — Fenced Planner Patch Tool

Deliverables:

- A graph planner submission tool/callback that accepts structured patch JSON.
- Planner `submit` without patch is rejected for generic planner roles unless
  the role is one of the existing special cases.
- Callback includes lease/execution/snapshot identity and idempotency key.

Mind-the-gap validation:

- Validator tries malformed, stale, unauthorized, and valid patch submissions.

Done when:

- Real Codex planner agent can submit a patch that the controller accepts.
- Stale or unauthorized patch submissions emit durable rejection events.

### Slice DG-1.3 — Planner Prompt Contract

Deliverables:

- Planner-specific prompt template.
- Explicit instruction to output only valid patch tool calls for graph mutation.
- Examples for create region, successor planner, gap planner, invariant gate,
  and final no-successor termination.

Done when:

- A controlled Codex planner run creates a minimal worker/verifier region through
  tool submission without manual event injection.

## Phase DG-2 — Dynamic Feature Routine

Goal: provide a production routine that exercises dynamic graph behavior.

### Slice DG-2.1 — Dynamic Feature Routine Skeleton

Deliverables:

- New routine, for example `dynamic-graph-feature`, with planner head and
  graph-mode execution.
- Inputs: feature spec path, acceptance command, hidden-oracle command optional,
  patch budget, gap-policy profile.
- Planner, worker, verifier, gap planner, and invariant gate roles are explicit.

Done when:

- Creating a run from the routine seeds a planner chain, not a static
  worker/verifier-only graph.

### Slice DG-2.2 — Horizon Region Templates

Deliverables:

- Standard patch templates for:
  - discovery region;
  - implementation region;
  - validation/check region;
  - gap-analysis region;
  - corrective-work region;
  - final invariant gate.

Done when:

- Planner can instantiate these templates through accepted patches.
- Successor readiness depends on accepted region records, not implicit sequence.

Status:

- Accepted 2026-06-15. The runtime catalog and planner packet/prompt exposure
  are verified. Template readiness is explicit through candidate/check records
  and documented expected readiness; no planner patch permissions were broadened.

## Phase DG-3 — Gap Planner And Invariant Gate

Goal: make "Mind the Gap" behavior native to dynamic graph runs.

### Slice DG-3.1 — Gap Planner Node Semantics

Deliverables:

- Gap planner role/kind policy or role specialization.
- Gap planner consumes verified work, active requirements, evidence freshness,
  and original intent.
- Output: no-gap evidence, gap finding, validation-strengthening proposal, or
  corrective-work patch.

Done when:

- A graph run where local verifier passes but validation is weak routes to a gap
  planner before final acceptance.

Accepted 2026-06-15. Gap planner nodes are now graph-patch-capable through the
same callback discipline as generic planners, with stricter validation for
corrective work and no planner successor creation. The stronger routing rule
after weak validation remains part of DG-3.2/DG-3.3 policy and invariant work.

### Slice DG-3.2 — Requirement/Evidence Revision Policy

Deliverables:

- First-class records/policies for requirement versions, validation
  strengthening, support-edge freshness, suspect regions, and superseded
  evidence.
- Authority distinction:
  - validation strengthening for an active must requirement can be accepted by
    policy;
  - new behavior requirements require explicit authority.

Done when:

- Tests cover definitional vs semantic changes and stale evidence cannot satisfy
  active requirements.

Accepted 2026-06-15. Requirement revisions and support evidence are replayable
graph facts; validation-strengthening revisions make older support stale; and
semantic/new-behavior revisions project explicit-authority requirements. Planner
packets now include compact freshness facts for gap planners. This slice did
not change final completion behavior, API, UI, metrics, scheduler completion
blocking, or true-comparison behavior.

### Slice DG-3.3 — Final Invariant Gate

Deliverables:

- Pre-completion invariant evaluator.
- Blocks on open proposals, suspect active nodes, stale support evidence,
  blocked must/expected requirements, pending planner/gap nodes, and unresolved
  validation-strengthening decisions.

Done when:

- A run with all local verifiers passing still refuses completion when the graph
  has stale evidence or open proposals.

Accepted 2026-06-15. Final completion is now blocked by pure graph invariant
facts, and lifecycle `complete` returns compact blocker evidence. The blocker
projection uses DG-3.2 freshness facts so later fresh support for an active
requirement clears stale/unsupported blockers. This slice did not add API, UI,
metrics export, scheduler expansion, or true-comparison behavior.

## Phase DG-4 — Operational Observability

Goal: make dynamic graph runs inspectable enough for operators and comparison.

### Slice DG-4.1 — Activity Events For Graph Grades And Patches

Deliverables:

- `/activity` emits graph verifier grade summaries.
- `/activity` emits planner patch accepted/rejected summaries and gap findings.

Done when:

- Graph runs can be scored for all-A / pass/fail without reading raw graph
  events manually.

Accepted 2026-06-15. `/activity` now includes compact graph patch decision,
command rejection, verifier grade, node-deferred, and review-blocker summaries
from durable graph events while preserving the existing route shape, event-type
filter, and global activity cursor semantics. Ordinary graph node payloads are
not surfaced.

### Slice DG-4.2 — Dynamic Graph UI Panels

Deliverables:

- Graph panel shows:
  - planner chain/horizons;
  - accepted/rejected patches;
  - appended/superseded/suspect regions;
  - gap findings;
  - invariant-gate blockers;
  - requirement/evidence revision state.

Done when:

- Operator can answer "why is this run not complete?" from the UI.

Accepted 2026-06-15. The existing graph panel now surfaces operator summary
counts and compact DG-4.1 activity rows for patch decisions, verifier results,
command rejections, and invariant/blocker facts while preserving scheduler,
decisions, file-state, node-state, node-detail, close, and initial-node
selection behavior.

### Slice DG-4.3 — Comparison Metric Export

Deliverables:

- `scripts/compare_carriers.py` or a companion script reads graph dynamic facts.
- Metrics align with `true-comparison-plan.md`.

Done when:

- A synthetic dynamic event stream and one real graph run both export complete
  metric rows.

Accepted 2026-06-15. `scripts/compare_carriers.py` now reads graph event
payloads through an optional fetcher, keeps legacy runs tolerant of missing graph
event endpoints, and aggregates exact dynamic graph metrics from accepted event
types instead of fuzzy event-name matching. Unit coverage uses literal graph
event fixtures and no mocks/monkeypatching. Remaining gap: the exporter is
ready for DG-5.1/DG-5.2 comparison runs, but no new full comparison campaign has
been executed yet.

## Phase DG-5 — True Comparison Gate

Goal: prove operational status with a real dynamic feature run.

### Slice DG-5.1 — Dynamic Smoke Run

Deliverables:

- Tiny repo fixture with intentionally weak validation and one required
  corrective append.
- Run through `dynamic-graph-feature` using `codex_server`.

Done when:

- Planner emits at least one patch.
- Gap planner appends at least one corrective region.
- Final invariant gate blocks before correction and passes after correction.

Attempted 2026-06-15 and blocked. The run proved the planner tool path can emit
a real accepted graph patch, but the dynamic feature routine does not yet pass
the smoke feature spec and acceptance/oracle commands into the graph planner and
generated worker contexts. Repair this before re-running DG-5.1.

### Slice DG-5.1a — Dynamic Feature Context Wiring

Deliverables:

- `dynamic-graph-feature` planner packets include the feature spec path, feature
  spec content or compact summary, weak acceptance command, hidden oracle
  command, patch budget, and gap policy profile.
- Planner-created worker/verifier/gap/corrective regions receive non-empty task
  context grounded in the feature spec instead of generic repo-discovery text.
- The dynamic smoke run can be launched without manual spec injection into the
  worktree.

Done when:

- A unit or integration test proves the planner packet for
  `dynamic-graph-feature` contains the smoke feature inputs.
- A dynamic smoke run reaches an appended worker whose prompt/context names the
  target artifact and acceptance/oracle commands, with no unrelated source-file
  edits before the run is paused or completes.

Accepted 2026-06-15 for context wiring. The graph compiler remains pure and now
accepts explicit run inputs; `GraphRunDriver` enriches graph seed config with
repo-relative feature spec content from the run worktree, falling back to a
read-only main-worktree copy when the run worktree lacks a newly-authored spec.
The routine snapshot and initial planner node carry `dynamic_feature` fields,
and the planner packet/prompt contract exposes those inputs for worker,
verifier, gap-analysis, corrective-work, and final invariant regions. Validation:
`uv run pytest tests/unit/test_graph_compiler.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_driver_logic.py tests/integration/test_graph_routine_compile.py -q`
passed with 68 tests; ruff and pyright passed on changed Python files; no
mock/monkeypatch usage was introduced. Next action: retry DG-5.1 with the
repaired seed/packet path.

### Slice DG-5.1b — Verifier Evidence Binding Canonicalization

Deliverables:

- Planner-created edges that use the common verifier alias
  `from_port="verification_result"` are canonicalized to the runtime verifier
  output port `verification_report`.
- Gap-analysis horizon guidance names the canonical verifier evidence input.
- Planner-created corrective workers receive expected artifact and corrective
  evidence fields in their prompts.

Done when:

- Focused unit tests prove alias canonicalization, gap template guidance, and
  dynamic worker prompt fields.
- A fresh DG-5.1 run can move past weak local verifier success into gap planning
  without blocking on `missing_required_input:verification_evidence`.

Accepted 2026-06-15 for the code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_planner.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_horizon_templates.py -q`;
`uv run ruff check src/orchestrator/graph/commands.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/horizon_templates.py tests/unit/test_graph_planner.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_horizon_templates.py`;
and `uv run pyright src/orchestrator/graph/commands.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/horizon_templates.py tests/unit/test_graph_planner.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_horizon_templates.py`.
Next action: retry DG-5.1 from a fresh run, because existing retry
`f26fb0f9-2c04-424a-9798-6aeccad90044` already contains the bad edge.

### Slice DG-5.1c — Verification Record Input Binding

Deliverables:

- Accepted verifier records call the same downstream input binding helper as
  ordinary output records and file-state records.
- The verifier-to-gap planner edge in the dynamic smoke run can bind
  `verification_evidence` after weak local verification passes.

Done when:

- A focused command-applier test proves a verifier callback with a matching
  `verification_report` edge emits `input_bound` and makes the gap planner
  schedulable.
- A fresh DG-5.1 run moves past local verifier success into gap planner leasing.

Accepted 2026-06-15 for the code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_commands.py tests/unit/test_graph_planner.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_horizon_templates.py -q`;
`uv run ruff check src/orchestrator/graph/commands.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/horizon_templates.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_horizon_templates.py`;
and `uv run pyright src/orchestrator/graph/commands.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/horizon_templates.py tests/unit/test_graph_commands.py tests/unit/test_graph_planner.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_horizon_templates.py`.
Next action: retry DG-5.1 from a fresh run, because retry
`83dafb47-c3aa-4e29-9b79-3b1f9753f5db` already contains the unbound verifier
record.

### Slice DG-5.1d — No-Submit Graph Agent Lease Recovery

Deliverables:

- If a graph runner exits without invoking the submit callback, dispatch records
  `agent_died` instead of leaving the lease active.
- The graph driver can recover/retry the node rather than pausing as generic
  quiescence with an active lease.

Done when:

- A focused dispatch test proves a runner returning successfully without
  `on_submit` calls `_agent_died("agent exited without submit")`.
- A fresh DG-5.1 run no longer leaves a running gap planner lease without an
  `agent_died`, callback, or retryable state.

Accepted 2026-06-15 for the code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_driver_logic.py tests/unit/test_graph_commands.py -q`;
`uv run ruff check src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph/commands.py src/orchestrator/workflow/graph_driver.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_driver_logic.py tests/unit/test_graph_commands.py`;
and `uv run pyright src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph/commands.py src/orchestrator/workflow/graph_driver.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_driver_logic.py tests/unit/test_graph_commands.py`.
Retry `80d31f6a-942b-427a-a06b-19ce5d9d50c9` verified the live behavior: the
gap planner emitted `agent_died` with reason `agent exited without submit`, then
the runtime scheduled retries instead of leaving a silent running lease.

### Slice DG-5.1e — Hidden Oracle Check Command Canonicalization

Deliverables:

- Planner-created check nodes with `hidden_oracle_command` receive a
  `command_definition` compatible with the existing check-node precondition.
- The final invariant check in DG-5.1 can become schedulable after required
  verification evidence binds.

Done when:

- A focused planner patch test proves a check node carrying
  `hidden_oracle_command` is accepted with a generated `command_definition`.
- The previous `precondition_failed:has_command_definition` blocker is absent in
  the next DG-5.1 retry when the planner emits the same check shape.

Accepted 2026-06-15 for the code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_planner.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_commands.py tests/unit/test_graph_horizon_templates.py -q`;
`uv run ruff check src/orchestrator/graph/commands.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/horizon_templates.py tests/unit/test_graph_planner.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_commands.py tests/unit/test_graph_horizon_templates.py`;
and `uv run pyright src/orchestrator/graph/commands.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/horizon_templates.py tests/unit/test_graph_planner.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_commands.py tests/unit/test_graph_horizon_templates.py`.
Retry `80d31f6a-942b-427a-a06b-19ce5d9d50c9` verified the prior
`precondition_failed:has_command_definition` blocker was absent: the final
invariant check became ready, ran, and completed.

### Slice DG-5.1f — Gap Planner Mandatory Patch Discipline

Deliverables:

- Gap-planner prompts explicitly require `submit_graph_patch` for every
  outcome.
- Gap-planner packets encode the same rule structurally: a corrective patch when
  a gap is found, or a no-op patch with `ops: []` when no safe graph mutation is
  available.
- Plain `submit` remains forbidden until at least one accepted or rejected patch
  attempt exists.

Done when:

- A focused packet/prompt test proves gap planners receive the mandatory no-op
  patch instruction and `gap_analysis_contract` fields.
- A fresh DG-5.1 run reaches the gap planner and records an accepted or rejected
  `submit_graph_patch` attempt instead of repeated no-submit exits.

Accepted 2026-06-15 for the code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_planner_packet.py -q`;
`uv run ruff check src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_planner_packet.py`;
and `uv run pyright src/orchestrator/graph_runtime/dispatch.py`.
Retry `fafa1c28-f745-4a22-bad8-8e4f675e1125` verified the contract is present
but not sufficient: the gap planner still exited without submit twice. That run
also verified the initial planner now gates corrective work on `classified_gap`.

### Slice DG-5.1g — Planner Evidence Packet Compaction

Deliverables:

- Planner evidence uses compact file-state records instead of serializing full
  raw boundary payloads.
- Compact file-state evidence preserves snapshot IDs, producer identity,
  changed-path samples, rejected-path samples, and counts for tracked,
  untracked, ignored, and rejected paths.
- Ignored dependency/cache trees are represented by counts only.

Done when:

- A focused planner-packet test proves ignored paths are summarized by count and
  not copied into `record_payload`, while tracked/untracked changed-path samples
  remain visible.
- A fresh DG-5.1 run reaches the gap planner with a compact packet and records
  a `submit_graph_patch` decision or a smaller, more diagnosable blocker.

Accepted 2026-06-15 for the code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_planner_packet.py -q`;
`uv run ruff check src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_planner_packet.py`;
and `uv run pyright src/orchestrator/graph_runtime/dispatch.py`.
Retry `64ef3aac-3d8c-4e45-b8b9-f3fba99b9b6c` verified compact evidence is not
sufficient by itself: the gap planner still exited without submit twice and the
run paused `graph_blocked`.

### Slice DG-5.1h — Gap Planner Codex Tool Exposure

Deliverables:

- Codex Server dynamic tools expose `submit_graph_patch` to planner nodes with
  role `gap_planner`, not only role `planner`.
- The Codex Server wrapper prompt includes the graph-mutation tool section for
  both planner roles.
- The `submit_graph_patch` schema and payload normalizer allow `ops: []` for
  explicit no-op patch decisions.

Done when:

- Focused Codex Server tests prove gap planners receive the tool and prompt
  section.
- A focused callback-routing test proves an empty-ops patch reaches the graph
  patch callback.
- A fresh DG-5.1 run reaches the gap planner and records a graph patch decision
  instead of no-submit caused by missing tool exposure.

Accepted 2026-06-15 for the code-level repair. Validation passed:
`uv run pytest tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py tests/unit/test_codex_server_transport.py -q`;
`uv run ruff check src/orchestrator/runners/__init__.py src/orchestrator/runners/agents/codex/common.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py tests/unit/test_codex_server_transport.py`;
and `uv run pyright src/orchestrator/runners/__init__.py src/orchestrator/runners/agents/codex/common.py tests/unit/test_codex_server_common.py`.
Retry `fd2728e8-a2dc-4b17-8c55-c0c031a33471` verified the live behavior: the
gap planner submitted an accepted no-op graph patch instead of exiting without
submit.

### Slice DG-5.1i — Dynamic Region Dependency Validation

Deliverables:

- Planner-created `gap_planner` nodes require a required incoming verification
  evidence edge in the same patch.
- Planner-precreated corrective workers require a required incoming
  `classified_gap` edge in the same patch. This does not apply to patches
  proposed by a `gap_planner` actor, because that actor's patch is itself the
  gap classification decision.
- Planner-created final invariant checks require a required incoming
  verification evidence edge in the same patch.

Done when:

- A focused graph planner test rejects the bad shape observed in
  `fd2728e8-a2dc-4b17-8c55-c0c031a33471`.
- A focused graph planner test accepts the same dynamic region shape once the
  required verification/classified-gap edges are present.
- Existing gap-planner validation still allows a gap planner actor to append a
  corrective work region directly.
- A fresh DG-5.1 run either receives a corrected root planner patch or records a
  clear `graph_patch_rejected` reason for missing dynamic-region dependencies.

Accepted 2026-06-15 for the code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_planner.py tests/unit/test_patch_validator.py tests/unit/test_graph_planner_packet.py -q`;
`uv run ruff check src/orchestrator/graph/patch_validator.py tests/unit/test_graph_planner.py`;
and `uv run pyright src/orchestrator/graph/patch_validator.py tests/unit/test_graph_planner.py`.
Retry `28d62e16-eff5-496a-aa9b-f360c77af779` verified the accepted-root-patch
case: required dynamic-region edges were present, and readiness deferred until
verification evidence bound.

### Slice DG-5.1j — Gap Classification Output Binding

Deliverables:

- A gap planner no-op patch is rejected when the graph already contains a
  required downstream `classified_gap` successor edge from that gap planner.
- A gap planner that has an accepted non-empty graph patch emits a compact
  `gap_classification` output record on plain submit.
- Existing classified-gap input edges can bind that record and release
  corrective work.

Done when:

- A focused patch-validator test rejects gap-planner no-op patches that would
  leave required classified-gap successors unsatisfied.
- A focused dispatch test proves gap-planner submit emits a `gap` record on
  port `gap_classification` after an accepted non-empty patch.
- A fresh DG-5.1 run moves from gap-planner completion into corrective-worker
  readiness through an `input_bound` on `classified_gap`.

Accepted 2026-06-15 for the code-level repair. Validation passed:
`uv run pytest tests/unit/test_patch_validator.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_planner.py -q`;
`uv run ruff check src/orchestrator/graph/patch_validator.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_patch_validator.py tests/unit/test_graph_dispatch_on_output.py`;
and `uv run pyright src/orchestrator/graph/patch_validator.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_patch_validator.py tests/unit/test_graph_dispatch_on_output.py`.
Next action: retry DG-5.1 from a fresh run and confirm classified-gap binding.

### Slice DG-5.1k — Gap Analysis Output Port Compatibility

Deliverables:

- Gap planner submit records use accepted generic `output` records, not a
  dropped custom `gap` record kind.
- Accepted non-empty gap-planner patches emit compact gap-analysis records on
  all live-observed planner ports: `gap_plan`, `gap_classification`, and
  `classified_gap`.
- `gap_analysis` selector matching binds those records into downstream
  `classified_gap` inputs.

Done when:

- Focused command tests prove `gap_analysis` output records bind for
  `gap_classification -> classified_gap` and
  `classified_gap -> classified_gap` edges.
- Focused dispatch tests prove gap-planner submit emits all compatibility
  records after an accepted non-empty patch.
- A fresh DG-5.1 run advances from gap-planner completion to corrective-worker
  readiness through an `input_bound` on `classified_gap`.

Accepted 2026-06-15 for code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_commands.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_claude_sdk_agent.py tests/unit/test_claude_sdk_tool_filtering.py -q`;
`uv run ruff check src/orchestrator/graph_runtime/dispatch.py src/orchestrator/runners/agents/claude_sdk/agent.py tests/unit/test_graph_commands.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_claude_sdk_agent.py`;
and `uv run pyright src/orchestrator/graph_runtime/dispatch.py src/orchestrator/runners/agents/claude_sdk/agent.py tests/unit/test_graph_commands.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_claude_sdk_agent.py`.

Live evidence:

- Run `3d0fcc75-45c5-4906-bd1a-a832bf44524d` showed the callback payload
  included `gap-classification-*`, but the graph accepted only the file-state
  record because `record_kind="gap"` was not accepted by `OutputRecord`.
- Run `4f143f81-e85f-4d6e-8693-14417562769a` showed gap planner submit emitted
  `gap_plan` and `gap_classification`, but the root edge used
  `from_port="classified_gap"`, so no `input_bound` fired.

Next action: retry DG-5.1 from a fresh run and confirm the new
`classified_gap` output port binds the live root edge.

### Slice DG-5.1l — Claude SDK Graph Runner Fallback

Deliverables:

- Claude SDK runner exposes `submit_graph_patch` through its in-process MCP
  server whenever `ExecutionContext.graph_patch_callback` is present.
- The tool accepts top-level patch fields, nested patch objects, and JSON-string
  patch payloads.
- Graph-node prompts explicitly require calling the MCP `submit` tool
  (`mcp__orchestrator__submit`) after node work, even when requirements are
  empty; prose saying "submitted" is not enough.

Done when:

- Focused Claude SDK tests cover graph-patch prompt text, graph-node submit
  instructions, and MCP server construction with graph callback enabled.
- A Claude SDK DG-5.1 run can submit graph patches and worker callbacks without
  relying on Codex quota.

Accepted 2026-06-15 for code-level fallback support. Validation passed:
`uv run pytest tests/unit/test_claude_sdk_agent.py tests/unit/test_claude_sdk_tool_filtering.py -q`;
`uv run ruff check src/orchestrator/runners/agents/claude_sdk/agent.py tests/unit/test_claude_sdk_agent.py`;
and `uv run pyright src/orchestrator/runners/agents/claude_sdk/agent.py tests/unit/test_claude_sdk_agent.py`.

Live evidence:

- Codex Server runs with `gpt-5.5` and `gpt-5.4-mini` both failed with the same
  usage-limit reset message: "try again at 2:27 PM."
- Claude SDK run `4f143f81-e85f-4d6e-8693-14417562769a` proved
  `submit_graph_patch` reaches the graph kernel: it produced two intended
  rejections, then accepted `smoke-full-execution-plan-v3`.
- The same run proved the graph-node submit prompt gap: the initial worker wrote
  `docs/graph-approach/dynamic-smoke-output.txt` but exited without submit while
  saying it had called `orchestrator_submit`.
- Later retry evidence in run `ee306e4c-0033-4e02-a2a0-4620990dc3f4` proved the
  stronger prompt can produce a worker candidate record and bind it into the
  weak verifier.

Residual risk:

- Claude SDK sessions remain less reliable than Codex Server after rejected
  graph patches; multiple live runs needed a retry before an accepted root patch.
- Root planner retries can accept duplicate root patches after an earlier
  accepted patch if the planner exits without plain submit. This is a separate
  scheduler/idempotency gap and should be addressed before declaring DG-5.1
  fully operational.

Next action: add a narrow guard so a planner node with an accepted graph patch
cannot be re-leased for additional graph writes after it exits without submit,
or ensure accepted graph-patch callback completion is enough to release the
planner without retry.

### Slice DG-5.1m — Accepted Planner Patch Retry Guard

Deliverables:

- Projection state records accepted graph patch IDs by proposer node.
- `agent_died` no longer requeues a non-gap planner that already has an
  accepted graph patch; it revokes the lease and marks the planner completed
  with trigger `accepted_graph_patch_before_agent_death`.
- Gap planners are excluded from this guard because their plain submit emits
  the gap-analysis records needed to release corrective work.

Done when:

- A pure command test proves a normal planner with an accepted patch completes
  rather than requeueing on agent death.
- A paired test proves gap planners still requeue after accepted patch + death.
- Projection tests preserve the new accepted-patch state.
- A fresh DG-5.1 run no longer accepts duplicate root planner patches after the
  first accepted root patch.

Accepted 2026-06-15 for code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py -q`;
`uv run ruff check src/orchestrator/graph/commands.py src/orchestrator/graph/projections.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py`;
and `uv run pyright src/orchestrator/graph/commands.py src/orchestrator/graph/projections.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py`.

Live evidence prompting the slice:

- Run `ee306e4c-0033-4e02-a2a0-4620990dc3f4` accepted root patch
  `dynamic-smoke-execution-plan-v2`, then later accepted another root patch
  `dynamic-smoke-wire-regions-v3` from the same root planner after an
  `agent exited without submit` retry. That duplicate patch added a second
  writer/verifier chain and affected scheduling.

Next action: retry DG-5.1 from a fresh run and confirm the root planner is not
re-leased for duplicate graph writes after an accepted root patch.

### Slice DG-5.1n — Claude CLI Graph Patch Bridge

Deliverables:

- `cli_subprocess` can drive graph planner nodes when Claude SDK is unavailable
  or stuck before model usage.
- Claude CLI planner prompts include a deterministic
  `ORCHESTRATOR_GRAPH_PATCH:` sentinel bridge for patch envelopes.
- The CLI runner parses both plain sentinel lines and Claude `stream-json`
  tool-result content, normalizes top-level or nested `{ "patch": ... }`
  payloads, and routes them through the existing graph patch callback before
  normal submit.

Done when:

- Prompt tests prove the bridge instructions are present when a graph patch
  callback exists, including graph dispatch contexts without an API URL.
- Execution tests prove sentinel output invokes the graph patch callback before
  submit.
- Stream-json tests prove the live Claude CLI output format is parsed.
- A fresh DG-5.1 run can use `cli_subprocess` with `command: claude`.

Accepted 2026-06-15 for code-level repair. Validation passed:
`uv run pytest tests/unit/test_cli_agent.py tests/unit/test_cli_agent_commit_retry.py -q`;
`uv run pytest tests/unit/test_cli_agent.py tests/unit/test_cli_agent_commit_retry.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py -q` (`146 passed`);
`uv run ruff check src/orchestrator/runners/agents/claude_cli/agent.py tests/unit/test_cli_agent.py tests/unit/test_cli_agent_commit_retry.py`;
and `uv run pyright src/orchestrator/runners/agents/claude_cli/agent.py tests/unit/test_cli_agent.py tests/unit/test_cli_agent_commit_retry.py`.

Live evidence prompting the slice:

- Claude SDK runs `c76154d3-c0c0-4222-bdb3-28c6b2a16ede` and
  `a6ad2fdf-a3d4-4074-9ace-4eb5add99404` both reached root planner dispatch,
  then remained active with zero actions and zero token usage until cancelled
  through the API.
- `cli_subprocess` did not previously expose `submit_graph_patch`, so it could
  not serve as a dynamic graph fallback despite the Claude CLI quota reset.

Next action: retry DG-5.1 with `cli_subprocess`/Claude CLI and confirm live
sentinel output reaches the graph kernel.

### Slice DG-5.1o — Graph Runner Rate-Limit Classification

Deliverables:

- Graph `agent_died` no longer treats runner rate-limit errors as ordinary
  retryable process deaths.
- Rate-limited graph nodes revoke their lease and transition to `failed` with
  trigger `agent_rate_limited`.
- Graph outcome classification reports failed node IDs and their recorded
  reasons, so run pause state distinguishes external runner quota from generic
  graph quiescence.

Done when:

- Pure command tests prove a rate-limit `agent_died` emits no
  `runtime_retry_scheduled` event.
- Driver logic tests prove the blocked reason includes the failed node and
  rate-limit reason.
- A fresh DG-5.1 run under an exhausted runner pauses with a clear rate-limit
  blocker instead of retrying immediately.

Accepted 2026-06-15 for code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_commands.py tests/unit/test_graph_driver_logic.py -q` (`66 passed`);
`uv run ruff check src/orchestrator/graph/commands.py src/orchestrator/workflow/graph_driver.py tests/unit/test_graph_commands.py tests/unit/test_graph_driver_logic.py`;
and `uv run pyright src/orchestrator/graph/commands.py src/orchestrator/workflow/graph_driver.py tests/unit/test_graph_commands.py tests/unit/test_graph_driver_logic.py`.

Live evidence prompting the slice:

- CLI graph run `e1e9648d-28a7-4ab2-a300-5ae764ce51e6` dispatched the root
  planner, then Claude CLI reported
  `Agent runner 'cli_subprocess' hit rate limit (resets at 2026-06-15 14:30:00+01:00)`.
- The graph runtime retried the same planner twice and then paused as
  `graph_blocked` with `graph quiescent without completion`, losing the real
  external quota cause in the durable pause reason.

Next action: after Claude CLI quota resets at 2026-06-15 14:30 BST, retry
DG-5.1 with `cli_subprocess`/Claude CLI and verify either sentinel bridge
success or the clearer rate-limit pause behavior.

Combined focused validation after DG-5.1n/o passed:
`uv run pytest tests/unit/test_cli_agent.py tests/unit/test_cli_agent_commit_retry.py tests/unit/test_claude_sdk_agent.py tests/unit/test_claude_sdk_tool_filtering.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/unit/test_graph_driver_logic.py -q` (`231 passed`);
`uv run ruff check` over the touched runner/graph/test files; and
`uv run pyright` over the same touched source/test set.

### Slice DG-5.1p — Rejected Planner Patch Submit Guard

Deliverables:

- Planner nodes can no longer complete after only a rejected graph patch.
- `GraphDispatchExecutor` tracks submitted vs accepted patch feedback
  separately.
- Plain submit for planner/gap-planner nodes requires accepted
  `submit_graph_patch` feedback; rejected feedback must be used to submit a
  corrected patch.
- Planner prompt contract now says to submit only after accepted patch
  feedback.

Done when:

- A focused dispatch test proves rejected patch feedback prevents submit and
  records an agent failure instead of completing the planner.
- Planner packet/prompt tests prove the active prompt no longer teaches
  "accepted or rejected" as sufficient for plain submit.
- A fresh DG-5.1 retry no longer quiesces immediately after a rejected root
  planner patch.

Accepted 2026-06-15 for code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_planner_packet.py -q` (`17 passed`);
`uv run ruff check src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_planner_packet.py`;
and `uv run pyright src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_planner_packet.py`.

Live evidence prompting the slice:

- CLI graph run `d142a850-ca60-4a3f-b0fc-171ca39c5d86` proved the
  `ORCHESTRATOR_GRAPH_PATCH:` bridge reaches the graph kernel: the root planner
  submitted `patch-dynamic-smoke-initial-plan` and the kernel rejected it with
  `invariant check requires verification input edge`.
- The same run then completed `planner-s-01` through the ordinary submit
  callback even though no patch was accepted, leaving no successor graph
  structure and pausing as `graph quiescent without completion`.

Next action: retry DG-5.1 with `cli_subprocess`/Claude CLI and verify rejected
root patches cause correction/retry instead of planner completion.

### Slice DG-5.1q — Startup Recovery Active-Run Guard

Deliverables:

- Graph startup recovery no longer re-arms every historical ACTIVE graph run.
- ACTIVE graph runs are not automatically re-armed at startup; operators can
  resume/recover them explicitly.
- Recoverable PAUSED graph runs still use the existing pause-reason policy.

Done when:

- Unit tests prove ACTIVE graph rows are excluded while restart-recoverable
  PAUSED graph runs are selected.
- A dev-server restart no longer re-arms old graph runs from earlier validation
  attempts and no longer causes repeated SQLite lock contention before a fresh
  DG-5.1 retry.

Accepted 2026-06-15 for code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_recovery_selection.py -q` (`4 passed`);
`uv run ruff check src/orchestrator/workflow/graph_recovery.py src/orchestrator/api/app.py tests/unit/test_graph_recovery_selection.py`;
and `uv run pyright src/orchestrator/workflow/graph_recovery.py src/orchestrator/api/app.py tests/unit/test_graph_recovery_selection.py`.

Live evidence prompting the slice:

- Dev-server restarts repeatedly re-armed old ACTIVE graph runs including
  `ee306e4c-0033-4e02-a2a0-4620990dc3f4` and
  `e039991a-0317-4415-b815-63f5998a2ae6`, causing SQLite lock contention and
  backend health timeouts before fresh DG-5.1 validation could proceed.

Next action: restart with the active-run guard loaded, confirm stale graph runs
are not rearmed, then retry DG-5.1 with `cli_subprocess`/Claude CLI.

### Slice DG-5.1r — Horizon Template Evidence Edges

Deliverables:

- Standard gap-analysis horizon templates now include the required
  verifier-to-gap `verification_evidence` edge.
- Standard final-invariant horizon templates now include the required
  verification-to-invariant `verification_evidence` edge.
- Compact planner examples no longer show invalid standalone gap-planner or
  invariant-check patches; each includes selector-bound verification evidence.

Done when:

- Horizon template patches validate under the same dynamic dependency rules
  that rejected the live root planner patches.
- Planner packet tests prove the active prompt examples expose the
  selector-bound evidence edges.
- A fresh DG-5.1 retry can move past root planner patch rejections caused by
  missing verification evidence edges.

Accepted 2026-06-15 for code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_horizon_templates.py tests/unit/test_patch_validator.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_dispatch_on_output.py -q` (`45 passed`);
`uv run ruff check src/orchestrator/graph_runtime/horizon_templates.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_horizon_templates.py tests/unit/test_patch_validator.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_dispatch_on_output.py`;
and `uv run pyright src/orchestrator/graph_runtime/horizon_templates.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_horizon_templates.py tests/unit/test_patch_validator.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_dispatch_on_output.py`.

Live evidence prompting the slice:

- Fresh CLI graph run `f207295f-1ab9-4ea1-9d01-687d489c4dea` proved the
  DG-5.1n sentinel bridge and DG-5.1p rejected-patch guard in production: the
  root planner submitted two `ORCHESTRATOR_GRAPH_PATCH:` patches, both reached
  the kernel, both were rejected, and the planner was retried instead of being
  completed.
- The first rejection was `gap planner requires verification input edge`.
- The second rejection was `corrective worker requires classified_gap input
  edge`; the corrective edge had already been added to
  `corrective_work_region`, but the active examples/templates still needed
  evidence-edge guidance for root-planner regions.

Next action: restart with DG-5.1r loaded and retry DG-5.1 with
`cli_subprocess`/Claude CLI.

### Slice DG-5.1s — Dynamic Worker Prompt Grounding

Deliverables:

- Worker-like graph dispatch prompts now recover dynamic-feature context from
  the routine snapshot when planner-created nodes omit explicit objective,
  feature-spec, artifact, or command fields.
- Dynamic-feature workers receive fallback prompt lines for feature spec path,
  feature spec content, weak acceptance command, hidden oracle command, and a
  direct instruction to avoid unrelated repository slices.
- Corrective workers receive a role-specific fallback instruction to make the
  hidden oracle pass.

Done when:

- A unit test covers the live failure shape: a planner-created worker with only
  `node_id`, `kind`, `role`, and `task_region_id`, plus dynamic-feature data in
  the routine snapshot.
- A fresh DG-5.1 retry gets past root patch acceptance and does not leave the
  initial worker exploring unrelated slice docs because of missing prompt
  grounding.

Accepted 2026-06-15 for code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_planner_packet.py -q` (`7 passed`);
`uv run ruff check src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_planner_packet.py`;
and `uv run pyright src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_planner_packet.py`.

Live evidence prompting the slice:

- Fresh CLI graph run `d58bdd11-2c8b-4fc1-aaff-4beda36b6aa3` accepted root
  planner patch `patch-ds-full-plan`, completing `planner-s-01` and scheduling
  `worker-ds-builder`.
- The graph then reached expected deferred downstream nodes:
  `verifier-ds-weak` missing `candidate_under_test`,
  `planner-ds-gap` missing `verification_evidence`,
  `worker-ds-corrective` missing `classified_gap`, and
  `check-ds-invariant` missing `verification_evidence`.
- `worker-ds-builder` was leased/running but produced no artifact and no graph
  callback. Activity showed the worker prompt lacked actionable feature context:
  it searched generic repo files, read unrelated slice docs such as
  `slice-4.4-spec.md`, and inspected Codex runner files instead of creating
  `docs/graph-approach/dynamic-smoke-output.txt`.
- The run was manually paused through `POST /api/runs/d58bdd11-2c8b-4fc1-aaff-4beda36b6aa3/pause`
  to preserve Claude quota after the blocker was classified.

Accepted live evidence after Claude quota reset:

- Fresh CLI graph run `4a147a09-fb6d-46a6-9d5f-2dec0a338c15` used
  `cli_subprocess` with Claude CLI model `claude-sonnet-4-6` and completed.
- The root planner submitted accepted graph patch `patch-smoke-full-plan`.
- `worker-smoke-builder` wrote and submitted
  `docs/graph-approach/dynamic-smoke-output.txt` with:
  `dynamic-smoke` and `validation-strengthened: true`.
- `verifier-smoke-initial` submitted accepted verification record
  `verification-exec-b010767103c941479336521a6f63dd66`, which bound to
  `planner-smoke-gap.verification_evidence`.
- `planner-smoke-gap` first submitted rejected no-op patch
  `smoke-gap-no-op` with reason
  `gap planner no-op leaves required classified_gap successor unsatisfied`;
  the rejected-patch guard retried the node, then accepted patch
  `smoke-gap-corrective-edges`.
- The gap planner emitted `gap_plan`, `gap_classification`, and
  `classified_gap` records; `classified_gap` bound to
  `worker-smoke-corrective.classified_gap`.
- `worker-smoke-corrective` submitted candidate `smoke-candidate-v2`, which
  bound to `verifier-smoke-corrective.candidate_under_test`.
- `verifier-smoke-corrective` submitted accepted verification record
  `verification-exec-632c1c3dbee64b3b9d62ff555c08cdb8`, which bound to
  `check-smoke-invariant.verification_evidence`.
- `uv run python scripts/compare_carriers.py dynamic=4a147a09-fb6d-46a6-9d5f-2dec0a338c15`
  reported `dynamic runs=1`, `completed=1`, `avg_tools=14.0`, and
  `avg_cost$=0.3497`.
- `/health` returned `{"status":"ok"}` after completion.

DG-5.1 is not fully accepted yet. The graph event stream did not show
`check-smoke-invariant` reaching ready/running/completed before the run status
became `completed`, and completed-run graph read models became unreliable:
`/api/runs/4a147a09-fb6d-46a6-9d5f-2dec0a338c15/graph` and
`/graph/scheduler` timed out, and a later narrow `/graph/events?from_position=132`
read also timed out once before the comparison script succeeded. The next slice
is DG-5.1t — Final Invariant Completion And Graph Read Health.

### Slice DG-5.1t — Final Invariant Completion And Graph Read Health

Deliverables:

- Graph-run completion must not mark a dynamic run complete while a final
  invariant check node is still merely input-bound.
- The final invariant check must emit observable ready/running/completed or
  failed evidence before the run reaches terminal status.
- Completed-run graph read APIs must remain responsive enough for validation
  and comparison: `/graph`, `/graph/events`, and `/graph/scheduler`.
- Add compact tests around the live failure shape: evidence bound into a final
  invariant node, then no explicit final-check terminal event before run
  completion.

Done when:

- Focused unit/integration tests prove completion waits for the final invariant
  node's terminal state, or documents a deliberate terminal-check shortcut with
  equivalent durable evidence.
- A fresh DG-5.1 retry reaches completion with visible final invariant evidence
  and responsive graph read APIs.
- `scripts/compare_carriers.py dynamic=<run_id>` succeeds against that fresh
  run.

Accepted 2026-06-15 for code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_projections.py tests/unit/test_graph_commands.py tests/unit/test_graph_driver_logic.py tests/integration/test_graph_run_driver.py -q`
(`108 passed`);
`uv run ruff check src/orchestrator/graph/projections.py tests/unit/test_graph_projections.py tests/integration/test_graph_run_driver.py`;
and `uv run pyright src/orchestrator/graph/projections.py tests/unit/test_graph_projections.py tests/integration/test_graph_run_driver.py`.

Implementation evidence:

- `final_invariant_blockers_for_events` now treats pending `check` nodes as
  final invariant blockers.
- Regression coverage proves accepted task state plus a planned check keeps
  `project_run_state(events)` active.
- `test_graph_run_driver` fake planner now follows the current planner
  contract by submitting an accepted graph patch before plain submit.

Live retry evidence from run `89d5347a-94d8-4881-8448-3dcfdca3f268` proved the
completion guard but exposed the next boundary gap:

- Root planner patch `patch-dynamic-smoke-full-plan` created
  `check-dynamic-smoke-invariant`.
- Builder, verifier, gap planner, corrective worker, and corrective verifier
  all progressed through accepted evidence.
- Corrective verification evidence bound to
  `check-dynamic-smoke-invariant.verification_evidence`.
- The run stayed `active` after that binding instead of prematurely completing,
  proving the DG-5.1t blocker repair.
- The final invariant check then deferred with
  `precondition_failed:has_command_definition` because the planner-created
  check node lacked both `command_definition` and `hidden_oracle_command`.
- `/graph/events?from_position=139` and `/graph/scheduler` responded; `/graph`
  still timed out under the completed/blocked live graph size.
- `uv run python scripts/compare_carriers.py dynamic=89d5347a-94d8-4881-8448-3dcfdca3f268`
  succeeded and reported `dynamic runs=1`, `completed=0`, `avg_tools=20.0`,
  and `avg_cost$=0.4179`.

Next action: DG-5.1u — Planner Patch Check Command Validation.

### Slice DG-5.1u — Planner Patch Check Command Validation

Deliverables:

- Planner-created `check` nodes are rejected at patch-validation time unless
  they include a dict `command_definition` or nonempty `hidden_oracle_command`.
- Planner prompts explicitly require command-bearing check nodes; dynamic
  feature final invariant checks should use
  `dynamic_feature.hidden_oracle_command` when present.
- The final invariant horizon template records that runtime command binding is
  required.

Done when:

- Focused patch-validator tests prove commandless checks are rejected while
  checks with `hidden_oracle_command` or `command_definition` are accepted.
- A fresh DG-5.1 retry no longer reaches
  `precondition_failed:has_command_definition` for the final invariant check.
  It either completes with visible final invariant evidence or pauses on a new,
  accurate blocker.

Accepted 2026-06-15 for behavior and live smoke completion. Validation passed:
`uv run pytest tests/unit/test_patch_validator.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner.py -q`
(`53 passed`);
`uv run ruff check src/orchestrator/graph/patch_validator.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/horizon_templates.py tests/unit/test_patch_validator.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner.py`;
and `uv run pyright src/orchestrator/graph/patch_validator.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/horizon_templates.py tests/unit/test_patch_validator.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner.py`.

Live run `0c053df6-1702-4d67-94de-628a4e2ee256` verified:

- Root planner created `check-final-invariant-dynamic-smoke` with
  `hidden_oracle_command` and canonical `command_definition`.
- The prior `precondition_failed:has_command_definition` blocker did not recur.
- The artifact in `worktrees/r301/docs/graph-approach/dynamic-smoke-output.txt`
  contains both `dynamic-smoke` and `validation-strengthened: true`.
- Corrective verifier completed; final invariant check reached ready, leased,
  running, and completed (`node_state_changed` completed at graph position 157).
- The run reached API status `completed` with cost `$0.765336`, `47` actions,
  `79` input tokens, `13278` output tokens, and `939866` cache tokens.

Remaining blocker: completed-run readback is still too heavy for comparison.
`/graph/scheduler` needed about 30 seconds in one completed-run probe, `/graph`
timed out at 60 seconds, and `scripts/compare_carriers.py
dynamic=0c053df6-1702-4d67-94de-628a4e2ee256` timed out fetching full
`/graph/events`. The next slice is DG-5.1v — Compact Graph Event Readback.

### Slice DG-5.1v — Compact Graph Event Readback

Deliverables:

- Add a validated compact graph-events API mode that preserves event identity
  and metric-relevant payload fields while omitting large callback/file-state
  payloads.
- Keep full `/graph/events` behavior as the default.
- Update `scripts/compare_carriers.py` to use compact graph events.

Done when:

- Focused API and comparison tests prove summary mode works and invalid modes
  return 422.
- `scripts/compare_carriers.py dynamic=0c053df6-1702-4d67-94de-628a4e2ee256`
  succeeds against the completed DG-5.1 run.
- A bounded summary graph-events probe responds without the full-event timeout.

Accepted 2026-06-15. Validation passed:
`uv run pytest tests/integration/test_graph_api.py tests/integration/test_graph_event_store.py tests/unit/test_compare_carriers.py -q`
(`21 passed`);
`uv run ruff check src/orchestrator/api/routers/graph.py src/orchestrator/graph_runtime/store.py scripts/compare_carriers.py tests/integration/test_graph_api.py tests/integration/test_graph_event_store.py tests/unit/test_compare_carriers.py`;
and `uv run pyright src/orchestrator/api/routers/graph.py src/orchestrator/graph_runtime/store.py scripts/compare_carriers.py tests/integration/test_graph_api.py tests/integration/test_graph_event_store.py tests/unit/test_compare_carriers.py`.

Live evidence against completed DG-5.1 run
`0c053df6-1702-4d67-94de-628a4e2ee256`:

- `GET /graph/events?payload_mode=summary` returned HTTP 200 in `0.603433s`
  with a `46969` byte payload.
- `GET /graph/events?payload_mode=compact` returned HTTP 422 in `0.001268s`.
- `uv run python scripts/compare_carriers.py dynamic=0c053df6-1702-4d67-94de-628a4e2ee256`
  succeeded and reported `dynamic runs=1`, `completed=1`, `avg_in=79`,
  `avg_out=13278`, `avg_cache=939866`, `avg_tools=47.0`, and
  `avg_cost$=0.7653`.

Next action: DG-5.2 — Full Comparison Re-run.

### Slice DG-5.2 — Full Comparison Re-run

Deliverables:

- Execute the five-arm comparison from `true-comparison-plan.md`.
- Arm C uses faithful Mind-the-gap skill.
- Arm E uses production dynamic graph, not manual horizon scripts.

Done when:

- Results report distinguishes:
  - single-agent baseline;
  - fixed 3-agent plan;
  - faithful Mind-the-gap;
  - static graph carrier;
  - dynamic graph.
- Dynamic graph operational status is accepted or remaining blockers are
  recorded with evidence.

### Slice DG-5.2a — True Comparison Harness

Deliverables:

- Create the durable comparison harness spec and results ledger for DG-5.2.
- Preserve accepted DG-5.1 Arm E smoke evidence without overstating it as a
  five-arm comparison conclusion.
- Define the scenario contract, five arms, runner controls, per-arm evidence
  fields, and validation commands that subsequent comparison runs must follow.

Done when:

- `docs/graph-approach/slice-DG-5.2a-spec.md` records the harness.
- `docs/graph-approach/true-comparison-results.md` records Arm E smoke evidence
  and marks Arms A-D pending.
- The next slice can launch controlled Arms A-D runs or select a larger
  comparison scenario without losing the verified DG-5.1 evidence.

Accepted 2026-06-15 as the comparison setup slice. Validation evidence:
`uv run python scripts/compare_carriers.py dynamic=0c053df6-1702-4d67-94de-628a4e2ee256`
reported `completed=1`, `avg_tools=47.0`, and `avg_cost$=0.7653`;
`GET /graph/events?payload_mode=summary` returned HTTP 200 in about `0.6s`.
The compact event summary contains 158 graph events, accepted planner patch
`patch-dynamic-smoke-full-graph`, rejected gap no-op
`no-gap-no-op-dynamic-smoke-01`, accepted gap patch
`gap-classify-passed-edge-dynamic-smoke-02`, two verifier passes, and final
invariant check completion at position 157. Next action: DG-5.2b, hidden oracle
isolation, because the completed smoke run is operational evidence but predates
the true-comparison hidden-test discipline.

### Slice DG-5.2b — Hidden Oracle Isolation

Deliverables:

- Keep `hidden_oracle_command` in durable runtime state but remove the command
  string from planner packets, planner task context, and worker-like prompts.
- Expose an opaque `dynamic_feature_hidden_oracle` command binding for dynamic
  final invariant checks.
- Accept check nodes that use the binding and resolve the binding to a concrete
  command definition from `routine-snapshot.dynamic_feature.hidden_oracle_command`
  when applying an accepted patch.

Done when:

- Focused prompt/packet tests prove agents do not see the hidden oracle command
  string.
- Focused patch-validator and command-applier tests prove
  `command_binding: dynamic_feature_hidden_oracle` is accepted and converted to
  an executable check command.
- Existing dynamic-feature routine compile tests still preserve the command in
  the routine snapshot for runtime use.

Accepted 2026-06-15 for code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_planner_packet.py tests/unit/test_patch_validator.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_compiler.py tests/unit/test_graph_planner.py tests/integration/test_graph_routine_compile.py -q`
(`111 passed`);
focused `uv run ruff check` over the touched graph/runtime/test files; and
focused `uv run pyright` over the same files. Next action: run a fresh DG-5.1
dynamic smoke retry with oracle isolation loaded, then launch controlled DG-5.2
Arms A-D if the binding path is live-proven.

Live isolated retry `e4c168ea-d61a-469b-ae92-127c739557ed` proved the binding
path but exposed the next blocker. The final check node was created with
`command_binding: dynamic_feature_hidden_oracle` and runtime-resolved
`command_definition.source: dynamic_feature_hidden_oracle_binding`. The artifact
contained only `dynamic-smoke`; weak verification passed; the gap planner's
first no-op was rejected; its retry accepted
`no-gap-retire-corrective-dynamic-smoke`, retired the corrective worker/verifier,
and added a late edge from the weak verifier to the final check. No input binding
was backfilled for the already accepted verifier record, and the run paused
`graph_blocked` with final check still deferred on
`missing_required_input:verification_evidence`. Next action: DG-5.2c — Gap
Planner Final Evidence Safety.

### Slice DG-5.2c — Gap Planner Final Evidence Safety

Deliverables:

- Backfill `input_bound` events when a new input edge matches an already
  accepted output record.
- Reject gap-planner patches that retire executable worker, verifier, or check
  nodes.
- Preserve DG-5.2b oracle isolation behavior.

Done when:

- A command-applier test proves a late verifier-to-check edge binds an existing
  verification record.
- A patch-validator test rejects the live gap-planner retire shape.
- Focused graph tests, ruff, and pyright pass.

Accepted 2026-06-15 for code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_commands.py tests/unit/test_patch_validator.py -q`
(`87 passed`);
`uv run pytest tests/unit/test_graph_planner_packet.py tests/unit/test_patch_validator.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_compiler.py tests/unit/test_graph_planner.py tests/unit/test_graph_commands.py tests/integration/test_graph_routine_compile.py -q`
(`174 passed`);
focused `uv run ruff check` over the touched files; and focused
`uv run pyright` over the same files. Next action: restart/reload with DG-5.2c
loaded and run a fresh isolated dynamic smoke retry.

Live retry `2558d649-d27a-4816-b1f6-a68e33e3c59d` proved the DG-5.2c retire
guard but exposed the next blocker. Summary event readback returned 110 events.
The root planner's first patch `patch-dynamic-smoke-full-plan` was rejected
because the invariant check lacked a verification input edge, retry patch
`patch-ds-full-plan-v3` was accepted, gap no-op patch `patch-ds-gap-no-op` was
rejected with `gap planner no-op leaves required classified_gap successor
unsatisfied`, and retire patch `patch-ds-gap-retire-corrective` was rejected
with `gap planner cannot retire executable node: worker-ds-corrective`. The
final summary event at position 110 re-readied `planner-ds-gap`, then the run
paused `graph_blocked`.

Next action: DG-5.2d — Gap Planner Retry Obligation Signal.

### Slice DG-5.2d — Gap Planner Retry Obligation Signal

Deliverables:

- Report ready-node and active-lease graph driver blockers explicitly instead
  of collapsing them to generic quiescence.
- Add gap-planner packet obligations for waiting `classified_gap` successors and
  final invariant checks deferred on missing `verification_evidence`.
- Tell gap planners that obligations are blocking and no-op patches are invalid
  while obligations remain.

Done when:

- Focused graph-driver tests prove retry-ready nodes are reported as dispatch
  blockers.
- Focused planner packet tests prove gap planners receive the live retry
  obligation shapes.
- Focused graph-runtime ruff and pyright checks pass.

Accepted 2026-06-15 for code-level repair. Validation passed:
`uv run pytest tests/unit/test_graph_driver_logic.py tests/unit/test_graph_planner_packet.py -q`
(`13 passed`);
`uv run ruff check src/orchestrator/workflow/graph_driver.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_driver_logic.py tests/unit/test_graph_planner_packet.py`;
and `uv run pyright src/orchestrator/workflow/graph_driver.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_driver_logic.py tests/unit/test_graph_planner_packet.py`.

Live retry `abba86e4-5b6e-459c-a074-63118005cb95` proved the DG-5.2d
obligation signal. The root planner accepted
`patch-dynamic-smoke-full-plan`; after weak verifier success, the gap planner
accepted `patch-smoke-gap-wire-final-invariant` instead of repeating the prior
no-op or executable-retire failures. Corrective worker ran, but corrective
verifier `verifier-smoke-corrective` failed with classified runner quota
evidence: `Agent runner 'cli_subprocess' hit rate limit (resets at 2026-06-15
19:30:00+01:00)`. The run paused `graph_blocked`; summary event readback
returned 118 events, with final event position 118 deferring
`check-smoke-final-invariant` on `missing_required_input:verification_evidence`.
The run worktree artifact still contains only `dynamic-smoke`. Comparison
metrics: `isolated3 runs=1 completed=0 avg_in=22 avg_out=7595
avg_cache=216187 avg_tools=12.0 avg_cost$=0.3276`.

Next action: retry `abba86e4-5b6e-459c-a074-63118005cb95` after the
2026-06-15 19:30 BST Claude CLI quota reset, or switch to an available
non-rate-limited runner. Expected outcome is corrective verifier completion and
final invariant scheduling, or a new verified blocker beyond runner quota.

## Recommended Slice Order

1. DG-0.1 Baseline Matrix
2. DG-0.2 Dynamic Metrics Schema
3. DG-1.1 Planner Graph Packet
4. DG-1.2 Fenced Planner Patch Tool
5. DG-1.3 Planner Prompt Contract
6. DG-2.1 Dynamic Feature Routine Skeleton
7. DG-2.2 Horizon Region Templates
8. DG-3.1 Gap Planner Node Semantics
9. DG-3.2 Requirement/Evidence Revision Policy
10. DG-3.3 Final Invariant Gate
11. DG-4.1 Activity Events For Graph Grades And Patches
12. DG-4.2 Dynamic Graph UI Panels
13. DG-4.3 Comparison Metric Export
14. DG-5.1 Dynamic Smoke Run
15. DG-5.1a Dynamic Feature Context Wiring
16. DG-5.1b Verifier Evidence Binding Canonicalization
17. DG-5.1c Verification Record Input Binding
18. DG-5.1d No-Submit Graph Agent Lease Recovery
19. DG-5.1e Hidden Oracle Check Command Canonicalization
20. DG-5.1f Gap Planner Mandatory Patch Discipline
21. DG-5.1g Planner Evidence Packet Compaction
22. DG-5.1h Gap Planner Codex Tool Exposure
23. DG-5.1i Dynamic Region Dependency Validation
24. DG-5.1j Gap Classification Output Binding
25. DG-5.1k Gap Analysis Output Port Compatibility
26. DG-5.1l Claude SDK Graph Runner Fallback
27. DG-5.1m Accepted Planner Patch Retry Guard
28. DG-5.1n Claude CLI Graph Patch Bridge
29. DG-5.1o Graph Runner Rate-Limit Classification
30. DG-5.1p Rejected Planner Patch Submit Guard
31. DG-5.1q Startup Recovery Active-Run Guard
32. DG-5.1r Horizon Template Evidence Edges
33. DG-5.1s Dynamic Worker Prompt Grounding
34. DG-5.1t Final Invariant Completion And Graph Read Health
35. DG-5.1u Planner Patch Check Command Validation
36. DG-5.1v Compact Graph Event Readback
37. DG-5.2 Full Comparison Re-run
38. DG-5.2a True Comparison Harness
39. DG-5.2b Hidden Oracle Isolation
40. DG-5.2c Gap Planner Final Evidence Safety
41. DG-5.2d Gap Planner Retry Obligation Signal

## First Action

Create `slice-DG-0.1-spec.md` from this plan and run it through the orchestrator
with `codex_server`. The planner/gap-finder for DG-0.1 should keep scope narrow:
record baselines and identify blockers only. Do not start planner-agent
implementation until the baseline is durable.
