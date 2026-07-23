# Current UI Projection Audit

## Purpose

Audit the current React application's routes, API projections, rendered claims,
actions, selection behavior, freshness/error/empty handling, frontend-only
inference, and current-versus-future boundaries. This report is a bounded Phase
1 evidence handoff. Keys beginning with `UIP-` are report-local provisional
keys, not canonical semantic IDs.

## Scope inspected

- Routing and composition: `ui/src/App.tsx`, `ui/src/main.tsx`,
  `ui/src/components/Layout.tsx`, and navigation/connection components.
- API and projection boundaries: `ui/src/api/client.ts`,
  `ui/src/api/reviewClient.ts`, `ui/src/types/`, and `ui/src/hooks/`.
- Current run surfaces: `ui/src/pages/Dashboard.tsx`, dashboard cards, run
  detail, task detail, activity, evidence digest, trace, graph, decision,
  file-state, branch, recovery, approval, clarification, and cost components.
- Current management surfaces: routine library, agent configurations, agent
  runner defaults, repository management, and managed environment files.
- Review surfaces: `ui/src/components/review/`, including task-range selection,
  diffs, commits, tests, conflicts, prune, back merge, and final merge.
- Relevant component, hook, API, and E2E tests under `ui/src/**/__tests__` and
  `ui/tests/`. The standalone JTBD presentation test was inspected only to
  identify whether proposed concepts leak into current product routes.

The audit follows the approved source-authority rule: TypeScript response types
establish accepted client shapes; tests establish exercised rendering; component
and hook code establishes current projection behavior. A label derived in React
is not treated as a backend fact merely because its inputs are typed.

## Key findings

### Current route inventory

| Route | Current projection | Selection encoded in URL | Loading/error/empty behavior |
|---|---|---|---|
| `/` | Dashboard run list, filters, expandable run/step/task summaries, task inspector | Only `search`; `routine` is a one-shot create-modal instruction and is removed | Initial spinner, run-list error, generic zero-result empty. Previous query data remains rendered during parameter changes without a stale marker. |
| `/runs/:runId` | Redirect | Preserves the original query string | Replaces history entry with `/runs/:runId/history`. |
| `/runs/:runId/history` | Run summary, evidence digest, actions, trace, activity/task history, optional graph drawer | Run ID and section; `action` plus `task_id` are one-shot modal hints and are removed after use | Run load has spinner/error. Most subordinate query errors are absent, collapsed to empty, or rendered only inside their own panel. |
| `/runs/:runId/changes` | Review/merge workspace | Run ID and section only | Individual file/diff/branch panels usually show loading/error/empty; several action jobs close on dispatch without durable-result feedback. |
| `/routines` | Routine names/descriptions/source/step and input counts/archive state; archive/unarchive and use controls | None | Initial spinner, route-level fetch error, no-routines and no-filter-result empties. Mutation pending/error/success is not rendered. |
| `/agent-runners` | Availability, runner metadata/config schema, browser-local defaults, server model-profile defaults | None | Initial spinner/error/empty; model-default fetch failure silently becomes empty fields; save has pending/saved/generic-error feedback. |
| `/agents` | Agent name, model profile, prompt preview/editor and CRUD/reset controls | None | Initial spinner/error/empty; create/update have pending/error; delete/reset omit complete failure feedback. |
| `/history` | Placeholder | None | Explicitly says completed run history is "Coming soon"; no API is consumed. |
| `/repos` | Repository name/path/default branch, run count, recent local branches; add/remove/create-run controls | `repo` is written when opening create-run from a card | Initial spinner/error/empty; expanded stats/branches have local loading/failure states. Add has pending/error; remove has pending but no rendered error. |
| `*` | Not-found page | Path itself | Static recovery link to dashboard. |

No current route exposes the standalone concepts exercised by
`ui/tests/e2e/jtbd-presentation.spec.ts`; that test loads
`outputs/jtbd-ui-directions/05-five-approach-interactive-comparison.html` via
`file://`. Its proposed interventions, causal spine, evidence workbench, mission
weave, and comparison state are design artifacts, not current React product
capabilities.

### Rendered claim trace

