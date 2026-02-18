# UI Gaps: Remaining Work

This document describes frontend work needed to wire up backend endpoints that already exist and have test coverage but are not yet connected to the UI. Each section references the backend endpoint, existing frontend state, and the specific work required.

Source: `docs/PARTIAL-FEATURES.md`

---

## 1. Step-Level Human Approval

**Backend endpoint:** `POST /api/runs/{id}/steps/{step_id}/approve`
**Backend tests:** `tests/integration/test_approval_workflow.py`

### Current state

- The `StepSummary` type already has `has_approval_gate: boolean` and `approval_status` fields (`ui/src/types/runs.ts`).
- Task-level approval is fully wired via `ApprovalModal` and `useApproveTask`/`useRejectTask` hooks.
- No API client function or mutation hook exists for the step-level approval endpoint.
- No UI renders a step-level approval prompt or button.

### Work required

1. **API client** (`ui/src/api/client.ts`): Add `approveStep(runId, stepId, { approved, comment })` function calling `POST /api/runs/{id}/steps/{step_id}/approve`.
2. **Mutation hook** (`ui/src/hooks/useApi.ts` or new file): Add `useApproveStep` mutation that invalidates `['run', runId]` on success.
3. **UI component**: When rendering a step in `RunDetail.tsx`, check `has_approval_gate && approval_status === 'pending'`. Show an approve/reject prompt inline or as a modal, similar to the existing `ApprovalModal` pattern but at the step level.
4. **Pending actions**: Ensure step-level approvals appear in `usePendingActions` results and are surfaced in the `PendingActionsBadge`.

### Complexity: Medium

---

## 2. Activity SSE Streaming (Settings Integration)

**Backend endpoint:** `GET /api/runs/{id}/activity/stream`
**Backend tests:** `tests/integration/test_api_runs.py`

### Current state

- SSE streaming is **already implemented** in `ui/src/hooks/useActivitySSE.ts`.
- A unified `useActivityStream` hook (`ui/src/hooks/useActivityStream.ts`) switches between SSE and polling based on `settings.activityStreamMode`.
- The `RunDetail` page uses `useActivityStream`.

### Work required

1. **Settings UI**: The `activityStreamMode` setting needs a toggle in the settings panel so users can switch between `'sse'` and `'polling'`. Verify the settings panel exposes this option.
2. **Default mode**: Consider defaulting to SSE instead of polling, with a fallback to polling if SSE connection fails.
3. **Connection status indicator**: Surface `isConnected` from the SSE hook in the activity feed UI so users know when the real-time connection drops.

### Complexity: Low

---

## 3. External Agent Lifecycle Hooks

**Backend endpoints:** `POST /api/runs/{id}/agent-started`, `POST /api/runs/{id}/agent-cancelled`
**Backend tests:** `tests/integration/test_api_runs.py`

### Current state

- The `RunResponse` type has `agent_started_at` field.
- `AgentGuidancePanel` shows guidance for user-managed agents (prompts, MCP URL, auth tokens).
- `WaitingIndicator` shows elapsed wait time and has a cancel button.
- No API client functions exist for `agent-started` or `agent-cancelled`.
- No UI buttons map to these endpoints.

### Work required

1. **API client** (`ui/src/api/client.ts`): Add `agentStarted(runId)` → `POST /api/runs/{id}/agent-started` and `agentCancelled(runId)` → `POST /api/runs/{id}/agent-cancelled`.
2. **Mutation hooks**: Add `useAgentStarted` and `useAgentCancelled` mutations.
3. **UI in AgentGuidancePanel**: Add an "I've started my agent" button that calls `agentStarted`. This signals the backend that external work has begun and sets `agent_started_at`.
4. **UI cancel**: Wire the existing cancel button in `WaitingIndicator` (or add one to `AgentGuidancePanel`) to call `agentCancelled` instead of or in addition to the run-level cancel.

### Complexity: Low

---

## 4. External Agent Guidance (Aggregate Endpoint)

**Backend endpoint:** `GET /api/runs/{id}/guidance`
**Backend tests:** `tests/integration/test_api_runs.py`

### Current state

- `AgentGuidancePanel` constructs its own guidance display using `useTaskPrompt()` and hardcoded MCP/auth info.
- The backend provides a single aggregate `/guidance` endpoint that bundles the task prompt, MCP URL, callback instructions, and expected next actions.
- The UI does not call this endpoint.

### Work required

