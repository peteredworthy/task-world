"""Detect available agent tools on the system."""

import asyncio
import shutil
import time
from dataclasses import dataclass, field
from typing import Any

from orchestrator.agents.types import AgentConfigField, AgentOption, AgentQuota
from orchestrator.config.enums import AgentType


@dataclass
class _QuotaCacheEntry:
    """Cache entry for agent quota information."""

    quota: AgentQuota | None
    cached_at: float = field(default_factory=time.monotonic)
    is_active: bool = False


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
    AgentConfigField(
        name="reasoning_effort",
        field_type="select",
        default="high",
        description="LLM reasoning effort level",
        options=["low", "medium", "high"],
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
        default="orchestrator/agent-server:patched",
        description="Docker image for the agent server",
    ),
    AgentConfigField(
        name="reasoning_effort",
        field_type="select",
        default="high",
        description="LLM reasoning effort level",
        options=["low", "medium", "high"],
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

_CODEX_SERVER_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="endpoint",
        field_type="string",
        default="http://localhost:9000",
        description="Codex app server endpoint URL (stdio transport via local process)",
    ),
    AgentConfigField(
        name="model",
        field_type="string",
        description="Model to use for Codex agent sessions",
    ),
    AgentConfigField(
        name="callback_channel",
        field_type="select",
        default="rest",
        description="How the Codex server calls back to the orchestrator",
        options=["rest", "mcp"],
    ),
]

_CODEX_SERVER_REMOTE_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="endpoint",
        field_type="string",
        required=True,
        description="Remote Codex app server endpoint URL (e.g. https://api.example.com)",
    ),
    AgentConfigField(
        name="api_key",
        field_type="secret",
        required=True,
        description="Bearer token for authentication (Authorization: Bearer <token>). Never logged or exposed in API responses.",
    ),
    AgentConfigField(
        name="model",
        field_type="string",
        description="Model to use for Codex agent sessions",
    ),
    AgentConfigField(
        name="callback_channel",
        field_type="select",
        default="rest",
        description="How the Codex server calls back to the orchestrator",
        options=["rest", "mcp"],
    ),
]


def _cli_config_for_command(command: str) -> list[AgentConfigField]:
    """Return CLI config schema with command default pinned to the selected tool."""
    config: list[AgentConfigField] = []
    for cfg_field in _CLI_SUBPROCESS_CONFIG:
        if cfg_field.name == "command":
            config.append(cfg_field.model_copy(update={"default": command}))
        else:
            config.append(cfg_field.model_copy())
    return config


