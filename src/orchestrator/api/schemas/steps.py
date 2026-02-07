"""Step API schemas."""

from datetime import datetime

from pydantic import BaseModel


class HumanApprovalRequest(BaseModel):
    """Request to approve a human gate."""

    approved_by: str
    comment: str | None = None


class HumanApprovalResponse(BaseModel):
    """Response with human approval details."""

    approved_by: str
    approved_at: datetime
    comment: str | None = None


class StepResponse(BaseModel):
    """Response with step details after approval."""

    id: str
    config_id: str
    title: str
    completed: bool
    human_approval: HumanApprovalResponse | None = None
