from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy.exc import OperationalError

from orchestrator.workflow.graph_driver import (
    ActiveLeaseWaitPlan,
    GraphProjectionSnapshot,
    GraphRunDriver,
    MAX_NODE_RECOVERIES_PER_DRIVE,
    _active_lease_wait_plan,
    _drive_with_transient_retries,
    _graph_seed_run_config,
    _node_max_attempts,
    _renew_running_expired_leases,
    _snapshot_from_events,
    classify_graph_outcome,
)
from orchestrator.graph import (
    Actor,
    ActorKind,
    CommandExecutionContext,
    EnvironmentFailureProjection,
    EventEnvelope,
    FakeClock,
    SequentialIdGenerator,
    apply_command,
    build_graph_catalog,
    build_graph_command_dependencies,
    initial_projection,
    reduce_event,
)


def _event(event_type: str, payload: dict[str, object], position: int = -1) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


def test_snapshot_from_events_preserves_typed_environment_failures() -> None:
    snapshot = _snapshot_from_events(
        [
            _event(
                "environment_failure_accepted",
                {
                    "task_region_id": "step/task",
                    "classification": "tool_unavailable",
                    "reason": "missing tool",
                },
                position=12,
            )
        ]
    )

    failure = snapshot.environment_failures["step/task"]

    assert isinstance(failure, EnvironmentFailureProjection)
    assert failure.position == 12
    assert failure.reason == "missing tool"


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
            events = [type("Event", (), {"event_type": "heartbeat_recorded"})()]
        return type("Result", (), {"events": events})()


class RenewingHeartbeatController(RecordingController):
    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        result = await super().handle_command(
            run_id,
            expected_position,
            command_type,
            payload,
        )
        if command_type != "record_heartbeat":
            return result
        return type(
            "Result",
            (),
            {
                "events": [
                    type("Event", (), {"event_type": "heartbeat_recorded"})(),
                    type("Event", (), {"event_type": "lease_renewed"})(),
                ]
            },
        )()


class ReconcileProgressController(RecordingController):
    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        if command_type != "reconcile":
            return await super().handle_command(run_id, expected_position, command_type, payload)
        self.commands.append(command_type)
        return type(
            "Result",
            (),
            {"events": [type("Event", (), {"event_type": "reconcile_progress"})()]},
        )()


class LockedOnceController(RecordingController):
    def __init__(self, command_to_lock: str) -> None:
        super().__init__()
        self._command_to_lock = command_to_lock
        self._raised = False

    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        if command_type == self._command_to_lock and not self._raised:
            self._raised = True
            raise OperationalError(
                "INSERT INTO events_v2 ...",
                {},
                sqlite3.OperationalError("database is locked"),
            )
        return await super().handle_command(run_id, expected_position, command_type, payload)


class StablePositionAfterFirstTickController(RecordingController):
    async def current_position(self, run_id: str) -> int:
        position = 0 if not self.positions else 1
        self.positions.append(position)
        return position


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    async def dispatch_pending(self, *, run_id: str | None = None) -> None:
        self.calls += 1

    async def earliest_pending_retry_at(self, *, run_id: str | None = None) -> datetime | None:
        return None


class FutureBackoffDispatcher(RecordingDispatcher):
    def __init__(self, retry_at: datetime) -> None:
        super().__init__()
        self.retry_at = retry_at
        self.retry_reads = 0

    async def earliest_pending_retry_at(self, *, run_id: str | None = None) -> datetime | None:
        self.retry_reads += 1
        return self.retry_at


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
    # Repeating the last snapshot forever lets tests express "state never
    # changes"; cap total calls so a driver bug that spins forever fails the
    # test with a clear error instead of hanging until the suite times out.
    max_calls: int = 50
    calls: int = 0

    async def read(self, run_id: str) -> GraphProjectionSnapshot:
        self.calls += 1
        assert self.calls <= self.max_calls, (
            "ScriptedProjectionReader.read exceeded max_calls — drive loop "
            "likely spinning without bound"
        )
        snapshot = self.snapshots[min(self.index, len(self.snapshots) - 1)]
        if self.index < len(self.snapshots) - 1:
            self.index += 1
        return snapshot


