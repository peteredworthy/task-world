# Step 5 Plan: History Page + Live Guidance (Gaps 10, 11)

## Purpose

Replace the History page stub with a functional completed/failed runs list, and add live guidance polling to the AgentGuidancePanel. The History page closes a MEDIUM gap by enabling users to review past runs. Live guidance closes a MEDIUM gap by showing the current agent prompt, phase, and expected actions in real-time.

## Prerequisites

- None (independent of Steps 1–4)

## Functional Contract

### Inputs

- History page: `GET /api/runs` with query params for status filter (`completed`, `failed`), date range, and cursor-based pagination
- History page: search query string for filtering by run name or routine name
- Guidance panel: `GET /api/runs/{id}/guidance` — returns `GuidanceResponse` with `prompt`, `phase`, `mcp_url`, `expected_actions`
- Guidance panel: `run_id` from RunDetail route params; polling interval of 10 seconds when panel is open

### Outputs

- `pages/History.tsx` rewritten with: runs list using RunCard, date range filter, outcome filter (completed/failed/all), search input, cursor-based pagination
- `useGuidance(runId)` query hook in `hooks/useApi.ts` with 10s polling interval (enabled only when panel is open)
- `GuidanceResponse` type in `types/guidance.ts`
- `AgentGuidancePanel` updated to use `useGuidance` hook, rendering current prompt, phase, and expected actions list

### Errors

- History API returns empty list → show "No runs found" empty state with filter reset suggestion
- History API pagination fails → show error inline with retry button
- Guidance API returns 404 → run has no active guidance → show "No active guidance" placeholder
- Guidance API returns null fields → show "Waiting for agent..." placeholder for null prompt/phase

## Tasks

1. Create `types/guidance.ts` with `GuidanceResponse` interface
2. Add `useGuidance(runId)` query hook to `hooks/useApi.ts` with `refetchInterval: 10000` (conditional on panel visibility)
3. Rewrite `pages/History.tsx`: replace stub with functional page using existing `RunCard` components, date range filter, outcome filter, search, and cursor-based pagination
4. Update `components/guidance/AgentGuidancePanel.tsx` to call `useGuidance`, render prompt text, phase badge, and expected actions as a bulleted list

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `pages/History.tsx` contains no "Coming soon" stub text
- [ ] `useGuidance` is exported from `hooks/useApi.ts`
- [ ] `GuidanceResponse` type is defined in `types/guidance.ts`

### Manual Verify

- [ ] History page loads and displays completed/failed runs
- [ ] Date range filter and outcome filter work correctly
- [ ] Search filters runs by name
- [ ] Pagination loads additional runs on scroll/click
- [ ] AgentGuidancePanel shows current prompt and phase for an active run
- [ ] Guidance panel updates every 10 seconds while open
- [ ] Guidance panel shows placeholder when no active guidance exists

## Context & References

- Gap analysis: Gaps 10 (history page), 11 (live guidance) — both MEDIUM
- Design decision Q3: Dedicated History page, reuse RunCard
- Architecture: History uses cursor-based pagination matching `useActivity` pattern
- Backend endpoints: `GET /api/runs` (with filters), `GET /api/runs/{id}/guidance`
