# Verification Report: Enhanced Clarification System

**Date:** 2026-02-17
**Stage:** 7 – Cross-check all plan artifacts for consistency and readiness
**Status:** ✅ Ready for execution with tracked gap remediations

---

## 1. Overview

This report verifies alignment across:
- `docs/enhanced-clarifications/intent.md` – original requirements
- `docs/enhanced-clarifications/plan.md` – milestone decomposition
- `docs/enhanced-clarifications/steps/step-01.md` through `step-05.md` – atomic execution tasks
- `docs/enhanced-clarifications/dry-run-notes.md` – pre-execution simulation results
- `docs/enhanced-clarifications/CONFLICTS.md` – design conflict log
- `docs/enhanced-clarifications/design-questions.md` – open design decisions
- `docs/enhanced-clarifications/architecture.md` – component-level design

---

## 2. Step Files vs. Plan Alignment

### Step 1 – Data Model & MCP Tool (Plan: Milestone 1)

| Plan Deliverable | Step File Coverage | Status |
|---|---|---|
| Extend `ClarificationQuestion` with 6 new fields | Task 1 – explicit field list with defaults | ✅ Aligned |
| Add Pydantic validator for `options` rules | Task 1 – full validator code provided | ✅ Aligned |
| Extend `ClarificationAnswer` with `selected_options`, `skipped`, `skip_reason` | Task 1 – explicit field list | ✅ Aligned |
| `format_clarification_artifact` returns `tuple[str, int, int]` | Task 1 – return type documented; sentinel 0 pattern explained | ✅ Aligned |
| Update `CLARIFICATION_TOOL` inputSchema | Task 2 – all 6 new properties defined | ✅ Aligned |
| Mirror fields in API schemas | Task 3 – all three schemas updated | ✅ Aligned |
| Router handles `skipped=True` | Task 3 – guard logic documented | ✅ Aligned (with GAP-04 note) |
| Integration + unit tests | Task 4 – concrete test list | ✅ Aligned |

**Note on GAP-04:** The plan implies a pre-existing "all required questions answered" guard in the router. The dry-run confirmed this guard does not yet exist. Step 1, Task 3 correctly describes adding the guard as part of this task. No remediation gap remains.

### Step 2 – Prompt Changes & History Endpoint (Plan: Milestone 2)

| Plan Deliverable | Step File Coverage | Status |
|---|---|---|
| `service.py` captures `(start_line, end_line)` from artifact | Task 1 – full code pattern with line-count pre-read | ✅ Aligned |
| `generate_builder_prompt` includes line-range + skip signal | Task 2 – template strings match architecture.md | ✅ Aligned |
| `BuilderPrompt` dataclass gets new fields | Task 2 – explicit field additions | ✅ Aligned |
| Repository method `get_clarification_history` | Task 3 – method signature and logic documented | ⚠️ See GAP-06/GAP-08 |
| `GET /api/runs/{id}/tasks/{task_id}/clarifications` endpoint | Task 4 – route and schema documented | ⚠️ See GAP-09/GAP-10 |
| Integration + unit tests for prompt and history | Task 5 – concrete test list | ✅ Aligned |

**GAP-06 (REQUIRED – addressed in step file):** The dry-run found that `service.py` does not currently call `format_clarification_artifact` at all—the entire artifact-write flow is missing. Step 2, Task 1 includes placeholder code (`artifact_path = ...`). **The builder must resolve this by finding the correct artifact path convention (from `GlobalConfig` or run worktree path) and implementing the full write flow.** The step file's instruction to "read the service file fully" before editing is critical.

**GAP-08 (REQUIRED – partially addressed):** Step 2, Task 3 shows synchronous SQLAlchemy query syntax (`self.session.query(...)`). The actual codebase uses async SQLAlchemy (`await self._session.execute(select(...))`). The task instructs the builder to "adapt class/method names to match the existing repository pattern," which should resolve this—however, the code snippet is misleading and may cause a `MissingGreenlet` error if followed literally. **The builder must use the async pattern.**

