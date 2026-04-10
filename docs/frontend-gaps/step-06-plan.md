# Step 6 Plan: Routine Detail + Agents Flow + Revision Visualization (Gaps 12, 13, 14)

## Purpose

Enrich the RoutineLibrary detail view with gate types and priorities, add a "create run with this agent" flow from the Agents page, and add visual connectors between attempts in AttemptHistory. These LOW-severity gaps reduce friction in the routine inspection, agent selection, and revision loop workflows.

## Prerequisites

- None (independent of Steps 1–5)

## Functional Contract

### Inputs

- Routine detail data: gate types (string[]), auto-verify commands (string[]), requirement priorities (string[]) — from routine API response
- Agent data: `agent_type` (string) — from Agents page list; passed via navigation state to pre-fill CreateRunModal
- `CreateRunContext` — existing context for modal state; extended to accept pre-filled agent type
- Attempt list data: `attempts_summary` array with `outcome`, `attempt_num`, timestamps — from run detail API

### Outputs

- `pages/RoutineLibrary.tsx` updated: routine detail view shows gate types as GateTypeBadge components, auto-verify commands as code snippets, requirement priorities with visual severity indicators
- `pages/Agents.tsx` updated: each agent row gets a "Create run" action button
- `context/CreateRunContext.tsx` updated: accepts optional `prefillAgentType` in context state, navigates to Dashboard and opens CreateRunModal with agent pre-filled
- `components/detail/AttemptHistory.tsx` updated: visual connectors (arrows, status flow indicators) between attempts showing build→verify→revise cycle

### Errors

- Routine has no gate types or auto-verify commands → omit those sections in detail view (no error)
- Agent type not found in CreateRunModal options → show warning "Agent type not available", allow manual selection
- Navigation state lost (direct URL access) → CreateRunModal opens without pre-fill (graceful degradation)

## Tasks

1. Update `pages/RoutineLibrary.tsx` to render gate types (using GateTypeBadge from Step 3), auto-verify commands, and requirement priorities in the routine detail view
2. Update `pages/Agents.tsx` to add "Create run with this agent" button per agent row
3. Update `context/CreateRunContext.tsx` to accept `prefillAgentType` and apply it when opening CreateRunModal
4. Update `components/detail/AttemptHistory.tsx` to add CSS-based visual connectors (arrows/flow lines) between attempt entries showing the build→verify→revise cycle

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `RoutineLibrary.tsx` renders gate type, auto-verify, and priority information
- [ ] `Agents.tsx` contains a "Create run" action button
- [ ] `AttemptHistory.tsx` contains visual connector styling

### Manual Verify

- [ ] Routine detail view shows gate types, auto-verify commands, and priorities
- [ ] Clicking "Create run" on Agents page opens CreateRunModal with agent pre-filled
- [ ] AttemptHistory shows visual flow indicators between attempts
- [ ] Visual connectors correctly indicate build→verify→revise cycle progression

## Context & References

- Gap analysis: Gaps 12 (routine inspection), 13 (agents flow), 14 (revision visualization) — all LOW
- Design decision Q7: Flat attempt list with visual connectors (lowest effort)
- Depends on GateTypeBadge from Step 3 for routine detail rendering (soft dependency — can use plain text fallback)
- Architecture: `context/CreateRunContext.tsx` manages modal state with navigation pre-fill