class AgentDiedRecordingController(RecordingController):
    """RecordingController that also answers ``agent_died`` commands.

    ``reject_lease_ids`` names leases for which the fake kernel refuses to
    revoke the lease (command_rejected), modeling a race where the lease was
    already resolved another way. Anything else is accepted.
    """

    def __init__(self, reject_lease_ids: set[str] | None = None) -> None:
        super().__init__()
        self.agent_died_payloads: list[dict[str, object]] = []
        self._reject_lease_ids = reject_lease_ids or set()

    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        if command_type != "agent_died":
            return await super().handle_command(run_id, expected_position, command_type, payload)
        self.commands.append(command_type)
        payload = dict(payload or {})
        self.agent_died_payloads.append(payload)
        lease_id = payload.get("lease_id")
        if lease_id in self._reject_lease_ids:
            events: list[object] = [
                type(
                    "Event",
                    (),
                    {
                        "event_type": "command_rejected",
                        "payload": {"command_type": "agent_died", "reason": "lease not active"},
                    },
                )()
            ]
        else:
            events = [
                type(
                    "Event",
                    (),
                    {"event_type": "agent_died", "payload": dict(payload)},
                )()
            ]
        return type("Result", (), {"events": events})()


class StablePositionAgentDiedRecordingController(AgentDiedRecordingController):
    async def current_position(self, run_id: str) -> int:
        position = 0 if not self.positions else 1
        self.positions.append(position)
        return position


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


@pytest.mark.asyncio
async def test_drive_with_transient_retries_retries_sqlite_locked_error() -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError(
                "INSERT INTO events_v2 ...",
                {},
                sqlite3.OperationalError("database is busy"),
            )
        return "ok"

    result = await _drive_with_transient_retries(operation, sleep=lambda _delay: _noop_sleep())

    assert result == "ok"
    assert calls == 2


async def _noop_sleep() -> None:
    return None


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

    assert controller.commands == ["schedule_tick", "schedule_tick", "reconcile"]
    assert executor.waits[0] == (0.0, {"exec-expired"})
    assert outcome.completed is False
    assert outcome.blocked_reason == (
        "graph has failed node(s): appeal-final: lease_expired_without_callback"
    )


@pytest.mark.asyncio
async def test_driver_renews_expired_lease_when_execution_is_still_running() -> None:
    controller = RenewingHeartbeatController()
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


def test_temporary_renewal_advances_expiry_and_avoids_zero_timeout_heartbeat_loop() -> None:
    clock = FakeClock()
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}, 0),
        _event("node_created", {"node_id": "worker-1", "kind": "worker"}, 1),
        _event(
            "lease_granted",
            {
                "lease_id": "lease-1",
                "node_id": "worker-1",
                "generation": 1,
                "execution_id": "exec-1",
                "expires_at": (clock.now() - timedelta(seconds=1)).isoformat(),
            },
            2,
        ),
    ]
    projection = initial_projection()
    for event in events:
        projection = reduce_event(build_graph_catalog(), projection, event)
    expired_snapshot = _snapshot_from_events(events)
    context = CommandExecutionContext(
        run_id="run-1",
        current_position=2,
        clock=clock,
        id_generator=SequentialIdGenerator(),
        actor=Actor(kind=ActorKind.CONTROLLER),
        events=(),
        future_effects=build_graph_command_dependencies().future_effects,
    )

    output = apply_command(
        projection,
        events,
        "record_heartbeat",
        {"lease_id": "lease-1", "node_id": "worker-1", "lease_generation": 1},
        clock,
        context.id_generator,
        catalog=build_graph_catalog(),
        context=context,
    )
    renewal = next(
        event
        for event in output
        if isinstance(event, EventEnvelope) and event.event_type == "lease_renewed"
    )
    renewed_snapshot = _snapshot_from_events([*events, renewal])

    assert _active_lease_wait_plan(expired_snapshot, clock.now()).timeout_seconds == 0.0
    assert _active_lease_wait_plan(renewed_snapshot, clock.now()).timeout_seconds == 3600.0


