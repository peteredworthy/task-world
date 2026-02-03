"""Pydantic configuration models for routines, steps, and tasks."""

from typing import Any, cast

from pydantic import BaseModel, Field, model_validator

from orchestrator.config.enums import Priority


def _check_for_inheritance_keys(v: dict[str, Any]) -> None:
    """Reject dicts containing 'ref' or 'use' keys (no inheritance support)."""
    if "ref" in v or "use" in v:
        raise ValueError(
            "Contains 'ref' or 'use'. Inheritance is not supported. Use explicit definitions."
        )


def _check_value_recursive(v: object) -> None:
    """Recursively check for ref/use keys in dicts and lists."""
    if isinstance(v, dict):
        d = cast(dict[str, Any], v)
        _check_for_inheritance_keys(d)
        for val in d.values():
            _check_value_recursive(val)
    elif isinstance(v, list):
        for item in cast(list[object], v):
            _check_value_recursive(item)


class RequirementConfig(BaseModel):
    """A single requirement in a task."""

    id: str
    desc: str
    must: bool = True
    priority: Priority = Priority.CRITICAL


class AutoVerifyItemConfig(BaseModel):
    """A single auto-verify command."""

    id: str
    cmd: str
    must: bool = True


class AutoVerifyConfig(BaseModel):
    """Auto-verification configuration."""

    items: list[AutoVerifyItemConfig] = Field(default_factory=lambda: [])
    tail_lines: int = 20


class RubricItemConfig(BaseModel):
    """A single rubric question for verifier."""

    id: str
    text: str


class SubmissionTemplateConfig(BaseModel):
    """Verifier submission template."""

    grade_scale: list[str] = Field(default=["A", "B", "C", "D", "F"])
    require_reason_if_below: str = "A"
    require_remediation_if_below: str = "B"


class VerifierConfig(BaseModel):
    """Verifier configuration."""

    rubric: list[RubricItemConfig] = Field(default_factory=lambda: [])
    submission_template: SubmissionTemplateConfig = Field(default_factory=SubmissionTemplateConfig)


class RetryConfig(BaseModel):
    """Retry configuration."""

    max_attempts: int = 3


class TaskConfig(BaseModel):
    """A task within a step."""

    id: str
    title: str
    task_context: str
    model_overrides: dict[str, dict[str, str]] | None = None
    requirements: list[RequirementConfig] = Field(default_factory=lambda: [])
    auto_verify: AutoVerifyConfig = Field(default_factory=AutoVerifyConfig)
    verifier: VerifierConfig = Field(default_factory=VerifierConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)


class StepConfig(BaseModel):
    """A step within a routine."""

    id: str
    title: str
    step_context: str | None = None
    tasks: list[TaskConfig] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def reject_inheritance_in_step(cls, data: Any) -> Any:  # noqa: ANN401
        """Reject ref/use in step data and nested task/tasks."""
        _check_value_recursive(data)
        return data  # type: ignore[no-any-return]


class RoutineInputConfig(BaseModel):
    """An input parameter for a routine."""

    name: str
    required: bool = True
    default: object = None
    description: str | None = None


class RoutineConfig(BaseModel):
    """A complete routine definition."""

    id: str
    name: str
    description: str | None = None
    inputs: list[RoutineInputConfig] = Field(default_factory=lambda: [])
    steps: list[StepConfig]

    @model_validator(mode="before")
    @classmethod
    def reject_inheritance_in_routine(cls, data: Any) -> Any:  # noqa: ANN401
        """Reject ref/use in routine data and nested steps."""
        _check_value_recursive(data)
        return data  # type: ignore[no-any-return]
