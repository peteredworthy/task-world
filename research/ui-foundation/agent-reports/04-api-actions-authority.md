# API, Actions, And Authority Audit

## Purpose

Audit the reachable REST, CLI, public orchestrator MCP, and per-execution graph
MCP surfaces as transports over domain capabilities. This report inventories
implemented command contracts, request validation, actors, enforced authority,
domain eligibility, durable effects, failures, races, reversibility, and audit
evidence. It uses scoped provisional keys only; it does not allocate canonical
IDs or design absent commands.

Status labels mean:

- **implemented**: reachable wiring and implementation were inspected.
- **tested**: repository tests exercise the stated behavior.
- **documented-only**: a source describes the behavior without sufficient
  reachability evidence.
- **inferred**: the conclusion follows from implementation but is not directly
  asserted or exercised.
- **unclear**: inspected evidence does not settle the proposition.

## Scope inspected

- Approved boundary and action rules:
  `docs/superpowers/specs/2026-07-23-ui-foundation-phase-0-3-design.md`, especially
  `Source Authority`, `Reality Investigations`, and `Action Contracts`.
- Closed demands owned by `api-actions-authority` in
  `research/ui-foundation/catalog/scope.yaml`.
- Decision demands in `docs/jtbd/jobs.md` and
  `docs/jtbd/decision-information.md`.
- REST assembly, authentication, schemas, errors, and mutable routers under
  `src/orchestrator/api/`.
- CLI commands under `src/orchestrator/cli/`.
- Public orchestrator MCP definitions and dispatch in
  `src/orchestrator/api/mcp/`, MCP scoping in
  `src/orchestrator/runners/mcp_scope.py`, and per-execution graph MCP tools in
  `src/orchestrator/graph_runtime/graph_mcp_tools.py`.
- Called workflow methods where needed to establish durable effect and evidence,
  principally `src/orchestrator/workflow/service.py`.
- API, CLI, MCP, graph-command, clarification, approval, recovery, review, and
  auth tests under `tests/integration/`, plus focused unit tests.

Read-only projections were inventoried where they provide action context or
confirmation. This report does not treat REST, CLI, and MCP as separate domain
capabilities merely because their envelopes differ.

## Key findings

### Authority model

| Provisional key | Status | Finding |
|---|---|---|
| `api-authn-jwt` | implemented, tested | All `/api/*` routers share one optional Bearer JWT dependency in `api.app.create_app`; `/mcp`, `/mcp-scoped`, and `/mcp-graph` use equivalent middleware. Auth is disabled by default. When enabled, possession of any valid token grants every read and mutation. `tests/integration/test_api_auth.py` exercises missing, invalid, and valid tokens. |
| `api-authz-roles` | implemented as absent, tested indirectly | No endpoint checks JWT subject, role, scope, ownership, run membership, or action-specific permission. `auth.validate_token` returns claims, but router dependencies discard them. The system has authentication when enabled, not authorization. |
| `api-operator-assumption` | implemented | REST graph patch, decision, scheduling-after-decision, and requeue endpoints construct `Actor(kind=human, id="human-operator", role="operator")`; this is an endpoint assumption, not an authenticated product role. |
| `api-identity-attribution` | implemented, tested, conflicting | Legacy clarification endpoints use fixed identity `"user"`; task approve/reject/force-accept use `deps.get_current_user`; step approval accepts caller-supplied `approved_by`; graph decisions accept caller-supplied `decider`; requeue records fixed `human-operator`. These are incompatible attribution mechanisms and none is bound to JWT claims. |
| `mcp-tool-scope` | implemented, tested | `/mcp-scoped/{tool-set}` limits registered tool names, and runner setup derives a phase/task allowlist. This is capability exposure, not actor authorization. The unscoped `/mcp` server registers all 11 tools regardless of phase; domain state checks reject some phase-invalid calls. |
| `graph-mcp-execution-scope` | implemented, tested | `/mcp-graph/{token}` uses an unguessable, live-execution token and closures bound to one execution. Planner/builder instances omit `graph_grade`; verifier instances include it. Token possession and closure binding constrain execution, while outer JWT auth remains global and optional. |

The source demand `jobs.J6.authority` is therefore only partly supported. The
graph decision projection can show `requested_authority`, node detail can show
resource claims and allowed actions, and command validation enforces some graph
actor/domain rules. There is no implemented operator-role policy or per-action
authorization. An assumed operator must not be represented downstream as an
enforced permission.