@pytest.mark.asyncio
async def test_driver_retries_locked_schedule_tick_at_new_head() -> None:
    controller = LockedOnceController(command_to_lock="schedule_tick")
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()
    reader = ScriptedProjectionReader(
        [
            GraphProjectionSnapshot(
                run_state="completed",
                ready_nodes=[],
                active_leases={},
                schedulable_nodes=[],
                task_states={},
            )
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

    assert controller.commands == ["schedule_tick"]
    assert controller.positions == [0, 1]
    assert outcome.completed is True


@pytest.mark.asyncio
async def test_driver_does_not_treat_neutral_heartbeat_as_lease_renewal() -> None:
    controller = LockedOnceController(command_to_lock="record_heartbeat")
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

    driver = GraphRunDriver.__new__(GraphRunDriver)
    driver._clock = type(
        "FixedDriverClock",
        (),
        {"now": lambda self: datetime.fromisoformat("2026-06-27T19:30:00+00:00")},
    )()

    renewed = await _renew_running_expired_leases(
        "run-1",
        controller,
        executor,
        expired_lease_snapshot,
        driver._clock.now(),
    )

    assert renewed is False
    assert controller.commands == ["record_heartbeat"]
    assert controller.positions == [0, 1]


@pytest.mark.asyncio
async def test_driver_runs_reconcile_before_quiescent_classification() -> None:
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

    assert controller.commands == ["schedule_tick", "reconcile", "schedule_tick"]
    assert dispatcher.calls == 2
    assert executor.calls == 2
    assert reader.calls == 5
    assert outcome.completed is True
    assert outcome.blocked_reason is None


@pytest.mark.asyncio
async def test_driver_returns_reconciled_quiescent_projection_without_second_schedule_tick() -> (
    None
):
    controller = ReconcileProgressController()
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
                schedulable_nodes=[],
                task_states={"final-invariant-region": "pending"},
                node_states={
                    "check-final": "completed",
                    "planner-recover-check-final": "planned",
                },
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

    assert controller.commands == ["schedule_tick", "reconcile"]
    assert dispatcher.calls == 1
    assert executor.calls == 1
    assert reader.calls == 3
    assert outcome.completed is False
    assert outcome.blocked_reason == (
        "graph quiescent with non-terminal node(s): planner-recover-check-final=planned"
    )


@pytest.mark.asyncio
async def test_driver_continues_when_reconcile_creates_schedulable_work() -> None:
    controller = ReconcileProgressController()
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
    ready_after_reconcile = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=["planner-recover-check-final"],
        active_leases={},
        schedulable_nodes=["planner-recover-check-final"],
        task_states={"final-invariant-region": "pending"},
        node_states={
            "check-final": "completed",
            "planner-recover-check-final": "planned",
        },
    )
    failed_after_second_tick = GraphProjectionSnapshot(
        run_state="failed",
        ready_nodes=[],
        active_leases={},
        schedulable_nodes=[],
        task_states={"final-invariant-region": "pending"},
        node_states={
            "check-final": "completed",
            "planner-recover-check-final": "failed",
        },
    )
    reader = ScriptedProjectionReader(
        [
            quiescent_pending,
            quiescent_pending,
            ready_after_reconcile,
            failed_after_second_tick,
            failed_after_second_tick,
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

    assert controller.commands == ["schedule_tick", "reconcile", "schedule_tick"]
    assert dispatcher.calls == 2
    assert executor.calls == 2
    assert reader.calls == 5
    assert outcome.completed is False
    assert outcome.run_state == "failed"


@pytest.mark.asyncio
async def test_driver_recovers_orphaned_lease_and_reschedules_node() -> None:
    """Regression test for run 8feabee5: an execution finished without an
    accepted callback (e.g. its submit was rejected), leaving an active lease
    on a "running" node with nothing schedulable. The driver must emit
    agent_died for that lease itself — recovering the run — instead of
    pausing graph_blocked with a lease that only clears if an operator
    manually resumes it later."""
    controller = StablePositionAgentDiedRecordingController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()  # no execution ids reported running

    orphaned_lease_snapshot = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=[],
        active_leases={
            "lease-1": {
                "lease_id": "lease-1",
                "state": "active",
                "node_id": "worker-1",
                "execution_id": "exec-1",
                "generation": 1,
            }
        },
        schedulable_nodes=[],
        task_states={"s/t": "in_progress"},
        node_states={"worker-1": "running"},
    )
    rescheduled_snapshot = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=["worker-1"],
        active_leases={},
        schedulable_nodes=["worker-1"],
        task_states={"s/t": "in_progress"},
        node_states={"worker-1": "ready"},
    )
    completed_snapshot = GraphProjectionSnapshot(
        run_state="completed",
        ready_nodes=[],
        active_leases={},
        schedulable_nodes=[],
        task_states={"s/t": "accepted"},
    )
    reader = ScriptedProjectionReader(
        [
            orphaned_lease_snapshot,
            orphaned_lease_snapshot,
            orphaned_lease_snapshot,
            orphaned_lease_snapshot,
            rescheduled_snapshot,
            rescheduled_snapshot,
            completed_snapshot,
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

    assert controller.commands.count("agent_died") == 1
    assert controller.agent_died_payloads == [
        {
            "lease_id": "lease-1",
            "reason": "runtime_execution_missing_no_callback",
            "execution_id": "exec-1",
        }
    ]
    assert outcome.completed is True


@pytest.mark.asyncio
async def test_driver_waits_for_future_outbox_backoff_before_declaring_blocked() -> None:
    controller = StablePositionAgentDiedRecordingController()
    clock = FakeClock()
    dispatcher = FutureBackoffDispatcher(clock.now() + timedelta(seconds=5))
    executor = RecordingExecutor()

    orphaned_lease_snapshot = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=[],
        active_leases={
            "lease-1": {
                "lease_id": "lease-1",
                "state": "active",
                "node_id": "worker-1",
                "execution_id": "exec-1",
                "generation": 1,
            }
        },
        schedulable_nodes=[],
        task_states={"s/t": "in_progress"},
        node_states={"worker-1": "leased"},
    )
    completed_snapshot = GraphProjectionSnapshot(
        run_state="completed",
        ready_nodes=[],
        active_leases={},
        schedulable_nodes=[],
        task_states={"s/t": "accepted"},
    )
    reader = ScriptedProjectionReader(
        [
            orphaned_lease_snapshot,
            orphaned_lease_snapshot,
            orphaned_lease_snapshot,
            orphaned_lease_snapshot,
            completed_snapshot,
            completed_snapshot,
        ]
    )
    slept: list[float] = []

    async def advance_sleep(delay: float) -> None:
        slept.append(delay)
        clock.advance(delay)

    driver = GraphRunDriver.__new__(GraphRunDriver)
    driver._clock = clock
    driver._sleep = advance_sleep
    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=reader.read,
    )

    assert slept == [5.0]
    assert controller.commands.count("agent_died") == 0
    assert dispatcher.calls == 3
    assert outcome.completed is True


@pytest.mark.asyncio
async def test_driver_blocks_without_recovery_when_no_active_leases() -> None:
    """A genuine block (ready node the scheduler can't dispatch, e.g. a
    resource/gate wait, and no active leases) must still return blocked with
    no behavior change — there is nothing for lease recovery to do."""
    controller = StablePositionAfterFirstTickController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()

    stuck_snapshot = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=["planner-gap"],
        active_leases={},
        schedulable_nodes=["planner-gap"],
        task_states={"s/t": "pending"},
    )
    reader = ScriptedProjectionReader([stuck_snapshot])

    driver = GraphRunDriver.__new__(GraphRunDriver)
    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=reader.read,
    )

    assert "agent_died" not in controller.commands
    assert outcome.completed is False
    assert outcome.blocked_reason == "graph has ready node(s) not dispatched: planner-gap"


