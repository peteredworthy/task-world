"""Shared code for OpenHands agent variants.

Contains the executor classes, metrics extraction, prompt building,
and callback registry used by both the local and Docker OpenHands agents.

SDK type definitions (Action/Observation/ToolDefinition subclasses) must
remain in each agent module because the SDK's DiscriminatedUnionMixin
rejects any subclass whose ``__qualname__`` contains ``<locals>``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from orchestrator.runners.types import (
    ChecklistUpdateCallback,
    ExecutionContext,
    ExecutionMetrics,
    GradeCallback,
    SubmitCallback,
)
from orchestrator.config.enums import ChecklistStatus


# ---------------------------------------------------------------------------
# Callback registry -- stores non-serializable objects that cannot go through
# the SDK's Tool.params (which must be JSON-serializable).  Each execute()
# call registers its callbacks under a unique key, passes that key through
# Tool.params, and the ToolDefinition.create() method looks them up here.
# ---------------------------------------------------------------------------


class CallbackRegistry:
    """Registry for non-serializable callbacks.

    Each ``execute()`` call registers its callbacks under a unique key.
    The ToolDefinition's ``create()`` method retrieves them by key.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def register(
        self,
        key: str,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        loop: asyncio.AbstractEventLoop,
        on_grade: GradeCallback | None = None,
    ) -> None:
        """Register callbacks under the given key."""
        self._store[key] = {
            "on_checklist_update": on_checklist_update,
            "on_submit": on_submit,
            "on_grade": on_grade,
            "loop": loop,
        }

    def get(self, key: str) -> dict[str, Any]:
        """Retrieve callbacks by key. Raises KeyError if not found."""
        return self._store[key]

    def pop(self, key: str) -> dict[str, Any] | None:
        """Remove and return callbacks for the key, or None."""
        return self._store.pop(key, None)


# ---------------------------------------------------------------------------
# Custom tool executor classes -- no SDK imports, fully testable standalone
#
# Each executor accepts an ``observation_factory`` callable that creates the
# SDK Observation object.  The factory is injected at wiring time in execute().
# ---------------------------------------------------------------------------


class GetRequirementsExecutor:
    """Returns the requirement list as text. Pure, synchronous."""

    def __init__(
        self,
        requirements: list[str],
        observation_factory: Any = None,
    ) -> None:
        self._requirements = requirements
        self._make_obs = observation_factory

    def __call__(self, action: Any, conversation: Any = None) -> Any:
        if self._make_obs is None:
            raise RuntimeError("observation_factory not provided")
        return self._make_obs(self.get_requirements_text())

    def get_requirements_text(self) -> str:
        """Get requirements as formatted text (no SDK dependency)."""
        return "\n".join(f"- {req}" for req in self._requirements)


class UpdateChecklistExecutor:
    """Bridges the SDK's synchronous tool call to the async checklist callback.

    When the SDK calls this executor from a worker thread, it uses
    ``run_coroutine_threadsafe`` to invoke the async callback on the
    event loop that owns the orchestrator.
    """

    def __init__(
        self,
        callback: ChecklistUpdateCallback,
        loop: asyncio.AbstractEventLoop,
        observation_factory: Any = None,
    ) -> None:
        self._callback = callback
        self._loop = loop
        self._make_obs = observation_factory

    def __call__(self, action: Any, conversation: Any = None) -> Any:
        req_id: str = action.req_id
        status_str: str = action.status
        note: str | None = getattr(action, "note", None)

        # Validate status
        try:
            status = ChecklistStatus(status_str)
        except ValueError:
            valid = ", ".join(s.value for s in ChecklistStatus)
            raise ValueError(f"Invalid checklist status '{status_str}'. Valid values: {valid}")

        coro = self._callback(req_id, status, note)
        future = asyncio.run_coroutine_threadsafe(  # pyright: ignore[reportUnknownVariableType]
            coro,  # pyright: ignore[reportArgumentType]
            self._loop,
        )
        future.result(timeout=60)  # pyright: ignore[reportUnknownMemberType]

        if self._make_obs is None:
            raise RuntimeError("observation_factory not provided")
        return self._make_obs(f"Updated requirement '{req_id}' to '{status_str}'.")


