# Step 02 Plan: Prompt Changes & History Endpoint (10d + history backend)

## Purpose

Wire the line-range data introduced in Step 1 into the builder resume prompt so the LLM knows exactly where in the artifact file to look for answers. Add the clarification history API endpoint so the frontend can display past Q&A rounds. Also surface the skip signal in the prompt so the builder can proceed with partial information.

## Prerequisites

- **Step 1 complete**: `format_clarification_artifact` must return `tuple[str, int, int]` (text, start_line, end_line); `ClarificationAnswer` must carry `skipped` and `skip_reason` fields.

## Functional Contract

### Inputs

- `respond_to_clarification(run_id, task_id, clarification_id, request)` in `workflow/service.py`:
  - Receives the updated `RespondToClarificationRequest` (with `skipped`, `skip_reason`, `selected_options` from Step 1).
  - Calls `format_clarification_artifact` and captures `(text, start_line, end_line)`.
- `generate_builder_prompt(...)` in `workflow/prompts.py`:
  - New optional parameter `clarification_line_range: tuple[str, int, int] | None` (path, start_line, end_line).
  - New optional parameters `skipped_questions: list[str] | None`, `skip_reason: str | None`.
- `GET /api/runs/{run_id}/tasks/{task_id}/clarifications`:
  - Path params: `run_id: str`, `task_id: str`.
  - No query params (returns all rounds including pending).

### Outputs

- Builder prompt text when `clarification_line_range` is provided includes:
  `"User answers have been written to {path} (lines {start}–{end}). Read that section for the answers."`
- Builder prompt text when `skipped_questions` is provided includes:
  `"The user declined to answer: {list}. Reason: {reason or 'none given'}. Proceed with your best judgment."`
- `GET .../clarifications` returns `ClarificationHistoryResponse`:
  ```json
  {
    "items": [
      {
        "request": { ...ClarificationRequest fields... },
        "response": { ...ClarificationResponse fields... } | null
      }
    ]
  }
  ```
  Ordered by creation time ascending; pending rounds have `response: null`.
- `BuilderPrompt` dataclass gains `clarification_line_range` and `skipped_questions` fields for test introspection.

### Errors

- History endpoint returns `404` if `run_id` or `task_id` not found.
- History endpoint returns `200` with empty `items` list if no clarification rounds exist yet.
- If `format_clarification_artifact` raises (e.g., file I/O error), the service propagates the exception (no swallowing).

## Tasks

1. Update `workflow/service.py` `respond_to_clarification`: capture `(text, start_line, end_line)` from `format_clarification_artifact`; count file lines before append to compute `start_line`; pass `clarification_line_range` and skip fields to `generate_builder_prompt`.
2. Update `workflow/prompts.py` `generate_builder_prompt`: accept `clarification_line_range`, `skipped_questions`, `skip_reason`; append appropriate sentences to the clarifications section of the prompt; update `BuilderPrompt` dataclass.
3. Add repository method `get_clarification_history(run_id, task_id)` returning `list[tuple[ClarificationRequest, ClarificationResponse | None]]`.
4. Add `ClarificationHistoryItem` and `ClarificationHistoryResponse` schemas in `api/schemas/clarifications.py`.
5. Add `GET /{run_id}/tasks/{task_id}/clarifications` route in `api/routers/clarifications.py` using the new repository method.
6. Write integration tests: verify prompt text contains line-range reference after respond; verify prompt text contains skip message when `skipped=True`; verify history endpoint returns completed and pending rounds correctly.

## Verification

### Auto-Verify

- [ ] `pytest tests/integration/ -k clarification` passes including new prompt and history tests.
- [ ] `pytest tests/unit/ -k prompts` passes; builder prompt contains line-range sentence when `clarification_line_range` is provided; skip sentence appears when `skipped_questions` provided.
- [ ] `mypy src/orchestrator/workflow/service.py src/orchestrator/workflow/prompts.py src/orchestrator/api/routers/clarifications.py` reports no errors.
- [ ] `ruff check` reports no errors on changed files.
- [ ] `GET .../clarifications` integration test returns items in correct order with null response for pending round.

### Manual Verify

- [ ] Complete a clarification round and inspect the builder prompt (via log or test fixture); confirm line-range sentence is present and line numbers are accurate.
- [ ] Force-skip a clarification round; inspect builder prompt for skip message with correct reason text.
- [ ] Call `GET .../clarifications` after one completed round and one pending round; confirm both appear with correct response status.

## Context & References

- `src/orchestrator/workflow/service.py` – `respond_to_clarification` to update
- `src/orchestrator/workflow/prompts.py` – `generate_builder_prompt` and `BuilderPrompt` dataclass
- `src/orchestrator/api/routers/clarifications.py` – new history route
- `src/orchestrator/api/schemas/clarifications.py` – `ClarificationHistoryItem`, `ClarificationHistoryResponse`
- `docs/enhanced-clarifications/architecture.md` – prompt text templates and history endpoint spec
- `docs/enhanced-clarifications/design-questions.md` – Q3 (history scope: all rounds including pending)
- Step 1 plan – prerequisite; `format_clarification_artifact` return type change
