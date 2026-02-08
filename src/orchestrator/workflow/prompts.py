"""Prompt generation for builder and verifier phases (pure functions)."""

from dataclasses import dataclass, field
from typing import Any

from orchestrator.config.models import TaskConfig
from orchestrator.state.models import TaskState


@dataclass
class BuilderPrompt:
    """Generated prompt for the builder phase."""

    system: str
    user: str
    task_context: str
    requirements: list[str] = field(default_factory=lambda: [])
    previous_feedback: str | None = None
    step_context: str | None = None
    clarifications_path: str | None = None


@dataclass
class VerifierPrompt:
    """Generated prompt for the verifier phase."""

    system: str
    user: str
    requirements: list[str] = field(default_factory=lambda: [])
    rubric: list[str] = field(default_factory=lambda: [])
    submission_instructions: str = ""
    step_context: str | None = None
    clarifications_path: str | None = None


def get_task_context(task_config: TaskConfig, model: str | None = None) -> str:
    """Get task context, applying model overrides if present."""
    if model and task_config.model_overrides:
        override = task_config.model_overrides.get(model, {})
        if "task_context" in override:
            return override["task_context"]
    return task_config.task_context


def generate_builder_prompt(
    task_config: TaskConfig,
    task_state: TaskState,
    config: dict[str, Any],
    model: str | None = None,
    step_context: str | None = None,
    clarifications_path: str | None = None,
) -> BuilderPrompt:
    """Generate builder prompt with fresh context.

    Applies variable substitution ({{key}} -> value) and includes
    previous feedback if this is a revision attempt. If step_context
    is provided, it is included before the task context. If clarifications_path
    is provided, it is included after step_context but before task details.
    """
    task_context = get_task_context(task_config, model)

    # Simple variable substitution
    for key, value in config.items():
        task_context = task_context.replace(f"{{{{{key}}}}}", str(value))

    # Apply variable substitution to step_context if present
    resolved_step_context: str | None = None
    if step_context is not None:
        resolved_step_context = step_context
        for key, value in config.items():
            resolved_step_context = resolved_step_context.replace(f"{{{{{key}}}}}", str(value))

    requirements = [f"- {req.desc}" for req in task_config.requirements]

    # Get previous feedback if this is a revision
    previous_feedback: str | None = None
    if task_state.attempts:
        # Look for the latest non-empty feedback so revision attempts can carry it forward.
        for attempt in reversed(task_state.attempts):
            if attempt.verifier_comment:
                previous_feedback = attempt.verifier_comment
                break

    system = (
        "You are a skilled software developer working within an orchestrated workflow.\n\n"
        "## How This Workflow Works\n"
        "You are in the BUILDER phase. Your job is to implement the task, then report your progress.\n\n"
        "## Your Workflow\n"
        "1. Read and understand the requirements listed below.\n"
        "2. Implement the code changes needed to satisfy each requirement.\n"
        "3. As you complete each requirement, mark it done using the orchestrator tools "
        "(update checklist with the requirement ID, e.g. 'R-01', and status 'done').\n"
        "4. If a requirement is not applicable, mark it 'not_applicable' with a note explaining why.\n"
        "5. If a requirement is blocked by something outside your control, mark it 'blocked' with a note.\n"
        "6. Before submitting for verification, commit your changes to git:\n"
        "   - Stage all relevant changes with: git add <files>\n"
        "   - Commit with a descriptive message summarizing your implementation\n"
        "   - Example: git commit -m 'Implement authentication system with login and signup'\n"
        "7. Once all requirements are addressed and changes are committed, submit your work for verification.\n\n"
        "## Important\n"
        "- You MUST update the checklist for each requirement before submitting.\n"
        "- All CRITICAL requirements must be marked 'done' before submission will succeed.\n"
        "- You MUST commit your changes to git before submitting for verification.\n"
        "- The verifier will review the committed code and grade each requirement.\n"
        "- If the verifier finds issues, you may be asked to revise (with feedback provided)."
    )

    user = ""
    if resolved_step_context is not None:
        user += f"## Step Context\n{resolved_step_context}\n\n"

    if clarifications_path is not None:
        user += (
            "## Clarifications\n\n"
            "Previous clarifications from the human are recorded in:\n"
            f"  {clarifications_path}\n\n"
            "Review this file for context on decisions made. If you need additional\n"
            "clarification, use the request_clarification tool.\n\n"
        )

    user += f"## Task\n{task_context}\n\n## Requirements\n" + "\n".join(requirements)

    if previous_feedback:
        user += (
            f"\n\n## Previous Feedback (Revision Required)\n{previous_feedback}\n\n"
            "Address the feedback above while maintaining all other requirements."
        )

    return BuilderPrompt(
        system=system,
        user=user,
        task_context=task_context,
        requirements=requirements,
        previous_feedback=previous_feedback,
        step_context=resolved_step_context,
        clarifications_path=clarifications_path,
    )


