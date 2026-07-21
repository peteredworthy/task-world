"""Tests for ``make_graph_runner``'s base_url threading into the graph runtime builder.

Regression coverage for a whole-branch review finding: the graph MCP base_url
was hardcoded to http://localhost:8000 deep in build_graph_runtime's default,
and nothing in the make_graph_runner -> GraphRunDriver call chain ever
overrode it, so orchestrator instances listening on other ports (worktree
agents, dev instances) handed subprocess agents an unreachable graph MCP URL.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from orchestrator.api.deps import make_graph_runner


async def test_make_graph_runner_threads_base_url_into_runtime_builder() -> None:
    """base_url passed to make_graph_runner ends up in the runtime_builder partial."""
    session_factory = MagicMock()
    service_factory = AsyncMock()

    run_callback = make_graph_runner(
        session_factory,
        service_factory,
        base_url="http://localhost:9999",
    )

    captured_kwargs: dict[str, Any] = {}

    class _FakeDriver:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)

        async def run(self, run_id: str) -> None:
            return None

    with patch("orchestrator.workflow.graph_driver.GraphRunDriver", _FakeDriver):
        await run_callback("run-1")

    runtime_builder = captured_kwargs["runtime_builder"]
    assert runtime_builder.keywords["base_url"] == "http://localhost:9999"


async def test_make_graph_runner_defaults_base_url_when_not_provided() -> None:
    """Without an explicit base_url, the runtime_builder falls back to :8000."""
    session_factory = MagicMock()
    service_factory = AsyncMock()

    run_callback = make_graph_runner(session_factory, service_factory)

    captured_kwargs: dict[str, Any] = {}

    class _FakeDriver:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)

        async def run(self, run_id: str) -> None:
            return None

    with patch("orchestrator.workflow.graph_driver.GraphRunDriver", _FakeDriver):
        await run_callback("run-1")

    runtime_builder = captured_kwargs["runtime_builder"]
    assert runtime_builder.keywords["base_url"] == "http://localhost:8000"
