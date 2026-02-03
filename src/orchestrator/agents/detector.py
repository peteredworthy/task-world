"""Detect available agent tools on the system."""

import shutil
import subprocess

from orchestrator.agents.types import AgentConfigField, AgentOption
from orchestrator.config.enums import AgentType

# --- Config schemas for each agent type ---

_OPENHANDS_LOCAL_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="model",
        field_type="string",
        default="gpt-5-mini",
        description="LLM model to use",
    ),
    AgentConfigField(
        name="tools",
        field_type="select",
        default=["terminal", "file_editor"],
        description="OpenHands tools to enable",
        options=["terminal", "file_editor", "browser", "glob", "grep"],
    ),
    AgentConfigField(
        name="max_iterations",
        field_type="number",
        default=100,
        description="Maximum agent iterations per run",
    ),
]

_OPENHANDS_DOCKER_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="model",
        field_type="string",
        default="gpt-5-mini",
        description="LLM model to use",
    ),
    AgentConfigField(
        name="tools",
        field_type="select",
        default=["terminal", "file_editor"],
        description="OpenHands tools to enable",
        options=["terminal", "file_editor", "browser", "glob", "grep"],
    ),
    AgentConfigField(
        name="max_iterations",
        field_type="number",
        default=100,
        description="Maximum agent iterations per run",
    ),
    AgentConfigField(
        name="server_image",
        field_type="string",
        default="ghcr.io/openhands/agent-server:latest-python",
        description="Docker image for the agent server",
    ),
]

_CLI_SUBPROCESS_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="command",
        field_type="string",
        description="CLI command to run (read-only, set by detection)",
    ),
    AgentConfigField(
        name="model",
        field_type="string",
        description="Model to pass as --model flag",
    ),
    AgentConfigField(
        name="callback_channel",
        field_type="select",
        default="rest",
        description="How the subprocess calls back to the orchestrator",
        options=["rest", "mcp"],
    ),
    AgentConfigField(
        name="stdin_mode",
        field_type="select",
        default="close",
        description="Whether to close stdin after sending the prompt",
        options=["close", "open"],
    ),
]

_USER_MANAGED_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="callback_channel",
        field_type="select",
        default="mcp",
        description="How the external agent calls back to the orchestrator",
        options=["rest", "mcp"],
    ),
    AgentConfigField(
        name="timeout_minutes",
        field_type="number",
        default=60,
        description="Minutes to wait for agent to submit before timing out",
    ),
]


class ToolDetector:
    """Detects which agent backends are available.

    OpenHands local detection checks if the SDK is importable.
    OpenHands Docker detection checks DockerWorkspace importable + docker CLI + daemon.
    CLI tools are detected via shutil.which().
    User Managed is always available.
    """

    async def detect_all(self) -> list[AgentOption]:
        """Detect all available agent backends."""
        results: list[AgentOption] = []
        results.append(self._detect_openhands_local())
        results.append(self._detect_openhands_docker())
        results.extend(self._detect_cli_tools())
        results.append(self._detect_user_managed())
        return results

    def _detect_openhands_local(self) -> AgentOption:
        """Check if the openhands-ai SDK is importable (no server needed)."""
        try:
            import openhands.sdk  # noqa: F401  # pyright: ignore[reportUnusedImport,reportMissingImports]

            return AgentOption(
                agent_type=AgentType.OPENHANDS_LOCAL,
                name="OpenHands (local)",
                available=True,
                detail="openhands-ai SDK installed",
                config_schema=_OPENHANDS_LOCAL_CONFIG,
            )
        except ImportError:
            return AgentOption(
                agent_type=AgentType.OPENHANDS_LOCAL,
                name="OpenHands (local)",
                available=False,
                detail="openhands-ai SDK not installed",
                install_hint="Install with: uv sync --extra openhands",
                config_schema=_OPENHANDS_LOCAL_CONFIG,
            )

    def _detect_openhands_docker(self) -> AgentOption:
        """Check if Docker-based OpenHands is available.

        Checks three things:
        1. openhands.workspace.DockerWorkspace is importable
        2. docker CLI is in PATH
        3. docker daemon is running (docker info returns 0)
        """
        # 1. Check DockerWorkspace importable
        try:
            from openhands.workspace import DockerWorkspace  # noqa: F401  # pyright: ignore[reportUnusedImport,reportMissingImports]
        except ImportError:
            return AgentOption(
                agent_type=AgentType.OPENHANDS_DOCKER,
                name="OpenHands (Docker)",
                available=False,
                detail="openhands-workspace package not installed",
                install_hint="Install with: uv add openhands-workspace",
                config_schema=_OPENHANDS_DOCKER_CONFIG,
            )

        # 2. Check docker CLI in PATH
        if shutil.which("docker") is None:
            return AgentOption(
                agent_type=AgentType.OPENHANDS_DOCKER,
                name="OpenHands (Docker)",
                available=False,
                detail="docker CLI not found in PATH",
                install_hint="Install Docker: https://docs.docker.com/get-docker/",
                config_schema=_OPENHANDS_DOCKER_CONFIG,
            )

        # 3. Check docker daemon running
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                return AgentOption(
                    agent_type=AgentType.OPENHANDS_DOCKER,
                    name="OpenHands (Docker)",
                    available=False,
                    detail="Docker daemon not running",
                    install_hint="Start Docker daemon",
                    config_schema=_OPENHANDS_DOCKER_CONFIG,
                )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return AgentOption(
                agent_type=AgentType.OPENHANDS_DOCKER,
                name="OpenHands (Docker)",
                available=False,
                detail="Failed to check Docker daemon status",
                install_hint="Start Docker daemon",
                config_schema=_OPENHANDS_DOCKER_CONFIG,
            )

        return AgentOption(
            agent_type=AgentType.OPENHANDS_DOCKER,
            name="OpenHands (Docker)",
            available=True,
            detail="DockerWorkspace available, Docker daemon running",
            config_schema=_OPENHANDS_DOCKER_CONFIG,
        )

    def _detect_cli_tools(self) -> list[AgentOption]:
        """Detect CLI tools available via PATH."""
        results: list[AgentOption] = []

        for tool_name in ("claude", "codex"):
            path = shutil.which(tool_name)
            if path is not None:
                results.append(
                    AgentOption(
                        agent_type=AgentType.CLI_SUBPROCESS,
                        name=tool_name,
                        available=True,
                        detail=f"Found at {path}",
                        config_schema=_CLI_SUBPROCESS_CONFIG,
                    )
                )
            else:
                results.append(
                    AgentOption(
                        agent_type=AgentType.CLI_SUBPROCESS,
                        name=tool_name,
                        available=False,
                        detail=f"{tool_name} not found in PATH",
                        install_hint=f"Install {tool_name} CLI tool",
                        config_schema=_CLI_SUBPROCESS_CONFIG,
                    )
                )

        return results

    def _detect_user_managed(self) -> AgentOption:
        """User Managed is always available for external agent connections."""
        return AgentOption(
            agent_type=AgentType.USER_MANAGED,
            name="User Managed",
            available=True,
            detail="Always available for external agent connections",
            config_schema=_USER_MANAGED_CONFIG,
        )