class SubmitExecutor:
    """Bridges the SDK's synchronous tool call to the async submit callback."""

    def __init__(
        self,
        callback: SubmitCallback,
        loop: asyncio.AbstractEventLoop,
        observation_factory: Any = None,
    ) -> None:
        self._callback = callback
        self._loop = loop
        self._make_obs = observation_factory

    def __call__(self, action: Any, conversation: Any = None) -> Any:
        if self._make_obs is None:
            raise RuntimeError("observation_factory not provided")
        coro = self._callback()
        future = asyncio.run_coroutine_threadsafe(  # pyright: ignore[reportUnknownVariableType]
            coro,  # pyright: ignore[reportArgumentType]
            self._loop,
        )
        try:
            future.result(timeout=60)  # pyright: ignore[reportUnknownMemberType]
        except Exception as e:
            return self._make_obs(f"ERROR submitting: {e}")
        return self._make_obs("Task submitted for verification.")


class SetGradeExecutor:
    """Bridges the SDK's synchronous tool call to the async grade callback."""

    def __init__(
        self,
        callback: GradeCallback,
        loop: asyncio.AbstractEventLoop,
        observation_factory: Any = None,
    ) -> None:
        self._callback = callback
        self._loop = loop
        self._make_obs = observation_factory

    def __call__(self, action: Any, conversation: Any = None) -> Any:
        req_id: str = action.req_id
        grade: str = action.grade
        grade_reason: str | None = getattr(action, "grade_reason", None)

        # Validate grade
        valid_grades = ["A", "B", "C", "D", "F"]
        if grade not in valid_grades:
            raise ValueError(f"Invalid grade '{grade}'. Valid values: {', '.join(valid_grades)}")

        if self._make_obs is None:
            raise RuntimeError("observation_factory not provided")
        coro = self._callback(req_id, grade, grade_reason)
        future = asyncio.run_coroutine_threadsafe(  # pyright: ignore[reportUnknownVariableType]
            coro,  # pyright: ignore[reportArgumentType]
            self._loop,
        )
        try:
            future.result(timeout=60)  # pyright: ignore[reportUnknownMemberType]
        except Exception as e:
            return self._make_obs(f"ERROR setting grade: {e}")
        return self._make_obs(f"Set grade '{grade}' on requirement '{req_id}'.")


class ValidateRoutineExecutor:
    """Validates a routine YAML file on the host and returns errors.

    Runs synchronously — no async callback needed.  The ``worktree_path``
    is used to resolve relative file paths.
    """

    def __init__(
        self,
        worktree_path: str,
        observation_factory: Any = None,
    ) -> None:
        self._worktree_path = worktree_path
        self._make_obs = observation_factory

    def __call__(self, action: Any, conversation: Any = None) -> Any:
        if self._make_obs is None:
            raise RuntimeError("observation_factory not provided")

        routine_path: str = getattr(action, "routine_path", "")
        if not routine_path:
            return self._make_obs("ERROR: routine_path is required")

        return self._make_obs(self.validate(routine_path))

    def validate(self, routine_path: str) -> str:
        """Validate a routine YAML and return a human-readable result."""
        from pathlib import Path

        import yaml

        abs_path = Path(self._worktree_path) / routine_path
        if not abs_path.exists():
            return f"ERROR: File not found: {routine_path}"

        try:
            with open(abs_path) as f:
                raw: Any = yaml.safe_load(f)
        except yaml.YAMLError as e:
            return f"YAML parse error: {e}"

        if raw is None:
            return "ERROR: File is empty"

        # Unwrap optional `routine:` wrapper
        if isinstance(raw, dict) and "routine" in raw and len(raw) == 1:  # pyright: ignore[reportUnknownArgumentType]
            raw: Any = raw["routine"]  # pyright: ignore[reportUnknownVariableType]

        try:
            from orchestrator.config.models import RoutineConfig

            RoutineConfig.model_validate(raw)
        except Exception as e:
            # Format pydantic errors into actionable feedback
            error_str = str(e)
            # Truncate very long error messages
            if len(error_str) > 3000:
                error_str = error_str[:3000] + "\n... (truncated)"
            return f"VALIDATION FAILED:\n{error_str}"

        return f"VALID: {routine_path} passes schema validation."


