# Dry-Run Simulation Notes: Bug and Gap Removal

**Date**: 2026-02-18
**Scope**: Steps 1–12 from `docs/bug-removal/steps/`
**Purpose**: Capture assumptions, expected outputs, blockers, and mitigations for each generated execution task before actual implementation begins.

---

## Summary

12 steps across 4 milestones, 34 individual tasks total. All backend source files referenced in the plan exist. One critical gap discovered: `ui/src/components/StepTimeline.tsx` does **not** exist, but Step 8 plans to modify it. The frontend API client uses an object-based pattern (`api.methodName()`) that diverges from the individual function export pattern assumed in most step plans — agents will need to adapt.

---

## Step 1: Fix GateBlockedError Handling (Backend)

### Tasks: T1 (cli.py re-raise), T2 (executor.py catch), T3 (unit tests)

**Assumptions**
- `GateBlockedError` is already imported by `cli.py` (confirmed: line 25)
- `executor.py` already catches `GateBlockedError` at lines 359–366 and logs/continues
- `workflow/errors.py` defines `GateBlockedError` with `gate_name` and `blocking_items`

**Expected Outputs**
- T1: `cli.py` `execute()` has explicit `except GateBlockedError: raise` before the generic `except Exception` block (verify it does not already exist; it may need moving/confirming)
- T2: `executor.py` `_execute_task` catches `GateBlockedError` and returns without calling `on_agent_died`
- T3: Two tests in `tests/unit/agents/test_gate_blocked.py` — both pass

**Blockers and Mitigations**
- **Potential duplicate**: `executor.py` lines 359–366 may already handle `GateBlockedError` in `_run_agent_loop` (not `_execute_task`). Agent must confirm the catch is at the right level — in `_execute_task`, not the outer loop. If already correct, just verify; if at wrong level, move it.
- **cli.py re-raise may already exist**: The import is confirmed present at line 25. Agent must check whether the `except GateBlockedError: raise` clause is already present in `execute()`. If so, T1 is a no-op — mark done after verifying.
- **Test file location**: `tests/unit/agents/` may not exist as a directory. Agent must create `__init__.py` files as needed for test discovery.

---

## Step 2: Rewrite Human Gate Task Prompts (Routine)

### Tasks: T1 (S-02 prompt), T2 (S-08 prompt)

**Assumptions**
- `routines/idea-to-plan.yaml` exists and is valid YAML (confirmed)
- S-02 T-01 currently has a no-op wait prompt (confirmed: "Await Human Feedback" with no actionable instructions)
- S-08 currently has a no-op final approval prompt (confirmed: "Human Final Approval" with no actionable instructions)
- `{{feature}}` is the template variable used for artifact path substitution at runtime

**Expected Outputs**
- T1: S-02 T-01 `task_context` (or equivalent prompt field) replaced with actionable check-artifacts instructions referencing `{{feature}}`
- T2: S-08 task prompt replaced with same pattern
- YAML parses cleanly after both changes

**Blockers and Mitigations**
- **YAML field name**: The plan calls the field `task_context`. Agent must confirm the actual field name in the YAML (could be `context`, `description`, `prompt`, `task_context`). Misidentification would corrupt the YAML structure.
- **Multi-line YAML indentation**: The replacement content uses `|` block scalars. Incorrect indentation will break YAML parsing. Agent must validate after each edit with `python -c "import yaml; yaml.safe_load(open('routines/idea-to-plan.yaml'))"`.
- **Template variable**: The `{{feature}}` variable must be preserved verbatim; double-brace Jinja syntax must not be collapsed to `{feature}` by any editor or formatter.
- **Prerequisite on Step 1**: S-02 and S-08 gates will only be auto-resolved once the GateBlockedError fix (Step 1) is also deployed. The prompt changes alone are not sufficient for end-to-end fix.

---

## Step 3: Implement Failed-Run Recovery API (Backend)

