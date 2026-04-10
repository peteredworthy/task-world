"""JWT authentication for the Orchestrator API.

Auth is disabled by default (AUTH_DISABLED=true) for zero-friction local
development. When enabled, uses HS256 JWT tokens with an auto-generated
secret if none is provided.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pydantic
from fastapi import Header, HTTPException, Query


class AuthConfig(pydantic.BaseModel):
    """Authentication configuration."""

    auth_disabled: bool = True
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    token_expiry_hours: int = 720  # 30 days


class AuthError(Exception):
    """Base authentication error."""


class InvalidTokenError(AuthError):
    """Token is invalid, expired, or has a bad signature."""


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def resolve_auth_config(
    auth_disabled: bool | None = None,
    jwt_secret: str | None = None,
) -> AuthConfig:
    """Build an AuthConfig, auto-generating a secret when needed.

    Args:
        auth_disabled: Explicit flag. Defaults to True if None.
        jwt_secret: Explicit secret. Auto-generated if empty/None when auth is enabled.
    """
    disabled = auth_disabled if auth_disabled is not None else True
    secret = jwt_secret or ""

    if not disabled and not secret:
        secret = secrets.token_urlsafe(32)

    return AuthConfig(auth_disabled=disabled, jwt_secret=secret)


def create_token(config: AuthConfig, subject: str = "orchestrator") -> str:
    """Create a signed JWT token.

    Args:
        config: Auth configuration with secret and algorithm.
        subject: The ``sub`` claim value.

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(hours=config.token_expiry_hours),
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algorithm)


def validate_token(config: AuthConfig, token: str) -> dict[str, Any]:
    """Validate and decode a JWT token.

    Args:
        config: Auth configuration with secret and algorithm.
        token: The JWT string to validate.

    Returns:
        Decoded claims dictionary.

    Raises:
        InvalidTokenError: If the token is expired, has a bad signature, or is malformed.
    """
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            config.jwt_secret,
            algorithms=[config.jwt_algorithm],
        )
        return claims
    except jwt.ExpiredSignatureError as e:
        raise InvalidTokenError("Token has expired") from e
    except jwt.InvalidSignatureError as e:
        raise InvalidTokenError("Invalid token signature") from e
    except jwt.DecodeError as e:
        raise InvalidTokenError("Malformed token") from e
    except jwt.InvalidTokenError as e:
        raise InvalidTokenError(str(e)) from e


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


def get_require_auth(config: AuthConfig) -> Any:
    """Create a require_auth dependency bound to a specific AuthConfig.

    Returns a FastAPI dependency function that checks the Authorization
    header against the provided config.
    """

    async def _require_auth(
        authorization: str | None = Header(None),
    ) -> dict[str, Any] | None:
        if config.auth_disabled:
            return None

        if not authorization:
            raise HTTPException(status_code=401, detail="Missing authorization header")

        # Expect "Bearer <token>"
        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization format")

        try:
            return validate_token(config, parts[1])
        except InvalidTokenError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e

    return _require_auth


def get_require_ws_auth(config: AuthConfig) -> Any:
    """Create a WebSocket auth dependency bound to a specific AuthConfig.

    WebSocket auth uses a ``?token=`` query parameter since WebSocket
    connections cannot set custom headers.
    """

    async def _require_ws_auth(
        token: str | None = Query(None),
    ) -> dict[str, Any] | None:
        if config.auth_disabled:
            return None

        if not token:
            raise HTTPException(status_code=401, detail="Missing token query parameter")

        try:
            return validate_token(config, token)
        except InvalidTokenError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e

    return _require_ws_auth