### Transport and capability inventory

#### Run and lifecycle capability

| Provisional key | Surface and request | Domain eligibility and effect | Failure, race, evidence, reversibility |
|---|---|---|---|
| `action-run-create` | REST `POST /api/runs` with `CreateRunRequest`; CLI `runs create` with Click options and key/value maps. | Creates a draft run. REST requires exactly one routine source, selectable runner types, valid execution/merge modes, runner config fields, and selected Codex model. CLI discovers local routines and persists directly. | REST returns 422/404/runner errors. CLI validation is narrower and bypasses API request validation. Durable run row and creation events are available. Deletion is separate and status-limited. |
| `action-run-start` | REST `POST /runs/{id}/start`; CLI `runs start`. | REST enqueues `RUN_START` and returns 202 before transition. CLI calls `WorkflowService.apply_start_run` directly and commits synchronously. | **Transport divergence:** the CLI bypasses the lifecycle signal queue. REST response is command acceptance/current read model, not proof of resulting active state. Domain transition rejects illegal state. No request source version. |
| `action-run-pause` | REST and CLI wrapper. | Cancels the active executor first, then enqueues pause through `WorkflowService.pause_run`; rejects `STOPPING`. | 202 acceptance precedes consumer-applied state. Cancellation-before-enqueue creates an observable interval. Child cancellation helper is currently a no-op. Resume is the operational inverse, but work lost during process cancellation is not reversed. |
| `action-run-resume` | REST `ResumeRunRequest` optionally selects a new runner/config and `continue` or `reset_worktree`; CLI exposes runner/config but not strategy. | Requires resumable domain state and enqueues resume. A retired runner requires explicit replacement. | 409 for stopping/invalid transition. Reset-worktree may discard file state and is not itself undoable through this command. No expected run version. |
| `action-run-cancel` | REST and CLI wrapper, no body/reason from these surfaces. | Rejects `STOPPING`, cancels executors, enqueues cancellation; graph mode additionally drives graph cancellation to terminal. | Terminal/destructive. No confirmation contract at API level, no client source version, and no direct uncancel. Recovery is a different capability and does not make cancellation reversible. Graph and legacy timing differ. |
| `action-run-recover` | REST `RecoverRequest`: target task, additional attempts, optional runner, checklist preservation, guidance, branch reset. | Only failed or paused legacy runs; rewinds target/downstream tasks, optionally resets branch, adds attempt budget, records guidance, and leaves run paused as `recovered`. | 404/409 for missing task, illegal state, or worktree reset. Emits `run_step_backward`, `task_reverted`, task/attempt snapshots, and run status evidence. This is a compensating rewind, not restoration of all external effects. |
| `action-run-delete` | REST `DELETE /runs/{id}`. | Deletes non-active/non-paused runs, with one narrow startup-orphan exception. | 409 otherwise. Destructive and no undo. No action-specific authorization or expected version. |
| `action-transition-back` | REST `BackwardTransitionRequest(target_step_index >= 0, reason?)`. | Rewinds to an earlier legacy step and resets skipped tasks according to workflow service. | Domain errors; no expected version. Durable workflow events provide evidence. Not a general undo because produced files/external effects are not promised to revert. |

CLI `pause`, `resume`, `cancel`, `status`, `branch-status`, `back-merge`, and
`merge-back` are REST wrappers, but they do not accept a Bearer token. `runs
watch` likewise does not add the WebSocket `?token=` required when auth is
enabled. These commands work in the default auth-disabled deployment and fail
against an auth-enabled server unless transport behavior is changed outside the
implemented CLI.

#### Legacy task, approval, clarification, and retry capability

