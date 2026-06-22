from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from orchestrator.workflow.graph_driver import (
    GraphProjectionSnapshot,
    GraphRunDriver,
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
