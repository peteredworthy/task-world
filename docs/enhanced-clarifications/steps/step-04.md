# Step 04: Frontend – Question Types & Skip (10a + 10e frontend)

Update the frontend to render all four question types (single_select, multi_select, free_text, number) and support the user force-skip flow. TypeScript types are extended to mirror the new backend schema. `QuestionCard` branches on `question_type`; `ClarificationModal` handles multi-select answer state, type-aware validation, and the "Skip remaining" action.

## Intent Verification
**Original Intent**: `docs/enhanced-clarifications/intent.md` – "Richer question types" rendered in the UI and "User force-skip – users can skip optional questions or force-skip an entire clarification request with a reason"

**Functionality to Produce**:
- `ClarificationQuestion` TypeScript type has all new fields
- `QuestionCard` renders radio buttons, checkboxes, textarea, and number input per `question_type`
- `ClarificationModal` validates per `required` flag and `question_type`; shows "Skip remaining" button
- Submit with `skipped: true` includes `skip_reason` and partial answers
- All existing `single_select` behavior is unchanged

**Final Verification Criteria**:
- `npm run typecheck` passes with no TypeScript errors
- `npm run lint` passes on changed files
- `npm test` passes; unit tests cover all four question types and skip-submit path
- Existing `single_select` flow is visually and behaviorally unchanged

---

## Task 1: Extend TypeScript types in clarifications.ts

**Description**: Mirror all new backend fields in the TypeScript domain types so the rest of the frontend is fully typed.

**Implementation Plan (Do These Steps)**

- [ ] Open `ui/src/types/clarifications.ts` and read it fully.
- [ ] Update `ClarificationQuestion` to add:
```ts
question_type: 'single_select' | 'multi_select' | 'free_text' | 'number';
allow_other: boolean;
required: boolean;
min?: number | null;
max?: number | null;
placeholder?: string | null;
```
- [ ] Update `ClarificationAnswer` to add:
```ts
selected_options?: string[];
skipped?: boolean;
skip_reason?: string | null;
```
- [ ] Update `RespondToClarificationRequest` to add:
```ts
skipped?: boolean;
skip_reason?: string | null;
```
- [ ] Add a new type (used in Step 5):
```ts
export interface ClarificationHistoryItem {
  request: ClarificationRequest;
  response: ClarificationResponse | null;
}

export interface ClarificationHistoryResponse {
  items: ClarificationHistoryItem[];
}
```

**Dependencies**
- [ ] Step 1 complete: backend API contracts are stable.

**References**
- `docs/enhanced-clarifications/architecture.md` – "Modified Components: ui/src/types/clarifications.ts"
- `docs/enhanced-clarifications/step-04-plan.md` – Task 1, Functional Contract (Inputs)

**Constraints**
- [ ] Only `clarifications.ts` changes in this task.
- [ ] All existing fields must remain (additive changes only).
- [ ] Use `?` for optional fields to maintain backward compatibility with older server responses.

**Functionality (Expected Outcomes)**
- [ ] TypeScript accepts `{ question_type: 'multi_select', options: ['A', 'B'], allow_other: false, required: true }` as a valid `ClarificationQuestion`
- [ ] TypeScript accepts `{ skipped: true, skip_reason: 'N/A', answers: [] }` as a valid `RespondToClarificationRequest`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `cd ui && npm run typecheck` passes with no errors
- [ ] `cd ui && npm run lint` passes on `clarifications.ts`

---

## Task 2: Update QuestionCard to render all four question types

**Description**: Branch `QuestionCard` on `question_type` and render the appropriate input element for each type.

**Implementation Plan (Do These Steps)**

