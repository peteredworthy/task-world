"""Detect available agent tools on the system."""

import asyncio
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from orchestrator.runners.agents.claude_sdk.agent import fetch_claude_models
from orchestrator.runners.agents.codex.common import fetch_codex_models
from orchestrator.runners.types import AgentConfigField, AgentOption, AgentQuota
from orchestrator.config.enums import AgentRunnerType


@dataclass
class _QuotaCacheEntry:
    """Cache entry for agent quota information."""

    quota: AgentQuota | None
    cached_at: float = field(default_factory=time.monotonic)
    is_active: bool = False
    last_success_quota: AgentQuota | None = None
    last_success_at: float | None = None  # wall-clock time.time() of last success
    retry_after: float = 0.0  # monotonic time before which no retry should be attempted


# --- Config schemas for each agent type ---

_OPENHANDS_LOCAL_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="model",
        field_type="string",
        default="gpt-5-mini",
        description="LLM model to use",
    ),
    AgentConfigField(
        name="max_iterations",
        field_type="number",
        default=100,
        description="Maximum agent iterations per run",
    ),
    AgentConfigField(
        name="max_actions",
        field_type="number",
        default=200,
        description="Hard ceiling on total agent actions (0 = disabled)",
    ),
    AgentConfigField(
        name="reasoning_effort",
        field_type="select",
        default="high",
        description="LLM reasoning effort level",
        options=["low", "medium", "high"],
    ),
    AgentConfigField(
        name="base_url",
        field_type="string",
        description="Local LLM base URL (e.g. http://localhost:1234/v1). Leave blank to use OpenAI.",
    ),
    AgentConfigField(
        name="timeout",
        field_type="number",
        default=1800,
        description="HTTP request timeout in seconds. Local LLMs may need 900-1800+.",
    ),
    AgentConfigField(
        name="model_canonical_name",
        field_type="string",
        description="Canonical model name for capability lookups (e.g. openai/gpt-4o). Required when using a local LLM with a custom model name.",
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
        name="max_iterations",
        field_type="number",
        default=100,
        description="Maximum agent iterations per run",
    ),
    AgentConfigField(
        name="max_actions",
        field_type="number",
        default=200,
        description="Hard ceiling on total agent actions (0 = disabled)",
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
    AgentConfigField(
        name="base_url",
        field_type="string",
        description="Local LLM base URL (e.g. http://localhost:1234/v1). Leave blank to use OpenAI.",
    ),
    AgentConfigField(
        name="timeout",
        field_type="number",
        default=1800,
        description="HTTP request timeout in seconds. Local LLMs may need 900-1800+.",
    ),
    AgentConfigField(
        name="model_canonical_name",
        field_type="string",
        description="Canonical model name for capability lookups (e.g. openai/gpt-4o). Required when using a local LLM with a custom model name.",
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
        name="model",
        field_type="string",
        description="Model to use for Codex agent sessions",
        allow_custom=True,
    ),
    AgentConfigField(
        name="callback_channel",
        field_type="select",
        default="rest",
        description="How the Codex server calls back to the orchestrator",
        options=["rest", "mcp"],
    ),
    AgentConfigField(
        name="restrictions",
        field_type="select",
        default="no-network",
        description=(
            "How strictly to sandbox Codex. "
            "'none' runs with workspace-write and network enabled. "
            "'no-network' forces workspace-write with network disabled. "
            "'use-local' hands control to your local Codex config.toml (may be read-only)."
        ),
        options=["none", "no-network", "use-local"],
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


def _claude_sdk_config_with_models(models: list[str]) -> list[AgentConfigField]:
    """Return the Claude SDK config schema with the model field populated.

    When *models* is non-empty the model field is upgraded to a ``"select"``
    with the discovered model IDs as options and the first entry as the
    default.  When empty the field stays as a plain ``"string"`` with the
    existing default, preserving the existing behaviour.

    Args:
        models: Ordered list of model ID strings returned by
            ``fetch_claude_models()``.

    Returns:
        A new config schema list with the model field updated.
    """
    config: list[AgentConfigField] = []
    for cfg_field in _CLAUDE_SDK_CONFIG:
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
        name="max_turns",
        field_type="number",
        default=50,
        description="Maximum agentic turns per run",
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

    def __init__(self, agents: list[Any] | None = None, *, quota_timeout: float = 10.0) -> None:
        self._quota_cache: dict[str, _QuotaCacheEntry] = {}
        self._quota_timeout = quota_timeout
        self._agents: dict[str, Any] = {}
        if agents:
            for agent in agents:
                if hasattr(agent, "name") and hasattr(agent, "get_quota"):
                    self._agents[str(agent.name)] = agent

    def _quota_cache_valid(self, entry: _QuotaCacheEntry) -> bool:
        """Return True if the cache entry is still fresh.

        TTL is 300s for active agents, 600s for inactive ones.
        The usage API is aggressively rate-limited so we cache generously.
        """
        ttl = 300.0 if entry.is_active else 600.0
        return (time.monotonic() - entry.cached_at) < ttl

    @staticmethod
    def _quota_with_fetched_at(entry: _QuotaCacheEntry) -> AgentQuota | None:
        """Return a copy of the entry's quota stamped with ``fetched_at``."""
        quota = entry.quota
        if quota is None:
            return None
        fetched_at: str | None = None
        if entry.last_success_at is not None:
            fetched_at = datetime.fromtimestamp(entry.last_success_at, tz=timezone.utc).isoformat()
        return quota.model_copy(update={"fetched_at": fetched_at})

    async def _fetch_quota_for_option(self, option: AgentOption) -> AgentQuota | None:
        """Fetch quota for one agent option, consulting the cache first.

        Returns ``None`` immediately for unavailable options or when no
        matching agent with ``get_quota()`` is registered.  Calls
        ``agent.get_quota()`` in a thread with a 10-second timeout; any
        exception (including ``asyncio.TimeoutError``) is swallowed and
        the last successful quota is returned instead.

        After a failure, a 5-minute backoff is applied before the next
        fetch attempt, returning the stale-but-good value in the interim.
        """
        if not option.available:
            return None

        agent = self._agents.get(option.name)
        if agent is None:
            return None

        cache_key = option.name
        cached = self._quota_cache.get(cache_key)

        # 1. Fresh cache → return immediately
        if cached is not None and self._quota_cache_valid(cached):
            return self._quota_with_fetched_at(cached)

        # 2. Within retry backoff → return stale value without fetching
        now_mono = time.monotonic()
        if cached is not None and now_mono < cached.retry_after:
            return self._quota_with_fetched_at(cached)

        try:
            quota: AgentQuota | None = await asyncio.wait_for(
                asyncio.to_thread(agent.get_quota),
                timeout=self._quota_timeout,
            )
        except Exception:
            # Failure: preserve last successful quota, apply 5-min backoff
            last_success_quota = cached.last_success_quota if cached else None
            last_success_at = cached.last_success_at if cached else None
            self._quota_cache[cache_key] = _QuotaCacheEntry(
                quota=last_success_quota,
                is_active=True,
                last_success_quota=last_success_quota,
                last_success_at=last_success_at,
                retry_after=time.monotonic() + 300.0,
            )
            return self._quota_with_fetched_at(self._quota_cache[cache_key])

        # Success: update all fields
        now_wall = time.time()
        self._quota_cache[cache_key] = _QuotaCacheEntry(
            quota=quota,
            is_active=True,
            last_success_quota=quota,
            last_success_at=now_wall,
        )
        return self._quota_with_fetched_at(self._quota_cache[cache_key])

    async def detect_all(self) -> list[AgentOption]:
        """Detect all available agent backends and attach cached quota info."""
        options: list[AgentOption] = []
        options.append(self._detect_openhands_local())
        options.append(await self._detect_openhands_docker())
        options.extend(self._detect_cli_tools())
        options.append(self._detect_codex_server())
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
                agent_type=AgentRunnerType.OPENHANDS_LOCAL,
                name="OpenHands (local)",
                title="OpenHands Local Agent",
                description="In-process LLM agent using the OpenHands SDK. Runs entirely locally with no remote server required.",
                available=True,
                detail="openhands-ai SDK installed",
                config_schema=_OPENHANDS_LOCAL_CONFIG,
            )
        except ImportError:
            return AgentOption(
                agent_type=AgentRunnerType.OPENHANDS_LOCAL,
                name="OpenHands (local)",
                title="OpenHands Local Agent",
                description="In-process LLM agent using the OpenHands SDK. Runs entirely locally with no remote server required.",
                available=True,
                detail="openhands-ai SDK not installed (will fail at runtime)",
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
                agent_type=AgentRunnerType.OPENHANDS_DOCKER,
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
                agent_type=AgentRunnerType.OPENHANDS_DOCKER,
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
                    agent_type=AgentRunnerType.OPENHANDS_DOCKER,
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
                agent_type=AgentRunnerType.OPENHANDS_DOCKER,
                name="OpenHands (Docker)",
                title="OpenHands Docker Agent",
                description="LLM agent running in an isolated Docker container. Provides full sandboxing and reproducible execution environments.",
                available=False,
                detail="Failed to check Docker daemon status",
                install_hint="Start Docker daemon",
                config_schema=_OPENHANDS_DOCKER_CONFIG,
            )

        return AgentOption(
            agent_type=AgentRunnerType.OPENHANDS_DOCKER,
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
            elif tool_name == "claude" and path is not None:
                # Attempt to discover available models from the Anthropic API.
                models = fetch_claude_models()
                config_schema = self._cli_config_for_codex(tool_name, models)
            else:
                config_schema = _cli_config_for_command(tool_name)

            if path is not None:
                results.append(
                    AgentOption(
                        agent_type=AgentRunnerType.CLI_SUBPROCESS,
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
                        agent_type=AgentRunnerType.CLI_SUBPROCESS,
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
                agent_type=AgentRunnerType.CODEX_SERVER,
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
            agent_type=AgentRunnerType.CODEX_SERVER,
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

    def _detect_claude_sdk(self) -> AgentOption:
        """Check if the Claude Agent SDK is importable for in-process execution.

        Availability requires the ``claude-agent-sdk`` package to be installed.
        When available, ``fetch_claude_models()`` is called to discover the
        models exposed by the Anthropic API.  If successful, the ``model``
        config field is upgraded to a ``"select"`` with the available model IDs
        and the first model set as the default value.  When model discovery
        fails the field stays as a plain ``"string"``.
        """
        try:
            import claude_agent_sdk  # noqa: F401  # pyright: ignore[reportUnusedImport]

            models = fetch_claude_models()
            config_schema = _claude_sdk_config_with_models(models)
            return AgentOption(
                agent_type=AgentRunnerType.CLAUDE_SDK,
                name="Claude SDK",
                title="Claude SDK Agent",
                description=(
                    "In-process Claude agent using the Claude Agent SDK. "
                    "Runs locally with built-in tools (Read, Write, Edit, Bash, etc.) "
                    "and orchestrator callbacks exposed via an in-process MCP server."
                ),
                available=True,
                detail="claude-agent-sdk installed",
                config_schema=config_schema,
            )
        except ImportError:
            return AgentOption(
                agent_type=AgentRunnerType.CLAUDE_SDK,
                name="Claude SDK",
                title="Claude SDK Agent",
                description=(
                    "In-process Claude agent using the Claude Agent SDK. "
                    "Runs locally with built-in tools (Read, Write, Edit, Bash, etc.) "
                    "and orchestrator callbacks exposed via an in-process MCP server."
                ),
                available=False,
                detail="claude-agent-sdk not installed",
                install_hint="Install with: uv add claude-agent-sdk",
                config_schema=_CLAUDE_SDK_CONFIG,
            )

    def _detect_user_managed(self) -> AgentOption:
        """User Managed is always available for external agent connections."""
        return AgentOption(
            agent_type=AgentRunnerType.USER_MANAGED,
            name="User Managed",
            title="User Managed Agent",
            description="Passive agent that waits for external actors (humans or third-party tools) to complete work via REST API or MCP.",
            available=True,
            detail="Always available for external agent connections",
            config_schema=_USER_MANAGED_CONFIG,
        )


# Mapping from AgentRunnerType to the set of valid config field names.
# Used by the API layer to reject unknown agent_config keys at creation time.
AGENT_CONFIG_FIELDS: dict[AgentRunnerType, set[str]] = {
    AgentRunnerType.OPENHANDS_LOCAL: {f.name for f in _OPENHANDS_LOCAL_CONFIG},
    AgentRunnerType.OPENHANDS_DOCKER: {f.name for f in _OPENHANDS_DOCKER_CONFIG},
    AgentRunnerType.CLI_SUBPROCESS: {f.name for f in _CLI_SUBPROCESS_CONFIG},
    AgentRunnerType.USER_MANAGED: {f.name for f in _USER_MANAGED_CONFIG},
    AgentRunnerType.CODEX_SERVER: {f.name for f in _CODEX_SERVER_CONFIG},
    AgentRunnerType.CLAUDE_SDK: {f.name for f in _CLAUDE_SDK_CONFIG},
}
