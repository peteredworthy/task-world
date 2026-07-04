"""Tests for the graph startup re-arm selector."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from orchestrator.config import RunStatus
from orchestrator.workflow import select_graph_runs_to_rearm


@dataclass
class _Run:
    id: str
    execution_mode: str
    status: RunStatus
    pause_reason: str | None = None


@pytest.mark.asyncio
async def test_select_graph_startup_rearm_only_includes_graph_runs_with_progress() -> None:
    active_runs = [
        _Run("graph-active-progress", "graph", RunStatus.ACTIVE),
        _Run("graph-active-zero", "graph", RunStatus.ACTIVE),
        _Run("legacy-active-progress", "legacy", RunStatus.ACTIVE),
    ]
    paused_runs = [_Run("graph-paused-recoverable", "graph", RunStatus.PAUSED, "server_shutdown")]
    current_positions = {
        "graph-active-progress": 1,
        "graph-active-zero": 0,
        "legacy-active-progress": 1,
        "graph-paused-recoverable": 0,
    }

    selected = await select_graph_runs_to_rearm(
        active_runs,
        paused_runs,
        current_position_for_run=lambda run_id: _position(current_positions, run_id),
        is_recoverable_pause=lambda reason: reason in ("server_shutdown", "executor_not_started"),
    )

    selected_ids = {run.id for run in selected}
    assert selected_ids == {"graph-active-progress", "graph-paused-recoverable"}


async def _position(positions: dict[str, int], run_id: str) -> int:
    return positions[run_id]
