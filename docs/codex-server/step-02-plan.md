# Step 02 Plan: Types and Detector Support

## Purpose

Add codex-server agent types and detection/config metadata so users can discover and select local/remote Codex variants through existing API and workflow entrypoints.

## Prerequisites

- Step 01 complete: integration contract and compatibility policy are locked.

## Functional Contract

### Inputs

- Step 01 integration contract.
- Existing enums and detector behavior:
  - `src/orchestrator/config/enums.py`
  - `src/orchestrator/agents/detector.py`
  - `src/orchestrator/agents/types.py`
  - `src/orchestrator/api/routers/agents.py`
  - `src/orchestrator/api/schemas/runs.py`

### Outputs

- New `AgentType` members:
  - `codex_server`
  - `codex_server_remote`
- `ToolDetector` options/config schema entries for both new types, including local/remote specific fields (endpoint/base URL, model, callback transport, auth token source, timeouts).
- `GET /api/agents` and run serialization compatibility for new types without breaking existing agent options.

### Errors

- Invalid enum migration or schema mismatch -> serialization/deserialization failures in API models.
- Detector reports an unavailable Codex option with missing required config guidance -> configuration dead-end for users.
- Missing compatibility constraints in detector metadata -> unsupported server versions appear as valid targets.

## Tasks

1. Extend `AgentType` and any display mappings to include both Codex variants.
2. Update `ToolDetector` availability logic and config field definitions for both variants.
3. Verify API agent-listing and run schema serialization include new types safely.

## Verification

### Auto-Verify

- [ ] Unit tests for `ToolDetector` availability and config schema pass for local/remote Codex cases.
- [ ] Unit/integration tests covering enum serialization in API schemas pass.
- [ ] `GET /api/agents` includes both Codex options with correct availability metadata.

### Manual Verify

- [ ] Inspect API response for new agent options and confirm required config fields are clear and complete.
- [ ] Validate unavailable state messaging provides actionable install/config hints.

## Context & References

- `docs/codex-server/step-01-plan.md`
- `src/orchestrator/config/enums.py`
- `src/orchestrator/agents/detector.py`
- `src/orchestrator/api/routers/agents.py`
- `src/orchestrator/api/schemas/runs.py`