@pytest.mark.asyncio
async def test_driver_uses_event_position_to_detect_stuck_ready_node() -> None:
    controller = StablePositionAfterFirstTickController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()

    stuck_snapshot = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=["planner-gap"],
        active_leases={},
        schedulable_nodes=["planner-gap"],
        task_states={"s/t": "pending"},
    )
    reader = ScriptedProjectionReader([stuck_snapshot])

    driver = GraphRunDriver.__new__(GraphRunDriver)
    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=reader.read,
    )

    assert controller.positions == [0, 1, 1, 1]
    assert controller.commands == ["schedule_tick", "schedule_tick"]
    assert outcome.completed is False
    assert outcome.blocked_reason == "graph has ready node(s) not dispatched: planner-gap"


@pytest.mark.asyncio
async def test_driver_stops_retrying_a_lease_that_never_clears() -> None:
    """A lease the driver has already tried to recover must not be retried
    forever: if the projection keeps showing the same orphaned lease_id after
    a recovery attempt (e.g. the kernel's retry policy keeps requeuing under
    conditions the fake never resolves), the per-lease_id dedup bounds the
    loop so it terminates instead of alternating recover/no-progress forever."""
    controller = StablePositionAgentDiedRecordingController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()

    # Every read returns the exact same orphaned lease — the fake kernel
    # "accepts" the agent_died but nothing about the projection ever changes,
    # standing in for a node that keeps dying under conditions this fixture
    # doesn't clear (in production, the kernel's own max_attempts budget in
    # build_agent_died_effects is what eventually stops requeuing a real node and
    # moves it to a terminal "failed" state).
    stuck_lease_snapshot = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=[],
        active_leases={
            "lease-1": {
                "lease_id": "lease-1",
                "state": "active",
                "node_id": "worker-1",
                "execution_id": "exec-1",
                "generation": 1,
            }
        },
        schedulable_nodes=[],
        task_states={"s/t": "in_progress"},
        node_states={"worker-1": "running"},
    )
    reader = ScriptedProjectionReader([stuck_lease_snapshot])

    driver = GraphRunDriver.__new__(GraphRunDriver)
    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=reader.read,
    )

    # The loop terminated at all (no ScriptedProjectionReader.max_calls
    # assertion failure) and only ever attempted recovery once for lease-1,
    # despite the identical orphaned lease reappearing on every subsequent
    # read — proof the per-lease_id dedup, not luck, bounded the loop.
    assert controller.commands.count("agent_died") == 1
    assert len(controller.agent_died_payloads) == 1
    assert outcome.completed is False


