# Step 02: Prompt Changes & History Endpoint (10d + history backend)

Wire the line-range data introduced in Step 1 into the builder resume prompt so the LLM knows exactly where in the artifact file to look for answers. Add the clarification history API endpoint so the frontend can display past Q&A rounds. Also surface the skip signal in the prompt so the builder can proceed with partial information.

## Intent Verification
**Original Intent**: `docs/enhanced-clarifications/intent.md` – "Line-number-aware builder prompts – after answers are written to the artifact file, the builder's resume prompt includes the file path and exact line range" and "Answer history in the activity timeline – completed clarification rounds shown as expandable cards"

**Functionality to Produce**:
- `generate_builder_prompt` includes file path and line range reference when `clarification_line_range` is provided
- `generate_builder_prompt` includes skip signal text when `skipped_questions` is provided
- `BuilderPrompt` dataclass has `clarification_line_range` and `skipped_questions` fields
- `GET /api/runs/{run_id}/tasks/{task_id}/clarifications` returns all historical rounds (including pending) ordered by creation time

**Final Verification Criteria**:
- `pytest tests/integration/ -k clarification` passes including new prompt and history tests
- `pytest tests/unit/ -k prompts` passes; builder prompt includes line-range sentence when `clarification_line_range` provided
- `mypy` reports no errors on `service.py`, `prompts.py`, `routers/clarifications.py`
- History endpoint returns 200 with empty list when no rounds exist; 404 when task not found

---

## Task 1: Update respond_to_clarification in workflow/service.py

**Description**: Capture the line range returned by `format_clarification_artifact` and pass it (along with skip data) to `generate_builder_prompt`.

**Implementation Plan (Do These Steps)**

`format_clarification_artifact` now returns `(text, _, section_line_count)` (the second value is a placeholder 0). The service must read the current artifact file line count before appending to compute the absolute `start_line`.

- [ ] Open `src/orchestrator/workflow/service.py` and read it fully.
- [ ] In `respond_to_clarification`, locate the call to `format_clarification_artifact`. Replace it with:
```python
# Count current lines in the artifact file before appending
artifact_path = ...  # existing path variable
try:
    with open(artifact_path, 'r') as f:
        current_line_count = sum(1 for _ in f)
except FileNotFoundError:
    current_line_count = 0

text, _, section_line_count = format_clarification_artifact(request_obj, response_obj)
# Append text to artifact file (existing logic)
# ...
start_line = current_line_count + 1
end_line = current_line_count + section_line_count
clarification_line_range = (str(artifact_path), start_line, end_line)
```
- [ ] Pass `clarification_line_range` and skip data to `generate_builder_prompt`:
```python
prompt = generate_builder_prompt(
    ...,  # existing args
    clarification_line_range=clarification_line_range,
    skipped_questions=[q.text for q in skipped_questions] if request.skipped else None,
    skip_reason=request.skip_reason if request.skipped else None,
)
```

**Dependencies**
- [ ] Step 1 complete: `format_clarification_artifact` returns `tuple[str, int, int]`
- [ ] Step 1 complete: `ClarificationAnswer` has `skipped` and `skip_reason` fields

**References**
- `docs/enhanced-clarifications/architecture.md` – "Modified Components: workflow/service.py"
- `docs/enhanced-clarifications/step-02-plan.md` – Task 1, Functional Contract (Inputs)

**Constraints**
- [ ] Only `respond_to_clarification` in `service.py` may change in this task.
- [ ] Do not change `request_clarification` or `get_pending_clarification`.

**Side Effects**
- [ ] The artifact file read-before-write adds a small I/O cost (negligible for typical file sizes).

**Functionality (Expected Outcomes)**
- [ ] `respond_to_clarification` passes a non-None `clarification_line_range` to `generate_builder_prompt` after a normal (non-skipped) response
- [ ] When `request.skipped=True`, `skipped_questions` list is passed to `generate_builder_prompt`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `mypy src/orchestrator/workflow/service.py` reports no errors
- [ ] `ruff check src/orchestrator/workflow/service.py` reports no errors

---

## Task 2: Update generate_builder_prompt in workflow/prompts.py

