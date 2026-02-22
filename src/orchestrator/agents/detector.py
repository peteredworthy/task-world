"""Detect available agent tools on the system."""

import asyncio
import shutil
import time
from dataclasses import dataclass, field
from typing import Any

from orchestrator.agents.codex_server_common import fetch_codex_models
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


def _codex_server_config_with_models(models: list[str]) -> list[AgentConfigField]:
    """Return the Codex Server config schema with the model field populated.

    When *models* is non-empty the model field is upgraded to a ``"select"``
    with the discovered model IDs as options and the first entry as the
    default.  When empty the field stays as a plain ``"string"`` with no
    options, preserving the existing behaviour.

    Args:
        models: Ordered list of model ID strings returned by
            ``fetch_codex_models()``.

    Returns:
        A new config schema list with the model field updated.
    """
    config: list[AgentConfigField] = []
    for cfg_field in _CODEX_SERVER_CONFIG:
        if cfg_field.name == "model" and models:
            config.append(
                cfg_field.model_copy(
                    update={
                        "field_type": "select",
                        "options": models,
                        "default": models[0],
                    }
                )
            )
        else:
            config.append(cfg_field.model_copy())
    return config


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

_CLAUDE_SDK_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="model",
        field_type="string",
        default="claude-sonnet-4-5",
        description="Claude model to use (e.g. claude-sonnet-4-5, claude-opus-4-5)",
    ),
    AgentConfigField(
        name="api_key",
        field_type="secret",
        description=(
            "Anthropic API key (optional). Falls back to ANTHROPIC_API_KEY env var, "
            "then the Claude CLI OAuth token from the macOS keychain (`claude auth login`)."
        ),
    ),
    AgentConfigField(
        name="auth_token",
        field_type="secret",
        description=(
            "Anthropic OAuth bearer token (optional). Falls back to ANTHROPIC_AUTH_TOKEN env var, "
            "then the Claude CLI OAuth token from the macOS keychain."
        ),
    ),
    AgentConfigField(
        name="max_tokens",
        field_type="number",
        default=4096,
        description="Maximum tokens per response turn",
    ),
    AgentConfigField(
        name="max_iterations",
        field_type="number",
        default=50,
        description="Maximum agentic loop iterations per run",
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
        options.append(self._detect_claude_sdk())
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
        """Detect CLI tools available via PATH.

        For the ``codex`` CLI entry, model options are fetched from the Codex
        app server via ``fetch_codex_models()``.  When successful, the
        ``model`` config field becomes a ``select`` with the available model
        IDs and the first model set as the default.  When model discovery
        fails (codex not found, server unreachable, etc.) the field stays as
        a plain ``string`` — existing behaviour is preserved.
        """
        results: list[AgentOption] = []

        for tool_name in ("claude", "codex"):
            path = shutil.which(tool_name)
            if tool_name == "codex" and path is not None:
                # Attempt to discover available models from the Codex API server.
                models = fetch_codex_models()
                config_schema = self._cli_config_for_codex(tool_name, models)
            else:
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

    @staticmethod
    def _cli_config_for_codex(command: str, models: list[str]) -> list[AgentConfigField]:
        """Return the CLI config schema for ``codex`` with model options populated.

        When *models* is non-empty the ``model`` field is upgraded to a
        ``"select"`` with the discovered IDs as options and the first entry
        as the default.  When empty the field stays as a plain
        ``"string"`` — identical to the baseline ``_cli_config_for_command``
        output.

        Args:
            command: The CLI command name (e.g. ``"codex"``).
            models: Ordered list of model ID strings returned by
                ``fetch_codex_models()``.

        Returns:
            A config schema list with the ``command`` default pinned and the
            ``model`` field updated when models are available.
        """
        config: list[AgentConfigField] = []
        for cfg_field in _CLI_SUBPROCESS_CONFIG:
            if cfg_field.name == "command":
                config.append(cfg_field.model_copy(update={"default": command}))
            elif cfg_field.name == "model" and models:
                config.append(
                    cfg_field.model_copy(
                        update={
                            "field_type": "select",
                            "options": models,
                            "default": models[0],
                        }
                    )
                )
            else:
                config.append(cfg_field.model_copy())
        return config

    def _detect_codex_server(self) -> AgentOption:
        """Check if codex binary is available for running a local app-server process.

        When the binary is present, ``fetch_codex_models()`` is called to
        discover the models the Codex API server exposes.  If successful, the
        ``model`` config field is upgraded to a ``"select"`` with the
        available model IDs and the first model set as the default value.
        When model discovery fails the field stays as a plain ``"string"``.
        """
        path = shutil.which("codex")
        if path is not None:
            # Attempt to discover available models from the Codex API server.
            models = fetch_codex_models()
            config_schema = _codex_server_config_with_models(models)
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
                config_schema=config_schema,
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

    def _detect_claude_sdk(self) -> AgentOption:
        """Check if the anthropic SDK is importable for in-process Claude execution.

        Availability requires the anthropic package to be installed.
        """
        try:
            import anthropic  # noqa: F401  # pyright: ignore[reportUnusedImport]

            return AgentOption(
                agent_type=AgentType.CLAUDE_SDK,
                name="Claude SDK",
                title="Claude SDK Agent",
                description=(
                    "In-process Claude agent using the Anthropic Python SDK. "
                    "Runs entirely locally with no subprocess required — calls "
                    "the Anthropic API directly via the Messages API with tool use."
                ),
                available=True,
                detail="anthropic SDK installed",
                config_schema=_CLAUDE_SDK_CONFIG,
            )
        except ImportError:
            return AgentOption(
                agent_type=AgentType.CLAUDE_SDK,
                name="Claude SDK",
                title="Claude SDK Agent",
                description=(
                    "In-process Claude agent using the Anthropic Python SDK. "
                    "Runs entirely locally with no subprocess required — calls "
                    "the Anthropic API directly via the Messages API with tool use."
                ),
                available=False,
                detail="anthropic SDK not installed",
                install_hint="Install with: pip install anthropic",
                config_schema=_CLAUDE_SDK_CONFIG,
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
