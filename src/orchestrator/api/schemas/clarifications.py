"""Clarification API schemas."""

from datetime import datetime

from pydantic import BaseModel


class ClarificationQuestionSchema(BaseModel):
    """A question from the builder needing human input."""

    id: str
    question: str
    context: str
    options: list[str]


class ClarificationAnswerSchema(BaseModel):
    """Human's answer to a clarification question."""

    question_id: str
    selected_option: str | None = None
    free_text: str | None = None


class CreateClarificationRequest(BaseModel):
    """Request to create a clarification from the builder."""

    questions: list[ClarificationQuestionSchema]


class ClarificationRequestResponse(BaseModel):
    """Response containing a clarification request."""

    id: str
    run_id: str
    task_id: str
    attempt_num: int
    questions: list[ClarificationQuestionSchema]
    created_at: datetime
    responded_at: datetime | None = None


class RespondToClarificationRequest(BaseModel):
    """Request to submit answers to clarification questions."""

    answers: list[ClarificationAnswerSchema]


class PendingActionSchema(BaseModel):
    """A pending user action (clarification or approval)."""

    task_id: str
    step_id: str
    action_type: str  # "clarification" | "approval"
    clarification_request: ClarificationRequestResponse | None = None
    summary_artifact: str | None = None
    approval_prompt: str | None = None
