<<<<<<< HEAD
# Design Questions: frontend-gaps

## Open Questions

### Q1: How should step-level approval differ visually from task-level approval?

- **Context:** The backend has both `POST /runs/{id}/steps/{step_id}/approve` and `POST /runs/{id}/tasks/{task_id}/approve`. The frontend currently only handles task approval. Step approval blocks an entire step (all tasks), while task approval is per-task.
- **Options:**
  1. Separate StepApprovalModal with step-level context (all tasks in step, step gate info) — clearer semantics but more code
  2. Extend existing ApprovalModal with a `scope` prop (step vs task) — less code but risks confusing the two concepts
- **Impact:** High — this is the #1 gap and affects Story 03's central workflow
- **Priority:** High
- **Status:** Open

### Q2: Where should branch status and back-merge controls live in the UI?

- **Context:** Story 04 revolves around branch divergence awareness. The backend has `GET /runs/{id}/branch-status` and `POST /runs/{id}/back-merge`. These need a home in the RunDetail page.
- **Options:**
  1. Dedicated BranchStatusPanel in RunDetail sidebar — always visible, prominent
  2. Collapsible section within the existing run info area — less prominent but doesn't add UI weight
  3. Tab in RunDetail (alongside Activity, Checklist, etc.) — discoverable but requires navigation
- **Impact:** High — this is gap #2 and #3 combined
- **Priority:** High
- **Status:** Open

### Q3: Should the History page reuse Dashboard components or be a fresh build?

- **Context:** Dashboard already shows completed runs via status filter. The History page is currently "Coming soon." Story 04 implies a dedicated view with search, date ranges, and outcome summaries.
- **Options:**
  1. Extend Dashboard with a "history mode" toggle — shared components, less duplication
  2. Build History as a separate page with its own components — distinct UX, more work
- **Impact:** Medium — affects Story 04 but dashboard workaround exists
- **Priority:** Medium
- **Status:** Open

### Q4: How should auto-verify output be displayed in the activity feed?

- **Context:** Auto-verify commands produce stdout/stderr. Currently the activity feed shows "auto-verify PASSED/FAILED" but not the output. Users need to see *why* it failed.
- **Options:**
  1. Expandable section within the activity event — click to reveal full output
  2. Side panel / drawer that opens when clicking an auto-verify event — more space for output
  3. Inline code block always shown for failures, collapsed for passes — immediate visibility for failures
- **Impact:** Medium — affects Story 02 comprehension
- **Priority:** Medium
- **Status:** Open

### Q5: What level of env file management should the UI provide?

- **Context:** Backend has env file endpoints (`api/routers/envfiles.py`). This is a low-severity gap. Env files contain secrets.
- **Options:**
  1. Full CRUD UI for env files with masked values — feature-complete but security-sensitive
  2. Read-only view showing which env files exist and which vars are set (masked) — useful without risk
  3. Skip entirely, keep as CLI-only — minimal effort, acceptable for low-severity gap
- **Impact:** Low
- **Priority:** Low
- **Status:** Open

## Resolved Questions

<!-- Move questions here once resolved -->
=======
# Design Questions: Close All 21 Frontend Gaps

## Open Questions

### Q8: Design-question UI for LLM-driven questions

- **Context:** [HUMAN] feedback identified a gap: there is no way for users to answer design questions in the UI. The planning LLM generates questions during plan creation, but the frontend has no mechanism to present them and capture answers.
- **Options:**
  1. Option A — Define a JSON schema for LLM-generated questions (question text, options, priority, context) and build a `DesignQuestionPanel` component that renders them and submits answers back to the orchestrator.
  2. Option B — Reuse the existing `ClarificationModal` pattern, extending it to support structured multi-option questions with context blocks.
  3. Option C — Add a dedicated `/runs/{id}/questions` sub-page that lists all pending questions for a run, with inline answer forms.
- **Impact:** Enables human-in-the-loop workflows during planning phases. Affects API design (needs an endpoint for question submission) and may require backend changes.
- **Priority:** High
- **Status:** Open — requires further design to determine question schema and backend endpoint. This is a NEW gap beyond the original 21.

## Resolved Questions

### Q1: Step approval modal — reuse ApprovalModal or create new component?

- **Context:** Gap 1 requires step-level approval UI. The existing `ApprovalModal` handles task-level approval via `useApproveTask`/`useRejectTask`. Step approval calls a different endpoint (`POST /api/runs/{id}/steps/{step_id}/approve`) with a different request shape (`HumanApprovalRequest` with `approved_by` and `comment`, no reject action).
- **Options:**
  1. Option A — Create a separate `StepApprovalModal` component. Keeps concerns cleanly separated; step approval has no reject flow and different payload.
  2. Option B — Extend `ApprovalModal` with a `mode` prop (`task` | `step`). Reuses existing UI patterns but adds conditional logic.
- **Impact:** Affects component count and complexity of RunDetail's pending action routing logic.
- **Priority:** High
- **Resolution:** **Option A** — Create a separate `StepApprovalModal`. [HUMAN decision]

