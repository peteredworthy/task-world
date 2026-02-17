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
