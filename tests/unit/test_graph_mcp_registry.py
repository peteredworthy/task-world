"""Unit tests for GraphMcpExecutionRegistry."""

from __future__ import annotations

from orchestrator.graph_runtime.graph_mcp_registry import GraphMcpExecutionRegistry


def test_get_returns_none_for_unknown_token() -> None:
    registry = GraphMcpExecutionRegistry()
    assert registry.get("unknown-token") is None


def test_register_then_get_returns_the_same_app() -> None:
    registry = GraphMcpExecutionRegistry()
    sentinel = object()
    registry.register("tok1", sentinel)
    assert registry.get("tok1") is sentinel


def test_unregister_removes_the_entry() -> None:
    registry = GraphMcpExecutionRegistry()
    registry.register("tok1", object())
    registry.unregister("tok1")
    assert registry.get("tok1") is None


def test_unregister_unknown_token_is_a_no_op() -> None:
    registry = GraphMcpExecutionRegistry()
    registry.unregister("never-registered")  # must not raise
