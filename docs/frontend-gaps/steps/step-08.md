# Step 8: Validation + Env Files + Transitions + Dashboard WebSocket (Gaps 18, 19, 20, 21)

Add routine validation, env file management, non-linear step transition visualization, and real-time dashboard updates. This final step closes the remaining LOW-severity gaps and completes the frontend gap closure work.

## Intent Verification
**Original Intent**: Close Gaps 18, 19, 20, and 21 (LOW severity) from `docs/stories/GAP-ANALYSIS-FRONTEND.md` — routine validation UI is missing, env file management is not exposed, non-linear step transitions are not visualized, and the dashboard lacks real-time updates.
**Functionality to Produce**:
- `ValidateRoutineRequest`/`ValidateRoutineResponse` types in `types/routines.ts`
- Env file types in `types/envfiles.ts`
- Validation, env file hooks in `hooks/useApi.ts`
- RoutineLibrary has a "Validate" button with inline results
- `EnvFileTemplates` component for config/settings area
- `EnvFileOverrides` component in CreateRunModal
- StepTimeline visualizes non-linear transitions (backward jumps)
- Dashboard uses WebSocket/SSE for real-time updates with polling fallback
**Final Verification Criteria**:
- `npx tsc --noEmit` passes
- `EnvFileTemplates.tsx` and `EnvFileOverrides.tsx` exist at expected paths
- `useValidateRoutine` is exported from `hooks/useApi.ts`
- `types/routines.ts` and `types/envfiles.ts` exist with type definitions
- Dashboard receives real-time updates or gracefully falls back to polling

---

## Task 1: Create Routine Validation Types

**Description**: Define types for the routine validation API request and response.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/types/routines.ts`
- [ ] Add type definitions:
```typescript
export interface ValidateRoutineRequest {
  yaml_content: string;
}

export interface ValidateRoutineResponse {
  valid: boolean;
  errors: string[];
  builder_feedback: string[];
}
```

**References**
- `docs/frontend-gaps/architecture.md` — Type Additions (types/routines.ts)
- `docs/frontend-gaps/step-08-plan.md` — Task 1

**Functionality (Expected Outcomes)**
- [ ] Types are importable from `types/routines.ts`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `types/routines.ts` exists with type definitions

---

## Task 2: Create Env File Types

**Description**: Define types for env file management API interactions.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/types/envfiles.ts`
- [ ] Add type definitions:
```typescript
export interface EnvFileTemplate {
  id: string;
  name: string;
  description?: string;
  keys: string[]; // key names only, no values (security)
}

export interface EnvFileSnapshot {
  id: string;
  template_id: string;
  created_at: string;
  description?: string;
}

export interface RevertEnvFileRequest {
  snapshot_id: string;
}

export interface CopyBackRequest {
  source_run_id: string;
}
```

**References**
- `docs/frontend-gaps/architecture.md` — Type Additions (types/envfiles.ts)
- `docs/frontend-gaps/step-08-plan.md` — Task 2
- Security: env file UI shows metadata only — values stay server-side

**Functionality (Expected Outcomes)**
- [ ] Types are importable from `types/envfiles.ts`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `types/envfiles.ts` exists with type definitions

---

## Task 3: Add Validation and Env File Hooks

**Description**: Add all API hooks for routine validation and env file management to `hooks/useApi.ts`.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/hooks/useApi.ts`
- [ ] Import types from `types/routines.ts` and `types/envfiles.ts`
- [ ] Add `useValidateRoutine` mutation hook:
```typescript
export function useValidateRoutine() {
  return useMutation({
    mutationFn: (data: ValidateRoutineRequest) =>
      apiClient.post<ValidateRoutineResponse>('/api/routines/validate', data),
  });
}
```
- [ ] Add env file hooks:
```typescript
export function useEnvFiles(runId: string) {
  return useQuery({
    queryKey: ['envFiles', runId],
    queryFn: () => apiClient.get<EnvFileTemplate[]>(`/api/runs/${runId}/env-files`),
  });
}

export function useEnvFileSnapshots(runId: string) {
  return useQuery({
    queryKey: ['envFileSnapshots', runId],
    queryFn: () => apiClient.get<EnvFileSnapshot[]>(`/api/runs/${runId}/env-files/snapshots`),
  });
}

