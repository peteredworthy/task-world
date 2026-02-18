# Step 01: Data Model & MCP Tool (10a backend)

Extend the core clarification data model to support richer question types (multi-select, free text, number) and user-skippable responses. Update the MCP tool's inputSchema so LLMs can emit these new question types. Update API schemas and router to pass new fields through. This step establishes the foundational contracts that all subsequent steps depend on.

## Intent Verification
**Original Intent**: `docs/enhanced-clarifications/intent.md` – "Richer question types – `single_select`, `multi_select`, `free_text`, `number` with per-question `required` flag" and "User force-skip – users can skip optional questions or force-skip an entire clarification request with a reason"

**Functionality to Produce**:
- `ClarificationQuestion` model carries `question_type`, `allow_other`, `required`, `min`, `max`, `placeholder` with correct defaults and validation
- `ClarificationAnswer` carries `selected_options`, `skipped`, `skip_reason`
- `format_clarification_artifact` returns `tuple[str, int, int]` (text, start_line, end_line)
- `CLARIFICATION_TOOL` inputSchema exposes all new fields to the LLM
- API schemas mirror the domain model
- Router handles `skipped=True` by bypassing the "all required answered" guard

**Final Verification Criteria**:
- All existing `single_select` integration tests still pass (no regression)
- `pytest tests/integration/ -k clarification` green with new field tests
- `pytest tests/unit/ -k clarifications` green including validator tests
- `mypy` reports no errors on changed files
- `ruff check` reports no errors on changed files

---

## Task 1: Extend ClarificationQuestion and ClarificationAnswer domain models

**Description**: Add the new fields to the domain dataclasses and update `format_clarification_artifact` to return line-range metadata.

**Implementation Plan (Do These Steps)**

The domain models live in `src/orchestrator/workflow/clarifications.py`. The changes are purely additive—new fields with defaults—plus a validator and a return-type change.

- [ ] Open `src/orchestrator/workflow/clarifications.py` and read the file fully before editing.
- [ ] Add the following fields to `ClarificationQuestion` (after the existing `options` field):
```python
question_type: Literal['single_select', 'multi_select', 'free_text', 'number'] = 'single_select'
allow_other: bool = True
required: bool = True
min: float | None = None
max: float | None = None
placeholder: str | None = None
```
- [ ] Add a Pydantic `@model_validator(mode='after')` to `ClarificationQuestion` that enforces:
  - If `question_type` in `{'single_select', 'multi_select'}` → `options` must be non-empty
  - If `question_type` in `{'free_text', 'number'}` → `options` must be empty or absent
  - If both `min` and `max` are provided → `min <= max`

Example validator:
```python
from pydantic import model_validator

@model_validator(mode='after')
def validate_options_for_type(self) -> 'ClarificationQuestion':
    if self.question_type in ('single_select', 'multi_select'):
        if not self.options:
            raise ValueError(
                f"'options' must be non-empty for question_type={self.question_type!r}"
            )
    else:  # free_text, number
        if self.options:
            raise ValueError(
                f"'options' must be empty for question_type={self.question_type!r}"
            )
    if self.min is not None and self.max is not None and self.min > self.max:
        raise ValueError("'min' must be <= 'max'")
    return self
```
- [ ] Add the following fields to `ClarificationAnswer`:
```python
selected_options: list[str] | None = None
skipped: bool = False
skip_reason: str | None = None
```
- [ ] Update `format_clarification_artifact` signature to return `tuple[str, int, int]`. The caller is responsible for counting lines in the artifact file before appending (see Task 2). The function itself computes start and end line numbers based on the text it is producing:
```python
def format_clarification_artifact(
    request: ClarificationRequest,
    response: ClarificationResponse,
) -> tuple[str, int, int]:
    # Build text as before
    text = ...  # existing construction logic
    line_count = text.count('\n') + (0 if text.endswith('\n') else 1)
    # start_line is computed by the caller; return 0 as a sentinel placeholder
    # that the caller replaces after reading the current file length.
    return text, 0, line_count
```
  **Note**: The actual `start_line` is determined by the caller in `workflow/service.py` (Step 2, Task 1). The function returns `(text, 0, line_count_of_appended_section)` so the caller can compute absolute line numbers.

