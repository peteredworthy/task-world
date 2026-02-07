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
import os
import uuid
from typing import TYPE_CHECKING, Any

import httpx

from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.agents.openhands_common import (
    CallbackRegistry,
    GetRequirementsExecutor,
    SubmitExecutor,
    UpdateChecklistExecutor,
    build_openhands_prompt,
    extract_metrics,
    register_builtin_tools,
)
from orchestrator.agents.types import (
    AgentInfo,
    ChecklistUpdateCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)
from orchestrator.config.enums import AgentType

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

            from orchestrator.agents.openhands_common import SetGradeExecutor

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

    def __init__(
        self,
        server_url: str = "http://localhost:3000",
        model: str = "gpt-5-mini",
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        max_iterations: int = 100,
        tools: list[str] | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> None:
        self._server_url = server_url
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._http_client = http_client
        self._max_iterations = max_iterations
        self._tools = tools
        self._llm_config = llm_config or {}
        self._cancelled = False
        self._conversation: _LocalConversation | None = None  # pyright: ignore[reportUnknownVariableType]

    @property
    def info(self) -> AgentInfo:
        return AgentInfo(
            agent_type=AgentType.OPENHANDS_LOCAL,
            name="OpenHands",
            version=None,
        )

    async def check_health(self) -> bool:
        """Check if the local OpenHands agent is usable.

        Returns True if the openhands-ai SDK is importable and an API key
        is configured.  No remote server is involved — this agent runs
        entirely in-process via LocalConversation.
        """
        return _SDK_AVAILABLE and bool(self._api_key)

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
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

        if not self._api_key:
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
            # Build LLM
            llm = OHLLM(
                model=self._model,
                api_key=SecretStr(self._api_key),
                **self._llm_config,
            )

            # Build Agent with built-in + custom tools.
            from orchestrator.agents.openhands_common import DEFAULT_OPENHANDS_TOOLS

            tool_names = self._tools or DEFAULT_OPENHANDS_TOOLS
            builtin_tools = [OHTool(name=name) for name in tool_names]
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

            agent = OHAgent(
                llm=llm,
                tools=builtin_tools + orchestrator_tools,
            )

            # Build prompt (with verifier flag if on_grade is provided)
            is_verifier = on_grade is not None
            full_prompt = build_openhands_prompt(context, is_verifier=is_verifier)

            # Create conversation
            conversation = LocalConversation(
                agent=agent,
                workspace=context.working_dir,
                max_iteration_per_run=self._max_iterations,
                visualizer=None,
            )
            self._conversation = conversation

            # Send message and run
            conversation.send_message(full_prompt)

            if self._cancelled:
                raise AgentCancelledError("openhands_local")

            await asyncio.to_thread(conversation.run)

            # Extract metrics
            metrics = extract_metrics(conversation)

            return ExecutionResult(success=True, metrics=metrics)

        except AgentCancelledError:
            raise
        except AgentNotAvailableError:
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