- [ ] Open `ui/src/components/detail/QuestionCard.tsx` and read it fully.
- [ ] Add an `onOptionsChange` prop for multi-select (alongside the existing `onOptionChange`):
```tsx
interface QuestionCardProps {
  question: ClarificationQuestion;
  answer: AnswerState;
  onOptionChange: (questionId: string, value: string) => void;
  onOptionsChange: (questionId: string, values: string[]) => void;
  onTextChange: (questionId: string, value: string) => void;
}
```
- [ ] Wrap the existing radio-button JSX in a `question.question_type === 'single_select'` branch.
- [ ] Add a `multi_select` branch rendering checkboxes:
```tsx
} else if (question.question_type === 'multi_select') {
  return (
    <div>
      {question.required && <span aria-label="required">*</span>}
      {question.options.map((opt) => (
        <label key={opt}>
          <input
            type="checkbox"
            checked={(answer.selectedOptions ?? []).includes(opt)}
            onChange={(e) => {
              const current = answer.selectedOptions ?? [];
              const next = e.target.checked
                ? [...current, opt]
                : current.filter((o) => o !== opt);
              onOptionsChange(question.id, next);
            }}
          />
          {opt}
        </label>
      ))}
      {question.allow_other && (
        <label>
          <input type="checkbox" ... /> Other
          <textarea ... />
        </label>
      )}
    </div>
  );
```
- [ ] Add a `free_text` branch rendering a textarea:
```tsx
} else if (question.question_type === 'free_text') {
  return (
    <div>
      {question.required && <span aria-label="required">*</span>}
      <textarea
        placeholder={question.placeholder ?? ''}
        value={answer.textValue ?? ''}
        onChange={(e) => onTextChange(question.id, e.target.value)}
      />
    </div>
  );
```
- [ ] Add a `number` branch rendering a number input with inline validation:
```tsx
} else if (question.question_type === 'number') {
  const val = parseFloat(answer.textValue ?? '');
  const invalid =
    !isNaN(val) &&
    ((question.min != null && val < question.min) ||
     (question.max != null && val > question.max));
  return (
    <div>
      {question.required && <span aria-label="required">*</span>}
      <input
        type="number"
        min={question.min ?? undefined}
        max={question.max ?? undefined}
        placeholder={question.placeholder ?? ''}
        value={answer.textValue ?? ''}
        onChange={(e) => onTextChange(question.id, e.target.value)}
      />
      {invalid && (
        <span role="alert">
          Value must be between {question.min} and {question.max}.
        </span>
      )}
    </div>
  );
```
- [ ] Show required indicator (`*`) consistently across all branches.
- [ ] Hide "Other" option when `question.allow_other === false`.

**References**
- `docs/enhanced-clarifications/architecture.md` – "Modified Components: ui/src/components/detail/QuestionCard.tsx"
- `docs/enhanced-clarifications/step-04-plan.md` – Task 2, Functional Contract (Outputs)

**Constraints**
- [ ] Only `QuestionCard.tsx` changes in this task.
- [ ] The existing `single_select` rendering path must be preserved exactly—no regressions.

**Functionality (Expected Outcomes)**
- [ ] `single_select` question renders radio buttons (unchanged)
- [ ] `multi_select` question renders checkboxes
- [ ] `free_text` question renders a textarea with optional placeholder
- [ ] `number` question renders a number input; shows inline error when value is out of `[min, max]`
- [ ] Required indicator `*` appears on all required questions

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `cd ui && npm test -- QuestionCard` passes for all four question-type unit tests
- [ ] `cd ui && npm run typecheck` passes
- [ ] `cd ui && npm run lint` passes on `QuestionCard.tsx`

---

## Task 3: Update ClarificationModal for multi-select state, validation, and skip flow

**Description**: Extend `ClarificationModal` to handle the new answer state, validate per `required` and `question_type`, and support "Skip remaining" with an optional reason.

**Implementation Plan (Do These Steps)**

