"""Repository pattern for Run persistence."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from orchestrator.config.enums import (
    AgentRunnerType,
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db.models import (
    AttemptModel,
    ClarificationRequestModel,
    ClarificationResponseModel,
    ReplayCheckpointModel,
    RunModel,
    StepModel,
    TaskModel,
)
from orchestrator.state.errors import RunNotFoundError
from orchestrator.runners.action_log import ActionLog
from orchestrator.state.models import (
    Attempt,
    AttemptMetrics,
    ChecklistItem,
    GradeSnapshotItem,
    HumanApproval,
    Run,
    StepState,
    TaskState,
)
from orchestrator.workflow.clarifications import (
    ClarificationAnswer,
    ClarificationQuestion,
    ClarificationRequest,
    ClarificationResponse,
)
from orchestrator.time_utils import (
    ensure_utc as _core_ensure_utc,
    ensure_utc_optional as _core_ensure_utc_optional,
)


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime has UTC timezone info.

    SQLite does not store timezone info, so datetimes retrieved from the
    database are naive. This re-attaches UTC so they serialize with a Z
    suffix in JSON responses.
    """
    return _core_ensure_utc(dt)


def _ensure_utc_optional(dt: datetime | None) -> datetime | None:
    """Like _ensure_utc but accepts and returns None for optional fields."""
    return _core_ensure_utc_optional(dt)


def _eager_run_query(*, include_action_logs: bool = True) -> Any:  # noqa: ANN401
    """Build a select query with all relationships eagerly loaded.

    Args:
        include_action_logs: If False, defers loading of large text/JSON
            columns (action_log_json, builder/verifier prompts, agent_output,
            routine_embedded) that are not needed for list/summary views.
    """
    attempt_load = selectinload(TaskModel.attempts)
    if not include_action_logs:
        attempt_load = (
            attempt_load.defer(AttemptModel.action_log_json)
            .defer(AttemptModel.builder_prompt)
            .defer(AttemptModel.verifier_prompt)
            .defer(AttemptModel.agent_output)
        )
    query = select(RunModel).options(
        selectinload(RunModel.steps).selectinload(StepModel.tasks).options(attempt_load)
    )
    if not include_action_logs:
        query = query.options(defer(RunModel.routine_embedded))
    return query


