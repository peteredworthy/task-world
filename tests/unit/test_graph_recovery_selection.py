from __future__ import annotations

from dataclasses import dataclass

from orchestrator.config.enums import RunStatus
from orchestrator.workflow.graph_recovery import select_graph_runs_to_recover


@dataclass
class _Run:
    id: str
    execution_mode: str
    status: RunStatus
    pause_reason: str | None = None


def _recoverable(reason: str | None) -> bool:
    return reason in ("server_shutdown", "executor_not_started")


def test_selects_recoverable_paused_graph_runs_but_not_active_rows() -> None:
    runs = [
        _Run("active-graph", "graph", RunStatus.ACTIVE),
        _Run("paused-recoverable-graph", "graph", RunStatus.PAUSED, "server_shutdown"),
        _Run("paused-blocked-graph", "graph", RunStatus.PAUSED, "graph_blocked"),
        _Run("active-legacy", "legacy", RunStatus.ACTIVE),
        _Run("paused-recoverable-legacy", "legacy", RunStatus.PAUSED, "server_shutdown"),
        _Run("completed-graph", "graph", RunStatus.COMPLETED),
        _Run("draft-graph", "graph", RunStatus.DRAFT),
    ]

    selected = {r.id for r in select_graph_runs_to_recover(runs, is_recoverable_pause=_recoverable)}

    assert selected == {"paused-recoverable-graph"}


def test_excludes_legacy_runs_entirely() -> None:
    runs = [
        _Run("active-legacy", "legacy", RunStatus.ACTIVE),
        _Run("paused-legacy", "legacy", RunStatus.PAUSED, "server_shutdown"),
    ]
    assert select_graph_runs_to_recover(runs, is_recoverable_pause=_recoverable) == []


def test_paused_graph_with_non_recoverable_reason_excluded() -> None:
    # graph_blocked (driver-decided block) and no_executor_running must not
    # auto-resume on startup.
    runs = [
        _Run("blocked", "graph", RunStatus.PAUSED, "graph_blocked"),
        _Run("no-exec", "graph", RunStatus.PAUSED, "no_executor_running"),
    ]
    assert select_graph_runs_to_recover(runs, is_recoverable_pause=_recoverable) == []


def test_missing_execution_mode_treated_as_legacy() -> None:
    @dataclass
    class _Legacyish:
        id: str
        status: RunStatus
        pause_reason: str | None = None

    runs = [_Legacyish("no-mode", RunStatus.ACTIVE)]
    assert select_graph_runs_to_recover(runs, is_recoverable_pause=_recoverable) == []