**Dependencies**
- [ ] `pydantic` is already installed (used by existing models)
- [ ] `typing.Literal` is available in Python 3.8+ (project uses 3.12+)

**References**
- `docs/enhanced-clarifications/architecture.md` – full field list and validator rules
- `docs/enhanced-clarifications/design-questions.md` – Q1 (multi-select encoding), Q5 (validation scope)
- `docs/enhanced-clarifications/step-01-plan.md` – task breakdown and functional contract

**Constraints**
- [ ] Only `ClarificationQuestion`, `ClarificationAnswer`, and `format_clarification_artifact` in `clarifications.py` may be changed.
- [ ] All existing fields must retain their current defaults (backward-compatible).
- [ ] Do not change `ClarificationRequest`, `ClarificationResponse`, or `build_artifact_header`.

**Functionality (Expected Outcomes)**
- [ ] `ClarificationQuestion(question_type='free_text', options=['a'])` raises `ValidationError`
- [ ] `ClarificationQuestion(question_type='single_select', options=[])` raises `ValidationError`
- [ ] `ClarificationQuestion(question_type='single_select', options=['a'])` succeeds
- [ ] `ClarificationAnswer(skipped=True, skip_reason='N/A')` succeeds
- [ ] `format_clarification_artifact(req, resp)` returns a 3-tuple `(str, int, int)`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `pytest tests/unit/ -k clarifications -v` passes with no failures
- [ ] `mypy src/orchestrator/workflow/clarifications.py` reports no errors
- [ ] `ruff check src/orchestrator/workflow/clarifications.py` reports no errors

---

## Task 2: Update CLARIFICATION_TOOL inputSchema

**Description**: Expose all new question-type fields to the LLM by extending the JSON Schema in `mcp/clarification_tools.py`.

**Implementation Plan (Do These Steps)**

The MCP tool schema is a plain Python dict. We need to add new property definitions and make `options` optional at the schema level.

- [ ] Open `src/orchestrator/mcp/clarification_tools.py` and read the full file.
- [ ] Locate `CLARIFICATION_TOOL['inputSchema']['items']['properties']` (or equivalent path for the question properties dict).
- [ ] Add the following new properties inside each question item's properties:
```python
"question_type": {
    "type": "string",
    "enum": ["single_select", "multi_select", "free_text", "number"],
    "default": "single_select",
    "description": "The type of input the user should provide.",
},
"allow_other": {
    "type": "boolean",
    "default": True,
    "description": "Whether to show a free-text 'Other' option for select types.",
},
"required": {
    "type": "boolean",
    "default": True,
    "description": "Whether an answer is required. If False, the user may skip.",
},
"min": {
    "type": ["number", "null"],
    "default": None,
    "description": "Minimum value for number question type.",
},
"max": {
    "type": ["number", "null"],
    "default": None,
    "description": "Maximum value for number question type.",
},
"placeholder": {
    "type": ["string", "null"],
    "default": None,
    "description": "Placeholder text for free_text or number inputs.",
},
```
- [ ] Remove `"options"` from the `"required"` list at the item level (make it optional in the schema; semantic validation happens in the router).

**Constraints**
- [ ] Only `CLARIFICATION_TOOL` dict in `clarification_tools.py` may change.
- [ ] Do not add Python logic to this file—only the JSON schema dict.

**References**
- `docs/enhanced-clarifications/architecture.md` – "Modified Components: mcp/clarification_tools.py"
- `docs/enhanced-clarifications/step-01-plan.md` – Task 4

**Functionality (Expected Outcomes)**
- [ ] `CLARIFICATION_TOOL['inputSchema']` is valid JSON Schema (no missing required fields for the new properties)
- [ ] `options` is no longer in the `required` array of the question item schema

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `python -c "from src.orchestrator.mcp.clarification_tools import CLARIFICATION_TOOL; import json; print(json.dumps(CLARIFICATION_TOOL, indent=2))"` runs without error and shows `question_type`, `allow_other`, `required`, `min`, `max`, `placeholder` in the schema
- [ ] `ruff check src/orchestrator/mcp/clarification_tools.py` reports no errors

