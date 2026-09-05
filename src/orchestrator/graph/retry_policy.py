"""Canonical finite retry policy for executable graph nodes."""

from __future__ import annotations

from typing import Any


DEFAULT_EXECUTABLE_NODE_MAX_ATTEMPTS = 3
# Canonical agent-handled contract kinds plus their persisted compatibility
# aliases. ``check`` remains included because it is a runtime-dispatched
# executable even though its handler is deterministic rather than an agent.
EXECUTABLE_NODE_KINDS = frozenset(
    {
        "worker",
        "verifier",
        "check",
        "planner",
        "gap_planner",
        "summarizer",
        "oversight",
        "appeal",
        "review",
    }
)


def is_executable_node_kind(kind: object) -> bool:
    return isinstance(kind, str) and kind in EXECUTABLE_NODE_KINDS


def effective_node_max_attempts(kind: object, declared: Any) -> int | None:
    """Resolve legacy missing/zero budgets without changing journal replay."""
    if not is_executable_node_kind(kind):
        return None
    if isinstance(declared, int) and not isinstance(declared, bool) and declared > 0:
        return declared
    return DEFAULT_EXECUTABLE_NODE_MAX_ATTEMPTS


def effective_node_attempt_number(value: Any) -> int:
    """Treat a historical missing/zero counter as its first execution."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return 1
