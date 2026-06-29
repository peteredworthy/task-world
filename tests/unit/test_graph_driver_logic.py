from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from orchestrator.workflow.graph_driver import (
    ActiveLeaseWaitPlan,
    GraphProjectionSnapshot,
    GraphRunDriver,
    _active_lease_wait_plan,
    _graph_seed_run_config,
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
        events: list[object] = []
        if command_type == "record_heartbeat":
            events = [type("Event", (), {"event_type": "lease_renewed"})()]
        return type("Result", (), {"events": events})()


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    async def dispatch_pending(self, *, run_id: str | None = None) -> None:
        self.calls += 1


class RecordingExecutor:
    def __init__(self, running_execution_ids: set[str] | None = None) -> None:
        self.calls = 0
        self.waits: list[tuple[float | None, set[str] | None]] = []
        self.running_execution_ids = set(running_execution_ids or set())

    def is_running(self, execution_id: str) -> bool:
        return execution_id in self.running_execution_ids

    async def wait_for_all(
        self,
        *,
        timeout_seconds: float | None = None,
        active_execution_ids: set[str] | None = None,
    ) -> None:
        self.calls += 1
        self.waits.append(
            (
                timeout_seconds,
                set(active_execution_ids) if active_execution_ids is not None else None,
            )
        )


@dataclass
class ScriptedProjectionReader:
    snapshots: list[GraphProjectionSnapshot]
    index: int = 0

    async def read(self, run_id: str) -> GraphProjectionSnapshot:
        snapshot = self.snapshots[min(self.index, len(self.snapshots) - 1)]
        if self.index < len(self.snapshots) - 1:
            self.index += 1
        return snapshot


@pytest.mark.asyncio
async def test_graph_seed_run_config_embeds_dynamic_feature_spec(tmp_path: Path) -> None:
    spec_path = tmp_path / "docs" / "graph-approach" / "dynamic-smoke-feature-spec.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text("Build the dynamic-smoke artifact.", encoding="utf-8")

    seed_config = await _graph_seed_run_config(
        {
            "feature_spec_path": "docs/graph-approach/dynamic-smoke-feature-spec.md",
            "acceptance_command": "uv run pytest tests/smoke -q",
        },
        tmp_path,
    )

    assert seed_config["feature_spec_content"] == "Build the dynamic-smoke artifact."
    assert seed_config["feature_spec_content_source"] == "worktree"


@pytest.mark.asyncio
async def test_graph_seed_run_config_rejects_unsafe_spec_path(tmp_path: Path) -> None:
    seed_config = await _graph_seed_run_config(
        {
            "feature_spec_path": "../outside.md",
            "acceptance_command": "uv run pytest tests/smoke -q",
        },
        tmp_path,
    )

    assert "feature_spec_content" not in seed_config


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

    assert controller.commands == ["schedule_tick", "schedule_tick"]
    assert dispatcher.calls == 2
    assert executor.calls == 2
    assert outcome.completed is True


def test_active_lease_wait_plan_uses_nearest_deadline() -> None:
    now = datetime.fromisoformat("2026-06-27T19:30:00+00:00")

    wait_plan = _active_lease_wait_plan(
        GraphProjectionSnapshot(
            run_state="active",
            ready_nodes=[],
            active_leases={
                "lease-expired": {
                    "state": "active",
                    "node_id": "worker-expired",
                    "execution_id": "exec-expired",
                    "expires_at": "2026-06-27T19:29:59+00:00",
                },
                "lease-future": {
                    "state": "active",
                    "node_id": "worker-future",
                    "execution_id": "exec-future",
                    "expires_at": "2026-06-27T19:30:10+00:00",
                },
            },
            schedulable_nodes=[],
            task_states={},
        ),
        now,
    )

    assert wait_plan == ActiveLeaseWaitPlan(
        execution_ids={"exec-expired", "exec-future"},
        timeout_seconds=0.0,
    )


@pytest.mark.asyncio
async def test_driver_reaches_scheduler_after_expired_active_lease() -> None:
    controller = RecordingController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()
    expired_lease_snapshot = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=[],
        active_leases={
            "lease-expired": {
                "state": "active",
                "node_id": "appeal-final",
                "execution_id": "exec-expired",
                "expires_at": "2026-06-27T19:29:59+00:00",
            }
        },
        schedulable_nodes=[],
        task_states={"corrective_work_region": "pending"},
    )
    reader = ScriptedProjectionReader(
        [
            expired_lease_snapshot,
            expired_lease_snapshot,
            GraphProjectionSnapshot(
                run_state="active",
                ready_nodes=[],
                active_leases={},
                schedulable_nodes=[],
                task_states={"corrective_work_region": "pending"},
                node_states={"appeal-final": "failed"},
                failed_node_reasons={"appeal-final": "lease_expired_without_callback"},
            ),
        ]
    )

    driver = GraphRunDriver.__new__(GraphRunDriver)
    driver._clock = type(
        "FixedDriverClock",
        (),
        {"now": lambda self: datetime.fromisoformat("2026-06-27T19:30:00+00:00")},
    )()

    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=reader.read,
    )

    assert controller.commands == ["schedule_tick", "schedule_tick", "schedule_tick"]
    assert executor.waits[0] == (0.0, {"exec-expired"})
    assert outcome.completed is False
    assert outcome.blocked_reason == (
        "graph has failed node(s): appeal-final: lease_expired_without_callback"
    )