### Q2: Branch status polling frequency and trigger

- **Context:** Gap 2 requires displaying branch status (ahead/behind counts). The `GET /api/runs/{id}/branch-status` endpoint performs a git operation on each call. Polling too frequently could be expensive; too rarely makes it stale.
- **Options:**
  1. Option A — Poll every 30s while RunDetail is open, plus on-demand refresh button.
  2. Option B — Fetch once on page load and on WebSocket `run_status_changed` events only.
  3. Option C — Poll every 60s with manual refresh.
- **Impact:** Affects server load and user perception of freshness.
- **Priority:** High
- **Resolution:** **Option B** — Fetch once on page load and refetch on WebSocket `run_status_changed` events. [HUMAN decision]

### Q3: History page — new page or enhance Dashboard?

- **Context:** Gap 10 requires replacing the "Coming soon" History stub. The Dashboard already supports filtering by status=completed. Having two places to view completed runs could confuse users.
- **Options:**
  1. Option A — Build History as a dedicated page focused on completed/failed runs with date ranges, outcome summaries, and cost totals. Dashboard keeps its current behavior.
  2. Option B — Enhance Dashboard to subsume History functionality (add date range filter, outcome view). Remove History nav item.
  3. Option C — History page that deep-links into Dashboard with pre-set filters plus adds aggregate stats.
- **Impact:** Affects navigation structure, component reuse, and user mental model.
- **Priority:** Medium
- **Resolution:** **Option A** — Build History as a dedicated page. [HUMAN decision]

### Q4: Dashboard real-time updates — WebSocket per-run or aggregate channel?

- **Context:** Gap 21 requires real-time updates on the Dashboard instead of 10s polling. The existing WebSocket infrastructure is per-run (`/ws/runs/{runId}`). The Dashboard shows multiple runs.
- **Options:**
  1. Option A — Open one WebSocket per visible active run on the Dashboard. Simple to implement using existing infra but could mean 5-10 concurrent connections.
  2. Option B — Add a dashboard-level SSE/WebSocket channel that broadcasts status changes for all runs. Requires checking if a backend endpoint exists or can be added.
  3. Option C — Reduce polling interval to 3-5s as a simpler improvement. No WebSocket changes needed.
- **Impact:** Affects connection count, backend requirements, and perceived responsiveness.
- **Priority:** Low
- **Resolution:** **Option B** — Add a dashboard-level WebSocket/SSE channel that broadcasts all run status changes. [HUMAN decision]. Note: this may require a new backend endpoint; verify availability before implementation.

### Q5: Env file management — where in the UI?

- **Context:** Gap 19 requires an env file management UI. Backend has endpoints for listing, snapshotting, reverting, and copying env files. This is a run-specific operation.
- **Options:**
  1. Option A — A collapsible panel/tab within RunDetail page, alongside activity feed.
  2. Option B — A modal triggered from a button on RunDetail.
  3. Option C — A dedicated sub-route (`/runs/{id}/env-files`).
- **Impact:** Affects RunDetail layout complexity and discoverability.
- **Priority:** Low
- **Resolution:** **Config-area approach** — Place env file management in the config/settings area as base env file templates that can be referenced when creating runs. The run creation flow (CreateRunModal) should allow overriding and adjusting env file values. [HUMAN decision]. This changes the implementation from a RunDetail panel to a config-level feature with CreateRunModal integration.

### Q6: Where to show auto-verify output?

- **Context:** Gap 6 requires surfacing auto-verify stdout/stderr. This output comes from running test commands during verification. It needs to be visible but not overwhelm the activity feed.
- **Options:**
  1. Option A — Collapsible code block within the auto-verify event in ActivityFeed. Collapsed by default, expandable inline.
  2. Option B — Link from the auto-verify event to a log viewer modal.
  3. Option C — Show in the TaskDetailCard's attempt details section.
- **Impact:** Affects ActivityFeed component complexity and readability.
- **Priority:** Medium
- **Resolution:** **Option A** — Collapsible code block within ActivityFeed, collapsed by default. [HUMAN decision]

### Q7: Attempt timeline visualization approach

- **Context:** Gap 14 asks for a visual representation of the build→verify→revise cycle rather than a flat list. AttemptHistory currently shows attempts as cards.
- **Options:**
  1. Option A — Horizontal timeline with nodes for each attempt, connecting lines showing the flow, and status icons.
  2. Option B — Vertical stepper with expandable attempt details at each node.
  3. Option C — Keep flat list but add visual connectors (arrows, status flow indicators) between attempts.
- **Impact:** Affects visual complexity and implementation effort. Option C is lowest effort.
- **Priority:** Low
- **Resolution:** **Option C** — Keep flat list with visual connectors (arrows, status flow indicators) between attempts. [HUMAN decision]
>>>>>>> orchestrator/run-70577a15-5a02-4235-9a42-0c27ef966bc5
