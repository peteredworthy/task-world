"""Tests for environment file resolution logic."""

from typing import Any

from orchestrator.config.models import EnvFileConfig
from orchestrator.envfiles.resolution import resolve_env_specs


def test_resolve_from_routine_config():
    """Test resolving env specs from routine config only."""
    routine_specs = [
        EnvFileConfig(path=".env", promote_on_success=True),
        EnvFileConfig(path=".secrets.json", promote_on_success=False),
    ]

    result = resolve_env_specs(routine_specs=routine_specs)

    assert len(result) == 2
    assert result[0].relative_path == ".env"
    assert result[0].promote_on_success is True
    assert result[1].relative_path == ".secrets.json"
    assert result[1].promote_on_success is False


def test_resolve_request_overrides_routine():
    """Test that request specs completely override routine specs."""
    routine_specs = [
        EnvFileConfig(path=".env", promote_on_success=True),
    ]

    request_specs = [
        {"path": "custom.env", "promote_on_success": False},
        {"path": "override.json", "promote_on_success": True},
    ]

    result = resolve_env_specs(routine_specs=routine_specs, request_specs=request_specs)

    assert len(result) == 2
    assert result[0].relative_path == "custom.env"
    assert result[0].promote_on_success is False
    assert result[1].relative_path == "override.json"
    assert result[1].promote_on_success is True


def test_resolve_empty_returns_empty():
    """Test that no specs returns empty list."""
    result = resolve_env_specs()

    assert result == []


def test_resolve_routine_only():
    """Test routine specs when request is explicitly None."""
    routine_specs = [
        EnvFileConfig(path=".env", promote_on_success=False),
    ]

    result = resolve_env_specs(routine_specs=routine_specs, request_specs=None)

    assert len(result) == 1
    assert result[0].relative_path == ".env"
    assert result[0].promote_on_success is False


def test_resolve_with_promote_flag():
    """Test that promote_on_success flag is correctly propagated."""
    routine_specs = [
        EnvFileConfig(path="dev.env", promote_on_success=True),
        EnvFileConfig(path="test.env", promote_on_success=False),
    ]

    result = resolve_env_specs(routine_specs=routine_specs)

    assert result[0].promote_on_success is True
    assert result[1].promote_on_success is False


def test_resolve_request_with_path_alias():
    """Test that both 'path' and 'relative_path' keys work in request specs."""
    request_specs = [
        {"relative_path": "alt.env", "promote_on_success": False},
    ]

    result = resolve_env_specs(request_specs=request_specs)

    assert len(result) == 1
    assert result[0].relative_path == "alt.env"
    assert result[0].promote_on_success is False


def test_resolve_request_empty_list_overrides_routine():
    """Test that empty request list completely overrides routine specs."""
    routine_specs = [
        EnvFileConfig(path=".env", promote_on_success=True),
    ]

    request_specs: list[dict[str, Any]] = []

    result = resolve_env_specs(routine_specs=routine_specs, request_specs=request_specs)

    assert result == []


def test_resolve_defaults_promote_on_success_to_false():
    """Test that promote_on_success defaults to False when not provided."""
    request_specs = [
        {"path": "test.env"},  # No promote_on_success
    ]

    result = resolve_env_specs(request_specs=request_specs)

    assert len(result) == 1
    assert result[0].promote_on_success is False
