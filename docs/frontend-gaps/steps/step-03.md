# Step 3: Merge Strategy + Clarification Context + Gate Types (Gaps 4, 7, 8)

Enhance the merge dialog with strategy selection, display clarification context in the modal, and add gate type badges throughout the UI. These MEDIUM-severity gaps improve transparency and control across approval, merge, and clarification flows.

## Intent Verification
**Original Intent**: Close Gaps 4, 7, and 8 (MEDIUM severity) from `docs/stories/GAP-ANALYSIS-FRONTEND.md` — merge strategy selection is missing from BackMergeDialog, clarification context is not displayed, and gate type is not indicated in pending actions.
**Functionality to Produce**:
- `MergeStrategyPicker` component for selecting squash/merge/rebase
- BackMergeDialog updated with MergeStrategyPicker, passing strategy to API
- CreateRunModal updated with MergeStrategyPicker in advanced config
- ClarificationModal updated to render `context` field
- `GateTypeBadge` component with color-coded gate type badges
- PendingActionsBadge updated to show gate type
**Final Verification Criteria**:
- `npx tsc --noEmit` passes
- `MergeStrategyPicker.tsx` and `GateTypeBadge.tsx` exist at expected paths
- BackMergeDialog shows strategy picker with three options
- ClarificationModal displays context text when present
- GateTypeBadge renders with correct colors for each gate type

---

## Task 1: Create MergeStrategyPicker Component

**Description**: Build a shared `<select>` component for merge strategy selection (squash/merge/rebase), reused across BackMergeDialog and CreateRunModal.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/MergeStrategyPicker.tsx`
- [ ] Implement a controlled component with props:
  - `value: string` (current strategy)
  - `onChange: (strategy: string) => void`
- [ ] Render a native `<select>` with TailwindCSS styling, options:
  - `merge` (default) — "Merge commit"
  - `squash` — "Squash and merge"
  - `rebase` — "Rebase and merge"

**References**
- `docs/frontend-gaps/architecture.md` — MergeStrategyPicker row
- `docs/frontend-gaps/step-03-plan.md` — Task 1
- Technology choice: Native `<select>` with TailwindCSS

**Constraints**
- Must be a shared/reusable component (used by BackMergeDialog and CreateRunModal)

**Functionality (Expected Outcomes)**
- [ ] `MergeStrategyPicker.tsx` exists at `ui/src/components/detail/MergeStrategyPicker.tsx`
- [ ] Component accepts `value` and `onChange` props

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] Component exports a reusable React component

---

## Task 2: Add MergeStrategyPicker to BackMergeDialog and CreateRunModal

**Description**: Wire the strategy picker into BackMergeDialog (passing strategy to the back-merge API) and into CreateRunModal's advanced config section.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/detail/BackMergeDialog.tsx` (created in Step 2)
- [ ] Import `MergeStrategyPicker`
- [ ] Add local state for `strategy` (default: `"merge"`)
- [ ] Render `MergeStrategyPicker` in the dialog, above the confirm button
- [ ] Pass `{ strategy }` to the `useBackMerge.mutate()` call
- [ ] Open `ui/src/components/run/CreateRunModal.tsx`
- [ ] Import `MergeStrategyPicker`
- [ ] Add `MergeStrategyPicker` to the advanced config section of CreateRunModal
- [ ] Include the selected strategy in the run creation payload

**Dependencies**
- [ ] Task 1 must be complete (MergeStrategyPicker exists)
- [ ] Step 2 must be complete (BackMergeDialog exists)

**References**
- `docs/frontend-gaps/step-03-plan.md` — Tasks 2, 3
- `docs/frontend-gaps/architecture.md` — MergeStrategyPicker is shared between dialogs

**Constraints**
- Only modify BackMergeDialog and CreateRunModal. Do not change other components.

**Functionality (Expected Outcomes)**
- [ ] BackMergeDialog shows strategy picker with three options
- [ ] Selected strategy is sent in the back-merge API call
- [ ] CreateRunModal advanced config includes strategy picker

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] BackMergeDialog renders MergeStrategyPicker
- [ ] CreateRunModal renders MergeStrategyPicker in advanced config

---

## Task 3: Add Clarification Context to ClarificationModal

**Description**: Update ClarificationModal to render the `context` field from `ClarificationQuestion` above the options list when present.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/detail/ClarificationModal.tsx`
- [ ] Locate where the clarification question is rendered
- [ ] Add a conditional section above the options list that renders `context` when it is non-null and non-empty:
```tsx
{question.context && (
  <div className="mb-4 rounded bg-gray-50 p-3 text-sm text-gray-700">
    {question.context}
  </div>
)}
```
- [ ] Adjust styling to match existing modal patterns

**References**
- `docs/frontend-gaps/step-03-plan.md` — Task 4
- `docs/frontend-gaps/architecture.md` — ClarificationModal modification

**Constraints**
- Only add context rendering. Do not modify existing clarification flow logic.
- Gracefully omit context section when value is null/empty (no error).

**Functionality (Expected Outcomes)**
- [ ] ClarificationModal displays context text when present
- [ ] Context section is absent when field is null or empty

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `ClarificationModal.tsx` references the `context` field

---

## Task 4: Create GateTypeBadge Component

**Description**: Build a color-coded badge component that visually indicates gate type (`human_approval`, `grade_threshold`, `checklist`).

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/GateTypeBadge.tsx`
- [ ] Implement component with props: `gateType: string`
- [ ] Map gate types to colors:
  - `human_approval` → blue badge
  - `grade_threshold` → purple badge
  - `checklist` → green badge
  - Unknown → gray "gate" badge (fallback)
- [ ] Use TailwindCSS classes for badge styling, consistent with existing badge components (e.g., StatusBadge)

**References**
- `docs/frontend-gaps/architecture.md` — GateTypeBadge row
- `docs/frontend-gaps/step-03-plan.md` — Task 5

**Functionality (Expected Outcomes)**
- [ ] `GateTypeBadge.tsx` exists at `ui/src/components/GateTypeBadge.tsx`
- [ ] Renders correct color for each known gate type
- [ ] Falls back to generic badge for unknown types

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] Component exports a React component

---

## Task 5: Add Gate Type to PendingActionsBadge

**Description**: Update PendingActionsBadge to show gate type information using GateTypeBadge.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/dashboard/PendingActionsBadge.tsx`
- [ ] Import `GateTypeBadge` from `components/GateTypeBadge`
- [ ] For each pending action that has a `gate_type` field, render `GateTypeBadge` in the tooltip or label area
- [ ] Ensure the badge is visible but does not break existing layout

**Dependencies**
- [ ] Task 4 must be complete (GateTypeBadge exists)

**References**
- `docs/frontend-gaps/step-03-plan.md` — Task 6
- `docs/frontend-gaps/architecture.md` — PendingActionsBadge modification

**Constraints**
- Only add gate type display. Do not modify pending action filtering or other badge behavior.

**Functionality (Expected Outcomes)**
- [ ] PendingActionsBadge shows gate type information

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] PendingActionsBadge renders GateTypeBadge for actions with gate type