@pytest.mark.asyncio
async def test_driver_stops_recovering_node_when_fresh_lease_ids_keep_orphaning() -> None:
    """Per-node recovery budget bounds dynamic nodes with no max_attempts.

    The kernel grants a fresh lease_id after each accepted agent_died when a node
    has no retry budget. A lease_id-only dedup would therefore keep recovering the
    same chronically orphaned node forever. The driver must stop after the node
    budget and return graph_blocked.
    """
    controller = StablePositionAgentDiedRecordingController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()

    def snapshot(lease_id: str, execution_id: str) -> GraphProjectionSnapshot:
        return GraphProjectionSnapshot(
            run_state="active",
            ready_nodes=[],
            active_leases={
                lease_id: {
                    "lease_id": lease_id,
                    "state": "active",
                    "node_id": "dynamic-worker-1",
                    "execution_id": execution_id,
                    "generation": 1,
                }
            },
            schedulable_nodes=[],
            task_states={"s/t": "in_progress"},
            node_states={"dynamic-worker-1": "running"},
        )

    snapshots: list[GraphProjectionSnapshot] = []
    for index in range(MAX_NODE_RECOVERIES_PER_DRIVE + 1):
        current = snapshot(f"lease-{index}", f"exec-{index}")
        # Each drive iteration reads a wait projection and then the projection
        # used for progress comparison. Keep the same lease visible across two
        # full iterations so the no-progress recovery branch is exercised.
        snapshots.extend([current, current, current, current])
    reader = ScriptedProjectionReader(snapshots, max_calls=len(snapshots) + 2)

    driver = GraphRunDriver.__new__(GraphRunDriver)
    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=reader.read,
    )

    assert controller.commands.count("agent_died") == MAX_NODE_RECOVERIES_PER_DRIVE
    assert len(controller.agent_died_payloads) == MAX_NODE_RECOVERIES_PER_DRIVE
    assert {payload["lease_id"] for payload in controller.agent_died_payloads} == {
        f"lease-{index}" for index in range(MAX_NODE_RECOVERIES_PER_DRIVE)
    }
    assert outcome.completed is False
    assert outcome.blocked_reason == "graph has active lease(s) without callback: dynamic-worker-1"


def test_node_max_attempts_matches_dispatch_first_node_created_lookup() -> None:
    attempts = _node_max_attempts(
        [
            _event(
                "node_created",
                {"node_id": "worker-1", "max_attempts": 2},
                position=1,
            ),
            _event(
                "node_created",
                {"node_id": "worker-1", "max_attempts": 7},
                position=2,
            ),
            _event(
                "node_created",
                {"node_id": "worker-2", "max_attempts": True},
                position=3,
            ),
            _event(
                "node_created",
                {"node_id": "worker-3"},
                position=4,
            ),
            _event(
                "node_created",
                {"node_id": "worker-3", "max_attempts": 4},
                position=5,
            ),
        ]
    )

    assert attempts == {"worker-1": 2, "worker-3": 4}


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

    missing_input_blocked = classify_graph_outcome(
        "run-missing-input",
        GraphProjectionSnapshot(
            run_state="active",
            ready_nodes=[],
            active_leases={},
            schedulable_nodes=[],
            task_states={},
            node_states={"check-final": "planned", "verifier-primary": "failed"},
            node_deferral_reasons={"check-final": "missing_required_input:verification_evidence"},
            missing_input_sources={
                "check-final": ["verification_evidence from verifier-primary=failed"],
            },
        ),
    )

    assert missing_input_blocked.completed is False
    assert missing_input_blocked.blocked_reason == (
        "graph quiescent with non-terminal node(s): "
        "check-final=planned: missing_required_input:verification_evidence "
        "(verification_evidence from verifier-primary=failed)"
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
                "step/task": EnvironmentFailureProjection(
                    position=12,
                    classification="tool_unavailable",
                    reason="check tool unavailable while running: npm --prefix ui test",
                )
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