1. **API client**: Add `getGuidance(runId)` → `GET /api/runs/{id}/guidance`.
2. **Query hook**: Add `useGuidance(runId)` with appropriate polling or WebSocket-triggered invalidation.
3. **Refactor AgentGuidancePanel**: Replace the multiple data sources (task prompt hook + hardcoded values) with the single `useGuidance` hook. The aggregate object should have all needed fields.
4. **Type definition**: Add a `GuidanceResponse` type matching the backend schema.

### Complexity: Low-Medium

---

## 5. Backward Step Transitions

**Backend endpoint:** `POST /api/runs/{id}/transition-back`
**Backend tests:** `tests/integration/test_api_runs.py`

### Current state

- `StepProgressBar` in `RunDetail.tsx` shows step completion with color-coded indicators and is clickable (scrolls to step).
- No API client function or UI control exists to transition backward.

### Work required

1. **API client**: Add `transitionBack(runId, { target_step })` → `POST /api/runs/{id}/transition-back`.
2. **Mutation hook**: Add `useTransitionBack` that invalidates `['run', runId]` and `['activity', runId]`.
3. **UI control**: Add a "Go back to step" action. Options:
   - A context menu or button on completed steps in the `StepProgressBar`.
   - A dropdown/dialog that lets the user pick which earlier step to return to.
4. **Confirmation dialog**: Since going back resets task states in the target step, show a warning explaining what will be lost.

### Complexity: Medium

---

## 6. Branch Status and Back-Merge

**Backend endpoints:** `GET /api/runs/{id}/branch-status`, `POST /api/runs/{id}/back-merge`
**Backend tests:** `tests/integration/test_api_runs.py`

### Current state

- Merge-back (run→source, completing a run) IS wired via `useMergeBack()`.
- No API client functions exist for `branch-status` or `back-merge`.
- The UI has no display for branch drift (ahead/behind counts).

### Work required

1. **API client**: Add `getBranchStatus(runId)` → `GET /api/runs/{id}/branch-status` and `backMerge(runId)` → `POST /api/runs/{id}/back-merge`.
2. **Types**: Add `BranchStatusResponse` with `ahead`, `behind`, `mergeable` fields.
3. **Query hook**: Add `useBranchStatus(runId)` with periodic polling (e.g., 30s).
4. **UI - Branch drift indicator**: In the run detail header or a sidebar panel, show ahead/behind counts. Highlight when the run's branch has drifted from the source branch (e.g., "3 commits behind source").
5. **UI - Back-merge button**: When `behind > 0`, show a "Pull latest changes" or "Back-merge" button. Disable if `mergeable` is false and show conflict info.
6. **Mutation hook**: Add `useBackMerge` that invalidates `['branch-status', runId]` and `['run', runId]`.

### Complexity: Medium

---

## 7. Environment File Management

**Backend endpoints:**
- `GET /api/runs/{id}/env-files`
- `GET /api/runs/{id}/env-files/snapshots`
- `POST /api/runs/{id}/env-files/revert`
- `POST /api/runs/{id}/env-files/copy-back`
- `GET /api/runs/{id}/env-files/default-target`

**Backend tests:** `tests/integration/test_api_runs_envfiles.py`

### Current state

- The `CreateRunModal` handles env-related config fields (`env_specs` in `RunResponse`).
- No UI exists for viewing, managing, or reverting env file snapshots during a run.

### Work required

1. **API client**: Add functions for all five env file endpoints.
2. **Types**: Add `EnvFile`, `EnvSnapshot`, `EnvDefaultTarget` types.
3. **Query hooks**: `useEnvFiles(runId)`, `useEnvSnapshots(runId)`, `useEnvDefaultTarget(runId)`.
4. **Mutation hooks**: `useRevertEnvSnapshot`, `useCopyBackEnvFiles`.
5. **UI - Env files panel**: New component (e.g., `EnvFilesPanel`) in the run detail view:
   - List current env files with masked values.
   - Show snapshot history with timestamps and task boundaries.
   - "Revert to snapshot" button per snapshot row.
   - "Copy back to project" button with target path display.
6. **Integration**: Add the panel to `RunDetail.tsx`, possibly as a tab or collapsible section.

### Complexity: High

---

## 8. Routine YAML Validation

**Backend endpoint:** `POST /api/routines/validate`
**Backend tests:** `tests/integration/test_api_routines.py`

### Current state

- The `RoutineSelector` and `CreateRunModal` browse existing routines but provide no editor.
- No API client function exists for the validate endpoint.

### Work required

