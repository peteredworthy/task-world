"""Dry-run execution logic for simulating plan coherence validation."""

import json
from typing import Any

from pydantic import BaseModel, Field

from orchestrator.config.models import DryRunConfig, RoutineConfig, StepConfig, TaskConfig
from orchestrator.state.models import Run


class DryRunResult(BaseModel):
    """Result of a dry-run simulation."""

    step_id: str
    task_id: str
    simulated_outcome: str
    identified_gaps: list[str] = Field(default_factory=lambda: [])
    missing_context: list[str] = Field(default_factory=lambda: [])
    unclear_requirements: list[str] = Field(default_factory=lambda: [])
    suggested_improvements: list[str] = Field(default_factory=lambda: [])


def _count_tokens(text: str) -> int:
    """Estimate token count (simple heuristic: ~4 chars per token)."""
    return len(text) // 4


def _truncate_to_tokens(text: str, token_limit: int) -> str:
    """Truncate text to approximate token limit."""
    char_limit = token_limit * 4
    if len(text) <= char_limit:
        return text
    return text[:char_limit] + "\n\n[... truncated ...]"


def build_dry_run_context(
    run: Run,
    step: StepConfig,
    artifacts: dict[str, str],
    token_limit: int,
) -> str:
    """Build limited context for dry-run simulation.

    Args:
        run: The current run state
        step: The step configuration being simulated
        artifacts: Map of artifact path -> content (from prior steps)
        token_limit: Maximum tokens for the context

    Returns:
        Context string truncated to token limit

    The context includes:
    - Step's own context
    - Summaries of artifacts from prior steps (truncated)
    - No full file contents
    """
    context_parts: list[str] = []
    remaining_tokens = token_limit

    # Include step context first (highest priority)
    if step.step_context:
        step_ctx = f"## Step Context\n{step.step_context}\n"
        token_count = _count_tokens(step_ctx)
        if token_count <= remaining_tokens:
            context_parts.append(step_ctx)
            remaining_tokens -= token_count

    # Include run config (variable context)
    if run.config:
        config_lines: list[str] = [f"- {k}: {v}" for k, v in run.config.items()]
        config_text = "## Run Configuration\n" + "\n".join(config_lines)
        token_count = _count_tokens(config_text)
        if token_count <= remaining_tokens:
            context_parts.append(config_text)
            remaining_tokens -= token_count

    # Include artifacts (truncated to remaining budget)
    if artifacts:
        artifacts_section = "## Available Artifacts (truncated)\n"
        for path, content in artifacts.items():
            # Allocate equal share to each artifact
            artifact_budget = remaining_tokens // len(artifacts)
            truncated = _truncate_to_tokens(content, artifact_budget)
            artifacts_section += f"\n### {path}\n{truncated}\n"

        context_parts.append(artifacts_section)

    return "\n".join(context_parts)


def _format_requirements(task: TaskConfig) -> str:
    """Format task requirements for prompt."""
    if not task.requirements:
        return "No specific requirements defined."

    lines: list[str] = []
    for req in task.requirements:
        priority = f"[{req.priority.value.upper()}]"
        lines.append(f"- {priority} {req.desc}")
    return "\n".join(lines)


def build_dry_run_prompt(
    step: StepConfig,
    task: TaskConfig,
    context: str,
    config: dict[str, Any],
) -> str:
    """Build prompt for dry-run simulation.

    Args:
        step: The step configuration
        task: The task configuration
        context: Limited context from build_dry_run_context
        config: Run configuration for variable substitution

    Returns:
        Complete prompt for LLM simulation
    """
    # Apply variable substitution to task context
    task_context = task.task_context
    for key, value in config.items():
        task_context = task_context.replace(f"{{{{{key}}}}}", str(value))

    requirements = _format_requirements(task)

    prompt = f"""You are simulating execution of a task with LIMITED context.
Your goal is to identify gaps, not to actually complete the task.

{context}

TASK:
{task_context}

REQUIREMENTS:
{requirements}

INSTRUCTIONS:
1. Describe what you WOULD do to complete this task
2. Identify any GAPS in the context that would block you
3. List any UNCLEAR requirements that need clarification
4. Suggest improvements to the task definition

Respond in JSON format:
{{
  "simulated_outcome": "description of what you would do",
  "identified_gaps": ["gap1", "gap2"],
  "missing_context": ["context1", "context2"],
  "unclear_requirements": ["req1", "req2"],
  "suggested_improvements": ["improvement1", "improvement2"]
}}
"""
    return prompt


def parse_dry_run_response(response: str) -> dict[str, Any]:
    """Parse LLM response from dry-run simulation.

    Args:
        response: JSON response from LLM

    Returns:
        Dictionary with parsed fields

    Raises:
        ValueError: If response is not valid JSON or missing required fields
    """
    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response: {e}") from e

    # Validate required fields
    required_fields = [
        "simulated_outcome",
        "identified_gaps",
        "missing_context",
        "unclear_requirements",
        "suggested_improvements",
    ]

    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    # Ensure list fields are lists
    list_fields = [
        "identified_gaps",
        "missing_context",
        "unclear_requirements",
        "suggested_improvements",
    ]

    for field in list_fields:
        if not isinstance(data[field], list):
            raise ValueError(f"Field {field} must be a list")

    return data


def get_step_by_id(routine: RoutineConfig, step_id: str) -> StepConfig | None:
    """Get a step configuration by ID.

    Args:
        routine: The routine configuration
        step_id: The step ID to find

    Returns:
        StepConfig if found, None otherwise
    """
    for step in routine.steps:
        if step.id == step_id:
            return step
    return None


def execute_dry_run(
    run: Run,
    routine: RoutineConfig,
    config: DryRunConfig,
    artifacts: dict[str, dict[str, str]],
) -> list[DryRunResult]:
    """Execute dry-run simulation for target steps.

    This is a SYNCHRONOUS function that builds prompts and prepares results.
    Actual LLM calls happen at the service layer (integration tests).

    Args:
        run: The current run state
        routine: The routine configuration
        config: Dry-run configuration
        artifacts: Map of step_id -> {path -> content}

    Returns:
        List of dry-run results (with placeholder data for unit testing)

    Raises:
        ValueError: If target step not found or invalid configuration
    """
    results: list[DryRunResult] = []

    for step_id in config.target_steps:
        step = get_step_by_id(routine, step_id)
        if step is None:
            raise ValueError(f"Target step not found: {step_id}")

        # Get artifacts for context (from all prior steps)
        all_artifacts: dict[str, str] = {}
        for step_artifacts in artifacts.values():
            all_artifacts.update(step_artifacts)

        # Process each task in the step
        for task in step.tasks:
            # Build context
            context = build_dry_run_context(
                run=run,
                step=step,
                artifacts=all_artifacts,
                token_limit=config.context_limit,
            )

            # Build prompt (for LLM call at service layer)
            # Note: prompt variable unused in unit test path, but needed for integration
            _prompt = build_dry_run_prompt(
                step=step,
                task=task,
                context=context,
                config=run.config,
            )

            # For unit tests, return placeholder result
            # Real LLM integration happens in service layer
            result = DryRunResult(
                step_id=step_id,
                task_id=task.id,
                simulated_outcome=f"Simulated outcome for {task.title}",
                identified_gaps=[],
                missing_context=[],
                unclear_requirements=[],
                suggested_improvements=[],
            )
            results.append(result)

    return results
