# Step 12 Plan: Routine YAML Validation UI (UI-ROUTINE-VALIDATION)

## Purpose

Add a YAML validation editor/modal that lets users paste or type a routine YAML definition, validate it against the backend schema, and review inline errors with line numbers before creating a run. The backend `POST /api/routines/validate` endpoint exists; the frontend has no client function, hook, or UI for it. The modal will be accessible from `RoutineSelector` or `CreateRunModal` and will include a "Create run from this routine" shortcut when the YAML is valid, keeping the flow integrated without adding a new route.

## Prerequisites

- None (independent of all other steps)

## Functional Contract

### Inputs

- User-pasted or typed YAML string in the validation textarea
- `POST /api/routines/validate` request body: `{ yaml_content: string }`
- `POST /api/routines/validate` response: `{ valid: boolean, errors: [{ line: number, message: string }] }`

### Outputs

- `validateRoutine(yamlContent: string)` function added to `ui/src/api/client.ts` calling `POST /api/routines/validate`
- `useValidateRoutine()` mutation hook added to `ui/src/hooks/useApi.ts`
- Routine validator modal or inline component (accessible from `RoutineSelector` or `CreateRunModal`):
  - Textarea for YAML input
  - "Validate" button that calls `useValidateRoutine`
  - On error: inline error list showing line number and message for each error
  - On success: "Valid" indicator and a "Create run from this routine" shortcut button
- `CreateRunModal.tsx` (or `RoutineSelector`) updated to expose a link/button that opens the validator

### Errors

- `validateRoutine` API 500 — show generic error toast; keep textarea and error list visible
- Network error — show "Connection error, please try again" and clear loading state
- Valid YAML with semantic errors in the schema — backend returns `{ valid: false, errors: [...] }`; display them inline
- TypeScript compile errors must be zero

## Tasks

1. Add `validateRoutine(yamlContent)` to `ui/src/api/client.ts`
2. Add `useValidateRoutine()` mutation hook to `ui/src/hooks/useApi.ts`
3. Create the routine validator modal/component (modal is preferred to avoid a new route): textarea, Validate button, inline error list with line numbers, "Create run from this routine" shortcut on success
4. Update `ui/src/components/CreateRunModal.tsx` (or `RoutineSelector`) to expose a trigger that opens the validator modal
5. Write Vitest test: render the validator with a mock validation response containing errors; confirm error list shows line numbers; render with a valid response and confirm the "Create run" shortcut appears

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `validateRoutine` is exported from `ui/src/api/client.ts`
- [ ] `useValidateRoutine` is exported from `ui/src/hooks/useApi.ts`
- [ ] Vitest test for the validator modal passes (error list and success shortcut)

### Manual Verify

- [ ] Validator modal is accessible from `CreateRunModal` or `RoutineSelector` (no new route required)
- [ ] Pasting invalid YAML and clicking Validate shows line-numbered errors inline
- [ ] Pasting valid YAML and clicking Validate shows a "Valid" confirmation and a "Create run from this routine" button
- [ ] Clicking "Create run from this routine" pre-fills the run creation form with the validated YAML

## Context & References

- Bug report: `docs/bugs/UI-ROUTINE-VALIDATION.md`
- Architecture: `docs/bug-removal/architecture.md` — "New Components: Routine validator modal", routing decision (modal not separate page)
- Key decision: modal accessible from `RoutineSelector` or `CreateRunModal` to keep routing simple and integrate naturally with run creation flow
- Backend endpoint: `POST /api/routines/validate` in `src/orchestrator/api/routers/`
