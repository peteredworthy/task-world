# Execution Summary: Enhanced Clarification System

**Date:** 2026-02-17
**Plan Status:** Ready for execution
**Verification Status:** ✅ Cross-checked and gap-tracked

---

## Intent Satisfaction Summary

The plan fully satisfies all five sub-features from the original intent:

| Sub-feature | Intent Requirement | Satisfied By |
|---|---|---|
| 10a | Richer question types (`single_select`, `multi_select`, `free_text`, `number`) with per-question `required`, `allow_other`, `min`, `max`, `placeholder` | Steps 1 + 4 |
| 10b | WebSocket push for `ClarificationRequested` / `ClarificationResponded` events | Steps 3 + 5 |
| 10c | Answer history in the activity timeline as expandable cards | Steps 2 + 5 |
| 10d | Line-number-aware builder resume prompts | Steps 1 + 2 |
| 10e | User force-skip with optional reason text | Steps 1 + 4 |

All 15 Definition-of-Complete criteria in `intent.md` are covered by at least one step. No intent requirement is orphaned. The system remains backward-compatible: existing `single_select` questions work without change.

---

## Ordered Step List with Task Counts

| Step | Milestone | Task Count | Key Deliverable |
|---|---|---|---|
| Step 1 | Data Model & MCP Tool (10a backend) | 4 tasks | Extended `ClarificationQuestion` / `ClarificationAnswer` models, updated `format_clarification_artifact` return type, updated `CLARIFICATION_TOOL` inputSchema, updated API schemas and router, integration tests |
| Step 2 | Prompt Changes & History Endpoint (10d + history backend) | 5 tasks | `service.py` artifact-write flow with line-range capture, `generate_builder_prompt` with line-range and skip signal, `GET /api/runs/{id}/tasks/{task_id}/clarifications` endpoint, integration tests |
| Step 3 | WebSocket Push (10b) | 3 tasks | `ClarificationRequested` / `ClarificationResponded` events broadcast over WebSocket with minimal payload, integration test |
| Step 4 | Frontend – Question Types & Skip (10a + 10e frontend) | 3 tasks | TypeScript types extended, `QuestionCard` branches on `question_type`, `ClarificationModal` multi-select state + validation + "Skip remaining" flow |
| Step 5 | Frontend – WebSocket Handler & History UI (10b + 10c frontend) | 5 tasks | `useWebSocket` cache invalidation handlers, `useClarificationHistory` hook, `ClarificationHistoryCard` component, activity feed wiring |

**Total:** 20 tasks across 5 steps.

**Execution order:** Steps 1 → 2 → (3 concurrent with 4) → 5. Step 3 can start concurrently with Step 2 once Step 1 stabilises the model; Step 4 can also start after Step 1. Step 5 requires Steps 2, 3, and 4.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Backward compatibility for `question_type` | Default `'single_select'`, `required=True` | Existing MCP tool callers and stored data remain valid without migration |
| `format_clarification_artifact` return type | `tuple[str, int, int]` (text, start_line, end_line) | Cleanest way to return line range without side effects; callers can ignore if not needed |
| `multi_select` answer encoding | Additive `selected_options: list[str]` field on `ClarificationAnswer` | Adds one new field rather than repurposing `selected_option`; avoids comma-encoding hacks |
| Skip handling | Accept partial answers when `skipped=True`; do not require all `required` questions | Matches intent: user signals "proceed with incomplete info" |
| WebSocket payload size | Minimal (IDs + counts only); frontend fetches full data via existing API | Avoids bloating WS messages; frontend already queries pending clarification |
| History endpoint scope | All rounds including pending (distinguished by `responded_at`) | Provides full context; `response: null` for pending rounds |
| Activity feed history source | `GET /api/runs/{id}/tasks/{task_id}/clarifications` (new endpoint) | Decouples history from the event log; provides structured Q&A data the feed can render directly |
| Number validation scope | Client-side only for MVP | Avoids server-side validation complexity for an MVP number input |

---

## Risks and Mitigations

### High – Step-file code is actively wrong (will silently fail if followed literally)

| Risk | Location | Mitigation |
|---|---|---|
| **GAP-16:** `q.text` in `ClarificationHistoryCard.tsx` should be `q.question` | Step 5, Task 4 | Builder must use `q.question`; field name confirmed in `workflow/clarifications.py` |
| **GAP-08:** Sync SQLAlchemy pattern (`self.session.query(...)`) in repository snippet | Step 2, Task 3 | Builder must use async pattern: `await self._session.execute(select(...))`. Sync pattern causes `MissingGreenlet` at runtime |
| **GAP-09:** `ClarificationHistoryItem.request` typed as `ClarificationQuestionSchema` (single question) | Step 2, Task 4 | Builder must use full `ClarificationRequestResponse` schema for `request` and a new `ClarificationResponseSchema` for `response` |