**GAP-09 (REQUIRED – partially addressed):** Step 2, Task 4 shows `ClarificationHistoryItem(request=ClarificationQuestionSchema, ...)` which is a single question schema, not a full request object. The architecture.md specifies the correct shape: `request: ClarificationRequest` (full request) and `response: ClarificationResponse | None`. The step file's instruction to "use the exact existing schema class names (check the file first)" should lead the builder to the correct types, but the sample code is wrong. **The builder must use the full request/response schema types, not single-question/answer schemas.**

**GAP-10 (EXPECTED – addressed):** Step 2, Task 4 references `ClarificationRepository(db)` but this class does not exist; methods are on `RunRepository`. The task notes "adapt to existing patterns," which is sufficient.

### Step 3 – WebSocket Push (Plan: Milestone 3)

| Plan Deliverable | Step File Coverage | Status |
|---|---|---|
| Audit `ClarificationRequested` / `ClarificationResponded` fields | Task 1 – read + verify + add if missing | ✅ Aligned |
| `question_count` field on event (if missing) | Task 1 – conditional addition shown | ✅ Aligned |
| WS broadcaster serializes both events | Task 2 – branch code with `broadcast_to_run` | ✅ Aligned (function name must be verified) |
| Minimal payload only (IDs + counts) per Q4 decision | Task 2 – explicitly constrainted | ✅ Aligned |
| Integration tests for WS events | Task 3 – test code pattern provided | ✅ Aligned |

**GAP-11 (OPTIONAL):** `run_id` is already on `ClarificationResponded` via inheritance from `WorkflowEvent`. Task 1 is essentially a no-op audit. Builder will confirm this on reading the file.

**GAP-12 (EXPECTED):** The actual broadcast function name must be verified in `api/websocket.py`. Task 2 instructs "read it fully first"—sufficient remediation.

### Step 4 – Frontend Question Types & Skip (Plan: Milestone 4)

| Plan Deliverable | Step File Coverage | Status |
|---|---|---|
| TypeScript types extended | Task 1 – all new fields listed; `ClarificationHistoryItem` added | ✅ Aligned |
| `ClarificationResponse` TS type | Task 1 includes `ClarificationHistoryItem` referencing `ClarificationResponse` | ⚠️ See GAP-14 |
| `QuestionCard` branches on `question_type` | Task 2 – all four branches with code | ✅ Aligned |
| `ClarificationModal` multi-select state + validation | Task 3 – `AnswerState` extension, `isAnswerComplete`, skip flow | ✅ Aligned |
| `handleSkipSubmit` implementation | Task 3 – full code provided | ✅ Aligned |

**GAP-14 (EXPECTED):** Step 4, Task 1's `ClarificationHistoryItem` references `ClarificationResponse` but this TypeScript interface is not defined anywhere. The builder must add `ClarificationResponse` to `clarifications.ts` (with `request_id`, `answers`, `responded_at`, `skipped`, `skip_reason` fields). This is not explicitly called out in Task 1's implementation steps.

**GAP-15 (OPTIONAL):** `AnswerState.selectedOptions` is used in Task 2 (QuestionCard) but defined in Task 3 (ClarificationModal). Since both tasks are in the same step, this is resolved if done together. No blocking issue.

### Step 5 – Frontend WebSocket Handler & History UI (Plan: Milestone 5)

| Plan Deliverable | Step File Coverage | Status |
|---|---|---|
| `ClarificationRequestedPayload` and `ClarificationRespondedPayload` TS types | Task 1 – interfaces defined | ✅ Aligned |
| `useWebSocket.processEvent` cache invalidation | Task 2 – both branches with guard for missing `task_id` | ✅ Aligned |
| `useClarificationHistory` hook | Task 3 – full hook code; adapter note for API client | ✅ Aligned |
| `ClarificationHistoryCard` component | Task 4 – full JSX provided; collapsed-by-default behavior | ⚠️ See GAP-16 |
| Wire `ClarificationHistoryCard` into activity feed | Task 5 – rendering branch and fallback | ⚠️ See GAP-18 |

