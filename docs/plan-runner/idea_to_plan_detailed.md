# Detailed Planning Process (Reference Document)

This document provides the **context and details** of the planning process. It is designed for **setting expectations and providing guidance**, not as the execution checklist. The stripped-down execution map should be used for step-by-step adherence.

---

## Purpose
The purpose of this process is to take an initial idea or prompt and transform it into a structured, executable plan that can be reliably carried out by both humans and LLMs. The detailed plan ensures:
- Functionality is the measure of success.
- Every step delivers progressive usability.
- Verification and contracts are defined early.
- The system remains runnable after each task.

---

## Core Principles
- **Functionality over description**: Plans define what the system can do now and what it will be able to do after, not just actions taken.
- **Progressive usability**: Each step must provide a minimum viable functionality (verifiable via CLI, API, or script).
- **Contract-first**: Each step defines a functional contract, including end-to-end verification methods.
- **Structured verification**: Small tasks use automated checks; steps use functionality checklists and end-to-end testing.
- **Runnable system**: After every task, the system and its tests must remain runnable, with `uv run pre-commit run --all-files` passing cleanly.

---

## Research & Context Collection
Research is a reusable activity that supports multiple stages. Its purpose is to eliminate unknowns before they cause issues during planning or execution.

**Outputs:**
- `docs/[feature]/context/*.md` (patterns, integrations, APIs, error handling, testing, DB, config)
- Updates to `plan-changes.md`, `design-questions.md`, `CONFLICTS.md`

**When to use:**
- Whenever uncertainties or gaps are discovered in Stages 1, 3, 4, or 5.

**Activities:**
- Review existing patterns and integrations.
- Verify error handling, testing standards, database usage, and configurations.
- Validate availability and correctness of APIs.
- Record changes and prepend new questions where required.

---

## Stages Overview

### Stage 1 – Initial Plan
- **Goal:** Form a high-level but structured plan that exposes gaps early.
- **Outputs:** `plan.md`, `intent.md`, `design-questions.md`, `architecture.md`.
- **Details:**
  - Summarize originating intent.
  - Break down into iterative, stepwise plan.
  - Draft design questions highlighting unknowns.
  - Draft architecture file with technology choices, interactions, and class hierarchies.

### Stage 2 – Human Review
- **Goal:** Align plan and intent with user expectations.
- **Actor:** 🚫 Human-only.
- **Outputs:** Feedback-marked documents (`[HUMAN]` notes).
- **Details:**
  - Reviewer clarifies open questions.
  - Reviewer flags decision points.
  - Gating: LLM must STOP and present a concise summary for the human. Proceed only after human feedback is explicitly committed (see `docs/idea_to_plan/HUMAN_REVIEW_TEMPLATE.md`).

### Stage 3 – Plan Refinement
- **Goal:** Integrate human feedback and surface conflicts.
- **Outputs:** Updated docs, possible `CONFLICTS.md`.
- **Details:**
  - Update plan, intent, architecture.
  - Resolve conflicts explicitly.
  - Use research if needed to clarify uncertainties.
  - Gating: If any open design questions or conflicts remain, RETURN to Stage 2 (Human Review). Only proceed to Stage 4 when these are resolved.

### Stage 4 – Step Planning
- **Goal:** Define detailed contracts and verification per step.
- **Outputs:** `step-xx-plan.md`, `plan-changes.md`.
- **Details:**
  - For each step, define purpose, contract (inputs/outputs/errors), verification tests.
  - Reference Research & Context outputs.
  - Update design questions and conflicts as needed.
  - Gating: If new conflicts or unresolved decisions are discovered, RETURN to Stage 2 and re-run subsequent stages.

### Stage 5 – Task Breakdown
- **Goal:** Produce atomic tasks for execution.
- **Outputs:** `steps-step-xx.md`.
- **Details:**
  - Tasks must be atomic (<5 files, <500 lines).
  - Ensure system remains runnable with passing tests.
  - Front-load grepping/tooling tasks.
  - Include context references directly in task descriptions.
  - Reference `docs/step-files.md`
  - Gating: If new conflicts emerge during breakdown, RETURN to Stage 2.

### Stage 6 – Dry Run
- **Goal:** Simulate execution to identify gaps.
- **Outputs:** Dry-run notes, improvement updates.
- **Details:**
  - LLM simulates carrying out each task with limited context.
  - Document expected outcomes.
  - Update tasks based on deltas.

### Stage 7 – Final Check
- **Goal:** Ensure consistency and completeness.
- **Outputs:** Verified step files.
- **Details:**
  - Cross-check against intent, plan, design-questions, plan-changes.

### Stage 8 – Final Plan Review
- **Goal:** Summarize the entire plan.
- **Outputs:** Plan summary.
- **Details:**
  - Provide holistic overview of how intent is satisfied.

### Stage 9 – Execution
- **Goal:** Implement tasks as defined.
- **Outputs:** Completed and verified tasks.
- **Details:**
  - Execute tasks in order.
  - Maintain runnable, test-passing system.

---

## Supporting References
- `docs/architecture.md` – System overview.
- `docs/architecture/**` – Module-specific guides.
- `docs/tests.md` – Testing standards.
- `docs/step-files.md` – Step file format & checklist.

---

## Generated Artifacts
- `docs/[feature]/plan.md` – Implementation plan.
- `docs/[feature]/intent.md` – Original request.
- `docs/[feature]/design-questions.md` – Clarifying questions.
- `docs/[feature]/implementation-cheat-sheet.md` – APIs, utilities, conventions.
- `docs/[feature]/context/*.md` – Background information.
- `docs/[feature]/step-xx-plan.md` – Detailed step planning.
- `docs/[feature]/steps/step-xx.md` – Task instructions for execution.
- `docs/[feature]/CONFLICTS.md` – Recorded conflicts and resolutions.
- `docs/[feature]/plan-changes.md` – Summary of plan modifications.