### Tasks: T1 (schemas), T2 (service.py), T3 (router), T4 (integration tests)

**Assumptions**
- `src/orchestrator/api/schemas/runs.py` exists with existing Pydantic models
- `WorkflowService` in `service.py` follows async pattern matching existing methods
- `NotFoundError` and `ConflictError` exception classes exist and are caught by the router (or equivalents are used)
- `RunStatus.FAILED` is a valid enum value
- Git worktree operations use an existing `git/` module consistent with GitPython
- `end_commit` field exists on task attempt records in the DB model

**Expected Outputs**
- T1: `RecoverRequest` and `RecoverResponse` importable from `orchestrator.api.schemas.runs`
- T2: `WorkflowService.recover_run()` async method implementing 8-step logic; returns `RecoverResponse` with `status="PAUSED"`, `pause_reason="recovered"`
- T3: `POST /api/runs/{id}/recover` registered in `api/routers/runs.py`; returns 409 for non-FAILED runs, 404 for missing run/task
- T4: Integration tests pass for happy path, 409 conflict, preserve_checklist, and invalid task_id cases

**Blockers and Mitigations**
- **Error class names**: The plan uses `NotFoundError` and `ConflictError`. The actual codebase may use `HTTPException` directly or a different exception hierarchy. Agent must grep for existing exception patterns in `runs.py` before implementing.
- **`end_commit` field**: If `end_commit` is not stored on attempt records, the git checkout step will need a fallback. The plan documents a `source_branch` HEAD fallback — ensure it's implemented.
- **Step "un-completion" semantics**: The plan says "un-complete affected steps (completed → False)". Agent must find the actual field name on the step model (could be `completed`, `is_completed`, `status`). Wrong field name will silently fail.
- **Downstream task ordering**: The plan requires tasks to be reset in "execution order." Agent must confirm how tasks within and across steps are ordered in the DB (by `step_index` + `task_index` or similar).
- **COMPLETED run returns 409**: Per clarification, COMPLETED recovery is explicitly deferred. The 409 check must cover all non-FAILED statuses, not just COMPLETED. Tests should verify ACTIVE, PAUSED, and COMPLETED all return 409.

---

## Step 4: Add Recovery UI (Frontend)

### Tasks: T1 (TS types), T2 (client + hook), T3 (RecoveryPanel), T4 (RunDetail mount + Vitest)

**Assumptions**
- `ui/src/api/client.ts` exists with an `ApiError` class and a consistent fetch pattern
- `ui/src/hooks/useApi.ts` uses TanStack Query `useMutation` and `useQueryClient`
- `RunDetail.tsx` receives a fully-typed run object including `steps` and nested `tasks`
- Step 3 (backend API) is deployed before UI is tested end-to-end

**Expected Outputs**
- T1: `RecoverRequest` and `RecoverResponse` TypeScript interfaces exported from `ui/src/types/`
- T2: `recoverRun()` function in `client.ts`; `useRecoverRun()` hook in `useApi.ts`
- T3: `RecoveryPanel.tsx` at `ui/src/components/detail/RecoveryPanel.tsx` with task timeline and confirmation dialog
- T4: `RunDetail.tsx` mounts panel when `run.status === 'FAILED'`; Vitest tests pass

**Blockers and Mitigations**
- **`client.ts` API pattern**: The existing `client.ts` uses an object pattern (`api.listRuns()`) rather than individual named exports. The plan's code snippets show individual function exports (`export async function recoverRun(...)`). Agent must align with the existing pattern or add exports consistently with how the file is structured — check whether functions are exported individually or attached to the `api` object.
- **`RunDetail` type for `run.steps[].tasks[]`**: The `RecoveryPanel` needs access to `tasks` nested under steps with `end_commit` data. Agent must verify the `RunDetail` type (or `RunResponse` schema) includes task-level `end_commit` and status fields, or extend it.
- **`ConfirmationDialog` component**: The `RecoveryPanel` uses a `ConfirmationDialog`. Agent must confirm this component exists in the codebase or use an alternative modal/dialog pattern already present.
- **`ui/src/components/detail/` directory**: Agent must confirm this directory exists before creating files inside it.

