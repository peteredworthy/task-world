from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from orchestrator.workflow.graph_driver import (
    GraphRunDriver,
    MANAGED_LEASE_RENEWAL_LEAD_SECONDS,
    MAX_NODE_RECOVERIES_PER_DRIVE,
    _drive_with_transient_retries,
    _graph_seed_run_config,
    _renew_running_leases_near_expiry,
)
from orchestrator.graph import (
    ActiveLeaseWaitPlan,
    Actor,
    ActorKind,
    EnvironmentFailureProjection,
    EventEnvelope,
    FakeClock,
    GraphCommandContext,
    GraphProjectionSnapshot,
    project_active_lease_wait_plan,
    project_graph_outcome,
    project_graph_projection_snapshot,
    project_node_max_attempts,
)
from orchestrator.graph_runtime import StaleProjectionError
from orchestrator.workflow import GraphRunOutcome as WorkflowGraphRunOutcome
from tests.unit.graph_test_utils import canonical_event_payload


def _event(event_type: str, payload: dict[str, Any], position: int = -1) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=canonical_event_payload(event_type, payload),
    )


def test_snapshot_from_events_preserves_typed_environment_failures() -> None:
    snapshot = project_graph_projection_snapshot(
        [
            _event(
                "output_record_accepted",
                {
                    "task_region_id": "step/task",
                    "record_kind": "check_result",
                    "value": {
                        "classification": "tool_unavailable",
                        "reason": "missing tool",
                    },
                },
                position=12,
            )
        ]
    )

    failure = snapshot.environment_failures["step/task"]

    assert isinstance(failure, EnvironmentFailureProjection)
    assert failure.position == 12
    assert failure.reason == "check tool unavailable while running: check command"


def test_workflow_graph_run_outcome_remains_the_public_graph_outcome() -> None:
    from orchestrator.graph import GraphRunOutcome

    assert WorkflowGraphRunOutcome is GraphRunOutcome


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
        *,
        context: GraphCommandContext | None = None,
    ) -> object:
        assert context is not None
        self.commands.append(command_type)
        events: list[object] = []
        if command_type == "record_heartbeat":
            events = [type("Event", (), {"event_type": "lease_renewed"})()]
        return type("Result", (), {"events": events})()


class ReconcileProgressController(RecordingController):
    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
        *,
        context: GraphCommandContext | None = None,
    ) -> object:
        if command_type != "reconcile":
            return await super().handle_command(
                run_id, expected_position, command_type, payload, context=context
            )
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
        *,
        context: GraphCommandContext | None = None,
    ) -> object:
        if command_type == self._command_to_lock and not self._raised:
            self._raised = True
            raise OperationalError(
                "INSERT INTO events_v2 ...",
                {},
                sqlite3.OperationalError("database is locked"),
            )
        return await super().handle_command(
            run_id, expected_position, command_type, payload, context=context
        )


class StablePositionAfterFirstTickController(RecordingController):
    async def current_position(self, run_id: str) -> int:
        position = 0 if not self.positions else 1
        self.positions.append(position)
        return position


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    async def dispatch_pending(
        self,
        *,
        run_id: str | None = None,
        allowed_kinds: frozenset[str] | None = None,
    ) -> None:
        del allowed_kinds
        self.calls += 1

    async def earliest_pending_retry_at(self, *, run_id: str | None = None) -> datetime | None:
        return None


class OrderedController(RecordingController):
    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self._order = order

    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
        *,
        context: GraphCommandContext | None = None,
    ) -> object:
        if command_type == "schedule_tick":
            self._order.append("schedule")
        return await super().handle_command(
            run_id, expected_position, command_type, payload, context=context
        )


