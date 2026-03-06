# Step 8: Integration Testing and Polish

End-to-end verification that all pieces work together. Verify agent overrides resolve correct prompts, the full run lifecycle works, existing routines are backward compatible, and documentation is updated.

## Intent Verification
**Original Intent**: M8 from `docs/agent-runners2/plan.md` -- E2E testing, browser verification, documentation updates, and final polish.
**Functionality to Produce**:
- E2E test: routine with agent overrides at all levels runs correctly
- E2E test: existing routine without agent fields uses defaults
- Browser verification via Playwright MCP
- Updated documentation (AGENTS.md, docs/ARCHITECTURE.md)
- All test suites green
**Final Verification Criteria**:
- E2E tests pass
- All backend tests pass (330+ unit, 235+ integration)
- All frontend tests pass (221+)
- TypeScript type-check, ESLint, and build all clean
- Documentation updated

---

## Task 1: Write E2E Tests

**Description**: Create end-to-end tests verifying the full agent override lifecycle and backward compatibility.

**Implementation Plan (Do These Steps)**
- [ ] Create E2E test: routine with agent overrides at routine/step/task levels
  - Create agents with custom prompts
  - Create routine YAML referencing those agents at different levels
  - Run the routine
  - Verify correct prompt composition at each task (agent system prompt + task prompt)
  - Verify correct model resolution via profile
- [ ] Create E2E test: existing routine without agent fields
  - Use an existing routine YAML (no agent fields)
  - Run the routine
  - Verify default Builder/Verifier agents are used
  - Verify prompts work as before
- [ ] Run full test suite: backend unit, integration, frontend

**Dependencies**
- [ ] Steps 01-07 must all be complete

**References**
- `docs/agent-runners2/step-08-plan.md` -- Tasks 1, 2, 5
- `docs/agent-runners2/architecture.md` -- execution flow, prompt generation

**Constraints**
- Tests should run on non-default ports (8001/5174) to avoid conflicts with production orchestrator

**Functionality (Expected Outcomes)**
- [ ] E2E tests cover agent overrides at all 3 cascade levels
- [ ] Backward compatibility confirmed
- [ ] All test suites pass

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest` passes with no failures
- [ ] E2E tests exist and pass

---

## Task 2: Browser Verification with Playwright MCP

**Description**: Use Playwright MCP to verify UI visually -- Agent Runners page, Agents page, and run creation.

**Implementation Plan (Do These Steps)**
- [ ] Start backend on port 8001: `uvicorn scripts.serve:app --port 8001 --reload --reload-dir src --reload-dir scripts`
- [ ] Start frontend on port 5174: `VITE_API_PORT=8001 npx vite --port 5174`
- [ ] Browser verification steps:
  - Navigate to Agent Runners page, verify "Agent Runners" heading and profile config sections
  - Navigate to Agents page, verify Planner/Builder/Verifier cards with prompt editors
  - Create a custom agent, verify it appears in the list
  - Edit a prompt, save, reload -- verify persistence
  - Create a run, verify runner selection works
- [ ] Fix any visual/UX issues found

**Dependencies**
- [ ] Task 1 should be complete (all tests pass first)

**References**
- `docs/agent-runners2/step-08-plan.md` -- Tasks 3, 4
- Port configuration: backend 8001, frontend 5174
- MCP config: `npx -y @playwright/mcp@latest --headless`

**Constraints**
- Use non-default ports to avoid conflicting with production orchestrator

**Functionality (Expected Outcomes)**
- [ ] Agent Runners page shows renamed labels and profile sections
- [ ] Agents page shows CRUD functionality
- [ ] Run creation works end-to-end

**Final Verification (Proof of Completion)**
- [ ] Screenshots confirm UI renders correctly
- [ ] No visual/UX blockers remain

---

## Task 3: Update Documentation

**Description**: Update project documentation to reflect the refactored architecture.

**Implementation Plan (Do These Steps)**
- [ ] Update `AGENTS.md` with new concepts:
  - Agent Runners (renamed from Agents): execution environments
  - Model Profiles: cognitive work classes with per-runner defaults
  - Agents: prompt templates paired with model profiles
- [ ] Update `docs/ARCHITECTURE.md` with:
  - New directory structure (`src/orchestrator/runners/`, `src/orchestrator/agents/`)
  - New API routes (`/api/agent-runners`, `/api/model-profiles`, `/api/agents`)
  - New data model (agent_configs, runner_profile_defaults tables)
- [ ] Verify no stale "Agent" references (in the runner sense) remain in docs
- [ ] Run `grep -r "GET /api/agents\b" docs/` to check for stale API references (should only reference the new agents concept)

**Dependencies**
- [ ] Tasks 1-2 should be complete (all code changes finalized)

**References**
- `docs/agent-runners2/step-08-plan.md` -- Tasks 6, 7
- `docs/agent-runners2/architecture.md` -- full system overview (source of truth for docs)

**Constraints**
- Documentation must accurately reflect the final state of the codebase
- Don't document planned-but-unimplemented features

**Functionality (Expected Outcomes)**
- [ ] AGENTS.md explains all 3 concepts clearly
- [ ] ARCHITECTURE.md has accurate file structure and API routes
- [ ] No stale references to old naming

**Final Verification (Proof of Completion)**
- [ ] Documentation files updated
- [ ] `grep -rn "AgentType\b" AGENTS.md` returns no hits (old naming)