| Provisional key | Rendered claim or control | API/type source | Projection behavior and qualification | Status |
|---|---|---|---|---|
| `UIP-01` | Run identity, routine/repository, runner, lifecycle badge, dates | `RunResponse.id`, `routine_id`, `repo_name`, `agent_runner_type_display`, `status`, `started_at` | Direct fields, except routine display name is joined from `RoutineListResponse` or `RoutineDetail`, then falls back to embedded/name/ID. Dashboard source branch falls back to `repo_name`, which is not a branch fact. | implemented; partly tested |
| `UIP-02` | Step/task progress and grades | `RunResponse.steps[]`, `StepSummary`, `TaskSummary.grade_summary`, `attempts_summary` | Step percentage is computed as completed tasks divided by current task count. It is rendered as a progress bar even though graph/fan-out plans may grow. Attempt labels such as "Needs revision", "Failed", and "Building..." are inferred when `outcome` is null. | implemented frontend inference; tested in parts |
| `UIP-03` | "Needs input" and pending action counts | `TaskSummary.pending_action_type`, step approval fields, and `PendingAction[]` | Dashboard filtering and card badges recompute attention locally. The dashboard counts all task pending flags but only the effective current step approval; run detail uses the pending-actions endpoint count. These are separate projections and can disagree. There is no explicit positive "nothing needs you" state, only absence of badges or a generic no-runs result. | implemented; partial semantics |
| `UIP-04` | Run blocked/stuck | `RunResponse.status`, task `status`, `current_attempt`, `max_attempts`, `parent_task_id` | `isRunStuck` declares an active run blocked when a top-level failed task has exhausted attempts, then UI says the run "cannot make further progress." This is frontend inference, excludes failed children, and does not consult scheduler, signals, recoverability, or pending transitions. | inferred; unit/E2E exercised; label overstates inputs |
| `UIP-05` | Pause reason and agent error | `RunResponse.pause_reason`, `last_error`; `ActivityEvent.payload` | Pause labels are a frontend lookup. Agent error selects the last loaded `agent_error` activity event. Activity pagination/stream completeness is not shown, so "last" means last loaded, not proven latest durable event. | implemented inference; pause rendering tested |
| `UIP-06` | "Live" connection | WebSocket hook state, not a response field | `ConnectionIndicator` maps an open run WebSocket to "Live". It proves socket connectivity only. It does not prove REST query freshness, activity completeness, graph freshness, or backend health; those have separate paths. | implemented; tested routing/reconnect; label semantically broad |
| `UIP-07` | Backend connection failure | `/health` response success/failure | Global banner distinguishes fetch failure from HTTP error and polls every 10 seconds. It has no last-success time, age, or restored-at annotation and can be dismissed while still failing. | implemented; no freshness contract |
| `UIP-08` | Run Evidence Digest | `RunEvidenceDigestResponse`: status, mode, blockers, scheduler counts, representative nodes, metrics, `generated_at` | Values are direct backend digest fields, but `generated_at` is never rendered. "No blockers reported" correctly refers to an empty digest list only in wording, while the surrounding "Run Evidence Digest" can still be read as comprehensive. Representative nodes are bounded but the UI does not show truncation/max-node coverage. | implemented; component exercised; freshness/coverage hidden |
| `UIP-09` | Graph state, scheduler, leases | `GraphProjectionResponse`, `SchedulerViewResponse`, `GraphHealthResponse` | `GraphPanel` issues six independent projection queries: projection, scheduler, health, decisions, file-state, and graph events. Selecting a node enables a seventh node-detail query. Their `event_count` values are not compared, and no consistency or age warning appears when snapshots differ. `GraphHealthResponse.status`, failed-node details, most blockers, patch decisions, pending gates, and review blockers are accepted by the type but only a small subset is rendered. | implemented projection; partial field consumption |
| `UIP-10` | Graph activity totals and recent rows | `ActivityResponse.events[]`, not `GraphEventResponse[]` | Accepted/rejected patch, verifier, and blocker totals are counted over the currently loaded activity array. Lists are sliced to the latest eight and then labeled with the sliced count. `has_more` is ignored. Labels omit "loaded" or "recent," so they can overstate totals. | frontend aggregation; fixture tested |
| `UIP-11` | Task-to-graph-node association and "live activity" | `GraphEventResponse.payload` plus `ActivityEvent.payload` plus `RunResponse.steps` | Run detail scans `node_created`, takes the first worker/verifier node for each `task_id` or `task_region_id`, then joins task cards and agent output. Graph panel separately joins each node to the latest loaded `agent_output` line through a set of candidate task keys. Multiple attempts/nodes can collapse to one node; string equality is the only relation proof. | distributed frontend join; inferred; fixture tested |
| `UIP-12` | Graph decision prompt/consequence and action | `DecisionViewResponse.pending_gates[]`; `RecordGraphDecisionResponse` | Prompt and supplied `consequence_summary` are direct. When consequence is absent, UI invents a generic approval/rejection consequence. Actor identity and role are hard-coded as `human-operator`/`operator`, not selected or authenticated UI state. | current command surface with inferred fallback and actor assumption |
| `UIP-13` | "Review readiness" / "No merge blockers" in graph drawer | `DecisionViewResponse.review.ready/blockers` | This is graph decision-view review state, distinct from review API `MergeReadiness`. Calling an empty graph blocker array "No merge blockers" overstates the local projection and can conflict with branch/tests/conflict gates. | implemented; label conflict |
| `UIP-14` | Node inputs, outputs, file-state, callbacks, prompt packet | `NodeDetailResponse` | Direct fields, but output/file/prompt records are untyped `Record<string, unknown>` and rendered through key probing. A `patch_bundle_id` becomes a link to the run changes route without preserving node/record/file selection. | implemented; fixture tested; lineage lost on navigation |
| `UIP-15` | File-state classifications/verdicts | `FileStateReportResponse` | Direct boundary/path/gatekeeper fields. The UI shows record/snapshot/node identities, classifications, rules/reasons, verdict rationale, and diff summary, but no report age or event-position consistency with the other graph views. | implemented; fixture tested |
| `UIP-16` | Task attempt evidence | `TaskDetailResponse`, `AttemptSchema`, `AgentLogsResponse`, `PromptResponse`, clarification history | Checklist, snapshots, prompts, verifier feedback, auto-verify payloads, output, and action log are joined by runtime task ID and attempt number. Missing output/prompt states are explicit in several panels. Task detail query failure is often rendered as no body rather than an error. | implemented distributed join; uneven error handling |
| `UIP-17` | Run Trace token pressure/tool attribution | `RunTraceResponse`, `ActionLogEntry.metrics`, tool arguments/results | Sorting and display are frontend logic. "Request charged" divides one request metric among associated tool calls; "Call delta" estimates text at four characters/token; "Attempt context" repeats accumulated context and substitutes estimates. Blocks mark estimates in hover text, but the headline "displayed tokens" mixes measured and estimated attribution. | frontend-only inference; no focused tests found |
| `UIP-18` | Run and model cost | `RunResponse` totals, `ModelTokenUsage`, `estimated_cost_usd`, `cost_disclaimer`, `rate_missing` | Per-model rows preserve unknown rates. However, if some models are unpriced, the footer sums priced rows and labels the partial sum "Total" unless every row is unknown. Legacy cards hard-code $3/M input and $15/M output when `estimated_cost_usd` is null. The card labels this "Est. Cost," but no rate source/date or unpriced share is shown. | implemented plus frontend estimates; mixed-price total overstates coverage |
| `UIP-19` | "Total Tokens" | aggregate run token fields | Dashboard sums read + write + cache and labels the result total. This is a frontend arithmetic projection; the type does not state whether cache is disjoint from input, so double-counting cannot be excluded from UI evidence alone. | inferred; UI test asserts arithmetic |
| `UIP-20` | Review task range and changed files | Task `AttemptSchema.start_commit/end_commit`, review diff files/diff responses | UI fetches every task detail, chooses earliest non-null start and latest non-null end, constructs `start..end`, and sends it as free-form `ref` with scope `task`. This is a frontend lineage derivation across revision attempts, not an API-provided task-range identity. | implemented frontend derivation; no focused test found |
| `UIP-21` | Commit badges "prune", "agent", "back-merge" | `CommitEntry.message` | Badges are regex/string inference from commit message text, not typed provenance. | frontend inference; untested |
| `UIP-22` | Tests and merge readiness | `TestRunResponse`, `TestRunResult`, `MergeReadiness` | Test result polling and status/summary/log display are direct. Merge button eligibility uses backend `ready` and gate statuses. The UI does not display query errors for test-result or merge-readiness fetches; readiness failure defaults to disabled with no reason if no gate data exists. | implemented; loading/status components present; error gap |
| `UIP-23` | Managed environment files and snapshots | `EnvFile`, `EnvSnapshot`, `EnvDefaultTarget` | `EnvFilesPanel` renders `EnvFile.path` and `masked_value`; `key` is used only in the React list key. It renders snapshot `timestamp` and `agent`, uses snapshot `id` in confirmation/dialog text, does not render snapshot `files`, and uses `target_path` only to prefill copy-back. Current/snapshot loading, error, and empty states are explicit; default-target failure is silent. | implemented; render-only test covers path/snapshot/revert control |
| `UIP-24` | Routine library | `RoutineSummary`, `RoutineListResponse` | Renders `id` as selection identity, `name`, `description`, `source`, `step_count`, `input_count`, and `is_archived`; filtering/group counts are frontend derivations. `ArchiveRoutineResponse` is never rendered. | implemented; selection integration tested; mutation states untested |
| `UIP-25` | Agent management | `Agent`, create/update requests | Cards render `name`, `model_profile`, and truncated `system_prompt`; editing consumes those fields and presence of `default_prompt`. `id` addresses writes. `created_at`/`updated_at` are not rendered. Returned `Agent` records from create/update/reset are discarded before list invalidation. | implemented; CRUD/reset dispatch tested with mocked client |
| `UIP-26` | Agent runner management | `AgentRunnerOption`, `AgentConfigField`, `AgentRunnerModelDefaults` | Renders title/name, availability, description/detail/install hint, non-secret config-schema metadata/defaults/options, and model-profile defaults. Quota is not rendered on this route. Model/restriction/full-config defaults are browser-local storage, while model-profile defaults are server GET/PUT state; load errors are suppressed. | implemented; server model-default feedback tested |
| `UIP-27` | Repository management | `RepoResponse`, `RepoStatsResponse`, `BranchesListResponse` | Renders repository `name`, `path`, `default_branch`, stats `run_count`, and up to five local branch `name`/short `commit`; uses `total` for the remainder count. `is_remote` and `truncated` are not rendered. Add returns `RepoResponse`, but the UI discards it and refetches. | implemented; no focused route-action test found |
| `UIP-28` | Run branch status | `BranchStatusResponse` | `BranchStatusPanel` renders `source_branch -> run_branch`, `behind_count`, and `ahead_count`. It derives one local conflict state as `has_conflicts || !can_merge_cleanly`; that derived state shows the conflict warning and disables Pull upstream changes. `predicted_conflict_count` and `merge_readiness` are not rendered. Branch identity is selected only by the route's `runId`; there is no local or URL source/run-branch selector. The query polls every 30 seconds and has explicit loading, error, and retry states. | implemented direct fields plus derived gate; field rendering tested |

