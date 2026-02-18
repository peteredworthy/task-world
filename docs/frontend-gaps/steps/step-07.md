# Step 7: Grade Threshold + Blocked State + Elapsed Time (Gaps 15, 16, 17)

Show grade threshold explanations when verification fails, add a visual blocked-on-human state, and display live elapsed time for active runs. These LOW-severity gaps improve user understanding of verification outcomes, run states, and execution duration.

## Intent Verification
**Original Intent**: Close Gaps 15, 16, and 17 (LOW severity) from `docs/stories/GAP-ANALYSIS-FRONTEND.md` — grade threshold math is not explained, blocked-on-human state is not visualized, and elapsed time is not shown during execution.
**Functionality to Produce**:
- `GradeThresholdExplainer` component showing threshold calculation and critical failures
- ChecklistTable renders explainer when verification fails
- StatusBadge has a `blocked-on-human` variant with distinct styling
- RunDetail passes blocked-on-human state to StatusBadge
- `ElapsedTimer` component showing live HH:MM:SS since run started
- MetricsBar renders ElapsedTimer for active runs
**Final Verification Criteria**:
- `npx tsc --noEmit` passes
- `GradeThresholdExplainer.tsx` and `ElapsedTimer.tsx` exist at expected paths
- StatusBadge handles `blocked-on-human` variant
- ChecklistTable shows threshold explanation when verification fails
- ElapsedTimer ticks for active runs, stops when run completes

---

## Task 1: Create GradeThresholdExplainer Component

**Description**: Build a component that explains why verification failed by showing the threshold calculation: average score vs threshold, plus a list of critical item failures.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/GradeThresholdExplainer.tsx`
- [ ] Implement component with props: `averageScore: number | null`, `threshold: number | null`, `criticalFailures: Array<{ requirement: string; score: number }>`
- [ ] Render:
  - Threshold comparison: "Average score: X.X / Threshold: Y.Y" with visual pass/fail indicator
  - Critical failures list: each failed critical item with its requirement name and score
  - "Grade details unavailable" placeholder when data is incomplete
- [ ] Use TailwindCSS — subtle background (e.g., red-50 for fail), matching existing detail panel styling

**References**
- `docs/frontend-gaps/architecture.md` — GradeThresholdExplainer row
- `docs/frontend-gaps/step-07-plan.md` — Task 1

**Functionality (Expected Outcomes)**
- [ ] `GradeThresholdExplainer.tsx` exists at `ui/src/components/detail/GradeThresholdExplainer.tsx`
- [ ] Shows average score, threshold, and critical failures
- [ ] Placeholder shown when grade data is incomplete

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] Component exports a React component

---

## Task 2: Wire GradeThresholdExplainer into ChecklistTable

**Description**: Update ChecklistTable to render GradeThresholdExplainer below the table when verification outcome is `fail`.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/detail/ChecklistTable.tsx`
- [ ] Import `GradeThresholdExplainer`
- [ ] Conditionally render `GradeThresholdExplainer` below the checklist table when the verification outcome is `fail`
- [ ] Pass the appropriate props: average score, threshold value, and critical failure items from the checklist/grade data

**Dependencies**
- [ ] Task 1 must be complete (GradeThresholdExplainer exists)

**References**
- `docs/frontend-gaps/step-07-plan.md` — Task 2
- `docs/frontend-gaps/architecture.md` — ChecklistTable modification

**Constraints**
- Only add explainer rendering. Do not modify existing checklist display logic.

**Functionality (Expected Outcomes)**
- [ ] ChecklistTable shows threshold explanation when verification fails
- [ ] Explainer is absent when verification passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] ChecklistTable conditionally renders GradeThresholdExplainer

---

## Task 3: Add Blocked-on-Human Variant to StatusBadge

