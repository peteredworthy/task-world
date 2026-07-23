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
| `/routines` | Routine library | None audited | Current route, outside the requested run-projection detail. |
| `/agent-runners` | Runner availability/configuration | None audited | Current route, outside the requested run-projection detail. |
| `/agents` | Agent configuration | None audited | Current route, outside the requested run-projection detail. |
| `/history` | Placeholder | None | Explicitly says completed run history is "Coming soon"; no API is consumed. |
| `/repos` | Repository management | None audited | Current route, outside the requested run-projection detail. |
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
| `UIP-09` | Graph state, scheduler, leases | `GraphProjectionResponse`, `SchedulerViewResponse`, `GraphHealthResponse` | Direct counts/states from five independent graph queries. Their `event_count` values are not compared, and no consistency or age warning appears when snapshots differ. `GraphHealthResponse.status`, failed-node details, most blockers, patch decisions, pending gates, and review blockers are accepted by the type but only a small subset is rendered. | implemented projection; partial field consumption |
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
  query keys. A visible "Live" indicator can therefore coexist with indefinitely
  cached graph projection data after its initial fetch.
- Polling activity requests `payload_mode=full` but supplies no limit/after and
  ignores `ActivityResponse.has_more`. SSE starts from an empty client array,
  does not bootstrap historical events, claims `has_more: false`, and does not
  clear accumulated events when `runId` changes in the same hook instance.
  Reconnect uses the last in-memory event ID, but page reload loses it.
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

| Action surface | Command/client return | Current feedback | Missing result evidence |
|---|---|---|---|
| Create/start/pause/resume/cancel/delete run | `RunResponse` or void | Pending labels; errors on major run surfaces; create navigates/updates | Returned run status/identity is generally discarded in favor of invalidation. Pause/cancel/resume have no durable signal/event identity or explicit resulting-state confirmation. |
| Transition back / skip step | `RunResponse` | Confirmation for revert; pending; one implementation has mapped errors | Successful returned state is discarded. Expanded card revert has no catch/error state. Skip has only pending/error. |
| Recover/retry | `RecoverResponse` | Recovery panel shows a success toast; inspector chains recover then resume | Recovery panel ignores returned fields and asserts "Run is now paused." Inspector closes only after resume, but shows no durable recovery or resume record. |
| Approve/reject/force-accept task; approve step | `TransitionResponse` or unknown | Modal pending/error then closes; query invalidation | `success`, `new_status`, and `error` are not shown; no approver identity, durable event ID, next activity, or stale-race recovery. Step approval uses an implicit `approved_by: user`. Force accept uses a fixed comment. |
| Answer/skip clarification | `TransitionResponse` | Local validation, pending/error, then closes | Result status and durable response identity are not shown. "Skip remaining" is frontend eligibility logic. |
| Record graph approval/rejection | `RecordGraphDecisionResponse` includes graph position, events, and replacement decision view | Pending/error, modal closes, graph/run queries invalidated | All returned event identities, graph position, resulting decision view, next activity, and race outcome are discarded. The fallback consequence is invented in the UI. |
| Run tests | `TestRunResponse` then `TestRunResult` | Polling shows status, summary, logs, duration | Start failure is not rendered in `TestPanel`; the selected test run ID is local and lost on reload. |
| Dispatch agent test fix/conflict resolution | `AgentJobResponse` with `job_id/status` | Dispatch pending/error, then modal closes | Job identity/status is discarded; no job progress, resulting files/conflicts/tests, or recovery path is shown. "Agent is working" while POST is pending overstates job execution. |
| Resolve conflict | `ConflictResolutionResponse` | Pending/error and refetched conflict/readiness projections | Returned path/status/remaining count is discarded. Local `files` props can remain stale until query propagation; success identity is absent. |
| Prune preview/apply | Preview plus `PruneApplyResponse` containing commit SHA and event ID | Preview is explicit; apply pending/error then closes and invalidates | Commit SHA, event ID, affected counts, and resulting state are discarded after apply. |
| Back merge / undo / final merge | Typed merge responses | Back-merge and final-merge banners expose merge SHA; errors shown | Undo discards `reverted_commit/new_head`. Final merge shows only short SHA, not strategy/message. The separate run-detail merge does show backend message. |

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
connection reconnection.

Important unexercised or insufficiently exercised behavior:

- No focused current-product test was found for Dashboard URL restoration,
  filter/scroll continuity, graph node URL state, trace selection continuity,
  or review task-range continuity.
- No focused test was found for graph query failure/staleness, mismatched graph
  `event_count` snapshots, activity `has_more`, SSE historical bootstrap, or SSE
  run-ID reset.
- No focused test was found for mixed priced/unpriced model totals, trace
  attribution estimates, commit-message provenance badges, or task-range commit
  derivation.
- No review component tests were found for prune, conflict, agent-job,
  back-merge, or final-merge result-state feedback.
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
  `ui/src/hooks/useActivityStream.ts`.
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
evidence/telemetry audits before assigning canonical IDs. In particular, ask
the graph/evidence synthesis to adjudicate node-task identity and snapshot
versioning; ask action synthesis to compare every current UI command with its
durable result fields; and ask capability synthesis to classify the frontend
stuck, progress, cost, trace, and readiness claims. Do not admit the standalone
JTBD presentation concepts as current UI capabilities.
