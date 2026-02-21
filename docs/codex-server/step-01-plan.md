# Step 01 Plan: Research + Integration Contract

## Purpose

Establish a locked integration contract for Codex app server support so implementation steps can proceed without unresolved interface assumptions. This step defines the supported Codex baseline, callback/tool boundaries, compatibility policy, and release gate criteria.

## Prerequisites

- None.

## Functional Contract

### Inputs

- `docs/codex-server/intent.md`
- `docs/codex-server/plan.md`
- `docs/codex-server/architecture.md`
- `docs/codex-server/clarifications.md`
- Existing orchestrator agent/callback contracts:
  - `src/orchestrator/agents/types.py`
  - `src/orchestrator/agents/openhands_common.py`
  - `src/orchestrator/mcp/tools.py`

### Outputs

- A documented capability and contract baseline for Codex integration, including:
  - Baseline interface: Codex app server docs (`https://developers.openai.com/codex/app-server/`)
  - Remote auth: static API key bearer auth (`Authorization: Bearer <token>`)
  - Callback channel parity requirement: REST and MCP in v1
  - Tool allow-list: `update_checklist`, `grade`, `submit`, `request_clarification`
  - Compatibility target: latest documented Codex app server only
  - Rollout gate: both local and remote variants required for release
- Concrete architecture deltas and open-risk list used as implementation inputs for Steps 2-6.

### Errors

- Missing or contradictory upstream contract details -> raise clarification request and block dependent implementation steps.
- Unsupported tool/transport assumptions discovered during contract review -> record explicit non-go constraints in architecture docs.
- Ambiguous release criteria -> mark rollout decision unresolved and block completion of this step.

## Tasks

1. Consolidate all clarification answers into a single enforceable integration contract.
2. Map Codex server capabilities to orchestrator callback/tool semantics and phase behavior (builder/verifier).
3. Record architecture deltas and unresolved risks as explicit inputs for implementation steps.

## Verification

### Auto-Verify

- [ ] Contract decisions in `docs/codex-server/plan.md` and `docs/codex-server/architecture.md` are internally consistent.
- [ ] Every later step plan (Steps 2-6) references this baseline contract as a prerequisite.

### Manual Verify

- [ ] Human review confirms no unresolved ambiguity for baseline interface, auth model, callback channels, tool scope, compatibility target, and release gate.
- [ ] Human review confirms contract is implementable against current orchestrator architecture without new hidden dependencies.

## Context & References

- `docs/codex-server/clarifications.md`
- `docs/codex-server/plan.md`
- `docs/codex-server/architecture.md`
- `docs/plan-runner/idea_to_plan_stripped.md`
