"""Pydantic configuration models for routines, steps, and tasks."""

from typing import Any, cast

from pydantic import BaseModel, Field, model_validator

from orchestrator.config.enums import GateType, Priority, StepType


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


class GateConfig(BaseModel):
    """Gate configuration for a step or task."""

    type: GateType
    # For human_approval
    approval_prompt: str | None = None
    require_comment: bool = False
    summary_artifact: str | None = None  # Path for summary artifact (human_approval gate)
    # For grade_threshold
    critical_threshold: str = "A"
    expected_threshold: str = "B"


class ArtifactSpec(BaseModel):
    """Expected artifact specification for a task."""

    path: str
    required: bool = True
    track_resolution: bool = False


class ContextSource(BaseModel):
    """Configuration for context from an artifact."""

    artifact: str  # Path pattern (supports {{variables}})
    as_name: str = Field(alias="as")  # Variable name in context
    required: bool = True
    section: str | None = None  # Extract specific section
    max_tokens: int | None = None  # Limit for this artifact


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
    artifacts: list[ArtifactSpec] = Field(default_factory=lambda: [])
    context_from: list[ContextSource] = Field(default_factory=lambda: [])


class TransitionCondition(BaseModel):
    """Condition for a backward transition."""

    condition: str
    target: str
    max_iterations: int = 3
    message: str | None = None


class StepTransitions(BaseModel):
    """Transition configuration for a step."""

    on_complete: str | None = None
    on_condition: list[TransitionCondition] = Field(default_factory=lambda: [])


class DryRunConfig(BaseModel):
    """Configuration for a dry-run step."""

    target_steps: list[str]
    context_limit: int = 4000
    report_path: str


class MCPServerConfig(BaseModel):
    """Configuration for an external MCP server available during a step."""

    name: str
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    auth_token_env: str | None = None
    timeout_seconds: int = 30

    @model_validator(mode="after")
    def _validate_transport(self) -> "MCPServerConfig":
        has_url = self.url is not None
        has_cmd = self.command is not None
        if has_url and has_cmd:
            raise ValueError(
                "MCPServerConfig must have exactly one of 'url' or 'command', not both"
            )
        if not has_url and not has_cmd:
            raise ValueError("MCPServerConfig must have exactly one of 'url' or 'command'")
        return self


class StepConfig(BaseModel):
    """A step within a routine."""

    id: str
    title: str
    step_context: str | None = None
    gate: GateConfig | None = None
    tasks: list[TaskConfig] = Field(min_length=1)
    transitions: StepTransitions | None = None
    type: StepType = StepType.STANDARD
    dry_run: DryRunConfig | None = None
    available_tools: list[str] | None = None
    mcp_servers: list[MCPServerConfig] | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_task_key(cls, data: Any) -> Any:  # noqa: ANN401
        """Accept singular 'task:' as shorthand for 'tasks: [task]'."""
        if isinstance(data, dict):
            d = cast(dict[str, Any], data)
            if "task" in d and "tasks" not in d:
                d["tasks"] = [d.pop("task")]
            elif "task" in data and "tasks" in data:
                raise ValueError("Cannot specify both 'task' and 'tasks' in a step")
        return data  # type: ignore[no-any-return]

    @model_validator(mode="before")
    @classmethod
    def reject_inheritance_in_step(cls, data: Any) -> Any:  # noqa: ANN401
        """Reject ref/use in step data and nested task/tasks."""
        _check_value_recursive(data)
        return data  # type: ignore[no-any-return]


class ClarificationsConfig(BaseModel):
    """Clarifications configuration for a routine."""

    artifact_path: str = "docs/clarifications.md"


class EnvFileConfig(BaseModel):
    """Environment file declaration in routine/project config."""

    path: str
    promote_on_success: bool = False


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
    env_files: list[EnvFileConfig] = Field(default_factory=lambda: [])
    clarifications: ClarificationsConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_inheritance_in_routine(cls, data: Any) -> Any:  # noqa: ANN401
        """Reject ref/use in routine data and nested steps."""
        _check_value_recursive(data)
        return data  # type: ignore[no-any-return]