@pytest.mark.asyncio
async def test_driver_renews_expired_lease_when_execution_is_still_running() -> None:
    controller = RecordingController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor(running_execution_ids={"exec-live"})
    expired_lease_snapshot = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=[],
        active_leases={
            "lease-live": {
                "lease_id": "lease-live",
                "state": "active",
                "node_id": "planner-s-01",
                "generation": 1,
                "execution_id": "exec-live",
                "expires_at": "2026-06-27T19:29:59+00:00",
            }
        },
        schedulable_nodes=[],
        task_states={"S-01": "pending"},
    )
    completed_snapshot = GraphProjectionSnapshot(
        run_state="completed",
        ready_nodes=[],
        active_leases={},
        schedulable_nodes=[],
        task_states={"S-01": "accepted"},
    )
    reader = ScriptedProjectionReader(
        [
            expired_lease_snapshot,
            expired_lease_snapshot,
            completed_snapshot,
            completed_snapshot,
        ]
    )

    driver = GraphRunDriver.__new__(GraphRunDriver)
    driver._clock = type(
        "FixedDriverClock",
        (),
        {"now": lambda self: datetime.fromisoformat("2026-06-27T19:30:00+00:00")},
    )()

    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=reader.read,
    )

    assert controller.commands == ["schedule_tick", "record_heartbeat", "schedule_tick"]
    assert executor.waits[0] == (0.0, {"exec-live"})
    assert outcome.completed is True


