# Step Plan: Model Profiles (Frontend)

## Purpose

Add model profile configuration UI to each Agent Runner card, allowing users to set which model each runner uses for each cognitive profile (Architect, Designer, Coder, Summarizer).

## Prerequisites

- **Step 02 (M2)** must be complete: frontend uses `AgentRunner` naming
- **Step 03 (M3)** must be complete: backend API serves profile endpoints

## Functional Contract

### Inputs

- `GET /api/model-profiles` response: list of profile names and descriptions
- `GET /api/agent-runners/{type}/model-profile-defaults` response: current profile-to-model mapping
- User input: model string selection/entry per profile per runner

### Outputs

- "Model Profiles" section on each `AgentRunnerCard` with 4 fields (Architect, Designer, Coder, Summarizer)
- Each field is a combobox with `allow_custom` for entering arbitrary model strings
- Save triggers `PUT /api/agent-runners/{type}/model-profile-defaults` to persist to backend
- Profile-to-model mappings displayed on runner cards

### Error Cases

- Backend API unavailable -> show error state, allow retry
- Save fails (validation error) -> display error message, keep form state
- Empty model string for a profile -> treated as "use runner default" (cleared from overrides)

## Tasks

1. Add "Model Profiles" section to `AgentRunnerCard` with 4 model selector fields
2. Fetch model default data from `GET /api/agent-runners/{type}/model-profile-defaults` on card load
3. Wire save to `PUT /api/agent-runners/{type}/model-profile-defaults` endpoint
4. Display current profile-to-model mappings on runner cards
5. Add combobox component with custom model entry support
6. Write frontend tests for profile UI components

## Verification Approach

### Auto-Verify

- Frontend tests: profile section renders with 4 fields
- Frontend tests: saving profiles calls correct API endpoint
- Frontend tests: loading profiles populates form fields
- TypeScript type-check clean
- Build succeeds

### Manual Verification

- Navigate to Agent Runners page -- each runner card shows profile section
- Set a model for CODER profile on CLI_SUBPROCESS runner -- save persists
- Reload page -- saved model appears in the field
- Clear a model field -- save removes the override

## Context & References

- Plan: `docs/agent-runners2/plan.md` -- M4 specification
- Architecture: `docs/agent-runners2/architecture.md` -- `AgentRunnerOption.profile_defaults` field
- Profile API: `GET /api/model-profiles`, `GET/PUT /api/agent-runners/{type}/model-profile-defaults`
- UI pattern: combobox with allow_custom matches existing model selector patterns