| Provisional key | Surface and request | Domain eligibility and durable effect | Failure, race, evidence, reversibility |
|---|---|---|---|
| `action-task-phase` | REST start, submit, complete-verification; checklist `PATCH`; grade `PUT`. Public MCP get/update/submit/grade maps to the same workflow service family. | Legacy-only. Task state, checklist status, gate checks, and grades control progression. REST submit/check-verification enqueue signals after synchronous checks. MCP submit calls `submit_for_verification` directly. | 404/409/422 for identity, transition, gate, worktree commit, or validation errors. **Transport divergence:** REST signal application and MCP direct transition have different acceptance/result timing and race behavior. Workflow events and attempt snapshots are durable evidence. |
| `action-task-approval` | REST task `approve`, `reject`, `force-accept`; bodies contain optional comment/reason only. | Approve completes a pending task; reject returns it to building; force-accept bypasses grades from failed/building/verifying and may complete the run. | State transition checks provide domain eligibility. Fixed/injected `user` identity is not role authorization. ApprovalDecision events are durable. Force-accept has no undo and is high-consequence. |
| `action-step-approval` | REST step `approve` with caller-supplied `approved_by`; CLI interactive `runs approve`. | Current actionable step must have a human approval gate. Records `StepHumanApprovalRecorded`, may enqueue resume, and may spawn an executor. Repeated approval is explicitly tested as last-write-wins. | 404/409 for absent/non-current/non-gated step. No expected version. **Tested contradiction:** on legacy runs, answering "no" in CLI still posts to the approve-only endpoint; `tests/integration/test_cli_approve.py::test_legacy_run_keeps_step_approval_no_answer_behavior` locks in this behavior. There is no legacy step-deny/defer command. |
| `action-step-skip` | REST step `skip`, no body/reason. | Only a run paused at `manual_gate`, only current actionable step. Marks step skipped/completed and resumes or progresses to another gate. | 409 for stale/wrong context. Emits `StepSkipped` and status/progression events. No undo endpoint; transition-back is not documented as an exact inverse. |
| `action-clarification-create` | REST `CreateClarificationRequest`; public MCP `orchestrator_request_clarification`. | Builder/verifier creates typed questions, transitions task to pending user action, pauses the run, and records request. REST requires typed options by question type; MCP additionally rejects finite-choice prose disguised as free text. | Schema/service transition failures. Request ID, timestamps, questions, pending action, and event are evidence. MCP returns an explicit stop instruction. |
| `action-clarification-respond` | REST response with answer variants plus top-level skip fields; CLI interactive wrapper. | Records answers, appends a Q&A artifact, compresses decisions into run config, clears pending state, resumes only clarification-paused runs, and can respawn the agent. | `StaleDataError` maps to 409, but the artifact append occurs before event commit. Required-answer guard is an empty `pass`; answer schemas do not enforce that required questions are answered, selected values belong to options, or numeric bounds apply. There is no expected request version. Durable response event/config/artifact exist, but retries could duplicate file content before DB conflict settles. No answer revision/undo command. |
| `action-recovery-outcome` | REST/MCP `complete-recovery` with `retry`, `skip`, or `abandon` plus notes. REST body uses unconstrained string and returns 400; MCP schema enum and handler check it. | Only task state `recovering`. Retry creates an attempt and resumes; skip completes and advances; abandon fails. | 409 domain transition. Task/run status and attempt snapshot events are durable. Retry is not idempotent once state changes. Skip/abandon have no direct inverse. |
| `action-fanout-retry` | REST task `retry`, no body. | Failed fan-out child only; targeted SQL resets child/parent and may enqueue run pause. | Designed to avoid clobbering concurrent child sessions, but no client source version. Emits task status and oversight evidence. Not a generic failed-task retry and cannot carry changed conditions. |
| `action-escalate` | REST/MCP requirement escalation with requirement ID and reason. | Marks requirement escalated and pauses legacy run for human review. | 404/409 on missing identity/invalid phase. Events and pause reason are evidence. Resume/intervention is separate. |

`jobs.J3.exact-question` is current for clarification requests and partly current
for graph/legacy gates. `jobs.J3.alternatives` is present when clarification
options or graph gate options were recorded, but legacy step approval exposes
only approval and the CLI fabricates a reject choice that does not reject.
`jobs.J3.reversibility` is not a shared field or projection; it must be derived
per action from the concrete contracts above, and many decisions have no inverse.

#### Graph decision, patch, retire/supersede, and requeue capability

