"""Docker-based OpenHands agent integration.

Uses the openhands-ai SDK with ``DockerWorkspace`` from ``openhands-workspace``
to run an agent whose tool execution happens inside an ephemeral Docker
container.  Agent reasoning and LLM calls stay on the host process.

Requires:
- openhands-ai package installed (SDK: Agent, LLM, Conversation, etc.)
- openhands-workspace package installed (DockerWorkspace)
- Docker daemon running
- OPENAI_API_KEY environment variable set
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import uuid
from typing import TYPE_CHECKING, Any

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
    SubmitCallback,
)
from orchestrator.config.enums import AgentType

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# SDK availability -- two separate guards
# ---------------------------------------------------------------------------

_SDK_AVAILABLE = False
_DOCKER_WORKSPACE_AVAILABLE = False

try:
    from openhands.sdk import (  # pyright: ignore[reportUnknownVariableType,reportMissingImports]
        Action as _OHAction,
        Agent as _OHAgent,
        Conversation as _OHConversation,
        LLM as _OHLLM,
        Observation as _OHObservation,
        TextContent as _OHTextContent,
        Tool as _OHTool,
        register_tool as _oh_register_tool,
    )
    from openhands.sdk.tool.tool import (  # pyright: ignore[reportUnknownVariableType,reportMissingImports]
        ToolDefinition as _OHToolDefinition,
        ToolExecutor as _OHToolExecutor,
    )

    _SDK_AVAILABLE = True  # pyright: ignore[reportConstantRedefinition]
except ImportError:
    pass

try:
    from openhands.workspace import DockerWorkspace as _DockerWorkspace  # pyright: ignore[reportMissingImports]

    _DOCKER_WORKSPACE_AVAILABLE = True  # pyright: ignore[reportConstantRedefinition]
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Callback registry -- independent from local agent's registry
# ---------------------------------------------------------------------------

_callback_registry = CallbackRegistry()


# ---------------------------------------------------------------------------
# SDK type definitions -- module level (unique names to avoid registry collisions)
# ---------------------------------------------------------------------------

if _SDK_AVAILABLE:

    class DockerOrcGetReqAction(_OHAction):  # type: ignore[misc]
        pass

    class DockerOrcGetReqObservation(_OHObservation):  # type: ignore[misc]
        pass

    class DockerOrcUpdateAction(_OHAction):  # type: ignore[misc]
        req_id: str
        status: str
        note: str | None = None

    class DockerOrcUpdateObservation(_OHObservation):  # type: ignore[misc]
        pass

    class DockerOrcSubmitAction(_OHAction):  # type: ignore[misc]
        pass

    class DockerOrcSubmitObservation(_OHObservation):  # type: ignore[misc]
        pass

    # --- Observation factories ---

    def _obs_get_req(text: str) -> DockerOrcGetReqObservation:  # type: ignore[type-arg]
        return DockerOrcGetReqObservation(content=[_OHTextContent(text=text)])  # type: ignore[call-arg]

    def _obs_update(text: str) -> DockerOrcUpdateObservation:  # type: ignore[type-arg]
        return DockerOrcUpdateObservation(content=[_OHTextContent(text=text)])  # type: ignore[call-arg]

    def _obs_submit(text: str) -> DockerOrcSubmitObservation:  # type: ignore[type-arg]
        return DockerOrcSubmitObservation(content=[_OHTextContent(text=text)])  # type: ignore[call-arg]

    # --- ToolExecutor wrappers ---

    class _DockerGetReqExec(_OHToolExecutor):  # type: ignore[type-arg,misc]
        def __init__(self, inner: GetRequirementsExecutor) -> None:
            self._inner = inner

        def __call__(self, action: Any, conversation: Any = None) -> Any:
            return self._inner(action, conversation)

    class _DockerUpdateExec(_OHToolExecutor):  # type: ignore[type-arg,misc]
        def __init__(self, inner: UpdateChecklistExecutor) -> None:
            self._inner = inner

        def __call__(self, action: Any, conversation: Any = None) -> Any:
            return self._inner(action, conversation)

    class _DockerSubmitExec(_OHToolExecutor):  # type: ignore[type-arg,misc]
        def __init__(self, inner: SubmitExecutor) -> None:
            self._inner = inner

        def __call__(self, action: Any, conversation: Any = None) -> Any:
            return self._inner(action, conversation)

    # --- ToolDefinition subclasses ---

    class DockerOrcGetRequirementsTool(
        _OHToolDefinition[DockerOrcGetReqAction, DockerOrcGetReqObservation]  # type: ignore[type-arg]
    ):
        @classmethod
        def create(cls, *args: Any, **kwargs: Any) -> list[DockerOrcGetRequirementsTool]:
            reqs: list[str] = kwargs.get("requirements", [])
            inner = GetRequirementsExecutor(reqs, observation_factory=_obs_get_req)
            return [
                cls(
                    description="Get the list of requirements for the current task.",
                    action_type=DockerOrcGetReqAction,
                    observation_type=DockerOrcGetReqObservation,
                    executor=_DockerGetReqExec(inner),
                )
            ]

    class DockerOrcUpdateChecklistTool(
        _OHToolDefinition[DockerOrcUpdateAction, DockerOrcUpdateObservation]  # type: ignore[type-arg]
    ):
        @classmethod
        def create(cls, *args: Any, **kwargs: Any) -> list[DockerOrcUpdateChecklistTool]:
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
                    action_type=DockerOrcUpdateAction,
                    observation_type=DockerOrcUpdateObservation,
                    executor=_DockerUpdateExec(inner),
                )
            ]

    class DockerOrcSubmitTool(
        _OHToolDefinition[DockerOrcSubmitAction, DockerOrcSubmitObservation]  # type: ignore[type-arg]
    ):
        @classmethod
        def create(cls, *args: Any, **kwargs: Any) -> list[DockerOrcSubmitTool]:
            reg = _callback_registry.get(kwargs["registry_key"])
            inner = SubmitExecutor(
                reg["on_submit"],
                reg["loop"],
                observation_factory=_obs_submit,
            )
            return [
                cls(
                    description="Submit the task for verification after completing all requirements.",
                    action_type=DockerOrcSubmitAction,
                    observation_type=DockerOrcSubmitObservation,
                    executor=_DockerSubmitExec(inner),
                )
            ]


# ---------------------------------------------------------------------------
# SDK tool registration -- lazy, idempotent
# ---------------------------------------------------------------------------

_docker_tools_registered = False


def _register_sdk_tools(tool_names: list[str] | None = None) -> None:
    """Register custom Docker-specific tools in the SDK registry.

    Must be called after the SDK is confirmed available. Idempotent.
    """
    global _docker_tools_registered  # noqa: PLW0603
    if _docker_tools_registered:
        return

    register_builtin_tools(tool_names)

    _oh_register_tool("DockerOrcGetRequirementsTool", DockerOrcGetRequirementsTool)  # pyright: ignore[reportPossiblyUnbound]
    _oh_register_tool("DockerOrcUpdateChecklistTool", DockerOrcUpdateChecklistTool)  # pyright: ignore[reportPossiblyUnbound]
    _oh_register_tool("DockerOrcSubmitTool", DockerOrcSubmitTool)  # pyright: ignore[reportPossiblyUnbound]

    _docker_tools_registered = True


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def _detect_platform() -> str | None:
    """Detect the Docker platform string for the current machine.

    Returns e.g. ``linux/amd64`` or ``linux/arm64``, or ``None`` if
    the architecture is unknown.
    """
    machine = platform.machine().lower()
    mapping: dict[str, str] = {
        "x86_64": "linux/amd64",
        "amd64": "linux/amd64",
        "aarch64": "linux/arm64",
        "arm64": "linux/arm64",
    }
    return mapping.get(machine)


# ---------------------------------------------------------------------------
# Docker OpenHands Agent
# ---------------------------------------------------------------------------


class DockerOpenHandsAgent:
    """Agent that executes via an ephemeral Docker container.

    Uses ``DockerWorkspace`` (from ``openhands-workspace``) to manage the
    container lifecycle.  ``Conversation`` (from ``openhands-ai``) drives the
    agent loop on the host, with tool execution routed to the container over
    HTTP.

    Requires:
    - openhands-ai package installed
    - openhands-workspace package installed
    - Docker daemon running
    - OPENAI_API_KEY environment variable set
    """

    def __init__(
        self,
        model: str = "gpt-5-mini",
        api_key: str | None = None,
        max_iterations: int = 100,
        server_image: str = "ghcr.io/openhands/agent-server:latest-python",
        docker_platform: str | None = None,
        tools: list[str] | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._max_iterations = max_iterations
        self._server_image = server_image
        self._platform = docker_platform
        self._tools = tools
        self._cancelled = False
        self._conversation: Any = None

    @property
    def info(self) -> AgentInfo:
        return AgentInfo(
            agent_type=AgentType.OPENHANDS_DOCKER,
            name="OpenHands (Docker)",
            version=None,
        )

    async def check_health(self) -> bool:
        """Check if the Docker daemon is running."""
        if shutil.which("docker") is None:
            return False
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "info",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await proc.wait() == 0

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
    ) -> ExecutionResult:
        """Execute a task via an ephemeral Docker container.

        Creates a ``DockerWorkspace`` (which starts the container), builds a
        ``Conversation`` with the agent on the host, and runs the agent loop.
        Tool execution is routed to the container; LLM calls stay on host.
        """
        if not _SDK_AVAILABLE:
            raise AgentNotAvailableError(
                "openhands_docker",
                "openhands-ai SDK not installed. Install with: uv sync --extra openhands",
            )

        if not _DOCKER_WORKSPACE_AVAILABLE:
            raise AgentNotAvailableError(
                "openhands_docker",
                "openhands-workspace package not installed. Install with: uv add openhands-workspace",
            )

        if not self._api_key:
            raise AgentNotAvailableError(
                "openhands_docker",
                "OPENAI_API_KEY environment variable not set",
            )

        if self._cancelled:
            raise AgentCancelledError("openhands_docker")

        _register_sdk_tools(self._tools)

        from pydantic import SecretStr

        loop = asyncio.get_running_loop()

        registry_key = uuid.uuid4().hex
        _callback_registry.register(
            registry_key,
            on_checklist_update,
            on_submit,
            loop,
        )

        workspace = None
        try:
            llm = _OHLLM(  # pyright: ignore[reportPossiblyUnbound]
                model=self._model,
                api_key=SecretStr(self._api_key),
            )

            from orchestrator.agents.openhands_common import DEFAULT_OPENHANDS_TOOLS

            tool_names = self._tools or DEFAULT_OPENHANDS_TOOLS
            builtin_tools = [_OHTool(name=name) for name in tool_names]  # pyright: ignore[reportPossiblyUnbound]
            orchestrator_tools = [
                _OHTool(  # pyright: ignore[reportPossiblyUnbound]
                    name="DockerOrcGetRequirementsTool",
                    params={"requirements": context.requirements},
                ),
                _OHTool(  # pyright: ignore[reportPossiblyUnbound]
                    name="DockerOrcUpdateChecklistTool",
                    params={"registry_key": registry_key},
                ),
                _OHTool(  # pyright: ignore[reportPossiblyUnbound]
                    name="DockerOrcSubmitTool",
                    params={"registry_key": registry_key},
                ),
            ]

            agent = _OHAgent(  # pyright: ignore[reportPossiblyUnbound]
                llm=llm,
                tools=builtin_tools + orchestrator_tools,
            )

            full_prompt = build_openhands_prompt(context)

            resolved_platform = self._platform or _detect_platform()

            workspace_kwargs: dict[str, Any] = {
                "server_image": self._server_image,
            }
            if resolved_platform is not None:
                workspace_kwargs["platform"] = resolved_platform

            workspace = _DockerWorkspace(**workspace_kwargs)  # pyright: ignore[reportPossiblyUnbound]

            conversation = _OHConversation(  # pyright: ignore[reportPossiblyUnbound]
                agent=agent,
                workspace=workspace,
                max_iteration_per_run=self._max_iterations,
                visualizer=None,
            )
            self._conversation = conversation

            conversation.send_message(full_prompt)  # pyright: ignore[reportUnknownMemberType]

            if self._cancelled:
                raise AgentCancelledError("openhands_docker")

            await asyncio.to_thread(conversation.run)  # pyright: ignore[reportUnknownMemberType]

            metrics = extract_metrics(conversation)

            return ExecutionResult(success=True, metrics=metrics)

        except AgentCancelledError:
            raise
        except AgentNotAvailableError:
            raise
        except Exception as exc:
            raise AgentExecutionError("openhands_docker", str(exc)) from exc
        finally:
            _callback_registry.pop(registry_key)
            self._conversation = None
            if workspace is not None:
                try:
                    workspace.cleanup()  # pyright: ignore[reportUnknownMemberType]
                except Exception:
                    pass

    async def cancel(self) -> None:
        """Cancel execution."""
        self._cancelled = True
        if self._conversation is not None:
            self._conversation.pause()  # pyright: ignore[reportUnknownMemberType]