class OrderedDispatcher(RecordingDispatcher):
    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self._order = order

    async def dispatch_pending(
        self,
        *,
        run_id: str | None = None,
        allowed_kinds: frozenset[str] | None = None,
    ) -> None:
        del allowed_kinds
        self._order.append("dispatch")
        await super().dispatch_pending(run_id=run_id)


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

    def can_heartbeat(self, execution_id: str) -> bool:
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
        *,
        context: GraphCommandContext | None = None,
    ) -> object:
        if command_type != "agent_died":
            return await super().handle_command(
                run_id, expected_position, command_type, payload, context=context
            )
        assert context is not None
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

    assert controller.commands == ["schedule_tick"]
    assert dispatcher.calls == 2
    assert executor.calls == 1
    assert outcome.completed is True


@pytest.mark.asyncio
async def test_resume_primes_recovery_dispatch_before_schedule_tick() -> None:
    """A resumed ready node must not lose its first scheduling opportunity.

    Recovery completion is an outbox side effect.  The kernel intentionally
    suppresses ``schedule_tick`` while that recovery is pending, so the resume
    driver must deliver the recovery tranche before asking the scheduler to
    classify the ready node.
    """
    order: list[str] = []
    controller = OrderedController(order)
    dispatcher = OrderedDispatcher(order)
    executor = RecordingExecutor()
    snapshot = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=[],
        active_leases={},
        schedulable_nodes=[],
        task_states={},
    )
    reader = ScriptedProjectionReader([snapshot])

    driver = GraphRunDriver.__new__(GraphRunDriver)
    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=reader.read,
        prime_dispatch_before_schedule=True,
    )

    assert order[:2] == ["dispatch", "schedule"]
    assert controller.commands[0] == "schedule_tick"
    assert outcome.completed is False