---

## Step 5: Phase-Aware MCP Tool Filtering

### Tasks: T1 (server.py phase param), T2 (executor.py passes phase), T3 (unit tests)

**Assumptions**
- `src/orchestrator/mcp/server.py` uses FastMCP; tools are registered via `self.server.add_tool()` or equivalent
- `_register_tools()` method exists and is called during `__init__`
- `executor.py` constructs `OrchestratorMCPServer` (or equivalent) when spawning agents
- The MCP `tools.py` soft-error workaround mentioned in the plan exists and should be preserved

**Expected Outputs**
- T1: `OrchestratorMCPServer.__init__` accepts `phase: Literal["building", "verifying"] = "building"`; raises `ValueError` for invalid phase; `_register_tools()` filters by phase
- T2: `executor.py` derives phase from task status and passes it when constructing MCP server
- T3: Four unit tests in `tests/unit/mcp/test_phase_filtering.py` all pass

**Blockers and Mitigations**
- **MCP tool registration API**: The plan assumes `self.server.add_tool(tool_name, tool_fn)`. The actual FastMCP API may differ (e.g., decorator-based `@self.server.tool()`). Agent must read `server.py` before implementing to understand the registration pattern.
- **Tool name constants**: The plan hardcodes tool names as strings (`"orchestrator_get_requirements"` etc.). The actual registered names may differ slightly. Agent must grep for `add_tool` or `@tool` calls in `server.py` to confirm exact names.
- **`ALL_TOOLS` dictionary**: The plan references `for tool_name, tool_fn in ALL_TOOLS.items()`. This dictionary doesn't exist yet and must be constructed from the existing registrations. This is a non-trivial refactor of the registration logic.
- **`executor.py` MCP construction point**: `executor.py` may not directly construct `OrchestratorMCPServer` — it may instantiate it elsewhere (e.g., a factory or the agent class itself). Agent must trace where the MCP server is created for each task before adding the `phase` parameter.
- **Default phase transition safety**: The plan's safe default of `"building"` ensures the system remains runnable during Task 1 → Task 2 transition. Do not merge Task 1 and Task 2 in the same commit if the deployment order matters.

---

## Step 6: Wire Step-Level Human Approval UI

### Tasks: T1 (client + hook), T2 (StepApprovalBanner), T3 (usePendingActions + RunDetail + Vitest)

**Assumptions**
- Backend `POST /api/runs/{id}/steps/{step_id}/approve` exists at approx. line 603 of `runs.py`
- `StepSummary` TypeScript type includes `has_approval_gate` and `approval_status` fields (confirmed from `api/schemas/runs.py`)
- `ui/src/components/detail/ApprovalModal.tsx` exists as a reference pattern
- `usePendingActions.ts` currently wraps `api.getPendingActions(runId)` and returns its result directly

**Expected Outputs**
- T1: `approveStep()` in `client.ts`; `useApproveStep()` in `useApi.ts`
- T2: `StepApprovalBanner.tsx` renders approval form for pending gates; renders null otherwise
- T3: `usePendingActions` includes pending step approval gates in count; `RunDetail` mounts banner per step; Vitest tests pass

**Blockers and Mitigations**
- **`usePendingActions` structure**: The hook currently returns raw React Query result from `api.getPendingActions()`. The plan assumes client-side count aggregation. The actual `getPendingActions` endpoint may already return an aggregated count — agent must check endpoint response schema before deciding whether to add client-side filtering or update the count from the API response.
- **`ApprovalModal.tsx` as reference**: If `ApprovalModal.tsx` doesn't exist or uses a different UI library, the banner pattern may need to be adapted.
- **Approval form field names**: The plan uses `approved_by: string` and `comment?: string`. Agent must verify these match the backend `ApproveStepRequest` schema exactly (case-sensitive).
- **`StepSummary.approval_status` values**: The plan checks `approval_status === 'pending'`. Agent must confirm the exact string values used by the backend enum (`'pending'`, `'approved'`, `null`).