# ---------------------------------------------------------------------------
# Metrics extraction -- shared between local and Docker agents
# ---------------------------------------------------------------------------


def extract_metrics(conversation: Any, duration_ms: int = 0) -> ExecutionMetrics:
    """Extract token usage and action count metrics from the conversation.

    Args:
        conversation: The OpenHands conversation object after execution.
        duration_ms: Wall-clock execution time in milliseconds (measured by caller).
    """
    try:
        stats = conversation.conversation_stats
        if stats is None:
            return ExecutionMetrics(duration_ms=duration_ms)

        usage_map = stats.usage_to_metrics
        total_read = 0
        total_write = 0
        total_cache = 0

        for _model_name, metrics in usage_map.items():
            if metrics.accumulated_token_usage is not None:
                total_read += metrics.accumulated_token_usage.prompt_tokens
                total_write += metrics.accumulated_token_usage.completion_tokens
                total_cache += metrics.accumulated_token_usage.cache_read_tokens

        # Try to count actions from conversation state
        num_actions = 0
        try:
            state = getattr(conversation, "state", None)
            if state is not None:
                events = getattr(state, "events", None)
                if events is not None:
                    # Count Action-type events (tool calls)
                    for event in events:
                        cls_name = type(event).__name__
                        if "Action" in cls_name and "Message" not in cls_name:
                            num_actions += 1
        except Exception:
            pass  # Action counting is best-effort

        return ExecutionMetrics(
            tokens_read=total_read,
            tokens_write=total_write,
            tokens_cache=total_cache,
            duration_ms=duration_ms,
            num_actions=num_actions,
        )
    except Exception:
        logging.getLogger(__name__).warning(
            "Failed to extract metrics from conversation", exc_info=True
        )
        return ExecutionMetrics(duration_ms=duration_ms)


# ---------------------------------------------------------------------------
# Prompt building -- shared between local and Docker agents
# ---------------------------------------------------------------------------