### Selection, URL, and continuity

- The durable canonical selection is only the run ID in the path and the
  `history`/`changes` section. Dashboard search is URL-backed.
- Dashboard status, project, and recency filters; expanded run; inspector task;
  scroll position; and result ranking are local component state and reset on
  navigation or reload.
- Pending-action links encode `action` and `task_id`, but run detail consumes
  and deletes them. They cannot be bookmarked as a stable selected decision.
  If the pending action has already changed, the requested identity silently
  fails or falls back to a direct pending-clarification lookup.
- Graph drawer open state and node identity are local. Closing/reloading loses
  the node, event, gate, file-state, and prompt context.
- Run Trace attempt, message/tool call, accounting mode, and zoom are local.
- Review task range, selected file, commit, diff mode, test run, conflict file,
  and panel expansion are local. The History panel's `historyScope` and
  `selectedCommitSha` do not feed `sharedDiffSelection` or `DiffPanel`, so
  choosing a commit changes only the History panel styling and does not change
  the displayed diff.
- Branch status has no independent selection: `runId` chooses the response, and
  the rendered source/run branch names cannot be changed or URL-addressed from
  `BranchStatusPanel`.
- A graph output record link navigates to `/changes` without the selected node,
  record, patch bundle, task range, or file. Cross-projection context is lost.
- There is no active comparison target in the current React application.
- No code restores prior ranking, filters (except search), selected objects, or
  scroll position. The current UI therefore does not satisfy the scoped
  continuity demands for canonical selection, context preservation, or return
  restoration.

### Freshness, stale, error, and empty states

