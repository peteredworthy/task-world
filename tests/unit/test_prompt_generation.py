"""Tests for prompt generation."""

from orchestrator.config.models import (
    RequirementConfig,
    RubricItemConfig,
    SubmissionTemplateConfig,
    TaskConfig,
    VerifierConfig,
)
from orchestrator.state.models import Attempt, TaskState
from orchestrator.workflow.prompts import (
    generate_builder_prompt,
    generate_verifier_prompt,
    get_task_context,
)


def _task_config(
    task_context: str = "Implement {{feature}}",
    model_overrides: dict[str, dict[str, str]] | None = None,
    rubric: list[RubricItemConfig] | None = None,
) -> TaskConfig:
    verifier = VerifierConfig()
    if rubric:
        verifier = VerifierConfig(rubric=rubric)
    return TaskConfig(
        id="T-01",
        title="Test Task",
        task_context=task_context,
        model_overrides=model_overrides,
        requirements=[
            RequirementConfig(id="R1", desc="Create the feature"),
            RequirementConfig(id="R2", desc="Add tests"),
        ],
        verifier=verifier,
    )


def _task_state(verifier_comment: str | None = None) -> TaskState:
    state = TaskState(id="task-1", config_id="T-01")
    if verifier_comment:
        state.attempts.append(Attempt(attempt_num=1, verifier_comment=verifier_comment))
    return state


# --- get_task_context ---


def test_get_task_context_default() -> None:
    config = _task_config(task_context="Default context")
    assert get_task_context(config) == "Default context"


def test_get_task_context_no_model() -> None:
    config = _task_config(
        task_context="Default context",
        model_overrides={"claude": {"task_context": "Claude context"}},
    )
    assert get_task_context(config, model=None) == "Default context"


def test_get_task_context_model_override_applied() -> None:
    config = _task_config(
        task_context="Default context",
        model_overrides={"claude": {"task_context": "Claude context"}},
    )
    assert get_task_context(config, model="claude") == "Claude context"


def test_get_task_context_model_not_in_overrides() -> None:
    config = _task_config(
        task_context="Default context",
        model_overrides={"claude": {"task_context": "Claude context"}},
    )
    assert get_task_context(config, model="gpt4") == "Default context"


# --- generate_builder_prompt ---


def test_builder_prompt_basic() -> None:
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(config, state, {"feature": "auth"})

    assert "auth" in prompt.task_context  # Variable substituted
    assert "{{feature}}" not in prompt.task_context
    assert len(prompt.requirements) == 2
    assert "Create the feature" in prompt.requirements[0]
    assert "software developer" in prompt.system.lower()
    assert prompt.previous_feedback is None


def test_builder_prompt_variable_substitution() -> None:
    config = _task_config(task_context="Build {{name}} for {{team}}")
    state = _task_state()
    prompt = generate_builder_prompt(config, state, {"name": "widget", "team": "platform"})

    assert "widget" in prompt.task_context
    assert "platform" in prompt.task_context
    assert "{{name}}" not in prompt.task_context


def test_builder_prompt_model_override() -> None:
    config = _task_config(
        task_context="Default context",
        model_overrides={"claude": {"task_context": "Claude-specific for {{feature}}"}},
    )
    state = _task_state()
    prompt = generate_builder_prompt(config, state, {"feature": "auth"}, model="claude")

    assert "Claude-specific for auth" in prompt.task_context


def test_builder_prompt_previous_feedback() -> None:
    config = _task_config()
    state = _task_state(verifier_comment="Fix the error handling")
    prompt = generate_builder_prompt(config, state, {"feature": "auth"})

    assert prompt.previous_feedback == "Fix the error handling"
    assert "Previous Feedback" in prompt.user
    assert "Fix the error handling" in prompt.user


def test_builder_prompt_no_feedback_on_first_attempt() -> None:
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(config, state, {"feature": "auth"})

    assert prompt.previous_feedback is None
    assert "Previous Feedback" not in prompt.user


# --- generate_verifier_prompt ---


def test_verifier_prompt_basic() -> None:
    config = _task_config()
    state = _task_state()
    prompt = generate_verifier_prompt(config, state)

    assert len(prompt.requirements) == 2
    assert "code reviewer" in prompt.system.lower()
    assert "Grade each requirement" in prompt.submission_instructions


def test_verifier_prompt_with_rubric() -> None:
    config = _task_config(
        rubric=[
            RubricItemConfig(id="Q1", text="Is the code well-structured?"),
            RubricItemConfig(id="Q2", text="Are edge cases handled?"),
        ],
    )
    state = _task_state()
    prompt = generate_verifier_prompt(config, state)

    assert len(prompt.rubric) == 2
    assert "well-structured" in prompt.rubric[0]
    assert "Rubric Questions" in prompt.user


def test_verifier_prompt_empty_rubric() -> None:
    config = _task_config()
    state = _task_state()
    prompt = generate_verifier_prompt(config, state)

    assert len(prompt.rubric) == 0
    assert "Evaluate based on requirements only" in prompt.user


def test_verifier_prompt_submission_instructions() -> None:
    config = TaskConfig(
        id="T-01",
        title="Test",
        task_context="Context",
        requirements=[RequirementConfig(id="R1", desc="Test")],
        verifier=VerifierConfig(
            submission_template=SubmissionTemplateConfig(
                grade_scale=["A", "B", "C"],
                require_reason_if_below="A",
                require_remediation_if_below="B",
            ),
        ),
    )
    state = _task_state()
    prompt = generate_verifier_prompt(config, state)

    assert "A, B, C" in prompt.submission_instructions
    assert "reason if grade below A" in prompt.submission_instructions
    assert "remediation if grade below B" in prompt.submission_instructions