### Medium – Incomplete specification (builder must fill in)

| Risk | Location | Mitigation |
|---|---|---|
| **GAP-06:** Entire artifact-write flow is missing from `service.py:respond_to_clarification` | Step 2, Task 1 | Builder must: (1) resolve artifact path from `GlobalConfig` or run worktree convention, (2) call `build_artifact_header()` if new file, (3) call `format_clarification_artifact`, (4) append to file, (5) track `clarification_number` via prior-response count |
| **GAP-14:** `ClarificationResponse` TypeScript interface is referenced but not defined | Step 4, Task 1 | Builder must add interface to `clarifications.ts` with fields: `request_id`, `answers: ClarificationAnswer[]`, `responded_at: string`, `skipped: bool`, `skip_reason: string \| null` |
| **GAP-18:** `useClarificationHistory` called at `RunDetail` level but events span multiple tasks | Step 5, Task 5 | Builder must call hook inside per-event renderer (pass `task_id` from event payload), not once at `RunDetail` level |

### Low – Expected gaps (non-blocking; builder self-corrects by reading files)

| Risk | Mitigation |
|---|---|
| **GAP-04:** "Required questions guard" doesn't exist yet; step assumes it does | Add the guard as part of Step 1, Task 3; then add the `skipped` bypass |
| **GAP-10:** Step file references `ClarificationRepository` class that doesn't exist | Use `RunRepository` with the new `get_clarification_history` method |
| **GAP-12:** Broadcast function name needs verification | Step 3, Task 2 instructs "read `api/websocket.py` fully first" |
| **GAP-05:** Integration test for `skipped=True` depends on Step 2 artifact-writing | Defer full `skipped` flow integration test to Step 2; note dependency in Step 1 test plan |

---

## Caveats for Execution

1. **Read files before editing.** The highest-risk gaps (GAP-06, GAP-08, GAP-09, GAP-16) all stem from step-file code snippets that do not match the actual codebase. Read the referenced source file fully before implementing each task.

2. **Step 1 is a hard prerequisite.** Steps 2, 3, 4, and 5 all depend on the extended model contracts established in Step 1. Do not attempt concurrent execution of later steps before Step 1 is merged and tests are green.

3. **Step 2, Task 1 requires the most judgment.** The artifact-write flow is entirely absent from the current `service.py`. The builder must discover the artifact path convention from the surrounding codebase (check `GlobalConfig`, existing worktree path conventions, and any `artifact_path` references in `service.py`) before writing code.

4. **Async SQLAlchemy throughout.** The entire backend uses `AsyncSession` with `await self._session.execute(select(...))`. Any synchronous ORM pattern will cause a `MissingGreenlet` error at runtime.

5. **CSS: use Tailwind utility classes.** The frontend uses Tailwind utilities, not BEM-style class names. `ClarificationHistoryCard` code snippets in step files use BEM names; replace with Tailwind classes consistent with neighboring components.

6. **`pre-commit` must pass after each step.** Run `uv run pre-commit run --all-files` before considering any step done. This validates ruff, mypy, eslint, and other hooks.

7. **`AnswerState` coupling.** Step 4, Task 2 (`QuestionCard`) uses `AnswerState.selectedOptions` which is defined in Task 3 (`ClarificationModal`). Implement Tasks 2 and 3 in the same session to avoid a broken intermediate state.

8. **History hook placement.** The `useClarificationHistory` hook must be called per-event (inside the activity feed event renderer), not once at the `RunDetail` level, because a single run has events from multiple tasks with different `task_id` values.

9. **`clarification_number` source.** `format_clarification_artifact` requires a `clarification_number` int. Derive this from a count of prior clarification requests for the task (`RunRepository` or a simple count query) before calling the function.

10. **No unresolved conflicts.** `CONFLICTS.md` has no `[HUMAN]` annotations; all five design questions in `design-questions.md` carry documented recommendations. Builders should treat those recommendations as resolved decisions.

---

## Planning Artifact Index

| Artifact | Purpose |
|---|---|
| `intent.md` | Original requirements and Definition of Complete |
| `plan.md` | 5-milestone implementation plan with key decisions |
| `design-questions.md` | 5 design questions with resolved recommendations |
| `architecture.md` | Component-level design |
| `step-01-plan.md` – `step-05-plan.md` | High-level plan per step |
| `steps/step-01.md` – `steps/step-05.md` | Atomic execution tasks (20 tasks total) |
| `dry-run-notes.md` | Pre-execution simulation with 18 identified gaps |
| `verification-report.md` | Stage 7 cross-check of all artifacts |
| `CONFLICTS.md` | Design conflict log (no unresolved conflicts) |
| `final-plan-summary.md` | Stage 8 readiness assessment |