def _to_domain(model: RunModel, *, action_logs_loaded: bool = True) -> Run:
    """Convert ORM model to domain Pydantic model.

    When action_logs_loaded is False, deferred columns (action_log_json,
    builder_prompt, verifier_prompt, agent_output, routine_embedded) are
    not available and will be set to None.
    """
    steps: list[StepState] = []
    for step_model in model.steps:
        tasks: list[TaskState] = []
        for task_model in step_model.tasks:
            attempts: list[Attempt] = []
            for att_model in task_model.attempts:
                snapshot_data: list[dict[str, Any]] = att_model.grade_snapshot or []
                grade_snapshot = [
                    GradeSnapshotItem(
                        req_id=item["req_id"],
                        grade=item.get("grade"),
                        grade_reason=item.get("grade_reason"),
                    )
                    for item in snapshot_data
                ]
                # Deserialize action_log from JSON if present and loaded
                action_log = None
                if action_logs_loaded and att_model.action_log_json:
                    try:
                        action_log = ActionLog.model_validate(att_model.action_log_json)
                    except Exception:
                        pass  # Gracefully handle invalid data

                attempts.append(
                    Attempt(
                        id=att_model.id,
                        attempt_num=att_model.attempt_num,
                        started_at=_ensure_utc_optional(att_model.started_at),
                        completed_at=_ensure_utc_optional(att_model.completed_at),
                        builder_prompt=att_model.builder_prompt if action_logs_loaded else None,
                        verifier_prompt=att_model.verifier_prompt if action_logs_loaded else None,
                        verifier_comment=att_model.verifier_comment,
                        outcome=att_model.outcome,
                        metrics=AttemptMetrics(
                            tokens_read=att_model.tokens_read,
                            tokens_write=att_model.tokens_write,
                            tokens_cache=att_model.tokens_cache,
                            duration_ms=att_model.duration_ms,
                            num_actions=att_model.num_actions,
                        ),
                        grade_snapshot=grade_snapshot,
                        auto_verify_results=att_model.auto_verify_results or [],
                        agent_type=AgentRunnerType(att_model.runner_type)
                        if att_model.runner_type
                        else None,
                        agent_model=att_model.agent_model,
                        agent_settings=att_model.agent_settings or {},
                        agent_output=att_model.agent_output if action_logs_loaded else None,
                        error=att_model.error,
                        action_log=action_log,
                        start_commit=att_model.start_commit,
                        end_commit=att_model.end_commit,
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
                    title=task_model.title or "",
                    status=TaskStatus(task_model.status),
                    complexity=task_model.complexity or "standard",
                    checklist=checklist,
                    attempts=attempts,
                    current_attempt=task_model.current_attempt,
                    max_attempts=task_model.max_attempts,
                    pending_action_type=task_model.pending_action_type,
                    pending_clarification_id=task_model.pending_clarification_id,
                    parent_task_id=task_model.parent_task_id,
                    fan_out_index=task_model.fan_out_index,
                    fan_out_input=task_model.fan_out_input,
                    fan_out_output=task_model.fan_out_output,
                )
            )

        # Convert human_approval from JSON to HumanApproval model
        human_approval = None
        if step_model.human_approval:
            approval_data = step_model.human_approval
            human_approval = HumanApproval(
                approved_by=approval_data["approved_by"],
                approved_at=_ensure_utc(
                    datetime.fromisoformat(approval_data["approved_at"].replace("Z", "+00:00"))
                    if isinstance(approval_data["approved_at"], str)
                    else approval_data["approved_at"]
                ),
                comment=approval_data.get("comment"),
            )

        steps.append(
            StepState(
                id=step_model.id,
                config_id=step_model.config_id,
                title=step_model.title or "",
                tasks=tasks,
                completed=bool(step_model.completed),
                human_approval=human_approval,
            )
        )

    # Convert env_file_specs from JSON to EnvFileSpec models
    from orchestrator.envfiles.models import EnvFileSpec

    env_specs_data: list[dict[str, Any]] = model.env_file_specs or []
    env_file_specs = [
        EnvFileSpec(
            relative_path=spec["relative_path"],
            promote_on_success=spec.get("promote_on_success", False),
        )
        for spec in env_specs_data
    ]

    return Run(
        id=model.id,
        repo_name=model.repo_name,
        status=RunStatus(model.status),
        pause_reason=model.pause_reason,
        last_error=model.last_error,
        routine_id=model.routine_id,
        routine_sha=model.routine_sha,
        routine_source=RoutineSource(model.routine_source) if model.routine_source else None,
        routine_embedded=model.routine_embedded if action_logs_loaded else None,
        routine_path=model.routine_path,
        routine_commit=model.routine_commit,
        agent_type=AgentRunnerType(model.runner_type) if model.runner_type else None,
        agent_config=model.runner_config or {},
        verifier_model=model.verifier_model,
        worktree_enabled=bool(model.worktree_enabled),
        worktree_path=model.worktree_path,
        delete_worktree_on_completion=bool(model.delete_worktree_on_completion),
        source_branch=model.source_branch,
        merge_strategy=model.merge_strategy or "squash",
        config=model.config or {},
        env_file_specs=env_file_specs,
        env_source_dir=model.env_source_dir,
        steps=steps,
        current_step_index=model.current_step_index,
        created_at=_ensure_utc(model.created_at),
        updated_at=_ensure_utc(model.updated_at),
        started_at=_ensure_utc_optional(model.started_at),
        completed_at=_ensure_utc_optional(model.completed_at),
        agent_started_at=_ensure_utc_optional(model.runner_started_at),
        total_tokens_read=model.total_tokens_read,
        total_tokens_write=model.total_tokens_write,
        total_tokens_cache=model.total_tokens_cache,
        total_duration_ms=model.total_duration_ms,
        total_num_actions=model.total_num_actions,
    )