1. **API client**: Add `validateRoutine(yaml: string)` → `POST /api/routines/validate`.
2. **Mutation hook**: Add `useValidateRoutine`.
3. **UI - Routine editor**: New page or modal with:
   - A YAML text editor (consider a code editor component like CodeMirror or Monaco, or a simple `<textarea>` for MVP).
   - "Validate" button that submits YAML and displays structured errors/warnings inline.
   - Error display with line numbers and builder-friendly messages from the backend response.
4. **Routing**: Add a route for the editor page if it's a standalone page (e.g., `/routines/new` or `/routines/edit`).

### Complexity: High

---

## 9. Global Configuration Endpoint

**Backend endpoint:** `GET /api/config`
**Backend tests:** None.

### Current state

- Frontend settings are local-only (stored in browser, managed by `SettingsContext`).
- No API call fetches server-side configuration.

### Work required

1. **API client**: Add `getConfig()` → `GET /api/config`.
2. **Types**: Add `GlobalConfig` type matching the backend schema.
3. **Query hook**: Add `useGlobalConfig()` with long stale time (config rarely changes).
4. **UI integration**: Surface relevant server config in the settings panel or as read-only info (e.g., available agent types, default paths, feature flags). Distinguish between local settings (user preferences) and server config (system-level).

### Complexity: Low

---

## 10. Enhanced Clarification System (Idea-to-Plan)

**Extends the existing clarification system** (`workflow/clarifications.py`, `mcp/clarification_tools.py`, `api/routers/clarifications.py`, `ClarificationModal`).

The current clarification system provides a basic multi-choice + free-text-override flow. This enhancement adds richer question types, real-time WebSocket notifications, answer history in the activity timeline, line-number-aware builder prompts, and user force-skip capability.

### Current state

**What works today:**
- MCP tool `orchestrator_request_clarification` lets the LLM submit questions during building.
- Task transitions to `PENDING_USER_ACTION` with `pending_action_type: "clarification"`.
- Frontend polls `GET /api/runs/{id}/pending-actions` every 10s; auto-opens `ClarificationModal`.
- User answers with single-select from 2-4 options or "Other" free text.
- Answers are formatted as markdown and appended to the artifact file (`clarification_artifact_path` in routine config).
- Task transitions back to `BUILDING` after response.

**What's missing:**

1. **Question types are too limited.** Only multi-choice with 2-4 options is supported. No pure free-text, number, or multi-select questions. No way to disable the text override. No per-question required/optional flag.
2. **No WebSocket push for clarification events.** The `useWebSocket` hook doesn't handle `ClarificationRequested` events, so the UI relies solely on 10s polling to detect pending questions.
3. **No answer history in the UI.** Historical Q&A rounds are not shown anywhere in the task detail or activity timeline. Only the current pending request is surfaced.
4. **Builder prompt lacks line references.** After answers are appended to the artifact file, the builder prompt doesn't include the file path or line number ranges pointing to the new answers.
5. **No force-skip capability.** The user must answer all questions; there's no way to skip remaining questions and tell the builder to proceed.

### Detailed requirements

#### 10a. Richer question types

Extend the `ClarificationQuestion` model and the MCP tool `inputSchema` to support:

| Type | Description | LLM specifies | UI renders |
|------|-------------|---------------|------------|
| `single_select` | Pick one option from a list | `options: string[]` (2-4), optional `allow_other: boolean` (default true) | Radio buttons + optional text input |
| `multi_select` | Pick one or more options | `options: string[]` (2-6), optional `allow_other: boolean` | Checkboxes + optional text input |
| `free_text` | Open-ended text answer | Optional `placeholder: string` | Textarea |
| `number` | Numeric answer | Optional `min`, `max`, `placeholder` | Number input with validation |

Each question gets a `required: boolean` field (default `true`). Optional questions can be left blank.

**Backend changes:**
- `workflow/clarifications.py`: Add `question_type`, `allow_other`, `required`, `min`, `max`, `placeholder` fields to `ClarificationQuestion`.
- `mcp/clarification_tools.py`: Update `CLARIFICATION_TOOL` inputSchema to include `question_type` and type-specific fields.
- `api/schemas/clarifications.py`: Update schema to match.
- Validation: `single_select` and `multi_select` require `options`; `free_text` and `number` must not have `options`.

**Frontend changes:**
- `ui/src/types/clarifications.ts`: Add new fields to `ClarificationQuestion`.
- `ui/src/components/detail/QuestionCard.tsx`: Render different input types based on `question_type`. Show required indicator. Validate number min/max.
- `ui/src/components/detail/ClarificationModal.tsx`: Update answer validation to respect `required` flag and question type.

