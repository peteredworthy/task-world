# Step 4: Model Profiles (Frontend)

Add model profile configuration UI to each Agent Runner card, allowing users to set which model each runner uses for each cognitive profile (Architect, Designer, Coder, Summarizer).

## Intent Verification
**Original Intent**: Provide a UI for configuring Agent Runner Model Defaults (see `docs/agent-runners2/intent.md` -- "Model Profiles" section).
**Functionality to Produce**:
- "Model Profiles" section on each `AgentRunnerCard` with 4 model selector fields
- Save/load wired to `PUT/GET /api/agent-runners/{type}/model-profile-defaults`
- Profile-to-model mappings displayed on runner cards

**Final Verification Criteria**:
- Frontend tests pass for profile UI components
- TypeScript type-check clean, build succeeds
- Each runner card shows profile configuration section

---

## Task 1: Add Profile Types and API Functions

**Description**: Add TypeScript types for model profiles and create API functions for fetching/saving Agent Runner Model Defaults.

**Implementation Plan (Do These Steps)**
- [ ] Add types to `ui/src/types/agentRunners.ts` (or a new `profiles.ts`):
  ```typescript
  export interface ModelProfile {
    name: string;
    description: string;
  }
  export interface AgentRunnerModelDefaults {
    agent_runner_type: string;
    model_profile_defaults: Record<string, string>;  // profile_name -> model_string
  }
  ```
- [ ] Add `profile_defaults` field to `AgentRunnerOption` type: `profile_defaults: Record<string, string>`
- [ ] Create API functions:
  - `fetchModelProfiles(): Promise<ModelProfile[]>` -- GET /api/model-profiles
  - `fetchAgentRunnerModelDefaults(type: string): Promise<AgentRunnerModelDefaults>` -- GET /api/agent-runners/{type}/model-profile-defaults
  - `saveAgentRunnerModelDefaults(type: string, defaults: AgentRunnerModelDefaults): Promise<void>` -- PUT /api/agent-runners/{type}/model-profile-defaults

**Dependencies**
- [ ] Step 2 must be complete (frontend uses `AgentRunner` naming)
- [ ] Step 3 must be complete (backend profile API exists)

**References**
- `docs/agent-runners2/architecture.md` -- `AgentRunnerOption.profile_defaults`, schema definitions
- `docs/agent-runners2/plan.md` -- M4 steps 1-3

**Constraints**
- Follow existing API call patterns in the codebase

**Functionality (Expected Outcomes)**
- [ ] Profile types are importable and type-check clean
- [ ] API functions correctly target the profile endpoints

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes

---

## Task 2: Add Profile Configuration UI to Runner Cards

**Description**: Add a "Model Profiles" section to each `AgentRunnerCard` with model selector fields for each profile and save functionality.

**Implementation Plan (Do These Steps)**
- [ ] Add a "Model Profiles" collapsible section to `AgentRunnerCard`
- [ ] Fetch available profiles from `GET /api/model-profiles` (or use static list of 4)
- [ ] Fetch current Agent Runner Model Defaults from `GET /api/agent-runners/{type}/model-profile-defaults` on card load
- [ ] Render 4 model selector fields (one per profile: Architect, Designer, Coder, Summarizer)
- [ ] Each field is a combobox/input allowing custom model strings
- [ ] Wire save button to `PUT /api/agent-runners/{type}/model-profile-defaults`
- [ ] Show loading/error states during API operations
- [ ] Clear a model field = remove the override (use runner default)

**Dependencies**
- [ ] Task 1 must be complete (types and API functions exist)

**References**
- `docs/agent-runners2/plan.md` -- M4 steps 1-4
- `docs/agent-runners2/architecture.md` -- `AgentRunnerOption.profile_defaults` field
- UI pattern: combobox with allow_custom matches existing model selector patterns

**Constraints**
- Do not modify runner card functionality beyond adding profile section
- Empty model field means "use runner default" -- do not send empty strings to API

**Functionality (Expected Outcomes)**
- [ ] Each runner card shows 4 profile model selector fields
- [ ] Saved profiles persist via API and reload correctly
- [ ] Clearing a field removes the override

**Final Verification (Proof of Completion)**
- [ ] `npx tsc --noEmit` passes
- [ ] `npx vite build` succeeds

---

## Task 3: Write Frontend Tests for Profile UI

**Description**: Write tests for the profile configuration UI on runner cards.

**Implementation Plan (Do These Steps)**
- [ ] Write tests verifying profile section renders with 4 fields on runner card
- [ ] Write tests verifying saving profiles calls the correct API endpoint with correct payload
- [ ] Write tests verifying loading profiles populates form fields
- [ ] Write tests verifying error states are displayed
- [ ] Run full frontend test suite to verify no regressions

**Dependencies**
- [ ] Task 2 must be complete (UI implemented)

**References**
- `docs/agent-runners2/plan.md` -- M4 step 6
- Existing test patterns in `ui/src/` test files

**Constraints**
- Follow existing test patterns (vitest + testing-library or similar)

**Functionality (Expected Outcomes)**
- [ ] Profile UI tests cover render, save, load, and error scenarios
- [ ] All frontend tests pass

**Final Verification (Proof of Completion)**
- [ ] `npx vitest run` -- all tests pass
- [ ] `npx tsc --noEmit` passes
- [ ] `npx vite build` succeeds
