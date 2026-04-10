"""Activity feed API schemas."""

from datetime import datetime
from typing import Any

from orchestrator.api.schemas.base import ApiModel


class ActivityEvent(ApiModel):
    id: int
    event_type: str
    timestamp: datetime
    payload: dict[str, Any]
    task_title: str | None = None
    step_title: str | None = None


class ActivityResponse(ApiModel):
    run_id: str
    events: list[ActivityEvent]
    has_more: bool
