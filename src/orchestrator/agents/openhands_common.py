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

from orchestrator.agents.types import (
    ChecklistUpdateCallback,
    ExecutionContext,
    ExecutionMetrics,
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
    ) -> None:
        """Register callbacks under the given key."""
        self._store[key] = {
            "on_checklist_update": on_checklist_update,
            "on_submit": on_submit,
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
        coro = self._callback()
        future = asyncio.run_coroutine_threadsafe(  # pyright: ignore[reportUnknownVariableType]
            coro,  # pyright: ignore[reportArgumentType]
            self._loop,
        )
        future.result(timeout=60)  # pyright: ignore[reportUnknownMemberType]

        if self._make_obs is None:
            raise RuntimeError("observation_factory not provided")
        return self._make_obs("Task submitted for verification.")


# ---------------------------------------------------------------------------
# Metrics extraction -- shared between local and Docker agents
# ---------------------------------------------------------------------------


def extract_metrics(conversation: Any) -> ExecutionMetrics:
    """Extract token usage metrics from the conversation stats."""
    try:
        stats = conversation.conversation_stats
        if stats is None:
            return ExecutionMetrics()

        usage_map = stats.usage_to_metrics
        total_read = 0
        total_write = 0
        total_cache = 0

        for _model_name, metrics in usage_map.items():
            if metrics.accumulated_token_usage is not None:
                total_read += metrics.accumulated_token_usage.prompt_tokens
                total_write += metrics.accumulated_token_usage.completion_tokens
                total_cache += metrics.accumulated_token_usage.cache_read_tokens

        return ExecutionMetrics(
            tokens_read=total_read,
            tokens_write=total_write,
            tokens_cache=total_cache,
        )
    except Exception:
        logging.getLogger(__name__).warning(
            "Failed to extract metrics from conversation", exc_info=True
        )
        return ExecutionMetrics()


# ---------------------------------------------------------------------------
# Prompt building -- shared between local and Docker agents
# ---------------------------------------------------------------------------


def build_openhands_prompt(context: ExecutionContext) -> str:
    """Build the full prompt with requirements and tool instructions."""
    requirements_text = "\n".join(f"- {req}" for req in context.requirements)
    return (
        f"{context.prompt}\n\n"
        f"## Requirements\n{requirements_text}\n\n"
        "## Available Orchestrator Tools\n"
        "- **get_requirements**: Returns the list of requirements.\n"
        "- **update_checklist**: Mark a requirement done/blocked/not_applicable. "
        "Parameters: req_id (string), status (string), note (optional string).\n"
        "- **submit**: Submit your work for verification.\n\n"
        "When you complete a requirement, call update_checklist with "
        "the requirement text and status 'done'.\n"
        "When all requirements are complete, call submit."
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
