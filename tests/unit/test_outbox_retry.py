"""Unit tests for OutboxDispatcher transient DB-lock retry (db-locked incident)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import OperationalError

from orchestrator.graph_runtime.outbox import OutboxDispatcher, _is_sqlite_locked


class _Clock:
    def now(self) -> datetime:
        return datetime(2025, 1, 1, tzinfo=timezone.utc)


def _locked_error() -> OperationalError:
    return OperationalError("UPDATE graph_outbox", {}, Exception("database is locked"))


def _dispatcher() -> OutboxDispatcher:
    # _retry_locked touches none of these collaborators, so stand-ins suffice.
    return OutboxDispatcher(
        session_factory=None,  # type: ignore[arg-type]
        executor=None,  # type: ignore[arg-type]
        clock=_Clock(),
    )


def test_is_sqlite_locked_matches_contention_errors() -> None:
    assert _is_sqlite_locked(_locked_error())
    assert _is_sqlite_locked(OperationalError("x", {}, Exception("database is busy")))
    assert not _is_sqlite_locked(OperationalError("x", {}, Exception("no such table")))


async def test_retry_locked_recovers_after_transient_lock() -> None:
    dispatcher = _dispatcher()
    attempts = 0

    async def op() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _locked_error()
        return "ok"

    result = await dispatcher._retry_locked(op, base_delay=0.0)

    assert result == "ok"
    assert attempts == 3


async def test_retry_locked_reraises_after_exhausting_attempts() -> None:
    dispatcher = _dispatcher()
    attempts = 0

    async def op() -> str:
        nonlocal attempts
        attempts += 1
        raise _locked_error()

    with pytest.raises(OperationalError):
        await dispatcher._retry_locked(op, attempts=3, base_delay=0.0)

    assert attempts == 3


async def test_retry_locked_does_not_retry_non_lock_errors() -> None:
    dispatcher = _dispatcher()
    attempts = 0

    async def op() -> str:
        nonlocal attempts
        attempts += 1
        raise OperationalError("x", {}, Exception("no such table"))

    with pytest.raises(OperationalError):
        await dispatcher._retry_locked(op, base_delay=0.0)

    assert attempts == 1
