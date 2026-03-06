# Step 4: Model Profiles (Frontend)

Add model profile configuration UI to each Agent Runner card, allowing users to set which model each runner uses for each cognitive profile (Architect, Designer, Coder, Summarizer).

## Intent Verification
**Original Intent**: M4 from `docs/agent-runners2/plan.md` -- add profile-to-model configuration UI on each runner card with save/load to backend API.
**Functionality to Produce**:
- "Model Profiles" section on each AgentRunnerCard with 4 model selector fields
- Combobox with custom model entry support
- Save/load wired to `GET/PUT /api/agent-runners/{type}/profiles`
- Frontend tests for profile UI components
**Final Verification Criteria**:
- `npx tsc --noEmit` passes
- `npx vite build` succeeds
- Frontend tests pass for profile section rendering and API wiring

---

## Task 1: Add Profile Section to Runner Card

**Description**: Add a "Model Profiles" section to `AgentRunnerCard` with 4 model selector fields (one per profile) and wire save/load to the backend API.

**Implementation Plan (Do These Steps)**
- [ ] Fetch profile data from `GET /api/model-profiles` (for descriptions) and `GET /api/agent-runners/{type}/profiles` (for current defaults) on card load
- [ ] Add a "Model Profiles" collapsible/expandable section to `AgentRunnerCard`
- [ ] Render 4 fields: Architect, Designer, Coder, Summarizer -- each with a model selector
- [ ] Model selector: combobox with `allow_custom` for entering arbitrary model strings (match existing model selector patterns)
- [ ] Wire save to `PUT /api/agent-runners/{type}/profiles` endpoint
- [ ] Handle errors: show error state on load failure with retry, display validation errors on save failure

**Dependencies**
- [ ] Step 02 must be complete (frontend uses AgentRunner naming)
- [ ] Step 03 must be complete (backend profile API exists)

**References**
- `docs/agent-runners2/step-04-plan.md` -- Tasks 1-5
- `docs/agent-runners2/architecture.md` -- `AgentRunnerOption.profile_defaults` field

**Constraints**
- Follow existing UI patterns for model selectors
- Empty model string for a profile means "use runner default" (clear from overrides)

**Functionality (Expected Outcomes)**
- [ ] Each runner card shows profile section with 4 fields
- [ ] Saving profiles persists to backend
- [ ] Loading profiles populates form fields from backend

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] Profile section renders on runner cards

---

## Task 2: Write Frontend Tests for Profile UI

**Description**: Write frontend tests verifying profile section rendering, API wiring, and save/load behavior.

**Implementation Plan (Do These Steps)**
- [ ] Test: profile section renders with 4 fields on runner card
- [ ] Test: saving profiles calls `PUT /api/agent-runners/{type}/profiles` with correct payload
- [ ] Test: loading profiles from API populates form fields
- [ ] Test: error state renders when API fails
- [ ] Verify TypeScript type-check clean
- [ ] Verify build succeeds

**Dependencies**
- [ ] Task 1 must be complete

**References**
- `docs/agent-runners2/step-04-plan.md` -- Task 6

**Functionality (Expected Outcomes)**
- [ ] All new frontend tests pass
- [ ] All existing frontend tests continue to pass

**Final Verification (Proof of Completion)**
- [ ] `npx vitest run` passes all tests
- [ ] `npx vite build` succeeds
