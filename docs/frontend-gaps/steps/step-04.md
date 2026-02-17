# Step 4: Attempt Cost + Auto-Verify Output + Step Progress Text (Gaps 5, 6, 9)

Surface per-attempt cost data, auto-verify command output, and textual step progress on the dashboard. These MEDIUM-severity improvements give users better visibility into execution costs, verification results, and run progress at a glance.

## Intent Verification
**Original Intent**: Close Gaps 5, 6, and 9 (MEDIUM severity) from `docs/stories/GAP-ANALYSIS-FRONTEND.md` — per-attempt cost breakdown is missing, auto-verify output is not surfaced, and step progress text is not shown on dashboard cards.
**Functionality to Produce**:
- `AttemptMetrics` component showing token counts and estimated cost per attempt
- AttemptHistory updated to render AttemptMetrics inline
- `AutoVerifyOutput` component as a collapsible code block for stdout/stderr
- ActivityFeed updated to embed AutoVerifyOutput in auto-verify events
- RunCard updated to show "Step X of Y" text alongside StepTimeline
**Final Verification Criteria**:
- `npx tsc --noEmit` passes
- `AttemptMetrics.tsx` and `AutoVerifyOutput.tsx` exist at expected paths
- AttemptHistory shows token counts and cost per attempt
- Auto-verify output block is collapsed by default and expands on click
- Dashboard RunCard shows "Step X of Y" text

---

## Task 1: Create AttemptMetrics Component

**Description**: Build a component that displays per-attempt token read/write counts and estimated cost.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/AttemptMetrics.tsx`
- [ ] Implement component with props matching attempt data: `tokensRead: number | null`, `tokensWrite: number | null`, `durationMs: number | null`
- [ ] Render:
  - Token counts: "Read: X tokens, Write: Y tokens"
  - Estimated cost calculation (tokens × rate — use a reasonable default rate constant)
  - Duration in human-readable format (e.g., "2.3s")
  - When token counts are zero or null, show "No usage data" placeholder
- [ ] Use TailwindCSS for compact inline styling

**References**
- `docs/frontend-gaps/architecture.md` — AttemptMetrics row
- `docs/frontend-gaps/step-04-plan.md` — Task 1

**Functionality (Expected Outcomes)**
- [ ] `AttemptMetrics.tsx` exists at `ui/src/components/detail/AttemptMetrics.tsx`
- [ ] Shows token counts and estimated cost
- [ ] Shows placeholder when data is missing

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] Component exports a React component

---

## Task 2: Wire AttemptMetrics into AttemptHistory

**Description**: Update AttemptHistory to render AttemptMetrics inline for each attempt in the list.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/detail/AttemptHistory.tsx`
- [ ] Import `AttemptMetrics` from `components/detail/AttemptMetrics`
- [ ] For each attempt in the list, render `AttemptMetrics` with the attempt's `tokens_read`, `tokens_write`, and `duration_ms` fields
- [ ] Position metrics below or alongside existing attempt information

**Dependencies**
- [ ] Task 1 must be complete (AttemptMetrics exists)

**References**
- `docs/frontend-gaps/step-04-plan.md` — Task 2

**Constraints**
- Only add AttemptMetrics rendering. Do not modify existing attempt display logic.

**Functionality (Expected Outcomes)**
- [ ] AttemptHistory shows token counts and cost per attempt
- [ ] Attempts with no usage data show appropriate placeholder

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] AttemptHistory renders AttemptMetrics for each attempt

---

## Task 3: Create AutoVerifyOutput Component

**Description**: Build a collapsible code block component for displaying auto-verify stdout/stderr output.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/AutoVerifyOutput.tsx`
- [ ] Implement component with props: `stdout: string | null`, `stderr: string | null`
- [ ] Render:
  - Collapsible wrapper (collapsed by default) with a toggle button ("Show output" / "Hide output")
  - `<pre>` block inside the collapsible area with `max-height` and `overflow-y: scroll`
  - stdout section (if present)
  - stderr section (if present, styled with red/error color)
  - "No output captured" message when both are empty/null
- [ ] Use TailwindCSS, match existing log viewer patterns in the codebase

**References**
- `docs/frontend-gaps/architecture.md` — AutoVerifyOutput row
- `docs/frontend-gaps/step-04-plan.md` — Task 3
- Design decision Q6: Collapsible code block in ActivityFeed (collapsed by default)
- Performance note: max-height + overflow scroll required for large output

**Functionality (Expected Outcomes)**
- [ ] `AutoVerifyOutput.tsx` exists at `ui/src/components/detail/AutoVerifyOutput.tsx`
- [ ] Block is collapsed by default, expands on click
- [ ] Large output scrolls within the container

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] Component exports a React component

---

## Task 4: Embed AutoVerifyOutput in ActivityFeed

**Description**: Update ActivityFeed to embed AutoVerifyOutput within auto-verify event entries.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/detail/ActivityFeed.tsx`
- [ ] Import `AutoVerifyOutput` from `components/detail/AutoVerifyOutput`
- [ ] Locate the rendering logic for activity feed events
- [ ] For events that are auto-verify events (identify by event type in the payload), render `AutoVerifyOutput` with `stdout` and `stderr` from the event payload
- [ ] Position the output block below the existing event summary text

**Dependencies**
- [ ] Task 3 must be complete (AutoVerifyOutput exists)

**References**
- `docs/frontend-gaps/step-04-plan.md` — Task 4
- `docs/frontend-gaps/architecture.md` — ActivityFeed modification

**Constraints**
- Only add AutoVerifyOutput for auto-verify events. Do not modify other event types.

**Functionality (Expected Outcomes)**
- [ ] Auto-verify events in ActivityFeed show collapsible output block
- [ ] Output block does not appear for non-verify events

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] ActivityFeed renders AutoVerifyOutput for auto-verify events

---

## Task 5: Add Step Progress Text to RunCard

**Description**: Update the dashboard RunCard to show "Step X of Y" text alongside the existing StepTimeline component.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/dashboard/RunCard.tsx`
- [ ] Locate where StepTimeline is rendered
- [ ] Add a text element showing "Step {current_step} of {total_steps}" using `current_step` and `total_steps` from the run summary data
- [ ] Only render the text when step count data is available (graceful degradation)
- [ ] Style with TailwindCSS — small text, muted color, positioned near StepTimeline

**References**
- `docs/frontend-gaps/step-04-plan.md` — Task 5
- `docs/frontend-gaps/architecture.md` — RunCard modification

**Constraints**
- Only add step progress text. Do not modify StepTimeline or other RunCard content.
- Omit text when step count data is missing.

**Functionality (Expected Outcomes)**
- [ ] Dashboard RunCard shows "Step X of Y" text for runs with step data
- [ ] Text is absent when step count data is unavailable

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `RunCard.tsx` contains step progress text rendering logic
