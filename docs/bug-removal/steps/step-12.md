# Step 12: Routine YAML Validation UI (UI-ROUTINE-VALIDATION)

This step adds a YAML validation editor/modal that lets users paste or type a routine YAML
definition, validate it against the backend schema, and review inline errors with line numbers
before creating a run. The backend `POST /api/routines/validate` endpoint exists; the frontend
has no client function, hook, or UI for it. The modal is accessible from `RoutineSelector` or
`CreateRunModal` (no new route required), and includes a "Create run from this routine" shortcut
on a valid result.

## Intent Verification
**Original Intent**: `docs/bug-removal/intent.md` — "Routine YAML validation page or modal exists with error display; validated routine can flow into run creation"
**Functionality to Produce**:
- `validateRoutine(yamlContent)` in `ui/src/api/client.ts`
- `useValidateRoutine()` mutation hook in `ui/src/hooks/useApi.ts`
- Routine validator modal/component with textarea, Validate button, inline error list, success shortcut
- `CreateRunModal.tsx` (or `RoutineSelector`) exposes a trigger to open the validator

**Final Verification Criteria**:
- `npx tsc --noEmit` passes with no type errors
- `validateRoutine` exported from `client.ts`
- `useValidateRoutine` exported from `useApi.ts`
- Vitest test for validator modal passes (error list and success shortcut cases)

---

## Task 1: Add validateRoutine client function and useValidateRoutine hook
**Description**:
Add the API client function for `POST /api/routines/validate` and the TanStack Query mutation
hook.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/api/client.ts`
- [ ] Add the client function and types:
```typescript
export interface ValidationError {
  line: number;
  message: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
}

export async function validateRoutine(yamlContent: string): Promise<ValidationResult> {
  const response = await fetch('/api/routines/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ yaml_content: yamlContent }),
  });
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}
```
- [ ] Open `ui/src/hooks/useApi.ts`
- [ ] Add the mutation hook:
```typescript
export function useValidateRoutine() {
  return useMutation({
    mutationFn: (yamlContent: string) => validateRoutine(yamlContent),
  });
}
```

**References**
- `docs/bug-removal/step-12-plan.md` — Task 1 and Task 2 descriptions
- `docs/bugs/UI-ROUTINE-VALIDATION.md`
- Backend endpoint: `POST /api/routines/validate` in `src/orchestrator/api/routers/`

**Constraints**
- [ ] Only `ui/src/api/client.ts` and `ui/src/hooks/useApi.ts` should be changed in this task
- [ ] `ValidationError` and `ValidationResult` types can live in `client.ts` or in `ui/src/types/`

**Functionality (Expected Outcomes)**
- [ ] `validateRoutine` exported from `ui/src/api/client.ts`
- [ ] `useValidateRoutine` exported from `ui/src/hooks/useApi.ts`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `grep -n "validateRoutine" ui/src/api/client.ts` shows the export
- [ ] `grep -n "useValidateRoutine" ui/src/hooks/useApi.ts` shows the export

---

## Task 2: Create the routine validator modal component
**Description**:
Create a routine validator modal component with a YAML textarea, a Validate button, inline error
list with line numbers, and a "Create run from this routine" shortcut button that appears on a
valid result.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/RoutineValidatorModal.tsx` (or `ui/src/components/routine/RoutineValidatorModal.tsx`):
```typescript
interface RoutineValidatorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreateRun?: (yamlContent: string) => void;
}

export function RoutineValidatorModal({ isOpen, onClose, onCreateRun }: RoutineValidatorModalProps) {
  const [yamlContent, setYamlContent] = useState('');
  const validateMutation = useValidateRoutine();

  const handleValidate = () => {
    validateMutation.mutate(yamlContent);
  };

  const result = validateMutation.data;

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Validate Routine YAML">
      <textarea
        value={yamlContent}
        onChange={(e) => setYamlContent(e.target.value)}
        placeholder="Paste your routine YAML here..."
        rows={20}
      />
      <button onClick={handleValidate} disabled={validateMutation.isPending}>
        {validateMutation.isPending ? 'Validating...' : 'Validate'}
      </button>

      {/* Error display */}
      {result && !result.valid && (
        <ul className="text-red-600">
          {result.errors.map((err, i) => (
            <li key={i}>Line {err.line}: {err.message}</li>
          ))}
        </ul>
      )}

      {/* Success state */}
      {result?.valid && (
        <div>
          <p className="text-green-600">Valid routine YAML</p>
          <button onClick={() => { onCreateRun?.(yamlContent); onClose(); }}>
            Create run from this routine
          </button>
        </div>
      )}

      {/* API error */}
      {validateMutation.isError && (
        <p className="text-red-600">Validation service error. Please try again.</p>
      )}
    </Modal>
  );
}
```