**Description**: Accept new optional parameters and append the appropriate clarification context sentences to the prompt.

**Implementation Plan (Do These Steps)**

- [ ] Open `src/orchestrator/workflow/prompts.py` and read it fully.
- [ ] Add the following fields to the `BuilderPrompt` dataclass:
```python
clarification_line_range: tuple[str, int, int] | None = None
skipped_questions: list[str] | None = None
```
- [ ] Update `generate_builder_prompt` signature to accept:
```python
clarification_line_range: tuple[str, int, int] | None = None,
skipped_questions: list[str] | None = None,
skip_reason: str | None = None,
```
- [ ] In the function body, after the existing clarifications section, append:
```python
if clarification_line_range:
    path, start, end = clarification_line_range
    clarification_text += (
        f"\n\nUser answers have been written to {path} (lines {start}–{end}). "
        "Read that section for the answers."
    )
if skipped_questions:
    reason = skip_reason or 'none given'
    q_list = ', '.join(f'"{q}"' for q in skipped_questions)
    clarification_text += (
        f"\n\nThe user declined to answer: {q_list}. "
        f"Reason: {reason}. Proceed with your best judgment."
    )
```
- [ ] Populate the new `BuilderPrompt` fields when constructing the return value.

**Constraints**
- [ ] Only `generate_builder_prompt` and `BuilderPrompt` in `prompts.py` may change.
- [ ] All existing parameters remain with their current defaults (backward-compatible).

**References**
- `docs/enhanced-clarifications/architecture.md` – "Modified Components: workflow/prompts.py" with exact template strings
- `docs/enhanced-clarifications/step-02-plan.md` – Task 2, Functional Contract (Outputs)

**Functionality (Expected Outcomes)**
- [ ] `generate_builder_prompt(..., clarification_line_range=('/path/artifact.md', 10, 15))` returns a prompt containing `"lines 10–15"`
- [ ] `generate_builder_prompt(..., skipped_questions=['Q1'], skip_reason='Not needed')` returns a prompt containing `"The user declined to answer"` and `"Not needed"`
- [ ] Calling without new params produces identical output to the previous version

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `pytest tests/unit/ -k prompts -v` passes; line-range and skip sentences present in output
- [ ] `mypy src/orchestrator/workflow/prompts.py` reports no errors
- [ ] `ruff check src/orchestrator/workflow/prompts.py` reports no errors

---

## Task 3: Add repository method for clarification history

**Description**: Add `get_clarification_history(run_id, task_id)` to the repository layer so the router can fetch all rounds.

**Implementation Plan (Do These Steps)**

- [ ] Identify the repository file that contains clarification DB queries (likely `src/orchestrator/db/repositories/clarifications.py` or equivalent). Read it fully.
- [ ] Add the method:
```python
def get_clarification_history(
    self,
    run_id: str,
    task_id: str,
) -> list[tuple[ClarificationRequest, ClarificationResponse | None]]:
    """Return all clarification rounds for a task, ordered by creation time ascending.
    Pending rounds have response=None.
    """
    requests = (
        self.session.query(ClarificationRequestModel)
        .filter_by(run_id=run_id, task_id=task_id)
        .order_by(ClarificationRequestModel.created_at.asc())
        .all()
    )
    result = []
    for req in requests:
        resp = (
            self.session.query(ClarificationResponseModel)
            .filter_by(clarification_request_id=req.id)
            .first()
        )
        result.append((req.to_domain(), resp.to_domain() if resp else None))
    return result
```
  Adapt class/method names to match the existing repository pattern in the codebase.

**References**
- `docs/enhanced-clarifications/architecture.md` – "New Components: GET /api/runs/{id}/tasks/{task_id}/clarifications"
- `docs/enhanced-clarifications/design-questions.md` – Q3 (history scope: all rounds including pending)
- `docs/enhanced-clarifications/step-02-plan.md` – Task 3

**Functionality (Expected Outcomes)**
- [ ] Returns an empty list when no clarifications exist for the task
- [ ] Returns pending rounds with `response=None`
- [ ] Returns completed rounds with the matching `ClarificationResponse`
- [ ] Items are ordered by creation time ascending

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Unit test calling `get_clarification_history` with no data returns `[]`
- [ ] `mypy` on the repository file reports no errors

