# Step Plan: Integration Testing and Polish

## Purpose

End-to-end verification that all pieces work together: agent overrides in routines resolve correct prompts and models, the full run lifecycle works, the UI is polished, and all existing routines run without modification. Update documentation to reflect the refactored architecture.

## Prerequisites

- **All previous steps (01-07)** must be complete: full rename, model profiles, agents concept, routine schema, and UI all in place.

## Functional Contract

### Inputs

- A routine YAML with agent overrides at different levels (routine, step, task)
- The full running system: backend on port 8001, frontend on port 5174 (non-default to avoid conflicts)
- Existing routines without agent fields (backward compatibility test)

### Outputs

- E2E test: routine with agent overrides runs to completion, correct prompts and models used at each phase
- Browser verification via Playwright MCP: Agent Runners page, Agents page, run creation all work visually
- All existing routines run without modification
- Updated documentation: `AGENTS.md`, `docs/ARCHITECTURE.md` reflect new concepts
- All test suites green: backend unit, integration, frontend, type-check, lint, build

### Error Cases

- E2E test discovers prompt composition bug -> fix in step 06 code, re-verify
- Browser test finds visual/UX issues -> fix CSS/layout in step 07 components
- Existing routine breaks -> cascading resolution has a bug, fix in step 06

## Tasks

1. Create E2E test: routine with agent overrides at routine/step/task levels, verify correct prompts and models
2. Create E2E test: existing routine without agent fields runs with defaults
3. Browser verification using Playwright MCP on ports 8001/5174:
   - Navigate to Agent Runners page, verify renamed labels
   - Navigate to Agents page, verify CRUD works
   - Create a run, verify runner selection and agent resolution
4. Fix any visual/UX issues found during browser testing
5. Run full test suite: backend unit, integration, frontend, TypeScript type-check, ESLint, build
6. Update `AGENTS.md` with new concepts (Agent Runners, Model Profiles, Agents)
7. Update `docs/ARCHITECTURE.md` with new directory structure, API routes, and data model

## Verification Approach

### Auto-Verify

- E2E test: full lifecycle with agent overrides passes
- E2E test: backward-compatible routine passes
- All backend tests pass (330+ unit, 235+ integration)
- All frontend tests pass (221+)
- TypeScript type-check clean
- ESLint clean
- Build succeeds

### Manual Verification

- Playwright MCP screenshots confirm:
  - Agent Runners page shows "Agent Runners" heading, profile config sections
  - Agents page shows Planner, Builder, Verifier with prompt editors
  - Run creation modal works with runner selection
- `AGENTS.md` and `docs/ARCHITECTURE.md` accurately reflect the refactored system

## Context & References

- Plan: `docs/agent-runners2/plan.md` -- M8 specification
- Architecture: `docs/agent-runners2/architecture.md` -- full system overview
- Port configuration: backend 8001, frontend 5174 (non-default for testing)
- MCP server config: `npx -y @playwright/mcp@latest --headless`
- Test baseline: 330+ unit, 235+ integration, 221+ frontend tests
