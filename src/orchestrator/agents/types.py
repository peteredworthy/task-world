"""Agent-related types for the orchestrator."""

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from orchestrator.config.enums import AgentType, ChecklistStatus

# Callback type aliases.
# run_id and task_id are captured in the closure by the caller,
# so callbacks only need req_id, status, and optional note.
ChecklistUpdateCallback = Callable[[str, ChecklistStatus, str | None], Awaitable[None]]
"""(req_id, status, note) -> None. run_id/task_id bound by caller."""

SubmitCallback = Callable[[], Awaitable[None]]
"""Called when agent submits work for verification."""

LogLineCallback = Callable[[list[str]], Awaitable[None]]

GradeCallback = Callable[[str, str, str | None], Awaitable[None]]
"""(req_id, grade, grade_reason) -> None. run_id/task_id bound by caller."""


class ExecutionMetrics(BaseModel):
    """Metrics collected during agent execution."""

    tokens_read: int = 0
    tokens_write: int = 0
    tokens_cache: int = 0
    duration_ms: int = 0


class ExecutionResult(BaseModel):
    """Result of agent execution."""

    success: bool
    error: str | None = None
    metrics: ExecutionMetrics = ExecutionMetrics()
    agent_metadata: dict[str, Any] = {}  # Runtime metadata like PID, container_id
    output_lines: list[str] = []


class ExecutionContext(BaseModel):
    """Context provided to an agent for execution."""

    run_id: str
    task_id: str
    working_dir: str
    prompt: str
    requirements: list[str]
    api_base_url: str | None = None
    auth_token: str | None = None
    end_commit: str | None = None  # For verifier: commit to checkout before verification


class AgentInfo(BaseModel):
    """Information about a concrete agent instance."""

    agent_type: AgentType
    name: str
    version: str | None = None


class AgentConfigField(BaseModel):
    """Schema for a single agent configuration field.

    Used by the frontend to render config forms per agent type.
    """

    name: str
    field_type: str  # "string", "number", "boolean", "select"
    required: bool = False
    default: Any = None
    description: str = ""
    options: list[str] | None = None  # for "select" type


class AgentOption(BaseModel):
    """An available agent option returned by the detector."""

    agent_type: AgentType
    name: str
    title: str = ""
    description: str = ""
    available: bool
    detail: str = ""
    install_hint: str = ""
    config_schema: list[AgentConfigField] = []