export function useRevertEnvFile(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: RevertEnvFileRequest) =>
      apiClient.post(`/api/runs/${runId}/env-files/revert`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['envFiles', runId] });
      queryClient.invalidateQueries({ queryKey: ['envFileSnapshots', runId] });
    },
  });
}

export function useCopyBackEnvFile(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CopyBackRequest) =>
      apiClient.post(`/api/runs/${runId}/env-files/copy-back`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['envFiles', runId] });
    },
  });
}
```

**Dependencies**
- [ ] Tasks 1 and 2 must be complete (types exist)

**References**
- `docs/frontend-gaps/architecture.md` — New Hooks section
- `docs/frontend-gaps/step-08-plan.md` — Task 3

**Functionality (Expected Outcomes)**
- [ ] All five hooks are exported from `hooks/useApi.ts`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `useValidateRoutine`, `useEnvFiles`, `useEnvFileSnapshots`, `useRevertEnvFile`, `useCopyBackEnvFile` are exported

---

## Task 4: Add Validate Button to RoutineLibrary

**Description**: Add a "Validate" button to RoutineLibrary that submits YAML to the validation endpoint and shows results inline.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/pages/RoutineLibrary.tsx`
- [ ] Import `useValidateRoutine` from hooks
- [ ] Add a "Validate" button in the routine detail view
- [ ] On click, call `useValidateRoutine.mutate()` with the routine's YAML content
- [ ] Display results inline below the button:
  - Valid: green success indicator "Routine is valid"
  - Invalid: red error list with line numbers (from `errors` array)
  - Builder feedback section (from `builder_feedback` array)
  - API error (500): "Validation service unavailable" message
- [ ] Loading state on button during mutation

**Dependencies**
- [ ] Task 3 must be complete (useValidateRoutine hook exists)

**References**
- `docs/frontend-gaps/step-08-plan.md` — Task 4

**Constraints**
- Only add validation UI. Do not modify other RoutineLibrary functionality.

**Functionality (Expected Outcomes)**
- [ ] Validate button submits YAML and shows results
- [ ] Errors display with line numbers
- [ ] API errors show appropriate message

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] RoutineLibrary contains validate button and results display

---

## Task 5: Create EnvFileTemplates Component

**Description**: Build a component for env file template management in the config/settings area.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/EnvFileTemplates.tsx`
- [ ] Import `useEnvFiles`, `useEnvFileSnapshots`, `useRevertEnvFile`, `useCopyBackEnvFile` from hooks
- [ ] Implement component with props: `runId: string`
- [ ] Render:
  - List of env file templates showing name, description, and key names (no values — security)
  - Snapshots section per template with timestamp and description
  - "Revert" button per snapshot calling `useRevertEnvFile`
  - "Copy back" button calling `useCopyBackEnvFile`
  - "No env file templates" empty state when API returns 404 or empty list
  - Error handling for failed revert (snapshot not found)
- [ ] Use TailwindCSS consistent with settings area styling

**Dependencies**
- [ ] Task 3 must be complete (env file hooks exist)

**References**
- `docs/frontend-gaps/architecture.md` — EnvFileTemplates row
- `docs/frontend-gaps/step-08-plan.md` — Task 5
- Design decision Q5: Env files in config area
- Security: display metadata only, values stay server-side

**Functionality (Expected Outcomes)**
- [ ] `EnvFileTemplates.tsx` exists at `ui/src/components/EnvFileTemplates.tsx`
- [ ] Templates list shows names and keys (not values)
- [ ] Revert and copy-back actions work

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] Component exports a React component

---

## Task 6: Create EnvFileOverrides Component and Wire into CreateRunModal

**Description**: Build a component for per-run env file overrides and add it to CreateRunModal.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/run/EnvFileOverrides.tsx`
- [ ] Implement component with props: `templates: EnvFileTemplate[]`, `overrides: Record<string, string>`, `onChange: (overrides: Record<string, string>) => void`
- [ ] Render:
  - Template selector dropdown (select which template to use)
  - For each key in the selected template, render an input field for the override value
  - Show key names from the template; user provides override values
- [ ] Open `ui/src/components/run/CreateRunModal.tsx`
- [ ] Import `EnvFileOverrides`
- [ ] Add `EnvFileOverrides` section in the modal, after other configuration fields
- [ ] Include overrides in the run creation payload