- React Query defaults to a 2-second stale time and three retries. Individual
  hooks override this inconsistently. Staleness is cache policy only; the UI
  almost never renders `isStale`, `isFetching`, `dataUpdatedAt`, or source age.
- Run list polling is 10 seconds with active rows and 60 seconds with terminal
  rows. Run detail polls every 10 seconds until terminal. Pending actions and
  task detail poll every 10 seconds. Branch status and merge readiness poll every
  30 seconds. Graph projections, scheduler, health, decisions, events,
  file-state, node detail, and trace do not poll.
- The run WebSocket invalidates run/task/activity/pending-action queries. Generic
  graph events fall through to run invalidation and do not invalidate graph
  query keys. A visible "Live" indicator can therefore coexist with graph data
  that receives no event- or interval-driven refresh until a React Query
  refetch/remount, explicit invalidation, or relevant mutation trigger occurs.
- Polling activity requests `payload_mode=full` but supplies no limit/after and
  ignores `ActivityResponse.has_more`. SSE starts with an empty client array,
  but the server bootstraps existing events because an absent `since_id` becomes
  `after=None` on its first paginated poll. The server reads at most 100 rows per
  poll and then continues from the last emitted ID. The client still hard-codes
  `has_more: false`, so it does not expose replay coverage or backlog state.
- SSE reconnect within one hook/run uses the last in-memory event ID. The cursor
  is not keyed/reset with `runId`, so switching runs in one mounted hook can send
  the prior run's ID and retain prior events. Reload loses both cursor and
  accumulated events, causing a fresh replay from the server. A disconnect
  during initial replay can reconnect after the last delivered ID, but the UI
  exposes neither replay-in-progress/completeness nor a durable cursor; server
  pages and disconnect timing are therefore invisible to the operator.
- `RunDetail` ignores the unified activity stream's loading/error/connection
  fields. A failed activity request/stream therefore commonly renders "No
  activity yet" rather than unavailable or stale evidence.
- Dashboard `keepPreviousData` preserves the prior run response when server-side
  status parameters change. Old rows remain visible during the fetch with no
  stale/loading annotation. Client recency uses the query's `dataUpdatedAt` as
  its clock, not a displayed audit time.
- Graph drawer returns `null` while the projection is missing. Projection load
  or failure gives no drawer spinner/error/retry. Failures of scheduler, health,
  decisions, events, and file-state silently omit those sections. Node detail
  alone has explicit loading/error text.
- Evidence digest, run trace, branch status, file list, and diff have useful
  explicit error/empty states. Digest `generated_at` and graph `event_count`
  consistency are not exposed as freshness.
- Empty labels such as "No pending human gates," "No appeals recorded," "No
  merge blockers," and "No activity yet" do not distinguish authoritative empty
  responses from omitted/failed subordinate queries in all compositions.

### Available actions and result-state feedback

This is a bounded inventory of API-writing controls reachable from current
`App.tsx` routes, plus the runner route's browser-local persistence controls.
Pure navigation, filters, expansion, selection, clipboard, and display settings
are excluded; unused exported client methods are not claimed as UI actions.

