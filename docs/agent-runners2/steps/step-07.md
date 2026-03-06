# Step 7: Agents UI

Create the frontend "Agents" page for managing agent configurations. Users can view, create, edit, and delete agents, edit system prompts, select model profiles, and reset prompts to factory defaults.

## Intent Verification
**Original Intent**: M7 from `docs/agent-runners2/plan.md` -- create Agents UI page with CRUD operations, prompt editing, profile selection, and factory default reset.
**Functionality to Produce**:
- New "Agents" page at `/agents` route
- Agent list showing Planner, Builder, Verifier + custom agents
- Agent card/editor with name, profile selector, prompt editor
- CRUD operations wired to backend API
- "Reset to Default" button for agents with factory defaults
- Navigation updated with "Agents" link
**Final Verification Criteria**:
- `npx tsc --noEmit` passes
- `npx vite build` succeeds
- Frontend tests pass for Agents page
- `/agents` route renders the agents page

---

## Task 1: Create Agent Types and API Module

**Description**: Create TypeScript types for the Agent concept and an API module for CRUD operations.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/types/agents.ts` with:
  - `Agent` interface (id, name, system_prompt, default_prompt, model_profile, created_at, updated_at)
  - `CreateAgentRequest` (name, system_prompt, model_profile)
  - `UpdateAgentRequest` (name?, system_prompt?, model_profile?)
- [ ] Create `ui/src/lib/agentApi.ts` with CRUD API functions:
  - `fetchAgents()` -> `GET /api/agents`
  - `createAgent(data)` -> `POST /api/agents`
  - `updateAgent(id, data)` -> `PUT /api/agents/{id}`
  - `deleteAgent(id)` -> `DELETE /api/agents/{id}`
  - `resetAgentPrompt(id)` -> `POST /api/agents/{id}/reset-prompt`

**Dependencies**
- [ ] Step 02 must be complete (frontend uses AgentRunner naming, `/agents` route is free)
- [ ] Step 05 must be complete (backend agent CRUD API exists)

**References**
- `docs/agent-runners2/step-07-plan.md` -- Tasks 1, 2
- `docs/agent-runners2/architecture.md` -- frontend type and file structure

**Constraints**
- Types must match backend schema exactly
- Follow existing API module patterns

**Functionality (Expected Outcomes)**
- [ ] `Agent` type is importable from `types/agents.ts`
- [ ] All CRUD functions are importable from `lib/agentApi.ts`

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes

---

## Task 2: Create Agents Page and Agent Components

**Description**: Build the Agents page with agent list, card display, and editor for prompt/profile management.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/pages/Agents.tsx` with agent list and management UI
- [ ] Create `AgentCard.tsx` component: displays agent name, profile badge, prompt preview
- [ ] Create `AgentEditor.tsx` component: prompt editing with textarea, profile selector dropdown, reset button
- [ ] Wire list to `GET /api/agents` (use TanStack Query hook)
- [ ] Wire create/update/delete to respective API functions
- [ ] "Reset to Default" button: calls `POST /api/agents/{id}/reset-prompt`, disabled/hidden for custom agents without `default_prompt`
- [ ] Error handling: delete confirmation dialog, save error display, 409 on duplicate name

**Dependencies**
- [ ] Task 1 must be complete (types and API module exist)

**References**
- `docs/agent-runners2/step-07-plan.md` -- Tasks 3, 4, 5, 8
- `docs/agent-runners2/architecture.md` -- component list

**Constraints**
- Delete a default agent shows confirmation warning about potential impact on routines
- Follow existing page/component patterns in the codebase

**Functionality (Expected Outcomes)**
- [ ] Agents page renders list of agents (Planner, Builder, Verifier + custom)
- [ ] Agent card shows name, profile, and prompt preview
- [ ] Editor allows prompt editing and profile selection
- [ ] CRUD operations work end-to-end

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] Agents page renders without errors

---

## Task 3: Add Route and Navigation, Write Tests

**Description**: Add `/agents` route to the router, update sidebar navigation, and write frontend tests.

**Implementation Plan (Do These Steps)**
- [ ] Add `/agents` route to router configuration, importing `Agents.tsx` page
- [ ] Update sidebar navigation: add "Agents" link alongside "Agent Runners"
- [ ] Write frontend tests:
  - Agents page renders with default agents listed
  - Creating an agent calls `POST /api/agents`
  - Editing a prompt calls `PUT /api/agents/{id}`
  - Deleting an agent calls `DELETE` with confirmation
  - Reset button calls `POST /api/agents/{id}/reset-prompt`
- [ ] Verify TypeScript type-check clean
- [ ] Verify build succeeds

**Dependencies**
- [ ] Task 2 must be complete (page and components exist)

**References**
- `docs/agent-runners2/step-07-plan.md` -- Tasks 6, 7, 9
- Clarification Q9: `/agent-runners` for runners, `/agents` for new agents concept

**Constraints**
- Sidebar must show both "Agent Runners" and "Agents" navigation items

**Functionality (Expected Outcomes)**
- [ ] `/agents` route renders the Agents page
- [ ] Sidebar shows both navigation links
- [ ] All frontend tests pass

**Final Verification (Proof of Completion)**
- [ ] `npx vitest run` passes all tests
- [ ] `npx vite build` succeeds
- [ ] Router config includes `/agents` path
