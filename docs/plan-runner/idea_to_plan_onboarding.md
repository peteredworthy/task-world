# Onboarding Guide: Using the Planning Documents

This guide explains how to use the two complementary documents:

- **Detailed Planning Process (Reference Document)** – provides context, principles, and detailed explanations.
- **Stripped-Down Execution Map** – provides a stage-by-stage checklist for LLMs or humans to follow.

It also describes how these fit together and what a new contributor (human or LLM) should do first.

---

## Purpose of the Documents

- The **Reference Document** is for understanding the philosophy and intent of the process. It ensures that everyone shares the same mental model of planning, research, refinement, and execution.
- The **Execution Map** is for day-to-day use. It is optimized for adherence: short checklists, inputs, outputs, and NEXT pointers.

Both are required: the Reference provides *why* and *what*, the Execution Map provides *how*.

---

## First Steps for a New Contributor

1. **Copy the Execution Map** into `docs/[feature]/execution-map.md`. This makes it available alongside the feature’s artifacts.
2. **Review the Reference Document** to understand the principles:
   - Functionality over description
   - Progressive usability
   - Contract-first planning
   - Structured verification
   - Runnable system requirement
3. **Confirm Understanding**: Be clear about context visibility limits (LLM can only see step header + current task).

---

## How to Use the Documents Together

- **Start with the Execution Map** when working: follow the stage checklists strictly.
- **Refer to the Reference Document** whenever you need context or detailed guidance (e.g., what “Contract-first” means, or how research artifacts should look).
- **Switch between them**: If the Execution Map feels unclear, the Reference Document will usually clarify.

---

## When Research is Needed

Research & Context Collection is **not a stage**, but a reusable activity. It supports Stages 1, 3, 4, and 5.
- Execution Map → reminds you when to perform research.
- Reference Document → explains what to gather (patterns, APIs, error handling, testing, etc.).

---

## Future Expansion

This onboarding guide will grow to include:
- How steps are formed and what makes a good step.
- Example step plans (`step-xx-plan.md`).
- Example task breakdowns (`steps-step-xx.md`).
- Common pitfalls and how to avoid them.

---

## Key Reminder for LLMs

- Do **not** attempt to perform Stage 2 (Human Review). This is explicitly human-only.
- Always respect the **priority of information sources**: Verified reality → Prompt → 🚫 Human feedback → Intent → Design-questions → Plan → Steps.
- After every task, system must remain runnable and clean (`uv run pre-commit run --all-files`).

