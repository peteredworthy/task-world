# Feature: Routine YAML Validation UI

## Summary

The backend exposes a `POST /api/routines/validate` endpoint that parses and validates a
routine YAML string, returning structured errors. The frontend has no editor or validator;
routine authors must validate manually via `curl` or the CLI.

## Current State

**Backend — complete:**
- `POST /api/routines/validate` — accepts `{ yaml: string }`, returns
  `{ valid: bool, errors: ValidationError[] }` with line numbers and messages
- Tests: `tests/integration/test_api_routines.py`

**Frontend — missing everything:**
- No `validateRoutine(yaml)` in `ui/src/api/client.ts`
- No `useValidateRoutine` mutation hook
- No editor or validation UI

## Work Required

1. **`ui/src/api/client.ts`** — add:
   ```ts
   validateRoutine(yaml: string): Promise<{ valid: boolean; errors: ValidationError[] }>
   ```

2. **`ui/src/hooks/useApi.ts`** — add `useValidateRoutine` mutation.

3. **UI — routine editor/validator:** A simple page or modal with:
   - `<textarea>` (or lightweight code editor) for YAML input
   - "Validate" button → calls `useValidateRoutine` → displays errors inline with line
     numbers
   - On valid result, "Create run from this routine" shortcut (passes validated YAML as
     `routine_embedded` to `useCreateRun`)

4. **Routing** — add a route (e.g., `/routines/new`) or surface as a modal in
   `RoutineSelector`/`CreateRunModal`.

## Severity

**Low** — routine authoring currently happens outside the UI; this is a convenience feature
for users writing routines directly in the app.

## Related

- `docs/ui-gaps2/README.md §8`
- `src/orchestrator/api/routers/routines.py` — validate endpoint
- `ui/src/components/CreateRunModal.tsx` — accepts `routine_embedded`; a validated routine
  could flow directly into run creation
