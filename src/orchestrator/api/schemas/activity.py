"""Activity feed API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ActivityEvent(BaseModel):
    id: int
    event_type: str
    timestamp: datetime
    payload: dict[str, Any]
    task_title: str | None = None
    step_title: str | None = None


class ActivityResponse(BaseModel):
    run_id: str
    events: list[ActivityEvent]
    has_more: bool