---

## Step 7: Wire AgentGuidancePanel Lifecycle Hooks

### Tasks: T1 (types + client functions), T2 (hooks), T3 (AgentGuidancePanel update + WaitingIndicator + Vitest)

**Assumptions**
- Backend endpoints exist at the referenced line numbers: `agent-started` (~791), `agent-cancelled` (~818), `guidance` (~677) in `runs.py`
- `AgentGuidancePanel.tsx` currently uses `useTaskPrompt()` and a hardcoded MCP URL
- `WaitingIndicator.tsx` has a cancel path that needs updating
- `GuidanceResponse` fields (`task_id`, `prompt`, `phase`, `mcp_url`, `expected_actions`) match the actual backend response schema

**Expected Outputs**
- T1: `GuidanceResponse` type; `agentStarted`, `agentCancelled`, `getGuidance` in `client.ts`
- T2: `useGuidance`, `useAgentStarted`, `useAgentCancelled` in `useApi.ts`
- T3: `AgentGuidancePanel` uses `useGuidance`; lifecycle buttons wired; Vitest test passes

**Blockers and Mitigations**
- **`GuidanceResponse` schema drift**: The plan's interface may not match the actual backend response. Agent must either read the backend `guidance` endpoint handler or rely on existing TypeScript types if they exist. Schema mismatch will cause silent runtime errors.
- **`useTaskPrompt` removal**: Removing `useTaskPrompt` may break other components if they also use it. Agent must grep for all usages of `useTaskPrompt` before removing it.
- **`WaitingIndicator.tsx` interface**: The component's cancel prop or callback name may differ from what the plan assumes. Agent must read the component before modifying.
- **Guidance 404 handling**: If no active task exists, the guidance endpoint may return 404. The component must render a placeholder rather than crash. Ensure `useGuidance` handles 404 gracefully.
- **WebSocket invalidation for `useGuidance`**: The plan notes "Invalidated by WebSocket run events; no polling needed." The existing WebSocket setup must already invalidate `['guidance', runId]` queries — or the agent must add that invalidation call to the WebSocket event handler.

---

## Step 8: Add Backward Step Transition UI

### Tasks: T1 (client + hook), T2 (StepTimeline update + Vitest)

**Assumptions**
- Backend `POST /api/runs/{id}/transition-back` exists at approx. line 837 of `runs.py`
- `StepTimeline.tsx` exists and can be modified (⚠️ **CRITICAL GAP BELOW**)
- Steps have `index`, `status`, and `title` fields accessible in the component

**Expected Outputs**
- T1: `transitionBack()` in `client.ts`; `useTransitionBack()` in `useApi.ts`
- T2: `StepTimeline.tsx` shows "Revert to this step" on completed preceding steps; confirmation dialog with reason field; Vitest tests pass

**Blockers and Mitigations**
- **CRITICAL: `StepTimeline.tsx` does NOT exist**: Glob search confirmed the file is absent from the codebase. The plan says to "open and modify" it. The agent will need to either:
  1. Create the file from scratch (including defining props interface, step rendering, and adding revert UI)
  2. Identify the component that currently renders the step timeline (likely `StepProgressBar` in `RunDetail.tsx`) and implement there instead.
  - **Remediation**: Before implementing T2, agent must search for where steps are currently rendered in the UI (search for `run.steps.map` or `steps.map` in `RunDetail.tsx` and other components). If `StepProgressBar` handles it, implement the revert action inline there and update the test path accordingly. If the component needs to be created, create `StepTimeline.tsx` with a full implementation.
