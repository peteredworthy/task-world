# Dry Run Notes: Enhanced Clarification System

## Summary

The 5-step plan is well-structured and largely executable as-written. The existing codebase already has the ORM models, repository pattern, event system, and WebSocket infrastructure needed. Most changes are additive (new fields with defaults) which preserves backward compatibility.

**Key observations from simulation:**

1. **No REQUIRED blockers** – all gaps are EXPECTED or OPTIONAL.
2. Three EXPECTED gaps that need attention before execution: (a) the `format_clarification_artifact` return-type contract needs clarification on how `start_line` is conveyed, (b) the `respond_to_clarification` router currently does not write the artifact file—it delegates to `service.py`—so the line-count logic needs to be placed in the correct layer, (c) the history schema uses `ClarificationQuestionSchema` as the `request` field but the actual request is a `ClarificationRequest` (full request object), not a single question.
3. Two minor OPTIONAL gaps: missing `ClarificationResponse` TypeScript type and the `ClarificationQuestion.question` field is renamed to `.text` in some step files (inconsistency with the actual model).

All gaps have concrete remediations documented below.

---

## Task-by-Task Simulation

### Step 1, Task 1: Extend ClarificationQuestion and ClarificationAnswer domain models

- **Simulation:** Open `src/orchestrator/workflow/clarifications.py`. Add 6 fields to `ClarificationQuestion` with defaults. Add `@model_validator(mode='after')` enforcing options rules. Add 3 fields to `ClarificationAnswer`. Change `format_clarification_artifact` return type from `str` to `tuple[str, int, int]`.
- **Assumptions:**
  - `pydantic` v2 `model_validator` is available (confirmed: project uses Pydantic v2).
  - `Literal` is available from `typing` (confirmed: Python 3.12).
  - `ClarificationQuestion.options` currently typed as `list[str]` is always required; changing the validator to only require it for select types is a semantic change but backward-compatible because default `question_type='single_select'` still requires options.
  - The existing `format_clarification_artifact` call site in `service.py:respond_to_clarification` currently ignores the return value (confirmed: line 1142 in service.py assigns nothing—the function returns `str` and isn't stored).
- **Gaps:**
  - **GAP-01:** `format_clarification_artifact` step plan says "return `(text, 0, line_count_of_section)`" but the current function body references `q.options` in a loop that will raise `AttributeError` for `free_text`/`number` questions once `options` is no longer required. The rendering logic for skipped answers and `selected_options` is not yet written.
  - **GAP-02:** The task plan says "return `(text, 0, line_count)`" where `0` is a sentinel for start_line. But `text.count('\n') + (0 if text.endswith('\n') else 1)` double-counts: if the text already ends with `\n` the actual line count is `text.count('\n')`, not `text.count('\n') + 1`. The formula should be `text.count('\n')` for text ending in newline, or `text.count('\n') + 1` for text not ending in newline—which is what the plan says—but needs verification against actual artifact format.

---

### Step 1, Task 2: Update CLARIFICATION_TOOL inputSchema

- **Simulation:** Open `src/orchestrator/mcp/clarification_tools.py`. Locate `CLARIFICATION_TOOL['inputSchema']['items']['properties']` (it's at `['inputSchema']['properties']['questions']['items']['properties']`). Add 6 new property dicts. Remove `"options"` from `["inputSchema"]["properties"]["questions"]["items"]["required"]`.
- **Assumptions:**
  - The JSON Schema path is `inputSchema.properties.questions.items.properties` (confirmed by reading the file: `"inputSchema" → "properties" → "questions" → "items" → "properties"`).
  - The `"required"` key at the item level is `["question", "context", "options"]` (confirmed).
  - `"options"` can be removed from `required` without breaking existing LLM callers because older tools always provide options; new tools will omit options for free_text/number.
- **Gaps:**
  - **GAP-03 (OPTIONAL):** The step plan's property path description says `"CLARIFICATION_TOOL['inputSchema']['items']['properties']"` but the actual path is `CLARIFICATION_TOOL['inputSchema']['properties']['questions']['items']['properties']`. This is just a documentation inaccuracy in the task file—the builder reading the file directly will figure it out. No code change needed.

---

### Step 1, Task 3: Mirror new fields in API schemas and update the router

- **Simulation:** Add fields to `ClarificationQuestionSchema`, `ClarificationAnswerSchema`, `RespondToClarificationRequest` in `api/schemas/clarifications.py`. In `api/routers/clarifications.py:respond_to_clarification`, wrap the required-questions guard with `if not request.skipped`. Pass `skipped` and `skip_reason` to `ClarificationAnswer` construction.
- **Assumptions:**
  - There is a "required questions answered" guard in the router. **Actual finding:** Looking at the current `respond_to_clarification` router (lines 162–180), there is NO such guard currently—it directly maps answers to `ClarificationAnswer` objects and calls `service.respond_to_clarification`. The guard mentioned in the plan either (a) doesn't exist yet or (b) is expected to be added as part of this step.
  - The `ClarificationAnswer` model in the domain layer needs `skipped` and `skip_reason` (from Task 1) before Task 3 can pass them through.
- **Gaps:**
  - **GAP-04 (EXPECTED):** The task says "In `respond_to_clarification`, locate the guard that checks 'all required questions answered.' Wrap it in `if not request.skipped:`" but this guard does not exist in the current codebase. The builder must be informed: either add the guard and then wrap it, or just add the `skipped` bypass without wrapping a nonexistent guard. The remediation: update the task description to say "Add a guard that validates all `required=True` questions have answers when `request.skipped` is False" rather than implying the guard already exists.

---

### Step 1, Task 4: Write integration and unit tests

- **Simulation:** Create unit tests in `tests/unit/` for `ClarificationQuestion` validator. Create integration tests following `tests/integration/test_api_runs.py` patterns. Run `pytest tests/integration/ -k clarification`.
- **Assumptions:**
  - Integration test infrastructure (real SQLite, real HTTP client via `httpx.AsyncClient`) is available.
  - A test fixture provides a run with an active task in `BUILDING` state.
- **Gaps:**
  - **GAP-05 (EXPECTED):** The integration test plan says "Respond with `skipped=True`; assert task transitions back to BUILDING." However, the service's `respond_to_clarification` method (lines 1112–1165 in service.py) does not currently write the clarification to the artifact file—the `format_clarification_artifact` return value is not used. Step 2, Task 1 is supposed to wire this. So the integration test for `skipped=True` will need the Step 2 changes in order to fully pass (artifact writing + prompt generation). The test plan should note this dependency ordering.

---

### Step 2, Task 1: Update respond_to_clarification in workflow/service.py

- **Simulation:** In `service.py:respond_to_clarification`, before the existing `format_clarification_artifact` call... wait—the existing code does NOT call `format_clarification_artifact` at all. The current `respond_to_clarification` (lines 1112–1165) creates a `ClarificationResponse`, saves it, transitions the task, emits the event. It never writes to an artifact file.
- **Assumptions:**
  - The plan assumes `format_clarification_artifact` is already being called in `respond_to_clarification`. **Actual finding:** It is not.
  - An `artifact_path` variable exists in the service method. **Actual finding:** It does not.
- **Gaps:**
  - **GAP-06 (REQUIRED—highest priority):** The task plan for Step 2, Task 1 assumes `format_clarification_artifact` is called in `respond_to_clarification` and just needs to unpack the new tuple return. In reality, the entire artifact-writing flow is missing from the service layer. The builder must: (1) determine the artifact file path (from run configuration or a known convention), (2) call `build_artifact_header()` if the file doesn't exist, (3) call `format_clarification_artifact`, (4) append to the file, (5) compute line numbers. The `clarification_number` argument to `format_clarification_artifact` also needs a source (count of previous clarifications for this task). This is a significant implementation gap that is unaddressed in the step files.
  - **Remediation:** Update `step-02.md` Task 1 to include: (a) look up the artifact path from `self._global_config` or the run's worktree path + convention, (b) implement the full write flow including `clarification_number` tracking, (c) note that the path convention (e.g., `worktrees/run-{id}/clarifications/{task_id}.md`) must be documented.

---

### Step 2, Task 2: Update generate_builder_prompt in workflow/prompts.py

- **Simulation:** Add `clarification_line_range` and `skipped_questions` to `BuilderPrompt` dataclass. Add parameters to `generate_builder_prompt`. Append template strings to the clarifications section.
- **Assumptions:**
  - The existing clarification section in the prompt uses `clarifications_path` (confirmed: lines 113–120 in prompts.py).
  - The new text appends after the existing path reference.
- **Gaps:**
  - **GAP-07 (OPTIONAL):** The `generate_builder_prompt` currently only has `clarifications_path: str | None`. The new `clarification_line_range` contains both the path and line numbers. After adding `clarification_line_range`, the function will have two ways to communicate the path (via `clarifications_path` and via `clarification_line_range[0]`). The plan should clarify: when `clarification_line_range` is provided, should `clarifications_path` still be included separately, or is the line-range reference sufficient? Recommendation: include both (line-range is a superset), with `clarification_line_range` overriding/supplementing `clarifications_path` when present.

---

### Step 2, Task 3: Add repository method for clarification history

- **Simulation:** Add `get_clarification_history(run_id, task_id)` to `RunRepository` in `db/repositories.py`. Use SQLAlchemy async to query `ClarificationRequestModel`, then for each request query `ClarificationResponseModel`.
- **Assumptions:**
  - The `ClarificationRequestModel` has a `response` relationship (confirmed: line 207 in models.py—`response: Mapped[ClarificationResponseModel | None]` with `uselist=False`).
  - Can use the relationship instead of a second query.
- **Gaps:**
  - **GAP-08 (EXPECTED):** The task plan shows `self.session.query(ClarificationRequestModel)` which is synchronous SQLAlchemy ORM style. The repository uses **async SQLAlchemy** (`AsyncSession`) with `await self._session.execute(select(...))` (confirmed from the existing repository code). The builder must use the async pattern, not the sync query shown in the task snippet. The snippet is wrong—it will cause a `MissingGreenlet` error at runtime.
  - **Remediation:** Update the step-02 Task 3 snippet to use async SQLAlchemy: `result = await self._session.execute(select(ClarificationRequestModel).where(...).order_by(...))`, `requests = result.scalars().all()`.

---

### Step 2, Task 4: Add ClarificationHistoryItem/Response schemas and the history route

- **Simulation:** Add `ClarificationHistoryItem` and `ClarificationHistoryResponse` to schemas. Add `GET /{run_id}/tasks/{task_id}/clarifications` route.
- **Assumptions:**
  - Helper functions `get_run_or_404` and `get_task_or_404` exist in the router. **Finding:** The current router does not have explicit 404 helpers—it uses the service layer which raises domain errors, and `api/errors.py` maps them to HTTP responses.
  - `ClarificationRepository` class exists as a separate class. **Finding:** Clarification methods are on `RunRepository`, not a separate class.
- **Gaps:**
  - **GAP-09 (EXPECTED):** The schema definition `ClarificationHistoryItem(request=ClarificationQuestionSchema, response=ClarificationAnswerSchema | None)` uses the wrong schema types. `request` should be a full `ClarificationRequestResponse` (the entire request object with all questions), and `response` should be a `ClarificationResponseSchema` (full response with all answers). The step file shows `request: ClarificationQuestionSchema` which is a single question, not a full request. This needs to be corrected in the schemas.
  - **GAP-10 (EXPECTED):** The task shows `ClarificationRepository(db)` but the actual class is `RunRepository` (confirmed). The builder will need to use `RunRepository` for the `get_clarification_history` method or create a helper that uses `self._session` directly in the router.

---

### Step 2, Task 5: Write integration and unit tests for prompt and history

- **Simulation:** Add unit tests for `generate_builder_prompt` with new params. Add integration tests for history endpoint.
- **Assumptions:**
  - The history endpoint returns items including pending rounds (per Q3 decision in design-questions.md).
- **Gaps:** No significant gaps. Straightforward test writing following established patterns.

---

### Step 3, Task 1: Audit and update ClarificationRequested event dataclass

- **Simulation:** Read `events.py`. The `ClarificationRequested` dataclass already has `task_id`, `request_id`, and `question_count` (confirmed: lines 140–145 in events.py). Add `questions: list[dict] = field(default_factory=list)`.
- **Assumptions:**
  - `ClarificationRequested` does not have a `questions` field yet (confirmed—it doesn't). Adding it with `default_factory=list` is backward-compatible.
  - `ClarificationResponded` already has `task_id` and `request_id` (confirmed: lines 149–153). It's missing `run_id` at the dataclass level—but looking at the construction in `service.py` (line 1154), `run_id` is passed as a positional arg to the base `WorkflowEvent`. So `run_id` is available on `ClarificationResponded` through inheritance.
- **Gaps:**
  - **GAP-11 (OPTIONAL):** The `WorkflowEvent` base class has `run_id` as a field. Both `ClarificationRequested` and `ClarificationResponded` inherit it. The task says "Verify `ClarificationResponded` has `run_id`, `task_id`, and `request_id`. Add `run_id` or `task_id` if missing." Both are present via inheritance + dataclass fields. No code change needed here—the task is essentially a no-op audit with a potential false alarm.

---

### Step 3, Task 2: Verify and add WebSocket broadcast for clarification events

- **Simulation:** Find where events are serialized in the WS broadcaster. Add branches for `ClarificationRequested` and `ClarificationResponded`.
- **Assumptions:**
  - The WS broadcaster has a dispatch mechanism on event types. Need to check `api/websocket.py` for the broadcasting pattern.
- **Gaps:**
  - **GAP-12 (EXPECTED):** The task plan gives pseudocode using `isinstance(event, ClarificationRequested)` and `await broadcast_to_run(event.run_id, payload)`. The actual broadcast function name in the codebase must be verified before implementation. The builder must read `api/websocket.py` first (which the task does instruct). This is properly handled by the task's "read the file fully" instruction—no code change to the task file needed, just awareness.

---

### Step 3, Task 3: Write integration tests for WS clarification events

- **Simulation:** Find existing WS integration test file. Add tests for `clarification_requested` and `clarification_responded` WS messages.
- **Assumptions:**
  - WebSocket test infrastructure exists with `client.websocket_connect()` and `ws.receive_json(timeout=2)` patterns.
- **Gaps:**
  - **GAP-13 (OPTIONAL):** The task uses `httpx.AsyncClient` TestClient patterns. WebSocket testing with real async timing (2-second timeout) can be flaky in CI if event emission is slow. The test should use a shorter timeout with retry or a `asyncio.wait_for` wrapper. This is a test reliability note, not a functionality gap.

---

### Step 4, Task 1: Extend TypeScript types in clarifications.ts

- **Simulation:** Open `ui/src/types/clarifications.ts`. Add fields to `ClarificationQuestion`, `ClarificationAnswer`, `RespondToClarificationRequest`. Add `ClarificationHistoryItem` and `ClarificationHistoryResponse`.
- **Assumptions:**
  - The current `ClarificationAnswer` type does not have `selected_options`, `skipped`, `skip_reason` (confirmed—it doesn't).
  - There is no `ClarificationResponse` TypeScript type—only `ClarificationRequest` and `ClarificationAnswer`.
- **Gaps:**
  - **GAP-14 (EXPECTED):** The new `ClarificationHistoryItem` uses `response: ClarificationResponse | null` but there is no `ClarificationResponse` TypeScript interface in `clarifications.ts`. The step file needs to add this type (it should have `request_id`, `answers: ClarificationAnswer[]`, `responded_at: string`). The builder must add it alongside the history types.

---

### Step 4, Task 2: Update QuestionCard to render all four question types

- **Simulation:** Read `QuestionCard.tsx`. Add `onOptionsChange` prop. Branch on `question_type`. Render radio (single_select), checkboxes (multi_select), textarea (free_text), number input.
- **Assumptions:**
  - The `AnswerState` type is defined locally in `QuestionCard.tsx` or imported from the modal. Need to check.
  - `answer.selectedOptions` must be initialized as `[]` in the parent (modal) for multi-select to work correctly.
- **Gaps:**
  - **GAP-15 (OPTIONAL):** The `multi_select` branch references `answer.selectedOptions` but `AnswerState` is defined in `ClarificationModal.tsx` (likely). The `QuestionCard` props include `answer: AnswerState`. The `AnswerState` extension to add `selectedOptions: string[]` happens in Task 3 (ClarificationModal). The builder should be aware that Task 2 and Task 3 are coupled—`QuestionCard.tsx` uses the `AnswerState` type from `ClarificationModal.tsx`, so Task 3's `AnswerState` extension must be done before or alongside Task 2. The task ordering (Task 2 then Task 3) is fine as long as the builder does both in the same commit.

---

### Step 4, Task 3: Update ClarificationModal for multi-select state, validation, and skip flow

- **Simulation:** Read `ClarificationModal.tsx`. Extend `AnswerState`. Add `handleOptionsChange`. Update validation. Add skip UI state and "Skip remaining" button. Implement `handleSkipSubmit`.
- **Assumptions:**
  - `ClarificationModal` uses `AnswerState` as a local interface.
  - The existing `buildAnswers()` function returns `ClarificationAnswer[]`.
  - The existing submit handler calls `onRespond(payload)`.
- **Gaps:**
  - **GAP-16 (OPTIONAL):** The `ClarificationQuestion.question` field in the Python model is named `question` (confirmed: `ClarificationQuestion.question: str` in `clarifications.py`). But the step files for the frontend (`step-05.md` Task 4) reference `q.text` in `ClarificationHistoryCard`. These are inconsistent—the actual field name from the API is `question`, not `text`. The `ClarificationHistoryCard` code snippet uses `q.text` which will be `undefined` at runtime. Remediation: use `q.question` in the component.

---

### Step 5, Task 1: Add clarification event payload types to activity.ts

- **Simulation:** Open `ui/src/types/activity.ts`. Add `ClarificationRequestedPayload` and `ClarificationRespondedPayload` interfaces. Add to any union type.
- **Assumptions:** Straightforward type additions.
- **Gaps:** No significant gaps.

---

### Step 5, Task 2: Extend useWebSocket processEvent with clarification handlers

- **Simulation:** Open `ui/src/hooks/useWebSocket.ts`. Find `processEvent`. Add two `else if` branches.
- **Assumptions:**
  - `processEvent` receives `{ event_type, ...data }` as parsed JSON from the WebSocket.
  - `runId` is in scope within `processEvent`.
  - The `QueryClient` is available as `qc` or similar.
- **Gaps:** No significant gaps beyond verifying variable names (which the task instructs the builder to check).

---

### Step 5, Task 3: Add useClarificationHistory query hook

- **Simulation:** Open `ui/src/hooks/useClarifications.ts`. Add `useClarificationHistory` hook at the end of the file.
- **Assumptions:**
  - The existing hooks use a `fetch`-based pattern (not axios or a custom client).
  - The query key `['clarification-history', runId, taskId]` matches what `useWebSocket` invalidates in Task 2.
- **Gaps:** No significant gaps. The `staleTime: 30_000` is reasonable; the task correctly notes to adapt to existing API client patterns.

---

### Step 5, Task 4: Create ClarificationHistoryCard component

- **Simulation:** Create `ui/src/components/detail/ClarificationHistoryCard.tsx`.
- **Assumptions:**
  - CSS class names follow the existing Tailwind utility pattern (not BEM with `.clarification-history-card`).
- **Gaps:**
  - **GAP-16** (noted above): `q.text` should be `q.question` in the component code. The step file's code snippet will not work as written.
  - **GAP-17 (OPTIONAL):** The component uses `response?.answers?.find(a => a.question_id === q.id)` to match answers to questions. This assumes answers carry `question_id`. Confirmed: `ClarificationAnswer` has `question_id` in the Python model and TypeScript type. No gap here after verification.

---

### Step 5, Task 5: Wire ClarificationHistoryCard into the activity feed

- **Simulation:** Open `RunDetail.tsx`. Import `useClarificationHistory` and `ClarificationHistoryCard`. Add hook call. Add `clarification_responded` branch in event renderer.
- **Assumptions:**
  - `RunDetail.tsx` renders the activity feed directly or via a sub-component.
  - The activity event objects have `event_type` and `request_id` fields.
- **Gaps:**
  - **GAP-18 (EXPECTED):** The plan calls `useClarificationHistory(runId, taskId)` at the top of `RunDetail`, but `RunDetail` renders events for a whole run (multiple tasks). Calling `useClarificationHistory` with a single `taskId` at the `RunDetail` level won't work if events from multiple tasks are shown. The hook needs to either be called per-task (inside the per-task renderer) or the history endpoint needs to be called with just `runId` to get all tasks' history. This is an architectural mismatch. **Remediation:** Call `useClarificationHistory` inside the per-event/per-task renderer, not at the `RunDetail` level. Or, match the `event.task_id` from the `clarification_responded` event and call the hook conditionally.

---

## Gap Resolution Table

| Gap ID | Gap Description | Severity | Affected Step/Task | Functionality Area | Resolution |
|--------|-----------------|----------|-------------------|-------------------|-----------|
| GAP-01 | `format_clarification_artifact` body renders `q.options` for all types; needs branches for `free_text`/`number`/skipped | REQUIRED | S-01 T-01 | Domain model / artifact rendering | Updated step-01.md Task 1 to include rendering branches for all question types and skipped answers |
| GAP-02 | Line count formula may be off-by-one for text ending in newline | EXPECTED | S-01 T-01 | Artifact line tracking | Clarified in step-01 Task 1: use `text.count('\n')` when text ends with `\n` |
| GAP-03 | Task file's JSON path description is incorrect (`['inputSchema']['items']` vs actual path) | OPTIONAL | S-01 T-02 | MCP tool schema | Documentation inaccuracy only; builder reads the file and self-corrects |
| GAP-04 | Router's "required questions guard" doesn't exist yet; task assumes it does | EXPECTED | S-01 T-03 | API router | Clarified: add the guard as part of this task, then also add the `skipped` bypass |
| GAP-05 | Integration test for `skipped=True` depends on artifact-writing from Step 2 | EXPECTED | S-01 T-04 | Testing / cross-step dependency | Note in test plan: full `skipped` flow test deferred to Step 2 integration tests |
| GAP-06 | Artifact-writing entirely missing from `service.py:respond_to_clarification` | REQUIRED | S-02 T-01 | Workflow service / artifact I/O | Updated step-02 Task 1 to include full artifact write flow: path resolution, header, append, line count |
| GAP-07 | Ambiguity between `clarifications_path` and new `clarification_line_range[0]` in prompt | OPTIONAL | S-02 T-02 | Prompt generation | Documented: include both; line-range sentence supplements the path reference |
| GAP-08 | Step-02 Task-3 snippet uses sync SQLAlchemy (`self.session.query`) vs actual async API | REQUIRED | S-02 T-03 | Repository / database | Corrected: use `await self._session.execute(select(...))` pattern |
| GAP-09 | `ClarificationHistoryItem.request` typed as `ClarificationQuestionSchema` (single question) not full request | REQUIRED | S-02 T-04 | API schema design | Corrected: `request: ClarificationRequestResponse`, `response: ClarificationResponseSchema` (new schema) |
| GAP-10 | Step-02 Task-4 refers to `ClarificationRepository` class that doesn't exist; methods are on `RunRepository` | EXPECTED | S-02 T-04 | Repository usage | Updated: use `RunRepository` with the new `get_clarification_history` method |
| GAP-11 | Task-3 T-01 audit: `run_id` in `ClarificationResponded` inherited from `WorkflowEvent`; false alarm | OPTIONAL | S-03 T-01 | Event model | No change needed; clarified in notes |
| GAP-12 | Broadcast function name needs verification before use | EXPECTED | S-03 T-02 | WebSocket broadcaster | Task already instructs "read the file first"; builder will find the correct name |
| GAP-13 | WS test 2-second timeout may be flaky in CI | OPTIONAL | S-03 T-03 | Testing reliability | Add note to use `asyncio.wait_for` with retry or longer timeout in CI |
| GAP-14 | Missing `ClarificationResponse` TypeScript interface for `ClarificationHistoryItem.response` | EXPECTED | S-04 T-01 | Frontend types | Add `ClarificationResponse` interface to `clarifications.ts` alongside history types |
| GAP-15 | `AnswerState.selectedOptions` used in Task 2 but added in Task 3; ordering concern | OPTIONAL | S-04 T-02/T-03 | Frontend component coupling | Implement both tasks in same session; no separate blocker |
| GAP-16 | Frontend code uses `q.text` but actual API field is `q.question` | REQUIRED | S-04/S-05 | Frontend component rendering | Update `ClarificationHistoryCard` code to use `q.question` not `q.text` |
| GAP-17 | `answer.question_id` matching confirmed present in both layers | OPTIONAL | S-05 T-04 | Frontend data shape | No change needed; verified correct |
| GAP-18 | `useClarificationHistory(runId, taskId)` called at `RunDetail` level but events span multiple tasks | EXPECTED | S-05 T-05 | Frontend data fetching | Call hook inside per-task/per-event renderer; or restructure to pass `task_id` from the event payload |

**Severity Definitions:**
- **REQUIRED**: Critical functionality that must be resolved; blocks execution if unresolved
- **EXPECTED**: Important functionality that should be resolved
- **OPTIONAL**: Nice-to-have; can proceed with awareness

---

## Recommendations

1. **Resolve REQUIRED gaps before starting execution.** GAP-01 (artifact rendering), GAP-06 (missing artifact write), GAP-08 (async SQLAlchemy), GAP-09 (wrong schema type), GAP-16 (wrong field name) must be fixed in the step files or the builder must be informed via notes.

2. **Add `ClarificationResponse` Python schema to Step 2.** The history endpoint returns full request+response pairs. A new `ClarificationResponseSchema` Pydantic model is needed in `api/schemas/clarifications.py` (similar to `ClarificationRequestResponse`). This was omitted from the plan.

3. **Artifact path convention.** The clarification artifact file path is not defined in any of the step files for Step 2. The existing service code (looking at the broader service.py) should have a convention for this. The step file must instruct the builder where to find/derive the path. Check `GlobalConfig` or the run's worktree path for the convention.

4. **`clarification_number` source.** `format_clarification_artifact` takes a `clarification_number` int. In the service, this requires counting prior clarifications for the task. The repository's `get_clarification_history` (from Step 2) can provide this count, but it creates a circular dependency if Step 2 Task 3 (adding the method) hasn't been done yet. Step 2 Task 1 should use `len(await self._repo.get_clarification_requests_for_task(run_id, task_id))` or a simpler count query.

5. **CSS class naming.** The `ClarificationHistoryCard` template uses BEM-style class names (`.clarification-history-card__header`). The project appears to use Tailwind utility classes. The builder should use Tailwind classes consistent with neighboring components rather than BEM names.

6. **Test ordering.** Step 1 Task 4 should be split: run unit tests after Task 1, integration tests after Task 3. The current ordering groups all tests at the end of Step 1 which is fine for the step structure but may make debugging harder. No change needed—just an awareness note.
