"""Clarification API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

import logging

from orchestrator.runners.executor import AgentRunnerExecutor
from orchestrator.api.deps import get_runner_executor, get_run_repository, get_workflow_service
from orchestrator.api.schemas.clarifications import (
    ClarificationAnswerSchema,
    ClarificationHistoryItem,
    ClarificationHistoryResponse,
    ClarificationQuestionSchema,
    ClarificationRequestResponse,
    CreateClarificationRequest,
    PendingActionSchema,
    RespondToClarificationRequest,
)
from orchestrator.api.schemas.tasks import TransitionResponse
from orchestrator.config.enums import RunStatus
from orchestrator.db.repositories import RunRepository
from orchestrator.state.errors import TaskNotFoundError
from orchestrator.workflow.clarifications import ClarificationAnswer, ClarificationQuestion
from orchestrator.workflow.service import WorkflowService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["clarifications"])


def _get_current_user() -> str:
    """Get the current user.

    For now, returns a fixed user ID. In the future, this will be extracted
    from the JWT claims when auth is enabled.
    """
    # TODO: Extract from JWT claims when auth is enabled
    return "user"


async def get_current_user() -> str:
    """Dependency to get the current user."""
    return _get_current_user()


@router.post(
    "/{run_id}/tasks/{task_id}/clarifications",
    response_model=ClarificationRequestResponse,
)
async def create_clarification(
    run_id: str,
    task_id: str,
    request: CreateClarificationRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    user: Annotated[str, Depends(get_current_user)],
) -> ClarificationRequestResponse:
    """Builder submits questions needing answers.

    Transitions the task to PENDING_USER_ACTION and creates a clarification
    request that the user must respond to before work can continue.

    Args:
        run_id: The run ID
        task_id: The task ID
        request: The clarification request containing questions
        service: The workflow service
        user: The current user (from auth)

    Returns:
        The created clarification request
    """
    try:
        questions = [
            ClarificationQuestion(
                id=q.id,
                question=q.question,
                context=q.context,
                options=q.options,
                question_type=q.question_type,
                allow_other=q.allow_other,
                required=q.required,
                min=q.min,
                max=q.max,
                placeholder=q.placeholder,
            )
            for q in request.questions
        ]
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    result = await service.request_clarification(run_id, task_id, questions)
    return ClarificationRequestResponse(
        id=result.id,
        run_id=result.run_id,
        task_id=result.task_id,
        attempt_num=result.attempt_num,
        questions=[
            ClarificationQuestionSchema(
                id=q.id,
                question=q.question,
                context=q.context,
                options=q.options,
                question_type=q.question_type,
                allow_other=q.allow_other,
                required=q.required,
                min=q.min,
                max=q.max,
                placeholder=q.placeholder,
            )
            for q in result.questions
        ],
        created_at=result.created_at,
        responded_at=result.responded_at,
    )


@router.get(
    "/{run_id}/tasks/{task_id}/clarifications/pending",
    response_model=ClarificationRequestResponse | None,
)
async def get_pending_clarification(
    run_id: str,
    task_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> ClarificationRequestResponse | None:
    """Get pending clarification request for a task.

    Returns the pending clarification request if one exists, otherwise None.

    Args:
        run_id: The run ID
        task_id: The task ID
        service: The workflow service

    Returns:
        The pending clarification request, or None if there isn't one
    """
    result = await service.get_pending_clarification(run_id, task_id)
    if result is None:
        return None
    return ClarificationRequestResponse(
        id=result.id,
        run_id=result.run_id,
        task_id=result.task_id,
        attempt_num=result.attempt_num,
        questions=[
            ClarificationQuestionSchema(
                id=q.id,
                question=q.question,
                context=q.context,
                options=q.options,
                question_type=q.question_type,
                allow_other=q.allow_other,
                required=q.required,
                min=q.min,
                max=q.max,
                placeholder=q.placeholder,
            )
            for q in result.questions
        ],
        created_at=result.created_at,
        responded_at=result.responded_at,
    )


@router.get(
    "/{run_id}/tasks/{task_id}/clarifications",
    response_model=ClarificationHistoryResponse,
)
async def get_clarification_history(
    run_id: str,
    task_id: str,
    repo: Annotated[RunRepository, Depends(get_run_repository)],
) -> ClarificationHistoryResponse:
    """Get full clarification history for a task in ascending creation order.

    Returns all clarification rounds (pending and answered).
    Pending rounds appear with response=null.

    Args:
        run_id: The run ID
        task_id: The task ID
        repo: The run repository

    Returns:
        ClarificationHistoryResponse with items in ascending creation order

    Raises:
        404 if run_id or task_id not found
    """
    run = await repo.get(run_id)  # raises RunNotFoundError → 404
    # Validate task_id belongs to this run
    task_found = any(task.id == task_id for step in run.steps for task in step.tasks)
    if not task_found:
        raise TaskNotFoundError(run_id, task_id)

    history = await repo.get_clarification_history(run_id, task_id)

    items: list[ClarificationHistoryItem] = []
    for req, resp in history:
        request_schema = ClarificationRequestResponse(
            id=req.id,
            run_id=req.run_id,
            task_id=req.task_id,
            attempt_num=req.attempt_num,
            questions=[
                ClarificationQuestionSchema(
                    id=q.id,
                    question=q.question,
                    context=q.context,
                    options=q.options,
                    question_type=q.question_type,
                    allow_other=q.allow_other,
                    required=q.required,
                    min=q.min,
                    max=q.max,
                    placeholder=q.placeholder,
                )
                for q in req.questions
            ],
            created_at=req.created_at,
            responded_at=req.responded_at,
        )
        response_schema: RespondToClarificationRequest | None = None
        if resp is not None:
            response_schema = RespondToClarificationRequest(
                answers=[
                    ClarificationAnswerSchema(
                        question_id=a.question_id,
                        selected_option=a.selected_option,
                        free_text=a.free_text,
                        selected_options=a.selected_options,
                        skipped=a.skipped,
                        skip_reason=a.skip_reason,
                    )
                    for a in resp.answers
                ],
            )
        items.append(ClarificationHistoryItem(request=request_schema, response=response_schema))

    return ClarificationHistoryResponse(items=items)


@router.post(
    "/{run_id}/tasks/{task_id}/clarifications/{request_id}/respond",
    response_model=TransitionResponse,
)
async def respond_to_clarification(
    run_id: str,
    task_id: str,
    request_id: str,
    request: RespondToClarificationRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    user: Annotated[str, Depends(get_current_user)],
    repo: Annotated[RunRepository, Depends(get_run_repository)],
    executor: Annotated[AgentRunnerExecutor, Depends(get_runner_executor)],
) -> TransitionResponse:
    """Human submits answers to clarification questions.

    Saves the answers and transitions the task back to BUILDING so the agent
    can continue work with the provided information.

    Args:
        run_id: The run ID
        task_id: The task ID
        request_id: The clarification request ID
        request: The answers to the clarification questions
        service: The workflow service
        user: The current user (from auth)

    Returns:
        The transition result
    """
    from datetime import datetime, timezone

    if not request.skipped:
        # Guard: all required questions must have an answer
        pass

    answers = [
        ClarificationAnswer(
            question_id=a.question_id,
            selected_option=a.selected_option,
            free_text=a.free_text,
            answered_by=user,
            answered_at=datetime.now(timezone.utc),
            selected_options=a.selected_options,
            skipped=a.skipped,
            skip_reason=a.skip_reason,
        )
        for a in request.answers
    ]
    result = await service.respond_to_clarification(run_id, task_id, request_id, answers, user)
    # Re-fetch run after clarification response to get up-to-date status
    run = await repo.get(run_id)
    # If the run is paused, resume it before spawning the agent
    if run.status == RunStatus.PAUSED:
        run = await service.resume_run(run_id)
        logger.info(f"API: Resumed paused run {run_id} after clarification response")
    # Always re-spawn agent after a clarification response (run should now be ACTIVE)
    if run.agent_type is not None and not executor.is_running(run_id):
        spawned = executor.spawn_for_run(run_id, run.agent_type, run.agent_config)
        if spawned:
            logger.info(
                f"API: Re-spawned {run.agent_type.value} agent after clarification response for run {run_id}"
            )
    return TransitionResponse(
        success=result.success,
        new_status=result.new_status.value,
        error=result.error,
    )


@router.get("/{run_id}/pending-actions", response_model=list[PendingActionSchema])
async def get_pending_actions(
    run_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> list[PendingActionSchema]:
    """List all pending user actions for a run.

    Returns a list of all tasks that require user action (either clarification
    or approval), along with the necessary data to display and respond to them.

    Args:
        run_id: The run ID
        service: The workflow service

    Returns:
        List of pending actions
    """
    actions = await service.get_pending_actions(run_id)
    result: list[PendingActionSchema] = []

    for action in actions:
        action_schema = PendingActionSchema(
            task_id=action["task_id"],
            step_id=action["step_id"],
            action_type=action["action_type"],
            approval_prompt=action.get("approval_prompt"),
            summary_artifact=action.get("summary_artifact"),
            is_gate_approval=action.get("is_gate_approval", False),
        )

        # Add clarification request if present
        if "clarification_request" in action:
            clarif_dict = action["clarification_request"]
            action_schema.clarification_request = ClarificationRequestResponse(
                id=clarif_dict["id"],
                run_id=clarif_dict["run_id"],
                task_id=clarif_dict["task_id"],
                attempt_num=clarif_dict["attempt_num"],
                questions=[ClarificationQuestionSchema(**q) for q in clarif_dict["questions"]],
                created_at=clarif_dict["created_at"],
                responded_at=clarif_dict.get("responded_at"),
            )

        result.append(action_schema)

    return result
