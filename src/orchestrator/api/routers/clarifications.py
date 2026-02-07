"""Clarification API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from orchestrator.api.deps import get_workflow_service
from orchestrator.api.schemas.clarifications import (
    ClarificationQuestionSchema,
    ClarificationRequestResponse,
    CreateClarificationRequest,
    PendingActionSchema,
    RespondToClarificationRequest,
)
from orchestrator.api.schemas.tasks import TransitionResponse
from orchestrator.workflow.clarifications import ClarificationAnswer, ClarificationQuestion
from orchestrator.workflow.service import WorkflowService

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
    questions = [
        ClarificationQuestion(
            id=q.id,
            question=q.question,
            context=q.context,
            options=q.options,
        )
        for q in request.questions
    ]
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
            )
            for q in result.questions
        ],
        created_at=result.created_at,
        responded_at=result.responded_at,
    )


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

    answers = [
        ClarificationAnswer(
            question_id=a.question_id,
            selected_option=a.selected_option,
            free_text=a.free_text,
            answered_by=user,
            answered_at=datetime.now(timezone.utc),
        )
        for a in request.answers
    ]
    result = await service.respond_to_clarification(run_id, task_id, request_id, answers, user)
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