@pytest.mark.asyncio
async def test_protocol_dispatcher_drains_second_cleanup_pass_before_completion() -> None:
    """The loop relies only on the dispatcher protocol for its final cleanup drain."""
    controller = RecordingController()
    executor = RecordingExecutor()

    class CleanupDrainProtocolDouble:
        def __init__(self) -> None:
            self.calls = 0

        async def dispatch_pending(
            self,
            *,
            run_id: str | None = None,
            allowed_kinds: frozenset[str] | None = None,
        ) -> None:
            del allowed_kinds
            assert run_id == "run-1"
            self.calls += 1

        async def earliest_pending_retry_at(self, *, run_id: str | None = None) -> datetime | None:
            assert run_id == "run-1"
            return None

    dispatcher = CleanupDrainProtocolDouble()
    pending_cleanup = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=[],
        active_leases={},
        schedulable_nodes=[],
        task_states={"step/task": "pending"},
        node_states={"final-gate": "completed"},
    )
    cleanup_applied = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=[],
        active_leases={},
        schedulable_nodes=[],
        task_states={"step/task": "accepted"},
        node_states={"final-gate": "completed"},
    )
    completed = GraphProjectionSnapshot(
        run_state="completed",
        ready_nodes=[],
        active_leases={},
        schedulable_nodes=[],
        task_states={"step/task": "accepted"},
    )

    async def read_projection(_run_id: str) -> GraphProjectionSnapshot:
        if "complete" in controller.commands:
            return completed
        return pending_cleanup if dispatcher.calls < 2 else cleanup_applied

    driver = GraphRunDriver.__new__(GraphRunDriver)
    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=read_projection,
    )

    assert dispatcher.calls == 2
    assert controller.commands == ["schedule_tick", "complete"]
    assert outcome.completed is True
    assert outcome.run_state == "completed"


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

    wait_plan = project_active_lease_wait_plan(
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


def test_active_lease_wait_plan_wakes_at_renewal_lead() -> None:
    now = datetime.fromisoformat("2026-06-27T19:30:00+00:00")

    wait_plan = project_active_lease_wait_plan(
        GraphProjectionSnapshot(
            run_state="active",
            ready_nodes=[],
            active_leases={
                "lease-live": {
                    "execution_id": "exec-live",
                    "expires_at": "2026-06-27T19:32:00+00:00",
                }
            },
            schedulable_nodes=[],
            task_states={},
        ),
        now,
        renewal_lead_seconds=MANAGED_LEASE_RENEWAL_LEAD_SECONDS,
    )

    assert wait_plan == ActiveLeaseWaitPlan(
        execution_ids={"exec-live"},
        timeout_seconds=60.0,
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

    assert controller.commands == ["schedule_tick", "reconcile"]
    assert "record_heartbeat" not in controller.commands
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
    near_expiry_lease_snapshot = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=[],
        active_leases={
            "lease-live": {
                "lease_id": "lease-live",
                "state": "active",
                "node_id": "planner-s-01",
                "generation": 1,
                "execution_id": "exec-live",
                "expires_at": "2026-06-27T19:30:30+00:00",
            }
        },
        schedulable_nodes=[],
        task_states={"S-01": "pending"},
    )
    renewed_lease_snapshot = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=[],
        active_leases={
            "lease-live": {
                "lease_id": "lease-live",
                "state": "active",
                "node_id": "planner-s-01",
                "generation": 1,
                "execution_id": "exec-live",
                "expires_at": "2026-06-27T20:30:00+00:00",
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
            near_expiry_lease_snapshot,
            renewed_lease_snapshot,
            renewed_lease_snapshot,
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

    assert controller.commands == ["record_heartbeat", "schedule_tick"]
    assert executor.waits[0] == (3540.0, {"exec-live"})
    assert outcome.completed is True


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
async def test_driver_retries_locked_heartbeat_renewal_at_new_head() -> None:
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

    renewed = await _renew_running_leases_near_expiry(
        "run-1",
        controller,
        executor,
        expired_lease_snapshot,
        driver._clock.now(),
    )

    assert renewed is True
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

    assert controller.commands == ["schedule_tick", "reconcile"]
    assert dispatcher.calls == 2
    assert executor.calls == 1
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
    assert dispatcher.calls == 2
    assert executor.calls == 1
    assert reader.calls == 5
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
    assert dispatcher.calls == 4
    assert executor.calls == 2
    assert reader.calls == 9
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
async def test_driver_recovers_resumed_leases_despite_ready_node_deferral_progress() -> None:
    """A ready node's resource-conflict deferral must not mask orphaned leases.

    On resume, consume-once outbox rows can leave leases behind without a live
    execution.  A different ready node then advances the graph position on each
    tick by being deferred on those resources, so stable-head recovery never
    runs unless orphan detection happens directly after dispatch and wait.
    """
    controller = AgentDiedRecordingController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()
    orphaned_with_ready_snapshot = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=["worker-final"],
        active_leases={
            "lease-1": {
                "lease_id": "lease-1",
                "state": "active",
                "node_id": "worker-implementation",
                "execution_id": "exec-1",
                "generation": 1,
            }
        },
        schedulable_nodes=["worker-final"],
        task_states={"s/t": "in_progress"},
        node_states={
            "worker-implementation": "leased",
            "worker-final": "ready",
        },
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
            orphaned_with_ready_snapshot,
            orphaned_with_ready_snapshot,
            orphaned_with_ready_snapshot,
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
    assert dispatcher.calls == 4
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
    # _apply_agent_died is what eventually stops requeuing a real node and
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


def _dynamic_worker_orphan_snapshot(lease_id: str, execution_id: str) -> GraphProjectionSnapshot:
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


@pytest.mark.asyncio
async def test_driver_terminally_revokes_lease_when_node_recovery_budget_is_exhausted() -> None:
    """Per-node recovery budget bounds dynamic nodes with no max_attempts.

    The kernel grants a fresh lease_id after each accepted agent_died when a node
    has no retry budget. A lease_id-only dedup would therefore keep recovering the
    same chronically orphaned node forever. Once the node's recovery budget is
    exhausted the driver must not silently give up on it: it issues one further,
    flagged terminal ``agent_died(recovery_exhausted=True)`` instead of a plain
    recovery attempt, so the kernel conclusively revokes the lease and fails the
    node rather than leaving it ``active`` with nothing recorded (criterion 3).
    """
    controller = StablePositionAgentDiedRecordingController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()

    snapshots: list[GraphProjectionSnapshot] = []
    for index in range(MAX_NODE_RECOVERIES_PER_DRIVE + 1):
        current = _dynamic_worker_orphan_snapshot(f"lease-{index}", f"exec-{index}")
        # Each drive iteration reads a preflight, wait, and post-wait
        # projection. Keep the same lease visible across two full iterations
        # so the no-progress recovery branch is exercised.
        snapshots.extend([current] * 6)
    # The terminal command lands, but this list never provides a post-
    # conclusion snapshot (that is the next test's job) — the loop keeps
    # seeing the same still-active lease, now skipped via concluded_node_ids,
    # and needs a couple more no-progress iterations before it gives up.
    reader = ScriptedProjectionReader(snapshots, max_calls=len(snapshots) + 10)

    driver = GraphRunDriver.__new__(GraphRunDriver)
    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=reader.read,
    )

    # One more command than the budget: the budget-th orphan still gets a
    # plain recovery attempt; only the NEXT one is concluded terminally.
    assert controller.commands.count("agent_died") == MAX_NODE_RECOVERIES_PER_DRIVE + 1
    assert len(controller.agent_died_payloads) == MAX_NODE_RECOVERIES_PER_DRIVE + 1
    recovering_payloads = controller.agent_died_payloads[:MAX_NODE_RECOVERIES_PER_DRIVE]
    terminal_payload = controller.agent_died_payloads[-1]
    assert {payload["lease_id"] for payload in recovering_payloads} == {
        f"lease-{index}" for index in range(MAX_NODE_RECOVERIES_PER_DRIVE)
    }
    assert all(not payload.get("recovery_exhausted") for payload in recovering_payloads)
    assert terminal_payload["recovery_exhausted"] is True
    assert terminal_payload["lease_id"] == f"lease-{MAX_NODE_RECOVERIES_PER_DRIVE}"
    assert terminal_payload["execution_id"] == f"exec-{MAX_NODE_RECOVERIES_PER_DRIVE}"
    assert outcome.completed is False


@pytest.mark.asyncio
async def test_driver_reports_failed_node_after_terminal_revocation() -> None:
    """The driver-level statement of criterion 3: once the budget is
    exhausted and the terminal command lands, the run pauses graph_blocked
    with the node failed and its lease revoked — never the forbidden "active
    lease(s) without callback" state.
    """
    controller = StablePositionAgentDiedRecordingController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()

    concluded_snapshot = GraphProjectionSnapshot(
        run_state="active",
        ready_nodes=[],
        active_leases={},
        schedulable_nodes=[],
        task_states={"s/t": "in_progress"},
        node_states={"dynamic-worker-1": "failed"},
        failed_node_reasons={"dynamic-worker-1": "recovery_budget_exhausted"},
    )

    snapshots: list[GraphProjectionSnapshot] = []
    for index in range(MAX_NODE_RECOVERIES_PER_DRIVE + 1):
        current = _dynamic_worker_orphan_snapshot(f"lease-{index}", f"exec-{index}")
        snapshots.extend([current] * 6)
    # After the terminal command is issued for the last orphan above, every
    # subsequent read reflects the kernel's real post-conclusion projection
    # (fact O): zero active leases, the node failed. ScriptedProjectionReader
    # repeats this final entry for as many further reads as the loop needs.
    snapshots.append(concluded_snapshot)
    reader = ScriptedProjectionReader(snapshots, max_calls=len(snapshots) + 10)

    driver = GraphRunDriver.__new__(GraphRunDriver)
    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=reader.read,
    )

    assert controller.commands.count("agent_died") == MAX_NODE_RECOVERIES_PER_DRIVE + 1
    assert outcome.completed is False
    assert (
        outcome.blocked_reason
        == "graph has failed node(s): dynamic-worker-1: recovery_budget_exhausted"
    )
    assert "active lease(s) without callback" not in (outcome.blocked_reason or "")


@pytest.mark.asyncio
async def test_driver_concludes_a_node_only_once_per_drive_call() -> None:
    """A kernel or fake that keeps handing out a fresh lease_id for the same
    node even after the terminal command must not be re-recovered or
    re-concluded. ``concluded_node_ids`` bounds the loop even when lease_id
    churn never stops; without it this test hangs/asserts on the reader's
    spin guard.
    """
    controller = StablePositionAgentDiedRecordingController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()

    total_iterations = MAX_NODE_RECOVERIES_PER_DRIVE + 5
    snapshots: list[GraphProjectionSnapshot] = []
    for index in range(total_iterations):
        current = _dynamic_worker_orphan_snapshot(f"lease-{index}", f"exec-{index}")
        snapshots.extend([current] * 6)
    reader = ScriptedProjectionReader(snapshots, max_calls=len(snapshots) + 3)

    driver = GraphRunDriver.__new__(GraphRunDriver)
    outcome = await driver.drive_to_quiescence(
        "run-1",
        controller=controller,
        dispatcher=dispatcher,
        executor=executor,
        read_projection=reader.read,
    )

    assert controller.commands.count("agent_died") == MAX_NODE_RECOVERIES_PER_DRIVE + 1
    assert {payload["lease_id"] for payload in controller.agent_died_payloads} == {
        f"lease-{index}" for index in range(MAX_NODE_RECOVERIES_PER_DRIVE + 1)
    }
    assert outcome.completed is False


class _StaleOnceThenAgentDiedController(StablePositionAgentDiedRecordingController):
    """Raises StaleProjectionError on the first agent_died issue attempt,
    then accepts it — modeling a concurrent append that rejected the driver's
    read-then-append race (fact S1)."""

    def __init__(self) -> None:
        super().__init__()
        self._raised_once = False

    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
        *,
        context: GraphCommandContext | None = None,
    ) -> object:
        if command_type == "agent_died" and not self._raised_once:
            self._raised_once = True
            raise StaleProjectionError("stale run-local position")
        return await super().handle_command(
            run_id, expected_position, command_type, payload, context=context
        )


