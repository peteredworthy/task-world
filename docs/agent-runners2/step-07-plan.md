# Step Plan: Agents UI

## Purpose

Create the frontend "Agents" page for managing agent configurations (Planner, Builder, Verifier, and custom agents). Users can view, create, edit, and delete agents, edit system prompts, select model profiles, and reset prompts to factory defaults.

## Prerequisites

- **Step 02 (M2)** must be complete: frontend uses AgentRunner naming, `/agents` route is free
- **Step 05 (M5)** must be complete: backend agent CRUD API exists

## Functional Contract

### Inputs

- `GET /api/agents` response: list of agent objects with name, system_prompt, model_profile, timestamps
- `GET /api/model-profiles` response: list of available profiles for dropdown
- User interactions: create, edit, delete agents; edit prompts; reset prompts; select profiles

### Outputs

- New "Agents" page at `/agents` route
- Agent list showing all agents (Planner, Builder, Verifier + custom)
- Agent card/editor: name, model profile selector, system prompt editor (textarea or code editor)
- CRUD operations wired to API: create, update, delete
- "Reset to Default" button on agents with factory defaults
- Navigation: sidebar shows both "Agent Runners" and "Agents" links
- Types in `ui/src/types/agents.ts` (new file for Agent concept)
- API calls in `ui/src/lib/agentApi.ts`

### Error Cases

- Delete a default agent -> confirm dialog warning it may affect existing routines
- API error on save -> display error message, preserve form state
- Reset prompt on custom agent (no factory default) -> button disabled or hidden
- Agent name conflict on create -> display 409 error message

## Tasks

1. Create `ui/src/types/agents.ts` with Agent, ModelProfile types
2. Create `ui/src/lib/agentApi.ts` with CRUD API functions
3. Create `ui/src/pages/Agents.tsx` with agent list and management UI
4. Create `AgentCard.tsx` component: displays agent name, profile, prompt preview
5. Create `AgentEditor.tsx` component: prompt editing with textarea, profile selector, reset button
6. Add `/agents` route to router configuration
7. Update sidebar navigation: add "Agents" link alongside "Agent Runners"
8. Wire CRUD operations to backend API
9. Write frontend tests for agent page and components

## Verification Approach

### Auto-Verify

- Frontend tests: Agents page renders with default agents listed
- Frontend tests: creating an agent calls POST /api/agents
- Frontend tests: editing a prompt calls PUT /api/agents/{id}
- Frontend tests: deleting an agent calls DELETE with confirmation
- Frontend tests: reset button calls POST /api/agents/{id}/reset-prompt
- TypeScript type-check clean
- Build succeeds

### Manual Verification

- Navigate to `/agents` -- see Planner, Builder, Verifier cards
- Edit Builder's system prompt -- save persists, reload shows changes
- Click "Reset to Default" on Builder -- prompt reverts to factory default
- Create a custom "Security Reviewer" agent with ARCHITECT profile
- Delete the custom agent -- removed from list
- Sidebar shows both "Agent Runners" and "Agents" navigation items

## Context & References

- Plan: `docs/agent-runners2/plan.md` -- M7 specification
- Architecture: `docs/agent-runners2/architecture.md` -- frontend file structure, component list
- Clarification Q9: `/agent-runners` for runners, `/agents` for new agents concept
- API endpoints: `GET/POST /api/agents`, `GET/PUT/DELETE /api/agents/{id}`, `POST /api/agents/{id}/reset-prompt`
