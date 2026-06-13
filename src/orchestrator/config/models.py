"""Pydantic configuration models for routines, steps, and tasks."""

import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, model_validator

from orchestrator.config.enums import (
    Complexity,
    GateType,
    ModelProfile,
    Priority,
    StepType,
)

logger = logging.getLogger(__name__)


@dataclass
class NudgerConfig:
    """Configuration for the nudger.

    Attributes:
        output_timeout: Time without output before considering agent stuck.
        nudge_interval: Minimum time between nudges.
        max_nudges: Maximum nudges before kill.
        nudge_message: Message sent to nudge the agent.
    """

    output_timeout: timedelta = timedelta(seconds=60)
    nudge_interval: timedelta = timedelta(seconds=30)
    max_nudges: int = 3
    nudge_message: str = "Please continue or call orchestrator tools to submit."


class EnvFileSpec(BaseModel):
    """Declares a file to be managed outside git."""

    relative_path: str
    promote_on_success: bool = False


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

    @model_validator(mode="after")
    def _reject_pipes(self) -> "AutoVerifyItemConfig":
        """Reject commands that use shell pipes.

        In a shell pipeline the exit code comes from the LAST command, so
        ``pytest ... | tail -5`` always returns 0 even when pytest fails.
        The auto-verify runner already captures the last N lines of output
        (via tail_lines), so piping through tail/head is unnecessary.
        Rewrite the command to avoid pipes entirely.
        """
        # Match a pipe operator ( | ) that is not part of || (logical OR).
        # We look for ` | ` or `|` preceded/followed by non-pipe chars,
        # but exclude content inside quotes to avoid false positives on
        # regex alternation like grep "a|b".
        raw = self.cmd

        # Strip quoted strings before checking for pipes
        stripped = re.sub(r"""(['"]).*?\1""", "", raw)
        # Now check for pipe: a | that is not part of ||
        if re.search(r"(?<!\|)\|(?!\|)", stripped):
            raise ValueError(
                f"Auto-verify command must not contain shell pipes — the exit "
                f"code of earlier commands is silently lost. The runner already "
                f"captures the last N lines of output via tail_lines.\n"
                f"  Problematic command: {raw}\n"
                f"Rewrite without pipes. For example:\n"
                f"  BAD:  uv run pytest tests/ -q 2>&1 | tail -5\n"
                f"  GOOD: uv run pytest tests/ -q\n"
                f"  BAD:  ls *.md | wc -l | awk '{{if ($1>=1) exit 0; else exit 1}}'\n"
                f"  GOOD: ls *.md >/dev/null 2>&1"
            )
        return self

    @model_validator(mode="after")
    def _reject_worktree_paths(self) -> "AutoVerifyItemConfig":
        """Reject commands that contain hardcoded worktree paths.

        Auto-verify commands run with cwd set to the run's worktree, so all
        paths should be relative.  Hardcoded worktree paths like
        ``/path/to/worktrees/r25/src/...`` break when the worktree number
        changes (e.g. after a server restart recreates the worktree).
        """
        raw = self.cmd
        if re.search(r"/worktrees/r\d+", raw):
            raise ValueError(
                f"Auto-verify command must not contain hardcoded worktree paths — "
                f"the worktree number can change between runs.  Auto-verify "
                f"commands run with cwd set to the worktree root, so use "
                f"relative paths instead.\n"
                f"  Problematic command: {raw}\n"
                f"Rewrite with relative paths. For example:\n"
                f"  BAD:  grep -q 'foo' /path/to/worktrees/r25/src/main.py\n"
                f"  GOOD: grep -q 'foo' src/main.py\n"
                f"  BAD:  cd /path/to/worktrees/r25/ui && npx tsc --noEmit\n"
                f"  GOOD: cd ui && npx tsc --noEmit"
            )
        return self


class AutoVerifyConfig(BaseModel):
    """Auto-verification configuration."""

    items: list[AutoVerifyItemConfig] = Field(default_factory=lambda: [])
    tail_lines: int = 20


class FanOutConfig(BaseModel):
    """Configuration for fan-out task execution."""

    input_glob: str
    output_pattern: str
    per_item_prompt: str
    shared_context: list[str] = Field(default_factory=list)
    max_attempts: int = 4
    max_concurrent: int = 4
    max_turns: int | None = None
    auto_verify: AutoVerifyConfig | None = None


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