def _to_model(run: Run) -> RunModel:
    """Convert domain Pydantic model to ORM model."""
    steps: list[StepModel] = []
    for step_idx, step in enumerate(run.steps):
        tasks: list[TaskModel] = []
        for task_idx, task in enumerate(step.tasks):
            attempts: list[AttemptModel] = []
            for att in task.attempts:
                snapshot_json = (
                    [item.model_dump(mode="json") for item in att.grade_snapshot]
                    if att.grade_snapshot
                    else None
                )
                auto_verify_json = att.auto_verify_results if att.auto_verify_results else None
                action_log_json = att.action_log.model_dump(mode="json") if att.action_log else None
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
                        num_actions=att.metrics.num_actions,
                        grade_snapshot=snapshot_json,
                        auto_verify_results=auto_verify_json,
                        runner_type=att.agent_type.value if att.agent_type else None,
                        agent_model=att.agent_model,
                        agent_settings=att.agent_settings if att.agent_settings else None,
                        agent_output=att.agent_output,
                        error=att.error,
                        action_log_json=action_log_json,
                        start_commit=att.start_commit,
                        end_commit=att.end_commit,
                    )
                )

            checklist_json = [item.model_dump(mode="json") for item in task.checklist]

            tasks.append(
                TaskModel(
                    id=task.id,
                    step_id=step.id,
                    config_id=task.config_id,
                    title=task.title,
                    complexity=task.complexity,
                    order_index=task_idx,
                    status=task.status.value,
                    checklist=checklist_json,
                    current_attempt=task.current_attempt,
                    max_attempts=task.max_attempts,
                    pending_action_type=task.pending_action_type,
                    pending_clarification_id=task.pending_clarification_id,
                    parent_task_id=task.parent_task_id,
                    fan_out_index=task.fan_out_index,
                    fan_out_input=task.fan_out_input,
                    fan_out_output=task.fan_out_output,
                    attempts=attempts,
                )
            )

        # Convert HumanApproval to JSON
        human_approval_json = None
        if step.human_approval:
            human_approval_json = step.human_approval.model_dump(mode="json")

        steps.append(
            StepModel(
                id=step.id,
                run_id=run.id,
                config_id=step.config_id,
                title=step.title,
                order_index=step_idx,
                completed=step.completed,
                human_approval=human_approval_json,
                tasks=tasks,
            )
        )

    # Convert env_file_specs to JSON
    env_specs_json = [spec.model_dump(mode="json") for spec in run.env_file_specs]

    return RunModel(
        id=run.id,
        repo_name=run.repo_name,
        status=run.status.value,
        pause_reason=run.pause_reason,
        last_error=run.last_error,
        routine_id=run.routine_id,
        routine_sha=run.routine_sha,
        routine_source=run.routine_source.value if run.routine_source else None,
        routine_embedded=run.routine_embedded,
        routine_path=run.routine_path,
        routine_commit=run.routine_commit,
        runner_type=run.agent_type.value if run.agent_type else None,
        runner_config=run.agent_config,
        verifier_model=run.verifier_model,
        worktree_enabled=run.worktree_enabled,
        worktree_path=run.worktree_path,
        delete_worktree_on_completion=run.delete_worktree_on_completion,
        source_branch=run.source_branch,
        merge_strategy=run.merge_strategy,
        config=run.config,
        env_file_specs=env_specs_json,
        env_source_dir=run.env_source_dir,
        steps=steps,
        current_step_index=run.current_step_index,
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        runner_started_at=run.agent_started_at,
        total_tokens_read=run.total_tokens_read,
        total_tokens_write=run.total_tokens_write,
        total_tokens_cache=run.total_tokens_cache,
        total_duration_ms=run.total_duration_ms,
        total_num_actions=run.total_num_actions,
    )