---

## Task 3: Mirror new fields in API schemas and update the router

**Description**: Extend `api/schemas/clarifications.py` to reflect all new model fields, then update the router to pass them through and handle `skipped=True`.

**Implementation Plan (Do These Steps)**

- [ ] Open `src/orchestrator/api/schemas/clarifications.py` and read it fully.
- [ ] Update `ClarificationQuestionSchema` to add:
```python
question_type: Literal['single_select', 'multi_select', 'free_text', 'number'] = 'single_select'
allow_other: bool = True
required: bool = True
min: float | None = None
max: float | None = None
placeholder: str | None = None
```
- [ ] Update `ClarificationAnswerSchema` to add:
```python
selected_options: list[str] | None = None
skipped: bool = False
skip_reason: str | None = None
```
- [ ] Update `RespondToClarificationRequest` to add:
```python
skipped: bool = False
skip_reason: str | None = None
```
- [ ] Open `src/orchestrator/api/routers/clarifications.py` and read it fully.
- [ ] In `respond_to_clarification`, locate the guard that checks "all required questions answered." Wrap it in a condition:
```python
if not request.skipped:
    # existing required-questions guard
    ...
```
- [ ] Pass `skipped` and `skip_reason` from the request through to the service/domain layer when creating `ClarificationAnswer` objects.

**References**
- `docs/enhanced-clarifications/architecture.md` – "Modified Components: api/schemas/clarifications.py" and "api/routers/clarifications.py"
- `docs/enhanced-clarifications/step-01-plan.md` – Tasks 5 and 6

**Constraints**
- [ ] Only `ClarificationQuestionSchema`, `ClarificationAnswerSchema`, and `RespondToClarificationRequest` in schemas file may change.
- [ ] Only the `respond_to_clarification` function in the router may change.
- [ ] Do not add new routes in this task (history route is Step 2, Task 5).

**Functionality (Expected Outcomes)**
- [ ] `RespondToClarificationRequest(answers=[...], skipped=True, skip_reason='N/A')` deserializes correctly
- [ ] Router accepts a respond request with `skipped=True` without requiring all answers

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `mypy src/orchestrator/api/schemas/clarifications.py src/orchestrator/api/routers/clarifications.py` reports no errors
- [ ] `ruff check src/orchestrator/api/schemas/clarifications.py src/orchestrator/api/routers/clarifications.py` reports no errors

---

## Task 4: Write integration and unit tests

**Description**: Cover all new fields, validation paths, the multi-select response path, and the skip path with tests.

**Implementation Plan (Do These Steps)**

Follow patterns from `tests/integration/test_api_runs.py`.

- [ ] Add unit tests in `tests/unit/` for `ClarificationQuestion` validator:
  - Test `question_type='free_text'` with non-empty `options` raises `ValidationError`
  - Test `question_type='single_select'` with empty `options` raises `ValidationError`
  - Test `question_type='number'` with `min=5, max=2` raises `ValidationError`
  - Test each valid `question_type` with appropriate `options` succeeds
- [ ] Add integration tests:
  - Create a clarification with `question_type='free_text'`; assert stored question has correct type and no options
  - Create a clarification with `question_type='multi_select'` and empty `options`; assert 422 response
  - Respond to a clarification with `selected_options=['A', 'B']`; assert artifact contains both selections
  - Respond with `skipped=True` and `skip_reason='Not needed'`; assert task transitions back to `BUILDING` and no 422 error

**References**
- `tests/integration/test_api_runs.py` – integration test patterns
- `docs/enhanced-clarifications/step-01-plan.md` – Task 7 (verification list)

**Functionality (Expected Outcomes)**
- [ ] All new tests pass
- [ ] No existing tests regress

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `pytest tests/integration/ -k clarification -v` passes with all new tests green
- [ ] `pytest tests/unit/ -k clarifications -v` passes including validator tests
- [ ] Existing `single_select` integration tests still pass