DEFAULT_SUMMARIZE_MODEL = "claude-haiku-4-5-20251001"


class ContextSource(BaseModel):
    """Configuration for context from an artifact."""

    artifact: str  # Path pattern (supports {{variables}})
    as_name: str | None = Field(default=None, alias="as")  # Variable name in context
    required: bool = True
    section: str | None = None  # Extract specific section
    max_tokens: int | None = None  # Limit for this artifact
    summarize: bool = False  # Summarize artifact content before injecting
    critical: str | None = None  # Description of critical aspects to preserve in summary
    summarize_model: str | None = None  # Override default summarization model


# Alias for clarity when used as context_from config
ContextFromConfig = ContextSource


class TaskConfig(BaseModel):
    """A task within a step."""

    id: str
    title: str
    task_context: str = ""
    work_mode: Literal["implementation", "oversight"] = "implementation"
    complexity: Complexity = Complexity.STANDARD
    profile: ModelProfile | None = None
    builder_agent: str | None = None
    verifier_agent: str | None = None
    available_tools: list[str] | None = None
    mcp_servers: list["MCPServerConfig"] | None = None
    model_overrides: dict[str, dict[str, str]] | None = None
    requirements: list[RequirementConfig] = Field(default_factory=lambda: [])
    auto_verify: AutoVerifyConfig = Field(default_factory=AutoVerifyConfig)
    verifier: VerifierConfig = Field(default_factory=VerifierConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    artifacts: list[ArtifactSpec] = Field(default_factory=lambda: [])
    context_from: list[ContextSource] = Field(default_factory=lambda: [])
    fan_out: FanOutConfig | None = None
    script: str | None = None

    @model_validator(mode="after")
    def _validate_task_config(self) -> "TaskConfig":
        """Validate task configuration: mode exclusivity and verification."""
        # Validate fan_out, script, and task_context are mutually exclusive.
        if self.fan_out is not None:
            if self.task_context != "":
                raise ValueError(
                    f"Task '{self.id}': 'fan_out' and 'task_context' are mutually exclusive."
                )
            if self.script is not None:
                raise ValueError(
                    f"Task '{self.id}': 'fan_out' and 'script' are mutually exclusive."
                )
        if self.script is not None:
            if self.task_context != "":
                raise ValueError(
                    f"Task '{self.id}': 'script' and 'task_context' are mutually exclusive."
                )

        # Auto-generate auto_verify items for required context_from sources.
        # This catches missing input files deterministically at auto-verify time
        # rather than leaving it to LLM grading (which may hallucinate or
        # contradict itself about whether missing files are acceptable).
        existing_av_ids = {item.id for item in self.auto_verify.items}
        for source in self.context_from:
            if not source.required:
                continue
            av_id = f"context_from_exists_{source.as_name or source.artifact}"
            if av_id in existing_av_ids:
                continue
            self.auto_verify.items.append(
                AutoVerifyItemConfig(
                    id=av_id,
                    cmd=f"test -f {source.artifact}",
                    must=True,
                )
            )
            existing_av_ids.add(av_id)

        # Warn when task has no auto_verify items and no verifier rubric.
        has_auto_verify = bool(self.auto_verify.items)

        # Auto-generate rubric from requirements when rubric is empty.
        if not self.verifier.rubric and self.requirements:
            self.verifier.rubric = [
                RubricItemConfig(
                    id=req.id,
                    text=f"Does the implementation satisfy: {req.desc}?",
                )
                for req in self.requirements
            ]

        has_rubric = bool(self.verifier.rubric)

        if not has_auto_verify and not has_rubric:
            logger.debug(
                "Task '%s' ('%s') has no auto_verify items and no verifier rubric. "
                "The verifier will have no criteria to grade against.",
                self.id,
                self.title,
            )
        elif has_rubric and self.requirements:
            req_ids = {req.id for req in self.requirements}
            for item in self.verifier.rubric:
                if item.id not in req_ids:
                    logger.debug(
                        "Task '%s' ('%s'): rubric item '%s' does not match any "
                        "requirement id %s. If this is a composite item (e.g. 'R1-R3'), "
                        "consider splitting into per-requirement rubric items.",
                        self.id,
                        self.title,
                        item.id,
                        sorted(req_ids),
                    )
        return self


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


class ChildRoutineRefConfig(BaseModel):
    """Legacy child routine reference for planner-chain translation."""

    routine: str
    label: str | None = None


class MCPServerConfig(BaseModel):
    """Configuration for an external MCP server available during a step."""

    name: str
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    auth_token_env: str | None = None
    cwd: Literal["worktree"] | None = None
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
        if self.cwd is not None and not has_cmd:
            raise ValueError("MCPServerConfig 'cwd' is only valid for command-based servers")
        return self


class StepCondition(BaseModel):
    """Condition for step execution."""

    when: str | None = None
    repeat_for: str | None = None


class StepConfig(BaseModel):
    """A step within a routine."""

    id: str
    kind: Literal["planner"] | None = None
    file: str | None = None
    title: str | None = None
    step_context: str | None = None
    builder_agent: str | None = None
    verifier_agent: str | None = None
    gate: GateConfig | None = None
    tasks: list[TaskConfig] = Field(default_factory=lambda: [])
    transitions: StepTransitions | None = None
    type: StepType = StepType.STANDARD
    dry_run: DryRunConfig | None = None
    child_routines: list[ChildRoutineRefConfig] = Field(default_factory=lambda: [])
    available_tools: list[str] | None = None
    mcp_servers: list[MCPServerConfig] | None = None
    step_auto_verify: list[AutoVerifyItemConfig] = Field(default_factory=lambda: [])
    condition: StepCondition | None = None

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

    @model_validator(mode="after")
    def _validate_file_exclusivity(self) -> "StepConfig":
        """If file is set, no other step fields may be set (except id)."""
        if self.file is not None:
            overlapping: list[str] = []
            if self.title is not None:
                overlapping.append("title")
            if self.kind is not None:
                overlapping.append("kind")
            if self.tasks:
                overlapping.append("tasks")
            if self.step_context is not None:
                overlapping.append("step_context")
            if self.gate is not None:
                overlapping.append("gate")
            if self.transitions is not None:
                overlapping.append("transitions")
            if self.type != StepType.STANDARD:
                overlapping.append("type")
            if self.dry_run is not None:
                overlapping.append("dry_run")
            if self.child_routines:
                overlapping.append("child_routines")
            if self.available_tools is not None:
                overlapping.append("available_tools")
            if self.mcp_servers is not None:
                overlapping.append("mcp_servers")
            if self.step_auto_verify:
                overlapping.append("step_auto_verify")
            if overlapping:
                raise ValueError(
                    f"Step '{self.id}' sets 'file' along with other fields "
                    f"({', '.join(overlapping)}). When 'file' is specified, no other "
                    f"step fields may be set."
                )
        else:
            if self.title is None:
                raise ValueError(
                    f"Step '{self.id}' must have a 'title' (or use 'file' to reference an external step)."
                )
            if self.child_routines and self.kind != "planner":
                raise ValueError(
                    f"Step '{self.id}' declares 'child_routines' but is not a planner step."
                )
            if not self.tasks and self.kind != "planner":
                raise ValueError(
                    f"Step '{self.id}' must have at least one task (or use 'file' to reference an external step)."
                )
        return self


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
    builder_agent: str | None = None
    verifier_agent: str | None = None
    execution_mode: Literal["legacy", "graph"] | None = None
    env_files: list[EnvFileConfig] = Field(default_factory=lambda: [])
    clarifications: ClarificationsConfig | None = None
    strict_validation: bool = False
    planner_generation_budget: int = Field(default=8, ge=0)

    @model_validator(mode="before")
    @classmethod
    def reject_inheritance_in_routine(cls, data: Any) -> Any:  # noqa: ANN401
        """Reject ref/use in routine data and nested steps."""
        _check_value_recursive(data)
        return data  # type: ignore[no-any-return]

    @model_validator(mode="after")
    def _enforce_strict_validation(self) -> "RoutineConfig":
        """When strict_validation=True, reject any task with no verification."""
        if not self.strict_validation:
            return self
        unverified: list[str] = []
        for step in self.steps:
            for task in step.tasks:
                has_auto_verify = bool(task.auto_verify.items)
                has_rubric = bool(task.verifier.rubric)
                if not has_auto_verify and not has_rubric:
                    unverified.append(f"{step.id}/{task.id}")
        if unverified:
            raise ValueError(
                f"strict_validation=True: the following tasks have no auto_verify items "
                f"and no verifier rubric: {', '.join(unverified)}"
            )
        return self