#### 10b. WebSocket push for clarification events

When a `ClarificationRequested` event is emitted, broadcast it via the run's WebSocket channel so the frontend reacts immediately.

**Backend changes:**
- `workflow/event_logger.py` or `api/websocket.py`: Ensure `ClarificationRequested` and `ClarificationResponded` events are broadcast to WebSocket subscribers (they may already be broadcast as generic events; verify and add type-specific handling if needed).

**Frontend changes:**
- `ui/src/hooks/useWebSocket.ts`: Add handler for `clarification_requested` event type that invalidates `['pending-actions', runId]` and `['pending-clarification', runId, taskId]` queries. This triggers the auto-open logic in `RunDetail.tsx` without waiting for the next poll cycle.
- Keep the existing 10s polling as fallback (no interval change needed).

#### 10c. Answer history in activity timeline

Show completed clarification rounds as expandable events in the activity feed.

**Backend changes:**
- Ensure `ClarificationRequested` and `ClarificationResponded` events include the full Q&A data in their payloads (questions, options, selected answers, free text, timestamps).
- Add a `GET /api/runs/{id}/tasks/{task_id}/clarifications` endpoint (or extend the existing one) to return all historical clarification requests+responses for a task, not just the pending one.

**Frontend changes:**
- `ui/src/types/activity.ts`: Add clarification event payload types.
- Activity feed rendering: When an event of type `clarification_responded` appears, render it as an expandable card showing:
  - Round number (e.g., "Clarification 1", "Clarification 2")
  - Each question with the selected answer (highlight chosen option, show free text)
  - Timestamp and who answered
  - Collapsed by default, expandable on click.

#### 10d. Line-number-aware builder prompt

After answers are appended to the artifact file, the builder's resume prompt should reference the file and the exact line range of the new answers.

**Backend changes:**
- `workflow/clarifications.py`: `format_clarification_artifact` should return both the formatted text AND metadata about the line range (start line, end line) after appending.
- `workflow/service.py`: When responding to a clarification, record the line range in the `ClarificationResponse` or as event metadata.
- `workflow/prompts.py`: When building the builder prompt after a clarification response, include: `"User answers have been written to {artifact_path} (lines {start}-{end}). Read that section for the answers to your questions."` Include the full file path relative to the worktree.

#### 10e. User force-skip with explicit signal

Allow the user to skip unanswered optional questions or force-skip an entire clarification request.

**Backend changes:**
- `api/routers/clarifications.py`: The `respond_to_clarification` endpoint should accept a `skipped: boolean` flag and an optional `skip_reason: string`. When skipped, unanswered questions are recorded with `skipped: true` rather than requiring answers.
- `workflow/clarifications.py`: Add `skipped` and `skip_reason` fields to `ClarificationAnswer`. Update `format_clarification_artifact` to render skipped questions as: `**Answer:** (skipped) {reason or "User declined to answer"}`.
- `workflow/prompts.py`: When the builder resumes after a force-skip, the prompt should include: `"The user declined to answer the following questions: {list}. Reason: {reason}. Proceed with your best judgment for those items."`.

**Frontend changes:**
- `ui/src/components/detail/ClarificationModal.tsx`: Add a "Skip remaining" button (enabled when at least one required question has been answered or when all questions are optional). Show a small text input for skip reason. Submit with `skipped: true` and any partial answers.
- `ui/src/types/clarifications.ts`: Add `skipped` and `skip_reason` to `RespondToClarificationRequest`.

### Complexity: High (spans backend models, MCP tool, API, prompts, WebSocket, and frontend)

---

## Priority Recommendation

| Priority | Item | Rationale |
|----------|------|-----------|
| P0 | Enhanced clarifications (#10) | Blocks idea-to-plan workflows; multi-part feature |
| P0 | Step-level approval (#1) | Blocks workflows that use approval gates between steps |
| P0 | External agent lifecycle (#3) | Low effort, high value for user-managed agent UX |
| P1 | Branch status & back-merge (#6) | Prevents stale branches in long-running runs |
| P1 | Backward step transitions (#5) | Needed for error recovery workflows |
| P1 | Agent guidance refactor (#4) | Low effort cleanup, uses proper aggregate endpoint |
| P2 | Env file management (#7) | Important for multi-env workflows, but higher effort |
| P2 | SSE settings integration (#2) | SSE works, just needs settings exposure |
| P2 | Routine YAML validation (#8) | Enables routine authoring in the UI |
| P3 | Global config endpoint (#9) | Low impact, no backend tests yet |
