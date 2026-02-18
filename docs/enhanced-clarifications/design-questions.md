# Design Questions: Enhanced Clarification System

## Open Questions

### Q1: Should `multi_select` answers extend `ClarificationAnswer` with a new field or reuse `selected_option`?

- **Context:** `ClarificationAnswer.selected_option` is typed as `str | None` – a single value. Multi-select requires a list. We need to decide whether to add a `selected_options: list[str] | None` field alongside the existing field or to replace/repurpose `selected_option` for all types.
- **Options:**
  1. **Add `selected_options: list[str] | None` (additive)** – `single_select` uses `selected_option`; `multi_select` uses `selected_options`. Old answers remain valid; API consumers check whichever field applies.
  2. **Replace both with `answers: list[str]`** – Unify all select types under a single `list[str]` field. `single_select` would have exactly one item. Breaking change for existing `selected_option` consumers.
  3. **Comma-encode into `selected_option`** – Store `"opt1,opt2"` in the existing string field. Simple but fragile if option text contains commas.
- **Impact:** Affects `ClarificationAnswer` (Python model + Pydantic schema), TypeScript type, `format_clarification_artifact`, and `QuestionCard` rendering. Whichever shape is chosen must be consistent across all layers.
- **Priority:** High – must be resolved before any code is written (blocks Step 1)
- **Status:** Open
- **Recommendation:** Option 1 (additive). Minimises backward-compat risk; existing `selected_option` tests remain green; new `selected_options` field is nullable so old code paths are unaffected.

---

### Q2: How should the builder prompt communicate clarification answers when the user force-skips?

- **Context:** When `skipped=True`, the builder resumes without complete answers. The prompt must signal which questions were skipped and why so the builder doesn't stall waiting for missing data. Two approaches differ in how much context the prompt includes.
- **Options:**
  1. **Inline skip summary in prompt text** – After the clarifications file reference, append: `"The user declined to answer the following questions: {Q-list}. Reason: {reason}. Proceed with your best judgment for those items."` This is self-contained.
  2. **Record skip in artifact file only** – `format_clarification_artifact` renders skipped questions as `**Answer:** (skipped) {reason}`; prompt only points to the file path+line. Builder reads the file to learn about skips.
- **Impact:** Option 1 is more reliable (builder sees the skip signal without having to read a file); Option 2 keeps the prompt shorter and consistent with the non-skip path. Risk with Option 2: builder may not re-read the artifact file on every resume.
- **Priority:** High – affects `workflow/prompts.py` and `workflow/service.py` design
- **Status:** Open
- **Recommendation:** Option 1. The builder prompt is the primary communication channel; inline text guarantees the LLM sees the skip signal. The artifact file still records the skip for auditability.

---

### Q3: Should the `GET /api/runs/{id}/tasks/{task_id}/clarifications` history endpoint return *all* rounds or only *completed* (responded) rounds?

- **Context:** A task may have one pending (unanswered) clarification request at any time. The history UI is intended for reviewing past Q&A. Should the pending request also appear in the history list (as "in progress") or only in the existing `GET .../pending` endpoint?
- **Options:**
  1. **All rounds including pending** – History endpoint returns all requests, with `responded_at: null` for the pending one. UI can distinguish state by checking `responded_at`.
  2. **Completed rounds only** – History endpoint returns only responded requests. The pending request remains accessible only via the existing `GET .../pending` endpoint.
- **Impact:** Affects query logic in the repository, schema design, and frontend rendering logic. Option 1 is simpler for the frontend (one query for full picture); Option 2 avoids duplication with the existing pending endpoint.
- **Priority:** Medium – affects Step 2 deliverable (history endpoint)
- **Status:** Open
- **Recommendation:** Option 1. The frontend can always tell completed vs. pending via `responded_at`. Having one endpoint for the full history simplifies the RunDetail data-fetching tree.

---

### Q4: What is the right WebSocket payload for `ClarificationRequested` – minimal (IDs only) or full question data?

- **Context:** `ClarificationRequested` currently stores `task_id`, `request_id`, and `question_count`. When the frontend receives this event, it must either (a) fetch the full pending clarification via `GET .../pending` before opening the modal, or (b) receive enough data in the WS payload to open the modal immediately without a round-trip.
- **Options:**
  1. **Minimal payload (current)** – Frontend invalidates `['pending-clarification', runId, taskId]` on WS event; React Query refetches; modal opens when query settles (~100ms extra). One extra HTTP round-trip.
  2. **Full payload** – Embed the full `ClarificationRequest` JSON in the WS message. Frontend can open the modal immediately without fetching. Larger WS messages.
- **Impact:** Option 1 requires no changes to the `ClarificationRequested` dataclass or the WS broadcaster. Option 2 requires extending the dataclass and ensuring serialization is consistent.
- **Priority:** Medium – affects Step 3 (WebSocket broadcast milestone)
- **Status:** Open
- **Recommendation:** Option 1. The extra HTTP round-trip is negligible (sub-second). Keeping WS messages minimal avoids serialization inconsistencies between the event dataclass and the API schema.

---

### Q5: Should `number` question type validation (min/max) be enforced server-side as well as client-side?

- **Context:** The `number` question type has optional `min` and `max` fields. The frontend `QuestionCard` will validate these on input. However, if the LLM or a direct API caller submits an out-of-range answer, there is no server-side guard without explicit validation in `api/routers/clarifications.py`.
- **Options:**
  1. **Client-side only** – Backend stores whatever numeric string is submitted. Simpler; consistent with how `free_text` answers are unvalidated.
  2. **Server-side validation in the router** – When `question_type == 'number'`, parse `free_text` (which stores the numeric value) and check against `min`/`max` from the question definition. Return 422 on violation.
  3. **Pydantic validator on `ClarificationAnswer`** – Requires the answer schema to carry `min`/`max` context from the question, which couples answer to question model.
- **Impact:** Server-side validation (Option 2) catches programmatic misuse but adds complexity to the router. Client-side only (Option 1) is simpler and sufficient for the MVP given that the UI is the only consumer.
- **Priority:** Low – does not block other work; can be deferred
- **Status:** Open
- **Recommendation:** Option 1 (client-side only) for MVP. Add a TODO comment in the router for future server-side validation.

---

## Resolved Questions

<!-- Move questions here once resolved -->
