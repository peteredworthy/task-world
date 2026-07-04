"""Startup recovery selection for graph-execution runs.

The actual recovery work (recover() + reconcile_runtime()) happens inside
``GraphRunDriver.run()`` when a graph run is re-armed, so a single executor
spans recovery and the drive loop. This module only decides *which* runs to
re-arm on startup; the lifespan handler in ``api/app.py`` enumerates runs and
arms each selected one through the SignalConsumer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from orchestrator.config.enums import RunStatus


def select_graph_runs_to_recover(
    runs: Iterable[Any],
    *,
    is_recoverable_pause: Callable[[str | None], bool],
) -> list[Any]:
    """Return graph-mode runs that should be re-armed on startup.

    A graph run is recovered only when PAUSED with a restart-recoverable pause
    reason. ACTIVE graph rows are not automatically re-armed on startup because
    historical orphaned graph drivers can hold leases/outbox work and contend
    with fresh runs. Operators can resume or recover those runs explicitly.
    Legacy runs are never selected here — they are handled by the legacy startup
    recovery path.
    """
    selected: list[Any] = []
    for run in runs:
        if getattr(run, "execution_mode", "legacy") != "graph":
            continue
        status = getattr(run, "status", None)
        if status == RunStatus.PAUSED and is_recoverable_pause(getattr(run, "pause_reason", None)):
            selected.append(run)
    return selected


async def select_graph_runs_to_rearm(
    active_runs: Iterable[Any],
    paused_runs: Iterable[Any],
    *,
    current_position_for_run: Callable[[str], Awaitable[int]],
    is_recoverable_pause: Callable[[str | None], bool],
) -> list[Any]:
    """Return graph runs that should be re-armed on startup.

    ACTIVE graph runs are selected only when their durable graph position is
    non-zero. That means the run already has graph history and was stranded by
    a killed in-process driver, so re-arming it resumes the existing graph
    instead of seeding a fresh one.
    """
    selected: list[Any] = []
    for run in active_runs:
        if getattr(run, "execution_mode", "legacy") != "graph":
            continue
        if await current_position_for_run(run.id) > 0:
            selected.append(run)

    selected.extend(
        select_graph_runs_to_recover(paused_runs, is_recoverable_pause=is_recoverable_pause)
    )
    return selected
