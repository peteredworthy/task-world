"""Pure STOPPING-state transition behavior."""

import pytest

from orchestrator.config import RunStatus
from orchestrator.state import Run, SessionStateManager, StepState, TaskState
from orchestrator.workflow import InvalidTransitionError, RunStatusChanged, WorkflowEngine
from tests.conftest import CollectingEmitter, FakeClock


def _active_run() -> Run:
    return Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[TaskState(id="task-1", config_id="T-01")],
            )
        ],
    )


def _engine(run: Run) -> tuple[WorkflowEngine, CollectingEmitter]:
    manager = SessionStateManager()
    manager.add_run(run)
    emitter = CollectingEmitter()
    return WorkflowEngine(manager, clock=FakeClock(), emitter=emitter), emitter


def test_active_run_stops_and_emits_transition() -> None:
    engine, emitter = _engine(_active_run())

    result = engine.stop_run("run-1")

    assert result.status == RunStatus.STOPPING
    event = emitter.events[0]
    assert isinstance(event, RunStatusChanged)
    assert (event.old_status, event.new_status) == (RunStatus.ACTIVE, RunStatus.STOPPING)


@pytest.mark.parametrize(
    ("operation", "terminal_status"),
    [("pause", RunStatus.PAUSED), ("cancel", RunStatus.CANCELLED)],
)
def test_stopping_run_allows_terminal_transition(
    operation: str,
    terminal_status: RunStatus,
) -> None:
    run = _active_run()
    run.status = RunStatus.STOPPING
    engine, emitter = _engine(run)

    result = (
        engine.pause_run("run-1", reason="server_shutdown")
        if operation == "pause"
        else engine.cancel_run("run-1")
    )

    assert result.status == terminal_status
    event = emitter.events[0]
    assert isinstance(event, RunStatusChanged)
    assert (event.old_status, event.new_status) == (RunStatus.STOPPING, terminal_status)


@pytest.mark.parametrize("operation", ["resume", "stop"])
def test_stopping_run_rejects_nonterminal_transition(operation: str) -> None:
    run = _active_run()
    run.status = RunStatus.STOPPING
    engine, _ = _engine(run)

    with pytest.raises(InvalidTransitionError):
        if operation == "resume":
            engine.resume_run("run-1")
        else:
            engine.stop_run("run-1")


@pytest.mark.parametrize(
    "status",
    [RunStatus.PAUSED, RunStatus.COMPLETED, RunStatus.FAILED],
)
def test_non_active_run_cannot_stop(status: RunStatus) -> None:
    run = _active_run()
    run.status = status
    engine, _ = _engine(run)

    with pytest.raises(InvalidTransitionError):
        engine.stop_run("run-1")