@pytest.mark.asyncio
async def test_driver_reissues_orphan_recovery_after_stale_projection() -> None:
    """A StaleProjectionError on the orphan-recovery command issue is
    retried, not treated as abandonment: the append was rejected and nothing
    landed, so re-issuing is safe (part C, fact S1)."""
    controller = _StaleOnceThenAgentDiedController()
    dispatcher = RecordingDispatcher()
    executor = RecordingExecutor()

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

    # The lease was recovered (agent_died accepted once) despite the first
    # issue attempt being rejected as stale — it was not abandoned after a
    # single failed append.
    assert controller.commands.count("agent_died") == 1
    assert len(controller.agent_died_payloads) == 1
    assert outcome.completed is False


def test_node_max_attempts_matches_dispatch_first_node_created_lookup() -> None:
    attempts = project_node_max_attempts(
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
    completed = project_graph_outcome(
        "run-1",
        GraphProjectionSnapshot(
            run_state="completed",
            ready_nodes=[],
            active_leases={},
            schedulable_nodes=[],
            task_states={},
        ),
    )
    blocked = project_graph_outcome(
        "run-2",
        GraphProjectionSnapshot(
            run_state="active",
            ready_nodes=[],
            active_leases={},
            schedulable_nodes=[],
            task_states={},
        ),
    )
    failed = project_graph_outcome(
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

    rate_limited = project_graph_outcome(
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

    ready_blocked = project_graph_outcome(
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

    expired_lease_failed = project_graph_outcome(
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

    pending_task_blocked = project_graph_outcome(
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

    nonterminal_nodes_blocked = project_graph_outcome(
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

    missing_input_blocked = project_graph_outcome(
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
    assert missing_input_blocked.blocked_reason == ("graph has failed node(s): verifier-primary")

    environment_blocked = project_graph_outcome(
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