**Description**: Extend StatusBadge with a `blocked-on-human` variant showing distinct styling (amber color, hand/pause icon) and wire it into RunDetail.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/StatusBadge.tsx`
- [ ] Add a new variant/case for `blocked-on-human`:
  - Amber/yellow background color
  - "Blocked on human" label text
  - Distinct icon (hand or pause icon if icons are available, or text-only)
- [ ] Open `ui/src/pages/RunDetail.tsx`
- [ ] Add logic to determine blocked-on-human state: run status is `ACTIVE` AND there are pending human actions (approval, clarification)
- [ ] Pass the `blocked-on-human` variant to StatusBadge when conditions are met

**References**
- `docs/frontend-gaps/step-07-plan.md` — Tasks 3, 4
- `docs/frontend-gaps/architecture.md` — StatusBadge modification, RunDetail modification

**Constraints**
- Only add the new variant. Do not modify existing badge variants or their behavior.
- Standard StatusBadge behavior when no pending human actions.

**Functionality (Expected Outcomes)**
- [ ] StatusBadge displays blocked-on-human variant with amber styling
- [ ] Variant activates when run is ACTIVE with pending human actions
- [ ] Standard badge shown otherwise

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `StatusBadge.tsx` handles a `blocked-on-human` variant
- [ ] RunDetail passes correct variant based on pending actions

---

## Task 4: Create ElapsedTimer Component

**Description**: Build a live timer component showing HH:MM:SS elapsed since run started, ticking every second for active runs.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/ElapsedTimer.tsx`
- [ ] Implement component with props: `startedAt: string | null` (ISO 8601 timestamp), `isActive: boolean`
- [ ] Use `useEffect` + `setInterval(1000)` for live updates:
```typescript
const [elapsed, setElapsed] = useState('00:00:00');

useEffect(() => {
  if (!startedAt || !isActive) return;
  const start = new Date(startedAt).getTime();
  const tick = () => {
    const diff = Date.now() - start;
    const h = String(Math.floor(diff / 3600000)).padStart(2, '0');
    const m = String(Math.floor((diff % 3600000) / 60000)).padStart(2, '0');
    const s = String(Math.floor((diff % 60000) / 1000)).padStart(2, '0');
    setElapsed(`${h}:${m}:${s}`);
  };
  tick();
  const id = setInterval(tick, 1000);
  return () => clearInterval(id);
}, [startedAt, isActive]);
```
- [ ] When `startedAt` is null, render nothing (return null)
- [ ] When `isActive` is false, show final elapsed time (compute once, no interval)

**References**
- `docs/frontend-gaps/architecture.md` — ElapsedTimer row
- `docs/frontend-gaps/step-07-plan.md` — Task 5
- Technology choice: `useEffect` + `setInterval` (simple client-side, negligible CPU)

**Functionality (Expected Outcomes)**
- [ ] `ElapsedTimer.tsx` exists at `ui/src/components/detail/ElapsedTimer.tsx`
- [ ] Timer ticks every second for active runs
- [ ] Timer stops when run completes, showing final time
- [ ] Returns null when `startedAt` is null

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] Component exports a React component

---

## Task 5: Wire ElapsedTimer into MetricsBar

**Description**: Update MetricsBar to render ElapsedTimer for active runs.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/detail/MetricsBar.tsx`
- [ ] Import `ElapsedTimer` from `components/detail/ElapsedTimer`
- [ ] Render `ElapsedTimer` with:
  - `startedAt` from the run detail data
  - `isActive` based on whether run status is `ACTIVE`
- [ ] Position the timer alongside other metrics in the bar

**Dependencies**
- [ ] Task 4 must be complete (ElapsedTimer exists)

**References**
- `docs/frontend-gaps/step-07-plan.md` — Task 6
- `docs/frontend-gaps/architecture.md` — MetricsBar modification

**Constraints**
- Only add ElapsedTimer rendering. Do not modify existing metrics.

**Functionality (Expected Outcomes)**
- [ ] MetricsBar shows elapsed time for active runs
- [ ] Timer is absent for runs without `started_at` data

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] MetricsBar renders ElapsedTimer
