# Intent: UI Gaps — Wire Remaining Backend Endpoints to Frontend

## Original Request

Connect backend endpoints that already exist and have test coverage to the UI. Six endpoint groups are currently unreachable from the browser:

1. Step-level human approval (`POST /api/runs/{id}/steps/{step_id}/approve`)
2. Activity SSE streaming settings toggle (`GET /api/runs/{id}/activity/stream` + settings UI)
3. External agent lifecycle hooks (`POST /api/runs/{id}/agent-started`, `POST /api/runs/{id}/agent-cancelled`)
4. External agent guidance aggregate endpoint (`GET /api/runs/{id}/guidance`)
5. Backward step transitions (`POST /api/runs/{id}/transition-back`)
6. Branch status and back-merge (`GET /api/runs/{id}/branch-status`, `POST /api/runs/{id}/back-merge`)

Source: `docs/PARTIAL-FEATURES.md`

## Goal

Every backend endpoint listed in `docs/PARTIAL-FEATURES.md` (for the six groups above) is accessible through the web UI. Users can perform the full human-in-the-loop workflow, external agent signaling, step navigation, and branch operations without using the CLI or calling the API directly.

## Scope

### In Scope

- **Step-level approval**: API client function, mutation hook, and inline approval prompt in `RunDetail.tsx` for steps with `has_approval_gate && approval_status === 'pending'`. Step approvals must also appear in `usePendingActions` and `PendingActionsBadge` — requires extending the `GET /api/runs/{id}/pending-actions` backend endpoint to include pending step gates. Step approval UI appears both as a sticky banner at the top of `RunDetail.tsx` AND inline within the relevant `StepAccordion` section.
- **Activity SSE mode toggle**: Settings panel toggle to switch `activityStreamMode` between `'sse'` and `'polling'`. Default SSE. Connection status indicator in the activity feed.
- **External agent lifecycle buttons**: `agentStarted(runId)` and `agentCancelled(runId)` API client functions, mutation hooks, and UI buttons in `AgentGuidancePanel` and `WaitingIndicator`. `agentCancelled` transitions the run to PAUSED (not FAILED) so the user can restart — requires a backend change to `POST /api/runs/{id}/agent-cancelled` and the underlying service/engine.
- **Guidance aggregate endpoint**: `getGuidance(runId)` API client function, `useGuidance` hook; `AgentGuidancePanel` adds `useGuidance` as a data source for `mcp_url` and `expected_actions` (additive — keeps `useTaskPrompt` for the detailed separated system/user prompts). `GuidanceResponse` type definition.
- **Backward step transitions**: `transitionBack(runId, { target_step_index: int })` API client (zero-based integer index), `useTransitionBack` mutation hook, dropdown menu on the step progress bar ("Revert to step…") in `RunDetail.tsx`, confirmation dialog warning about state reset. Router docstrings updated to document `target_step_index`.
- **Branch status and back-merge**: `getBranchStatus(runId)` and `backMerge(runId)` API client functions, `BranchStatusResponse` type, query and mutation hooks, display of ahead/behind counts and merge conflict status in `RunDetail.tsx`, back-merge button with confirmation.
- Backend changes where required: extend `GET /api/runs/{id}/pending-actions` to include step approval gates; fix `POST /api/runs/{id}/agent-cancelled` to transition to PAUSED; improve router docstrings for `transition-back`.
- TypeScript types for all new API responses
- Query cache invalidation on mutations

### Out of Scope

- New backend API endpoints beyond the two corrections noted above
- Backend bug fixes unrelated to the wiring work
- Features not listed in `docs/PARTIAL-FEATURES.md` (e.g., env file management UI, routine YAML validation, global config endpoint — left for separate work)
- Vitest unit tests (no test infrastructure currently configured for components)
- Accessibility audit
- Mobile-specific responsive design
- Authentication or authorization changes

## Definition of Complete

- [ ] `approveStep(runId, stepId, data: StepApprovalRequest)` exists in `ui/src/api/client.ts` calling `POST /api/runs/{id}/steps/{step_id}/approve`
- [ ] `useApproveStep` mutation hook exists and invalidates `['run', runId]` on success
- [ ] `StepApprovalModal` component exists (separate from `ApprovalModal`); triggered from `RunDetail.tsx` when a step has `has_approval_gate && approval_status === 'pending'`
- [ ] Step approval prompt appears both inline in `StepAccordion` AND as a sticky banner at the top of `RunDetail.tsx`
- [ ] `GET /api/runs/{id}/pending-actions` backend endpoint extended to include pending step approval gates
- [ ] Step-level pending approvals appear in `usePendingActions` results and `PendingActionsBadge`
- [ ] Settings panel has a toggle for `activityStreamMode` (`'sse'` | `'polling'`)
- [ ] Activity feed shows an SSE connection status indicator (connected/disconnected)
- [ ] `agentStarted(runId)` and `agentCancelled(runId)` API client functions exist
- [ ] `useAgentStarted` and `useAgentCancelled` mutation hooks exist
- [ ] `AgentGuidancePanel` has an "I've started my agent" button wired to `useAgentStarted`
- [ ] `WaitingIndicator` cancel calls `agentCancelled` (replaces run-level cancel in this context)
- [ ] `POST /api/runs/{id}/agent-cancelled` backend updated to transition run to PAUSED (not FAILED)
- [ ] `getGuidance(runId)` API client function exists calling `GET /api/runs/{id}/guidance`
- [ ] `useGuidance` hook exists with appropriate refetch strategy
- [ ] `GuidanceResponse` TypeScript type is defined
- [ ] `AgentGuidancePanel` uses `useGuidance` additively: `mcp_url` and `expected_actions` sourced from guidance; detailed prompt text sourced from `useTaskPrompt`
- [ ] `transitionBack(runId, { target_step_index: number })` API client function exists (integer index, not UUID)
- [ ] `useTransitionBack` mutation hook exists and invalidates `['run', runId]` and `['activity', runId]`
- [ ] `RunDetail.tsx` step progress bar has a dropdown menu ("Revert to step…") to trigger backward transitions
- [ ] A confirmation dialog warns the user that going back will reset task states in the target step
- [ ] `GET /api/runs/{id}/transition-back` router docstrings document `target_step_index` as a zero-based integer
- [ ] `getBranchStatus(runId)` and `backMerge(runId)` API client functions exist
- [ ] `BranchStatusResponse` TypeScript type is defined with `ahead`, `behind`, `mergeable` (and conflict fields)
- [ ] Branch status (ahead/behind counts, conflict warning) is displayed on `RunDetail.tsx`
- [ ] A back-merge button with confirmation dialog exists on `RunDetail.tsx` and calls `backMerge`
- [ ] `tsc --noEmit` passes after all changes
