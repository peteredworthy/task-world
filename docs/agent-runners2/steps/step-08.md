# Step 8: Integration Testing and Polish

End-to-end verification that all pieces work together: agent overrides in routines resolve correct prompts and models, the full run lifecycle works, the UI is polished, and all existing routines run without modification. Update documentation to reflect the refactored architecture.

## Intent Verification
**Original Intent**: Verify the complete refactor works end-to-end and update documentation (see `docs/agent-runners2/intent.md` -- "Completion Criteria").
**Functionality to Produce**:
- E2E tests proving agent overrides resolve correct prompts and models
- Browser verification of Agent Runners and Agents pages
- All existing routines run without modification
- Updated documentation (AGENTS.md, architecture docs)

**Final Verification Criteria**:
- E2E lifecycle tests pass
- All backend tests pass (330+ unit, 235+ integration + new tests)
- All frontend tests pass (221+ + new tests)
- TypeScript, ESLint, build all clean
- Documentation updated

---

## Task 1: Create E2E Tests for Agent Overrides

**Description**: Write end-to-end tests that create a routine with agent overrides at different levels, run it, and verify correct prompts and models are used.

**Implementation Plan (Do These Steps)**
- [ ] Create E2E test: routine with agent overrides at routine/step/task levels
  - Create custom agents with distinct prompts
  - Create routine YAML referencing those agents
  - Verify prompt endpoint returns correct agent-prefixed prompt at each level
  - Verify model resolution uses the agent's profile defaults
- [ ] Create E2E test: existing routine without agent fields runs with system defaults
  - Use an existing routine YAML with no `*_agent` fields
  - Verify prompt endpoint returns default Builder/Verifier prompts
  - Verify run completes successfully
- [ ] Create E2E test: per-run model-profile overrides (if implemented in earlier steps)

**Dependencies**
- [ ] All previous steps (01-07) must be complete

**References**
- `docs/agent-runners2/plan.md` -- M8 steps 1-2
- `docs/agent-runners2/architecture.md` -- execution flow, resolution order

**Constraints**
- Tests must be self-contained (create their own test data, clean up after)
- Use test database, not production

**Functionality (Expected Outcomes)**
- [ ] E2E test with agent overrides passes
- [ ] E2E test with backward-compatible routine passes
- [ ] Tests verify both prompt content and model resolution

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/integration/test_agent_overrides.py -v` -- all pass (or equivalent test file)

---

## Task 2: Browser Verification with Playwright MCP

**Description**: Run the system on non-default ports and verify the UI using Playwright MCP browser automation.

**Implementation Plan (Do These Steps)**
- [ ] Start backend on port 8001: `uvicorn scripts.serve:app --port 8001 --reload --reload-dir src --reload-dir scripts`
- [ ] Start frontend on port 5174: `VITE_API_PORT=8001 npx vite --port 5174`
- [ ] Browser verification checklist:
  - Navigate to Agent Runners page (`http://localhost:5174/agent-runners`): verify "Agent Runners" heading, profile config sections on cards
  - Navigate to Agents page (`http://localhost:5174/agents`): verify Planner, Builder, Verifier displayed with prompt editors
  - Test agent CRUD: create a custom agent, edit its prompt, delete it
  - Navigate to run creation: verify runner selection works with new naming
- [ ] Fix any visual/UX issues found

**Dependencies**
- [ ] Task 1 must be complete (E2E tests prove backend works)

**References**
- `docs/agent-runners2/plan.md` -- M8 step 3, port configuration section
- MCP config: `npx -y @playwright/mcp@latest --headless`

**Constraints**
- Use ports 8001/5174 to avoid conflicting with production orchestrator
- Document any visual fixes made

**Functionality (Expected Outcomes)**
- [ ] Agent Runners page displays correctly with profile sections
- [ ] Agents page displays correctly with CRUD functionality
- [ ] Run creation works with renamed runner selection

**Final Verification (Proof of Completion)**
- [ ] Browser screenshots confirm both pages render correctly
- [ ] No JavaScript console errors on either page

---

## Task 3: Run Full Test Suite and Fix Any Regressions

**Description**: Run the complete test suite across backend and frontend, fix any regressions.

**Implementation Plan (Do These Steps)**
- [ ] Run backend unit tests: `uv run pytest tests/unit/ -v --timeout=60`
- [ ] Run backend integration tests: `uv run pytest tests/integration/ -v --timeout=120`
- [ ] Run frontend tests: `cd ui && npx vitest run`
- [ ] Run TypeScript type-check: `cd ui && npx tsc --noEmit`
- [ ] Run ESLint: `cd ui && npx eslint src/`
- [ ] Run frontend build: `cd ui && npx vite build`
- [ ] Fix any failures

**Dependencies**
- [ ] Tasks 1-2 should be complete

**References**
- Test baseline: 330+ unit, 235+ integration, 221+ frontend
- `docs/agent-runners2/plan.md` -- M8 step 5

**Constraints**
- All existing tests must pass
- New tests from steps 3-7 must also pass

**Functionality (Expected Outcomes)**
- [ ] All backend tests pass
- [ ] All frontend tests pass
- [ ] TypeScript, ESLint, build all clean

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/ -v` -- all pass
- [ ] `npx vitest run` -- all pass
- [ ] `npx tsc --noEmit` -- clean
- [ ] `npx vite build` -- succeeds

---

## Task 4: Update Documentation

**Description**: Update `AGENTS.md` and architecture documentation to reflect the refactored system with Agent Runners, Model Profiles, and Agents concepts.

**Implementation Plan (Do These Steps)**
- [ ] Update `AGENTS.md`:
  - Document Agent Runner concept (renamed from Agent)
  - Document Model Profiles concept (4 profiles, per-runner defaults)
  - Document Agent concept (prompt + profile, CRUD, factory defaults)
  - Document routine schema agent fields and cascading resolution
  - Document API endpoint changes (renamed + new)
- [ ] Update any existing architecture docs that reference old naming
- [ ] Verify no documentation references old "Agent" naming in the runner context

**Dependencies**
- [ ] Task 3 must be complete (all tests pass, system is stable)

**References**
- `docs/agent-runners2/architecture.md` -- source of truth for new architecture
- `docs/agent-runners2/intent.md` -- scope and completion criteria
- `docs/agent-runners2/plan.md` -- M8 steps 6-7

**Constraints**
- Documentation should be accurate and match implemented behavior
- Keep docs concise -- reference architecture doc for details

**Functionality (Expected Outcomes)**
- [ ] `AGENTS.md` accurately reflects the refactored system
- [ ] No orphaned references to old naming in documentation

**Final Verification (Proof of Completion)**
- [ ] `AGENTS.md` contains sections for Agent Runners, Model Profiles, and Agents
- [ ] `grep -rn "AgentType\b\|AgentExecutor\b" AGENTS.md docs/` returns no hits (old naming removed)