@pytest.mark.asyncio
async def test_driver_runs_recovery_tick_before_quiescent_classification() -> None:
    controller = RecordingController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()
    quiescent_pending = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=[],
        active_leases={},
        schedulable_nodes=[],
        task_states={"final-invariant-region": "pending"},
        node_states={"check-final": "completed"},
    )
    reader = ScriptedProjectionReader(
        [
            quiescent_pending,
            quiescent_pending,
            GraphProjectionSnapshot(
                run_state="active",
                ready_nodes=[],
                active_leases={},
                schedulable_nodes=["planner-recover-check-final"],
                task_states={"final-invariant-region": "pending"},
                node_states={
                    "check-final": "completed",
                    "planner-recover-check-final": "planned",
                },
            ),
            GraphProjectionSnapshot(
                run_state="completed",
                ready_nodes=[],
                active_leases={},
                schedulable_nodes=[],
                task_states={"final-invariant-region": "accepted"},
            ),
            GraphProjectionSnapshot(
                run_state="completed",
                ready_nodes=[],
                active_leases={},
                schedulable_nodes=[],
                task_states={"final-invariant-region": "accepted"},
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
    assert dispatcher.calls == 2
    assert executor.calls == 2
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

    rate_limited = classify_graph_outcome(
        "run-4",
        GraphProjectionSnapshot(
            run_state="active",
            ready_nodes=[],
            active_leases={},
            schedulable_nodes=[],
            task_states={},
            node_states={"planner-1": "failed"},
            failed_node_reasons={
                "planner-1": "Agent runner 'cli_subprocess' hit rate limit (resets at 14:30)"
            },
        ),
    )

    assert rate_limited.completed is False
    assert rate_limited.blocked_reason == (
        "graph has failed node(s): planner-1: "
        "Agent runner 'cli_subprocess' hit rate limit (resets at 14:30)"
    )

    ready_blocked = classify_graph_outcome(
        "run-5",
        GraphProjectionSnapshot(
            run_state="active",
            ready_nodes=["planner-gap"],
            active_leases={},
            schedulable_nodes=["planner-gap"],
            task_states={},
        ),
    )

    assert ready_blocked.completed is False
    assert ready_blocked.blocked_reason == "graph has ready node(s) not dispatched: planner-gap"

    expired_lease_failed = classify_graph_outcome(
        "run-6",
        GraphProjectionSnapshot(
            run_state="active",
            ready_nodes=[],
            active_leases={},
            schedulable_nodes=[],
            task_states={"step/task": "in_progress"},
            node_states={"verifier-1": "failed"},
            failed_node_reasons={"verifier-1": "lease_expired_without_callback"},
        ),
    )

    assert expired_lease_failed.completed is False
    assert expired_lease_failed.blocked_reason == (
        "graph has failed node(s): verifier-1: lease_expired_without_callback"
    )

    pending_task_blocked = classify_graph_outcome(
        "run-7",
        GraphProjectionSnapshot(
            run_state="active",
            ready_nodes=[],
            active_leases={},
            schedulable_nodes=[],
            task_states={"step/task-a": "pending", "step/task-b": "in_progress"},
        ),
    )

    assert pending_task_blocked.completed is False
    assert pending_task_blocked.blocked_reason == (
        "graph quiescent with non-accepted task(s): step/task-a=pending, step/task-b=in_progress"
    )

    nonterminal_nodes_blocked = classify_graph_outcome(
        "run-8",
        GraphProjectionSnapshot(
            run_state="active",
            ready_nodes=[],
            active_leases={},
            schedulable_nodes=[],
            task_states={},
            node_states={
                "check-1": "blocked",
                "planner-1": "planned",
                "worker-1": "running",
                "verifier-1": "suspended",
            },
        ),
    )

    assert nonterminal_nodes_blocked.completed is False
    assert nonterminal_nodes_blocked.blocked_reason == (
        "graph quiescent with non-terminal node(s): "
        "check-1=blocked, planner-1=planned, verifier-1=suspended (+1 more)"
    )

    environment_blocked = classify_graph_outcome(
        "run-9",
        GraphProjectionSnapshot(
            run_state="active",
            ready_nodes=[],
            active_leases={},
            schedulable_nodes=[],
            task_states={"step/task": "blocked_environment"},
            environment_failures={
                "step/task": {
                    "classification": "tool_unavailable",
                    "reason": "check tool unavailable while running: npm --prefix ui test",
                }
            },
        ),
    )

    assert environment_blocked.completed is False
    assert environment_blocked.blocked_reason == (
        "graph needs human/operator help for check environment issue(s): "
        "step/task: tool_unavailable: check tool unavailable while running: npm --prefix ui test"
    )


@pytest.mark.asyncio
async def test_drive_stops_when_should_continue_false() -> None:
    """An external cancel/pause (should_continue → False) halts the drive loop
    immediately, without issuing a schedule_tick — so a cancelled graph run
    stops retrying dead agents."""
    controller = RecordingController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()
    reader = ScriptedProjectionReader(
        snapshots=[
            GraphProjectionSnapshot(
                run_state="active",
                ready_nodes=["worker-1"],
                active_leases={},
                schedulable_nodes=["worker-1"],
                task_states={"s/t": "in_progress"},
            )
        ]
    )

    driver = GraphRunDriver.__new__(GraphRunDriver)

    async def never_continue() -> bool:
        return False

    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=reader.read,
        should_continue=never_continue,
    )

    assert controller.commands == []  # no schedule_tick issued
    assert dispatcher.calls == 0
    assert outcome.completed is False
