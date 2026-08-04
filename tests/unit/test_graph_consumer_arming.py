"""Slice 2.8 — SignalConsumer.arm_graph_run double-arm guard.

arm_graph_run is the shared primitive used by RUN_START, RESUME, and startup
recovery to start (or re-arm) the GraphRunDriver for a run. It must start at
most one driver per run and no-op when no graph runner is configured.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from orchestrator.workflow import SignalConsumer


class _ServiceFactory:
    async def __call__(self, session: Any) -> Any:  # pragma: no cover - unused here
        raise AssertionError("service factory should not be called by arm_graph_run")


def _consumer(graph_runner: Any) -> SignalConsumer:
    return SignalConsumer(
        session_factory=None,  # type: ignore[arg-type]
        create_service=_ServiceFactory(),
        graph_runner=graph_runner,
    )


@pytest.mark.asyncio
async def test_arm_graph_run_starts_once_and_guards_double_arm() -> None:
    started: list[str] = []
    release = asyncio.Event()

    async def runner(run_id: str) -> None:
        started.append(run_id)
        await release.wait()  # keep the driver "running" so the guard is exercised

    consumer = _consumer(runner)

    assert consumer.arm_graph_run("run-1") is True
    # Second arm while the first driver task is still running → guarded.
    assert consumer.arm_graph_run("run-1") is False
    await asyncio.sleep(0)  # let the driver task start
    assert started == ["run-1"]

    # Finish the driver; the run leaves the active set and can be re-armed.
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert consumer.arm_graph_run("run-1") is True
    release.set()


@pytest.mark.asyncio
async def test_arm_graph_run_noop_without_graph_runner() -> None:
    consumer = _consumer(None)
    assert consumer.arm_graph_run("run-1") is False


@pytest.mark.asyncio
async def test_quiesce_graph_run_cancels_and_awaits_before_rearming() -> None:
    started = asyncio.Event()
    stopped = asyncio.Event()
    release = asyncio.Event()

    async def runner(run_id: str) -> None:
        del run_id
        started.set()
        try:
            await release.wait()
        finally:
            stopped.set()

    consumer = _consumer(runner)
    assert consumer.arm_graph_run("run-1") is True
    await started.wait()

    await consumer._quiesce_graph_run("run-1")

    assert stopped.is_set()
    assert "run-1" not in consumer._active_graph_runs
    assert "run-1" not in consumer._graph_driver_tasks
    assert consumer.arm_graph_run("run-1") is True
    await consumer._quiesce_graph_run("run-1")