| Control/component | Request / response | Pending, error, success feedback | Retained or discarded result | Status | Exact source / test evidence |
|---|---|---|---|---|---|
| Validate YAML, `RoutineValidatorModal` | `POST /api/routines/validate` with `yaml_content` -> normalized `ValidationResult` | Validating label; validation/request errors and valid result render in modal | Validation result is retained only in modal state; no durable identity | implemented; local result | `ui/src/components/RoutineValidatorModal.tsx`; `ui/src/api/client.ts::validateRoutine`; `ui/src/components/__tests__/RoutineValidatorModal.test.tsx` |
| Create and optionally start run, `CreateRunModal` | `POST /api/runs` -> `RunResponse`; optional `POST /api/runs/{id}/start` -> `RunResponse` | Creating/starting disabled labels and errors; success closes/navigates | Created `id` is retained for start/navigation; the returned started run state is discarded after invalidation | implemented; partial result retention | `ui/src/components/dashboard/CreateRunModal.tsx`; `ui/src/hooks/useApi.ts::useCreateRun/useStartRun`; `ui/src/components/dashboard/__tests__/CreateRunModal.test.tsx` |
| Start/pause/cancel/delete, dashboard run controls | lifecycle POSTs -> `RunResponse`; delete -> void | Mutation-specific pending labels and mapped errors; success invalidates list | Lifecycle response status is discarded; no signal/event ID or explicit resulting-state receipt | implemented; incomplete result evidence | `ui/src/pages/Dashboard.tsx`; `ui/src/components/dashboard/RunCard.tsx`; `ui/src/hooks/useApi.ts`; `ui/tests/e2e/state-transitions.spec.ts` and run-card tests exercise wiring, not durable receipts |
| Pause/resume/cancel/skip/final Merge Back, `RunDetail` / `ResumeDialog` / manual gate | lifecycle/skip POSTs -> `RunResponse`; final `POST .../merge-back` -> `{merge_commit,strategy,message}` | Pending/error states; resume and final merge success close/show message; skip error is shown | Lifecycle/skip states are discarded after invalidation; detail final merge retains a transient backend message, not a durable command identity | implemented; mixed retention | `ui/src/components/dashboard/RunDetail.tsx`; `ui/src/components/run/ResumeDialog.tsx`; `ui/src/components/dashboard/__tests__/ManualGatePanel.test.tsx`; `ui/tests/e2e/state-transitions.spec.ts` |
| Pull upstream changes, `BranchStatusPanel` | `POST /api/runs/{id}/back-merge` via `useBackMerge` -> void | Button is disabled by derived conflicts or pending and says `Pulling...`; API error renders; success only invalidates run and branch-status queries | No success receipt, merge/commit/event identity, or returned state exists to retain | implemented; distinct upstream pull with no receipt | `ui/src/components/detail/BranchStatusPanel.tsx`; `ui/src/hooks/useApi.ts::useBackMerge`; `ui/src/api/client.ts::backMerge`; `ui/src/components/detail/__tests__/BranchStatusPanel.test.tsx` covers counts/conflict warning only, not dispatch or feedback |
| Transition back, `StepTimeline` and expanded `RunCard` | `POST .../transition-back` with target/reason -> `RunResponse` | Timeline has confirm/pending/mapped error; card control has confirm/pending but no catch/rendered error | Returned run is discarded after invalidation | implemented twice; uneven errors | `ui/src/components/dashboard/StepTimeline.tsx`; `ui/src/components/dashboard/RunCard.tsx`; `ui/src/hooks/useApi.ts::useTransitionBack`; `StepTimeline.test.tsx` tests display, not response retention |
| Recover/retry, `RecoveryPanel` and `InspectorPanel` | `POST .../recover` -> `RecoverResponse`; inspector then resume -> `RunResponse` | Panel pending/error and success toast; inspector pending/error and closes after chain | Both responses are discarded; toast asserts paused state without retaining returned evidence | implemented; inferred success copy | `ui/src/components/detail/RecoveryPanel.tsx`; `InspectorPanel.tsx`; `ui/src/hooks/useApi.ts::useRecoverRun`; no focused result-retention test found |
| Approve/reject task or approve step, approval dialogs/banners | approval/rejection POST -> `TransitionResponse`; step approval typed `unknown` | Pending/error then close/invalidate on success | `success/new_status/error` are discarded; no event ID/actor receipt; step actor is fixed as `user` | implemented; incomplete receipt | `ui/src/components/detail/ApprovalReviewDialog.tsx`; `ApprovalModal.tsx`; `StepApprovalBanner.tsx`; approval component tests and `state-transitions.spec.ts` exercise dispatch/rendering |
| Force accept task, `TaskDetailCard` / `InspectorPanel` | `POST .../force-accept` -> `TransitionResponse` | Confirmation/pending/error; closes or invalidates on success | Transition response discarded; fixed UI comment, no durable approver/action identity | implemented; incomplete receipt | `ui/src/components/detail/TaskDetailCard.tsx`; `InspectorPanel.tsx`; `ui/src/hooks/useApi.ts::useForceAcceptTask`; state-transition/component tests exercise wiring |
| Answer or skip clarification, `ClarificationModal` | `POST .../clarifications/{request}/respond` -> `TransitionResponse` | Local validation, pending/error, closes on success | Transition response discarded; request ID exists in request but no durable response receipt shown | implemented; incomplete receipt | `ui/src/components/detail/ClarificationModal.tsx`; `ui/src/hooks/useApi.ts::useRespondToClarification`; clarification modal tests and `state-transitions.spec.ts` |
| Approve/reject graph gate, `GraphDecisionModal` | `POST .../graph/decisions` -> `RecordGraphDecisionResponse` | Pending/error; success closes and invalidates graph/run queries | Returned graph position, emitted events, and replacement decision view are discarded | implemented; rich result discarded | `ui/src/components/GraphDecisionModal.tsx`; `ui/src/hooks/useApi.ts::useRecordGraphDecision`; `ui/src/components/__tests__/GraphPanel.decisions.test.tsx` verifies payload/focus, not receipt |
| Revert env snapshot, `EnvFilesPanel` | `POST .../env-files/revert` with duplicate `snapshot_id`/`revert_to` -> normalized `EnvSnapshot` | Revert buttons/dialog disable and label pending; no rendered mutation error; success closes via selected-snapshot reset | Returned snapshot, including files/timestamp/agent, is discarded; env files/snapshots invalidated; no success receipt | implemented; feedback gap | `ui/src/components/detail/EnvFilesPanel.tsx`; `ui/src/api/client.ts::revertEnvSnapshot`; `ui/src/hooks/useApi.ts::useRevertEnvSnapshot`; `EnvFilesPanel.test.tsx` only asserts table/control rendering |
| Copy env files back, `EnvFilesPanel` | `POST .../env-files/copy-back` with duplicate `target_path`/`target_dir` -> void | Required-path validation, pending label/disable, API error; success closes dialog | No result retained; env files invalidated. Selected snapshot ID is displayed but is not sent, so the control does not prove snapshot-specific copy-back | implemented; semantic/result gap | `ui/src/components/detail/EnvFilesPanel.tsx`; `ui/src/api/client.ts::copyBackEnvFiles`; `ui/src/hooks/useApi.ts::useCopyBackEnvFiles`; no copy-back behavior test found |
| Run tests, `ReviewMergeTab` / `TestPanel` | `POST /api/runs/{id}/review/test` -> `TestRunResponse`; poll `GET /api/runs/{id}/review/test/{testRunId}` every 2 seconds while status is `running` -> `TestRunResult` | Start button pending; result polling renders status/summary/logs/duration; start mutation error is not rendered | `test_run_id` is retained only in component state and lost on reload | implemented; local job continuity | `ui/src/components/review/ReviewMergeTab.tsx`; `TestPanel.tsx`; `ui/src/api/reviewClient.ts::runTests/getTestResult`; `ui/src/hooks/useReview.ts::useRunTests/useTestResult`; no focused action-result test found |
| Dispatch agent test fix / conflict resolution, respective modals | POST -> `AgentJobResponse {job_id,status}` | Dispatch pending/error; modal closes on accepted response | Job ID/status discarded; no progress/result/recovery projection | implemented; job receipt discarded | `ui/src/components/review/AgentFixTestsModal.tsx`; `AgentResolveConflictsModal.tsx`; `ui/src/hooks/useReview.ts`; no focused result-state tests found |
| Resolve conflict, `ConflictResolverDialog` | `POST .../review/conflicts/resolve` -> `ConflictResolutionResponse` | Confirmation/pending/error; success refetches conflict/readiness data and advances/closes | Returned path/status/remaining count discarded; parent file props may lag query propagation | implemented; result discarded | `ui/src/components/review/ConflictResolverDialog.tsx`; `ui/src/hooks/useReview.ts::useResolveConflict`; no focused result-state test found |
| Preview/apply prune, `PrunePreviewModal` | preview POST -> `PrunePreviewResponse`; apply POST -> `PruneApplyResponse` | Preview loading/error/content; apply pending/error; success closes and invalidates | Apply commit SHA, event ID, and affected counts discarded | implemented; rich result discarded | `ui/src/components/review/PrunePreviewModal.tsx`; `ui/src/hooks/useReview.ts::usePrunePreview/usePruneApply`; no focused action-result test found |
| Review-route back merge / undo / final merge, review modals/banner | Review API POSTs -> `BackMergeResponse`, `RevertBackMergeResponse`, `FinalMergeBackResponse` | Pending/errors; back/final merge show merge SHA; undo refreshes banner state | Back/final retain only transient short SHA; undo discards `reverted_commit/new_head`; strategy/message not retained in final receipt | implemented; partial receipt; distinct from detail Pull upstream changes | `ui/src/components/review/BackMergeModal.tsx`; `BackMergeBanner.tsx`; `MergeConfirmModal.tsx`; `ui/src/hooks/useReview.ts`; no focused result-retention tests found |
| Archive/unarchive routine, `RoutineCard` on `RoutineLibrary` | `POST /api/routines/{id}/archive|unarchive` -> `ArchiveRoutineResponse` | No pending disable/label, no rendered error, no success receipt; success invalidates list | Entire response (`id/source/is_archived`) discarded | implemented; no action feedback | `ui/src/pages/RoutineLibrary.tsx`; `ui/src/components/routines/RoutineCard.tsx`; `ui/src/hooks/useApi.ts::useArchiveRoutine/useUnarchiveRoutine`; no focused mutation test found |
| Create agent, `AgentEditor` | `POST /api/agents` with name/prompt/profile -> `Agent` | Saving disable/label and rendered error; success closes and invalidates list | Returned agent identity/timestamps discarded | implemented; dispatch tested | `ui/src/pages/Agents.tsx`; `ui/src/lib/agentApi.ts::createAgent`; `ui/src/pages/__tests__/Agents.test.tsx` verifies payload/close |
| Update agent, `AgentEditor` | `PUT /api/agents/{id}` -> `Agent` | Saving disable/label and rendered error; success closes and invalidates | Returned updated agent discarded | implemented; dispatch tested | `ui/src/pages/Agents.tsx`; `ui/src/lib/agentApi.ts::updateAgent`; `Agents.test.tsx` verifies PUT dispatch |
| Delete agent, `Agents` confirm dialog | `DELETE /api/agents/{id}` -> void | Confirmation only; dialog closes before request; no pending disable/error/success | No result; rejection is not caught/rendered | implemented; failure gap | `ui/src/pages/Agents.tsx`; `ui/src/lib/agentApi.ts::deleteAgent`; `Agents.test.tsx` verifies confirmation/dispatch/cancel, not failure |
| Reset agent prompt, `AgentEditor` | `POST /api/agents/{id}/reset-prompt` -> `Agent` | Resetting disable/label; no catch/rendered error; success closes editor and invalidates | Returned reset prompt/updated record discarded | implemented; failure/result gap | `ui/src/pages/Agents.tsx`; `ui/src/lib/agentApi.ts::resetAgentPrompt`; `Agents.test.tsx` verifies dispatch only |
| Save server model-profile defaults, `AgentRunnerCard` | `PUT /api/agent-runners/{type}/model-profile-defaults` -> `AgentRunnerModelDefaults` | Saving disable/label; transient `Saved`; generic `Failed to save` | Returned normalized mapping discarded; edited local React values remain | implemented; feedback tested | `ui/src/pages/AgentRunners.tsx`; `ui/src/api/client.ts::saveAgentRunnerModelDefaults`; `ui/src/pages/__tests__/AgentRunners.modelDefaults.test.tsx` covers payload/pending/success/error |
| Edit runner model/restrictions/full config, `AgentRunnerCard` | Browser-local storage writes, no HTTP response | No pending/error/success; updates immediately | Values retained in local storage by runner name; no server authority or validation receipt | implemented local-only; scope-qualified | `ui/src/pages/AgentRunners.tsx`; `ui/src/components/agentRunnerConfigUtils.ts`; model-default test mocks local helpers but does not test persistence failures |
| Add repository, `AddRepoModal` | `POST /api/repos` with URL or path -> `RepoResponse` | Submit spinner/disable and rendered API error; success invalidates list and closes | Returned name/path/default branch discarded | implemented; no focused route test found | `ui/src/pages/Repos.tsx::AddRepoModal`; `ui/src/api/client.ts::addRepo`; no `Repos` action test found |
| Remove repository, `Repos` confirm dialog | `DELETE /api/repos/{name}` -> void | Confirmation and pending label; no catch/rendered error; finally closes even on failure | No result retained; failure can leave stale list with no explanation | implemented; failure gap | `ui/src/pages/Repos.tsx`; `ui/src/api/client.ts::removeRepo`; no focused route test found |

