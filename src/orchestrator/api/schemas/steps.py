"""Step API schemas."""

from datetime import datetime

from orchestrator.api.schemas.base import ApiModel


class HumanApprovalRequest(ApiModel):
    """Request to approve a human gate."""

    approved_by: str
    comment: str | None = None


class HumanApprovalResponse(ApiModel):
    """Response with human approval details."""

    approved_by: str
    approved_at: datetime
    comment: str | None = None


class StepResponse(ApiModel):
    """Response with step details after approval."""

    id: str
    config_id: str
    title: str
    completed: bool
    human_approval: HumanApprovalResponse | None = None