def build_openhands_prompt(context: ExecutionContext, is_verifier: bool = False) -> str:
    """Build the full prompt with requirements and tool instructions.

    Args:
        context: Execution context with prompt and requirements.
        is_verifier: If True, includes grading tools for verifier phase.
    """
    requirements_text = "\n".join(f"- {req}" for req in context.requirements)
    workflow_action = (
        "Perform only oversight/documentation/API operations. Do not implement source or test changes."
        if context.work_mode == "oversight"
        else "Implement each requirement."
    )
    git_section = (
        "## Git Workflow\n"
        "Before submitting, commit only allowed oversight artifacts:\n"
        "- Allowed paths are task-requested documentation/metadata such as "
        "`docs/super-parent/` and `.mcp.json`\n"
        "- Do not edit or commit source code, tests, dependency files, lockfiles, migrations, or UI files.\n"
        "- Always use `git --no-pager` for git commands.\n"
        if context.work_mode == "oversight"
        else "## Git Workflow\n"
        "Before submitting, commit your changes to git:\n"
        "- Stage changes: `git add <files>`\n"
        "- Commit with a descriptive message: `git commit -m 'Description of changes'`\n"
        "- Always use `git --no-pager` for git commands.\n"
    )

    if is_verifier:
        return (
            f"{context.prompt}\n\n"
            f"## Requirements\n{requirements_text}\n\n"
            "## Orchestrator Integration (Verifier)\n"
            "You are connected to an orchestrator. Your role is to VERIFY the builder's work.\n\n"
            "### Required Workflow\n"
            "1. Review the code changes made by the builder.\n"
            "2. Grade EVERY requirement using **orc_set_grade**.\n"
            "3. After grading all requirements, call **orc_submit** to complete verification.\n"
            "4. Grades: A (excellent), B (good), C (adequate), D (poor), F (failing)\n\n"
            "### Available Tools\n"
            "- **orc_get_requirements**()\n"
            "  Returns all checklist items with their current status and grades.\n\n"
            "- **orc_set_grade**(req_id, grade, grade_reason?)\n"
            "  Set a grade on a requirement.\n"
            "  - req_id: The requirement ID (e.g. 'R-01', 'R-02')\n"
            "  - grade: One of 'A', 'B', 'C', 'D', 'F'\n"
            "  - grade_reason: Optional explanation for the grade\n"
            "  Example: orc_set_grade('R-01', 'A', 'Well implemented')\n\n"
            "- **orc_submit**()\n"
            "  Complete the verification after grading all requirements.\n\n"
            "### Terminal Tips\n"
            "- ALWAYS use `git --no-pager` for every git command to avoid pager hangs.\n"
            "- For long output, pipe through `| head -80` to limit lines.\n"
            "- To view the builder's changes:\n"
            "  `git --no-pager show HEAD --stat` then `git --no-pager diff HEAD~1 -- <file>`\n"
            "- NEVER run bare `git diff`, `git log`, or `git show` without --no-pager."
        )

    return (
        f"{context.prompt}\n\n"
        f"## Requirements\n{requirements_text}\n\n"
        "## Orchestrator Integration\n"
        "You are connected to an orchestrator that tracks your progress. "
        "Use the tools below to report your work.\n\n"
        "### Required Workflow\n"
        "1. Read the requirements above carefully.\n"
        f"2. {workflow_action}\n"
        "3. After completing each requirement, call **orc_update_checklist** "
        "to mark it 'done'.\n"
        "4. Once ALL requirements are addressed, call **orc_submit** to submit.\n"
        "5. All CRITICAL requirements must be 'done' before submission succeeds.\n\n"
        "### Available Tools\n"
        "- **orc_get_requirements**()\n"
        "  Returns all checklist items with their current status and grades.\n"
        "  Call this first to see the exact requirement IDs.\n\n"
        "- **orc_update_checklist**(req_id, status, note?)\n"
        "  Mark a requirement as done, blocked, or not_applicable.\n"
        "  - req_id: The requirement ID (e.g. 'R-01', 'R-02')\n"
        "  - status: 'done', 'blocked', or 'not_applicable'\n"
        "  - note: Optional explanation\n"
        "  Example: orc_update_checklist('R-01', 'done')\n\n"
        "- **orc_submit**()\n"
        "  Submit your work for verification by a reviewer.\n"
        "  Only call this after addressing all requirements.\n"
        "  Submission will fail if any CRITICAL requirement is not 'done'.\n\n"
        "### Terminal Tips\n"
        "- ALWAYS use `git --no-pager` for every git command to avoid pager hangs.\n"
        "- For long output, pipe through `| head -80` to limit lines.\n"
        "- NEVER run bare `git diff`, `git log`, or `git show` without --no-pager.\n\n"
        f"{git_section}\n"
        "## File Exploration Guidelines\n"
        "- NEVER re-read a file you have already read in this session.\n"
        "- If you catch yourself about to read the same file again, stop and use your existing knowledge.\n"
        "- Each file read consumes context — be selective and avoid redundant reads.\n\n"
        "## Container Awareness\n"
        "- You may be running inside a Docker container.\n"
        "- The workspace is mounted at the configured working directory.\n"
        "- External network access may be limited depending on the sandbox configuration.\n"
    )


# ---------------------------------------------------------------------------
# Built-in tool registration
# ---------------------------------------------------------------------------

# Tool registry mapping short names to SDK module paths
OPENHANDS_TOOL_IMPORTS: dict[str, str] = {
    "terminal": "openhands.tools.terminal.definition",
    "file_editor": "openhands.tools.file_editor.definition",
    "browser": "openhands.tools.browser_use.definition",
    "glob": "openhands.tools.glob.definition",
    "grep": "openhands.tools.grep.definition",
}

DEFAULT_OPENHANDS_TOOLS: list[str] = ["terminal", "file_editor"]

_registered_tool_sets: set[frozenset[str]] = set()


def register_builtin_tools(tool_names: list[str] | None = None) -> None:
    """Import built-in tool modules to trigger their self-registration.

    Only imports the requested tools. Idempotent per unique tool set.

    Args:
        tool_names: List of tool short names to register.
            Defaults to DEFAULT_OPENHANDS_TOOLS.
    """
    import importlib

    names = tool_names or DEFAULT_OPENHANDS_TOOLS
    key = frozenset(names)
    if key in _registered_tool_sets:
        return

    for name in names:
        module_path = OPENHANDS_TOOL_IMPORTS.get(name)
        if module_path is not None:
            importlib.import_module(module_path)

    _registered_tool_sets.add(key)