No current UI control implements "ignore/keep watching" as a recorded action.
Absence of interaction is the only equivalent, so `decisions.ignore-watch` is a
current UI gap rather than an executable action.

### UI labels that exceed their evidence

- `Live`: WebSocket connected, not proof that REST, graph, activity, or evidence
  projections are current.
- `Run blocked` / `cannot make further progress`: a local heuristic over one
  class of failed top-level tasks.
- `Recovery agent diagnosing issue...`: inferred from task status
  `recovering`, not a current runner heartbeat or diagnostic event.
- `No merge blockers` in graph Decisions: only an empty
  `DecisionViewResponse.review.blockers`, not full merge readiness.
- `Review readiness`: graph decision review state and review API merge
  readiness use similar language for different contracts.
- Graph activity counts (`Patches accepted`, `Activity blockers`, verifier
  pass/fail): counts over loaded activity, not complete durable totals.
- `Total Tokens`: frontend sum with no type-level proof that cache is disjoint.
- Model `Total` cost with mixed `rate_missing` rows: priced subtotal presented
  as total.
- Commit provenance badges: inferred from commit-message text.
- `All conflicts resolved`: computed from currently supplied conflict files;
  query completeness/freshness is not annotated.
- Graph decision fallback consequence and the claim that approval "allows
  dependent graph work to continue": frontend prose when the API omits a
  consequence summary.

