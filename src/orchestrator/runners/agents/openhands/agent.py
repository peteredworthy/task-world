"""OpenHands agent integration.

Uses the openhands-ai SDK's ``LocalConversation`` to run an agent entirely
in-process.  No remote OpenHands server is required -- only the LLM provider
API key (``OPENAI_API_KEY``).

The SDK import is deferred to a module-level ``try/except`` so that the rest
of the orchestrator works even when ``openhands-ai`` is not installed.

Custom tool executors (GetRequirements, UpdateChecklist, Submit) are defined
in ``openhands_common`` with no SDK imports so they can be unit-tested
independently.  All classes that *subclass* SDK types live at true module
scope (not inside a function) because the SDK's ``DiscriminatedUnionMixin``
rejects any subclass whose ``__qualname__`` contains ``<locals>``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import TYPE_CHECKING, Any

import httpx

from orchestrator.runners.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.workflow.errors import GateBlockedError
from orchestrator.runners.repetition_detector import (
    ActionBudget,
    ActionBudgetConfig,
    ReasoningRepetitionDetector,
    RepetitionAction,
    RepetitionDetector,
    RepetitionDetectorConfig,
)
from orchestrator.runners.quota import HttpQuotaFetcher, QuotaFetcher
from orchestrator.runners.agents.openhands.common import (
    CallbackRegistry,
    GetRequirementsExecutor,
    SubmitExecutor,
    UpdateChecklistExecutor,
    build_openhands_prompt,
    extract_metrics,
    register_builtin_tools,
)
from orchestrator.runners.types import (
    AgentRunnerInfo,
    AgentMetadataCallback,
    AgentQuota,
    ChecklistUpdateCallback,
    EscalationCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    QuotaBucket,
    SubmitCallback,
)
from orchestrator.config.enums import AgentRunnerType

if TYPE_CHECKING:
    from openhands.sdk.conversation.local import LocalConversation as _LocalConversation  # pyright: ignore[reportMissingImports,reportUnknownVariableType]


# ---------------------------------------------------------------------------
# Callback registry instance for local agent
# ---------------------------------------------------------------------------

_callback_registry = CallbackRegistry()


# ---------------------------------------------------------------------------
# SDK type definitions -- module level
#
# All Action, Observation, ToolExecutor, and ToolDefinition subclasses MUST
# live at module level so their __qualname__ does not contain ``<locals>``.
# The SDK's DiscriminatedUnionMixin rejects local classes.
#
# Guarded by try/except so the module loads even without openhands-ai.
# ---------------------------------------------------------------------------

_SDK_AVAILABLE = False

try:
    from openhands.sdk import (  # pyright: ignore[reportUnknownVariableType,reportMissingImports]
        Action as _OHAction,
        Observation as _OHObservation,
        TextContent as _OHTextContent,
        register_tool as _oh_register_tool,  # pyright: ignore[reportUnknownVariableType]
    )
    from openhands.sdk.tool.tool import (  # pyright: ignore[reportUnknownVariableType,reportMissingImports]
        ToolDefinition as _OHToolDefinition,
        ToolExecutor as _OHToolExecutor,
    )

    _SDK_AVAILABLE = True  # pyright: ignore[reportConstantRedefinition]
except ImportError:
    pass


if _SDK_AVAILABLE:
    # --- Action / Observation types ---

    class OrcGetReqAction(_OHAction):  # type: ignore[misc]
        pass

    class OrcGetReqObservation(_OHObservation):  # type: ignore[misc]
        pass

    class OrcUpdateAction(_OHAction):  # type: ignore[misc]
        req_id: str
        status: str
        note: str | None = None

    class OrcUpdateObservation(_OHObservation):  # type: ignore[misc]
        pass

    class OrcSubmitAction(_OHAction):  # type: ignore[misc]
        pass

    class OrcSubmitObservation(_OHObservation):  # type: ignore[misc]
        pass

    class OrcSetGradeAction(_OHAction):  # type: ignore[misc]
        req_id: str
        grade: str
        grade_reason: str | None = None

    class OrcSetGradeObservation(_OHObservation):  # type: ignore[misc]
        pass

    # --- Observation factories ---

    def _obs_get_req(text: str) -> OrcGetReqObservation:  # type: ignore[type-arg]
        return OrcGetReqObservation(content=[_OHTextContent(text=text)])  # type: ignore[call-arg]

    def _obs_update(text: str) -> OrcUpdateObservation:  # type: ignore[type-arg]
        return OrcUpdateObservation(content=[_OHTextContent(text=text)])  # type: ignore[call-arg]

    def _obs_submit(text: str) -> OrcSubmitObservation:  # type: ignore[type-arg]
        return OrcSubmitObservation(content=[_OHTextContent(text=text)])  # type: ignore[call-arg]

    def _obs_set_grade(text: str) -> OrcSetGradeObservation:  # type: ignore[type-arg]
        return OrcSetGradeObservation(content=[_OHTextContent(text=text)])  # type: ignore[call-arg]

    # --- ToolExecutor wrappers (must subclass SDK ABC) ---

    class _GetReqExec(_OHToolExecutor):  # type: ignore[type-arg,misc]
        def __init__(self, inner: GetRequirementsExecutor) -> None:
            self._inner = inner

        def __call__(self, action: Any, conversation: Any = None) -> Any:
            return self._inner(action, conversation)

    class _UpdateExec(_OHToolExecutor):  # type: ignore[type-arg,misc]
        def __init__(self, inner: UpdateChecklistExecutor) -> None:
            self._inner = inner

        def __call__(self, action: Any, conversation: Any = None) -> Any:
            return self._inner(action, conversation)

    class _SubmitExec(_OHToolExecutor):  # type: ignore[type-arg,misc]
        def __init__(self, inner: SubmitExecutor) -> None:
            self._inner = inner

        def __call__(self, action: Any, conversation: Any = None) -> Any:
            return self._inner(action, conversation)

    class _SetGradeExec(_OHToolExecutor):  # type: ignore[type-arg,misc]
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def __call__(self, action: Any, conversation: Any = None) -> Any:
            return self._inner(action, conversation)

    # --- ToolDefinition subclasses ---

    class OrcGetRequirementsTool(
        _OHToolDefinition[OrcGetReqAction, OrcGetReqObservation]  # type: ignore[type-arg]
    ):
        @classmethod
        def create(cls, *args: Any, **kwargs: Any) -> list[OrcGetRequirementsTool]:
            reqs: list[str] = kwargs.get("requirements", [])
            inner = GetRequirementsExecutor(reqs, observation_factory=_obs_get_req)
            return [
                cls(
                    description="Get the list of requirements for the current task.",
                    action_type=OrcGetReqAction,
                    observation_type=OrcGetReqObservation,
                    executor=_GetReqExec(inner),
                )
            ]

    class OrcUpdateChecklistTool(
        _OHToolDefinition[OrcUpdateAction, OrcUpdateObservation]  # type: ignore[type-arg]
    ):
        @classmethod
        def create(cls, *args: Any, **kwargs: Any) -> list[OrcUpdateChecklistTool]:
            reg = _callback_registry.get(kwargs["registry_key"])
            inner = UpdateChecklistExecutor(
                reg["on_checklist_update"],
                reg["loop"],
                observation_factory=_obs_update,
            )
            return [
                cls(
                    description=(
                        "Mark a requirement as done, not_applicable, or blocked. "
                        "Parameters: req_id (string), status (one of: done, "
                        "not_applicable, blocked), note (optional string)."
                    ),
                    action_type=OrcUpdateAction,
                    observation_type=OrcUpdateObservation,
                    executor=_UpdateExec(inner),
                )
            ]

    class OrcSubmitTool(
        _OHToolDefinition[OrcSubmitAction, OrcSubmitObservation]  # type: ignore[type-arg]
    ):
        @classmethod
        def create(cls, *args: Any, **kwargs: Any) -> list[OrcSubmitTool]:
            reg = _callback_registry.get(kwargs["registry_key"])
            inner = SubmitExecutor(
                reg["on_submit"],
                reg["loop"],
                observation_factory=_obs_submit,
            )
            return [
                cls(
                    description="Submit the task for verification after completing all requirements.",
                    action_type=OrcSubmitAction,
                    observation_type=OrcSubmitObservation,
                    executor=_SubmitExec(inner),
                )
            ]

    class OrcSetGradeTool(
        _OHToolDefinition[OrcSetGradeAction, OrcSetGradeObservation]  # type: ignore[type-arg]
    ):
        @classmethod
        def create(cls, *args: Any, **kwargs: Any) -> list[OrcSetGradeTool]:
            reg = _callback_registry.get(kwargs["registry_key"])
            on_grade = reg.get("on_grade")
            if on_grade is None:
                # Return empty list if on_grade is not provided (builder phase)
                return []

            from orchestrator.runners.agents.openhands.common import SetGradeExecutor

            inner = SetGradeExecutor(
                on_grade,
                reg["loop"],
                observation_factory=_obs_set_grade,
            )
            return [
                cls(
                    description=(
                        "Set a grade on a requirement. "
                        "Parameters: req_id (string), grade (one of: A, B, C, D, F), "
                        "grade_reason (optional string explaining the grade)."
                    ),
                    action_type=OrcSetGradeAction,
                    observation_type=OrcSetGradeObservation,
                    executor=_SetGradeExec(inner),
                )
            ]


# ---------------------------------------------------------------------------
# SDK tool registration -- lazy, idempotent
# ---------------------------------------------------------------------------

_tools_registered = False


def _format_oh_event(event: Any) -> str:
    """Extract a human-readable log line from an OpenHands SDK event."""
    try:
        cls_name = type(event).__name__
        parts: list[str] = []

        # Reasoning content from thinking models (qwen <think>, deepseek, etc.)
        reasoning = getattr(event, "reasoning_content", None)
        if isinstance(reasoning, str) and reasoning.strip():
            parts.append(f"[reasoning] {reasoning.strip()[:2000]}")

        # ActionEvent: thought is Sequence[TextContent], action is an Action object
        raw_thought = getattr(event, "thought", None)
        if raw_thought and not isinstance(raw_thought, str):
            # Sequence of TextContent objects
            for tc in raw_thought:
                text = getattr(tc, "text", None)
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip()[:1500])
        elif isinstance(raw_thought, str) and raw_thought.strip():
            parts.append(raw_thought.strip()[:1500])

        tool_name = getattr(event, "tool_name", None)
        if isinstance(tool_name, str) and tool_name:
            parts.append(f"tool={tool_name}")

        # ActionEvent: extract action arguments for visibility
        action = getattr(event, "action", None)
        if action is not None:
            # For think tool, the thought content is in action.thought
            action_thought = getattr(action, "thought", None)
            if isinstance(action_thought, str) and action_thought.strip():
                parts.append(f"thought={action_thought.strip()[:1500]}")
            # For terminal, the command is in action.command
            action_cmd = getattr(action, "command", None)
            if isinstance(action_cmd, str) and action_cmd.strip():
                parts.append(f"$ {action_cmd.strip()[:500]}")

        # ObservationEvent: observation has .text property and .content list
        obs = getattr(event, "observation", None)
        if obs is not None:
            obs_text = getattr(obs, "text", None)
            if isinstance(obs_text, str) and obs_text.strip():
                parts.append(obs_text.strip()[:2000])

        # MessageEvent or other events with content list
        if not parts:
            content = getattr(event, "content", None)
            if isinstance(content, str) and content.strip():
                parts.append(content.strip()[:1500])
            elif isinstance(content, list):
                for c in content:  # pyright: ignore[reportUnknownVariableType]
                    text: Any = getattr(c, "text", None)  # pyright: ignore[reportUnknownArgumentType]
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip()[:1500])

        if not parts:
            return ""
        return f"[{cls_name}] {' | '.join(parts)}"
    except Exception:
        return ""


def _register_sdk_tools(tool_names: list[str] | None = None) -> None:
    """Import built-in tool modules and register custom tools.

    Must be called after the SDK is confirmed available.  Idempotent.
    """
    global _tools_registered  # noqa: PLW0603
    if _tools_registered:
        return

    register_builtin_tools(tool_names)

    # Register our custom tools in the SDK's global registry.
    _oh_register_tool("OrcGetRequirementsTool", OrcGetRequirementsTool)  # pyright: ignore[reportPossiblyUnboundVariable]
    _oh_register_tool("OrcUpdateChecklistTool", OrcUpdateChecklistTool)  # pyright: ignore[reportPossiblyUnboundVariable]
    _oh_register_tool("OrcSubmitTool", OrcSubmitTool)  # pyright: ignore[reportPossiblyUnboundVariable]
    _oh_register_tool("OrcSetGradeTool", OrcSetGradeTool)  # pyright: ignore[reportPossiblyUnboundVariable]

    _tools_registered = True


def _build_openhands_mcp_config(
    mcp_servers: list[Any] | None,
) -> dict[str, Any] | None:
    """Convert MCPServerConfig list to OpenHands mcp_config format.

    Format: {"mcpServers": {"name": {"url": "...", "command": "...", ...}}}
    Auth tokens are resolved from environment variables via auth_token_env field.
    """
    if not mcp_servers:
        return None

    servers: dict[str, dict[str, Any]] = {}
    for mcp in mcp_servers:
        entry: dict[str, Any] = {}

        # Add transport: either url or command
        if mcp.url:
            entry["url"] = mcp.url
        elif mcp.command:
            entry["command"] = mcp.command
            if mcp.args:
                entry["args"] = mcp.args

        # Add environment variables
        if mcp.env:
            entry["env"] = dict(mcp.env)

        # Resolve auth token from environment variable if specified
        if mcp.auth_token_env:
            token = os.environ.get(mcp.auth_token_env)
            if token:
                entry.setdefault("env", {})["AUTH_TOKEN"] = token

        servers[mcp.name] = entry

    return {"mcpServers": servers}


# ---------------------------------------------------------------------------
# OpenHands Agent
# ---------------------------------------------------------------------------


class OpenHandsAgent:
    """Agent that executes via the openhands-ai SDK's LocalConversation.

    Runs entirely in-process -- no remote server required.

    Requires:
    - openhands-ai package installed
    - OPENAI_API_KEY environment variable set

    Configuration:
        The server_url parameter is currently unused by LocalConversation
        (which runs in-process), but is preserved for compatibility with
        future remote OpenHands support.

        To use the openhands_url from global config:

            from orchestrator.config.global_config import load_global_config

            global_cfg = load_global_config()
            agent = OpenHandsAgent(
                server_url=global_cfg.agents.openhands_url or "http://localhost:3000",
            )
    """

    name = "OpenHands (local)"

    def __init__(
        self,
        server_url: str = "http://localhost:3000",
        model: str = "gpt-5-mini",
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        max_iterations: int = 100,
        tools: list[str] | None = None,
        llm_config: dict[str, Any] | None = None,
        max_actions: int = 200,
    ) -> None:
        self._server_url = server_url
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._http_client = http_client
        self._max_iterations = max_iterations
        self._tools = tools
        self._llm_config = llm_config or {}
        self._max_actions = max_actions
        self._cancelled = False
        self._conversation: _LocalConversation | None = None  # pyright: ignore[reportUnknownVariableType]

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_type=AgentRunnerType.OPENHANDS_LOCAL,
            name="OpenHands",
            version=None,
        )

    async def check_health(self) -> bool:
        """Check if the local OpenHands agent is usable.

        Returns True if the openhands-ai SDK is importable.  No remote
        server is involved — this agent runs entirely in-process via
        LocalConversation.  API key is not required when using a local LLM.
        """
        return _SDK_AVAILABLE

    def get_quota(self, fetcher: QuotaFetcher | None = None) -> AgentQuota | None:
        """Fetch the OpenAI credit balance for the configured API key.

        Uses the injected fetcher if provided; otherwise constructs an
        HttpQuotaFetcher.  All exceptions are swallowed and result in None.
        The api_key is never logged at any log level.

        Returns:
            AgentQuota with balance_usd, max_balance_usd, and label when the
            key is present and the fetch succeeds; None otherwise.
        """
        api_key = self._api_key
        if not api_key:
            return None
        try:
            quota_fetcher: QuotaFetcher = fetcher if fetcher is not None else HttpQuotaFetcher()
            data = quota_fetcher.fetch_openai_credits(api_key)
            total_granted: float = data["total_granted"]
            total_used: float = data["total_used"]
            balance_usd = total_granted - total_used
            return AgentQuota(
                balance_usd=balance_usd,
                max_balance_usd=total_granted,
                balance_pct=None,
                label="OpenAI credit balance",
                breakdown=[
                    QuotaBucket(
                        label="OpenAI credits",
                        remaining_usd=round(balance_usd, 2),
                    )
                ],
            )
        except Exception:
            return None

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        """Execute a task via OpenHands.

        Creates a local conversation with custom orchestrator tools registered,
        sends the prompt, and runs the agent. The SDK's Conversation.run() is
        blocking, so it is dispatched to a thread via asyncio.to_thread().
        Custom tool executors bridge back to async callbacks using
        run_coroutine_threadsafe().
        """
        if not _SDK_AVAILABLE:
            raise AgentNotAvailableError(
                "openhands_local",
                "openhands-ai package not installed. Install with: uv sync --extra openhands",
            )

        _register_sdk_tools(self._tools)

        from openhands.sdk import (  # pyright: ignore[reportUnknownVariableType,reportMissingImports]
            Agent as OHAgent,
            LLM as OHLLM,
            LocalConversation,
            Tool as OHTool,
        )
        from pydantic import SecretStr

        # API key is required for OpenAI/cloud LLMs but optional for local servers
        using_local_llm = bool(self._llm_config.get("base_url"))
        if not self._api_key and not using_local_llm:
            raise AgentNotAvailableError(
                "openhands_local",
                "OPENAI_API_KEY environment variable not set",
            )

        if self._cancelled:
            raise AgentCancelledError("openhands_local")

        loop = asyncio.get_running_loop()

        # Register callbacks under a unique key so that ToolDefinition.create()
        # can retrieve them without non-serializable objects in Tool.params.
        registry_key = uuid.uuid4().hex
        _callback_registry.register(
            registry_key,
            on_checklist_update,
            on_submit,
            loop,
            on_grade=on_grade,
        )

        try:
            # Build LLM — api_key is optional when using a local server
            # When using a local LLM server (base_url set), LiteLLM requires
            # a provider prefix. Local servers speak the OpenAI-compatible API.
            model = self._model
            if using_local_llm and "/" not in model:
                model = f"openai/{model}"
            llm_kwargs: dict[str, Any] = {"model": model, **self._llm_config}
            if self._api_key:
                llm_kwargs["api_key"] = SecretStr(self._api_key)

            # Log token usage (including cache info) from each LLM response
            import litellm
            from litellm.integrations.custom_logger import CustomLogger

            _oh_logger = logging.getLogger("orchestrator.runners.openhands.usage")

            class _UsageLogger(CustomLogger):
                def log_success_event(
                    self, kwargs: Any, response_obj: Any, start_time: Any, end_time: Any
                ) -> None:  # type: ignore[override]
                    usage = getattr(response_obj, "usage", None)
                    if usage:
                        details = getattr(usage, "prompt_tokens_details", None)
                        cached = getattr(details, "cached_tokens", 0) if details else 0
                        _oh_logger.info(
                            f"LLM usage: prompt={getattr(usage, 'prompt_tokens', '?')}"
                            f" completion={getattr(usage, 'completion_tokens', '?')}"
                            f" cached={cached}"
                            f" details={details}"
                        )

            litellm.callbacks.append(_UsageLogger())  # type: ignore[attr-defined]

            llm = OHLLM(**llm_kwargs)

            # Build Agent with built-in + custom tools.
            from orchestrator.runners.agents.openhands.common import DEFAULT_OPENHANDS_TOOLS

            # Start with configured or default tools
            tool_names = list(self._tools or DEFAULT_OPENHANDS_TOOLS)

            # Add step-level tools (additive to defaults)
            if context.available_tools:
                for tool_name in context.available_tools:
                    if tool_name not in tool_names:
                        tool_names.append(tool_name)

            # Create tool objects with warning for unknown tools
            logger = logging.getLogger(__name__)
            builtin_tools: list[Any] = []
            for name in tool_names:
                try:
                    builtin_tools.append(OHTool(name=name))
                except Exception as e:
                    logger.warning("Error creating tool '%s': %s — skipping", name, e)
            orchestrator_tools = [
                OHTool(
                    name="OrcGetRequirementsTool",
                    params={"requirements": context.requirements},
                ),
                OHTool(
                    name="OrcUpdateChecklistTool",
                    params={"registry_key": registry_key},
                ),
                OHTool(
                    name="OrcSubmitTool",
                    params={"registry_key": registry_key},
                ),
                OHTool(
                    name="OrcSetGradeTool",
                    params={"registry_key": registry_key},
                ),
            ]

            # Build MCP config if servers are available
            mcp_config = _build_openhands_mcp_config(context.mcp_servers)

            # Create agent with MCP config if supported by this SDK version
            agent_kwargs: dict[str, Any] = {
                "llm": llm,
                "tools": builtin_tools + orchestrator_tools,
            }
            if mcp_config:
                agent_kwargs["mcp_config"] = mcp_config

            try:
                agent = OHAgent(**agent_kwargs)
            except TypeError as e:
                if "mcp_config" in str(e):
                    # Graceful fallback: OpenHands SDK does not support mcp_config
                    logger.warning(
                        "OpenHands SDK does not support mcp_config parameter — "
                        "MCP servers will not be available. Error: %s",
                        e,
                    )
                    # Retry without mcp_config
                    agent = OHAgent(
                        llm=llm,
                        tools=builtin_tools + orchestrator_tools,
                    )
                else:
                    raise

            # Build prompt (with verifier flag if on_grade is provided)
            is_verifier = on_grade is not None

            # No checkout needed for verifier mode — the worktree is already
            # at end_commit (submit_for_verification auto-commits and captures HEAD).

            full_prompt = build_openhands_prompt(context, is_verifier=is_verifier)

            # Create a visualizer that streams events to on_output in real time.
            # on_event is called synchronously from conversation.run()'s thread,
            # so we bridge to the async on_output via run_coroutine_threadsafe.
            # Lines are also collected for the ExecutionResult.output_lines so
            # they get persisted to the attempt's agent_output column.
            collected_lines: list[str] = []
            visualizer = None
            rep_detector = RepetitionDetector(RepetitionDetectorConfig())
            reasoning_detector = ReasoningRepetitionDetector()
            action_budget = ActionBudget(ActionBudgetConfig(max_actions=self._max_actions))
            if on_output:
                from openhands.sdk.conversation.visualizer.base import (  # pyright: ignore[reportMissingImports]
                    ConversationVisualizerBase as _VizBase,
                )

                class _StreamingVisualizer(_VizBase):  # type: ignore[misc]
                    def on_event(self, event: Any) -> None:
                        try:
                            line = _format_oh_event(event)
                            if not line:
                                return
                            collected_lines.append(line)

                            # Repetition detection: feed terminal commands and tool actions
                            action = getattr(event, "action", None)
                            if action is not None:
                                rep_result = RepetitionAction.NONE

                                cmd = getattr(action, "command", None)
                                if isinstance(cmd, str) and cmd.strip():
                                    rep_result = rep_detector.record_action(cmd)

                                # Feed tool actions (file_editor views, glob, grep, etc.)
                                ev_tool_name = getattr(event, "tool_name", None)
                                if isinstance(ev_tool_name, str) and ev_tool_name:
                                    action_path = getattr(action, "path", None)
                                    action_command_attr = getattr(action, "command", None)

                                    if ev_tool_name == "file_editor":
                                        # Only track views (not productive edits)
                                        # str_replace and create indicate productive work
                                        old_str = getattr(action, "old_str", None)
                                        new_str = getattr(action, "new_str", None)
                                        file_text = getattr(action, "file_text", None)
                                        is_edit = (
                                            old_str is not None
                                            or new_str is not None
                                            or file_text is not None
                                        )
                                        if not is_edit and isinstance(action_path, str):
                                            rep_result = rep_detector.record_action(
                                                f"file_editor:view:{action_path}"
                                            )
                                    elif not isinstance(action_command_attr, str):
                                        # Non-terminal tools (glob, grep, etc.)
                                        summary = (
                                            action_path
                                            or getattr(action, "pattern", None)
                                            or getattr(action, "query", None)
                                            or ""
                                        )
                                        if isinstance(summary, str):
                                            summary = summary[:100]
                                        else:
                                            summary = str(summary)[:100]
                                        rep_result = rep_detector.record_action(
                                            f"{ev_tool_name}:{summary}"
                                        )

                                if rep_result == RepetitionAction.KILL:
                                    logger.warning(
                                        "RepetitionDetector: agent stuck repeating %r "
                                        "(%d times in last %d actions) — pausing",
                                        rep_detector.repeated_command,
                                        rep_detector.config.threshold,
                                        rep_detector.config.window_size,
                                    )
                                    conversation.pause()

                                # Action budget check
                                budget_result = action_budget.record_action()
                                if budget_result == RepetitionAction.KILL:
                                    logger.warning(
                                        "ActionBudget: agent exceeded %d actions — pausing",
                                        action_budget.config.max_actions,
                                    )
                                    conversation.pause()

                            # Reasoning repetition detection
                            reasoning = getattr(event, "reasoning_content", None)
                            if isinstance(reasoning, str) and reasoning.strip():
                                reason_result = reasoning_detector.record_reasoning(reasoning)
                                if reason_result == RepetitionAction.KILL:
                                    logger.warning(
                                        "ReasoningDetector: agent stuck in reasoning loop "
                                        "(%d repeated prefixes in last %d events) — pausing",
                                        reasoning_detector.config.threshold,
                                        reasoning_detector.config.window_size,
                                    )
                                    conversation.pause()

                            future = asyncio.run_coroutine_threadsafe(  # pyright: ignore[reportUnknownVariableType]
                                on_output([line]),  # type: ignore[arg-type]
                                loop,
                            )
                            future.result(timeout=5)
                        except Exception:
                            pass  # Best-effort streaming — never crash the SDK

                visualizer = _StreamingVisualizer()

            # Create conversation
            conversation = LocalConversation(
                agent=agent,
                workspace=context.working_dir,
                max_iteration_per_run=self._max_iterations,
                visualizer=visualizer,
            )
            self._conversation = conversation

            # Send message and run
            conversation.send_message(full_prompt)

            if self._cancelled:
                raise AgentCancelledError("openhands_local")

            await asyncio.to_thread(conversation.run)

            # Extract metrics
            metrics = extract_metrics(conversation)

            # Parse OpenHands events into structured action log
            action_log = None
            try:
                from orchestrator.runners.agents.openhands.parser import OpenHandsEventParser

                events_list = list(getattr(getattr(conversation, "state", None), "events", []))
                if events_list:
                    action_log = OpenHandsEventParser().parse_events(events_list)
            except Exception:
                pass  # Action log is best-effort

            return ExecutionResult(
                success=True,
                metrics=metrics,
                action_log=action_log,
                output_lines=collected_lines,
            )

        except AgentCancelledError:
            raise
        except AgentNotAvailableError:
            raise
        except GateBlockedError:
            raise
        except Exception as exc:
            raise AgentExecutionError("openhands_local", str(exc)) from exc
        finally:
            _callback_registry.pop(registry_key)
            self._conversation = None  # pyright: ignore[reportUnknownMemberType]

    async def cancel(self) -> None:
        """Cancel execution."""
        self._cancelled = True
        if self._conversation is not None:  # pyright: ignore[reportUnknownMemberType]
            self._conversation.pause()  # pyright: ignore[reportUnknownMemberType]
