"""Startup recovery selection for graph-execution runs.

The actual recovery work (recover() + reconcile_runtime()) happens inside
``GraphRunDriver.run()`` when a graph run is re-armed, so a single executor
spans recovery and the drive loop. This module only decides *which* runs to
re-arm on startup; the lifespan handler in ``api/app.py`` enumerates runs and
arms each selected one through the SignalConsumer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from orchestrator.config.enums import RunStatus


def select_graph_runs_to_recover(
    runs: Iterable[Any],
    *,
    is_recoverable_pause: Callable[[str | None], bool],
) -> list[Any]:
    """Return graph-mode runs that should be re-armed on startup.

    A graph run is recovered when it is ACTIVE (orphaned when a reload cancelled
    its driver task) or PAUSED with a restart-recoverable pause reason. Legacy
    runs are never selected here — they are handled by the legacy startup
    recovery path.
    """
    selected: list[Any] = []
    for run in runs:
        if getattr(run, "execution_mode", "legacy") != "graph":
            continue
        status = getattr(run, "status", None)
        if status == RunStatus.ACTIVE:
            selected.append(run)
        elif status == RunStatus.PAUSED and is_recoverable_pause(
            getattr(run, "pause_reason", None)
        ):
            selected.append(run)
    return selected