### Current/future boundary

- Current product UI exposes only implemented API clients and commands listed
  above. It does not route to the five JTBD concept workspaces or expose their
  proposed corrective intervention as a product command.
- `/history` is an explicit, honest future placeholder.
- The standalone JTBD presentation repeatedly labels interventions as
  "Proposed capability" and its local authorization outcome says no backend
  command was sent. This boundary is tested and does not leak into `App.tsx`.
- Current React labels do still create semantic overreach through inference
  (`Live`, blockers, totals, generic graph consequences), but this is
  current-evidence overstatement rather than a routed future feature.

### Test evidence and gaps

Exercised behavior includes run-card fields/actions, step badges and revert
dialog, stuck-run inference, pause labels, pending-action WebSocket invalidation
and modal auto-open, evidence digest direct/legacy-empty rendering, graph
activity joins, graph decision payload/focus behavior, node/file-state rendering,
task attempt details, cost rows/legacy fallback, activity grouping, and
connection reconnection. Server integration tests establish that SSE without
`since_id` emits existing events, `since_id` resumes exclusively, filtering and
enrichment work, and disconnect does not make the run inaccessible. Agent CRUD
dispatch and runner model-default pending/success/error states are component
tested; the env panel test only establishes field/control rendering.
`BranchStatusPanel.test.tsx` establishes ahead/behind rendering and the warning
when supplied fields derive a conflict state; it does not exercise Pull upstream
changes, pending/error feedback, or invalidation.

Important unexercised or insufficiently exercised behavior:

- No focused current-product test was found for Dashboard URL restoration,
  filter/scroll continuity, graph node URL state, trace selection continuity,
  or review task-range continuity.
- No focused browser-hook test was found for graph query failure/staleness,
  mismatched graph `event_count` snapshots, activity `has_more`, SSE run-ID
  reset, reload cursor loss, or disconnect during a multi-page initial replay.
- No focused test was found for mixed priced/unpriced model totals, trace
  attribution estimates, commit-message provenance badges, or task-range commit
  derivation.
- No review component tests were found for prune, conflict, agent-job,
  back-merge, or final-merge result-state feedback.
- No focused route-action tests were found for routine archive/unarchive,
  repository add/remove, env revert/copy-back result feedback, or browser-local
  runner configuration persistence. Agent delete/reset failure paths are also
  untested.
- Graph tests seed React Query with mutually consistent fixtures; they establish
  rendering, not live consistency among independent endpoints.
- State-transition E2E tests intercept all API/WS calls and establish UI wiring,
  not backend command reachability or durable action evidence.
- The large JTBD presentation E2E suite validates a standalone design artifact;
  it is not evidence that those entities, derived claims, or actions exist in
  the current React application.

## Important uncertainties

- TypeScript types do not establish whether every endpoint is reachable in all
  run modes, whether activity responses are bounded by a server default, or
  whether graph endpoint `event_count` values are intended as a common version.
- The audit cannot prove from UI code whether aggregate cache token fields are
  disjoint from input tokens, whether `estimated_cost_usd` includes all unpriced
  usage, or whether mixed model `cost_usd` values are guaranteed complete.
- `PendingAction` lacks action/record identity beyond task/step and type, so the
  UI cannot distinguish repeated approvals or clarifications for the same task
  without inspecting nested clarification request IDs.
- Node/task identity uses runtime IDs, config IDs, and graph region-like strings.
  The frontend's equality joins do not prove equivalence among them.
- Review `scope` and `ref` are typed as free strings in clients. The UI's
  `start_commit..end_commit` meaning depends on backend review semantics not
  established by the frontend boundary alone.

## Conflicts found

- `UIP-CON-01`: `ConnectionIndicator` says `Live` from WebSocket connectivity,
  while graph queries are neither polled nor invalidated by ordinary graph
  events. Current UI can simultaneously assert live and show stale graph data.
- `UIP-CON-02`: graph Decisions can say `No merge blockers` while the separate
  review `MergeReadiness` contract can be blocked by tests, conflicts, or branch
  gates. The labels describe different evidence scopes without qualification.
- `UIP-CON-03`: cost rows explicitly mark missing rates, but a mixed-rate footer
  labels the sum of known rows `Total`; this conflicts with the honesty rule that
  unpriced usage must not become zero.
- `UIP-CON-04`: review History exposes `Selected Commit`, but that selection is
  not connected to the shared diff query. The control promises a projection
  change that does not occur.
- `UIP-CON-05`: source demands require explicit freshness and positive empty
  attention state; current run surfaces hide source age and mostly represent
  "nothing needs you" through absence.
- `UIP-CON-06`: source honesty forbids fixed completion percentages for growing
  plans, while expanded run cards render completed/current-task-count as a
  percentage progress bar.

## Decisions required