class ToolDetector:
    """Detects which agent backends are available.

    OpenHands local detection checks if the SDK is importable.
    OpenHands Docker detection checks DockerWorkspace importable + docker CLI + daemon.
    CLI tools are detected via shutil.which().
    User Managed is always available.

    Optional *agents* may be passed to enable quota fetching. Each entry must
    have a ``name`` attribute matching an ``AgentOption.name`` value and a
    ``get_quota()`` method matching the Agent protocol. Agents without
    ``get_quota()`` (or when no agents are provided) silently yield
    ``quota=None``.
    """

    def __init__(self, agents: list[Any] | None = None) -> None:
        self._quota_cache: dict[str, _QuotaCacheEntry] = {}
        self._agents: dict[str, Any] = {}
        if agents:
            for agent in agents:
                if hasattr(agent, "name") and hasattr(agent, "get_quota"):
                    self._agents[str(agent.name)] = agent

    def _quota_cache_valid(self, entry: _QuotaCacheEntry) -> bool:
        """Return True if the cache entry is still fresh.

        TTL is 60s for active agents, 300s for inactive ones.
        """
        ttl = 60.0 if entry.is_active else 300.0
        return (time.monotonic() - entry.cached_at) < ttl

    async def _fetch_quota_for_option(self, option: AgentOption) -> AgentQuota | None:
        """Fetch quota for one agent option, consulting the cache first.

        Returns ``None`` immediately for unavailable options or when no
        matching agent with ``get_quota()`` is registered.  Calls
        ``agent.get_quota()`` in a thread with a 3-second timeout; any
        exception (including ``asyncio.TimeoutError``) is swallowed and
        results in ``None``.
        """
        if not option.available:
            return None

        agent = self._agents.get(option.name)
        if agent is None:
            return None

        cache_key = option.name
        cached = self._quota_cache.get(cache_key)
        if cached is not None and self._quota_cache_valid(cached):
            return cached.quota

        try:
            quota: AgentQuota | None = await asyncio.wait_for(
                asyncio.to_thread(agent.get_quota),
                timeout=3.0,
            )
        except Exception:
            quota = None

        self._quota_cache[cache_key] = _QuotaCacheEntry(
            quota=quota,
            is_active=True,
        )
        return quota

    async def detect_all(self) -> list[AgentOption]:
        """Detect all available agent backends and attach cached quota info."""
        options: list[AgentOption] = []
        options.append(self._detect_openhands_local())
        options.append(await self._detect_openhands_docker())
        options.extend(self._detect_cli_tools())
        options.append(self._detect_codex_server())
        options.append(self._detect_codex_server_remote())
        options.append(self._detect_user_managed())

        quotas: list[AgentQuota | None] = list(
            await asyncio.gather(*[self._fetch_quota_for_option(opt) for opt in options])
        )
        return [opt.model_copy(update={"quota": quota}) for opt, quota in zip(options, quotas)]

    def _detect_openhands_local(self) -> AgentOption:
        """Check if the openhands-ai SDK is importable (no server needed)."""
        try:
            import openhands.sdk  # noqa: F401  # pyright: ignore[reportUnusedImport,reportMissingImports]

            return AgentOption(
                agent_type=AgentType.OPENHANDS_LOCAL,
                name="OpenHands (local)",
                title="OpenHands Local Agent",
                description="In-process LLM agent using the OpenHands SDK. Runs entirely locally with no remote server required.",
                available=True,
                detail="openhands-ai SDK installed",
                config_schema=_OPENHANDS_LOCAL_CONFIG,
            )
        except ImportError:
            return AgentOption(
                agent_type=AgentType.OPENHANDS_LOCAL,
                name="OpenHands (local)",
                title="OpenHands Local Agent",
                description="In-process LLM agent using the OpenHands SDK. Runs entirely locally with no remote server required.",
                available=False,
                detail="openhands-ai SDK not installed",
                install_hint="Install with: uv sync --extra openhands",
                config_schema=_OPENHANDS_LOCAL_CONFIG,
            )

    async def _detect_openhands_docker(self) -> AgentOption:
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
                title="OpenHands Docker Agent",
                description="LLM agent running in an isolated Docker container. Provides full sandboxing and reproducible execution environments.",
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
                title="OpenHands Docker Agent",
                description="LLM agent running in an isolated Docker container. Provides full sandboxing and reproducible execution environments.",
                available=False,
                detail="docker CLI not found in PATH",
                install_hint="Install Docker: https://docs.docker.com/get-docker/",
                config_schema=_OPENHANDS_DOCKER_CONFIG,
            )

        # 3. Check docker daemon running
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "info",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            returncode = await asyncio.wait_for(proc.wait(), timeout=10)
            if returncode != 0:
                return AgentOption(
                    agent_type=AgentType.OPENHANDS_DOCKER,
                    name="OpenHands (Docker)",
                    title="OpenHands Docker Agent",
                    description="LLM agent running in an isolated Docker container. Provides full sandboxing and reproducible execution environments.",
                    available=False,
                    detail="Docker daemon not running",
                    install_hint="Start Docker daemon",
                    config_schema=_OPENHANDS_DOCKER_CONFIG,
                )
        except (TimeoutError, FileNotFoundError, OSError):
            return AgentOption(
                agent_type=AgentType.OPENHANDS_DOCKER,
                name="OpenHands (Docker)",
                title="OpenHands Docker Agent",
                description="LLM agent running in an isolated Docker container. Provides full sandboxing and reproducible execution environments.",
                available=False,
                detail="Failed to check Docker daemon status",
                install_hint="Start Docker daemon",
                config_schema=_OPENHANDS_DOCKER_CONFIG,
            )

        return AgentOption(
            agent_type=AgentType.OPENHANDS_DOCKER,
            name="OpenHands (Docker)",
            title="OpenHands Docker Agent",
            description="LLM agent running in an isolated Docker container. Provides full sandboxing and reproducible execution environments.",
            available=True,
            detail="DockerWorkspace available, Docker daemon running",
            config_schema=_OPENHANDS_DOCKER_CONFIG,
        )

    def _detect_cli_tools(self) -> list[AgentOption]:
        """Detect CLI tools available via PATH."""
        results: list[AgentOption] = []

        for tool_name in ("claude", "codex"):
            path = shutil.which(tool_name)
            config_schema = _cli_config_for_command(tool_name)
            if path is not None:
                results.append(
                    AgentOption(
                        agent_type=AgentType.CLI_SUBPROCESS,
                        name=tool_name,
                        title=f"{tool_name.capitalize()} CLI Agent",
                        description=f"Subprocess agent running the {tool_name} CLI tool. Sends prompts via stdin and reads outputs from stdout.",
                        available=True,
                        detail=f"Found at {path}",
                        config_schema=config_schema,
                    )
                )
            else:
                results.append(
                    AgentOption(
                        agent_type=AgentType.CLI_SUBPROCESS,
                        name=tool_name,
                        title=f"{tool_name.capitalize()} CLI Agent",
                        description=f"Subprocess agent running the {tool_name} CLI tool. Sends prompts via stdin and reads outputs from stdout.",
                        available=False,
                        detail=f"{tool_name} not found in PATH",
                        install_hint=f"Install {tool_name} CLI tool",
                        config_schema=config_schema,
                    )
                )

        return results

    def _detect_codex_server(self) -> AgentOption:
        """Check if codex binary is available for running a local app-server process.

        Availability requires the codex CLI to be installed; the detector checks
        PATH only — it does not start or probe the server process at detection time.
        """
        path = shutil.which("codex")
        if path is not None:
            return AgentOption(
                agent_type=AgentType.CODEX_SERVER,
                name="Codex Server",
                title="Codex Server (local)",
                description=(
                    "Managed local Codex app server. Launches `codex app-server` as a "
                    "local process using stdio transport (JSON-RPC over JSONL). Supports "
                    "experimental dynamic tools for orchestrator callbacks."
                ),
                available=True,
                detail=f"codex binary found at {path}",
                config_schema=_CODEX_SERVER_CONFIG,
            )
        return AgentOption(
            agent_type=AgentType.CODEX_SERVER,
            name="Codex Server",
            title="Codex Server (local)",
            description=(
                "Managed local Codex app server. Launches `codex app-server` as a "
                "local process using stdio transport (JSON-RPC over JSONL). Supports "
                "experimental dynamic tools for orchestrator callbacks."
            ),
            available=False,
            detail="codex binary not found in PATH",
            install_hint=(
                "Install the Codex CLI: npm install -g @openai/codex  "
                "(or follow the instructions at https://openai.com/codex)"
            ),
            config_schema=_CODEX_SERVER_CONFIG,
        )

    def _detect_codex_server_remote(self) -> AgentOption:
        """Codex Server Remote connects to an existing remote HTTP endpoint.

        Always reported as available because no local binary is required.
        The caller must supply `endpoint` and `api_key` in the agent config
        before starting a run.
        """
        return AgentOption(
            agent_type=AgentType.CODEX_SERVER_REMOTE,
            name="Codex Server Remote",
            title="Codex Server Remote",
            description=(
                "Remote Codex app server accessible via HTTP. Authenticates using a "
                "static bearer API key (Authorization: Bearer <token>). Configure "
                "`endpoint` and `api_key` before starting a run."
            ),
            available=True,
            detail="Always available; requires endpoint and api_key configuration",
            config_schema=_CODEX_SERVER_REMOTE_CONFIG,
        )

    def _detect_user_managed(self) -> AgentOption:
        """User Managed is always available for external agent connections."""
        return AgentOption(
            agent_type=AgentType.USER_MANAGED,
            name="User Managed",
            title="User Managed Agent",
            description="Passive agent that waits for external actors (humans or third-party tools) to complete work via REST API or MCP.",
            available=True,
            detail="Always available for external agent connections",
            config_schema=_USER_MANAGED_CONFIG,
        )