| Provisional key | Surface and request | Domain eligibility and durable effect | Failure, race, evidence, reversibility |
|---|---|---|---|
| `action-graph-decision` | REST `POST /graph/decisions` reuses strict `RecordDecisionCommand`: approval, authority, or oversight; typed decision set; node; decider; optional scope/expiry/reason/record ID. CLI handles pending human-approval gates only. | Graph controller validates target kind, decision type/value, graph state, and actor/domain rules. Accepted authority/approval can produce decision records, bind inputs, release leases, change node state, and make successors ready; rejection can dead-end required inputs. | 404 for no graph; 409 for stale projection or command rejection; 422 for malformed/invalid decision. Endpoint reads current position itself, so the client supplies no expected graph version. Durable graph events and decision records give identity/state evidence; response includes events and refreshed decision view. No decision-reversal command. Caller-supplied `decider` is not bound to auth. |
| `action-graph-patch` | REST operator `POST /graph/patch` with optional patch ID, optional nonnegative base position, strict ops, optional rationale record. Per-execution graph MCP exposes raw patch plus eight macros, including `retire_or_supersede`. | Controller validates patch and graph invariants. REST stamps human operator context; MCP callbacks bind a node execution and normalize macros into the same patch envelope. Accepted patch appends patch and topology events. | 404 no graph; 409 stale/rejected; 422 strict fields. Client base position supports stale-base validation for patches. Patch attempts projection exposes accepted/rejected event IDs, diagnostics, read-set differences, and created topology IDs. No generic patch rollback; corrective patches are new effects, not undo. |
| `action-retire-supersede` | Per-execution graph MCP macro; operator can express equivalent low-level ops through raw REST patch if validator permits. | Agent macro requires target/action and optional replacement ops/rationale, then graph validation controls legal topology effects. | This is not a standalone operator REST contract. Evidence is the normalized patch attempt/events. Reversibility depends on a subsequent validated patch and is not guaranteed. Assisted operator UI remains absent. |
| `action-outbox-requeue` | REST `POST /graph/outbox/requeue/{event_id}`, constrained path IDs. | Exact row must belong to run and be failed. Transaction resets status/attempts/error/backoff and appends `outbox_requeued`; dispatcher may execute it again. | 404/409/422. Optimistic append conflict maps to 409 and the transaction rolls back. Event records prior error/attempts and fixed operator. Requeue deliberately risks duplicate work according to downstream idempotency; no API preview or idempotency key. It is repeatable only after another failure, not reversible. |

Raw graph patches are **not** typed steering. `retire_or_supersede` is an
agent-scoped patch macro, not proof that an operator can inject new knowledge
into future prompt packets. No `steer`, `directive`, or steering-patch command
was found under `src/orchestrator/`.

#### Repository, review, source/configuration, and file effects

| Provisional key | Implemented commands | Safety and evidence boundary |
|---|---|---|
| `action-branch-sync` | REST/CLI back-merge, merge-back; REST review revert-back-merge. | Back-merge requires active/paused and may leave conflicts in progress. Merge-back requires completed and no failed readiness gates, then mutates source branch. Revert-back-merge only reverses a merge commit at worktree HEAD. These are git effects without per-action auth or client source version. |
| `action-review-prune` | REST prune preview/apply and revert-file. | Preview is non-mutating. Apply mutates files and creates commits; emits `PruneApplied`. The response `event_id` is a fresh UUID generated after emission and is not the persisted event ID, so it does not satisfy durable feedback identity. File revert creates a commit but emits no action event in the route. Git commits provide partial audit/reversal evidence. |
| `action-conflict-resolution` | REST per-block ours/theirs/manual resolution; agent conflict resolution dispatch. | Requires unresolved conflict file or existing conflicts. Manual route stages files and emits `ConflictResolved`; agent route emits `AgentFixStarted`. File path is checked against git's unresolved list. Agent dispatch accepts runner override. No actor authorization. |
| `action-test-run` | REST async review test using routine `auto_verify` commands. | Requires configured commands and no concurrent run; emits start/completion events and returns/polls by test-run ID. This validates work but does not authorize merge. |
| `action-env-files` | REST revert managed env files and copy snapshots to caller-supplied target. | Literal snapshot mode and snapshot ID pattern exist, but `worktree_path` and `target_dir` are caller-supplied filesystem paths. No route-level containment, run ownership, or role authorization is visible. Effects are filesystem writes; response lists files, with no durable action event established here. |
| `action-repository-admin` | REST add clone/symlink and destructive remove; CLI only lists/shows. | URL scheme and one-of URL/path validation exist. Repository name path parameter is joined directly to repos path; removal recursively deletes a non-symlink directory. No per-action authorization, confirmation token, active-run precondition, audit event, or undo. |
| `action-agent-policy` | REST agent create/update/delete/reset prompt and runner model-profile default replacement. | This is the current source-changing surface closest to "change prompt/policy." It affects future resolution, with ordinary schema/name checks. It does not preview cohort impact, version policy, or steer live runs. DB rows/timestamps are evidence, but no operator identity/audit event is established by the routes. |
| `action-routine-archive` | REST archive/unarchive only; CLI validates/reads routines. | Changes routine visibility metadata, not routine source content. Source routine/prompt/policy editing with preview/versioning is not implemented as one unified action. |