- Decide whether `Live` will be narrowed to socket connectivity or upgraded to a
  versioned freshness contract spanning the visible projections.
- Decide which backend/version identity is canonical for run, task, graph node,
  attempt, activity record, decision, and review selection across routes.
- Decide whether graph review readiness and merge readiness remain distinct
  named concepts; if so, labels must expose their evidence scope.
- Decide whether frontend task-range, stuck-run, token, cost, and trace
  calculations are admitted derivations with explicit unknown/freshness rules or
  merely diagnostic estimates requiring stronger labels.
- Decide the minimum action-result contract to retain and render: accepted or
  rejected, durable identity, resulting state, next activity, and stale-race
  recovery.
- Decide whether the current product needs an explicit recorded watch/ignore
  action; none exists now.

## Artifact paths

- `research/ui-foundation/agent-reports/06-ui-projections.md`
- `.superpowers/sdd/task-8-audit-report.md`

No canonical catalog, capability, action, product, or source file was modified.

## Evidence pointers

- Routes and URL behavior: `ui/src/App.tsx` (`RunDetailRedirect`, `App`),
  `ui/src/pages/Dashboard.tsx` (`Dashboard`), and
  `ui/src/components/dashboard/RunDetail.tsx` (`RunDetailInner`).
- API/type boundaries: `ui/src/api/client.ts` (`api`, `fetchApi`,
  `normalizeRunTrace`), `ui/src/api/reviewClient.ts`,
  `ui/src/types/runs.ts`, `ui/src/types/tasks.ts`, `ui/src/types/activity.ts`,
  `ui/src/types/trace.ts`, and `ui/src/types/review.ts`.
- Freshness and invalidation: `ui/src/main.tsx`, `ui/src/hooks/useApi.ts`,
  `ui/src/hooks/useWebSocket.ts`, `ui/src/hooks/useActivitySSE.ts`, and
  `ui/src/hooks/useActivityStream.ts`; server replay behavior is established by
  `src/orchestrator/api/routers/runs.py::stream_activity` and
  `tests/integration/test_api_activity.py::test_sse_stream_sends_events`,
  `::test_sse_stream_since_id_resumption`, and `::test_sse_stream_client_disconnect`.
- Dashboard/detail inference: `ui/src/components/dashboard/RunCard.tsx`,
  `ui/src/components/dashboard/RunEvidenceDigest.tsx`,
  `ui/src/lib/runStuck.ts`, `ui/src/components/detail/ActivityFeed.tsx`,
  `ui/src/components/detail/TaskDetailCard.tsx`, and
  `ui/src/components/detail/InspectorPanel.tsx`.
- Graph/evidence joins: `ui/src/components/GraphPanel.tsx`,
  `ui/src/components/GraphDecisionModal.tsx`,
  `ui/src/components/NodeDetailPanel.tsx`,
  `ui/src/components/FileStateViewer.tsx`, and
  `ui/src/components/SchedulerView.tsx`.
- Managed env projection/actions: `ui/src/components/detail/EnvFilesPanel.tsx`,
  `ui/src/types/envFiles.ts`, `ui/src/api/client.ts::getEnvFiles` through
  `copyBackEnvFiles`, and `ui/src/components/detail/__tests__/EnvFilesPanel.test.tsx`.
- Branch status and upstream pull: `ui/src/components/detail/BranchStatusPanel.tsx`,
  `ui/src/types/branches.ts`, `ui/src/hooks/useApi.ts::useBranchStatus/useBackMerge`,
  `ui/src/api/client.ts::getBranchStatus/backMerge`, and
  `ui/src/components/detail/__tests__/BranchStatusPanel.test.tsx`.
- Management routes/actions: `ui/src/pages/RoutineLibrary.tsx`,
  `ui/src/components/routines/RoutineCard.tsx`, `ui/src/pages/Agents.tsx`,
  `ui/src/lib/agentApi.ts`, `ui/src/pages/AgentRunners.tsx`, and
  `ui/src/pages/Repos.tsx`; focused tests are `Agents.test.tsx` and
  `AgentRunners.modelDefaults.test.tsx` under `ui/src/pages/__tests__/`.
- Telemetry inference: `ui/src/components/detail/RunTraceExplorer.tsx` and
  `ui/src/components/detail/ModelCostBreakdown.tsx`.
- Review selection/actions: `ui/src/components/review/ReviewMergeTab.tsx`,
  `TaskRangeSelectorBar.tsx`, `HistoryPanel.tsx`, `DiffPanel.tsx`,
  `MergeReadinessBar.tsx`, and the review action modals.
- Exercised behavior: graph decision/activity/hidden-diagnostics tests, run
  evidence digest tests, run-card/task-detail/model-cost tests, WebSocket tests,
  and `ui/tests/e2e/state-transitions.spec.ts`.
- Future boundary evidence: `ui/tests/e2e/jtbd-presentation.spec.ts` and the
  absence of corresponding routes in `ui/src/App.tsx`.

## Recommended next delegation

Normalize these findings with the domain, graph, workflow, API/action, and
evidence/telemetry audits before assigning canonical IDs. Handoff the corrected
SSE distinction explicitly: server replay exists, while client cursor scope,
reload persistence, hard-coded `has_more`, suppressed errors, and replay
completeness remain UI gaps. Treat GraphPanel as six base projection queries
plus selected-node detail. Ask action synthesis to use the per-control table,
including env and management routes, when comparing request/result contracts;
keep detail-page Pull upstream changes distinct from run-detail final
`merge-back` and the review-route back-merge family, and use the singular review
test endpoints recorded above. Do not generalize beyond its stated routed
API-writing scope. Ask capability
synthesis to classify the frontend stuck, progress, cost, trace, and readiness
claims. Do not admit the standalone JTBD presentation concepts as current UI
capabilities.
