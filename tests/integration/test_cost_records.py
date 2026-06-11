"""Integration coverage for cost records and interaction log artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config import ChecklistStatus, Priority, RunStatus, TaskStatus
from orchestrator.db import (
    CostRecordModel,
    InteractionLogArtifactModel,
    RunModel,
    RunRepository,
    StepModel,
    TaskModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.runners import (
    AttemptStore,
    EventBroadcaster,
    MockAgent,
    MockBehavior,
    PhaseHandler,
)
from orchestrator.runners.types import ExecutionContext
from orchestrator.state.models import ActionLog, ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.service import WorkflowService


@pytest.fixture
async def session_factory_fixture() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    yield factory
    await engine.dispose()


def _run_with_task() -> Run:
    now = datetime.now(timezone.utc)
    return Run(
        id="cost-run",
        repo_name="test-project",
        source_branch="main",
        status=RunStatus.DRAFT,
        steps=[
            StepState(
                id="cost-step",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="cost-task",
                        config_id="T-01",
                        status=TaskStatus.PENDING,
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Requirement",
                                priority=Priority.CRITICAL,
                            )
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


def _embedded_cost_routine() -> dict[str, object]:
    return {
        "id": "cost-routine",
        "name": "Cost Routine",
        "steps": [
            {
                "id": "S-01",
                "title": "Cost Step",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Cost Task",
                        "task_context": "Do the cost-record task.",
                        "requirements": [
                            {
                                "id": "R1",
                                "desc": "Requirement",
                            }
                        ],
                    }
                ],
            }
        ],
    }


async def test_phase_handler_records_cost_and_interaction_logs_for_each_agent_execution(
    session_factory_fixture: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    phase_handler = PhaseHandler(
        AttemptStore(session_factory_fixture),
        EventBroadcaster(session_factory_fixture),
    )

    async with session_factory_fixture() as service_session:
        service = WorkflowService(service_session)
        await service.create_run(_run_with_task())
        await service.apply_start_run("cost-run")
        await service.start_task("cost-run", "cost-task")

        run = await service.get_run("cost-run")
        task = await service.get_task("cost-run", "cost-task")
        builder = MockAgent(
            MockBehavior(
                complete_requirements=["R1"],
                tokens_read=100,
                tokens_write=40,
                tokens_cache=7,
                duration_ms=1200,
                output_lines=["builder output"],
            )
        )
        await phase_handler.execute_phase(
            phase="building",
            run=run,
            task_state=task,
            service=service,
            agent=builder,
            context=ExecutionContext(
                run_id="cost-run",
                task_id="cost-task",
                working_dir=str(tmp_path),
                prompt="builder prompt",
                requirements=["R1: Requirement"],
            ),
            req_desc_to_id={"requirement": "R1"},
            agent_runner_type_value="",
            session=service_session,
        )

        run = await service.get_run("cost-run")
        task = await service.get_task("cost-run", "cost-task")
        assert task.status == TaskStatus.VERIFYING
        verifier = MockAgent(
            MockBehavior(
                tokens_read=30,
                tokens_write=10,
                tokens_cache=3,
                duration_ms=800,
                output_lines=["verifier output"],
            )
        )

        await phase_handler.execute_phase(
            phase="verifying",
            run=run,
            task_state=task,
            service=service,
            agent=verifier,
            context=ExecutionContext(
                run_id="cost-run",
                task_id="cost-task",
                working_dir=str(tmp_path),
                prompt="verifier prompt",
                requirements=["R1: Requirement"],
            ),
            req_desc_to_id={"requirement": "R1"},
            session=service_session,
        )

    async with session_factory_fixture() as session:
        cost_rows = (
            (await session.execute(select(CostRecordModel).order_by(CostRecordModel.phase)))
            .scalars()
            .all()
        )
        assert len(cost_rows) == 2
        identities = {
            (row.run_id, row.task_id, row.attempt_num, row.agent_runner_type, row.phase)
            for row in cost_rows
        }
        assert identities == {
            ("cost-run", "cost-task", 1, "cli_subprocess", "building"),
            ("cost-run", "cost-task", 1, "cli_subprocess", "verifying"),
        }
        by_phase = {row.phase: row for row in cost_rows}
        assert by_phase["building"].input_tokens == 100
        assert by_phase["building"].output_tokens == 40
        assert by_phase["building"].cache_read_tokens == 7
        assert by_phase["building"].wall_time_ms == 1200
        assert by_phase["verifying"].input_tokens == 30
        assert by_phase["verifying"].output_tokens == 10
        assert by_phase["verifying"].cache_read_tokens == 3
        assert by_phase["verifying"].wall_time_ms == 800

        artifacts = (
            (
                await session.execute(
                    select(InteractionLogArtifactModel).order_by(InteractionLogArtifactModel.phase)
                )
            )
            .scalars()
            .all()
        )
        assert len(artifacts) == 2
        artifact_by_phase = {artifact.phase: artifact for artifact in artifacts}
        assert artifact_by_phase["building"].prompt_text == "builder prompt"
        assert artifact_by_phase["building"].output_text == "builder output"
        assert artifact_by_phase["verifying"].prompt_text == "verifier prompt"
        assert artifact_by_phase["verifying"].output_text == "verifier output"

        run_state = await RunRepository(session).get("cost-run")
        assert run_state.total_tokens_read == 130
        assert run_state.total_tokens_write == 50
        assert run_state.total_tokens_cache == 10


async def test_phase_handler_records_recovering_cost_and_interaction_log_prompt(
    session_factory_fixture: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    phase_handler = PhaseHandler(
        AttemptStore(session_factory_fixture),
        EventBroadcaster(session_factory_fixture),
    )

    async with session_factory_fixture() as service_session:
        service = WorkflowService(service_session)
        run = _run_with_task()
        run.routine_embedded = _embedded_cost_routine()
        await service.create_run(run)
        await service.apply_start_run("cost-run")
        await service.start_task("cost-run", "cost-task")
        await service.update_checklist_item("cost-run", "cost-task", "R1", ChecklistStatus.DONE)
        await service.submit_for_verification("cost-run", "cost-task")
        await service.trigger_recovery(
            "cost-run",
            "cost-task",
            "verification script crashed",
        )

        recovering_run = await service.get_run("cost-run")
        recovering_task = await service.get_task("cost-run", "cost-task")
        assert recovering_task.status == TaskStatus.RECOVERING
        assert recovering_task.attempts[-1].builder_prompt is not None
        assert recovering_task.attempts[-1].builder_prompt.startswith("[RECOVERY PROMPT]")
        recovery_context_prompt = "recovery execution prompt"

        recovery_agent = MockAgent(
            MockBehavior(
                tokens_read=55,
                tokens_write=21,
                tokens_cache=8,
                duration_ms=900,
                output_lines=["recovery output"],
            )
        )
        await phase_handler.execute_phase(
            phase="recovering",
            run=recovering_run,
            task_state=recovering_task,
            service=service,
            agent=recovery_agent,
            context=ExecutionContext(
                run_id="cost-run",
                task_id="cost-task",
                working_dir=str(tmp_path),
                prompt=recovery_context_prompt,
                requirements=[],
            ),
            req_desc_to_id={},
            agent_runner_type_value="cli_subprocess",
            session=service_session,
        )

    async with session_factory_fixture() as session:
        cost_row = (
            await session.execute(
                select(CostRecordModel).where(CostRecordModel.phase == "recovering")
            )
        ).scalar_one()
        assert cost_row.run_id == "cost-run"
        assert cost_row.task_id == "cost-task"
        assert cost_row.attempt_num == 1
        assert cost_row.agent_runner_type == "cli_subprocess"
        assert cost_row.input_tokens == 55
        assert cost_row.output_tokens == 21
        assert cost_row.cache_read_tokens == 8
        assert cost_row.cache_write_tokens == 0
        assert cost_row.wall_time_ms == 900

        artifact = (
            await session.execute(
                select(InteractionLogArtifactModel).where(
                    InteractionLogArtifactModel.phase == "recovering"
                )
            )
        ).scalar_one()
        assert artifact.cost_record_id == cost_row.id
        assert artifact.prompt_text == recovery_context_prompt
        assert artifact.output_text == "recovery output"


async def test_phase_handler_persists_per_model_cost_usage(
    session_factory_fixture: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    phase_handler = PhaseHandler(
        AttemptStore(session_factory_fixture),
        EventBroadcaster(session_factory_fixture),
    )

    async with session_factory_fixture() as service_session:
        service = WorkflowService(service_session)
        await service.create_run(_run_with_task())
        await service.apply_start_run("cost-run")
        await service.start_task("cost-run", "cost-task")

        agent = MockAgent(
            MockBehavior(
                complete_requirements=["R1"],
                tokens_read=1,
                tokens_write=1,
                tokens_cache=1,
                duration_ms=1,
                output_lines=["builder output with usage"],
                action_log=ActionLog(
                    agent_model="gpt-4o",
                    total_input_tokens=1_000,
                    total_output_tokens=500,
                    total_cache_read_tokens=100,
                    total_cache_creation_tokens=200,
                    total_duration_ms=1_234,
                ),
            )
        )

        run = await service.get_run("cost-run")
        task = await service.get_task("cost-run", "cost-task")
        await phase_handler.execute_phase(
            phase="building",
            run=run,
            task_state=task,
            service=service,
            agent=agent,
            context=ExecutionContext(
                run_id="cost-run",
                task_id="cost-task",
                working_dir=str(tmp_path),
                prompt="builder prompt with usage",
                requirements=["R1: Requirement"],
            ),
            req_desc_to_id={"requirement": "R1"},
            agent_runner_type_value="cli_subprocess",
            session=service_session,
        )

    async with session_factory_fixture() as session:
        cost_row = (await session.execute(select(CostRecordModel))).scalar_one()
        assert cost_row.model_name == "gpt-4o"
        assert cost_row.input_tokens == 1_000
        assert cost_row.output_tokens == 500
        assert cost_row.cache_read_tokens == 100
        assert cost_row.cache_write_tokens == 200
        assert cost_row.wall_time_ms == 1_234
        assert cost_row.cost_usd > 0
        assert cost_row.token_usage_by_model is not None
        assert cost_row.token_usage_by_model[0]["model"] == "gpt-4o"
        assert cost_row.token_usage_by_model[0]["cache_creation_tokens"] == 200

        run_state = await RunRepository(session).get("cost-run")
        assert run_state.total_tokens_read == 1_000
        assert run_state.total_tokens_write == 500
        assert run_state.total_tokens_cache == 300


async def test_cost_report_aggregates_temp_database(tmp_path: Path) -> None:
    db_path = tmp_path / "cost-report.db"
    engine = create_engine(db_path)
    await init_db(engine)
    factory = create_session_factory(engine)
    now = datetime.now(timezone.utc)

    async with factory() as session:
        session.add(
            RunModel(
                id="run-a",
                repo_name="repo",
                status="completed",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(StepModel(id="step-a", run_id="run-a", config_id="S-01", order_index=0))
        session.add(
            TaskModel(
                id="task-a",
                step_id="step-a",
                config_id="T-01",
                order_index=0,
                checklist=[],
            )
        )
        session.add_all(
            [
                CostRecordModel(
                    id="cost-a",
                    run_id="run-a",
                    task_id="task-a",
                    attempt_num=1,
                    agent_runner_type="cli_subprocess",
                    phase="building",
                    mode_tag="loop",
                    model_name="model-a",
                    input_tokens=100,
                    output_tokens=50,
                    cache_read_tokens=10,
                    cache_write_tokens=5,
                    wall_time_ms=1000,
                    cost_usd=0.25,
                    created_at=now,
                ),
                CostRecordModel(
                    id="cost-b",
                    run_id="run-a",
                    task_id="task-a",
                    attempt_num=1,
                    agent_runner_type="cli_subprocess",
                    phase="verifying",
                    mode_tag="loop",
                    model_name="model-a",
                    input_tokens=40,
                    output_tokens=20,
                    cache_read_tokens=3,
                    cache_write_tokens=2,
                    wall_time_ms=400,
                    cost_usd=0.10,
                    created_at=now,
                ),
            ]
        )
        await session.commit()
    await engine.dispose()

    result = subprocess.run(
        [sys.executable, "scripts/cost_report.py", "--db", str(db_path), "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)

    assert report["by_run"] == [
        {
            "run_id": "run-a",
            "executions": 2,
            "input_tokens": 140,
            "output_tokens": 70,
            "cache_read_tokens": 13,
            "cache_write_tokens": 7,
            "wall_time_ms": 1400,
            "cost_usd": 0.35,
        }
    ]
    assert report["by_mode"] == [
        {
            "agent_runner_type": "cli_subprocess",
            "mode_tag": "loop",
            "executions": 2,
            "input_tokens": 140,
            "output_tokens": 70,
            "cache_read_tokens": 13,
            "cache_write_tokens": 7,
            "wall_time_ms": 1400,
            "cost_usd": 0.35,
        }
    ]
