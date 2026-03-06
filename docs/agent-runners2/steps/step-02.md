# Step 2: Rename "Agents" to "Agent Runners" (Frontend)

Rename all frontend references from "Agent" to "AgentRunner" -- pages, components, types, routes, API URLs, and UI labels. This completes the rename across the full stack and clears the "Agent" namespace for the new concept introduced in Step 5.

## Intent Verification
**Original Intent**: Complete the rename of "agents" to "agent-runners" in the frontend, matching the backend rename from Step 1 (see `docs/agent-runners2/intent.md`).
**Functionality to Produce**:
- Page renamed to `AgentRunners.tsx`, route changed to `/agent-runners`
- All component, type, and utility names use `AgentRunner` prefix
- API calls target `/api/agent-runners`
- UI labels display "Agent Runners" in nav, headings, tooltips

**Final Verification Criteria**:
- All 221+ frontend tests pass
- TypeScript type-check (`tsc --noEmit`) clean
- ESLint clean, build succeeds
- `grep -r "AgentOption\b" ui/src/` returns no hits

---

## Task 1: Rename Types and Utility Files

**Description**: Rename `ui/src/types/agents.ts` to `agentRunners.ts` and update all type names. Rename `ui/src/lib/agentConfigUtils.ts` to `agentRunnerConfigUtils.ts` and update function names.

**Implementation Plan (Do These Steps)**
- [ ] Rename type file: `git mv ui/src/types/agents.ts ui/src/types/agentRunners.ts`
- [ ] In `agentRunners.ts`, rename types: `AgentOption` -> `AgentRunnerOption`, `AgentQuota` -> `AgentRunnerQuota`, and all related types
- [ ] Rename utils file: `git mv ui/src/lib/agentConfigUtils.ts ui/src/lib/agentRunnerConfigUtils.ts`
- [ ] Rename exported functions in the utils file to use `AgentRunner` prefix
- [ ] Update all import statements across the frontend that reference these files/types

**Dependencies**
- [ ] Step 1 (backend rename) must be complete -- API now serves `/api/agent-runners`

**References**
- `docs/agent-runners2/plan.md` -- M2 steps 2, 4
- `docs/agent-runners2/architecture.md` -- frontend file structure
- Current types: `ui/src/types/agents.ts`
- Current utils: `ui/src/lib/agentConfigUtils.ts`

**Constraints**
- Use `git mv` to preserve history
- Only rename types and utils in this task. Page/component renames are separate.

**Functionality (Expected Outcomes)**
- [ ] `agentRunners.ts` exports `AgentRunnerOption`, `AgentRunnerQuota`, etc.
- [ ] `agentRunnerConfigUtils.ts` exports renamed utility functions
- [ ] All imports across the codebase reference new paths

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] `grep -rn "from.*types/agents\b" ui/src/` returns no hits
- [ ] `grep -rn "AgentOption\b" ui/src/` returns no hits

---

## Task 2: Rename Page and Components

**Description**: Rename the Agents page and all agent-related components to use `AgentRunner` prefix.

**Implementation Plan (Do These Steps)**
- [ ] Rename page: `git mv ui/src/pages/Agents.tsx ui/src/pages/AgentRunners.tsx`
- [ ] Rename components (if in separate files): `AgentCard` -> `AgentRunnerCard`, `AgentConfigForm` -> `AgentRunnerConfigForm`, `AgentIcon` -> `AgentRunnerIcon`, `AgentQuotaBadge` -> `AgentRunnerQuotaBadge`, `AgentGuidancePanel` -> `AgentRunnerGuidancePanel`
- [ ] Update component names inside each file (function name, display name)
- [ ] Update all imports of these components throughout the app

**Dependencies**
- [ ] Task 1 must be complete (types renamed first)

**References**
- `docs/agent-runners2/plan.md` -- M2 steps 1, 3
- `docs/agent-runners2/architecture.md` -- frontend component list

**Constraints**
- Preserve component functionality -- only rename, no behavior changes

**Functionality (Expected Outcomes)**
- [ ] `AgentRunners.tsx` page exists and renders
- [ ] All `AgentRunner*` components exist and are importable
- [ ] No orphaned `AgentCard`, `AgentConfigForm`, etc. references

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] `grep -rn "AgentCard\b\|AgentConfigForm\b\|AgentIcon\b" ui/src/` returns no hits (old names gone)

---

## Task 3: Update Routes, API URLs, and UI Labels

**Description**: Update the router to serve `/agent-runners`, change API call URLs from `/api/agents` to `/api/agent-runners`, and update all visible UI text.

**Implementation Plan (Do These Steps)**
- [ ] Update router configuration: change route path to `/agent-runners`, import `AgentRunners` page
- [ ] Update all API fetch/axios calls: `/api/agents` -> `/api/agent-runners`, `/api/agents/local-models` -> `/api/agent-runners/local-models`
- [ ] Update UI text in nav sidebar: "Agents" -> "Agent Runners"
- [ ] Update page headings, tooltips, and any user-visible strings
- [ ] Update `CreateRunModal` and run-related components that reference agent type/config field names

**Dependencies**
- [ ] Tasks 1-2 must be complete (types and components renamed)

**References**
- `docs/agent-runners2/plan.md` -- M2 steps 5-7
- Clarification Q9: `/agent-runners` for runners, `/agents` for new agents concept

**Constraints**
- `/agents` route must be left free for the new Agents concept (Step 7)
- Do not add redirects from old paths unless explicitly needed

**Functionality (Expected Outcomes)**
- [ ] `/agent-runners` route renders the Agent Runners page
- [ ] API calls hit `/api/agent-runners` endpoints
- [ ] All visible text says "Agent Runners" not "Agents"

**Final Verification (Proof of Completion)**
- [ ] `grep -rn '"/api/agents"' ui/src/` returns no hits (only `/api/agent-runners`)
- [ ] `grep -rn 'path.*"/agents"' ui/src/` returns no hits in router config

---

## Task 4: Run Frontend Tests and Fix Failures

**Description**: Run the complete frontend test suite, TypeScript type-check, ESLint, and build. Fix any failures from the rename.

**Implementation Plan (Do These Steps)**
- [ ] Run type check: `cd ui && npx tsc --noEmit`
- [ ] Run tests: `cd ui && npx vitest run`
- [ ] Run lint: `cd ui && npx eslint src/`
- [ ] Run build: `cd ui && npx vite build`
- [ ] Fix any failures -- update test files that reference old names, fix snapshot mismatches

**Dependencies**
- [ ] Tasks 1-3 must be complete

**References**
- `docs/agent-runners2/plan.md` -- M2 step 8
- Test baseline: 221+ frontend tests

**Constraints**
- All existing tests must pass -- fix, don't skip

**Functionality (Expected Outcomes)**
- [ ] All frontend tests pass
- [ ] TypeScript, ESLint, and build all clean
- [ ] UI can be loaded in browser showing "Agent Runners"

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] `npx vitest run` -- all tests pass
- [ ] `npx vite build` succeeds
