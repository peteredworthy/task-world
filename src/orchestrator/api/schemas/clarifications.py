"""Clarification API schemas."""

from datetime import datetime
from typing import Literal

from pydantic import model_validator

from orchestrator.api.schemas.base import ApiModel


class ClarificationQuestionSchema(ApiModel):
    """A question from the builder needing human input."""

    id: str
    question: str
    context: str
    options: list[str] = []
    question_type: Literal["single_select", "multi_select", "free_text", "number"] = "single_select"
    allow_other: bool = True
    required: bool = True
    min: float | None = None
    max: float | None = None
    placeholder: str | None = None

    @model_validator(mode="after")
    def validate_options_for_type(self) -> "ClarificationQuestionSchema":
        if self.question_type in ("single_select", "multi_select"):
            if not self.options:
                raise ValueError(
                    f"'options' must be non-empty for question_type={self.question_type!r}"
                )
        else:  # free_text, number
            if self.options:
                raise ValueError(
                    f"'options' must be empty for question_type={self.question_type!r}"
                )
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("'min' must be <= 'max'")
        return self


class ClarificationAnswerSchema(ApiModel):
    """Human's answer to a clarification question."""

    question_id: str
    selected_option: str | None = None
    free_text: str | None = None
    selected_options: list[str] | None = None
    skipped: bool = False
    skip_reason: str | None = None


class CreateClarificationRequest(ApiModel):
    """Request to create a clarification from the builder."""

    questions: list[ClarificationQuestionSchema]


class ClarificationRequestResponse(ApiModel):
    """Response containing a clarification request."""

    id: str
    run_id: str
    task_id: str
    attempt_num: int
    questions: list[ClarificationQuestionSchema]
    created_at: datetime
    responded_at: datetime | None = None


class RespondToClarificationRequest(ApiModel):
    """Request to submit answers to clarification questions."""

    answers: list[ClarificationAnswerSchema]
    skipped: bool = False
    skip_reason: str | None = None


class ClarificationHistoryItem(ApiModel):
    """A single clarification round (request + optional response)."""

    request: ClarificationRequestResponse
    response: RespondToClarificationRequest | None = None


class ClarificationHistoryResponse(ApiModel):
    """All clarification rounds for a task."""

    items: list[ClarificationHistoryItem]


class PendingActionSchema(ApiModel):
    """A pending user action (clarification or approval)."""

    task_id: str
    step_id: str
    action_type: str  # "clarification" | "approval"
    clarification_request: ClarificationRequestResponse | None = None
    summary_artifact: str | None = None
    approval_prompt: str | None = None
    is_gate_approval: bool = False
