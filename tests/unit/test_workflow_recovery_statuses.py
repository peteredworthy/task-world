"""Recovery status guards exercised directly through the workflow service."""

import pytest

from orchestrator.config import RunStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.state import Run, StepState, TaskState
from orchestrator.workflow import InvalidTransitionError, WorkflowService


@pytest.mark.parametrize("status", [RunStatus.ACTIVE, RunStatus.COMPLETED])
async def test_recover_run_rejects_each_nonrecoverable_status(status: RunStatus) -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            service = WorkflowService(session)
            run = Run(
                id=f"run-non-recoverable-{status.value}",
                repo_name="project",
                source_branch="main",
                status=status,
                steps=[
                    StepState(
                        id="step-1",
                        config_id="S-01",
                        tasks=[TaskState(id="task-1", config_id="T-01")],
                    )
                ],
            )
            await service.create_run(run)

            with pytest.raises(InvalidTransitionError):
                await service.recover_run(run.id, "task-1")
    finally:
        await engine.dispose()
