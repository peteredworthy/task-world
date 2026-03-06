# Step 2: Rename "Agents" to "Agent Runners" (Frontend)

Rename all frontend references from "Agent" to "AgentRunner" -- pages, components, types, routes, API URLs, and UI labels. This completes the full-stack rename and frees the "Agent" namespace for the new concept in Step 5.

## Intent Verification
**Original Intent**: M2 from `docs/agent-runners2/plan.md` -- rename all frontend "Agent" references to "AgentRunner" across pages, components, types, routes, and labels.
**Functionality to Produce**:
- Page renamed to `AgentRunners.tsx`, route changed to `/agent-runners`
- All component names updated with `AgentRunner` prefix
- Types file renamed to `agentRunners.ts` with updated type names
- API calls updated to `/api/agent-runners`
- All UI labels changed from "Agents" to "Agent Runners"
**Final Verification Criteria**:
- All 221+ frontend tests pass
- `npx tsc --noEmit` passes
- `npx vite build` succeeds
- `grep -r "AgentOption\b" ui/src/` returns no hits

---

## Task 1: Rename Types File and Type Names

**Description**: Rename `ui/src/types/agents.ts` to `agentRunners.ts` and update all type names from Agent* to AgentRunner*.

**Implementation Plan (Do These Steps)**
- [ ] Rename file: `git mv ui/src/types/agents.ts ui/src/types/agentRunners.ts`
- [ ] Rename types: `AgentOption` -> `AgentRunnerOption`, `AgentQuota` -> `AgentRunnerQuota`, etc.
- [ ] Update all files that import from `types/agents` to import from `types/agentRunners`
- [ ] Update type references throughout the codebase

**Dependencies**
- [ ] Step 01 must be complete (backend API serves `/api/agent-runners`)

**References**
- `docs/agent-runners2/step-02-plan.md` -- Task 2
- `docs/agent-runners2/architecture.md` -- frontend type structure

**Constraints**
- Only rename types related to runners. Do not create new types for the Agent concept yet.

**Functionality (Expected Outcomes)**
- [ ] `ui/src/types/agentRunners.ts` exists with `AgentRunner`-prefixed types
- [ ] All imports updated across the codebase

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] `grep -rn "AgentOption" ui/src/` returns no hits (only AgentRunnerOption)

---

## Task 2: Rename Page and Route

**Description**: Rename `Agents.tsx` page to `AgentRunners.tsx` and update the route from `/agents` to `/agent-runners`.

**Implementation Plan (Do These Steps)**
- [ ] Rename file: `git mv ui/src/pages/Agents.tsx ui/src/pages/AgentRunners.tsx`
- [ ] Update the component name inside the file
- [ ] Update router configuration to use `/agent-runners` path and import the renamed page
- [ ] Update any navigation links pointing to the old route

**Dependencies**
- [ ] Task 1 should be complete (types renamed)

**References**
- `docs/agent-runners2/step-02-plan.md` -- Task 1
- Clarification Q9: `/agent-runners` for runners, `/agents` for new agents concept

**Constraints**
- The `/agents` route must be freed for the new Agent concept (Step 7)

**Functionality (Expected Outcomes)**
- [ ] `/agent-runners` route renders the runners page
- [ ] Old `/agents` route no longer renders runners

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] Router config references `/agent-runners` path

---

## Task 3: Rename Components

**Description**: Rename all Agent* components to AgentRunner* and update their imports.

**Implementation Plan (Do These Steps)**
- [ ] Rename `AgentCard` -> `AgentRunnerCard` (file and component name)
- [ ] Rename `AgentConfigForm` -> `AgentRunnerConfigForm`
- [ ] Rename `AgentIcon` -> `AgentRunnerIcon`
- [ ] Rename `AgentQuotaBadge` -> `AgentRunnerQuotaBadge`
- [ ] Rename `AgentGuidancePanel` -> `AgentRunnerGuidancePanel`
- [ ] Update all imports across the codebase for each renamed component

**Dependencies**
- [ ] Tasks 1-2 should be complete

**References**
- `docs/agent-runners2/step-02-plan.md` -- Task 3
- `docs/agent-runners2/architecture.md` -- frontend component structure

**Functionality (Expected Outcomes)**
- [ ] All component files and exports use `AgentRunner` prefix
- [ ] No orphaned imports to old component names

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] `grep -rn "AgentCard\b" ui/src/` returns no hits (only AgentRunnerCard)

---

## Task 4: Update Utils, API URLs, and UI Labels

**Description**: Rename `agentConfigUtils.ts` to `agentRunnerConfigUtils.ts`, update API call URLs from `/api/agents` to `/api/agent-runners`, and change all UI labels.

**Implementation Plan (Do These Steps)**
- [ ] Rename utils: `git mv ui/src/lib/agentConfigUtils.ts ui/src/lib/agentRunnerConfigUtils.ts`
- [ ] Rename exported functions to use `AgentRunner` prefix
- [ ] Update all API call URLs from `/api/agents` to `/api/agent-runners`
- [ ] Update all UI labels: "Agents" -> "Agent Runners" in nav, headings, tooltips, button text
- [ ] Update `CreateRunModal` and run-related components that reference agent type/config

**Dependencies**
- [ ] Tasks 1-3 should be complete

**References**
- `docs/agent-runners2/step-02-plan.md` -- Tasks 4, 5, 6, 7

**Constraints**
- Ensure nav labels match the new naming consistently

**Functionality (Expected Outcomes)**
- [ ] Utils file renamed with updated function names
- [ ] API calls target `/api/agent-runners`
- [ ] All visible UI text says "Agent Runners" instead of "Agents"

**Final Verification (Proof of Completion)**
- [ ] `grep -rn '"/api/agents"' ui/src/` returns no hits
- [ ] `grep -rn "agentConfigUtils" ui/src/` returns no hits

---

## Task 5: Fix Tests and Verify Build

**Description**: Run frontend tests, fix TypeScript errors, verify ESLint and build pass.

**Implementation Plan (Do These Steps)**
- [ ] Run TypeScript check: `npx tsc --noEmit`
- [ ] Fix any type errors from the rename
- [ ] Run frontend tests: `npx vitest run`
- [ ] Fix any test failures (update imports, component names in tests)
- [ ] Run ESLint: `npx eslint .`
- [ ] Run build: `npx vite build`

**Dependencies**
- [ ] Tasks 1-4 must be complete

**References**
- `docs/agent-runners2/step-02-plan.md` -- Task 8
- Test baseline: 221+ frontend tests

**Constraints**
- All existing tests must pass -- no test deletions

**Functionality (Expected Outcomes)**
- [ ] All 221+ frontend tests pass
- [ ] TypeScript type-check clean
- [ ] ESLint clean
- [ ] Build succeeds

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] `npx vitest run` passes all tests
- [ ] `npx vite build` succeeds
