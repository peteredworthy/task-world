# W5 Core Payload Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the remaining W5 core raw payload maps for requirement revisions, support evidence, and oversight decisions with typed projection models while preserving public JSON output.

**Architecture:** Follow the existing `CandidateProjection` and `VerifierVerdictProjection` pattern. Projection state stores Pydantic models; checkpoint serialization dumps JSON dictionaries; checkpoint restore validates and drops malformed entries.

**Tech Stack:** Python 3.12, Pydantic v2, pytest via `uv run`.

## Global Constraints

- Use `uv run` for all Python commands.
- Do not stage or commit; the workspace already has unrelated unstaged changes.
- Do not replace structural maps such as leases, edges, input bindings, or gates in this pass.
- Preserve existing external dict output for projection helper functions and checkpoints.
- Tests use real projection functions and event envelopes; no mocks, patches, or monkeypatching.

---

### Task 1: Requirement Revision Projection

**Files:**
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Test: `tests/unit/test_graph_projections.py`

**Interfaces:**
- Produces: `RequirementRevisionProjection`
- Produces: `GraphProjection["requirement_revisions"]: dict[str, RequirementRevisionProjection]`

- [ ] **Step 1: Write failing tests**

Add a test that reduces `requirement_revision_recorded`, asserts the stored value is `RequirementRevisionProjection`, and asserts `model_dump(mode="json")` matches the existing dict shape.

- [ ] **Step 2: Verify red**

Run: `uv run pytest tests/unit/test_graph_projections.py::test_requirement_revision_projection_uses_typed_payload -q`
Expected: FAIL/ERROR because `RequirementRevisionProjection` is not defined/exported.

- [ ] **Step 3: Implement minimal typed model and state conversion**

Add a Pydantic model with required `requirement_id`, `version_id`, `change_classification`, `requires_authority`, `position`, and `validation_strengthening`; optional `previous_version_id`, `revision_index`, and `authority_required_reason`. Update recorder, clone, checkpoint dump, and restore helpers.

- [ ] **Step 4: Verify green**

Run: `uv run pytest tests/unit/test_graph_projections.py::test_requirement_revision_projection_uses_typed_payload -q`
Expected: PASS.

### Task 2: Support Evidence Projection

**Files:**
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Test: `tests/unit/test_graph_projections.py`

**Interfaces:**
- Produces: `SupportEvidenceProjection`
- Produces: `GraphProjection["support_evidence"]: dict[str, SupportEvidenceProjection]`

- [ ] **Step 1: Write failing tests**

Add tests for support evidence typed storage, checkpoint round-trip, freshness output compatibility, and malformed checkpoint entry dropping.

- [ ] **Step 2: Verify red**

Run: `uv run pytest tests/unit/test_graph_projections.py::test_support_evidence_projection_checkpoint_round_trips_typed_payload -q`
Expected: FAIL/ERROR because `SupportEvidenceProjection` is not defined/exported.

- [ ] **Step 3: Implement minimal typed model and state conversion**

Add a Pydantic model with required `support_id`, `evidence_id`, `requirement_id`, `requirement_version_id`, `status`, and `position`; optional `stale_reason` and `confidence`. Update recorder, stale-marker, freshness helpers, clone, checkpoint dump, and restore helpers.

- [ ] **Step 4: Verify green**

Run: `uv run pytest tests/unit/test_graph_projections.py::test_support_evidence_projection_checkpoint_round_trips_typed_payload tests/unit/test_graph_projections.py::test_malformed_requirement_and_support_checkpoint_entries_are_dropped -q`
Expected: PASS.

### Task 3: Oversight Decision Projection

**Files:**
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph/projections.py`
- Modify: `src/orchestrator/graph/__init__.py`
- Test: `tests/unit/test_graph_projections.py`

**Interfaces:**
- Produces: `OversightDecisionProjection`
- Produces: `GraphProjection["oversight_decisions"]: dict[str, OversightDecisionProjection]`

- [ ] **Step 1: Write failing tests**

Add a test that reduces `oversight_decision_recorded`, round-trips through checkpoint serialization, asserts stored values are typed, and verifies appeal aliases still point at the same decision payload.

- [ ] **Step 2: Verify red**

Run: `uv run pytest tests/unit/test_graph_projections.py::test_oversight_decision_projection_checkpoint_round_trips_typed_payload -q`
Expected: FAIL/ERROR because `OversightDecisionProjection` is not defined/exported.

- [ ] **Step 3: Implement minimal typed model and state conversion**

Add a model with required `node_id`, `decision`, and `position`; optional `outcome`, `verdict`, `approved`, `task_region_id`, `candidate_id`, `gate_id`, `appeal_node_id`, `appealed_node_id`, `appeal_type`, `decider`, `scope`, `expires_at`, and `reason`. Update latest decision recording, decision outcome helper, clone, checkpoint dump, and restore helpers.

- [ ] **Step 4: Verify green**

Run: `uv run pytest tests/unit/test_graph_projections.py::test_oversight_decision_projection_checkpoint_round_trips_typed_payload -q`
Expected: PASS.

### Task 4: Final Verification

**Files:**
- Check all modified files.

**Interfaces:**
- Verifies W5 typed payload cleanup and no projection regressions.

- [ ] **Step 1: Run targeted graph projection tests**

Run: `uv run pytest tests/unit/test_graph_projections.py -q`
Expected: PASS.

- [ ] **Step 2: Run payload allowlist guard**

Run: `uv run pytest tests/unit/test_graph_payload_field_allowlists.py -q`
Expected: PASS.

- [ ] **Step 3: Run lint and type checks for touched graph files**

Run: `uv run ruff check src/orchestrator/graph tests/unit/test_graph_projections.py tests/unit/test_graph_payload_field_allowlists.py`
Expected: PASS.

Run: `uv run pyright`
Expected: PASS.
