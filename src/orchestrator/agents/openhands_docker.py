"""Docker-based OpenHands agent integration using hybrid approach.

Uses a hybrid architecture where:
- Agent loop runs locally (LocalConversation) for callback support
- Built-in tool execution (terminal, file operations) routes to Docker container
- Custom orchestrator tools execute locally with callbacks

This approach fixes the issue where custom tools with callbacks couldn't work
with RemoteConversation (which serializes everything to the container).

Requires:
- openhands-ai package installed (SDK: Agent, LLM, LocalConversation, etc.)
- openhands-workspace package installed (DockerWorkspace)
- Docker daemon running
- OPENAI_API_KEY environment variable set
- Project directory must be accessible for mounting into the container
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import uuid
from typing import Any

from pydantic import Field

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

# ---------------------------------------------------------------------------
# SDK availability -- two separate guards
# ---------------------------------------------------------------------------

_SDK_AVAILABLE = False
_DOCKER_WORKSPACE_AVAILABLE = False

try:
    from openhands.sdk import (  # pyright: ignore[reportUnknownVariableType,reportMissingImports]
        Action as _OHAction,
        Agent as _OHAgent,
        LLM as _OHLLM,
        Observation as _OHObservation,
        Tool as _OHTool,
        register_tool as _oh_register_tool,  # pyright: ignore[reportUnknownVariableType]
    )
    from openhands.sdk.llm import TextContent as _OHTextContent  # pyright: ignore[reportMissingImports]
    from openhands.sdk.tool.tool import (  # pyright: ignore[reportUnknownVariableType,reportMissingImports]
        ToolDefinition as _OHToolDefinition,
        ToolExecutor as _OHToolExecutor,
    )
    from openhands.sdk.conversation.impl.local_conversation import (  # pyright: ignore[reportMissingImports]
        LocalConversation as _OHLocalConversation,
    )
    from openhands.sdk.workspace import (  # pyright: ignore[reportMissingImports]
        LocalWorkspace as _OHLocalWorkspace,
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
# Registries -- store non-serializable objects by key
# ---------------------------------------------------------------------------

_callback_registry = CallbackRegistry()

# Workspace registry for Docker execution routing
_workspace_registry: dict[str, Any] = {}


def _register_workspace(key: str, workspace: Any) -> None:
    """Register a workspace for tool execution routing."""
    _workspace_registry[key] = workspace


def _get_workspace(key: str) -> Any:
    """Get a registered workspace by key."""
    return _workspace_registry.get(key)


def _pop_workspace(key: str) -> Any:
    """Remove and return a workspace from the registry."""
    return _workspace_registry.pop(key, None)


# ---------------------------------------------------------------------------
# SDK type definitions -- module level (unique names to avoid registry collisions)
# ---------------------------------------------------------------------------

if _SDK_AVAILABLE:
    # --- Terminal tool that routes to Docker ---

    class DockerTerminalAction(_OHAction):  # type: ignore[misc]
        """Action for terminal commands executed in Docker."""

        command: str = Field(description="The bash command to execute.")
        timeout: float | None = Field(default=None, description="Optional timeout in seconds.")

    class DockerTerminalObservation(_OHObservation):  # type: ignore[misc]
        """Observation from terminal command in Docker."""

        exit_code: int | None = Field(default=None, description="Exit code of the command.")

    class _DockerTerminalExecutor(_OHToolExecutor):  # type: ignore[type-arg,misc]
        """Executor that routes terminal commands to Docker container."""

        def __init__(self, workspace_key: str, working_dir: str) -> None:
            self._workspace_key = workspace_key
            self._working_dir = working_dir

        def __call__(self, action: Any, conversation: Any = None) -> Any:
            workspace = _get_workspace(self._workspace_key)
            if workspace is None:
                return DockerTerminalObservation(
                    content=[_OHTextContent(text="Error: Docker workspace not found")],  # pyright: ignore[reportPossiblyUnboundVariable,reportArgumentType]
                    is_error=True,
                    exit_code=-1,
                )

            timeout = getattr(action, "timeout", None) or 30.0
            command = getattr(action, "command", "")

            try:
                result = workspace.execute_command(command, cwd=self._working_dir, timeout=timeout)

                output = result.stdout or ""
                if result.stderr:
                    output = f"{output}\n{result.stderr}" if output else result.stderr

                return DockerTerminalObservation(
                    content=[_OHTextContent(text=output or "(no output)")],  # pyright: ignore[reportPossiblyUnboundVariable,reportArgumentType]
                    exit_code=result.exit_code,
                )
            except Exception as exc:
                return DockerTerminalObservation(
                    content=[_OHTextContent(text=f"Error executing command: {exc}")],  # pyright: ignore[reportPossiblyUnboundVariable,reportArgumentType]
                    is_error=True,
                    exit_code=-1,
                )

    class DockerTerminalTool(
        _OHToolDefinition[DockerTerminalAction, DockerTerminalObservation]  # type: ignore[type-arg]
    ):
        """Terminal tool that routes execution to Docker container."""

        @classmethod
        def create(cls, *args: Any, **kwargs: Any) -> list["DockerTerminalTool"]:
            workspace_key = kwargs.get("workspace_key")
            working_dir = kwargs.get("working_dir", "/workspace")

            if workspace_key is None:
                raise ValueError("workspace_key is required for DockerTerminalTool")

            executor = _DockerTerminalExecutor(workspace_key, working_dir)

            return [
                cls(
                    description=(
                        "Execute a bash command in the Docker container. "
                        "Use this for running shell commands, scripts, and system operations."
                    ),
                    action_type=DockerTerminalAction,
                    observation_type=DockerTerminalObservation,
                    executor=executor,
                )
            ]

    # --- Orchestrator tools (run locally with callbacks) ---

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

    class DockerOrcSetGradeAction(_OHAction):  # type: ignore[misc]
        req_id: str
        grade: str
        grade_reason: str | None = None

    class DockerOrcSetGradeObservation(_OHObservation):  # type: ignore[misc]
        pass

    # --- Observation factories ---

    def _obs_get_req(text: str) -> DockerOrcGetReqObservation:  # type: ignore[type-arg]
        return DockerOrcGetReqObservation(content=[_OHTextContent(text=text)])  # type: ignore[call-arg]

    def _obs_update(text: str) -> DockerOrcUpdateObservation:  # type: ignore[type-arg]
        return DockerOrcUpdateObservation(content=[_OHTextContent(text=text)])  # type: ignore[call-arg]

    def _obs_submit(text: str) -> DockerOrcSubmitObservation:  # type: ignore[type-arg]
        return DockerOrcSubmitObservation(content=[_OHTextContent(text=text)])  # type: ignore[call-arg]

    def _obs_set_grade(text: str) -> DockerOrcSetGradeObservation:  # type: ignore[type-arg]
        return DockerOrcSetGradeObservation(content=[_OHTextContent(text=text)])  # type: ignore[call-arg]

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

    class _DockerSetGradeExec(_OHToolExecutor):  # type: ignore[type-arg,misc]
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def __call__(self, action: Any, conversation: Any = None) -> Any:
            return self._inner(action, conversation)

    # --- ToolDefinition subclasses ---

    class DockerOrcGetRequirementsTool(
        _OHToolDefinition[DockerOrcGetReqAction, DockerOrcGetReqObservation]  # type: ignore[type-arg]
    ):
        @classmethod
        def create(cls, *args: Any, **kwargs: Any) -> list["DockerOrcGetRequirementsTool"]:
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
        def create(cls, *args: Any, **kwargs: Any) -> list["DockerOrcUpdateChecklistTool"]:
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
        def create(cls, *args: Any, **kwargs: Any) -> list["DockerOrcSubmitTool"]:
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

    class DockerOrcSetGradeTool(
        _OHToolDefinition[DockerOrcSetGradeAction, DockerOrcSetGradeObservation]  # type: ignore[type-arg]
    ):
        @classmethod
        def create(cls, *args: Any, **kwargs: Any) -> list["DockerOrcSetGradeTool"]:
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
                    action_type=DockerOrcSetGradeAction,
                    observation_type=DockerOrcSetGradeObservation,
                    executor=_DockerSetGradeExec(inner),
                )
            ]


# ---------------------------------------------------------------------------
# SDK tool registration -- lazy, idempotent
# ---------------------------------------------------------------------------

_docker_tools_registered = False


def _register_sdk_tools() -> None:
    """Register custom Docker-specific tools in the SDK registry.

    Must be called after the SDK is confirmed available. Idempotent.
    """
    global _docker_tools_registered  # noqa: PLW0603
    if _docker_tools_registered:
        return

    # Register our custom tools
    _oh_register_tool("DockerTerminalTool", DockerTerminalTool)  # pyright: ignore[reportPossiblyUnboundVariable]
    _oh_register_tool("DockerOrcGetRequirementsTool", DockerOrcGetRequirementsTool)  # pyright: ignore[reportPossiblyUnboundVariable]
    _oh_register_tool("DockerOrcUpdateChecklistTool", DockerOrcUpdateChecklistTool)  # pyright: ignore[reportPossiblyUnboundVariable]
    _oh_register_tool("DockerOrcSubmitTool", DockerOrcSubmitTool)  # pyright: ignore[reportPossiblyUnboundVariable]
    _oh_register_tool("DockerOrcSetGradeTool", DockerOrcSetGradeTool)  # pyright: ignore[reportPossiblyUnboundVariable]

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
# Docker OpenHands Agent (Hybrid Approach)
# ---------------------------------------------------------------------------


class DockerOpenHandsAgent:
    """Agent that executes via an ephemeral Docker container using hybrid approach.

    Uses a hybrid architecture where:
    - Agent loop runs locally (LocalConversation) for callback support
    - Built-in tool execution routes to Docker container via HTTP API
    - Custom orchestrator tools execute locally with callbacks

    This fixes the issue where RemoteConversation couldn't support custom tools
    with callbacks (since callbacks can't be serialized to the container).

    Requires:
    - openhands-ai package installed
    - openhands-workspace package installed
    - Docker daemon running
    - OPENAI_API_KEY environment variable set
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        max_iterations: int = 100,
        server_image: str = "ghcr.io/openhands/agent-server:latest-python",
        docker_platform: str | None = None,
        tools: list[str] | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._max_iterations = max_iterations
        self._server_image = server_image
        self._platform = docker_platform
        self._tools = tools
        self._llm_config = llm_config or {}
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
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
    ) -> ExecutionResult:
        """Execute a task via Docker container using hybrid approach.

        Creates a DockerWorkspace for the container, but uses LocalConversation
        for the agent loop. This keeps callbacks working locally while routing
        built-in tool execution to the container.
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

        _register_sdk_tools()

        from pydantic import SecretStr

        loop = asyncio.get_running_loop()

        # Generate unique keys for this session
        session_key = uuid.uuid4().hex
        registry_key = f"cb_{session_key}"
        workspace_key = f"ws_{session_key}"

        _callback_registry.register(
            registry_key,
            on_checklist_update,
            on_submit,
            loop,
            on_grade=on_grade,
        )

        docker_workspace = None
        try:
            # Start Docker container
            resolved_platform = self._platform or _detect_platform()
            workspace_kwargs: dict[str, Any] = {
                "server_image": self._server_image,
                "volumes": [f"{context.working_dir}:/workspace:rw"],
                "detach_logs": False,  # Don't spam logs
            }
            if resolved_platform is not None:
                workspace_kwargs["platform"] = resolved_platform

            docker_workspace = _DockerWorkspace(**workspace_kwargs)  # pyright: ignore[reportPossiblyUnboundVariable]

            # Register workspace for tool execution routing
            _register_workspace(workspace_key, docker_workspace)

            # Create LLM
            llm = _OHLLM(  # pyright: ignore[reportPossiblyUnboundVariable]
                model=self._model,
                api_key=SecretStr(self._api_key),
                **self._llm_config,
            )

            # Build tools list
            # Our DockerTerminalTool replaces the standard terminal tool
            tools = [
                _OHTool(  # pyright: ignore[reportPossiblyUnboundVariable]
                    name="DockerTerminalTool",
                    params={
                        "workspace_key": workspace_key,
                        "working_dir": "/workspace",
                    },
                ),
                _OHTool(  # pyright: ignore[reportPossiblyUnboundVariable]
                    name="DockerOrcGetRequirementsTool",
                    params={"requirements": context.requirements},
                ),
                _OHTool(  # pyright: ignore[reportPossiblyUnboundVariable]
                    name="DockerOrcUpdateChecklistTool",
                    params={"registry_key": registry_key},
                ),
                _OHTool(  # pyright: ignore[reportPossiblyUnboundVariable]
                    name="DockerOrcSubmitTool",
                    params={"registry_key": registry_key},
                ),
                _OHTool(  # pyright: ignore[reportPossiblyUnboundVariable]
                    name="DockerOrcSetGradeTool",
                    params={"registry_key": registry_key},
                ),
            ]

            agent = _OHAgent(  # pyright: ignore[reportPossiblyUnboundVariable]
                llm=llm,
                tools=tools,
            )

            # Build prompt (with verifier flag if on_grade is provided)
            is_verifier = on_grade is not None
            full_prompt = build_openhands_prompt(context, is_verifier=is_verifier)

            # Use LocalConversation with a local workspace
            # The actual execution routes to Docker via our custom tools
            local_workspace = _OHLocalWorkspace(working_dir=context.working_dir)  # pyright: ignore[reportPossiblyUnboundVariable]

            conversation = _OHLocalConversation(  # pyright: ignore[reportPossiblyUnboundVariable]
                agent=agent,
                workspace=local_workspace,
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
            _pop_workspace(workspace_key)
            self._conversation = None
            if docker_workspace is not None:
                try:
                    docker_workspace.cleanup()  # pyright: ignore[reportUnknownMemberType]
                except Exception:
                    logging.getLogger(__name__).warning(
                        "Failed to clean up Docker workspace", exc_info=True
                    )

    async def cancel(self) -> None:
        """Cancel execution."""
        self._cancelled = True
        if self._conversation is not None:
            self._conversation.pause()  # pyright: ignore[reportUnknownMemberType]
