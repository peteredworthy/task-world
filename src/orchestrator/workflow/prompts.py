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


@dataclass
class VerifierPrompt:
    """Generated prompt for the verifier phase."""

    system: str
    user: str
    requirements: list[str] = field(default_factory=lambda: [])
    rubric: list[str] = field(default_factory=lambda: [])
    submission_instructions: str = ""


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
) -> BuilderPrompt:
    """Generate builder prompt with fresh context.

    Applies variable substitution ({{key}} -> value) and includes
    previous feedback if this is a revision attempt.
    """
    task_context = get_task_context(task_config, model)

    # Simple variable substitution
    for key, value in config.items():
        task_context = task_context.replace(f"{{{{{key}}}}}", str(value))

    requirements = [f"- {req.desc}" for req in task_config.requirements]

    # Get previous feedback if this is a revision
    previous_feedback: str | None = None
    if task_state.attempts:
        last_attempt = task_state.attempts[-1]
        if last_attempt.verifier_comment:
            previous_feedback = last_attempt.verifier_comment

    system = (
        "You are a skilled software developer. Complete the task according to the requirements.\n"
        "Mark each requirement as done when completed using the provided tools."
    )

    user = f"## Task\n{task_context}\n\n## Requirements\n" + "\n".join(requirements)

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
    )


def generate_verifier_prompt(
    task_config: TaskConfig,
    task_state: TaskState,
) -> VerifierPrompt:
    """Generate verifier prompt with fresh context."""
    requirements = [f"- {req.desc}" for req in task_config.requirements]
    rubric = [f"- {item.text}" for item in task_config.verifier.rubric]

    template = task_config.verifier.submission_template
    submission_instructions = (
        f"Grade each requirement using scale: {', '.join(template.grade_scale)}\n"
        f"Provide reason if grade below {template.require_reason_if_below}.\n"
        f"Provide remediation if grade below {template.require_remediation_if_below}."
    )

    system = (
        "You are a code reviewer. Evaluate the work against requirements.\n"
        "Be thorough but fair. Provide actionable feedback for any issues."
    )

    rubric_section = "\n".join(rubric) if rubric else "Evaluate based on requirements only."

    user = (
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
    )