**GAP-16 (REQUIRED):** Step 5, Task 4 renders question text as `{q.text}` but the actual API field is `q.question` (confirmed in `workflow/clarifications.py`). The code snippet will silently render nothing at runtime. **The builder must use `q.question` not `q.text` in `ClarificationHistoryCard.tsx`.**

**GAP-18 (EXPECTED):** Step 5, Task 5 instructs calling `useClarificationHistory(runId, taskId)` at the `RunDetail` level. However, `RunDetail` renders events for an entire run spanning multiple tasks; a single `taskId` call at this level will not cover all tasks' history. **The builder must call the hook per-task (inside the per-event renderer) or restructure the data-fetching to pass `task_id` from the event payload.** The task's instruction to "adapt to the exact event shape and rendering pattern" points in this direction but does not make the mismatch explicit.

---

## 3. Dry-Run Gap Resolution Status

### REQUIRED Gaps

| Gap | Description | Resolution Status |
|---|---|---|
| GAP-01 | `format_clarification_artifact` body doesn't branch on question type | ✅ Step 1, Task 1 now specifies per-type rendering; builder must implement |
| GAP-06 | Artifact-write flow entirely missing from `service.py` | ⚠️ Step 2, Task 1 has placeholder but builder must resolve `artifact_path` and full write flow |
| GAP-08 | Sync SQLAlchemy pattern in step file vs. async codebase | ⚠️ Step 2, Task 3 relies on "adapt to patterns" instruction—risk of builder following wrong snippet |
| GAP-09 | Wrong schema types in `ClarificationHistoryItem` | ⚠️ Step 2, Task 4 sample code uses single-question schema instead of full request schema |
| GAP-16 | `q.text` in ClarificationHistoryCard should be `q.question` | ⚠️ Step 5, Task 4 code snippet has incorrect field name—will silently break rendering |

**All five REQUIRED gaps have been identified and tracked. No gap is entirely unresolved—each has either been fixed in the step file or is covered by an instruction to read and adapt. The highest-risk items are GAP-06, GAP-08, and GAP-16 where the step file sample code is actively wrong.**

### EXPECTED Gaps (tracked, non-blocking)

| Gap | Description | Resolution |
|---|---|---|
| GAP-02 | Line count formula off-by-one edge case | Clarified in Step 1, Task 1 note |
| GAP-04 | "Required questions guard" doesn't exist yet | Step 1, Task 3 correctly adds it |
| GAP-05 | Skip integration test depends on Step 2 artifact write | Noted: test deferred to Step 2 |
| GAP-07 | `clarifications_path` vs `clarification_line_range` ambiguity | Include both; line-range is additive |
| GAP-10 | `ClarificationRepository` class doesn't exist | Use `RunRepository`; step notes "adapt to patterns" |
| GAP-12 | Broadcast function name must be verified | Task 2 instructs "read file fully first" |
| GAP-14 | Missing `ClarificationResponse` TypeScript type | Builder must add alongside history types |
| GAP-18 | `useClarificationHistory` at `RunDetail` level spans multiple tasks | Builder must call per-event or restructure |

### OPTIONAL Gaps (no action required)

| Gap | Description |
|---|---|
| GAP-03 | JSON path description inaccuracy in step file (builder self-corrects by reading file) |
| GAP-07 | Prompt field duplication (both paths are additive; either works) |
| GAP-11 | `run_id` on `ClarificationResponded` already present via inheritance |
| GAP-13 | WS test timeout flakiness in CI |
| GAP-15 | `AnswerState` coupling between Task 2 and Task 3 (same-session fix) |
| GAP-17 | `answer.question_id` matching confirmed correct |

---

## 4. Design Questions Alignment

| Question | Decision | Reflected in Steps |
|---|---|---|
| Q1: `multi_select` encoding | Option 1: additive `selected_options` field | ✅ Steps 1, 4 both specify the new field |
| Q2: Skip signal in prompt | Option 1: inline skip summary in prompt text | ✅ Step 2, Task 2 has the exact template string |
| Q3: History endpoint scope | Option 1: all rounds including pending | ✅ Step 2, Tasks 3–4 return pending with `response=None` |
| Q4: WebSocket payload size | Option 1: minimal (IDs + counts only) | ✅ Step 3, Task 2 explicitly constrains to minimal payload |
| Q5: Number validation scope | Option 1: client-side only for MVP | ✅ Step 4 validates client-side; no server-side guard added |

