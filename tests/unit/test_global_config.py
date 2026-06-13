"""Tests for global configuration loading."""

from pathlib import Path

import pytest

from orchestrator.config.global_config import (
    ConfigLoadError,
    GlobalConfig,
    load_global_config,
)


class TestLoadGlobalConfig:
    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        config = load_global_config(tmp_path / "nonexistent.yaml")
        assert config == GlobalConfig()
        assert config.server.port == 8000
        assert config.database.path == "orchestrator.db"

    def test_empty_file_returns_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        config = load_global_config(config_file)
        assert config == GlobalConfig()

    def test_partial_yaml_merges_with_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("server:\n  port: 9000\n")
        config = load_global_config(config_file)
        assert config.server.port == 9000
        assert config.server.host == "0.0.0.0"  # default preserved
        assert config.database.path == "orchestrator.db"  # other sections default
        assert config.execution.default_execution_mode == "graph"

    def test_full_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
server:
  host: "127.0.0.1"
  port: 3000
database:
  path: "/tmp/test.db"
routines:
  dirs:
    - "~/.orchestrator/routines"
    - "/shared/routines"
agents:
  default_type: "cli_subprocess"
  openhands_url: "http://localhost:3001"
dashboard:
  refresh_interval_seconds: 10
  max_recent_runs: 100
execution:
  default_execution_mode: "legacy"
nudger:
  check_interval_seconds: 30
  nudge_after_seconds: 120
  kill_after_seconds: 300
""")
        config = load_global_config(config_file)
        assert config.server.host == "127.0.0.1"
        assert config.server.port == 3000
        assert config.database.path == "/tmp/test.db"
        assert len(config.routines.dirs) == 2
        assert config.agents.default_type == "cli_subprocess"
        assert config.dashboard.max_recent_runs == 100
        assert config.execution.default_execution_mode == "legacy"
        assert config.nudger.nudge_after_seconds == 120

    def test_invalid_yaml_raises_config_load_error(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("server:\n  port: [invalid yaml\n")
        with pytest.raises(ConfigLoadError):
            load_global_config(config_file)

    def test_non_dict_yaml_raises_config_load_error(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("- just\n- a\n- list\n")
        with pytest.raises(ConfigLoadError):
            load_global_config(config_file)

    def test_agents_config_defaults(self) -> None:
        config = GlobalConfig()
        assert config.agents.default_type is None
        assert config.agents.openhands_url is None
        assert config.agents.allowed_types is None
        assert config.agents.codex_session_timeout_minutes == 120

    def test_execution_config_defaults_to_graph(self) -> None:
        config = GlobalConfig()
        assert config.execution.default_execution_mode == "graph"