**Dependencies**
- [ ] Task 5 must be complete (EnvFileTemplates component exists for reference)

**References**
- `docs/frontend-gaps/architecture.md` — EnvFileOverrides row
- `docs/frontend-gaps/step-08-plan.md` — Tasks 6, 7

**Constraints**
- Values entered in overrides are sent to the API — the component itself does not store secrets client-side beyond form state.

**Functionality (Expected Outcomes)**
- [ ] `EnvFileOverrides.tsx` exists at `ui/src/components/run/EnvFileOverrides.tsx`
- [ ] CreateRunModal shows env file override inputs

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] Both files exist and CreateRunModal renders EnvFileOverrides

---

## Task 7: Add Non-Linear Transition Visualization to StepTimeline

**Description**: Update StepTimeline to visualize non-linear step transitions (backward jumps) with arrows or annotations.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/dashboard/StepTimeline.tsx`
- [ ] Identify step transition data: `from_step` and `to_step` fields that may include backward jumps (e.g., step 5 → step 3)
- [ ] Add visual annotations for non-linear transitions:
  - Backward-jump indicators: curved arrow or highlight on the step that was jumped back to
  - Color-coded: distinguish forward transitions from backward jumps (e.g., gray for forward, orange for backward)
- [ ] Use CSS-based approach for annotations (no SVG library)
- [ ] Handle case where all transitions are linear (no annotations needed)

**References**
- `docs/frontend-gaps/step-08-plan.md` — Task 8
- `docs/frontend-gaps/architecture.md` — StepTimeline modification

**Constraints**
- CSS-only visual approach
- Do not change the underlying step data structure

**Functionality (Expected Outcomes)**
- [ ] StepTimeline visualizes backward-jump transitions
- [ ] Linear-only transitions render without annotations

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] StepTimeline contains non-linear transition visualization logic

---

## Task 8: Add Real-Time Dashboard Updates via WebSocket

**Description**: Update the Dashboard page to establish a WebSocket/SSE connection for aggregate run status updates, replacing the existing 10s polling.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/pages/Dashboard.tsx`
- [ ] Check if a dashboard-level WebSocket endpoint exists. If the endpoint `ws://...` or SSE endpoint is available, establish a connection.
- [ ] On receiving `run_status_changed` events, invalidate the relevant TanStack Query cache keys to trigger re-renders:
```typescript
// Inside WebSocket message handler
const queryClient = useQueryClient();
queryClient.invalidateQueries({ queryKey: ['runs'] });
```
- [ ] Implement graceful fallback: if WebSocket connection fails, fall back to existing polling behavior
```typescript
const [wsConnected, setWsConnected] = useState(false);
// Use refetchInterval only when WS is not connected
useQuery({
  queryKey: ['runs'],
  queryFn: fetchRuns,
  refetchInterval: wsConnected ? false : 10000,
});
```
- [ ] If the dashboard WebSocket endpoint doesn't exist yet (per CONFLICTS.md), log a console warning and use polling fallback:
```typescript
console.warn('Dashboard WebSocket endpoint not available, falling back to polling');
```
- [ ] Clean up WebSocket connection on component unmount

**References**
- `docs/frontend-gaps/step-08-plan.md` — Task 9
- `docs/frontend-gaps/architecture.md` — Dashboard WebSocket
- Design decision Q4: Dashboard aggregate WebSocket channel (may need backend work)
- `docs/frontend-gaps/CONFLICTS.md` — Dashboard WebSocket endpoint needs backend verification

**Constraints**
- Must gracefully fall back to polling if WebSocket fails or endpoint doesn't exist
- One WebSocket connection per browser tab
- Clean up on unmount

**Side Effects**
- Dashboard WebSocket endpoint may not exist yet (backend work needed per CONFLICTS.md). The polling fallback ensures the feature degrades gracefully.

**Functionality (Expected Outcomes)**
- [ ] Dashboard receives real-time updates via WebSocket when available
- [ ] Falls back to polling when WebSocket is unavailable
- [ ] Connection is cleaned up on unmount

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] Dashboard contains WebSocket connection logic with polling fallback
- [ ] Console warning appears when WebSocket endpoint is unavailable