### Validation and failure contract

- **implemented, tested:** Shared Pydantic schemas validate many constrained
  values: selectable runner types, merge/execution mode, checklist status,
  grade, graph identifiers, patch strictness, graph decisions, review prune
  modes, and clarification question type/options.
- **implemented limitation:** `ApiModel` does not set `extra="forbid"`; strict
  rejection depends on inherited domain schemas such as graph command payloads.
  Several request models use free strings and endpoint-body conversion instead
  of boundary enums: complete-recovery outcome, review conflict choice, diff
  scope, run-list status, and legacy pending action type.
- **implemented limitation:** Several filesystem-affecting fields are raw paths:
  repo local path, env worktree/target paths, review file path, and git refs.
  Some are checked by downstream git/file functions, but a uniform boundary
  containment contract is absent.
- **implemented:** Domain exceptions generally map to 404 identity errors, 409
  state/gate/lock/stale conflicts, 422 request/gate-check failures, 503 runner
  unavailable, and 500 execution/git errors. Error bodies are not uniform:
  domain handlers use `error`, while endpoint exceptions use `detail`.
- **implemented limitation:** MCP tools return JSON strings and sometimes encode
  failure as a successful tool result with `error`/`hint`; REST uses HTTP status.
  Therefore "accepted/rejected" feedback is transport-specific.

### Race, idempotency, and action feedback

- **tested:** Graph event appends enforce expected positions and expose stale
  projection as 409. Patch requests can carry `base_graph_position`; graph
  decisions cannot carry a client-observed source position.
- **tested:** Outbox requeue changes the row and appends audit evidence in one DB
  transaction; stale append becomes 409. Subsequent dispatch is separately
  observable.
- **tested:** Clarification response catches SQLAlchemy `StaleDataError`, and a
  stale legacy clarification does not reopen an already advanced task. File
  append occurs outside the DB transaction before conflict resolution, so exact
  once-only artifact evidence is unclear.
- **tested contradiction:** Step approval is last-write-wins and can be posted
  repeatedly. This is not idempotency tied to a decision ID or source version.
- **implemented:** Lifecycle and REST task progression often return command
  acceptance/current status before queued signals apply. Polling activity/run
  state is needed for resulting state; responses do not consistently state next
  expected activity or a recovery path.
- **implemented:** Graph decision responses are the strongest feedback contract:
  accepted command, emitted durable event IDs, graph position, resulting
  decision view, and scheduler effects. Rejections return a reason but not a
  refreshed state/recovery object.
- **implemented limitation:** Most destructive REST actions do not accept an
  idempotency key, expected entity version, or confirmation token. Duplicate
  safety depends on current domain state, unique constraints, or git behavior.

### Closed-scope demand disposition

