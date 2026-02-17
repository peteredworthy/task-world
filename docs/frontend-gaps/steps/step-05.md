# Step 5: History Page + Live Guidance (Gaps 10, 11)

Replace the History page stub with a functional completed/failed runs list, and add live guidance polling to the AgentGuidancePanel. The History page closes a MEDIUM gap by enabling users to review past runs. Live guidance closes a MEDIUM gap by showing the current agent prompt, phase, and expected actions in real-time.

## Intent Verification
**Original Intent**: Close Gaps 10 and 11 (MEDIUM severity) from `docs/stories/GAP-ANALYSIS-FRONTEND.md` — History page is a stub ("Coming soon") and AgentGuidancePanel does not poll the live guidance endpoint.
**Functionality to Produce**:
- `GuidanceResponse` type in `types/guidance.ts`
- `useGuidance(runId)` query hook with 10s polling interval
- `pages/History.tsx` rewritten with runs list, filters, search, and pagination
- `AgentGuidancePanel` updated to show live prompt, phase, and expected actions
**Final Verification Criteria**:
- `npx tsc --noEmit` passes
- History page contains no "Coming soon" stub text
- `useGuidance` is exported from `hooks/useApi.ts`
- History page loads and displays completed/failed runs with filters
- AgentGuidancePanel shows current prompt and phase for active runs

---

## Task 1: Create GuidanceResponse Type

**Description**: Define the `GuidanceResponse` interface for the live guidance API response.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/types/guidance.ts`
- [ ] Add the following type definition:
```typescript
export interface GuidanceResponse {
  run_id: string;
  task_id: string | null;
  prompt: string | null;
  phase: string | null;
  mcp_url: string;
  expected_actions: string[];
}
```

**References**
- `docs/frontend-gaps/architecture.md` — Type Additions (types/guidance.ts)
- `docs/frontend-gaps/step-05-plan.md` — Task 1

**Functionality (Expected Outcomes)**
- [ ] `GuidanceResponse` is importable from `types/guidance.ts`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `types/guidance.ts` exists and exports `GuidanceResponse`

---

## Task 2: Add useGuidance Hook

**Description**: Create a TanStack Query hook for fetching live guidance data with conditional 10s polling.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/hooks/useApi.ts`
- [ ] Import `GuidanceResponse` from `types/guidance.ts`
- [ ] Add `useGuidance` hook:
```typescript
export function useGuidance(runId: string, enabled: boolean = true) {
  return useQuery({
    queryKey: ['guidance', runId],
    queryFn: () => apiClient.get<GuidanceResponse>(`/api/runs/${runId}/guidance`),
    refetchInterval: enabled ? 10000 : false,
    enabled,
  });
}
```
- [ ] The `enabled` parameter controls whether polling is active (only when guidance panel is open)

**Dependencies**
- [ ] Task 1 must be complete (GuidanceResponse type exists)

**References**
- `docs/frontend-gaps/architecture.md` — New Hooks section (useGuidance)
- `docs/frontend-gaps/step-05-plan.md` — Task 2

**Functionality (Expected Outcomes)**
- [ ] `useGuidance` is exported from `hooks/useApi.ts`
- [ ] Polls every 10 seconds when enabled

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] Hook is exported from `hooks/useApi.ts`

---

## Task 3: Rewrite History Page

**Description**: Replace the History page stub with a functional page showing completed/failed runs with filters, search, and cursor-based pagination.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/pages/History.tsx`
- [ ] Remove the "Coming soon" stub content entirely
- [ ] Implement a functional history page with:
  - Runs list using existing `RunCard` components
  - Outcome filter: dropdown or button group for "All", "Completed", "Failed"
  - Date range filter: date pickers for start/end date
  - Search input: text input filtering by run name or routine name
  - Cursor-based pagination: "Load more" button or infinite scroll (match `useActivity` pagination pattern)
- [ ] Create a query hook or use existing `useRuns` with appropriate query params for status filter, date range, search, and cursor
- [ ] Handle empty state: "No runs found" with filter reset suggestion
- [ ] Handle pagination errors: inline error with retry button
- [ ] Use TailwindCSS, maintain consistency with existing page layouts (Dashboard, etc.)

**References**
- `docs/frontend-gaps/step-05-plan.md` — Task 3
- `docs/frontend-gaps/architecture.md` — History uses cursor-based pagination matching `useActivity` pattern
- Design decision Q3: Dedicated History page, reuse RunCard
- Backend endpoint: `GET /api/runs` with status/date/search/cursor query params

**Constraints**
- Reuse existing `RunCard` component for displaying runs
- Follow cursor-based pagination pattern from `useActivity`
- No "Coming soon" text may remain

**Functionality (Expected Outcomes)**
- [ ] History page loads and displays completed/failed runs
- [ ] Date range and outcome filters work correctly
- [ ] Search filters runs by name
- [ ] Pagination loads additional runs
- [ ] Empty state shows "No runs found" message

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `pages/History.tsx` contains no "Coming soon" text
- [ ] Page renders a list of runs with filtering controls

---

## Task 4: Update AgentGuidancePanel with Live Guidance

**Description**: Wire the AgentGuidancePanel to poll the live guidance endpoint and render prompt, phase, and expected actions.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/guidance/AgentGuidancePanel.tsx`
- [ ] Import `useGuidance` from `hooks/useApi`
- [ ] Call `useGuidance(runId, isPanelOpen)` where `isPanelOpen` controls polling
- [ ] Render guidance data:
  - Current prompt text (or "Waiting for agent..." when null)
  - Phase badge (or "Waiting for agent..." when null)
  - Expected actions as a bulleted list
- [ ] Handle 404 response: show "No active guidance" placeholder
- [ ] Handle null fields: show "Waiting for agent..." placeholder

**Dependencies**
- [ ] Task 2 must be complete (useGuidance hook exists)

**References**
- `docs/frontend-gaps/step-05-plan.md` — Task 4
- `docs/frontend-gaps/architecture.md` — AgentGuidancePanel modification

**Constraints**
- Only add guidance data rendering. Do not modify existing panel structure beyond what's needed.
- Polling must only occur when the panel is open.

**Functionality (Expected Outcomes)**
- [ ] AgentGuidancePanel shows current prompt and phase for active runs
- [ ] Panel updates every 10 seconds while open
- [ ] Placeholder shown when no active guidance exists

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] AgentGuidancePanel imports and uses `useGuidance`
- [ ] Panel renders prompt, phase, and expected actions