- **`ConfirmationDialog` component**: Same concern as Step 4 — must verify this component exists.
- **`currentStepIndex` prop**: The Vitest test assumes `StepTimeline` receives a `currentStepIndex` prop. If the component is derived from `StepProgressBar`, this prop may not exist and must be derived from the step array.

---

## Step 9: Branch Status Panel and Back-Merge

### Tasks: T1 (types + client), T2 (hooks), T3 (BranchStatusPanel + RunDetail + Vitest)

**Assumptions**
- Backend `GET /api/runs/{id}/branch-status` and `POST /api/runs/{id}/back-merge` exist
- `RunResponse`/`RunDetail` TypeScript type includes `worktree_path` field
- `BranchStatusResponse` fields match backend response exactly
- `ui/src/components/detail/` directory exists

**Expected Outputs**
- T1: `BranchStatusResponse` type; `getBranchStatus()` and `backMerge()` in `client.ts`
- T2: `useBranchStatus()` (30s polling) and `useBackMerge()` in `useApi.ts`
- T3: `BranchStatusPanel.tsx` at expected path; `RunDetail` mounts for ACTIVE/PAUSED with worktree; Vitest tests pass

**Blockers and Mitigations**
- **Backend endpoint path**: Endpoint name might differ (e.g., `/branch-status` vs `/git-status`). Agent must verify exact path in `runs.py` before implementing client function.
- **`can_merge_cleanly` vs `has_conflicts`**: The plan's `BranchStatusResponse` includes both fields, with the UI checking both (`has_conflicts || !can_merge_cleanly`). If the backend only returns one, the TypeScript type must be adjusted and the condition simplified.
- **30s polling in tests**: `refetchInterval: 30_000` will be active in Vitest tests if not mocked. Agent must configure `vi.useFakeTimers()` or mock `useBranchStatus` to avoid flaky async tests.
- **Conflict state disables button**: The "Pull upstream changes" button is disabled when `has_conflicts`. This UX decision should be validated — users with conflicts may need to resolve them via a different path. Note this gap but implement as specified.

---

## Step 10: Env File Management UI

### Tasks: T1 (types + 5 client functions), T2 (5 hooks), T3 (EnvFilesPanel + RunDetail + Vitest)

**Assumptions**
- Five backend env file endpoints exist in `runs.py` with paths matching the plan
- `run.env_file_specs` field exists on the `RunResponse` TypeScript type
- `ConfirmationDialog` exists for revert and copy-back confirmation flows
- Masked values are a backend guarantee; the frontend never has access to raw values

**Expected Outputs**
- T1: `EnvFile`, `EnvSnapshot`, `EnvDefaultTarget` types; 5 client functions exported
- T2: 3 query hooks + 2 mutation hooks in `useApi.ts`
- T3: `EnvFilesPanel.tsx` with current files list and snapshot table; confirmation dialogs; Vitest test passes

**Blockers and Mitigations**
- **Endpoint path verification**: Endpoint paths for env file operations must be confirmed against `runs.py` (e.g., `/env-files`, `/env-snapshots`, `/env-default-target`, `/env-snapshots/{id}/revert`, `/env-copy-back`). Any path mismatch results in 404s at runtime.
- **`EnvFile.masked_value` field**: The plan defines `masked_value: string`. Backend may use a different field name (e.g., `value_masked`, `masked`). Agent must read the backend schema.
- **`copyBackEnvFiles` target path UX**: The copy-back dialog in the plan initializes `copyBackPath` from `defaultTarget?.target_path`. If `defaultTarget` is undefined, the path is empty string `''`. The component's dialog open condition `copyBackPath !== ''` means it won't open if no default exists. Consider pre-populating from another source or allowing manual input.
- **Security**: Ensure no unmasked values are logged, rendered, or stored in component state. The plan correctly shows only `masked_value` in the template.

---

## Step 11: Surface Server GlobalConfig in Settings Panel

### Tasks: T1 (type + getConfig), T2 (useGlobalConfig), T3 (settings panel + run list + Vitest)