| Scope demand | Audit disposition |
|---|---|
| `jobs.J3.exact-question` | **partial/current by action:** clarification questions and graph gate prompts are implemented; some legacy approvals provide sparse context. |
| `jobs.J3.alternatives` | **partial:** clarification/graph options can exist; legacy step approval has no deny/defer endpoint and the CLI no-choice still approves. |
| `jobs.J3.reversibility` | **gap as a shared claim:** action-specific reality is known, but no consistent field/projection communicates it. Many effects are irreversible through current commands. |
| `jobs.J6.alternatives` | **partial:** lifecycle, recovery outcomes, graph decisions/patches, and requeue exist, but no unified eligible-action projection. |
| `jobs.J6.expected-effect` | **partial:** descriptions, some gate consequences, previews, and graph response events exist; many endpoints do not return predicted/next effects. |
| `jobs.J6.scope` | **partial:** run/task/node/patch/outbox identifiers scope commands, but filesystem/admin actions can accept broad caller paths and there is no common blast-radius contract. |
| `jobs.J6.authority` | **gap for operator policy/enforcement:** optional global auth and domain eligibility exist; role-based authorization does not. |
| `jobs.J6.reversibility` | **gap as a current projection:** per-command compensations vary and are not consistently declared. |
| `jobs.J8.interventions` | **partial evidence, no unified count:** graph/workflow/review events record several interventions, but no inspected API defines a complete cross-mode intervention taxonomy or count. |
| `journeys.continuity.action-safety-fields` | **gap:** no common action response exposes scope, consequence, reversibility, authority, and confirmation together. |
| `decisions.approve-gate-patch` | **current but split:** graph approval/authority decisions, raw graph patch, legacy task decisions, and approve-only step gates are separate. Deny/defer support is graph-specific. |
| `decisions.answer-clarification` | **current with validation gaps:** exact request/response records and resume behavior exist; required-answer and value-membership validation are incomplete. |
| `decisions.retry` | **current but plural:** recovery retry, run recovery, and fan-out retry are distinct; changed-condition evidence is not required. |
| `decisions.lifecycle` | **current:** pause/resume/cancel are reachable, with asynchronous acceptance and mode-specific effects. |
| `decisions.retire-supersede` | **partial/current machinery:** graph MCP macro and raw patch machinery exist; no dedicated operator action or guaranteed rollback. |
| `decisions.requeue` | **current for failed graph outbox rows:** no unified failed-work requeue action beyond that concrete endpoint. |
| `decisions.steer-context` | **gap:** no typed directive/context injection command found. |
| `decisions.apply-steering-patch` | **gap:** raw graph validation exists, but no steering proposal/provenance/binding command contract exists. |
| `decisions.change-source` | **partial:** agent prompt/default policy CRUD and routine archive exist; source routine editing, preview/versioning, and impact analysis are not unified. |
| `feedback.command-accepted-rejected` | **partial:** HTTP status/tool result usually indicates acceptance, but queued acceptance is not resulting state and error shapes vary. |
| `feedback.failure-race-recovery` | **gap/partial:** 409 stale/conflict reasons exist for selected actions; refreshed state and recovery guidance are not systematic. |

## Important uncertainties

- **unclear:** Whether production deployments normally enable auth. The default
  and tests establish that unauthenticated full access is supported, not how an
  operator deploys it.
- **unclear:** Whether all graph domain actor checks can be summarized as one
  stable product permission policy. They validate command legitimacy but do not
  establish human product roles.
- **unclear:** Exactly-once behavior for clarification artifact append when a DB
  race occurs after the file write.
- **unclear:** Whether every review/file helper fully confines user paths to the
  run worktree; route schemas alone do not prove it.
- **unclear:** Whether every mutation has event evidence in lower layers. This
  audit found strong evidence for workflow/graph decisions and weaker or absent
  action events for repo admin, env copy/revert, agent policy, model defaults,
  and some git operations.
- **unclear:** Whether an intervention count can be deterministically derived
  without first deciding which heterogeneous events count. No current API
  contract supplies that taxonomy.

## Conflicts found

1. **CLI lifecycle versus signal-queue invariant.** `AGENTS.md` says all
   start/pause/resume/cancel transitions go through the signal queue, while
   `cli.runs.start_run` directly calls `apply_start_run`. The CLI and REST do not
   currently share one transition acceptance contract.
2. **MCP submit versus REST submit.** REST checks then enqueues
   `ACTIVITY_COMPLETED`; MCP calls `submit_for_verification` directly. Treating
   transports as equivalent without preserving this difference would invent
   common race/result semantics.
3. **Legacy CLI rejection versus implemented effect.** The CLI asks whether to
   approve but always posts to the step approval endpoint; the explicit test
   names this "no answer behavior." The displayed alternative contradicts the
   command effect.
4. **Authenticated identity versus recorded identity.** JWT subject can be
   validated, but legacy and graph mutations persist fixed or caller-supplied
   identities. Audit attribution must not be described as authenticated actor
   identity.
5. **Prune feedback event identity.** `prune_apply` emits a durable event and
   then returns an unrelated UUID as `event_id`. The response field must not be
   treated as a pointer to persisted evidence.
6. **JTBD capability wording versus implementation.** Source documents label
   several interventions "Current," but current support is mode- and
   subtype-specific: requeue means graph outbox row, retry has multiple narrow
   commands, and retire/supersede is agent macro/raw patch machinery. The source
   demand does not establish a unified current action.

## Decisions required