**References**
- `docs/bug-removal/step-12-plan.md` — Task 3 description
- `docs/bug-removal/architecture.md` — "New Components: Routine validator modal", routing decision (modal not page)

**Constraints**
- [ ] Modal approach (not a new route) to keep routing simple
- [ ] Only the new modal file should be created in this task

**Functionality (Expected Outcomes)**
- [ ] Modal renders textarea, Validate button, and inline error list
- [ ] Error list shows line numbers for each error
- [ ] "Create run from this routine" button appears only when `valid === true`
- [ ] API error shows a generic error message without crashing

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] File exists: `ui/src/components/RoutineValidatorModal.tsx` (or equivalent path)

---

## Task 3: Wire validator modal into CreateRunModal, write Vitest test
**Description**:
Update `CreateRunModal.tsx` (or `RoutineSelector`) to expose a trigger that opens the
`RoutineValidatorModal`. Write Vitest tests for the validator: error list with line numbers and
the success shortcut.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/CreateRunModal.tsx` (locate the correct file by searching for `CreateRunModal`)
- [ ] Add a "Validate YAML" button or link that opens the `RoutineValidatorModal`:
```typescript
const [validatorOpen, setValidatorOpen] = useState(false);

// In the render:
<button onClick={() => setValidatorOpen(true)}>Validate routine YAML</button>

<RoutineValidatorModal
  isOpen={validatorOpen}
  onClose={() => setValidatorOpen(false)}
  onCreateRun={(yaml) => {
    // pre-fill the routine field in CreateRunModal with the validated YAML
    setRoutineYaml(yaml);
    setValidatorOpen(false);
  }}
/>
```
- [ ] Write a Vitest test in `ui/src/components/__tests__/RoutineValidatorModal.test.tsx`:
```typescript
const errorResult: ValidationResult = {
  valid: false,
  errors: [
    { line: 3, message: 'Unexpected key "foo"' },
  ],
};

const validResult: ValidationResult = {
  valid: true,
  errors: [],
};

test('shows error list with line numbers on invalid result', () => {
  // mock useValidateRoutine to return errorResult
  render(<RoutineValidatorModal isOpen onClose={jest.fn()} />);
  // fire validate
  expect(screen.getByText(/Line 3: Unexpected key/i)).toBeInTheDocument();
});

test('shows create run shortcut on valid result', () => {
  // mock useValidateRoutine to return validResult
  render(<RoutineValidatorModal isOpen onClose={jest.fn()} onCreateRun={jest.fn()} />);
  // fire validate
  expect(screen.getByRole('button', { name: /create run from this routine/i })).toBeInTheDocument();
});
```
- [ ] Run `npx vitest run` and confirm all tests pass

**References**
- `docs/bug-removal/step-12-plan.md` — Task 4 and Task 5 descriptions
- `docs/bug-removal/architecture.md` — "Key decision: modal accessible from RoutineSelector or CreateRunModal"

**Constraints**
- [ ] Only `CreateRunModal.tsx` (or `RoutineSelector`) is modified; no new routes are added
- [ ] The validator must be accessible without navigating away from the run creation flow

**Functionality (Expected Outcomes)**
- [ ] `CreateRunModal` (or `RoutineSelector`) exposes a trigger to open the validator modal
- [ ] Validator modal is accessible without a new route
- [ ] "Create run from this routine" shortcut pre-fills the run creation form with the validated YAML
- [ ] Vitest tests for the validator pass (error list case and success shortcut case)

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `npx vitest run` exits 0 (all tests pass including the new RoutineValidatorModal tests)
