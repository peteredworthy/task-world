# Step Plan: Rename "Agents" to "Agent Runners" (Frontend)

## Purpose

Rename all frontend references from "Agent" to "AgentRunner" -- pages, components, types, routes, API URLs, and UI labels. This completes the rename across the full stack and clears the "Agent" namespace for the new concept introduced in M5.

## Prerequisites

- **Step 01 (M1)** must be complete: backend API now serves `/api/agent-runners` and all backend types are renamed.

## Functional Contract

### Inputs

- Existing frontend with `Agents.tsx` page, `AgentCard`, `AgentConfigForm`, `AgentIcon`, `AgentQuotaBadge`, `AgentGuidancePanel` components
- Existing types in `ui/src/types/agents.ts`: `AgentOption`, `AgentQuota`, etc.
- Existing utils in `ui/src/lib/agentConfigUtils.ts`
- Existing route `/agents` in router configuration
- API calls targeting `/api/agents`

### Outputs

- Page `ui/src/pages/AgentRunners.tsx` (renamed from `Agents.tsx`)
- Components renamed: `AgentRunnerCard`, `AgentRunnerConfigForm`, `AgentRunnerIcon`, `AgentRunnerQuotaBadge`, `AgentRunnerGuidancePanel`
- Types file `ui/src/types/agentRunners.ts` with `AgentRunnerOption`, `AgentRunnerQuota`, etc.
- Utils file `ui/src/lib/agentRunnerConfigUtils.ts` with renamed functions
- Route changed to `/agent-runners`
- API calls updated to `/api/agent-runners`
- All UI labels changed: "Agents" -> "Agent Runners" in nav, headings, tooltips

### Error Cases

- Missed import references -- TypeScript compiler will catch these as type errors
- Broken routes -- router config must update path and any navigation links
- Stale localStorage keys referencing old names -- handle gracefully (read old key, migrate or ignore)

## Tasks

1. Rename `ui/src/pages/Agents.tsx` -> `AgentRunners.tsx`, update route to `/agent-runners` in router
2. Rename `ui/src/types/agents.ts` -> `agentRunners.ts`, update all type names
3. Rename components: `AgentCard` -> `AgentRunnerCard`, `AgentConfigForm` -> `AgentRunnerConfigForm`, `AgentIcon` -> `AgentRunnerIcon`, `AgentQuotaBadge` -> `AgentRunnerQuotaBadge`, `AgentGuidancePanel` -> `AgentRunnerGuidancePanel`
4. Update `agentConfigUtils.ts` -> `agentRunnerConfigUtils.ts`, rename functions
5. Update API call URLs from `/api/agents` to `/api/agent-runners`
6. Update all UI labels: "Agents" -> "Agent Runners" in nav, headings, tooltips
7. Update `CreateRunModal` and run-related components that reference agent type/config
8. Run frontend tests, fix failures. TypeScript type-check clean

## Verification Approach

### Auto-Verify

- All 221+ frontend tests pass
- TypeScript type-check (`tsc --noEmit`) passes with no errors
- ESLint clean
- `npx vite build` succeeds
- `grep -r "AgentOption\b" ui/src/` returns no hits (old type names eliminated)

### Manual Verification

- Navigate to `/agent-runners` -- page renders with "Agent Runners" heading
- Create a run via UI -- runner selection works with new API path
- Old `/agents` route no longer resolves (or redirects)

## Context & References

- Plan: `docs/agent-runners2/plan.md` -- M2 specification
- Architecture: `docs/agent-runners2/architecture.md` -- frontend file structure after refactor
- Clarification Q9: `/agent-runners` for runners, `/agents` for new agents concept
- Current page: `ui/src/pages/Agents.tsx`
- Current types: `ui/src/types/agents.ts`
- Current utils: `ui/src/lib/agentConfigUtils.ts`
