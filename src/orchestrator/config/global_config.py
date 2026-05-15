"""Global configuration loading from ~/.orchestrator/config.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from orchestrator.config.models import NudgerConfig as AgentNudgerConfig


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    worktree_base_port: int = 9000


class DatabaseConfig(BaseModel):
    path: str = "orchestrator.db"


class RoutinesConfig(BaseModel):
    dirs: list[str] = []


class AgentsConfig(BaseModel):
    default_type: str | None = None
    openhands_url: str | None = None
    allowed_types: list[str] | None = None
    codex_session_timeout_minutes: int = 120


class DashboardConfig(BaseModel):
    refresh_interval_seconds: int = 5
    max_recent_runs: int = 50


class NudgerConfig(BaseModel):
    check_interval_seconds: int = 60
    nudge_after_seconds: int = 300
    kill_after_seconds: int = 600

    def to_agent_runner_config(self) -> AgentNudgerConfig:
        """Convert to agent NudgerConfig format.

        The global config uses seconds as integers, while the agent runner config
        uses timedeltas for more flexible configuration.
        """
        from datetime import timedelta

        return AgentNudgerConfig(
            output_timeout=timedelta(seconds=self.nudge_after_seconds),
            nudge_interval=timedelta(seconds=self.check_interval_seconds),
            max_nudges=self.kill_after_seconds // self.nudge_after_seconds,
        )


class WebSocketConfig(BaseModel):
    batching_enabled: bool = True
    batch_window_seconds: float = 0.1


class PathsConfig(BaseModel):
    """Paths for repos and worktrees directories."""

    repos_dir: str = "repos"
    worktrees_dir: str = "worktrees"
    worktree_retention_days: int = 14

    def get_repos_path(self, base: Path | None = None) -> Path:
        """Get the resolved repos directory path.

        If repos_dir is relative, resolves against base (or cwd if not provided).
        If repos_dir is absolute, returns it as-is.
        """
        path = Path(self.repos_dir)
        if path.is_absolute():
            return path
        return (base or Path.cwd()) / path

    def get_worktrees_path(self, base: Path | None = None) -> Path:
        """Get the resolved worktrees directory path.

        If worktrees_dir is relative, resolves against base (or cwd if not provided).
        If worktrees_dir is absolute, returns it as-is.
        """
        path = Path(self.worktrees_dir)
        if path.is_absolute():
            return path
        return (base or Path.cwd()) / path


class GlobalConfig(BaseModel):
    server: ServerConfig = ServerConfig()
    database: DatabaseConfig = DatabaseConfig()
    routines: RoutinesConfig = RoutinesConfig()
    agents: AgentsConfig = AgentsConfig()
    dashboard: DashboardConfig = DashboardConfig()
    nudger: NudgerConfig = NudgerConfig()
    websocket: WebSocketConfig = WebSocketConfig()
    paths: PathsConfig = PathsConfig()


class ConfigLoadError(Exception):
    """Raised when configuration file cannot be parsed."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Failed to load config from {path}: {reason}")


DEFAULT_CONFIG_PATH = Path.home() / ".orchestrator" / "config.yaml"


def load_global_config(path: Path | None = None) -> GlobalConfig:
    """Load global configuration from YAML file.

    If path is None, uses ~/.orchestrator/config.yaml.
    If the file doesn't exist, returns defaults.
    Partial YAML is merged with defaults (Pydantic handles this).
    """
    config_path = path or DEFAULT_CONFIG_PATH

    if not config_path.exists():
        return GlobalConfig()

    try:
        raw = config_path.read_text()
        data: Any = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ConfigLoadError(config_path, str(e)) from e

    if data is None:
        return GlobalConfig()

    if not isinstance(data, dict):
        raise ConfigLoadError(config_path, "Expected a YAML mapping at top level")

    try:
        return GlobalConfig.model_validate(data)
    except Exception as e:
        raise ConfigLoadError(config_path, str(e)) from e
