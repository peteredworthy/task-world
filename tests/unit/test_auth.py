"""Unit tests for JWT authentication pure functions."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from orchestrator.api.auth import (
    AuthConfig,
    InvalidTokenError,
    create_token,
    resolve_auth_config,
    validate_token,
)


def test_resolve_config_disabled() -> None:
    """When auth_disabled is True (or None), returns disabled config."""
    config = resolve_auth_config(auth_disabled=True)
    assert config.auth_disabled is True

    config_default = resolve_auth_config()
    assert config_default.auth_disabled is True


def test_resolve_config_auto_secret() -> None:
    """When auth is enabled with no secret, auto-generates one."""
    config = resolve_auth_config(auth_disabled=False)
    assert config.auth_disabled is False
    assert len(config.jwt_secret) > 0


def test_resolve_config_explicit_secret() -> None:
    """When a secret is provided, uses it as-is."""
    config = resolve_auth_config(auth_disabled=False, jwt_secret="my-secret")
    assert config.jwt_secret == "my-secret"
    assert config.auth_disabled is False


def test_create_and_validate_token() -> None:
    """Round-trip: create a token and validate it."""
    config = AuthConfig(auth_disabled=False, jwt_secret="test-secret")
    token = create_token(config, subject="test-user")
    claims = validate_token(config, token)
    assert claims["sub"] == "test-user"
    assert "exp" in claims
    assert "iat" in claims


def test_validate_expired_token() -> None:
    """Expired tokens raise InvalidTokenError."""
    config = AuthConfig(auth_disabled=False, jwt_secret="test-secret")
    # Create a token that's already expired
    payload = {
        "sub": "test",
        "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    token = jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algorithm)

    with pytest.raises(InvalidTokenError, match="expired"):
        validate_token(config, token)


def test_validate_bad_signature() -> None:
    """Tokens signed with a different secret raise InvalidTokenError."""
    config = AuthConfig(auth_disabled=False, jwt_secret="correct-secret")
    wrong_config = AuthConfig(auth_disabled=False, jwt_secret="wrong-secret")

    token = create_token(wrong_config)

    with pytest.raises(InvalidTokenError, match="signature"):
        validate_token(config, token)


def test_validate_malformed_token() -> None:
    """Malformed tokens raise InvalidTokenError."""
    config = AuthConfig(auth_disabled=False, jwt_secret="test-secret")

    with pytest.raises(InvalidTokenError, match="Malformed"):
        validate_token(config, "not-a-jwt-token")
