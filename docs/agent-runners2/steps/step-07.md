# Step 7: Agents UI

Create the frontend "Agents" page for managing agent configurations (Planner, Builder, Verifier, and custom agents). Users can view, create, edit, and delete agents, edit system prompts, select model profiles, and reset prompts to factory defaults.

## Intent Verification
**Original Intent**: Provide a UI for managing the new Agent concept -- CRUD operations, prompt editing, profile selection (see `docs/agent-runners2/intent.md` -- "Agents" section).
**Functionality to Produce**:
- New "Agents" page at `/agents` route
- Agent list showing Planner, Builder, Verifier + custom agents
- Agent card/editor with name, model profile selector, system prompt editor
- CRUD wired to API, "Reset to Default" button for factory prompts
- Navigation sidebar shows both "Agent Runners" and "Agents"

**Final Verification Criteria**:
- Frontend tests pass for agent page and components
- TypeScript type-check clean, build succeeds
- `/agents` route renders agent management page
- Sidebar shows both navigation items

---

## Task 1: Create Agent Types and API Functions

**Description**: Add TypeScript types for the Agent concept and create API functions for agent CRUD operations.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/types/agents.ts` with:
  ```typescript
  export interface Agent {
    id: string;
    name: string;
    system_prompt: string;
    default_prompt: string | null;
    model_profile: string;
    created_at: string;
    updated_at: string;
  }
  export interface CreateAgentRequest {
    name: string;
    system_prompt: string;
    model_profile: string;
  }
  export interface UpdateAgentRequest {
    name?: string;
    system_prompt?: string;
    model_profile?: string;
  }
  ```
- [ ] Create `ui/src/lib/agentApi.ts` with API functions:
  - `fetchAgents(): Promise<Agent[]>` -- GET /api/agents
  - `fetchAgent(id: string): Promise<Agent>` -- GET /api/agents/{id}
  - `createAgent(data: CreateAgentRequest): Promise<Agent>` -- POST /api/agents
  - `updateAgent(id: string, data: UpdateAgentRequest): Promise<Agent>` -- PUT /api/agents/{id}
  - `deleteAgent(id: string): Promise<void>` -- DELETE /api/agents/{id}
  - `resetAgentPrompt(id: string): Promise<Agent>` -- POST /api/agents/{id}/reset-prompt

**Dependencies**
- [ ] Step 2 must be complete (frontend uses AgentRunner naming, `/agents` route is free)
- [ ] Step 5 must be complete (backend agent CRUD API exists)

**References**
- `docs/agent-runners2/architecture.md` -- frontend file structure, API endpoints
- `docs/agent-runners2/plan.md` -- M7 steps 1-2

**Constraints**
- Follow existing API call patterns in the codebase
- These types are for the NEW Agent concept, not runners

**Functionality (Expected Outcomes)**
- [ ] `Agent` type is importable from `types/agents`
- [ ] All API functions correctly target `/api/agents` endpoints

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes

---

## Task 2: Create Agents Page and Components

**Description**: Build the Agents page with list view, agent cards, and the agent editor component for prompt editing and profile selection.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/pages/Agents.tsx`:
  - Fetch agents list on mount
  - Render agent cards in a grid/list
  - "Create Agent" button opens create form
- [ ] Create `AgentCard.tsx` component (or embed in page):
  - Displays agent name, model profile badge, prompt preview (truncated)
  - Edit button opens editor
  - Delete button with confirmation dialog
- [ ] Create `AgentEditor.tsx` component:
  - Form fields: name input, model profile selector (dropdown of ModelProfile values), system prompt textarea
  - "Reset to Default" button (visible only when `default_prompt` is not null)
  - Save/Cancel buttons
  - Loading and error states
- [ ] Wire CRUD operations to API functions from Task 1

**Dependencies**
- [ ] Task 1 must be complete (types and API functions exist)

**References**
- `docs/agent-runners2/architecture.md` -- frontend component list
- `docs/agent-runners2/plan.md` -- M7 steps 3-5, 8
- Clarification Q9: `/agents` for new agents concept

**Constraints**
- Use existing UI patterns (TailwindCSS, existing component structure)
- "Reset to Default" button disabled/hidden for custom agents (no `default_prompt`)
- Confirm dialog on delete warns about potential routine impact

**Functionality (Expected Outcomes)**
- [ ] Agents page renders with default agents listed
- [ ] Creating an agent adds it to the list
- [ ] Editing an agent's prompt persists changes
- [ ] Deleting an agent removes it from the list
- [ ] Reset button restores factory default prompt

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] `npx vite build` succeeds

---

## Task 3: Add Route and Update Navigation

**Description**: Add the `/agents` route to the router and update the sidebar navigation to include both "Agent Runners" and "Agents" links.

**Implementation Plan (Do These Steps)**
- [ ] Add route in router configuration: `{ path: "/agents", element: <Agents /> }`
- [ ] Update sidebar navigation component:
  - Add "Agents" link pointing to `/agents`
  - Keep "Agent Runners" link pointing to `/agent-runners`
  - Use appropriate icons to differentiate the two
- [ ] Verify both routes render their respective pages

**Dependencies**
- [ ] Task 2 must be complete (Agents page exists)

**References**
- `docs/agent-runners2/plan.md` -- M7 steps 6-7
- Clarification Q9: `/agent-runners` for runners, `/agents` for new agents concept

**Constraints**
- Both links must be visible in the sidebar simultaneously
- Do not modify the Agent Runners route or page

**Functionality (Expected Outcomes)**
- [ ] `/agents` renders the Agents page
- [ ] `/agent-runners` still renders the Agent Runners page
- [ ] Sidebar shows both navigation items

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] `npx vite build` succeeds

---

## Task 4: Write Frontend Tests

**Description**: Write tests for the Agents page, agent card, and agent editor components.

**Implementation Plan (Do These Steps)**
- [ ] Write tests for Agents page:
  - Renders with default agents listed (mock API)
  - Creating an agent calls POST /api/agents
  - Deleting an agent calls DELETE with confirmation
- [ ] Write tests for agent editor:
  - Editing a prompt calls PUT /api/agents/{id}
  - Reset button calls POST /api/agents/{id}/reset-prompt
  - Reset button hidden when `default_prompt` is null
  - Profile selector shows all 4 profiles
- [ ] Run full frontend test suite to verify no regressions

**Dependencies**
- [ ] Tasks 2-3 must be complete (page and routes exist)

**References**
- `docs/agent-runners2/plan.md` -- M7 step 9
- Existing test patterns in the codebase

**Constraints**
- Follow existing test patterns (vitest + testing-library)
- Mock API calls, don't depend on running backend

**Functionality (Expected Outcomes)**
- [ ] Agent page and component tests cover CRUD and reset scenarios
- [ ] All frontend tests pass

**Final Verification (Proof of Completion)**
- [ ] `npx vitest run` -- all tests pass
- [ ] `npx tsc --noEmit` passes
- [ ] `npx vite build` succeeds
