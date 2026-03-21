# Idea-to-Plan Process Reference

This document provides the principles and context behind the idea-to-plan planning process. It is designed for setting expectations and providing guidance — the routine YAML defines the execution steps.

---

## Core Principles

- **Functionality over description**: Plans define what the system can do now and what it will be able to do after, not just actions taken.
- **Progressive usability**: Each step must provide a minimum viable functionality (verifiable via CLI, API, or script).
- **Contract-first**: Each step defines a functional contract, including end-to-end verification methods.
- **Structured verification**: Small tasks use automated checks; steps use functionality checklists and end-to-end testing. Verification must prove behavior, not just presence — a check that passes when the implementation is a stub is not a verification, it is a false gate. See `docs/plan-runner/step-files.md §4` for guidance on distinguishing presence checks from behavioral checks.
- **Runnable system**: After every task, the system and its tests must remain runnable, with `uv run pre-commit run --all-files` passing cleanly.

---

## Global Rules

- Follow the core principles above in all planning and execution decisions.
- Respect information priority: Verified reality > Prompt > Human feedback (provided externally) > Intent > Design-questions > Plan > Steps.
- Keep tasks atomic (<5 files, <500 lines).
- System must stay runnable and pass linting/tests after each task.
- Prepend new questions to design-questions.md; mark resolutions inline.

---

## Research & Context Collection

Research is a reusable activity that supports multiple stages. Its purpose is to eliminate unknowns before they cause issues during planning or execution.

**Outputs:**
- `docs/[feature]/context/*.md` (patterns, integrations, APIs, error handling, testing, DB, config)
- Updates to `plan-changes.md`, `design-questions.md`, `CONFLICTS.md`

**When to use:**
- Whenever uncertainties or gaps are discovered during planning or task breakdown.

**Activities:**
- Review existing patterns and integrations.
- Verify error handling, testing standards, database usage, and configurations.
- Validate availability and correctness of APIs.
- Record changes and prepend new questions where required.

---

## Human Review Gates

Human review stages require the LLM to STOP and present a concise summary. Proceed only after human feedback is explicitly committed. The LLM must not generate or simulate human feedback.

If any open design questions or conflicts remain after refinement, return to human review. Only proceed when these are resolved.

---

## Generated Artifacts

- `docs/[feature]/intent.md` — Original request and completion criteria.
- `docs/[feature]/plan.md` — Implementation plan with ordered milestones.
- `docs/[feature]/architecture.md` — Technology choices, interactions, class hierarchies.
- `docs/[feature]/design-questions.md` — Clarifying questions and resolutions.
- `docs/[feature]/step-xx.md` — Detailed step planning with contracts.
- `docs/[feature]/steps/step-xx.md` — Task instructions for execution (expanded from step plans).
- `docs/[feature]/dry-run-notes.md` — Simulation results and gap analysis.
- `docs/[feature]/verification-report.md` — Cross-check findings.
- `docs/[feature]/plan-summary.md` — Holistic overview.
- `docs/[feature]/CONFLICTS.md` — Recorded conflicts and resolutions.
- `docs/[feature]/plan-changes.md` — Summary of plan modifications.
