"""Repository pattern for Run persistence."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from orchestrator.config.enums import (
    AgentType,
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db.models import AttemptModel, RunModel, StepModel, TaskModel
from orchestrator.state.errors import RunNotFoundError
from orchestrator.state.models import (
    Attempt,
    AttemptMetrics,
    ChecklistItem,
    Run,
    StepState,
    TaskState,
)


def _eager_run_query() -> Any:  # noqa: ANN401
    """Build a select query with all relationships eagerly loaded."""
    return select(RunModel).options(
        selectinload(RunModel.steps).selectinload(StepModel.tasks).selectinload(TaskModel.attempts)
    )


def _to_domain(model: RunModel) -> Run:
    """Convert ORM model to domain Pydantic model."""
    steps: list[StepState] = []
    for step_model in model.steps:
        tasks: list[TaskState] = []
        for task_model in step_model.tasks:
            attempts: list[Attempt] = []
            for att_model in task_model.attempts:
                attempts.append(
                    Attempt(
                        id=att_model.id,
                        attempt_num=att_model.attempt_num,
                        started_at=att_model.started_at,
                        completed_at=att_model.completed_at,
                        builder_prompt=att_model.builder_prompt,
                        verifier_prompt=att_model.verifier_prompt,
                        verifier_comment=att_model.verifier_comment,
                        outcome=att_model.outcome,
                        metrics=AttemptMetrics(
                            tokens_read=att_model.tokens_read,
                            tokens_write=att_model.tokens_write,
                            tokens_cache=att_model.tokens_cache,
                            duration_ms=att_model.duration_ms,
                        ),
                    )
                )

            checklist_data: list[dict[str, Any]] = task_model.checklist or []
            checklist: list[ChecklistItem] = [
                ChecklistItem(
                    req_id=item["req_id"],
                    desc=item["desc"],
                    priority=Priority(item["priority"]),
                    status=ChecklistStatus(item.get("status", "open")),
                    note=item.get("note"),
                    grade=item.get("grade"),
                    grade_reason=item.get("grade_reason"),
                )
                for item in checklist_data
            ]

            tasks.append(
                TaskState(
                    id=task_model.id,
                    config_id=task_model.config_id,
                    status=TaskStatus(task_model.status),
                    checklist=checklist,
                    attempts=attempts,
                    current_attempt=task_model.current_attempt,
                    max_attempts=task_model.max_attempts,
                )
            )

        steps.append(
            StepState(
                id=step_model.id,
                config_id=step_model.config_id,
                tasks=tasks,
                completed=bool(step_model.completed),
            )
        )

    return Run(
        id=model.id,
        project_id=model.project_id,
        status=RunStatus(model.status),
        routine_id=model.routine_id,
        routine_sha=model.routine_sha,
        routine_source=RoutineSource(model.routine_source) if model.routine_source else None,
        agent_type=AgentType(model.agent_type) if model.agent_type else None,
        agent_config=model.agent_config or {},
        worktree_enabled=bool(model.worktree_enabled),
        worktree_path=model.worktree_path,
        delete_worktree_on_completion=bool(model.delete_worktree_on_completion),
        config=model.config or {},
        steps=steps,
        current_step_index=model.current_step_index,
        created_at=model.created_at,
        updated_at=model.updated_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
        total_tokens_read=model.total_tokens_read,
        total_tokens_write=model.total_tokens_write,
        total_tokens_cache=model.total_tokens_cache,
        total_duration_ms=model.total_duration_ms,
    )


def _to_model(run: Run) -> RunModel:
    """Convert domain Pydantic model to ORM model."""
    steps: list[StepModel] = []
    for step_idx, step in enumerate(run.steps):
        tasks: list[TaskModel] = []
        for task_idx, task in enumerate(step.tasks):
            attempts: list[AttemptModel] = []
            for att in task.attempts:
                attempts.append(
                    AttemptModel(
                        id=att.id,
                        task_id=task.id,
                        attempt_num=att.attempt_num,
                        started_at=att.started_at,
                        completed_at=att.completed_at,
                        builder_prompt=att.builder_prompt,
                        verifier_prompt=att.verifier_prompt,
                        verifier_comment=att.verifier_comment,
                        outcome=att.outcome,
                        tokens_read=att.metrics.tokens_read,
                        tokens_write=att.metrics.tokens_write,
                        tokens_cache=att.metrics.tokens_cache,
                        duration_ms=att.metrics.duration_ms,
                    )
                )

            checklist_json = [item.model_dump(mode="json") for item in task.checklist]

            tasks.append(
                TaskModel(
                    id=task.id,
                    step_id=step.id,
                    config_id=task.config_id,
                    order_index=task_idx,
                    status=task.status.value,
                    checklist=checklist_json,
                    current_attempt=task.current_attempt,
                    max_attempts=task.max_attempts,
                    attempts=attempts,
                )
            )

        steps.append(
            StepModel(
                id=step.id,
                run_id=run.id,
                config_id=step.config_id,
                order_index=step_idx,
                completed=step.completed,
                tasks=tasks,
            )
        )

    return RunModel(
        id=run.id,
        project_id=run.project_id,
        status=run.status.value,
        routine_id=run.routine_id,
        routine_sha=run.routine_sha,
        routine_source=run.routine_source.value if run.routine_source else None,
        agent_type=run.agent_type.value if run.agent_type else None,
        agent_config=run.agent_config,
        worktree_enabled=run.worktree_enabled,
        worktree_path=run.worktree_path,
        delete_worktree_on_completion=run.delete_worktree_on_completion,
        config=run.config,
        steps=steps,
        current_step_index=run.current_step_index,
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        total_tokens_read=run.total_tokens_read,
        total_tokens_write=run.total_tokens_write,
        total_tokens_cache=run.total_tokens_cache,
        total_duration_ms=run.total_duration_ms,
    )


class RunRepository:
    """Repository for Run persistence using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, run_id: str) -> Run:
        """Get a run by ID. Raises RunNotFoundError if not found."""
        result = await self._session.execute(_eager_run_query().where(RunModel.id == run_id))
        model = result.scalar_one_or_none()
        if model is None:
            raise RunNotFoundError(run_id)
        return _to_domain(model)

    async def list_all(self) -> list[Run]:
        """List all runs."""
        result = await self._session.execute(_eager_run_query())
        return [_to_domain(m) for m in result.scalars().all()]

    async def list_by_project(self, project_id: str) -> list[Run]:
        """List runs filtered by project ID."""
        result = await self._session.execute(
            _eager_run_query().where(RunModel.project_id == project_id)
        )
        return [_to_domain(m) for m in result.scalars().all()]

    async def list_by_status(self, status: RunStatus) -> list[Run]:
        """List runs filtered by status."""
        result = await self._session.execute(
            _eager_run_query().where(RunModel.status == status.value)
        )
        return [_to_domain(m) for m in result.scalars().all()]

    async def list_by_project_and_status(self, project_id: str, status: RunStatus) -> list[Run]:
        """List runs filtered by both project ID and status."""
        result = await self._session.execute(
            _eager_run_query().where(
                RunModel.project_id == project_id,
                RunModel.status == status.value,
            )
        )
        return [_to_domain(m) for m in result.scalars().all()]

    async def save(self, run: Run) -> None:
        """Upsert a run. Calls flush(), not commit()."""
        new_model = _to_model(run)
        await self._session.merge(new_model)
        await self._session.flush()

    async def delete(self, run_id: str) -> None:
        """Delete a run by ID. Raises RunNotFoundError if not found."""
        result = await self._session.execute(select(RunModel).where(RunModel.id == run_id))
        model = result.scalar_one_or_none()
        if model is None:
            raise RunNotFoundError(run_id)
        await self._session.delete(model)
        await self._session.flush()