**Assumptions**
- Backend `GET /api/config` exists and returns a JSON response matching `GlobalConfig` interface
- A settings panel component exists somewhere in `ui/src/components/` or `ui/src/pages/`
- The run list uses a hardcoded constant for `max_recent_runs` that can be identified and replaced
- `GlobalConfig.active_agent_types` is a `string[]`

**Expected Outputs**
- T1: `GlobalConfig` type in `ui/src/types/`; `getConfig()` in `client.ts`
- T2: `useGlobalConfig()` with `staleTime: Infinity` in `useApi.ts`
- T3: Settings panel "Server" section renders DB path, agent types, max runs; run list uses server value; Vitest test passes

**Blockers and Mitigations**
- **Settings panel location**: The plan says to "locate the settings panel component." This component may not exist, or may be a simple inline render in a layout component. Agent must search for settings-related files before deciding where to add the "Server" section.
- **Run list hardcoded constant**: The hardcoded `max_recent_runs` constant may be in `useRuns()` query parameters or in a pagination component. If `useGlobalConfig` is async, there's a chicken-and-egg problem: the run list can't know the limit until config loads. The plan's solution (`?? <default_fallback>`) handles this, but the fallback value must be chosen sensibly (suggest 20 as default).
- **`GlobalConfig` schema**: The backend `GlobalConfig` model may have additional fields beyond `db_path`, `active_agent_types`, `max_recent_runs`. The TypeScript interface should be extended or use an index signature if the backend response is a superset.
- **`staleTime: Infinity` in tests**: TanStack Query with `staleTime: Infinity` means the query won't refetch between test cases sharing a QueryClient. Ensure Vitest tests create a fresh QueryClient per test.

---

## Step 12: Routine YAML Validation UI

### Tasks: T1 (validateRoutine + useValidateRoutine), T2 (RoutineValidatorModal), T3 (CreateRunModal integration + Vitest)

**Assumptions**
- Backend `POST /api/routines/validate` exists and returns `{ valid: boolean, errors: [{line: number, message: string}] }`
- `CreateRunModal.tsx` exists and handles run creation flow
- A `Modal` component exists that `RoutineValidatorModal` can use
- `RoutineSelector` is accessible from `CreateRunModal`

**Expected Outputs**
- T1: `validateRoutine()` in `client.ts`; `useValidateRoutine()` in `useApi.ts`
- T2: `RoutineValidatorModal.tsx` with textarea, Validate button, error list, success shortcut
- T3: `CreateRunModal` exposes a trigger; validator pre-fills run creation on success; Vitest tests pass

**Blockers and Mitigations**
- **Backend `validate` endpoint path**: Path might be `/api/routines/validate` or `/api/routine/validate` (singular). Agent must verify.
- **`Modal` component**: `RoutineValidatorModal` references a `Modal` component. If no generic `Modal` wrapper exists, agent must use whatever dialog/modal primitive is already present in the codebase (e.g., Radix Dialog, Headless UI Dialog, or a custom `BaseModal`).
- **`CreateRunModal` pre-fill pattern**: The plan has `setRoutineYaml(yaml)` but the actual state management in `CreateRunModal` may differ. Agent must read `CreateRunModal.tsx` to understand how routine content is currently managed before adding the pre-fill path.
- **`ValidationError` type location**: The plan puts `ValidationError` and `ValidationResult` in `client.ts`. Consider moving them to `ui/src/types/` for consistency with other types added in Steps 4, 7, 9, 10, 11.
- **Line number accuracy**: Backend-reported line numbers must be 1-indexed and match the textarea content. If the backend uses 0-indexed lines, the UI display should add 1.

---

## Cross-Cutting Gaps

### 1. `client.ts` API Object Pattern vs. Individual Exports
**Severity**: High
**Affects**: Steps 4, 6, 7, 8, 9, 10, 11, 12

