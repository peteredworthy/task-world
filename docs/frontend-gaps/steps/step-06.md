# Step 6: Routine Detail + Agents Flow + Revision Visualization (Gaps 12, 13, 14)

Enrich the RoutineLibrary detail view with gate types and priorities, add a "create run with this agent" flow from the Agents page, and add visual connectors between attempts in AttemptHistory. These LOW-severity gaps reduce friction in the routine inspection, agent selection, and revision loop workflows.

## Intent Verification
**Original Intent**: Close Gaps 12, 13, and 14 (LOW severity) from `docs/stories/GAP-ANALYSIS-FRONTEND.md` — routine inspection lacks depth, no agent-to-run creation flow, and revision loop has no visual representation.
**Functionality to Produce**:
- RoutineLibrary detail view shows gate types, auto-verify commands, and requirement priorities
- Agents page has "Create run with this agent" button per agent row
- CreateRunContext accepts pre-filled agent type from navigation
- AttemptHistory shows visual connectors between attempts (build→verify→revise cycle)
**Final Verification Criteria**:
- `npx tsc --noEmit` passes
- RoutineLibrary renders gate type, auto-verify, and priority information
- Agents page contains a "Create run" action button
- AttemptHistory contains visual connector styling

---

## Task 1: Enrich RoutineLibrary Detail View

**Description**: Update RoutineLibrary to show gate types (using GateTypeBadge), auto-verify commands, and requirement priorities in the routine detail view.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/pages/RoutineLibrary.tsx`
- [ ] Import `GateTypeBadge` from `components/GateTypeBadge` (created in Step 3; if Step 3 is not yet complete, use plain text labels as fallback)
- [ ] In the routine detail view section, add:
  - Gate types section: render `GateTypeBadge` for each gate type in the routine data
  - Auto-verify commands section: render each command as a `<code>` snippet
  - Requirement priorities section: render priorities with visual severity indicators (e.g., color-coded text or badges for HIGH/MEDIUM/LOW)
- [ ] Conditionally render each section only when data is present (omit section if no gate types, etc.)

**Dependencies**
- [ ] `GateTypeBadge` from Step 3 (soft dependency — use plain text fallback if not available)

**References**
- `docs/frontend-gaps/step-06-plan.md` — Task 1
- `docs/frontend-gaps/architecture.md` — RoutineLibrary modifications

**Constraints**
- Only add detail rendering. Do not modify routine list or navigation behavior.
- Gracefully handle missing data (no gate types, no auto-verify commands, etc.)

**Functionality (Expected Outcomes)**
- [ ] Routine detail shows gate types, auto-verify commands, and priorities
- [ ] Missing sections are gracefully omitted

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `RoutineLibrary.tsx` renders gate type, auto-verify, and priority information

---

## Task 2: Add "Create Run" Flow from Agents Page

**Description**: Add a "Create run with this agent" button to each agent row on the Agents page, navigating to Dashboard with the agent pre-filled in CreateRunModal.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/pages/Agents.tsx`
- [ ] For each agent row, add a "Create run" button
- [ ] On click, navigate to the Dashboard page with the agent type in navigation state:
```typescript
navigate('/', { state: { prefillAgentType: agent.agent_type } });
```
- [ ] Open `ui/src/context/CreateRunContext.tsx`
- [ ] Update the context to accept an optional `prefillAgentType` in its state
- [ ] When the Dashboard mounts with navigation state containing `prefillAgentType`, open CreateRunModal with the agent type pre-filled
- [ ] Handle graceful degradation: if navigation state is lost (direct URL access), modal opens without pre-fill

**References**
- `docs/frontend-gaps/step-06-plan.md` — Tasks 2, 3
- `docs/frontend-gaps/architecture.md` — Agents page modification, CreateRunContext modification

**Constraints**
- Only add the "Create run" button and navigation flow. Do not modify agent list rendering beyond the new button.
- Agent type not found in modal options → show warning, allow manual selection.

**Functionality (Expected Outcomes)**
- [ ] Agents page has "Create run" button per agent row
- [ ] Clicking button navigates to Dashboard and opens CreateRunModal with agent pre-filled
- [ ] Navigation state loss is handled gracefully

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `Agents.tsx` contains a "Create run" action button
- [ ] `CreateRunContext.tsx` accepts `prefillAgentType`

---

## Task 3: Add Visual Connectors to AttemptHistory

**Description**: Add CSS-based visual connectors (arrows/flow lines) between attempt entries in AttemptHistory to show the build→verify→revise cycle.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/components/detail/AttemptHistory.tsx`
- [ ] Add visual connectors between attempt entries using CSS:
  - Vertical line connecting sequential attempts
  - Status-based coloring (green for pass, red for fail, gray for in-progress)
  - Arrow or flow indicator showing build→verify→revise progression
- [ ] Use CSS pseudo-elements or border-based approach for connectors (no SVG library needed)
- [ ] Add TailwindCSS classes for connector styling:
```css
/* Example approach using relative positioning and pseudo-elements */
.attempt-connector {
  position: relative;
}
.attempt-connector::before {
  content: '';
  position: absolute;
  left: 1rem;
  top: 0;
  bottom: 0;
  width: 2px;
  background: currentColor;
}
```

**References**
- `docs/frontend-gaps/step-06-plan.md` — Task 4
- Design decision Q7: Flat attempt list with visual connectors (lowest effort)

**Constraints**
- CSS-only approach — no additional dependencies
- Do not change the data structure or ordering of attempts

**Functionality (Expected Outcomes)**
- [ ] AttemptHistory shows visual flow indicators between attempts
- [ ] Connectors indicate build→verify→revise cycle progression

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` passes
- [ ] `AttemptHistory.tsx` contains visual connector styling