---

## Task 4: Add ClarificationHistoryItem/Response schemas and the history route

**Description**: Add the new Pydantic schemas and wire up the `GET .../clarifications` endpoint.

**Implementation Plan (Do These Steps)**

- [ ] Open `src/orchestrator/api/schemas/clarifications.py` and add:
```python
class ClarificationHistoryItem(BaseModel):
    request: ClarificationQuestionSchema  # or existing request schema
    response: ClarificationAnswerSchema | None

class ClarificationHistoryResponse(BaseModel):
    items: list[ClarificationHistoryItem]
```
  Use the exact existing schema class names for request/response (check the file first).
- [ ] Open `src/orchestrator/api/routers/clarifications.py` and add:
```python
@router.get("/{run_id}/tasks/{task_id}/clarifications", response_model=ClarificationHistoryResponse)
async def get_clarification_history(
    run_id: str,
    task_id: str,
    db: Session = Depends(get_db),
) -> ClarificationHistoryResponse:
    # Verify run and task exist (404 if not)
    run = get_run_or_404(run_id, db)
    task = get_task_or_404(run_id, task_id, db)

    repo = ClarificationRepository(db)
    pairs = repo.get_clarification_history(run_id, task_id)
    items = [
        ClarificationHistoryItem(
            request=ClarificationQuestionSchema.from_orm(req),
            response=ClarificationAnswerSchema.from_orm(resp) if resp else None,
        )
        for req, resp in pairs
    ]
    return ClarificationHistoryResponse(items=items)
```
  Adapt helper function names to match existing router patterns (check the existing routes for `get_run_or_404` equivalents).

**References**
- `docs/enhanced-clarifications/step-02-plan.md` – Tasks 4 and 5, Functional Contract (Outputs)
- `docs/enhanced-clarifications/architecture.md` – "New Components: GET /api/runs/{id}/tasks/{task_id}/clarifications"

**Constraints**
- [ ] Only add the two new schema classes; do not modify existing schemas in this task.
- [ ] Add only the new `GET` route; do not modify existing routes.

**Functionality (Expected Outcomes)**
- [ ] `GET .../clarifications` returns `{"items": []}` when no rounds exist
- [ ] `GET .../clarifications` returns 404 when run_id or task_id not found
- [ ] Pending rounds appear with `"response": null`
- [ ] Items are in ascending creation order

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `pytest tests/integration/ -k clarification_history` passes
- [ ] `mypy src/orchestrator/api/schemas/clarifications.py src/orchestrator/api/routers/clarifications.py` reports no errors
- [ ] `ruff check` on both files reports no errors

---

## Task 5: Write integration and unit tests for prompt and history

**Description**: Verify the prompt changes and history endpoint with automated tests.

**Implementation Plan (Do These Steps)**

- [ ] Add unit tests for `generate_builder_prompt` in `tests/unit/`:
  - With `clarification_line_range=('/artifact.md', 5, 12)`: assert output contains `"lines 5–12"` and `/artifact.md`
  - With `skipped_questions=['Question 1'], skip_reason='Too vague'`: assert output contains `"declined to answer"` and `"Too vague"`
  - Without new params: assert output matches existing baseline (no regression)
- [ ] Add integration tests:
  - Complete a clarification round; then `GET .../clarifications`; assert 1 item with non-null response
  - Submit a pending clarification; `GET .../clarifications`; assert the pending item has `"response": null`
  - `GET .../clarifications` with nonexistent `run_id`; assert 404
  - Respond to clarification with `skipped=True`; read builder prompt from test fixture; assert skip message present

**References**
- `docs/enhanced-clarifications/step-02-plan.md` – Task 6 and Verification sections
- `tests/integration/test_api_runs.py` – integration test patterns

**Functionality (Expected Outcomes)**
- [ ] All new tests pass
- [ ] No existing tests regress

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `pytest tests/integration/ -k clarification -v` all green
- [ ] `pytest tests/unit/ -k prompts -v` all green
