# Final Plan Summary: Enhanced Clarification System

**Date:** 2026-02-17
**Stage:** 8 – Final Plan Review
**Status:** Ready for execution

---

## Feature Overview

Enhance the existing clarification system to support richer question types, real-time WebSocket push, answer history in the activity timeline, line-number-aware builder prompts, and user force-skip with reason.

---

## Planning Artifacts

| Artifact | Location | Purpose |
|---|---|---|
| `intent.md` | `docs/enhanced-clarifications/intent.md` | Original requirements and definition of complete |
| `plan.md` | `docs/enhanced-clarifications/plan.md` | 5-milestone implementation plan |
| `design-questions.md` | `docs/enhanced-clarifications/design-questions.md` | 5 design decisions with recommendations |
| `architecture.md` | `docs/enhanced-clarifications/architecture.md` | Component-level design |
| `step-01-plan.md` | `docs/enhanced-clarifications/step-01-plan.md` | Step 1 high-level plan |
| `step-02-plan.md` | `docs/enhanced-clarifications/step-02-plan.md` | Step 2 high-level plan |
| `step-03-plan.md` | `docs/enhanced-clarifications/step-03-plan.md` | Step 3 high-level plan |
| `step-04-plan.md` | `docs/enhanced-clarifications/step-04-plan.md` | Step 4 high-level plan |
| `step-05-plan.md` | `docs/enhanced-clarifications/step-05-plan.md` | Step 5 high-level plan |
| `steps/step-01.md` | `docs/enhanced-clarifications/steps/step-01.md` | Atomic execution tasks for Step 1 |
| `steps/step-02.md` | `docs/enhanced-clarifications/steps/step-02.md` | Atomic execution tasks for Step 2 |
| `steps/step-03.md` | `docs/enhanced-clarifications/steps/step-03.md` | Atomic execution tasks for Step 3 |
| `steps/step-04.md` | `docs/enhanced-clarifications/steps/step-04.md` | Atomic execution tasks for Step 4 |
| `steps/step-05.md` | `docs/enhanced-clarifications/steps/step-05.md` | Atomic execution tasks for Step 5 |
| `dry-run-notes.md` | `docs/enhanced-clarifications/dry-run-notes.md` | Pre-execution simulation results |
| `verification-report.md` | `docs/enhanced-clarifications/verification-report.md` | Cross-check report (Stage 7) |
| `CONFLICTS.md` | `docs/enhanced-clarifications/CONFLICTS.md` | Design conflict log |

---

## Implementation Plan

### Step 1: Data Model & MCP Tool (Milestone 1)

**Files:** `workflow/clarifications.py`, `mcp/clarification_tools.py`, `api/schemas/clarifications.py`, `api/routers/clarifications.py`, integration tests

**Deliverables:**
- Extend `ClarificationQuestion` with `question_type`, `allow_other`, `required`, `min`, `max`, `placeholder`
- Extend `ClarificationAnswer` with `selected_options`, `skipped`, `skip_reason`
- `format_clarification_artifact` returns `tuple[str, int, int]`
- Updated MCP tool inputSchema with all 4 question types
- Updated API schemas and router with `skipped` handling
- Integration tests for all new fields and skip path

### Step 2: Prompt Changes & History Endpoint (Milestone 2)

**Files:** `workflow/service.py`, `workflow/prompts.py`, `api/routers/clarifications.py`, `api/schemas/clarifications.py`, integration tests

**Deliverables:**
- `service.py` captures `(start_line, end_line)` from artifact; passes to prompt generator
- `generate_builder_prompt` includes line-range reference and skip signal in resume prompt
- `GET /api/runs/{run_id}/tasks/{task_id}/clarifications` history endpoint
- `ClarificationHistoryResponse` schema with full request+response pairs
- Integration tests for prompt content and history endpoint

### Step 3: WebSocket Push (Milestone 3)

**Files:** `workflow/events.py`, `api/websocket.py`, integration tests

**Deliverables:**
- `ClarificationRequested` and `ClarificationResponded` events broadcast over WebSocket with minimal payload (IDs + counts)
- Integration test asserting WebSocket message contains expected fields

### Step 4: Frontend – Question Types & Skip (Milestone 4)

**Files:** `ui/src/types/clarifications.ts`, `ui/src/components/detail/QuestionCard.tsx`, `ui/src/components/detail/ClarificationModal.tsx`

**Deliverables:**
- TypeScript types extended with all new fields; `ClarificationResponse` interface added
- `QuestionCard` renders radio buttons, checkboxes, textarea, number input with validation
- `ClarificationModal` validates per `required` flag; "Skip remaining" button with reason textarea
- Backward-compatible with existing `single_select` questions

### Step 5: Frontend – WebSocket Handler & History UI (Milestone 5)

**Files:** `ui/src/hooks/useWebSocket.ts`, `ui/src/types/activity.ts`, `ui/src/hooks/useClarificationHistory.ts`, `ui/src/components/detail/ClarificationHistoryCard.tsx`, activity feed component

**Deliverables:**
- `useWebSocket` handles `clarification_requested` and `clarification_responded` events → cache invalidation
- `ClarificationRequestedPayload` and `ClarificationRespondedPayload` TypeScript types
- `useClarificationHistory` hook for `GET /api/runs/{id}/tasks/{task_id}/clarifications`
- `ClarificationHistoryCard` component rendering Q&A pairs, collapsed by default
- Activity feed wires history cards per-event (not at `RunDetail` level)

---

## Design Decisions

| Decision | Choice |
|---|---|
| `multi_select` encoding | Additive `selected_options: list[str]` field on `ClarificationAnswer` |
| Skip signal in builder prompt | Inline skip summary in prompt text |
| History endpoint scope | All rounds including pending (distinguished by `responded_at`) |
| WebSocket payload size | Minimal (IDs + counts only); frontend fetches full data via existing API |
| Number validation scope | Client-side only for MVP |

---

## Known Issues for Builders

### High Priority (step-file code is actively wrong — must correct)

1. **GAP-16 / Step 5, Task 4:** Use `q.question` not `q.text` in `ClarificationHistoryCard.tsx`
2. **GAP-08 / Step 2, Task 3:** Use async SQLAlchemy (`await self._session.execute(select(...))`) not sync pattern
3. **GAP-09 / Step 2, Task 4:** Use full `ClarificationRequestResponse` schema in `ClarificationHistoryItem`, not single-question schema

### Medium Priority (incomplete specification — builder must fill in)

4. **GAP-06 / Step 2, Task 1:** Resolve `artifact_path` from `service.py`; implement full artifact write flow
5. **GAP-14 / Step 4, Task 1:** Add `ClarificationResponse` TypeScript interface to `clarifications.ts`
6. **GAP-18 / Step 5, Task 5:** Call `useClarificationHistory` per-event, not once at `RunDetail` level

---

## Readiness Assessment

| Dimension | Status |
|---|---|
| All intent requirements covered | ✅ |
| All design questions resolved | ✅ |
| No unresolved conflicts | ✅ |
| All step files verified against plan | ✅ |
| Known code errors documented | ✅ |
| Pre-execution blockers | None |

**The plan is ready for execution.**
