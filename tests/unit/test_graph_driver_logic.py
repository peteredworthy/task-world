from __future__ import annotations

from dataclasses import dataclass

import pytest

from orchestrator.workflow.graph_driver import (
    GraphProjectionSnapshot,
    GraphRunDriver,
    classify_graph_outcome,
)


class RecordingController:
    def __init__(self) -> None:
        self.positions: list[int] = []
        self.commands: list[str] = []

    async def current_position(self, run_id: str) -> int:
        self.positions.append(len(self.positions))
        return len(self.positions) - 1

    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        self.commands.append(command_type)
        return object()


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    async def dispatch_pending(self) -> None:
        self.calls += 1


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def wait_for_all(self) -> None:
        self.calls += 1


@dataclass
class ScriptedProjectionReader:
    snapshots: list[GraphProjectionSnapshot]
    index: int = 0

    async def read(self, run_id: str) -> GraphProjectionSnapshot:
        snapshot = self.snapshots[self.index]
        self.index += 1
        return snapshot


@pytest.mark.asyncio
async def test_loop_terminates_on_quiescence() -> None:
    controller = RecordingController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()
    reader = ScriptedProjectionReader(
        [
            GraphProjectionSnapshot(
                run_state="active",
                ready_nodes=["verifier-1"],
                active_leases={},
                schedulable_nodes=["verifier-1"],
                task_states={},
            ),
            GraphProjectionSnapshot(
                run_state="active",
                ready_nodes=[],
                active_leases={"lease-1": {"state": "active"}},
                schedulable_nodes=[],
                task_states={},
            ),
            GraphProjectionSnapshot(
                run_state="completed",
                ready_nodes=[],
                active_leases={},
                schedulable_nodes=[],
                task_states={},
            ),
        ]
    )

    driver = GraphRunDriver.__new__(GraphRunDriver)
    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=reader.read,
    )

    assert controller.commands == ["schedule_tick", "schedule_tick", "schedule_tick"]
    assert dispatcher.calls == 3
    assert executor.calls == 3
    assert outcome.completed is True


def test_outcome_classification() -> None:
    completed = classify_graph_outcome(
        "run-1",
        GraphProjectionSnapshot(
            run_state="completed",
            ready_nodes=[],
            active_leases={},
            schedulable_nodes=[],
            task_states={},
        ),
    )
    blocked = classify_graph_outcome(
        "run-2",
        GraphProjectionSnapshot(
            run_state="active",
            ready_nodes=[],
            active_leases={},
            schedulable_nodes=[],
            task_states={},
        ),
    )
    failed = classify_graph_outcome(
        "run-3",
        GraphProjectionSnapshot(
            run_state="failed",
            ready_nodes=[],
            active_leases={},
            schedulable_nodes=[],
            task_states={},
        ),
    )

    assert completed.completed is True
    assert completed.blocked_reason is None
    assert blocked.completed is False
    assert blocked.blocked_reason == "graph quiescent without completion"
    assert failed.completed is False
    assert failed.blocked_reason == "graph failed"
