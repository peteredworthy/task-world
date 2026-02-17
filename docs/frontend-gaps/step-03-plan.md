# Step 3 Plan: Merge Strategy + Clarification Context + Gate Types (Gaps 4, 7, 8)

## Purpose

Enhance the merge dialog with strategy selection, display clarification context in the modal, and add gate type badges throughout the UI. These MEDIUM-severity gaps improve transparency and control across approval, merge, and clarification flows.

## Prerequisites

- **Step 2** (Branch status + back-merge) — BackMergeDialog must exist before adding MergeStrategyPicker to it

## Functional Contract

### Inputs

- Merge strategy selection: `squash | merge | rebase` — user selects in MergeStrategyPicker, passed to back-merge API
- CreateRunModal advanced config: strategy picker added for default merge strategy on run creation
- `ClarificationQuestion.context` field (string | null) — from the existing clarification API response
- `PendingAction.gate_type` field (string) — values: `human_approval`, `grade_threshold`, `checklist`
- Step progress data with gate type metadata

### Outputs

- `MergeStrategyPicker` component at `components/detail/MergeStrategyPicker.tsx` — shared `<select>` for strategy choice
- `BackMergeDialog` updated to include MergeStrategyPicker, passing strategy to `useBackMerge` call
- `CreateRunModal` updated with MergeStrategyPicker in advanced config section
- `ClarificationModal` updated to render `context` field above options when present
- `GateTypeBadge` component at `components/GateTypeBadge.tsx` — colored badge per gate type
- `PendingActionsBadge` updated to show gate type in tooltip/label

### Errors

- Back-merge with invalid strategy → API returns 400 → show "Invalid merge strategy" error
- Clarification context is null/empty → gracefully omit context section (no error)
- Unknown gate type value → render generic "gate" badge with neutral color

## Tasks

1. Create `components/detail/MergeStrategyPicker.tsx` as a controlled `<select>` component with squash/merge/rebase options
2. Update `components/detail/BackMergeDialog.tsx` to include MergeStrategyPicker and pass selected strategy to `useBackMerge`
3. Update `components/run/CreateRunModal.tsx` to include MergeStrategyPicker in advanced config
4. Update `components/detail/ClarificationModal.tsx` to render `context` field from ClarificationQuestion above the options list
5. Create `components/GateTypeBadge.tsx` with color-coded badges for each gate type
6. Update `components/dashboard/PendingActionsBadge.tsx` to show gate type via GateTypeBadge

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `MergeStrategyPicker.tsx` exists at `ui/src/components/detail/MergeStrategyPicker.tsx`
- [ ] `GateTypeBadge.tsx` exists at `ui/src/components/GateTypeBadge.tsx`
- [ ] `ClarificationModal.tsx` references the `context` field

### Manual Verify

- [ ] BackMergeDialog shows strategy picker with three options
- [ ] Selected strategy is sent in the back-merge API call
- [ ] CreateRunModal advanced config includes strategy picker
- [ ] ClarificationModal displays context text when present, omits section when absent
- [ ] GateTypeBadge renders with correct colors for each gate type
- [ ] PendingActionsBadge shows gate type information

## Context & References

- Gap analysis: Gaps 4 (merge strategy), 7 (clarification context), 8 (gate type indication) — all MEDIUM
- Design decision Q1: Separate approval modal (gate badges complement this)
- Depends on Step 2: `BackMergeDialog.tsx` must exist
- Architecture: `MergeStrategyPicker` is shared between BackMergeDialog and CreateRunModal