class RunRepository:
    """Repository for Run persistence using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        """Expose session for internal methods."""
        return self._session

    async def get(self, run_id: str) -> Run:
        """Get a run by ID. Raises RunNotFoundError if not found."""
        result = await self._session.execute(_eager_run_query().where(RunModel.id == run_id))
        model = result.scalar_one_or_none()
        if model is None:
            raise RunNotFoundError(run_id)
        return _to_domain(model)

    async def list_all(
        self, limit: int | None = None, *, include_action_logs: bool = True
    ) -> list[Run]:
        """List all runs, optionally limited to the most recent N runs."""
        query = _eager_run_query(include_action_logs=include_action_logs).order_by(
            RunModel.created_at.desc()
        )
        if limit is not None:
            query = query.limit(limit)
        result = await self._session.execute(query)
        return [
            _to_domain(m, action_logs_loaded=include_action_logs) for m in result.scalars().all()
        ]

    async def list_by_repo(self, repo_name: str, *, include_action_logs: bool = True) -> list[Run]:
        """List runs filtered by repository name."""
        result = await self._session.execute(
            _eager_run_query(include_action_logs=include_action_logs).where(
                RunModel.repo_name == repo_name
            )
        )
        return [
            _to_domain(m, action_logs_loaded=include_action_logs) for m in result.scalars().all()
        ]

    async def list_by_status(
        self, status: RunStatus, *, include_action_logs: bool = True
    ) -> list[Run]:
        """List runs filtered by status."""
        result = await self._session.execute(
            _eager_run_query(include_action_logs=include_action_logs).where(
                RunModel.status == status.value
            )
        )
        return [
            _to_domain(m, action_logs_loaded=include_action_logs) for m in result.scalars().all()
        ]

    async def list_by_repo_and_status(
        self, repo_name: str, status: RunStatus, *, include_action_logs: bool = True
    ) -> list[Run]:
        """List runs filtered by both repository name and status."""
        result = await self._session.execute(
            _eager_run_query(include_action_logs=include_action_logs).where(
                RunModel.repo_name == repo_name,
                RunModel.status == status.value,
            )
        )
        return [
            _to_domain(m, action_logs_loaded=include_action_logs) for m in result.scalars().all()
        ]

    async def list_recent(self, hours: int, *, include_action_logs: bool = True) -> list[Run]:
        """List runs created within the last N hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self._session.execute(
            _eager_run_query(include_action_logs=include_action_logs).where(
                RunModel.created_at >= cutoff
            )
        )
        return [
            _to_domain(m, action_logs_loaded=include_action_logs) for m in result.scalars().all()
        ]

    async def list_repo_names(self) -> list[str]:
        """Return unique repo_name values from all runs."""
        result = await self._session.execute(
            select(distinct(RunModel.repo_name)).order_by(RunModel.repo_name)
        )
        return [row[0] for row in result.all()]

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

    async def create_clarification_request(
        self, request: ClarificationRequest
    ) -> ClarificationRequest:
        """Create a new clarification request."""
        model = ClarificationRequestModel(
            id=request.id,
            run_id=request.run_id,
            task_id=request.task_id,
            attempt_num=request.attempt_num,
            questions=[q.model_dump(mode="json") for q in request.questions],
            created_at=request.created_at,
            responded_at=request.responded_at,
        )
        self._session.add(model)
        await self._session.flush()
        return request

    async def get_clarification_request(self, request_id: str) -> ClarificationRequest | None:
        """Get a clarification request by ID."""
        result = await self._session.execute(
            select(ClarificationRequestModel).where(ClarificationRequestModel.id == request_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._clarification_request_from_model(model)

    async def get_pending_clarification(
        self, run_id: str, task_id: str
    ) -> ClarificationRequest | None:
        """Get the pending clarification request for a task."""
        result = await self._session.execute(
            select(ClarificationRequestModel).where(
                ClarificationRequestModel.run_id == run_id,
                ClarificationRequestModel.task_id == task_id,
                ClarificationRequestModel.responded_at.is_(None),
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._clarification_request_from_model(model)

    async def save_clarification_response(self, response: ClarificationResponse) -> None:
        """Save a clarification response and mark request as responded."""
        # Create response model
        model = ClarificationResponseModel(
            id=str(uuid.uuid4()),
            request_id=response.request_id,
            answers=[a.model_dump(mode="json") for a in response.answers],
            responded_by=response.answers[0].answered_by if response.answers else "unknown",
            responded_at=response.responded_at,
        )
        self._session.add(model)

        # Update request with responded_at
        result = await self._session.execute(
            select(ClarificationRequestModel).where(
                ClarificationRequestModel.id == response.request_id
            )
        )
        request_model = result.scalar_one_or_none()
        if request_model:
            request_model.responded_at = response.responded_at

        await self._session.flush()

    async def get_clarification_history(
        self,
        run_id: str,
        task_id: str,
    ) -> list[tuple[ClarificationRequest, ClarificationResponse | None]]:
        """Return all clarification rounds for a task, ordered by creation time ascending.

        Pending rounds have response=None.
        """
        result = await self._session.execute(
            select(ClarificationRequestModel)
            .where(
                ClarificationRequestModel.run_id == run_id,
                ClarificationRequestModel.task_id == task_id,
            )
            .order_by(ClarificationRequestModel.created_at.asc())
            .options(selectinload(ClarificationRequestModel.response))
        )
        request_models = result.scalars().all()

        history: list[tuple[ClarificationRequest, ClarificationResponse | None]] = []
        for req_model in request_models:
            request = self._clarification_request_from_model(req_model)
            response: ClarificationResponse | None = None
            if req_model.response is not None:
                resp_model = req_model.response
                response = ClarificationResponse(
                    request_id=resp_model.request_id,
                    answers=[ClarificationAnswer(**a) for a in resp_model.answers],
                    responded_at=_ensure_utc(resp_model.responded_at),
                )
            history.append((request, response))
        return history

    def _clarification_request_from_model(
        self, model: ClarificationRequestModel
    ) -> ClarificationRequest:
        """Convert ORM model to Pydantic model."""
        return ClarificationRequest(
            id=model.id,
            run_id=model.run_id,
            task_id=model.task_id,
            attempt_num=model.attempt_num,
            questions=[ClarificationQuestion(**q) for q in model.questions],
            created_at=_ensure_utc(model.created_at),
            responded_at=_ensure_utc_optional(model.responded_at),
        )


class CheckpointRepository:
    """Repository for replay checkpoint persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_checkpoint(self, journal_path: str) -> ReplayCheckpointModel | None:
        """Get the checkpoint for a journal path, or None if not found."""
        result = await self._session.execute(
            select(ReplayCheckpointModel).where(ReplayCheckpointModel.journal_path == journal_path)
        )
        return result.scalar_one_or_none()

    async def upsert_checkpoint(
        self,
        journal_path: str,
        last_applied_sequence: int,
        last_applied_timestamp: datetime,
        backup_snapshot_id: str | None = None,
    ) -> ReplayCheckpointModel:
        """Create or update a checkpoint. Calls flush(), not commit()."""
        result = await self._session.execute(
            select(ReplayCheckpointModel).where(ReplayCheckpointModel.journal_path == journal_path)
        )
        checkpoint = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if checkpoint:
            checkpoint.last_applied_sequence = last_applied_sequence
            checkpoint.last_applied_timestamp = last_applied_timestamp
            checkpoint.updated_at = now
            if backup_snapshot_id is not None:
                checkpoint.backup_snapshot_id = backup_snapshot_id
        else:
            checkpoint = ReplayCheckpointModel(
                journal_path=journal_path,
                last_applied_sequence=last_applied_sequence,
                last_applied_timestamp=last_applied_timestamp,
                backup_snapshot_id=backup_snapshot_id,
                updated_at=now,
            )
            self._session.add(checkpoint)
        await self._session.flush()
        await self._session.refresh(checkpoint)
        return checkpoint

    @staticmethod
    async def upsert_checkpoint_in_session(
        session: AsyncSession,
        journal_path: str,
        last_applied_sequence: int,
        last_applied_timestamp: datetime,
    ) -> None:
        """Upsert a checkpoint within an existing session (for atomic batch commits)."""
        result = await session.execute(
            select(ReplayCheckpointModel).where(ReplayCheckpointModel.journal_path == journal_path)
        )
        checkpoint = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if checkpoint:
            checkpoint.last_applied_sequence = last_applied_sequence
            checkpoint.last_applied_timestamp = last_applied_timestamp
            checkpoint.updated_at = now
        else:
            checkpoint = ReplayCheckpointModel(
                journal_path=journal_path,
                last_applied_sequence=last_applied_sequence,
                last_applied_timestamp=last_applied_timestamp,
                updated_at=now,
            )
            session.add(checkpoint)