def generate_verifier_prompt(
    task_config: TaskConfig,
    task_state: TaskState,
    step_context: str | None = None,
    clarifications_path: str | None = None,
) -> VerifierPrompt:
    """Generate verifier prompt with fresh context.

    If step_context is provided, it is included before the requirements.
    If clarifications_path is provided, it is included after step_context
    but before requirements.
    """
    requirements = [f"- {req.desc}" for req in task_config.requirements]
    rubric = [f"- {item.text}" for item in task_config.verifier.rubric]

    template = task_config.verifier.submission_template
    submission_instructions = (
        f"Grade each requirement using scale: {', '.join(template.grade_scale)}\n"
        f"Provide reason if grade below {template.require_reason_if_below}.\n"
        f"Provide remediation if grade below {template.require_remediation_if_below}."
    )

    system = (
        "You are a code reviewer working within an orchestrated workflow.\n\n"
        "## How This Workflow Works\n"
        "You are in the VERIFIER phase. A builder has implemented the task. "
        "Your job is to review the work and grade each requirement.\n\n"
        "## Your Workflow\n"
        "1. Review the code changes made by the builder.\n"
        "2. Evaluate each requirement against the rubric (if provided).\n"
        "3. For each requirement, assign a grade using the orchestrator tools "
        "(set grade with the requirement ID, e.g. 'R-01', a grade letter, "
        "and a reason explaining your assessment).\n"
        "4. After grading ALL requirements, complete the verification.\n\n"
        "## Grading Guidelines\n"
        "- A: Excellent - fully meets the requirement with high quality\n"
        "- B: Good - meets the requirement with minor issues\n"
        "- C: Adequate - partially meets the requirement, needs improvement\n"
        "- D: Poor - significant gaps in meeting the requirement\n"
        "- F: Failing - requirement not met\n\n"
        "## Important\n"
        "- You MUST grade every CRITICAL and EXPECTED requirement.\n"
        "- Provide a clear reason for any grade below the passing threshold.\n"
        "- Include specific, actionable remediation guidance for failing items.\n"
        "- Be thorough but fair. Evaluate what was actually built, not style preferences."
    )

    rubric_section = "\n".join(rubric) if rubric else "Evaluate based on requirements only."

    user = ""
    if step_context is not None:
        user += f"## Step Context\n{step_context}\n\n"

    if clarifications_path is not None:
        user += (
            "## Clarifications\n\n"
            "Previous clarifications from the human are recorded in:\n"
            f"  {clarifications_path}\n\n"
            "Review this file for context on decisions made. If you need additional\n"
            "clarification, use the request_clarification tool.\n\n"
        )

    user += (
        "## Requirements to Verify\n"
        + "\n".join(requirements)
        + f"\n\n## Rubric Questions\n{rubric_section}"
        + f"\n\n## Submission Instructions\n{submission_instructions}"
    )

    return VerifierPrompt(
        system=system,
        user=user,
        requirements=requirements,
        rubric=rubric,
        submission_instructions=submission_instructions,
        step_context=step_context,
        clarifications_path=clarifications_path,
    )