All five design questions have resolved recommendations documented in `design-questions.md`. The step files are consistent with all five decisions.

**Note:** `design-questions.md` still shows all five questions under "Open Questions" with no "Resolved Questions" section populated. The questions are functionally resolved (decisions documented inline), but the file's status markers still read "Open." This does not block execution—builders have access to the recommendations.

---

## 5. Intent vs. Step Coverage Matrix

| Intent Requirement | Covered By | Status |
|---|---|---|
| Richer question types: `single_select`, `multi_select`, `free_text`, `number` | Steps 1, 4 | ✅ |
| Per-question `required` flag | Steps 1, 4 | ✅ |
| WebSocket push for `ClarificationRequested` | Steps 3, 5 | ✅ |
| Answer history in activity timeline | Steps 2, 5 | ✅ |
| Line-number-aware builder prompts | Steps 1, 2 | ✅ |
| User force-skip with reason | Steps 1, 4 | ✅ |
| `allow_other` flag on select types | Steps 1, 4 | ✅ |
| `min`/`max` on number type | Steps 1, 4 | ✅ |
| `placeholder` for free_text/number | Steps 1, 4 | ✅ |
| Backend integration tests | Steps 1, 2, 3 | ✅ |
| TypeScript types updated | Step 4 | ✅ |
| Pre-commit checks pass (ruff, mypy, eslint) | Verification criteria in each step | ✅ |

All intent requirements are covered by at least one step file. No intent requirement is orphaned.

---

## 6. Critical Issues Summary

The following items require builder attention before or during execution:

### High Priority (code in step files is actively wrong)

1. **GAP-16 / Step 5, Task 4:** `q.text` → must be `q.question` in `ClarificationHistoryCard.tsx`
2. **GAP-08 / Step 2, Task 3:** Sync SQLAlchemy snippet → must use async pattern (`await self._session.execute(select(...))`)
3. **GAP-09 / Step 2, Task 4:** `ClarificationQuestionSchema` in `ClarificationHistoryItem` → must be full `ClarificationRequestResponse` schema

### Medium Priority (incomplete specification; builder must fill in)

4. **GAP-06 / Step 2, Task 1:** `artifact_path = ...` is a placeholder—builder must resolve the actual artifact path from `service.py` and implement the full write flow including `clarification_number` tracking
5. **GAP-14 / Step 4, Task 1:** `ClarificationResponse` TypeScript interface is referenced but not defined—builder must add it
6. **GAP-18 / Step 5, Task 5:** `useClarificationHistory` hook placement at `RunDetail` level is architecturally incorrect for multi-task runs—must be called per-event

---

## 7. Conflicts

**No unresolved critical conflicts remain.**

Per `CONFLICTS.md`: all design questions (Q1–Q5) carry documented recommendations. No `[HUMAN]` annotations were added during review. The CONFLICTS.md file accurately reflects the current state.

---

## 8. Overall Readiness Assessment

| Dimension | Assessment |
|---|---|
| Step files align with plan milestones | ✅ All 5 steps map 1:1 to plan milestones |
| Step files align with intent | ✅ All intent requirements covered |
| Dry-run gaps addressed | ✅ All REQUIRED gaps tracked; 3 step-file code errors documented for builder |
| Design questions resolved | ✅ All 5 questions have recommendations |
| No unresolved critical conflicts | ✅ CONFLICTS.md confirms clean slate |
| Pre-execution blockers | ⚠️ None blocking—all gaps are documentation/guidance issues, not missing infrastructure |

**Conclusion:** The plan is ready for execution. Builders should read `dry-run-notes.md` before starting each step, paying particular attention to the three step-file code errors (GAP-16, GAP-08, GAP-09) and the incomplete artifact-write specification (GAP-06). All gaps have concrete remediations; none require architectural redesign.
