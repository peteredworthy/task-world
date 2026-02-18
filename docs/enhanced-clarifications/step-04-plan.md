# Step 04 Plan: Frontend – Question Types & Skip (10a + 10e frontend)

## Purpose

Update the frontend to render all four question types (single_select, multi_select, free_text, number) and support the user force-skip flow. TypeScript types are extended to mirror the new backend schema. `QuestionCard` branches on `question_type`; `ClarificationModal` handles multi-select answer state, type-aware validation, and the "Skip remaining" action.

## Prerequisites

- **Step 1 complete**: backend schemas are stable and API contracts are known. Frontend can be implemented against the documented contracts without waiting for Steps 2 or 3.
- Step 2 and Step 3 do NOT need to be complete before starting this step.

## Functional Contract

### Inputs

- `ClarificationQuestion` TypeScript type (received from `GET .../pending-actions` / `GET .../clarifications/{id}`):
  ```ts
  question_type: 'single_select' | 'multi_select' | 'free_text' | 'number'
  allow_other: boolean
  required: boolean
  min?: number | null
  max?: number | null
  placeholder?: string | null
  options: string[]  // populated for select types; empty for free_text/number
  ```
- `RespondToClarificationRequest` mutation payload:
  ```ts
  answers: ClarificationAnswer[]  // may be partial when skipped=true
  skipped?: boolean
  skip_reason?: string | null
  ```
- `ClarificationAnswer` per question:
  ```ts
  question_id: string
  selected_option?: string        // single_select
  selected_options?: string[]     // multi_select
  other_text?: string             // free_text answer or "other" text
  skipped?: boolean
  skip_reason?: string | null
  ```

### Outputs

- `QuestionCard` renders:
  - `single_select`: radio buttons, optional "Other" textarea (controlled by `allow_other`), required indicator (`*`) when `required=true`
  - `multi_select`: checkboxes, optional "Other" checkbox+textarea, required indicator
  - `free_text`: textarea with `placeholder`, required indicator
  - `number`: `<input type="number">` with `min`, `max`, `placeholder`, inline validation message; required indicator
- `ClarificationModal`:
  - Maintains `selectedOptions: string[]` per question for multi-select answers
  - Validates: if `required`, at least one option/value must be present (type-specific); for `number`, checks `min`/`max`
  - Shows "Skip remaining" button when: at least one required question is answered OR all questions are optional
  - On skip: reveals reason textarea; on confirm submits `{skipped: true, skip_reason, answers: <partial>}`
  - Backward-compatible: existing `single_select` flow unchanged

### Errors

- `number` input: display inline validation message (client-side only per Q5) when value is outside `[min, max]` range; "Submit" button is disabled.
- `multi_select` required with zero selections: "Submit" button is disabled with a visual indicator.
- `free_text` required with empty string: "Submit" button is disabled.
- Skip without a reason: allowed (reason textarea is optional); `skip_reason` sent as `null`.

## Tasks

1. Update `ui/src/types/clarifications.ts`: add `question_type`, `allow_other`, `required`, `min`, `max`, `placeholder` to `ClarificationQuestion`; add `selected_options`, `skipped`, `skip_reason` to `ClarificationAnswer`; add `skipped`, `skip_reason` to `RespondToClarificationRequest`.
2. Update `ui/src/components/detail/QuestionCard.tsx`: add `onOptionsChange` prop for multi-select; branch on `question_type` to render the four input variants; show required indicator; respect `allow_other`.
3. Update `ui/src/components/detail/ClarificationModal.tsx`: extend `AnswerState` with `selectedOptions: string[]`; add multi-select answer handler; update validation logic per question type; add "Skip remaining" button with reason textarea and conditional visibility logic; update submit handler to build payload with `skipped` / `skip_reason`.
4. Smoke-test the existing `single_select` flow to confirm backward compatibility (no regressions).

## Verification

### Auto-Verify

- [ ] `cd ui && npm run typecheck` (or `tsc --noEmit`) passes with no TypeScript errors.
- [ ] `cd ui && npm run lint` passes on changed files.
- [ ] `cd ui && npm test` (vitest / jest) passes; unit tests for `QuestionCard` cover all four question types; unit tests for `ClarificationModal` cover validation and skip-submit path.

### Manual Verify

- [ ] Open the clarification modal with a `multi_select` question; select two options; confirm both appear in the submitted payload.
- [ ] Open the modal with a `free_text` question; submit empty text for a required question; confirm submit is disabled.
- [ ] Open the modal with a `number` question and enter a value outside `[min, max]`; confirm inline error message and disabled submit.
- [ ] Click "Skip remaining" after answering one question; enter a reason; confirm the payload includes `skipped: true` and the reason.
- [ ] Open the modal with the existing `single_select` question type; confirm no regression in UX or behavior.

## Context & References

- `ui/src/types/clarifications.ts` – TypeScript domain types to extend
- `ui/src/components/detail/QuestionCard.tsx` – question renderer to update
- `ui/src/components/detail/ClarificationModal.tsx` – modal to update (validation + skip)
- `docs/enhanced-clarifications/architecture.md` – field list, UI component spec, skip flow description
- `docs/enhanced-clarifications/design-questions.md` – Q1 (multi-select encoding), Q2 (skip signal), Q5 (client-side number validation only)
- Step 1 plan – prerequisite; backend schema contracts