- Synthesis must decide whether missing per-action authorization is a blocking
  authority gap for J3/J6. This report provides no proposed product-role policy.
- Synthesis must decide whether transport-divergent start/submit behavior is one
  conflicted capability or multiple implementation variants under one domain
  intent.
- Human review should explicitly resolve whether the legacy CLI's false reject
  affordance blocks any current approval classification.
- Synthesis must define, from existing evidence only, which events qualify for
  `jobs.J8.interventions`; otherwise the claim remains unknown/gap.
- No decision should complete a steering command contract in this phase.

## Artifact paths

- `research/ui-foundation/agent-reports/04-api-actions-authority.md`
- `.superpowers/sdd/task-6-audit-report.md`

No canonical catalog, reality, capability, product, source, test, or git files
were modified by this task.

## Evidence pointers

Primary implementation:

- `src/orchestrator/api/app.py`: `create_app`, `_mount_mcp_sse`,
  `_SessionPerCallHandler`.
- `src/orchestrator/api/auth.py`: `AuthConfig`, `get_require_auth`,
  `get_require_ws_auth`, `validate_token`.
- `src/orchestrator/api/errors.py`: `register_error_handlers`.
- `src/orchestrator/api/schemas/runs.py`: `CreateRunRequest`, `ResumeRunRequest`,
  `RecoverRequest`, `MergeBackRequest`.
- `src/orchestrator/api/schemas/tasks.py`: `UpdateChecklistRequest`,
  `SetGradeRequest`, approval request models.
- `src/orchestrator/api/schemas/clarifications.py`: question/answer contracts.
- `src/orchestrator/api/routers/runs.py`: lifecycle, recovery, approval, skip,
  backward transition, branch operations.
- `src/orchestrator/api/routers/tasks.py`: legacy task phases, retry, checklist,
  grading, escalation, task decisions, force accept.
- `src/orchestrator/api/routers/clarifications.py`: fixed current user,
  clarification response race handling and constrained auto-resume.
- `src/orchestrator/api/routers/graph.py`: `SubmitGraphPatchRequest`,
  `RecordGraphDecisionRequest`, `submit_operator_graph_patch`,
  `record_graph_decision`, `requeue_failed_outbox_row`.
- `src/orchestrator/api/routers/review.py`: prune, revert, test, conflict, and
  back-merge reversal operations.
- `src/orchestrator/api/routers/envfiles.py`, `agents.py`, `runners.py`,
  `repos.py`, and `routines.py`: administrative/file/source-adjacent mutations.
- `src/orchestrator/api/mcp/tools.py`: 11 public tools and `ToolHandler`.
- `src/orchestrator/api/mcp/server.py`: all-tools and allowlisted registration.
- `src/orchestrator/runners/mcp_scope.py`: phase/task exposure scoping.
- `src/orchestrator/graph_runtime/graph_mcp_tools.py`: execution-bound graph
  patch macros and verifier-only grade.
- `src/orchestrator/cli/runs.py` and `src/orchestrator/cli/approve.py`: direct DB
  and REST CLI behavior.
- `src/orchestrator/workflow/service.py`: `recover_run`,
  `retry_fan_out_child`, `respond_to_clarification`, task approval methods, and
  recovery outcomes.

Decisive tests:

- `tests/integration/test_api_auth.py`
- `tests/integration/test_cli_approve.py`
- `tests/integration/test_api_clarifications.py`
- `tests/integration/test_api_human_approval.py`
- `tests/integration/test_api_tasks.py`
- `tests/integration/test_graph_decisions_api.py`
- `tests/integration/test_graph_api.py`
- `tests/integration/test_graph_fr08_acceptance.py`
- `tests/integration/test_mcp.py`
- `tests/integration/test_mcp_sse.py`
- `tests/integration/test_merge_readiness.py`
- `tests/integration/test_prune_api.py`
- `tests/integration/test_stopping_state.py`
- `tests/integration/test_workflow_service.py`
- `tests/unit/test_graph_mcp_tools.py`

## Recommended next delegation

Normalize these provisional findings into action and permission contracts only
after the workflow-state and graph-runtime reports are reconciled. Preserve the
three authority dimensions separately: enforced authentication/authorization,
implemented domain eligibility, and any later approved product-role policy.
Carry typed steering and steering-patch demands forward only as gaps with their
required outcomes and evidence needs; delegate command design to a separately
approved future capability-design work package.