The existing `client.ts` uses an object pattern (`api.listRuns()`, `api.getRun()`, etc.) rather than individual named exports. All step plans show individual function exports (`export async function recoverRun(...)`).

**Remediation**: Before implementing any step, agents must decide on one of:
1. **Extend the `api` object**: Add new methods to the existing object. Update hook calls accordingly.
2. **Export individual functions alongside the object**: Simpler for new additions, avoids touching existing patterns.

Whichever approach is chosen must be applied consistently across all 8 affected steps.

### 2. `ConfirmationDialog` Component
**Severity**: Medium
**Affects**: Steps 4, 8, 10

Multiple steps reference a `ConfirmationDialog` component. Its existence must be verified and its API (props: `title`, `description`, `onConfirm`, `onCancel`) confirmed before use. If absent, a shared `ConfirmationDialog` component should be created first.

### 3. `ui/src/components/detail/` Directory
**Severity**: Low
**Affects**: Steps 4, 6, 9, 10

Multiple new component files target `ui/src/components/detail/`. This directory may not exist. Agent for Step 4 (first to create a file there) must create the directory.

### 4. Type Consistency Across Steps
**Severity**: Low
**Affects**: Steps 4, 7, 9, 10, 11, 12

Each step defines new TypeScript types in isolation. Several types reference common patterns (e.g., run status strings as string literals vs. enums, API error shapes). A shared `ui/src/types/index.ts` re-export file should be maintained as types are added, or each type file should be self-contained.

### 5. Frontend Test Infrastructure
**Severity**: Low
**Affects**: Steps 4, 6, 7, 8, 9, 10, 11, 12

All frontend Vitest tests mock TanStack Query hooks. The existing test infrastructure (Vitest setup, React Testing Library, mock patterns) must be confirmed before writing new tests. Agents should reference existing test files in `ui/src/` for the correct mock patterns rather than inventing new ones.

---

## Execution Order Risks

| Risk | Steps | Mitigation |
|------|-------|-----------|
| Step 4 (UI) deployed before Step 3 (API) | 3 → 4 | Deploy backend first; UI shows no-op state gracefully |
| Step 2 gate prompts deployed before Step 1 GateBlockedError fix | 1 → 2 | Agents get actionable prompts but still die on GateBlockedError. Deploy Step 1 first. |
| Step 5 T1 (server phase param) deployed before T2 (executor passes phase) | 5-T1 → 5-T2 | Safe: default `"building"` means all connections get builder tools until T2 is deployed |
| Multiple steps modifying `client.ts` and `useApi.ts` concurrently | 4–12 | Serialize these steps or use a feature-branch merge strategy to avoid conflicts |

---

## Verification Checkpoint Summary

| Step | Backend Tests | Frontend Tests | Static Analysis |
|------|--------------|----------------|-----------------|
| 1    | `pytest -k gate_blocked` | — | `pyright`, `ruff` on cli.py + executor.py |
| 2    | yaml.safe_load | — | — |
| 3    | `pytest -k recover` | — | `pyright`, `ruff` on schemas + service + router |
| 4    | — | `npx vitest run` (RecoveryPanel) | `tsc --noEmit` |
| 5    | `pytest -k "mcp or phase_filter"` | — | `pyright`, `ruff` on server.py + executor.py |
| 6    | — | `npx vitest run` (StepApprovalBanner) | `tsc --noEmit` |
| 7    | — | `npx vitest run` (AgentGuidancePanel) | `tsc --noEmit` |
| 8    | — | `npx vitest run` (StepTimeline) | `tsc --noEmit` |
| 9    | — | `npx vitest run` (BranchStatusPanel) | `tsc --noEmit` |
| 10   | — | `npx vitest run` (EnvFilesPanel) | `tsc --noEmit` |
| 11   | — | `npx vitest run` (SettingsPanel) | `tsc --noEmit` |
| 12   | — | `npx vitest run` (RoutineValidatorModal) | `tsc --noEmit` |
