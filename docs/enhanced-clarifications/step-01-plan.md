# Step 01 Plan: Data Model & MCP Tool (10a backend)

## Purpose

Extend the core clarification data model to support richer question types (multi-select, free text, number) and user-skippable responses. Update the MCP tool's inputSchema so LLMs can emit these new question types. Update API schemas and router to pass new fields through. This step establishes the foundational contracts that all subsequent steps depend on.

## Prerequisites

- None. This is the first step and has no upstream dependencies within this feature.

## Functional Contract

### Inputs

- `ClarificationQuestion` creation payload (from MCP tool call or direct API call):
  - `question_type: Literal['single_select', 'multi_select', 'free_text', 'number']` (default: `'single_select'`)
  - `allow_other: bool` (default: `True`)
  - `required: bool` (default: `True`)
  - `min: float | None` (default: `None`; used only when `question_type='number'`)
  - `max: float | None` (default: `None`; used only when `question_type='number'`)
  - `placeholder: str | None` (default: `None`)
  - `options: list[str]` – still required for `single_select` / `multi_select`; must be empty / absent for `free_text` / `number`
- `RespondToClarificationRequest` payload (from user submission):
  - Existing fields plus `selected_options: list[str] | None` (for `multi_select` answers)
  - `skipped: bool` (default: `False`)
  - `skip_reason: str | None` (default: `None`)

### Outputs

- Stored `ClarificationQuestion` row includes all new fields with correct defaults.
- Stored `ClarificationAnswer` row includes `selected_options`, `skipped`, `skip_reason`.
- `format_clarification_artifact(request, response)` returns `tuple[str, int, int]`: (formatted text, start_line, end_line) indicating where in the artifact file the new section begins and ends.
- All existing `single_select` flows remain unchanged (backward-compatible defaults).

### Errors

- `422 Unprocessable Entity` if `question_type` is `single_select` or `multi_select` and `options` is empty or absent.
- `422 Unprocessable Entity` if `question_type` is `free_text` or `number` and `options` is non-empty.
- `422 Unprocessable Entity` if `min` > `max` when both are provided.
- `422 Unprocessable Entity` if `required` questions are unanswered and `skipped` is `False`.

## Tasks

1. Extend `ClarificationQuestion` in `src/orchestrator/workflow/clarifications.py`: add `question_type`, `allow_other`, `required`, `min`, `max`, `placeholder` fields with defaults; add Pydantic validator enforcing the options/question_type semantic constraint.
2. Extend `ClarificationAnswer` in `src/orchestrator/workflow/clarifications.py`: add `selected_options: list[str] | None`, `skipped: bool`, `skip_reason: str | None`.
3. Update `format_clarification_artifact` in `src/orchestrator/workflow/clarifications.py` to return `tuple[str, int, int]` (text, start_line, end_line); caller counts lines in artifact file before appending.
4. Update `CLARIFICATION_TOOL.inputSchema` in `src/orchestrator/mcp/clarification_tools.py`: add `question_type` enum, `allow_other`, `required`, `min`, `max`, `placeholder`; make `options` optional at schema level.
5. Mirror new fields in `src/orchestrator/api/schemas/clarifications.py`: update `ClarificationQuestionSchema`, `ClarificationAnswerSchema`, `RespondToClarificationRequest`.
6. Update `src/orchestrator/api/routers/clarifications.py`: pass new fields through; when `request.skipped` is True, bypass the "all required answered" guard.
7. Write integration tests: test creation with each `question_type`; test `multi_select` response with `selected_options`; test skip path (partial answers + `skipped=True`); test validation rejections.

## Verification

### Auto-Verify

- [ ] `pytest tests/integration/ -k clarification` passes with all new field tests green.
- [ ] `pytest tests/unit/ -k clarifications` passes including validator tests for options constraint.
- [ ] `mypy src/orchestrator/workflow/clarifications.py src/orchestrator/api/schemas/clarifications.py` reports no errors.
- [ ] `ruff check src/orchestrator/workflow/clarifications.py src/orchestrator/mcp/clarification_tools.py src/orchestrator/api/` reports no errors.
- [ ] Existing `single_select` integration tests continue to pass (no regression).

### Manual Verify

- [ ] Send a `POST .../clarifications` request with `question_type='free_text'` and confirm the stored question has correct type and no options.
- [ ] Send a `POST .../clarifications` request with `question_type='multi_select'` and empty `options`; confirm 422 response.
- [ ] Respond to a clarification with `skipped=True` and `skip_reason='Not needed'`; confirm task transitions back to BUILDING.
- [ ] Verify the artifact file has a new section appended and the `format_clarification_artifact` return value line numbers match.

## Context & References

- `src/orchestrator/workflow/clarifications.py` – domain models to extend
- `src/orchestrator/mcp/clarification_tools.py` – MCP inputSchema to extend
- `src/orchestrator/api/routers/clarifications.py` – router to update (skip guard)
- `src/orchestrator/api/schemas/clarifications.py` – Pydantic API schemas to mirror
- `docs/enhanced-clarifications/architecture.md` – full field list and validator rules
- `docs/enhanced-clarifications/design-questions.md` – Q1 (multi-select encoding), Q2 (skip signal), Q5 (validation scope)
- `tests/integration/test_api_runs.py` – integration test patterns to follow