- [ ] Open `ui/src/components/detail/ClarificationModal.tsx` and read it fully.
- [ ] Extend `AnswerState` to include:
```ts
interface AnswerState {
  selectedOption?: string;
  selectedOptions?: string[];  // NEW: for multi_select
  textValue?: string;
  otherText?: string;
  skipped?: boolean;
}
```
- [ ] Add a multi-select answer handler:
```ts
const handleOptionsChange = (questionId: string, values: string[]) => {
  setAnswers((prev) => ({
    ...prev,
    [questionId]: { ...prev[questionId], selectedOptions: values },
  }));
};
```
- [ ] Pass `onOptionsChange={handleOptionsChange}` to `QuestionCard`.
- [ ] Update the validation logic to be type-aware:
```ts
const isAnswerComplete = (q: ClarificationQuestion, a: AnswerState): boolean => {
  if (!q.required) return true;
  if (q.question_type === 'single_select') return !!a.selectedOption || !!a.otherText;
  if (q.question_type === 'multi_select') return (a.selectedOptions?.length ?? 0) > 0 || !!a.otherText;
  if (q.question_type === 'free_text') return (a.textValue?.trim().length ?? 0) > 0;
  if (q.question_type === 'number') {
    const val = parseFloat(a.textValue ?? '');
    if (isNaN(val)) return false;
    if (q.min != null && val < q.min) return false;
    if (q.max != null && val > q.max) return false;
    return true;
  }
  return false;
};
const canSubmit = questions.every((q) => isAnswerComplete(q, answers[q.id] ?? {}));
```
- [ ] Add skip UI state:
```ts
const [showSkip, setShowSkip] = useState(false);
const [skipReason, setSkipReason] = useState('');
```
- [ ] Show "Skip remaining" button when at least one required question has an answer OR all questions are optional:
```ts
const canSkip =
  questions.every((q) => !q.required) ||
  questions.some((q) => q.required && isAnswerComplete(q, answers[q.id] ?? {}));
```
- [ ] Render skip UI:
```tsx
{canSkip && !showSkip && (
  <button onClick={() => setShowSkip(true)}>Skip remaining</button>
)}
{showSkip && (
  <div>
    <textarea
      placeholder="Reason for skipping (optional)"
      value={skipReason}
      onChange={(e) => setSkipReason(e.target.value)}
    />
    <button onClick={handleSkipSubmit}>Confirm skip</button>
    <button onClick={() => setShowSkip(false)}>Cancel</button>
  </div>
)}
```
- [ ] Implement `handleSkipSubmit`:
```ts
const handleSkipSubmit = () => {
  const partialAnswers = buildAnswers(); // existing answer-building logic
  onRespond({
    answers: partialAnswers,
    skipped: true,
    skip_reason: skipReason || null,
  });
};
```
- [ ] Update `buildAnswers()` to include `selected_options` for multi-select questions.

**References**
- `docs/enhanced-clarifications/architecture.md` – "Modified Components: ui/src/components/detail/ClarificationModal.tsx"
- `docs/enhanced-clarifications/step-04-plan.md` – Task 3, Functional Contract (Outputs, Errors)
- `docs/enhanced-clarifications/design-questions.md` – Q2 (skip signal), Q5 (client-side only number validation)

**Constraints**
- [ ] Only `ClarificationModal.tsx` changes in this task (besides `QuestionCard` already updated in Task 2).
- [ ] The existing single-answer submit path must be preserved; no regressions.

**Functionality (Expected Outcomes)**
- [ ] Multi-select question: selecting 2 options produces `selected_options: ['A', 'B']` in submit payload
- [ ] Required free_text with empty value: Submit button is disabled
- [ ] Number question with out-of-range value: Submit button is disabled
- [ ] "Skip remaining" button visible when one required question is answered
- [ ] Clicking "Skip remaining" → entering reason → confirm produces `{skipped: true, skip_reason: '...', answers: [...]}`
- [ ] Skip reason is optional; submitting without reason sends `skip_reason: null`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `cd ui && npm test -- ClarificationModal` passes all unit tests (validation, skip-submit)
- [ ] `cd ui && npm run typecheck` passes
- [ ] `cd ui && npm run lint` passes on `ClarificationModal.tsx`
- [ ] Manual: open modal with `single_select` question; confirm UX is identical to before
