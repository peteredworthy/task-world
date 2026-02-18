# Intent: Enhanced Clarification System

## Original Request

The current clarification system (`workflow/clarifications.py`, `mcp/clarification_tools.py`, `api/routers/clarifications.py`, `ClarificationModal`) provides a basic multi-choice + free-text-override flow. This enhancement adds:

1. **Richer question types** – `single_select`, `multi_select`, `free_text`, `number` with per-question `required` flag
2. **WebSocket push** – `ClarificationRequested` events broadcast immediately so the UI reacts without waiting for the 10s poll cycle
3. **Answer history in the activity timeline** – completed clarification rounds shown as expandable cards in the activity feed
4. **Line-number-aware builder prompts** – after answers are written to the artifact file, the builder's resume prompt includes the file path and exact line range
5. **User force-skip** – users can skip optional questions or force-skip an entire clarification request with a reason

## Goal

Enable the builder agent to ask richer, more precise questions during a run; allow the human to answer them efficiently via improved UI; and ensure the builder resumes with maximal context (line references, skip signals) so that clarification rounds translate directly into better code output. Every sub-feature must leave the system in a runnable, testable state.

## Scope

### In Scope

- Extend `ClarificationQuestion` model with `question_type` (`single_select` | `multi_select` | `free_text` | `number`), `allow_other`, `required`, `min`, `max`, `placeholder`
- Extend `ClarificationAnswer` model with `skipped` and `skip_reason` fields
- Update `CLARIFICATION_TOOL` inputSchema in `mcp/clarification_tools.py` to expose the new question-type fields to the LLM
- Update `api/schemas/clarifications.py` to match new model fields
- Update `RespondToClarificationRequest` schema to accept `skipped: bool` and `skip_reason: str`
- Broadcast `ClarificationRequested` / `ClarificationResponded` over the run's WebSocket channel
- Handle `clarification_requested` WebSocket event in `useWebSocket.ts` to invalidate pending-actions immediately
- Add `GET /api/runs/{id}/tasks/{task_id}/clarifications` endpoint returning all historical clarification rounds for a task
- Render clarification history in the activity feed as expandable cards
- Return line range metadata from `format_clarification_artifact` and thread it through `workflow/service.py` → `workflow/prompts.py`
- Add "Skip remaining" button to `ClarificationModal` with optional reason text
- Update `QuestionCard` to render each question type and validate number min/max
- Update `ClarificationModal` answer validation to respect `required` flag and `question_type`
- Add `skipped` / `skip_reason` fields to `RespondToClarificationRequest` TypeScript type
- All backend changes covered by integration tests; all frontend changes exercisable in the running dev environment

### Out of Scope

- Authentication / authorization changes
- Changes to the approval workflow (step-level or task-level)
- Persistent UI settings for clarification preferences
- Rich YAML editor or routine validation UI (tracked separately)
- WebSocket infrastructure changes beyond adding a new event handler
- Mobile / accessibility audit (handled in a later pass)

## Definition of Complete

- [ ] `ClarificationQuestion` in `workflow/clarifications.py` has `question_type`, `allow_other`, `required`, `min`, `max`, `placeholder` fields with correct defaults and validation
- [ ] `ClarificationAnswer` has `skipped` and `skip_reason` fields; `format_clarification_artifact` renders skipped answers correctly
- [ ] `format_clarification_artifact` returns (text, start_line, end_line) so callers can reference the appended section
- [ ] `workflow/service.py` passes line range to `generate_builder_prompt` after a clarification response
- [ ] `generate_builder_prompt` in `workflow/prompts.py` includes file path and line range in the resume prompt when `clarification_line_range` is provided
- [ ] `CLARIFICATION_TOOL` inputSchema exposes `question_type` and type-specific fields; validation enforces `options` required for select types and absent for others
- [ ] `api/schemas/clarifications.py` reflects all new fields; `RespondToClarificationRequest` accepts `skipped` and `skip_reason`
- [ ] `api/routers/clarifications.py` `respond_to_clarification` handles `skipped=True` by recording partial answers without requiring all required questions to be answered; builder resume prompt includes skip signal
- [ ] `GET /api/runs/{run_id}/tasks/{task_id}/clarifications` returns all historical request+response pairs for the task
- [ ] `ClarificationRequested` and `ClarificationResponded` events include full Q&A payload and are broadcast via WebSocket
- [ ] `useWebSocket.ts` handles `clarification_requested` event by invalidating `['pending-actions', runId]` and `['pending-clarification', runId, taskId]`
- [ ] `ui/src/types/clarifications.ts` has all new fields for `ClarificationQuestion`, `ClarificationAnswer`, `RespondToClarificationRequest`
- [ ] `QuestionCard.tsx` renders `single_select` (radio), `multi_select` (checkboxes), `free_text` (textarea), `number` (number input with min/max validation) correctly
- [ ] `ClarificationModal.tsx` validates answers per `required` flag and question type; shows "Skip remaining" button; submits `skipped: true` with partial answers
- [ ] Activity feed renders `clarification_responded` events as expandable cards showing round number, each Q&A, and timestamp
- [ ] Integration tests pass for all new backend endpoints and modified endpoints
- [ ] `uv run pre-commit run --all-files` passes (ruff, mypy, eslint, etc.)
