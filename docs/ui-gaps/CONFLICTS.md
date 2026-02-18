# Conflicts: UI Gaps — Wire Remaining Backend Endpoints to Frontend

## Status

No unresolved conflicts.

All design questions (Q1–Q8) have been resolved in Stage 3 Plan Refinement using [HUMAN] annotations and backend code inspection. Decisions are recorded in `design-questions.md` and incorporated into `intent.md`, `plan.md`, and `architecture.md`.

## Resolved During Stage 3

| Question | Resolution |
|----------|------------|
| Q1: Step approval UI pattern | Option 1 — Separate `StepApprovalModal` |
| Q2: Step approval location | Option 3 — Both sticky banner AND inline in accordion |
| Q3: Step approvals in pending-actions | Extend backend `GET /api/runs/{id}/pending-actions` |
| Q4: Guidance vs task-prompt endpoint | Additive (keep `useTaskPrompt`, add `useGuidance` for mcp_url + expected_actions) |
| Q5: Backward transition trigger | Option 2 — Dropdown on step progress bar |
| Q6: `agentCancelled` behavior | Transition to PAUSED; backend change required |
| Q7: `target_step_index` type | Zero-based integer (confirmed by backend code) |
| Q8: SSE settings toggle | Already implemented in `SettingsModal.tsx`; only status indicator needed |
